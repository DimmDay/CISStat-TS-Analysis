"""Прозрачная матрица предпосылок моделей для остановки EDA.

Модуль переиспользует единый ModelingSpec, но не сводит решение к первому
сработавшему правилу. Для каждой модели возвращаются все проверяемые критерии,
а методологическая совместимость отделяется от готовности backend.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from app.data.detectors import detect_column_frequency, score_all_columns_as_date, smart_to_datetime
from apps.api.eda_seasonality import build_eda_seasonality
from apps.api.eda_stationarity import build_eda_stationarity
from apps.api.eda_validation_strategy import MIN_TRAIN_OBSERVATIONS
from apps.api.model_readiness import PRODUCTION_BACKTEST_MODEL_IDS
from src.catalog.modeling_spec_loader import Family, FamilyModel, ModelingSpec


DATE_CONFIDENCE_THRESHOLD = 0.7
Task = Literal["forecast", "multivariate", "volatility"]
CriterionStatus = Literal["pass", "attention", "fail", "unknown", "not_required"]


def _criterion(
    criterion_id: str,
    label: str,
    status: CriterionStatus,
    observed: str,
    requirement: str,
    conclusion: str,
    *,
    blocking: bool = False,
) -> dict[str, Any]:
    return {
        "id": criterion_id,
        "label": label,
        "status": status,
        "observed": observed,
        "requirement": requirement,
        "conclusion": conclusion,
        "blocking": blocking,
    }


def _validation_sizes(
    n: int,
    strategy: str,
    horizon: int,
    n_splits: int,
    gap: int,
    train_window: int,
) -> tuple[int, int]:
    if strategy == "single":
        required = horizon + gap + MIN_TRAIN_OBSERVATIONS
        return max(0, n - horizon - gap), required
    if strategy == "sliding":
        required = train_window + gap + horizon * n_splits
        return min(train_window, max(0, n - gap - horizon * n_splits)), required
    required = MIN_TRAIN_OBSERVATIONS + gap + horizon * n_splits
    return max(0, n - gap - horizon * n_splits), required


def _temporal_profile(df: pd.DataFrame, column: str) -> dict[str, Any]:
    candidates = [
        item for item in score_all_columns_as_date(df)
        if item["name"] != column and item["score"] >= DATE_CONFIDENCE_THRESHOLD
    ]
    if not candidates:
        return {
            "order_source": "row_order",
            "order_column": None,
            "frequency": None,
            "is_regular": None,
            "temporal_status": "unknown",
            "warning": "Временная колонка уверенно не определена; порядок строк требует ручного подтверждения.",
        }
    order_column = str(candidates[0]["name"])
    dates = smart_to_datetime(df[order_column])
    if dates.isna().any():
        return {
            "order_source": "time_column", "order_column": order_column,
            "frequency": None, "is_regular": False, "temporal_status": "invalid",
            "warning": f"В колонке «{order_column}» есть нераспознанные даты.",
        }
    if dates.duplicated().any():
        return {
            "order_source": "time_column", "order_column": order_column,
            "frequency": None, "is_regular": False, "temporal_status": "panel",
            "warning": "Повторные даты похожи на панель: сначала выберите сущность или явно задайте структуру панели.",
        }
    frequency = detect_column_frequency(dates)["code"]
    return {
        "order_source": "time_column", "order_column": order_column,
        "frequency": frequency, "is_regular": frequency is not None,
        "temporal_status": "regular" if frequency else "irregular",
        "warning": None if frequency else "Временная сетка нерегулярна; календарный горизонт и лаги требуют явной регуляризации.",
    }


def _task_criterion(model: FamilyModel, family: Family, task: Task) -> dict[str, Any]:
    if task == "volatility":
        compatible = family.id == "volatility"
        expected = "модель условной дисперсии"
    elif task == "multivariate":
        compatible = family.id == "multivariate"
        expected = "совместная модель системы рядов"
    else:
        compatible = family.id not in {"volatility", "multivariate"}
        expected = "прогноз уровня выбранной цели"
    return _criterion(
        "task", "Задача", "pass" if compatible else "fail",
        {"forecast": "прогноз уровня", "multivariate": "многомерная система", "volatility": "волатильность"}[task],
        expected,
        "Назначение модели соответствует задаче." if compatible else "Модель прогнозирует другой объект.",
        blocking=not compatible,
    )


def _history_criterion(model: FamilyModel, initial_train: int) -> dict[str, Any]:
    enough = initial_train >= model.min_observations
    return _criterion(
        "history", "История", "pass" if enough else "fail",
        f"минимальный train = {initial_train}", f"train ≥ {model.min_observations}",
        "Истории достаточно на первом fold." if enough else "На первом fold модели не хватит истории.",
        blocking=not enough,
    )


def _time_criterion(family: Family, temporal: dict[str, Any]) -> dict[str, Any]:
    status = temporal["temporal_status"]
    observed = {
        "regular": f"регулярная, {temporal['frequency']}",
        "irregular": "нерегулярная",
        "panel": "повторные даты / панель",
        "invalid": "ошибки дат",
        "unknown": "только порядок строк",
    }[status]
    if status in {"panel", "invalid"}:
        return _criterion("time", "Временная ось", "fail", observed, "один упорядоченный ряд", temporal["warning"], blocking=True)
    if status == "regular":
        return _criterion("time", "Временная ось", "pass", observed, "хронологический порядок", "Временная структура определена.")
    conclusion = (
        "Модель может использовать метки дат, но горизонт и сезонности нужно задать явно."
        if family.id in {"structural", "tree_ml", "neural"}
        else "Сначала подтвердите порядок и приведите ряд к регулярной сетке."
    )
    return _criterion("time", "Временная ось", "attention" if status == "irregular" else "unknown", observed, "подтверждённая временная шкала", conclusion)


def _seasonality_criterion(model: FamilyModel, seasonality_status: str, periods: list[int]) -> dict[str, Any]:
    observed = {
        "present": f"подтверждена, периоды {', '.join(map(str, periods))}",
        "absent": "не подтверждена",
        "unknown": "не оценена",
    }[seasonality_status]
    if model.id == "seasonal_naive":
        if seasonality_status == "present":
            return _criterion("seasonality", "Сезонность", "pass", observed, "подтверждённый период", "Seasonal Naive получает период из EDA.")
        status: CriterionStatus = "fail" if seasonality_status == "absent" else "unknown"
        return _criterion("seasonality", "Сезонность", status, observed, "подтверждённый период", "Без устойчивого периода сезонный baseline не определён.", blocking=status == "fail")
    if model.id == "tbats" and seasonality_status != "present":
        return _criterion("seasonality", "Сезонность", "attention", observed, "желательно несколько устойчивых периодов", "Сложность TBATS пока не обоснована.")
    return _criterion("seasonality", "Сезонность", "not_required", observed, "не является жёстким требованием", "Модель допускает несезонную спецификацию.")


def _stationarity_criterion(model: FamilyModel, family: Family, stationarity_status: str) -> dict[str, Any]:
    observed = {
        "stationary": "стационарен / тренд-стационарен",
        "non_stationary": "единичный корень",
        "inconclusive": "смешанный вывод",
        "unknown": "не оценена",
    }[stationarity_status]
    if model.id == "var":
        if stationarity_status == "stationary":
            return _criterion("stationarity", "Стационарность", "attention", observed, "стационарность всех компонент", "Цель прошла проверку, но остальные совместно моделируемые ряды нужно проверить отдельно.")
        status: CriterionStatus = "fail" if stationarity_status == "non_stationary" else "unknown"
        return _criterion("stationarity", "Стационарность", status, observed, "стационарность всех компонент", "VAR требует преобразования и повторной проверки всех рядов.", blocking=status == "fail")
    if model.id == "vecm":
        return _criterion("stationarity", "I(1) и коинтеграция", "attention", observed, "все ряды I(1), ранг Йохансена > 0", "Коинтеграция не выводится из одномерного EDA; нужен отдельный тест системы.")
    if family.id == "arima":
        if stationarity_status == "stationary":
            return _criterion("stationarity", "Стационарность", "pass", observed, "стационарность после d", "Можно включить d=0 в поиск.")
        return _criterion("stationarity", "Стационарность", "attention" if stationarity_status != "unknown" else "unknown", observed, "стационарность после d", "Подберите дифференцирование внутри train fold и повторно проверьте остатки.")
    if family.id == "volatility":
        return _criterion("stationarity", "Стационарность", "attention", observed, "стационарные доходности/изменения", "GARCH применяют к изменениям/доходностям, а не автоматически к уровню.")
    return _criterion("stationarity", "Стационарность", "not_required", observed, "не является жёстким требованием", "Не блокирует модель на этапе shortlist.")


def _shape_criterion(model: FamilyModel, family: Family, task: Task, numeric_series: int) -> dict[str, Any]:
    if model.id == "deepar":
        required = model.min_series or 5
        return _criterion("shape", "Структура рядов", "fail", "одна выбранная цель", f"панель ≥ {required} независимых рядов", "Числовые колонки одного объекта нельзя считать панелью DeepAR.", blocking=True)
    required = model.min_series or (2 if family.id == "multivariate" else 1)
    if required <= 1:
        return _criterion("shape", "Структура рядов", "not_required", "одна целевая серия", "одномерная модель", "Структура подходит.")
    enough = task == "multivariate" and numeric_series >= required
    return _criterion(
        "shape", "Структура рядов", "pass" if enough else "fail",
        f"числовых рядов-кандидатов: {numeric_series}", f"совместно моделируемых рядов ≥ {required}",
        "Есть кандидаты для системы; состав нужно подтвердить." if enough else "Недостаточно явно заданных рядов для системы.",
        blocking=not enough,
    )


def _exogenous_criterion(model: FamilyModel, n_exogenous: int) -> dict[str, Any]:
    if model.supports_exogenous and n_exogenous:
        return _criterion("exogenous", "Экзогенные X", "pass", f"кандидатов X: {n_exogenous}", "поддерживаются", "Модель может использовать отобранные признаки.")
    if not model.supports_exogenous and n_exogenous:
        return _criterion("exogenous", "Экзогенные X", "not_required", f"кандидатов X: {n_exogenous}", "не используются", "Наличие X не блокирует одномерную модель: она просто не включает их.")
    return _criterion("exogenous", "Экзогенные X", "not_required", "нет отобранных X", "опциональны", "Модель может работать без внешних признаков.")


def _features_criterion(model: FamilyModel) -> dict[str, Any]:
    if model.requires_feature_engineering:
        return _criterion("features", "Lag-features", "attention", "ещё не построены", "лаги/rolling/calendar внутри fold", "Постройте признаки только на train каждого fold, чтобы исключить утечку.")
    return _criterion("features", "Lag-features", "not_required", "не требуются", "нет жёсткого требования", "Специальная матрица лаговых X не обязательна.")


def _target_criterion(model: FamilyModel, family: Family, has_negative: bool) -> dict[str, Any]:
    if family.id == "volatility":
        return _criterion("target", "Цель модели", "attention", "выбран уровень ряда", "доходности/изменения и ARCH-эффект", "Сначала сформируйте стационарные изменения и подтвердите кластеризацию волатильности.")
    if family.id == "exponential_smoothing" and has_negative and model.id in {"ets", "ets_damped"}:
        return _criterion("target", "Знак значений", "attention", "есть ≤ 0", "мультипликативные компоненты требуют > 0", "Ограничьте поиск аддитивной ETS-спецификацией.")
    return _criterion("target", "Цель модели", "not_required", "числовой ряд", "конечные значения", "Дополнительных ограничений не выявлено.")


def _platform_criterion(model: FamilyModel) -> tuple[str, dict[str, Any]]:
    ready = model.id in PRODUCTION_BACKTEST_MODEL_IDS
    platform_status = "ready" if ready else "catalog_only"
    return platform_status, _criterion(
        "platform", "Backend", "pass" if ready else "attention",
        "реализован" if ready else "только каталог", "production backtest",
        "Модель можно передать в этап моделирования." if ready else "Перед запуском требуется реализация и интеграционный тест backend.",
    )


def _model_out(
    model: FamilyModel,
    family: Family,
    *,
    task: Task,
    initial_train: int,
    temporal: dict[str, Any],
    seasonality_status: str,
    periods: list[int],
    stationarity_status: str,
    numeric_series: int,
    n_exogenous: int,
    has_negative: bool,
) -> dict[str, Any]:
    platform_status, platform = _platform_criterion(model)
    criteria = [
        _task_criterion(model, family, task),
        _history_criterion(model, initial_train),
        _time_criterion(family, temporal),
        _seasonality_criterion(model, seasonality_status, periods),
        _stationarity_criterion(model, family, stationarity_status),
        _shape_criterion(model, family, task, numeric_series),
        _exogenous_criterion(model, n_exogenous),
        _features_criterion(model),
        _target_criterion(model, family, has_negative),
        platform,
    ]
    blocking = [item["conclusion"] for item in criteria if item["status"] == "fail" and item["blocking"]]
    cautions = [item["conclusion"] for item in criteria if item["status"] in {"attention", "unknown"}]
    compatibility = "blocked" if blocking else ("conditional" if cautions else "candidate")
    return {
        "model_id": model.id,
        "model_name": model.name,
        "family_id": family.id,
        "family_name": family.name,
        "compatibility": compatibility,
        "platform_status": platform_status,
        "min_observations": model.min_observations,
        "supports_exogenous": model.supports_exogenous,
        "libraries": model.libraries,
        "training_time": model.training_time,
        "criteria": criteria,
        "blocking_reasons": list(dict.fromkeys(blocking)),
        "cautions": list(dict.fromkeys(cautions)),
    }


def build_eda_model_matrix(
    df: pd.DataFrame,
    column: str,
    task: Task = "forecast",
    horizon: int = 12,
    validation_strategy: str = "expanding",
    n_splits: int = 5,
    gap: int = 0,
    train_window: int = 60,
) -> dict[str, Any]:
    """Профилирует текущий датасет без обучения и без его мутации."""
    values = pd.to_numeric(df[column], errors="coerce")
    finite = np.isfinite(values.to_numpy(dtype=float, na_value=np.nan))
    missing_count = int((~finite).sum())
    n = int(finite.sum())
    spec = ModelingSpec.from_yaml(str(Path(__file__).resolve().parents[2] / "rules" / "modeling.yaml"))
    if missing_count or n < 2:
        reason = "Цель содержит пропуски/бесконечные значения; завершите предобработку перед оценкой моделей."
        return {
            "column": column, "applicable": False, "reason": reason, "task": task,
            "horizon": horizon, "spec_version": spec.metadata.version,
            "profile": {
                "n_observations": n, "missing_count": missing_count, "numeric_series_count": 0,
                "n_exogenous": 0, "order_source": "row_order", "order_column": None,
                "frequency": None, "is_regular": None, "temporal_status": "unknown",
                "seasonality_status": "unknown", "seasonal_periods": [],
                "stationarity_status": "unknown", "has_negative_values": False,
                "validation_strategy": validation_strategy, "initial_train_observations": 0,
                "required_observations": 0,
            },
            "summary": {"total_models": spec.total_model_count(), "candidates": 0, "conditional": 0, "blocked": 0, "ready": 0, "catalog_only": 0},
            "families": [], "models": [], "shortlist": [], "runnable_shortlist": [],
            "recommendation": "Сначала завершите предобработку цели.",
            "methodology_note": "Матрица проверяет предпосылки, но не прогнозную точность.",
            "warnings": [reason],
        }

    temporal = _temporal_profile(df, column)
    date_columns = {temporal["order_column"]} if temporal["order_column"] else set()
    numeric_columns = [
        name for name in df.select_dtypes(include="number").columns
        if name not in date_columns
    ]
    n_exogenous = max(0, len([name for name in numeric_columns if name != column]))
    numeric_series = 1 + n_exogenous
    initial_train, required = _validation_sizes(n, validation_strategy, horizon, n_splits, gap, train_window)

    seasonality_status = "unknown"
    periods: list[int] = []
    stationarity_status = "unknown"
    warnings: list[str] = []
    if temporal["warning"]:
        warnings.append(temporal["warning"])
    if temporal["temporal_status"] not in {"panel", "invalid"}:
        seasonality = build_eda_seasonality(df, column, min_cycles=3, max_candidates=5)
        if seasonality["applicable"]:
            confirmed = [item for item in seasonality["candidates"] if item["confirmed"]]
            periods = [int(round(item["period"])) for item in confirmed]
            seasonality_status = "present" if periods else "absent"
        stationarity = build_eda_stationarity(df, column, alpha=0.05, rolling_window=12)
        if stationarity["applicable"]:
            consensus = stationarity["consensus"]
            stationarity_status = (
                "stationary" if consensus in {"stationary", "trend-stationary"}
                else "non_stationary" if consensus == "non-stationary"
                else "inconclusive"
            )

    models: list[dict[str, Any]] = []
    for family in sorted(spec.families, key=lambda item: item.priority):
        for model in family.models:
            models.append(_model_out(
                model, family, task=task, initial_train=initial_train, temporal=temporal,
                seasonality_status=seasonality_status, periods=periods,
                stationarity_status=stationarity_status, numeric_series=numeric_series,
                n_exogenous=n_exogenous, has_negative=bool((values[finite] <= 0).any()),
            ))

    compatibility_counts = Counter(item["compatibility"] for item in models)
    platform_counts = Counter(item["platform_status"] for item in models)
    families_out = []
    for family in sorted(spec.families, key=lambda item: item.priority):
        rows = [item for item in models if item["family_id"] == family.id]
        counts = Counter(item["compatibility"] for item in rows)
        readiness = Counter(item["platform_status"] for item in rows)
        families_out.append({
            "family_id": family.id, "family_name": family.name,
            "candidates": counts["candidate"], "conditional": counts["conditional"],
            "blocked": counts["blocked"], "ready": readiness["ready"],
            "catalog_only": readiness["catalog_only"],
        })
    shortlist = [item["model_id"] for item in models if item["compatibility"] != "blocked"]
    runnable = [item["model_id"] for item in models if item["compatibility"] != "blocked" and item["platform_status"] == "ready"]
    if n < required:
        warnings.append(f"Текущей схеме валидации нужно не менее {required} наблюдений; доступно {n}.")
    return {
        "column": column, "applicable": True, "reason": None, "task": task,
        "horizon": horizon, "spec_version": spec.metadata.version,
        "profile": {
            "n_observations": n, "missing_count": missing_count,
            "numeric_series_count": numeric_series, "n_exogenous": n_exogenous,
            "order_source": temporal["order_source"], "order_column": temporal["order_column"],
            "frequency": temporal["frequency"], "is_regular": temporal["is_regular"],
            "temporal_status": temporal["temporal_status"],
            "seasonality_status": seasonality_status, "seasonal_periods": periods,
            "stationarity_status": stationarity_status,
            "has_negative_values": bool((values[finite] <= 0).any()),
            "validation_strategy": validation_strategy,
            "initial_train_observations": initial_train,
            "required_observations": required,
        },
        "summary": {
            "total_models": len(models), "candidates": compatibility_counts["candidate"],
            "conditional": compatibility_counts["conditional"], "blocked": compatibility_counts["blocked"],
            "ready": platform_counts["ready"], "catalog_only": platform_counts["catalog_only"],
        },
        "families": families_out, "models": models,
        "shortlist": shortlist, "runnable_shortlist": runnable,
        "recommendation": "Сравните runnable shortlist и обязательные baselines на временных folds; матрица не ранжирует будущую точность.",
        "methodology_note": "Совместимость означает выполнение наблюдаемых предпосылок. Неизвестные свойства дают оговорку, а не ложную рекомендацию; победителя определяет backtest.",
        "warnings": list(dict.fromkeys(warnings)),
    }
