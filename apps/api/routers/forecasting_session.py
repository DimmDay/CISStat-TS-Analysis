# apps/api/routers/forecasting_session.py
"""Session-контур этапа «Прогнозирование» (spec_forecasting2.md §6).

Роуты живут на том же префиксе /v1/session/modeling/*, что и Model Card
(та же сессия, та же cookie-аутентификация), но в отдельном модуле:
modeling_session.py уже несёт selection/comparison/card контур, а
прогнозирование -- собственный этап пайплайна со своей зоной ответственности.
URL-контракт спецификации (§6) сохранён 1:1.

Честность контура:
- прогноз потребляет Model Card и НЕ переоткрывает вопрос «какая модель
  лучше» (закрыт этапом Моделирования);
- точечный прогноз -- только через MODEL_EXECUTION_REGISTRY;
- freshness-gate: fingerprint ряда обязан совпадать с картой (lineage);
- ensemble-карты и модели вне level_forecast-scope -- честный 422;
- прогнозы -- артефакты сессии (modeling_artifacts["forecasts"], тот же
  паттерн, что model_cards) и инвалидируются вместе с картами;
- forecast_exported завершает этап (§10.5 -- derived-статус по прецеденту
  Моделирования, без отдельной кнопки «Готово»).
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO

from typing import Any, Optional
from uuid import uuid4

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from apps.api.final_fit import build_final_fit
from apps.api.forecasting import (
    DEFAULT_SIMULATION_TRAJECTORIES,
    ForecastingError,
    compute_forecast,
    future_date_labels,
)
from apps.api.forecasting_contract import (
    FORECASTING_ELIGIBLE_MODEL_IDS,
    interval_method_for_model,
    resolve_forecast_alpha,
)
from apps.api.model_execution import MODEL_EXECUTION_REGISTRY
from apps.api.schemas import (
    CardListResponse,
    ForecastCompareResponse,
    ForecastListResponse,
    ForecastRunResponse,
)
from apps.api.trace_events import make_trace_event
from apps.api.routers.modeling_session import (
    _action_context,
    _get_session,
    _prepare_state,
)
from app.core.passport import prepare_passport_series
from src.catalog.modeling_spec_loader import ModelingSpec

router = APIRouter()

_SPEC_CACHE: ModelingSpec | None = None
# Тот же repo-относительный контракт пути, что и routers/models.py
# (процесс API всегда стартует из корня репозитория).
_SPEC_YAML_PATH = "rules/modeling.yaml"


# ── Request-схемы (по конвенции роутеров) ─────────────────────────


class ForecastRequest(BaseModel):
    model_card_id: str
    horizon: Optional[int] = Field(None, ge=1)
    alpha: Optional[float] = Field(None, gt=0.0, lt=1.0)


class ForecastCompareRequest(BaseModel):
    forecast_ids: list[str] = Field(..., min_length=2, max_length=4)


class ForecastTraceRequest(BaseModel):
    event_type: str = "forecast_exported"
    format: str = "png"


def _forecasting_error(status_code: int, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=message)


def _load_spec() -> ModelingSpec:
    global _SPEC_CACHE
    if _SPEC_CACHE is not None:
        return _SPEC_CACHE
    _SPEC_CACHE = ModelingSpec.from_yaml(str(_SPEC_YAML_PATH))
    return _SPEC_CACHE


def _get_forecasts(session) -> dict[str, Any]:
    return session.modeling_artifacts.setdefault("forecasts", {})


def _card_summary(card_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    card = entry.get("card") or {}
    model_info = card.get("model_info") or {}
    training = card.get("training") or {}
    return {
        "card_id": card_id,
        "model_id": model_info.get("model_id"),
        "model_name": model_info.get("description") or model_info.get("model_id"),
        "selection_kind": model_info.get("selection_kind", "single"),
        "horizon": training.get("horizon"),
        "fingerprint": (card.get("data_summary") or {}).get("fingerprint"),
        "created_at": card.get("created_at"),
    }


def _load_card_entry(session, model_card_id: str) -> dict[str, Any]:
    cards = session.modeling_artifacts.get("model_cards") or {}
    entry = cards.get(model_card_id)
    if entry is None:
        raise _forecasting_error(404, "Model Card не найдена")
    return entry


def _validate_card_for_forecast(entry: dict[str, Any]) -> dict[str, Any]:
    card = entry.get("card") or {}
    model_info = card.get("model_info") or {}
    model_id = model_info.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise _forecasting_error(422, "Model Card не содержит model_id")
    if model_info.get("selection_kind") == "ensemble":
        raise _forecasting_error(
            422,
            "Прогноз ensemble-карты не поддержан в текущей версии: ансамбль "
            "не имеет единой статистической модели для финального рефита; "
            "фиктивное усреднение прогнозов членов запрещено. Используйте "
            "прогноз одной модели или сравнение прогнозов (§5.6)",
        )
    if model_id not in FORECASTING_ELIGIBLE_MODEL_IDS:
        raise _forecasting_error(
            422,
            f"Модель '{model_id}' недостижима через Model Card (сравнение "
            "моделей изолировано по objective cohort'а; var/vecm, garch/egarch "
            "и deepar образуют собственные cohort'ы). Прогноз multi-objective "
            "карт -- отдельная постановка",
        )
    return card


def _chain_method_list(session) -> tuple[str, list[str]]:
    """Методы цепочки target-препроцессинга текущей сессии (для консистент-
    гейта с картой)."""
    from apps.api.fold_preprocessing import _resolve_chain

    source_column, chain = _resolve_chain(
        session.preprocessing_transformations, session.target_column,
    )
    methods = [str(item.get("method") or "unknown") for item in chain]
    return source_column, methods


def _seasonal_period_of(context: dict[str, Any]) -> int:
    periods = (context.get("profile") or {}).get("seasonal_periods") or [1]
    return int(periods[0] or 1)


def _history_and_future(session, final_fit, horizon: int) -> list[str] | None:
    dates = prepare_passport_series(
        session.dataframe, final_fit.source_column, session.date_column, min_points=2,
    ).index
    return future_date_labels(pd.DatetimeIndex(dates), horizon)


def _append_event(session, run: dict[str, Any], event) -> None:
    run["trace_events"].append(event.to_dict())
    if event.event_type == "forecast_exported":
        # §10.5: экспорт -- естественное терминальное действие этапа
        # (derived-статус из данных, как tuning в Моделировании).
        session.stages["forecasting"] = "done"


def _expected_accuracy(card: dict[str, Any]) -> dict[str, Any]:
    metrics = dict((card.get("performance") or {}).get("backtest_metrics") or {})
    rmse = metrics.get("rmse")
    metrics.setdefault("mase", metrics.get("mase"))
    if rmse is not None:
        metrics["mse"] = round(float(rmse) ** 2, 12)
    for key in ("mae", "rmse", "mape", "mase", "smape", "rmsse"):
        metrics.setdefault(key, None)
    return metrics


# ── Генерация прогноза ────────────────────────────────────────────


@router.post("/forecast", response_model=ForecastRunResponse)
def create_forecast(
    payload: "ForecastRequest",
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    context = _action_context(session)
    _prepare_state(session, context)
    entry = _load_card_entry(session, payload.model_card_id)
    card = _validate_card_for_forecast(entry)
    model_id = card["model_info"]["model_id"]
    ci_method = interval_method_for_model(model_id)

    card_fingerprint = (card.get("data_summary") or {}).get("fingerprint")
    if card_fingerprint != context.get("fingerprint"):
        raise _forecasting_error(
            409,
            "Model Card устарела: ряд изменился после её создания "
            "(fingerprint расходится с modeling_entry). Сформируйте карту заново",
        )

    source_column, chain_methods = _chain_method_list(session)
    card_methods = list(((card.get("training") or {}).get("preprocessing") or {}).get("transformations") or [])
    if card_methods != chain_methods:
        raise _forecasting_error(
            409,
            "Цепочка target-препроцессинга расходится с Model Card "
            f"({card_methods} vs {chain_methods}); прогноз по изменившейся "
            "цепочке запрещён",
        )

    final_fit = build_final_fit(
        session.dataframe,
        target_column=session.target_column,
        date_column=session.date_column,
        transformations=session.preprocessing_transformations,
        scaling_recipe=session.preprocessing_scaling_recipe,
    )
    if not final_fit.reversible:
        raise _forecasting_error(
            422,
            "Цепочка target-препроцессинга содержит необратимое преобразование "
            "(например сглаживание): прогноз в исходной шкале невозможен; "
            "честный отказ вместо прогноза в transformed-шкале",
        )

    horizon = int(
        payload.horizon
        if payload.horizon is not None
        else (card.get("training") or {}).get("horizon") or 12
    )
    if horizon < 1:
        raise _forecasting_error(422, "Горизонт прогноза должен быть положительным")
    validated_horizon = (card.get("training") or {}).get("horizon")

    try:
        alpha_resolution = resolve_forecast_alpha(
            model_id, payload.alpha, dict(card.get("hyperparameters") or {}),
        )
    except ValueError as exc:
        raise _forecasting_error(422, str(exc)) from exc

    seasonal_period = _seasonal_period_of(context)
    future_labels = _history_and_future(session, final_fit, horizon)

    card_params = dict(card.get("hyperparameters") or {})
    oof_predictions = list((card.get("performance") or {}).get("oof_predictions") or [])

    try:
        computation = compute_forecast(
            model_id=model_id,
            horizon=horizon,
            alpha_resolution=alpha_resolution,
            final_fit=final_fit,
            seasonal_period=seasonal_period,
            params=card_params,
            registry=MODEL_EXECUTION_REGISTRY,
            history_values=final_fit.source_values,
            history_labels=final_fit.history_labels,
            future_labels=future_labels,
            oof_predictions=oof_predictions,
            validated_horizon=validated_horizon,
            simulation_trajectories=DEFAULT_SIMULATION_TRAJECTORIES,
        )
    except ForecastingError as exc:
        raise _forecasting_error(422, str(exc)) from exc
    except ValueError as exc:
        raise _forecasting_error(422, str(exc)) from exc

    checkpoint = context.get("checkpoint") or {}
    forecast_id = str(uuid4())
    run = {
        "forecast_id": forecast_id,
        "model_card_id": payload.model_card_id,
        "model_id": model_id,
        "model_name": card["model_info"].get("description") or model_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "horizon": horizon,
        "alpha": float(payload.alpha) if payload.alpha is not None else alpha_resolution.effective_alpha,
        "alpha_effective": computation.alpha_effective,
        "alpha_source": computation.alpha_source,
        "ci_method": computation.ci_method,
        "points": computation.points,
        "history": {
            "labels": list(final_fit.history_labels),
            "values": [float(value) for value in final_fit.source_values],
            "source_column": final_fit.source_column,
        },
        "expected_accuracy": _expected_accuracy(card),
        "prediction_interval_coverage": computation.coverage,
        "warnings": list(computation.warnings),
        "trace_events": [],
        "lineage": {
            "fingerprint": context.get("fingerprint"),
            "checkpoint_id": checkpoint.get("checkpoint_id"),
            "cohort_id": (card.get("training") or {}).get("cohort_id"),
            "preprocessing_signature": final_fit.signature,
            "fit_policy": final_fit.summary.get("fit_policy"),
            "seasonal_period": seasonal_period,
            "params": dict(card_params),
            "n_history": len(final_fit.source_values),
            "interval_provenance": computation.metadata.get("interval_provenance"),
            "parity_gate": computation.metadata.get("parity_gate"),
            "adapter_warnings": computation.metadata.get("adapter_warnings"),
        },
        "sensitivity": None,
    }
    event = make_trace_event(
        "forecast_generated",
        model_card_id=payload.model_card_id,
        forecast_id=forecast_id,
        model_id=model_id,
        horizon=horizon,
        alpha=computation.alpha_effective,
        ci_method=computation.ci_method,
    )
    _append_event(session, run, event)
    _get_forecasts(session)[forecast_id] = run
    if session.stages.get("forecasting") != "done":
        session.stages["forecasting"] = "in_progress"
    session.touch()
    store.save(session)
    return run


# ── История и чтение ──────────────────────────────────────────────


@router.get("/forecast", response_model=ForecastListResponse)
def list_forecasts(request: Request, response: Response):
    _store, session = _get_session(request, response)
    forecasts = list(_get_forecasts(session).values())
    forecasts.sort(key=lambda run: run.get("generated_at") or "")
    return {"forecasts": forecasts}


@router.get("/forecast/{forecast_id}", response_model=ForecastRunResponse)
def get_forecast(forecast_id: str, request: Request, response: Response):
    _store, session = _get_session(request, response)
    run = _get_forecasts(session).get(forecast_id)
    if run is None:
        raise _forecasting_error(404, "Прогноз не найден")
    return run


# ── Экспорт (§5.5) ────────────────────────────────────────────────


def _forecast_csv(run: dict[str, Any]) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["date", "actual", "forecast", "ci_lower", "ci_upper"])
    history = run.get("history") or {}
    for label, value in zip(
        history.get("labels") or [], history.get("values") or [], strict=True,
    ):
        writer.writerow([label, repr(float(value)), "", "", ""])
    for point in run.get("points") or []:
        writer.writerow([
            point["date"], "",
            repr(float(point["value"])),
            repr(float(point["ci_lower"])),
            repr(float(point["ci_upper"])),
        ])
    return buffer.getvalue()


def _record_export(request: Request, response: Response, forecast_id: str, fmt: str) -> dict[str, Any]:
    store, session = _get_session(request, response)
    run = _get_forecasts(session).get(forecast_id)
    if run is None:
        raise _forecasting_error(404, "Прогноз не найден")
    event = make_trace_event(
        "forecast_exported", forecast_id=forecast_id, format=fmt,
    )
    _append_event(session, run, event)
    session.touch()
    store.save(session)
    return run


@router.get("/forecast/{forecast_id}/export.csv")
def export_forecast_csv(forecast_id: str, request: Request, response: Response):
    run = _record_export(request, response, forecast_id, "csv")
    content = _forecast_csv(run)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="forecast_{forecast_id[:8]}.csv"',
        },
    )


@router.get("/forecast/{forecast_id}/export.json", response_model=ForecastRunResponse)
def export_forecast_json(forecast_id: str, request: Request, response: Response):
    # Самодостаточный файл (§5.5): ForecastRun целиком -- карта-ссылка,
    # метрики, параметры, история; интерпретация не требует доступа к сессии.
    return _record_export(request, response, forecast_id, "json")


@router.post("/forecast/{forecast_id}/trace", response_model=ForecastRunResponse)
def record_client_export_event(
    forecast_id: str,
    payload: "ForecastTraceRequest",
    request: Request,
    response: Response,
):
    """Клиентский экспорт (PNG) не требует backend-рендеринга (§5.5), но
    событие трассы обязано попасть в общий журнал этапа."""
    if payload.format not in {"png", "pdf"}:
        raise _forecasting_error(422, "Формат клиентского экспорта: png|pdf")
    return _record_export(request, response, forecast_id, payload.format)


# ── Сравнение прогнозов (§5.6) ────────────────────────────────────


@router.post("/forecast/compare", response_model=ForecastCompareResponse)
def compare_forecasts(
    payload: "ForecastCompareRequest",
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    forecasts = _get_forecasts(session)
    if len(payload.forecast_ids) != len(set(payload.forecast_ids)):
        raise _forecasting_error(422, "forecast_ids содержит дубликаты")
    if len(payload.forecast_ids) < 2:
        raise _forecasting_error(422, "Для сравнения нужно минимум два прогноза")
    missing = [fid for fid in payload.forecast_ids if fid not in forecasts]
    if missing:
        raise _forecasting_error(404, f"Прогнозы не найдены: {missing}")
    # §5.6: сравнение НЕ вводит новое ранжирование -- наложение уже
    # построенных артефактов; каждое участие фиксируется событием трассы.
    event = make_trace_event(
        "forecast_compared",
        forecast_ids=list(payload.forecast_ids),
        model_card_ids=sorted({forecasts[fid]["model_card_id"] for fid in payload.forecast_ids}),
    )
    for forecast_id in payload.forecast_ids:
        _append_event(session, forecasts[forecast_id], event)
    session.touch()
    store.save(session)
    ordered = [forecasts[fid] for fid in payload.forecast_ids]
    return {"forecasts": ordered}


# ── Чувствительность (§5.7) ───────────────────────────────────────

MAX_SENSITIVITY_COMBOS = 8


def _param_space_corners(param_space: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Границы уже исследованного тюнингом пространства (§5.7): по каждой оси
    первый/последний элемент декларированного списка значений (без сортировки
    -- значения могут быть категориальными); декартово произведение углов,
    дедуплицированное, с потолком MAX_SENSITIVITY_COMBOS."""
    axes: list[list[Any]] = []
    for values in param_space.values():
        unique = list(dict.fromkeys(values))
        picks = [unique[0], unique[-1]] if len(unique) > 1 else [unique[0]]
        axes.append(picks)
    combos: list[dict[str, Any]] = []

    def _walk(index: int, current: dict[str, Any]) -> None:
        if index == len(axes):
            if current not in combos:
                combos.append(dict(current))
            return
        for value in axes[index]:
            key = list(param_space.keys())[index]
            if len(combos) >= MAX_SENSITIVITY_COMBOS and current:
                return
            current[key] = value
            _walk(index + 1, current)
            current.pop(key, None)

    _walk(0, {})
    return combos


@router.post("/forecast/{forecast_id}/sensitivity", response_model=ForecastRunResponse)
def forecast_sensitivity(forecast_id: str, request: Request, response: Response):
    store, session = _get_session(request, response)
    context = _action_context(session)
    _prepare_state(session, context)
    run = _get_forecasts(session).get(forecast_id)
    if run is None:
        raise _forecasting_error(404, "Прогноз не найден")

    card_entry = (session.modeling_artifacts.get("model_cards") or {}).get(
        run["model_card_id"],
    )
    if card_entry is None:
        raise _forecasting_error(
            409, "Model Card, на которую ссылается прогноз, инвалидирована"
        )
    card = card_entry["card"]
    model_id = run["model_id"]
    spec = _load_spec()
    spec_model = spec.get_model(model_id)
    param_space = (spec_model.param_space if spec_model else None) or {}
    if not param_space:
        raise _forecasting_error(
            422,
            f"Модель '{model_id}' имеет пустой param_space: веер чувствительности "
            "строить не по чему (§5.7 -- варьирование только в границах уже "
            "исследованного пространства тюнинга)",
        )

    combos = _param_space_corners(param_space)
    if not combos:
        raise _forecasting_error(422, "Пространство параметров вырождено")

    final_fit = build_final_fit(
        session.dataframe,
        target_column=session.target_column,
        date_column=session.date_column,
        transformations=session.preprocessing_transformations,
        scaling_recipe=session.preprocessing_scaling_recipe,
    )
    if not final_fit.reversible:
        raise _forecasting_error(
            422, "Цепочка target-препроцессинга необратима: веер в исходной шкале невозможен",
        )

    seasonal_period = _seasonal_period_of(context)
    horizon = int(run["horizon"])
    future_labels = _history_and_future(session, final_fit, horizon)
    card_params = dict(card.get("hyperparameters") or {})

    fan_combos: list[dict[str, Any]] = []
    warnings: list[str] = []
    definition = MODEL_EXECUTION_REGISTRY.describe(model_id)
    if (definition or {}).get("dependency_group") == "neural":
        warnings.append(
            "Веер чувствительности исполняет реальные фиты нейро-модели "
            f"({len(combos)} комбинаций границ param_space): операция может "
            "занять заметное время"
        )
    for combo in combos:
        combo_params = {**card_params, **combo}
        try:
            result = MODEL_EXECUTION_REGISTRY.execute(
                model_id,
                _sensitivity_request(
                    final_fit, horizon, seasonal_period, combo_params,
                    future_labels or (),
                ),
            )
            point_orig = final_fit.restore(np.asarray(result.forecast, dtype=float))
        except (ForecastingError, ValueError) as exc:
            raise _forecasting_error(422, f"Вариант {combo}: {exc}") from exc
        dates = (
            list(future_labels)
            if future_labels is not None
            else [str(len(final_fit.source_values) + step) for step in range(1, horizon + 1)]
        )
        fan_combos.append({
            "params": dict(combo),
            "points": [
                {
                    "step": step,
                    "date": dates[step - 1],
                    "value": float(point_orig[step - 1]),
                }
                for step in range(1, horizon + 1)
            ],
        })

    run["sensitivity"] = {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "varied_axes": list(param_space.keys()),
        "combos": fan_combos,
        "truncated": len(fan_combos) >= MAX_SENSITIVITY_COMBOS,
        "warnings": warnings,
    }
    event = make_trace_event(
        "forecast_sensitivity_computed",
        forecast_id=forecast_id,
        varied_axes=list(param_space.keys()),
        n_combos=len(fan_combos),
    )
    _append_event(session, run, event)
    session.touch()
    store.save(session)
    return run


def _sensitivity_request(
    final_fit, horizon: int, seasonal_period: int, params: dict[str, Any],
    future_timestamps: tuple[str, ...],
):
    from apps.api.model_execution import ModelExecutionRequest

    return ModelExecutionRequest(
        target=[float(value) for value in final_fit.model_train],
        horizon=int(horizon),
        seasonal_period=int(seasonal_period),
        params=dict(params),
        train_timestamps=tuple(final_fit.model_train_labels),
        future_timestamps=tuple(future_timestamps),
        random_state=42,
    )
