"""Session-backed, traceable Modeling workflow for both web shells."""
from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal, Optional
from uuid import uuid4

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.core.passport import prepare_passport_series
from apps.api.backtesting import (
    BacktestExecutionError,
    build_backtest_plan,
    run_backtest_plan,
    validate_target_preprocessing,
)
from apps.api.model_readiness import PRODUCTION_BACKTEST_MODEL_IDS
from apps.api.modeling_workflow import build_modeling_context
from apps.api.routers.diagnostics import _diagnose
from apps.api.routers.models import (
    _compute_candidates,
    _execute_tune,
    _resolve_model_info,
    _run_backtest_with_series,
)
from apps.api.schemas import (
    BacktestResponse,
    CVConfig,
    CandidatesRequest,
    CandidatesResponse,
    DataProfileRequest,
    TuneResponse,
)
from apps.api.session_store import get_or_create_session_id, get_session_store


router = APIRouter()


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


class ModelingCandidatesRequest(BaseModel):
    min_level: str = "CONDITIONALLY_APPLICABLE"
    strategy: Literal["expanding", "sliding", "single"] = "expanding"
    horizon: int = Field(12, ge=1, le=10000)
    n_splits: int = Field(5, ge=1, le=20)
    gap: int = Field(0, ge=0, le=10000)
    train_window: int = Field(60, ge=2, le=100000)


class ModelingBacktestRequest(BaseModel):
    model_id: str
    train_ratio: Optional[float] = Field(None, ge=0.5, le=0.95)


class ModelingTuneRequest(BaseModel):
    model_id: str
    cv: Optional[CVConfig] = None
    max_trials: Optional[int] = Field(None, ge=1)
    metric: Literal["mae", "rmse", "mape", "mase", "weighted_score"] = "rmse"
    random_state: int = 42


class ModelingDiagnosticsRequest(BaseModel):
    model_id: str
    alpha: float = Field(0.05, gt=0, lt=1)
    ljung_box_lags: Optional[int] = Field(None, ge=1, le=50)
    arch_lags: Optional[int] = Field(None, ge=1, le=20)


class ModelingCompareRequest(BaseModel):
    model_ids: list[str] = Field(default_factory=list)


class ModelingSelectRequest(BaseModel):
    model_id: str
    acknowledge_baseline_risk: bool = False


class ModelingCardRequest(BaseModel):
    notes: Optional[str] = Field(None, max_length=2000)


def _context(session, *, require_ready: bool = True, **kwargs) -> dict[str, Any]:
    try:
        context = build_modeling_context(session, **kwargs)
        if require_ready and not context.get("ready"):
            raise ValueError("Modeling заблокирован критическими проверками; устраните причины из traceability")
        return context
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _validation_contract(context: dict[str, Any]) -> dict[str, Any]:
    return {
        key: context["validation_strategy"].get(key)
        for key in (
            "column", "applicable", "reason",
            "strategy", "horizon", "n_splits", "gap", "train_window",
            "initial_train_size", "effective_splits", "requested_splits",
            "n_observations", "folds", "order_source", "order_column",
            "frequency", "warnings",
        )
    }


def _action_context(session) -> dict[str, Any]:
    """Rebuild readiness using the validation contract chosen for this run."""
    saved = session.modeling_artifacts.get("validation_strategy", {})
    kwargs = {
        "horizon": saved.get("horizon", 12),
        "strategy": saved.get("strategy", "expanding"),
        "n_splits": saved.get("n_splits", 5),
        "gap": saved.get("gap", 0),
        "train_window": saved.get("train_window", 60),
    }
    return _context(session, **{key: value for key, value in kwargs.items() if value is not None})


def _prepare_state(session, context: dict[str, Any], *, refresh_contract: bool = False) -> None:
    fingerprint = context["fingerprint"]
    if session.modeling_artifacts.get("source_fingerprint") != fingerprint:
        session.reset_modeling()
        session.modeling_artifacts = {
            "source_fingerprint": fingerprint,
            "source_checkpoint": context["checkpoint"],
            "profile": context["profile"],
            "validation_strategy": _validation_contract(context),
            "traceability_summary": context["traceability"]["summary"],
            "backtests": {}, "tuning": {}, "diagnostics": {}, "model_cards": {},
        }
        for stage in ("problem_definition", "data_structure", "constraint_mapping"):
            session.modeling_pipeline[stage] = "done"
        session.modeling_pipeline["candidate_generation"] = "in_progress"
    elif refresh_contract:
        session.modeling_artifacts["validation_strategy"] = _validation_contract(context)
        session.modeling_artifacts["profile"] = context["profile"]
        session.modeling_artifacts["runnable_shortlist"] = context["runnable_shortlist"]


def _get_session(request: Request, response: Response):
    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    return store, store.get_or_create(session_id)


@router.get("/context")
def get_modeling_context(
    request: Request,
    response: Response,
    horizon: Optional[int] = Query(None, ge=1, le=10000),
    strategy: Optional[Literal["expanding", "sliding", "single"]] = None,
    n_splits: Optional[int] = Query(None, ge=1, le=20),
    gap: Optional[int] = Query(None, ge=0, le=10000),
    train_window: Optional[int] = Query(None, ge=2, le=100000),
):
    store, session = _get_session(request, response)
    saved = session.modeling_artifacts.get("validation_strategy") or session.eda_validation_strategy
    if saved.get("column") not in {None, session.target_column}:
        saved = {}
    context = _context(
        session,
        horizon=horizon if horizon is not None else int(saved.get("horizon") or 12),
        strategy=strategy or saved.get("strategy") or "expanding",
        n_splits=n_splits if n_splits is not None else int(
            saved.get("requested_splits") or saved.get("n_splits") or 5
        ),
        gap=gap if gap is not None else int(saved.get("gap") or 0),
        train_window=(
            train_window if train_window is not None else int(saved.get("train_window") or 60)
        ),
        require_ready=False,
    )
    _prepare_state(session, context, refresh_contract=True)
    store.save(session)
    return context


@router.get("/state")
def get_modeling_state(request: Request, response: Response):
    store, session = _get_session(request, response)
    stale = False
    try:
        context = _context(session, require_ready=False)
        _prepare_state(session, context)
        store.save(session)
    except HTTPException:
        stale = bool(session.modeling_artifacts)
    return {
        "pipeline": session.modeling_pipeline,
        "artifacts": session.modeling_artifacts,
        "stale": stale,
    }


@router.post("/candidates", response_model=CandidatesResponse)
def generate_modeling_candidates(
    payload: ModelingCandidatesRequest,
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    context = _context(
        session, strategy=payload.strategy, horizon=payload.horizon,
        n_splits=payload.n_splits, gap=payload.gap,
        train_window=payload.train_window,
    )
    _prepare_state(session, context, refresh_contract=True)
    result = _compute_candidates(CandidatesRequest(
        profile=DataProfileRequest(**context["profile"]),
        min_level=payload.min_level,
    ))
    runnable = set(context["runnable_shortlist"])
    matrix_models = {
        item["model_id"]: item for item in context["model_matrix"].get("models", [])
    }
    # Ограничения EDA применяются ко всему каталогу, иначе реализованная, но
    # противопоказанная модель могла бы получить кнопку запуска в режиме all.
    for candidate in result.catalog:
        if candidate.platform_status != "ready" or candidate.model_id in runnable:
            continue
        matrix_item = matrix_models.get(candidate.model_id, {})
        reasons = matrix_item.get("blocking_reasons") or matrix_item.get("cautions") or []
        candidate.available_actions = []
        candidate.blocking_reason = (
            "; ".join(str(reason) for reason in reasons)
            or "Модель реализована, но заблокирована матрицей применимости для текущего ряда."
        )
    catalog_by_id = {candidate.model_id: candidate for candidate in result.catalog}
    result.candidates = [catalog_by_id[candidate.model_id] for candidate in result.candidates]
    result.statistics.runnable_candidates = sum(
        "backtest" in candidate.available_actions for candidate in result.candidates
    )
    result.statistics.catalog_only_candidates = sum(
        candidate.platform_status == "catalog_only" for candidate in result.catalog
    )
    result.statistics.blocked_candidates = sum(
        candidate.platform_status == "ready" and not candidate.available_actions
        for candidate in result.catalog
    )
    session.modeling_artifacts["candidates"] = result.model_dump(mode="json")
    session.modeling_artifacts["runnable_shortlist"] = context["runnable_shortlist"]
    session.modeling_pipeline["candidate_generation"] = "done"
    session.modeling_pipeline["baseline_estimation"] = "in_progress"
    session.touch()
    store.save(session)
    return result


@router.post("/backtest", response_model=BacktestResponse)
def run_modeling_backtest(
    payload: ModelingBacktestRequest,
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    context = _action_context(session)
    _prepare_state(session, context)
    if payload.model_id not in PRODUCTION_BACKTEST_MODEL_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"Production backtest для модели '{payload.model_id}' не реализован; фиктивные метрики запрещены",
        )
    runnable = set(session.modeling_artifacts.get("runnable_shortlist") or context.get("runnable_shortlist", []))
    if payload.model_id not in runnable:
        raise HTTPException(
            status_code=422,
            detail=f"Модель '{payload.model_id}' заблокирована матрицей применимости для текущего ряда",
        )
    if payload.train_ratio is not None:
        raise HTTPException(
            status_code=422,
            detail="Ручной train_ratio запрещён: backtest исполняет точные folds из EDA validation strategy",
        )
    series = prepare_passport_series(session.dataframe, session.target_column, session.date_column)
    values = series.to_numpy(dtype=float).tolist()
    period = (session.modeling_artifacts.get("profile", context["profile"]).get("seasonal_periods") or [1])[0]
    model_info = _resolve_model_info(payload.model_id)
    validation = session.modeling_artifacts["validation_strategy"]
    tuned = session.modeling_artifacts.get("tuning", {}).get(payload.model_id, {})
    try:
        preprocessing_warnings = validate_target_preprocessing(
            session.preprocessing_transformations, session.target_column,
        )
        plan = build_backtest_plan(
            validation, n_observations=len(values),
            fingerprint=context["fingerprint"], target_column=session.target_column,
            seasonal_period=int(period),
        )
        result = BacktestResponse(**run_backtest_plan(
            model_id=payload.model_id, model_name=model_info[0], family_id=model_info[1],
            series=values, labels=[value.isoformat() for value in series.index],
            plan=plan, seasonal_period=int(period), params=tuned.get("best_params", {}),
            preprocessing_warnings=preprocessing_warnings,
        ))
    except BacktestExecutionError as exc:
        session.modeling_artifacts.setdefault("backtest_failures", {})[payload.model_id] = {
            "model_id": payload.model_id, "cohort_id": getattr(locals().get("plan"), "cohort_id", None),
            "error": str(exc), "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        session.touch()
        store.save(session)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    session.modeling_artifacts.setdefault("backtests", {})[payload.model_id] = result.model_dump(mode="json")
    if model_info[1] == "baselines":
        session.modeling_pipeline["baseline_estimation"] = "done"
    session.modeling_pipeline["backtest"] = "done"
    session.modeling_pipeline["tuning"] = "in_progress"
    session.touch()
    store.save(session)
    return result


@router.post("/tune", response_model=TuneResponse)
def tune_modeling_candidate(
    payload: ModelingTuneRequest,
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    context = _action_context(session)
    _prepare_state(session, context)
    series = prepare_passport_series(session.dataframe, session.target_column, session.date_column)
    from apps.api.routers.models import _get_spec
    validation = session.modeling_artifacts["validation_strategy"]
    if payload.cv is None and validation.get("strategy") == "sliding":
        raise HTTPException(
            status_code=422,
            detail="Тюнинг sliding-window пока не реализован; выберите expanding или передайте явную CV config",
        )
    cv_config = payload.cv or CVConfig(
        n_splits=int(validation.get("n_splits") or 1),
        test_size=int(validation.get("horizon") or 1),
        min_train_size=int(validation.get("initial_train_size") or 1),
        step=int(validation.get("horizon") or 1),
        gap=int(validation.get("gap") or 0),
    )
    result = _execute_tune(
        spec=_get_spec(), model_id=payload.model_id,
        series=series.to_numpy(dtype=float).tolist(), cv_config=cv_config,
        max_trials=payload.max_trials, metric=payload.metric,
        random_state=payload.random_state,
    )
    session.modeling_artifacts.setdefault("tuning", {})[payload.model_id] = result.model_dump(mode="json")
    session.modeling_pipeline["tuning"] = "done"
    session.modeling_pipeline["diagnostics"] = "in_progress"
    session.touch()
    store.save(session)
    return result


@router.post("/diagnostics")
def diagnose_modeling_candidate(
    payload: ModelingDiagnosticsRequest,
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    context = _action_context(session)
    _prepare_state(session, context)
    backtest = session.modeling_artifacts.get("backtests", {}).get(payload.model_id)
    if not backtest:
        raise HTTPException(status_code=409, detail="Сначала выполните backtest модели на EDA folds")
    points = backtest.get("oof_predictions") or []
    if not points:
        raise HTTPException(status_code=409, detail="Backtest не содержит OOF-остатков для диагностики")
    residuals = np.asarray([point["residual"] for point in points], dtype=float)
    try:
        diagnostics = _diagnose(residuals, payload.alpha, payload.ljung_box_lags, payload.arch_lags)
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = {
        "model_id": payload.model_id, "target_column": session.target_column,
        "n_observations": int(residuals.size), "residuals_count": int(residuals.size),
        "alpha": payload.alpha,
        "params_source": "backtest", "residuals_source": "backtest_oof",
        "cohort_id": backtest.get("cohort_id"),
        "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
    }
    session.modeling_artifacts.setdefault("diagnostics", {})[payload.model_id] = result
    session.modeling_pipeline["diagnostics"] = "done"
    session.modeling_pipeline["comparison"] = "in_progress"
    session.touch()
    store.save(session)
    return result


def _minmax(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi - lo <= np.finfo(float).eps:
        return [0.0 for _ in values]
    return [(value - lo) / (hi - lo) for value in values]


@router.post("/compare")
def compare_modeling_candidates(
    payload: ModelingCompareRequest,
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    context = _action_context(session)
    _prepare_state(session, context)
    saved = session.modeling_artifacts.get("backtests", {})
    model_ids = payload.model_ids or list(saved)
    results = [saved[item] for item in model_ids if item in saved]
    if len(results) < 2:
        raise HTTPException(status_code=409, detail="Для сравнения нужны минимум два сопоставимых бэктеста")
    incomplete = [item["model_id"] for item in results if item.get("status") != "success"]
    if incomplete:
        raise HTTPException(status_code=409, detail=f"Неполные backtest нельзя сравнивать: {incomplete}")
    cohorts = {item.get("cohort_id") for item in results}
    if None in cohorts or len(cohorts) != 1:
        raise HTTPException(status_code=409, detail="Бэктесты рассчитаны на разных разбиениях и несопоставимы")

    metric_ids = ["mae", "rmse", "mape", "mase"]
    weights = {"mae": 0.35, "rmse": 0.25, "mape": 0.20, "mase": 0.20}
    warnings = []
    if any(item["metrics"].get("mape") is None for item in results):
        metric_ids.remove("mape")
        warnings.append("MAPE исключена из ranking: метрика определена не для всех моделей cohort.")
    if any(item["metrics"].get("mase") is None for item in results):
        metric_ids.remove("mase")
        warnings.append("MASE исключена из ranking: seasonal train scale не определён для всех folds.")
    weight_sum = sum(weights[item] for item in metric_ids)
    normalized = {
        metric: _minmax([float(item["metrics"][metric]) for item in results])
        for metric in metric_ids
    }
    ranking = []
    for index, item in enumerate(results):
        score = sum(weights[metric] / weight_sum * normalized[metric][index] for metric in metric_ids)
        raw_mase = item["metrics"].get("mase")
        mase = float(raw_mase) if raw_mase is not None else None
        baseline_eligible = mase is not None and mase <= 1.05
        ranking.append({
            "model_id": item["model_id"], "model_name": item["model_name"],
            "family_id": item["family_id"], "metrics": item["metrics"],
            "weighted_score": round(score, 6),
            "baseline_eligible": baseline_eligible,
            "baseline_note": (
                "лучше/сопоставима с сезонным Naive scale" if baseline_eligible
                else "MASE не определена либо выше 1.05; допустим только осознанный override"
            ),
        })
    ranking.sort(key=lambda item: (
        item["weighted_score"],
        item["metrics"].get("mase") if item["metrics"].get("mase") is not None else float("inf"),
        item["metrics"]["rmse"],
    ))
    for rank, item in enumerate(ranking, 1):
        item["rank"] = rank
    if any(not item["baseline_eligible"] for item in ranking):
        warnings.append("Модели с MASE > 1.05 помечены риском, но не скрыты из аудиторской таблицы.")
    result = {
        "comparison_id": str(uuid4()), "fingerprint": context["fingerprint"],
        "cohort_id": next(iter(cohorts)),
        "normalization": "min_max_within_comparable_pool", "metric_weights": {
            metric: round(weights[metric] / weight_sum, 6) for metric in metric_ids
        },
        "ranking": ranking, "warnings": warnings,
    }
    session.modeling_artifacts["comparison"] = result
    session.modeling_pipeline["comparison"] = "done"
    session.modeling_pipeline["selection"] = "in_progress"
    session.touch()
    store.save(session)
    return result


@router.post("/select")
def select_modeling_candidate(
    payload: ModelingSelectRequest,
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    _action_context(session)
    comparison = session.modeling_artifacts.get("comparison")
    if not comparison:
        raise HTTPException(status_code=409, detail="Сначала выполните сравнение моделей")
    candidate = next((item for item in comparison["ranking"] if item["model_id"] == payload.model_id), None)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Модель отсутствует в текущем сравнении")
    if not candidate["baseline_eligible"] and not payload.acknowledge_baseline_risk:
        raise HTTPException(status_code=409, detail="Подтвердите выбор модели, уступающей Naive")
    top = comparison["ranking"][:3]
    close_scores = len(top) >= 2 and top[1]["weighted_score"] - top[0]["weighted_score"] <= 0.05
    enough_strong_models = sum(
        item["metrics"].get("mase") is not None and item["metrics"]["mase"] < 1
        for item in top
    ) >= 2
    ensemble_candidate = close_scores and enough_strong_models
    result = {
        "selected_model_id": payload.model_id,
        "selected_at": datetime.now(timezone.utc).isoformat(),
        "user_override": payload.model_id != comparison["ranking"][0]["model_id"],
        "baseline_risk_acknowledged": payload.acknowledge_baseline_risk,
        "ensemble_candidate": ensemble_candidate,
        "ensemble_recommended": False,
        "ensemble_note": (
            "Выполнены условия MASE и близости score, но корреляция out-of-fold ошибок не сохранена; "
            "автоматический ансамбль методологически недопустим."
            if ensemble_candidate else None
        ),
    }
    session.modeling_artifacts["selection"] = result
    session.modeling_pipeline["selection"] = "done"
    session.modeling_pipeline["model_card"] = "in_progress"
    session.touch()
    store.save(session)
    return result


@router.post("/card")
def create_model_card(
    payload: ModelingCardRequest,
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    context = _action_context(session)
    _prepare_state(session, context)
    selection = session.modeling_artifacts.get("selection")
    comparison = session.modeling_artifacts.get("comparison")
    if not selection or not comparison:
        raise HTTPException(status_code=409, detail="Сначала сравните и выберите модель")
    model_id = selection["selected_model_id"]
    ranked = next(item for item in comparison["ranking"] if item["model_id"] == model_id)
    backtest = session.modeling_artifacts["backtests"][model_id]
    tuning = session.modeling_artifacts.get("tuning", {}).get(model_id)
    diagnostics = session.modeling_artifacts.get("diagnostics", {}).get(model_id)
    candidate = next((item for item in session.modeling_artifacts.get("candidates", {}).get("candidates", []) if item["model_id"] == model_id), None)
    series = prepare_passport_series(session.dataframe, session.target_column, session.date_column)
    folds = backtest.get("folds") or []
    first_fold = folds[0] if folds else None
    last_fold = folds[-1] if folds else None
    diagnostics_items = (diagnostics or {}).get("diagnostics", [])
    passed = [item["test"] for item in diagnostics_items if item["applicable"] and item["status"] == "pass"]
    failed = [item for item in diagnostics_items if item["applicable"] and item["status"] in {"warning", "fail"}]
    limitations = ["Оценка основана на историческом временном разбиении; будущий режим может отличаться."]
    if not diagnostics:
        limitations.append("Диагностика остатков для выбранной модели не зафиксирована.")
    limitations.append("Prediction intervals и их coverage ещё не реализованы в production backtest.")
    card_id = str(uuid4())
    card = {
        "model_info": {
            "model_id": model_id, "family": ranked["family_id"],
            "applicability_level": (candidate or {}).get("level", "CONDITIONALLY_APPLICABLE"),
            "description": (candidate or {}).get("message", ranked["model_name"]),
            "version": "1.0", "library_versions": {
                "numpy": _package_version("numpy"),
                "pandas": _package_version("pandas"),
                "statsmodels": _package_version("statsmodels"),
            },
        },
        "data_summary": {
            "n_observations": len(series), "n_series": context["profile"]["n_series"],
            "frequency": context["profile"]["frequency"], "domain": context["profile"]["domain"],
            "target_column": session.target_column, "date_column": session.date_column,
            "source_checkpoint": context["checkpoint"]["checkpoint_id"],
            "fingerprint": context["fingerprint"],
        },
        "hyperparameters": (tuning or {}).get("best_params", {}),
        "training": {
            "train_start": (
                first_fold.get("train_start_label") if first_fold else str(series.index[0])
            ),
            "train_end": (
                last_fold.get("train_end_label") if last_fold
                else str(series.index[backtest["n_train"] - 1])
            ),
            "validation_method": backtest.get("strategy", context["validation_strategy"]["strategy"]),
            "n_folds": backtest.get("n_folds", context["validation_strategy"]["n_splits"]),
            "horizon": backtest.get("horizon"),
            "gap": backtest.get("gap", 0),
            "cohort_id": backtest.get("cohort_id"),
            "folds": folds,
            "training_time_seconds": round(backtest["duration_ms"] / 1000, 6),
            "gpu_used": False,
        },
        "performance": {
            "backtest_metrics": backtest["metrics"],
            "residuals_source": "backtest_oof",
            "oof_predictions": backtest.get("oof_predictions", []),
            "cv_metrics": (tuning or {}).get("best_metrics") or {},
            "baseline_comparison": {
                "mase": ranked["metrics"]["mase"],
                "threshold": 1.05,
                "eligible": ranked["baseline_eligible"],
                "note": ranked["baseline_note"],
            },
            "prediction_interval_coverage": None, "winkler_score": None,
        },
        "diagnostics": {"passed": passed, "failed": failed, "report": diagnostics},
        "limitations": limitations,
        "recommendations": ["Переобучать preprocessing и модель внутри каждого train fold.", "Мониторить ошибку и дрейф после ввода прогноза в эксплуатацию."],
        "feature_importance": None,
        "traceability": {
            "total_sources": context["traceability"]["summary"]["total"],
            "summary": context["traceability"]["summary"],
            "checkpoint_id": context["checkpoint"]["checkpoint_id"],
        },
        "notes": payload.notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = {"card_id": card_id, "card": card}
    session.modeling_artifacts.setdefault("model_cards", {})[card_id] = result
    session.modeling_pipeline["model_card"] = "done"
    session.set_stage("modeling", "done")
    session.touch()
    store.save(session)
    return result


@router.get("/card/{card_id}")
def get_model_card(card_id: str, request: Request, response: Response):
    _store, session = _get_session(request, response)
    card = session.modeling_artifacts.get("model_cards", {}).get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Model Card не найден")
    return card
