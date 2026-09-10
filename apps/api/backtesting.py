"""Leakage-safe rolling-origin backtest engine.

The EDA validation strategy owns fold boundaries.  This module validates and
executes that immutable plan for every production model.  Predictors receive
only the train slice and forecast a fixed multi-step horizon; test observations
are never passed to model code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
import platform
import time
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

import numpy as np

from apps.api.model_execution import (
    LegacyPredictor as Predictor,
    MODEL_EXECUTION_CONTRACT_VERSION,
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionRequest,
    fixed_origin_baseline_predict,
    legacy_predictor_registry,
)
from apps.api.feature_plan import (
    FoldFeatureMatrixBuilder,
    FeaturePlan,
    KIND_EXOGENOUS,
    POLICY_NONE,
    ROLE_HISTORIC,
    bind_feature_importance,
)
from apps.api.schemas import BacktestMetrics


class BacktestExecutionError(ValueError):
    """A plan or model fold cannot be executed without fabricating results."""


def validate_target_preprocessing(
    transformations: Mapping[str, Mapping[str, Any]], target_column: str,
) -> list[str]:
    """Reject a derived target whose full-history fit would leak into folds.

    Deterministic/causal transforms may be evaluated on their explicit target
    scale.  Non-causal smoothers/detrending and estimated power-transform
    parameters require a future fold-local pipeline, so the canonical engine
    fails closed instead of reporting optimistic metrics.
    """
    metadata = transformations.get(target_column)
    if not metadata:
        return []
    method = str(metadata.get("method") or "unknown")
    if metadata.get("modeling_safe") is False:
        raise BacktestExecutionError(
            f"Target '{target_column}' получен методом '{method}', который должен "
            "переоцениваться внутри каждого train fold"
        )
    if (
        method in {"box_cox", "yeo_johnson"}
        and metadata.get("lambda_policy") != "fixed"
        and metadata.get("fit_policy") != "per_train_fold"
    ):
        raise BacktestExecutionError(
            f"Параметры '{method}' для target '{target_column}' оценены по полной "
            "истории; требуется fit внутри каждого train fold"
        )
    return [
        f"Метрики рассчитаны в шкале преобразованной цели '{target_column}' ({method})."
    ]


@dataclass
class BacktestFoldPlan:
    fold: int
    train_indices: list[int]
    test_indices: list[int]
    gap: int
    train_start_label: Optional[str] = None
    train_end_label: Optional[str] = None
    test_start_label: Optional[str] = None
    test_end_label: Optional[str] = None


@dataclass
class BacktestPlan:
    strategy: str
    horizon: int
    gap: int
    folds: list[BacktestFoldPlan]
    cohort_id: str
    fingerprint: str
    target_column: str
    seasonal_period: int
    n_observations: int
    preprocessing_signature: str = "none"
    objective: str = "level_forecast"
    cohort_contract: dict[str, Any] = field(default_factory=dict)
    feature_plan: Optional[FeaturePlan] = None
    feature_columns: dict[str, list[float]] = field(default_factory=dict)


class PreparedFoldProtocol(Protocol):
    model_train: list[float]
    evaluation_train: list[float]
    evaluation_actual: list[float]
    restore_forecast: Callable[[list[float]], list[float]]


class FoldPreprocessorProtocol(Protocol):
    summary: Mapping[str, Any]

    def prepare(
        self, values: list[float], fold: BacktestFoldPlan,
    ) -> PreparedFoldProtocol: ...


def build_backtest_plan(
    validation: Mapping[str, Any], *, n_observations: int,
    fingerprint: str, target_column: str, seasonal_period: int,
    preprocessing_signature: str = "none",
    objective: str = "level_forecast",
    series_fingerprints: Optional[Mapping[str, str]] = None,
    feature_contract: Optional[Mapping[str, Any]] = None,
    metric_policy: Optional[Mapping[str, Any]] = None,
    feature_plan: Optional[FeaturePlan] = None,
    feature_columns: Optional[Mapping[str, Sequence[float]]] = None,
    cohort_contract_override: Optional[Mapping[str, Any]] = None,
) -> BacktestPlan:
    """Validate and freeze the exact folds produced by EDA."""
    strategy = str(validation.get("strategy", ""))
    if strategy not in {"single", "expanding", "sliding"}:
        raise BacktestExecutionError(f"Неподдерживаемая стратегия бэктеста: {strategy!r}")
    horizon = int(validation.get("horizon") or 0)
    gap = int(validation.get("gap") or 0)
    metric_period = int(seasonal_period)
    if objective not in {"level_forecast", "multivariate", "volatility"}:
        raise BacktestExecutionError(f"Неподдерживаемый objective: {objective}")
    raw_folds = validation.get("folds") or []
    if horizon < 1 or gap < 0 or metric_period < 1 or not raw_folds:
        raise BacktestExecutionError("EDA validation strategy не содержит исполнимых folds")
    if strategy == "single" and len(raw_folds) != 1:
        raise BacktestExecutionError("Стратегия single должна содержать ровно один fold")

    folds: list[BacktestFoldPlan] = []
    seen_test_indices: set[int] = set()
    for ordinal, raw in enumerate(raw_folds, 1):
        train_start, train_end = int(raw["train_start"]), int(raw["train_end"])
        test_start, test_end = int(raw["test_start"]), int(raw["test_end"])
        if not (0 <= train_start <= train_end < test_start <= test_end < n_observations):
            raise BacktestExecutionError(f"Некорректные временные границы fold {ordinal}")
        actual_gap = test_start - train_end - 1
        if actual_gap != gap or int(raw.get("gap_size", gap)) != gap:
            raise BacktestExecutionError(f"Fold {ordinal} расходится с EDA gap={gap}")
        train_indices = list(range(train_start, train_end + 1))
        test_indices = list(range(test_start, test_end + 1))
        if len(test_indices) != horizon:
            raise BacktestExecutionError(
                f"Fold {ordinal}: test_size={len(test_indices)} не равен horizon={horizon}"
            )
        if seen_test_indices.intersection(test_indices):
            raise BacktestExecutionError(f"Test-интервалы пересекаются в fold {ordinal}")
        if folds and test_start <= folds[-1].test_indices[-1]:
            raise BacktestExecutionError("EDA folds должны идти строго по времени")
        if strategy == "expanding" and folds:
            if train_start != folds[-1].train_indices[0] or train_end <= folds[-1].train_indices[-1]:
                raise BacktestExecutionError("Expanding folds не расширяют train-окно")
        if strategy == "sliding":
            declared_window = int(validation.get("train_window") or len(train_indices))
            if len(train_indices) != declared_window:
                raise BacktestExecutionError(
                    f"Fold {ordinal}: train_size={len(train_indices)} не равен sliding train_window={declared_window}"
                )
            if folds and (
                train_start <= folds[-1].train_indices[0]
                or train_end <= folds[-1].train_indices[-1]
            ):
                raise BacktestExecutionError("Sliding folds не сдвигают train-окно вперёд")
        seen_test_indices.update(test_indices)
        folds.append(BacktestFoldPlan(
            fold=int(raw.get("fold", ordinal)), train_indices=train_indices,
            test_indices=test_indices, gap=gap,
            train_start_label=raw.get("train_start_label"),
            train_end_label=raw.get("train_end_label"),
            test_start_label=raw.get("test_start_label"),
            test_end_label=raw.get("test_end_label"),
        ))

    declared_splits = int(validation.get("n_splits") or validation.get("effective_splits") or len(folds))
    if declared_splits != len(folds):
        raise BacktestExecutionError(
            f"EDA объявила {declared_splits} folds, но передала {len(folds)}"
        )
    if folds[-1].test_indices[-1] != n_observations - 1:
        raise BacktestExecutionError("Последний EDA test fold должен завершаться последним наблюдением")
    series_scope = dict(series_fingerprints or {target_column: fingerprint})
    if not series_scope or not all(series_scope.values()):
        raise BacktestExecutionError("Cohort требует fingerprint каждого входного ряда")
    # Task 126: иммутабельный FeaturePlan -- единственный источник feature_contract.
    # Без плана контракт остаётся legacy-формы (policy=none), поэтому cohort_id
    # уже существующих бэктестов не меняется.
    if feature_plan is not None:
        features = feature_plan.feature_contract()
        if not feature_plan.features:
            feature_plan = None
    else:
        features = dict(feature_contract or {
            "historic": [], "future_known": [], "static": [], "policy": "none",
        })
    metrics = dict(metric_policy or {
        "metrics": ["mae", "rmse", "mape", "mase", "smape", "rmsse"],
        "primary": "rmse",
        "aggregation": "test_size_weighted_folds",
        "seasonal_period": metric_period,
    })
    if cohort_contract_override is not None:
        # Task 132: векторный cohort строит контракт АВТОРИТЕТНО через
        # multivariate_cohort_contract (Task 131) -- с system-блоком и
        # vector-метрикой; он используется дословно и участвует в cohort_id.
        override = dict(cohort_contract_override)
        if str(override.get("objective") or "") != str(objective):
            raise BacktestExecutionError(
                "cohort_contract_override не совпадает с objective плана"
            )
        cohort_contract = override
    else:
        cohort_contract = {
            "objective": objective,
            "series_fingerprints": series_scope,
            "feature_contract": features,
            "metric_policy": metrics,
        }
    payload = {
        "fingerprint": fingerprint, "target_column": target_column,
        "strategy": strategy, "horizon": horizon, "gap": gap,
        "metric_seasonal_period": metric_period,
        "preprocessing_signature": preprocessing_signature,
        "cohort_contract": cohort_contract,
        "folds": [
            {"fold": item.fold, "train": item.train_indices, "test": item.test_indices}
            for item in folds
        ],
    }
    cohort_id = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return BacktestPlan(
        strategy=strategy, horizon=horizon, gap=gap, folds=folds,
        cohort_id=cohort_id, fingerprint=fingerprint, target_column=target_column,
        seasonal_period=metric_period,
        n_observations=n_observations,
        preprocessing_signature=preprocessing_signature,
        objective=objective, cohort_contract=cohort_contract,
        feature_plan=feature_plan,
        feature_columns={
            str(name): [float(value) for value in column]
            for name, column in (feature_columns or {}).items()
        },
    )


# Compatibility facade for tests and callers that inject the legacy callable
# shape.  Canonical production execution below goes through the typed registry.
PRODUCTION_PREDICTORS: dict[str, Predictor] = legacy_predictor_registry()


def compute_metric_scales(
    y_train: list[float], seasonal_period: int,
) -> tuple[Optional[float], Optional[float]]:
    """Return train-only MASE/RMSSE denominators for audit and reuse.

    Persisting the denominators makes a pointwise forecast combination
    evaluable on exactly the same fold without reconstructing or leaking the
    training data later in the selection stage.
    """
    train = np.asarray(y_train, dtype=float)
    period = max(1, int(seasonal_period))
    if train.size <= period:
        return None, None
    scale_errors = train[period:] - train[:-period]
    mae_scale = float(np.mean(np.abs(scale_errors)))
    rmsse_scale = float(np.sqrt(np.mean(np.square(scale_errors))))
    epsilon = np.finfo(float).eps
    return (
        mae_scale if mae_scale > epsilon else None,
        rmsse_scale if rmsse_scale > epsilon else None,
    )


def compute_forecast_metrics(
    y_true: list[float], y_pred: list[float], *,
    mase_scale: Optional[float], rmsse_scale: Optional[float],
) -> BacktestMetrics:
    """Compute metrics from forecasts and already fitted train-only scales."""
    if not y_true or len(y_true) != len(y_pred):
        raise BacktestExecutionError("Факты и прогноз должны иметь одинаковую ненулевую длину")
    actual = np.asarray(y_true, dtype=float)
    predicted = np.asarray(y_pred, dtype=float)
    if not (np.isfinite(actual).all() and np.isfinite(predicted).all()):
        raise BacktestExecutionError("Backtest получил NaN/Inf")
    errors = actual - predicted
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(np.square(errors))))
    nonzero = np.abs(actual) > np.finfo(float).eps
    mape = float(np.mean(np.abs(errors[nonzero] / actual[nonzero])) * 100) if nonzero.any() else None
    denominator = np.abs(actual) + np.abs(predicted)
    valid_smape = denominator > np.finfo(float).eps
    smape = float(np.mean(200 * np.abs(errors[valid_smape]) / denominator[valid_smape])) if valid_smape.any() else 0.0

    mase = mae / mase_scale if mase_scale is not None else None
    rmsse = rmse / rmsse_scale if rmsse_scale is not None else None
    return BacktestMetrics(
        mae=round(mae, 6), rmse=round(rmse, 6),
        mape=round(mape, 6) if mape is not None else None,
        mase=round(mase, 6) if mase is not None else None,
        smape=round(smape, 6), rmsse=round(rmsse, 6) if rmsse is not None else None,
        mape_valid_points=int(nonzero.sum()), weighted_score=None,
    )


def compute_backtest_metrics(
    y_true: list[float], y_pred: list[float], y_train: list[float], seasonal_period: int,
) -> BacktestMetrics:
    mase_scale, rmsse_scale = compute_metric_scales(y_train, seasonal_period)
    return compute_forecast_metrics(
        y_true, y_pred, mase_scale=mase_scale, rmsse_scale=rmsse_scale,
    )


def _aggregate_metrics(folds: list[dict[str, Any]]) -> BacktestMetrics:
    points = [point for fold in folds for point in fold["predictions"]]
    mae = float(np.mean([abs(point["residual"]) for point in points]))
    rmse = float(np.sqrt(np.mean([point["residual"] ** 2 for point in points])))
    valid_mape = [
        abs(point["residual"] / point["actual"]) * 100
        for point in points if abs(point["actual"]) > np.finfo(float).eps
    ]
    valid_smape = [
        200 * abs(point["residual"]) / (abs(point["actual"]) + abs(point["predicted"]))
        for point in points
        if abs(point["actual"]) + abs(point["predicted"]) > np.finfo(float).eps
    ]
    total = sum(fold["n_test"] for fold in folds)
    def weighted(metric: str) -> Optional[float]:
        values = [(fold["metrics"].get(metric), fold["n_test"]) for fold in folds]
        if any(value is None for value, _ in values):
            return None
        return sum(float(value) * weight for value, weight in values) / total
    aggregate_mase = weighted("mase")
    fold_rmsse = [(fold["metrics"].get("rmsse"), fold["n_test"]) for fold in folds]
    aggregate_rmsse = None
    if all(value is not None for value, _ in fold_rmsse):
        aggregate_rmsse = math.sqrt(
            sum(float(value) ** 2 * weight for value, weight in fold_rmsse) / total
        )
    return BacktestMetrics(
        mae=round(mae, 6), rmse=round(rmse, 6),
        mape=round(float(np.mean(valid_mape)), 6) if valid_mape else None,
        mase=round(aggregate_mase, 6) if aggregate_mase is not None else None,
        smape=round(float(np.mean(valid_smape)), 6) if valid_smape else 0.0,
        rmsse=round(aggregate_rmsse, 6) if aggregate_rmsse is not None else None,
        mape_valid_points=len(valid_mape), weighted_score=None,
    )


def _feature_execution_context(
    plan: BacktestPlan, execution_contract: Mapping[str, Any], model_id: str,
) -> tuple[Optional[FeaturePlan], str, list[str]]:
    """Resolve the Task 126 capability gates ONCE per run (not per fold).

    Returns (plan, mode, warnings) where mode is:
    ``none``     -- нет активного плана: legacy-путь без изменений;
    ``univariate`` -- модель без regressor-интерфейса: только warning;
    ``gated``    -- supervised, но без supports_future_features: матрицы
                    строятся (lineage/подготовка к ML), regressors не идут;
    ``granted``  -- supervised + supports_future_features: полный канал.
    """
    feature_plan = plan.feature_plan
    if feature_plan is None or not feature_plan.features:
        return None, "none", []
    input_kind = execution_contract.get("input_kind")
    if input_kind == "univariate":
        return feature_plan, "univariate", [
            f"FeaturePlan '{feature_plan.plan_id}': модель '{model_id}' не принимает "
            f"регрессоры (input_kind=univariate); исключены: "
            f"{feature_plan.future_known_names() + feature_plan.static_names()}"
        ]
    if input_kind not in {"supervised", "panel"}:
        return feature_plan, "none", []
    if not execution_contract.get("supports_future_features"):
        return feature_plan, "gated", [
            f"FeaturePlan '{feature_plan.plan_id}': модель '{model_id}' не объявила "
            f"supports_future_features; регрессоры "
            f"{feature_plan.future_known_names() + feature_plan.static_names()} "
            "исключены (capability-гейт), fold-матрицы записываются для аудита"
        ]
    return feature_plan, "granted", []


def run_backtest_plan(
    *, model_id: str, model_name: str, family_id: str,
    series: list[float], labels: list[str], plan: BacktestPlan,
    seasonal_period: int, params: Optional[Mapping[str, Any]] = None,
    seasonal_periods: Optional[Sequence[int]] = None,
    predictors: Optional[Mapping[str, Predictor]] = None,
    preprocessing_warnings: Optional[list[str]] = None,
    fold_preprocessor: Optional[FoldPreprocessorProtocol] = None,
    random_state: int = 42,
) -> dict[str, Any]:
    """Execute every EDA fold with strict, fixed-origin model predictions.

    ``seasonal_periods`` (plural) is an optional pass-through of the FULL
    multi-period spectral hand-off (e.g. [7, 365] daily+yearly), distinct from
    the single ``seasonal_period`` that fixes the cohort's MASE/RMSSE scale
    (Task 121) and must stay identical across every model for a fair
    comparison. Stored in ``params`` under ``tbats_seasonal_periods`` (NOT
    ``seasonal_periods`` -- that key is already used, pre-Task-125, by the ETS
    executor as a single-value seasonal_period override; reusing it here would
    silently break ETS). Only TBATS (Task 125) currently reads it; every other
    adapter ignores unknown params keys, so this is safe to pass unconditionally.
    """
    # Task 134: одномерный движок считает LEVEL-метрики (MAE/RMSE/MASE) по
    # уровню ряда.  Для objective="volatility" target -- условная дисперсия:
    # её метрики -- QLIKE (primary) + RMSE/MAE по realized proxy
    # (volatility_contract), а level-метрики на дисперсии запрещены
    # постановкой («GARCH нельзя ранжировать рядом с ETS/ARIMA»).  Гейт
    # стоит ПЕРЕД любым исполнением (включая injected-predictor путь,
    # минующий реестр) -- иначе volatility-план был бы исполнен здесь с
    # фиктивными level-метриками.  Исполнение volatility-планов --
    # volatility-движок (Tasks 135-136 поверх контракта Task 134).
    if plan.objective == "volatility":
        raise BacktestExecutionError(
            "Одномерный движок не исполняет volatility-планы: target "
            "волатильности -- условная дисперсия, а не уровень ряда; "
            "level-метрики (MAE/RMSE/MASE) на ней запрещены. Primary "
            "метрика volatility-cohort -- QLIKE; исполнение -- "
            "volatility-движок поверх контракта Task 134."
        )
    if int(seasonal_period) != plan.seasonal_period:
        raise BacktestExecutionError("Seasonal period расходится с зафиксированным backtest cohort")
    if len(series) != plan.n_observations:
        raise BacktestExecutionError("Длина ряда расходится с зафиксированным backtest cohort")
    if len(series) != len(labels):
        raise BacktestExecutionError("Число временных меток не совпадает с длиной ряда")
    predictor = None if predictors is None else predictors.get(model_id)
    if predictors is None:
        try:
            execution_contract = MODEL_EXECUTION_REGISTRY.describe(model_id)
        except ValueError as exc:
            raise BacktestExecutionError(str(exc)) from exc
    else:
        if predictor is None:
            raise BacktestExecutionError(
                f"Injected predictor для модели '{model_id}' не реализован"
            )
        injected_payload = {
            "version": MODEL_EXECUTION_CONTRACT_VERSION,
            "model_id": model_id,
            "family_id": family_id,
            "adapter_id": "injected-legacy-predictor",
            "objective": plan.objective,
            "model_version": "test-injected",
            "adapter_version": "compat-v1",
            "input_kind": "univariate",
            "output_kind": "point",
            "fit_policy": "per_train_fold",
            "actions": ["backtest"],
            "dependency_group": "classical",
            "dependency_status": [],
            "library_versions": {"python": platform.python_version()},
            "runtime_available": True,
            "lifecycle_capabilities": {
                "fit": True, "predict": True,
                "tuning": False, "diagnostics": False,
            },
            "resource_capabilities": {
                "cpu": "required", "gpu": "unsupported",
                "memory_class": "low", "supports_parallel_folds": False,
            },
        }
        encoded = json.dumps(
            injected_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
        execution_contract = {
            **injected_payload, "signature": sha256(encoded).hexdigest(),
        }
    values = [float(value) for value in series]
    if not np.isfinite(np.asarray(values, dtype=float)).all():
        raise BacktestExecutionError("Ряд содержит NaN/Inf")
    parameters = dict(params or {})
    if seasonal_periods is not None and "tbats_seasonal_periods" not in parameters:
        parameters["tbats_seasonal_periods"] = [int(value) for value in seasonal_periods]
    feature_plan, feature_mode, feature_warnings = (
        _feature_execution_context(plan, execution_contract, model_id)
    )
    if predictors is not None:
        # Legacy injected-предикторы не принимают regressor-канал Task 126.
        feature_mode = "none" if feature_mode == "none" else "legacy-injected"
        if feature_mode == "legacy-injected":
            feature_warnings.append(
                f"FeaturePlan '{feature_plan.plan_id}' не применён: injected-предиктор "
                f"модели '{model_id}' вне типизированного registry-контракта"
            )
            feature_plan = None
    if feature_mode == "granted" and feature_plan is not None:
        # Task 124: historic-объявления (future неизвестен) не проходят в
        # regressor-канал ни при каком capability-гейте -- сообщаем это явно,
        # один раз на run, а не тихим деградационным путём.
        historic_exogenous = [
            spec.name for spec in feature_plan.features
            if spec.role == ROLE_HISTORIC and spec.kind == KIND_EXOGENOUS
        ]
        if historic_exogenous:
            feature_warnings.append(
                f"FeaturePlan '{feature_plan.plan_id}': historic-регрессоры "
                f"{historic_exogenous} не переданы модели '{model_id}': будущие "
                "значения неизвестны (строгий future-known contract); доступны "
                "только в fold-матрицах аудита"
            )
    folds: list[dict[str, Any]] = []
    adapter_warnings: list[str] = []
    started = time.monotonic()
    for fold in plan.folds:
        raw_train = [values[index] for index in fold.train_indices]
        fold_started = time.monotonic()
        feature_lineage: Optional[dict[str, Any]] = None
        fold_feature_importance: Optional[dict[str, Any]] = None
        try:
            if fold_preprocessor is None:
                y_train = raw_train
                y_true = [values[index] for index in fold.test_indices]
                metric_train = y_train
                restore_forecast = lambda forecast: forecast
            else:
                prepared = fold_preprocessor.prepare(values, fold)
                y_train = prepared.model_train
                y_true = prepared.evaluation_actual
                metric_train = prepared.evaluation_train
                restore_forecast = prepared.restore_forecast
            execution_horizon = fold.gap + len(y_true)
            if predictors is None:
                train_timestamps = (
                    [labels[index] for index in fold.train_indices]
                    if len(y_train) == len(raw_train) else []
                )
                future_timestamps = [
                    labels[index]
                    for index in range(
                        fold.train_indices[-1] + 1, fold.test_indices[-1] + 1,
                    )
                ]
                supervised_train_features: Mapping[str, Sequence[float]] = {}
                supervised_future_features: Mapping[str, Sequence[float]] = {}
                if feature_plan is not None and feature_mode in {"gated", "granted"}:
                    # Fresh-инстанс на каждый fold: все статистики трансформеров
                    # (imputer/scaler/encoder) фитуются заново на train-срезе fold'а.
                    builder = FoldFeatureMatrixBuilder(feature_plan).fit_fold(
                        values, labels, fold, feature_columns=plan.feature_columns,
                    )
                    feature_lineage = builder.lineage_record(fold=fold.fold)
                    if feature_mode == "granted":
                        future_matrix = builder.future_matrix()
                        if future_matrix["columns"]:
                            train_known = builder.train_known_matrix()
                            supervised_train_features = {
                                name: [row[position] for row in train_known["rows"]]
                                for position, name in enumerate(train_known["columns"])
                            }
                            supervised_future_features = {
                                name: [row[position] for row in future_matrix["rows"]]
                                for position, name in enumerate(future_matrix["columns"])
                            }
                execution_result = MODEL_EXECUTION_REGISTRY.execute(
                    model_id,
                    ModelExecutionRequest(
                        target=y_train,
                        horizon=execution_horizon,
                        objective=plan.objective,
                        seasonal_period=seasonal_period,
                        params=parameters,
                        train_features=supervised_train_features,
                        future_features=supervised_future_features,
                        train_timestamps=train_timestamps,
                        future_timestamps=future_timestamps,
                        random_state=random_state,
                    ),
                )
                model_forecast = list(execution_result.forecast)
                adapter_warnings.extend(execution_result.warnings)
                # Task 127: feature importance адаптера привязывается к ТОЧНОЙ
                # матрице, на которой он посчитан (bind_feature_importance,
                # oracle-защита: чужие колонки отклоняются -> ошибка fold'а).
                fold_feature_importance: Optional[dict[str, Any]] = None
                importance_lineage = execution_result.metadata.get(
                    "feature_importance_lineage",
                )
                importance_records = execution_result.metadata.get("feature_importances")
                if isinstance(importance_lineage, Mapping) and importance_records:
                    fold_feature_importance = bind_feature_importance(
                        importance_lineage, importance_records,
                    )
                    fold_feature_importance["fold"] = fold.fold
                    if feature_lineage is not None:
                        fold_feature_importance["plan_id"] = feature_lineage.get("plan_id")
                else:
                    fold_feature_importance = None
            else:
                assert predictor is not None
                model_forecast = [float(value) for value in predictor(
                    y_train, execution_horizon, seasonal_period, parameters,
                )]
            forecast = [float(value) for value in restore_forecast(model_forecast)]
            if len(forecast) != fold.gap + len(y_true):
                raise BacktestExecutionError("Model/preprocessing вернул неверную длину прогноза")
            y_pred = forecast[fold.gap:]
            mase_scale, rmsse_scale = compute_metric_scales(metric_train, seasonal_period)
            metrics = compute_forecast_metrics(
                y_true, y_pred, mase_scale=mase_scale, rmsse_scale=rmsse_scale,
            )
        except Exception as exc:
            raise BacktestExecutionError(
                f"{model_name}: fold {fold.fold} завершился ошибкой: {exc}"
            ) from exc
        predictions = [
            {
                "fold": fold.fold, "horizon_step": step,
                "index": index, "label": labels[index],
                "actual": actual, "predicted": predicted,
                "residual": round(actual - predicted, 12),
            }
            for step, (index, actual, predicted) in enumerate(
                zip(fold.test_indices, y_true, y_pred, strict=True), 1,
            )
        ]
        folds.append({
            "fold": fold.fold, "status": "success",
            "train_start": fold.train_indices[0], "train_end": fold.train_indices[-1],
            "test_start": fold.test_indices[0], "test_end": fold.test_indices[-1],
            "gap": fold.gap, "n_train": len(raw_train), "n_test": len(y_true),
            "train_start_label": fold.train_start_label or labels[fold.train_indices[0]],
            "train_end_label": fold.train_end_label or labels[fold.train_indices[-1]],
            "test_start_label": fold.test_start_label or labels[fold.test_indices[0]],
            "test_end_label": fold.test_end_label or labels[fold.test_indices[-1]],
            "metrics": metrics.model_dump(mode="json"), "predictions": predictions,
            "mase_scale": mase_scale, "rmsse_scale": rmsse_scale,
            "feature_matrix": feature_lineage,
            "feature_importance": fold_feature_importance,
            "duration_ms": round((time.monotonic() - fold_started) * 1000, 3),
            "error": None,
        })
    aggregate = _aggregate_metrics(folds)
    oof = [point for fold in folds for point in fold["predictions"]]
    warnings: list[str] = list(preprocessing_warnings or [])
    warnings.extend(adapter_warnings)
    warnings.extend(feature_warnings)
    if aggregate.mape is None:
        warnings.append("MAPE не определена: во всех OOF-фактах нулевые значения.")
    if aggregate.mase is None:
        warnings.append("MASE/RMSSE не определены: train-only seasonal scale равен нулю или истории недостаточно.")
    last_train = len(plan.folds[-1].train_indices)
    preprocessing = (
        dict(fold_preprocessor.summary) if fold_preprocessor is not None else {
            "fit_policy": "none", "evaluation_scale": plan.target_column,
            "source_column": plan.target_column, "target_column": plan.target_column,
        }
    )
    return {
        "model_id": model_id, "model_name": model_name, "family_id": family_id,
        "metrics": aggregate.model_dump(mode="json"),
        "n_train": last_train, "n_test": len(oof),
        "train_ratio": round(last_train / len(values), 12),
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
        "data_source": "session", "status": "success",
        "strategy": plan.strategy, "cohort_id": plan.cohort_id,
        "objective": plan.objective, "cohort_contract": plan.cohort_contract,
        "horizon": plan.horizon, "n_folds": len(plan.folds), "gap": plan.gap,
        "folds": folds, "oof_predictions": oof, "warnings": warnings,
        "preprocessing": preprocessing,
        "execution_contract": execution_contract,
    }


# ---------------------------------------------------------------------------
# Task 132: векторный движок (multivariate models поверх контракта Task 131)
# ---------------------------------------------------------------------------

def _pointwise_vector_metrics(
    actual_matrix: np.ndarray, predicted_matrix: np.ndarray,
    per_series: Mapping[str, Any],
) -> BacktestMetrics:
    """Свести per-series метрики fold'а в один BacktestMetrics.

    MAE/RMSE/MAPE/sMAPE -- поточечный пул по всем сериям (математически
    определён на объединённом наборе OOF-точек); MASE/RMSSE -- среднее
    пер-серийных значений (all-or-none: хоть одна None -- агрегат None,
    частичная подмена запрещена).  Оба подхода редуцируют fold к схеме
    сертифицированной compute_forecast_metrics движка.
    """
    errors = (actual_matrix - predicted_matrix).reshape(-1)
    actual_flat = actual_matrix.reshape(-1)
    predicted_flat = predicted_matrix.reshape(-1)
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(np.square(errors))))
    nonzero = np.abs(actual_flat) > np.finfo(float).eps
    mape = (
        float(np.mean(np.abs(errors[nonzero] / actual_flat[nonzero])) * 100)
        if nonzero.any() else None
    )
    denominator = np.abs(actual_flat) + np.abs(predicted_flat)
    valid_smape = denominator > np.finfo(float).eps
    smape = (
        float(np.mean(200 * np.abs(errors[valid_smape]) / denominator[valid_smape]))
        if valid_smape.any() else 0.0
    )
    mases = [metrics.mase for metrics in per_series.values()]
    rmsses = [metrics.rmsse for metrics in per_series.values()]
    mean_mase = (
        round(float(np.mean([float(v) for v in mases])), 6)
        if all(v is not None for v in mases) else None
    )
    mean_rmsse = (
        round(float(np.mean([float(v) for v in rmsses])), 6)
        if all(v is not None for v in rmsses) else None
    )
    return BacktestMetrics(
        mae=round(mae, 6), rmse=round(rmse, 6),
        mape=round(mape, 6) if mape is not None else None,
        mase=mean_mase,
        smape=round(smape, 6),
        rmsse=mean_rmsse,
        mape_valid_points=int(nonzero.sum()), weighted_score=None,
    )


def _aggregate_vector_metrics(folds: list[dict[str, Any]]) -> BacktestMetrics:
    """Агрегат по folds: пул всех OOF-точек + взвешенные MASE/RMSSE folds.

    Зеркалит сертифицированную _aggregate_metrics univariate-движка:
    поточечные метрики -- пул всех точек, MASE -- взвешенное по n_test
    среднее fold-значений (all-or-none), RMSSE -- корень из взвешенного
    среднего квадратов.
    """
    points = [point for fold in folds for point in fold["predictions"]]
    residuals = np.asarray([point["residual"] for point in points], dtype=float)
    actual_flat = np.asarray([point["actual"] for point in points], dtype=float)
    predicted_flat = np.asarray([point["predicted"] for point in points], dtype=float)
    mae = float(np.mean(np.abs(residuals)))
    rmse = float(np.sqrt(np.mean(np.square(residuals))))
    nonzero = np.abs(actual_flat) > np.finfo(float).eps
    mape = (
        float(np.mean(np.abs(residuals[nonzero] / actual_flat[nonzero])) * 100)
        if nonzero.any() else None
    )
    denominator = np.abs(actual_flat) + np.abs(predicted_flat)
    valid_smape = denominator > np.finfo(float).eps
    smape = (
        float(np.mean(200 * np.abs(residuals[valid_smape]) / denominator[valid_smape]))
        if valid_smape.any() else 0.0
    )
    total = sum(fold["n_test"] for fold in folds)

    def weighted(metric: str) -> Optional[float]:
        values = [(fold["metrics"].get(metric), fold["n_test"]) for fold in folds]
        if any(value is None for value, _ in values):
            return None
        return sum(float(value) * weight for value, weight in values) / total

    aggregate_mase = weighted("mase")
    fold_rmsse = [(fold["metrics"].get("rmsse"), fold["n_test"]) for fold in folds]
    aggregate_rmsse = None
    if all(value is not None for value, _ in fold_rmsse):
        aggregate_rmsse = math.sqrt(
            sum(float(value) ** 2 * weight for value, weight in fold_rmsse) / total
        )
    return BacktestMetrics(
        mae=round(mae, 6), rmse=round(rmse, 6),
        mape=round(mape, 6) if mape is not None else None,
        mase=round(aggregate_mase, 6) if aggregate_mase is not None else None,
        smape=round(float(smape), 6) if smape is not None else 0.0,
        rmsse=round(aggregate_rmsse, 6) if aggregate_rmsse is not None else None,
        mape_valid_points=int(nonzero.sum()), weighted_score=None,
    )


def _aggregate_per_series_metrics(folds: list[dict[str, Any]]) -> dict[str, BacktestMetrics]:
    """Per-series агрегат по folds (пул точек серии; MASE/RMSSE взвешенно)."""
    names = list(folds[0]["per_series_metrics"]) if folds else []
    aggregate: dict[str, BacktestMetrics] = {}
    total = sum(fold["n_test"] for fold in folds)
    for name in names:
        residuals: list[float] = []
        actuals: list[float] = []
        predicted: list[float] = []
        weighted_mase: list[tuple[Optional[float], int]] = []
        weighted_rmsse: list[tuple[Optional[float], int]] = []
        for fold in folds:
            for point in fold["predictions"]:
                if point["series"] == name:
                    residuals.append(float(point["residual"]))
                    actuals.append(float(point["actual"]))
                    predicted.append(float(point["predicted"]))
            weighted_mase.append((fold["per_series_metrics"][name].get("mase"), fold["n_test"]))
            weighted_rmsse.append((fold["per_series_metrics"][name].get("rmsse"), fold["n_test"]))
        errors = np.asarray(residuals, dtype=float)
        actual_flat = np.asarray(actuals, dtype=float)
        predicted_flat = np.asarray(predicted, dtype=float)
        nonzero = np.abs(actual_flat) > np.finfo(float).eps
        denominator = np.abs(actual_flat) + np.abs(predicted_flat)
        valid_smape = denominator > np.finfo(float).eps

        def _weighted(values: list[tuple[Optional[float], int]]) -> Optional[float]:
            if any(value is None for value, _ in values):
                return None
            return sum(
                float(value) * weight for value, weight in values
            ) / total if total else None

        mase_value = _weighted(weighted_mase)
        rmsse_values = _weighted(weighted_rmsse)
        aggregate[name] = BacktestMetrics(
            mae=round(float(np.mean(np.abs(errors))), 6),
            rmse=round(float(np.sqrt(np.mean(np.square(errors)))), 6),
            mape=(
                round(float(np.mean(np.abs(errors[nonzero] / actual_flat[nonzero])) * 100), 6)
                if nonzero.any() else None
            ),
            mase=round(mase_value, 6) if mase_value is not None else None,
            smape=(
                round(float(np.mean(200 * np.abs(errors[valid_smape]) / denominator[valid_smape])), 6)
                if valid_smape.any() else 0.0
            ),
            rmsse=(
                round(math.sqrt(rmsse_values), 6) if rmsse_values is not None else None
            ),
            mape_valid_points=int(nonzero.sum()), weighted_score=None,
        )
    return aggregate


def run_vector_backtest_plan(
    *, model_id: str, model_name: str, family_id: str,
    system: "EndogenousSystem", plan: BacktestPlan,
    seasonal_period: int, params: Optional[Mapping[str, Any]] = None,
    exogenous: Optional[Mapping[str, Sequence[float]]] = None,
    fold_preprocessor: Optional[FoldPreprocessorProtocol] = None,
    preprocessing_warnings: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Векторное исполнение EDA-плана для multivariate-моделей (Task 132/133).

    Зеркалирует run_backtest_plan, но на системе Task 131:
    - fold-local: адаптер получает ТОЛЬКО train-префикс системы
      (EndogenousSystem валидирована, порядок колонок = порядок объявления);
    - OOF-точки -- long-format vector_oof_points (размерность series);
    - метрики -- per-series compute_vector_metrics + агрегированная
      scaled loss (mean пер-серийных MASE, all-or-none);
    - baseline -- persistence каждой серии (VAR(0)-аналог) на ТЕХ ЖЕ
      folds, в evaluation-шкале target-колонки;
    - диагностика fold'а -- fold-local evidence контракта:
      стационарность/коинтеграция train-среза, companion-устойчивость и
      белый шум системы по остаткам адаптера;
    - никакого доступа к тестовым наблюдениям со стороны модели.

    Task 133 (VARX): ``exogenous`` -- future-known экзогенные регрессоры
    ПОЛНОЙ длины системы (та же регулярная сетка).  Движок режет их
    per-fold: train_features = [:n_train], future_features =
    [n_train:n_train+execution_horizon] (регистри-гейт future ⊆ train
    выполняется по построению).  Модели без объявления канала
    (supports_future_features=False, напр. VECM) получают честный
    warning и НЕ получают exog.  Импутация известного будущего запрещена:
    NaN/Inf -- отказ fold'а.
    """
    from apps.api.multivariate_contract import (
        companion_stability,
        compute_vector_metrics,
        fold_cointegration_evidence,
        fold_stationarity_evidence,
        system_white_noise_diagnostics,
        vector_metric_scales,
        vector_oof_points,
        vecm_stability,
    )

    if plan.objective != "multivariate":
        raise BacktestExecutionError(
            "Векторный движок исполняет только multivariate-планы, "
            f"получено objective='{plan.objective}'"
        )
    if int(seasonal_period) != plan.seasonal_period:
        raise BacktestExecutionError(
            "Seasonal period расходится с зафиксированным backtest cohort"
        )
    if system.n_observations != plan.n_observations:
        raise BacktestExecutionError(
            "Длина системы расходится с зафиксированным backtest cohort"
        )
    try:
        execution_contract = MODEL_EXECUTION_REGISTRY.describe(model_id)
    except ValueError as exc:
        raise BacktestExecutionError(str(exc)) from exc
    if execution_contract.get("objective") != "multivariate":
        raise BacktestExecutionError(
            f"Модель '{model_id}' не объявила objective=multivariate"
        )
    if execution_contract.get("input_kind") != "multivariate":
        raise BacktestExecutionError(
            f"Модель '{model_id}' не объявила input_kind=multivariate"
        )

    names = list(system.names)
    target_name = names[0]
    related_names = names[1:]
    target_values = [float(value) for value in system.series[target_name]]
    if not np.isfinite(np.asarray(target_values, dtype=float)).all():
        raise BacktestExecutionError("Система содержит NaN/Inf")
    timestamps = system.timestamps

    warnings: list[str] = list(preprocessing_warnings or [])

    parameters = dict(params or {})
    # ── Task 133: exogenous-канал (VARX) ────────────────────────────────
    exogenous_input = dict(exogenous or {})
    consumed_exogenous: dict[str, list[float]] = {}
    if exogenous_input:
        if execution_contract.get("supports_future_features"):
            system_name_set = set(names)
            for name, column in exogenous_input.items():
                clean_name = str(name).strip()
                if not clean_name:
                    raise BacktestExecutionError(
                        "Имена exogenous-регрессоров не могут быть пустыми"
                    )
                if clean_name in system_name_set:
                    raise BacktestExecutionError(
                        f"Exogenous-колонка '{clean_name}' пересекается с "
                        "endogenous-рядами системы -- двойной учет запрещен"
                    )
                try:
                    values = [float(value) for value in column]
                except (TypeError, ValueError) as exc:
                    raise BacktestExecutionError(
                        f"Exogenous-колонка '{clean_name}' должна быть числовой"
                    ) from exc
                if len(values) != system.n_observations:
                    raise BacktestExecutionError(
                        f"Exogenous-колонка '{clean_name}': длина {len(values)} "
                        f"не равна длине системы {system.n_observations}"
                    )
                if not np.isfinite(np.asarray(values, dtype=float)).all():
                    raise BacktestExecutionError(
                        f"Exogenous-колонка '{clean_name}' содержит NaN/Inf -- "
                        "импутация известного будущего запрещена (fail-closed)"
                    )
                consumed_exogenous[clean_name] = values
        else:
            warnings.append(
                f"Экзогенные регрессоры {sorted(exogenous_input)} не применены: "
                f"модель '{model_id}' не поддерживает exogenous-канал (VARX)."
            )
    if plan.feature_plan is not None and plan.feature_plan.features \
            and not consumed_exogenous:
        warnings.append(
            f"FeaturePlan '{plan.feature_plan.plan_id}' не применен: векторный "
            f"контракт модели '{model_id}' не принимает регрессоры "
            "(exogenous-канал VARX доступен только моделям с "
            "supports_future_features); полная история в fold-матрицах аудита"
        )

    folds: list[dict[str, Any]] = []
    started = time.monotonic()
    for fold in plan.folds:
        fold_started = time.monotonic()
        n_train = len(fold.train_indices)
        n_test = len(fold.test_indices)
        if fold.train_indices != list(range(n_train)):
            raise BacktestExecutionError(
                f"Fold {fold.fold}: train-срез векторной модели должен быть "
                "непрерывным префиксом системы (упорядоченная общая сетка)"
            )
        if min(fold.test_indices) <= fold.train_indices[-1]:
            raise BacktestExecutionError(
                f"Fold {fold.fold}: тестовые наблюдения не могут пересекать train-срез"
            )
        execution_horizon = fold.gap + n_test
        try:
            related_train = {
                name: [float(value) for value in system.series[name][:n_train]]
                for name in related_names
            }
            # Task 133 (VARX): per-fold срезы future-known экзогенных
            # колонок.  Полная длина колонки валидирована выше; future-часть
            # [n_train:n_train+execution_horizon] покрывает gap+n_test.
            exog_train: dict[str, list[float]] = {}
            exog_future: dict[str, list[float]] = {}
            if consumed_exogenous:
                exog_train = {
                    name: column[:n_train]
                    for name, column in consumed_exogenous.items()
                }
                exog_future = {
                    name: column[n_train:n_train + execution_horizon]
                    for name, column in consumed_exogenous.items()
                }
                if any(
                    len(column) != execution_horizon
                    for column in exog_future.values()
                ):
                    raise BacktestExecutionError(
                        "Future-часть exogenous-колонок не покрывает "
                        "горизонт fold'а (gap+test)"
                    )
            if fold_preprocessor is None:
                model_train_target = target_values[:n_train]
                eval_train_target = list(model_train_target)
                eval_actual_target = [
                    float(target_values[index]) for index in fold.test_indices
                ]
                restore_forecast = lambda forecast: forecast  # noqa: E731
            else:
                prepared = fold_preprocessor.prepare(target_values, fold)
                model_train_target = prepared.model_train
                eval_train_target = prepared.evaluation_train
                eval_actual_target = prepared.evaluation_actual
                restore_forecast = prepared.restore_forecast
            if len(model_train_target) != n_train:
                raise BacktestExecutionError(
                    "Preprocessing вернул неверную длину train-среза target"
                )
            execution_result = MODEL_EXECUTION_REGISTRY.execute(
                model_id,
                ModelExecutionRequest(
                    target=model_train_target,
                    horizon=execution_horizon,
                    objective="multivariate",
                    seasonal_period=seasonal_period,
                    params=parameters,
                    related_series=related_train,
                    train_features=exog_train,
                    future_features=exog_future,
                ),
            )
            metadata = execution_result.metadata
            warnings.extend(execution_result.warnings)
            vector_forecast = np.asarray(
                metadata.get("vector_forecast"), dtype=float,
            )
            if vector_forecast.shape != (execution_horizon, len(names)):
                raise BacktestExecutionError(
                    "Адаптер вернул векторный прогноз неверной формы "
                    f"{vector_forecast.shape}, ожидалось "
                    f"({execution_horizon}, {len(names)})"
                )
            restored_target = restore_forecast(
                [float(value) for value in vector_forecast[:, 0]],
            )
            if len(restored_target) != execution_horizon:
                raise BacktestExecutionError(
                    "Preprocessing вернул неверную длину восстановления прогноза"
                )
            predicted_matrix = np.column_stack(
                [np.asarray(restored_target, dtype=float), vector_forecast[:, 1:]],
            ) if related_names else np.asarray(restored_target, dtype=float).reshape(-1, 1)
            actual_matrix = np.column_stack(
                [np.asarray(eval_actual_target, dtype=float),
                 np.column_stack([
                     np.asarray([system.series[name][index] for index in fold.test_indices],
                                dtype=float)
                     for name in related_names
                 ])] if related_names else [np.asarray(eval_actual_target, dtype=float)],
            )
            y_pred_matrix = predicted_matrix[fold.gap:]
            actual_window = actual_matrix
            if actual_window.shape != (n_test, len(names)):
                raise BacktestExecutionError(
                    f"Форма фактов тест-горизонта {actual_window.shape} не "
                    f"соответствует (n_test={n_test}, K={len(names)})"
                )
            # Train-матрица в evaluation-шкале: знаменатели MASE/RMSSE и
            # fold-local evidence считаются только на train-срезе.
            eval_train_matrix = np.column_stack(
                [np.asarray(eval_train_target, dtype=float),
                 np.column_stack([
                     np.asarray([system.series[name][index] for index in fold.train_indices],
                                dtype=float)
                     for name in related_names
                 ])] if related_names else [np.asarray(eval_train_target, dtype=float)],
            )
            scales = vector_metric_scales(
                eval_train_matrix, names, seasonal_period=seasonal_period,
            )
            metrics = compute_vector_metrics(
                actual_window, y_pred_matrix, names,
                mase_scales={
                    name: scales[name]["mase_scale"] for name in names
                },
                rmsse_scales={
                    name: scales[name]["rmsse_scale"] for name in names
                },
            )
            point_labels = (
                [timestamps[index] for index in fold.test_indices]
                if timestamps else None
            )
            predictions = vector_oof_points(
                fold.fold, fold.test_indices, actual_window, y_pred_matrix,
                names, labels=point_labels,
            )
            # Многомерный baseline: persistence каждой серии от последнего
            # train-наблюдения (evaluation-шкала target), те же folds.
            last_values = [float(eval_train_target[-1])] + [
                float(system.series[name][n_train - 1]) for name in related_names
            ]
            baseline_matrix = np.asarray([last_values] * execution_horizon, dtype=float)
            baseline_metrics = compute_vector_metrics(
                actual_window, baseline_matrix[fold.gap:], names,
                mase_scales={
                    name: scales[name]["mase_scale"] for name in names
                },
                rmsse_scales={
                    name: scales[name]["rmsse_scale"] for name in names
                },
            )
            baseline_predictions = vector_oof_points(
                fold.fold, fold.test_indices, actual_window,
                baseline_matrix[fold.gap:], names, labels=point_labels,
            )
            # Fold-local evidence контракта (advisory, только train-срез).
            stationarity_evidence = fold_stationarity_evidence(
                eval_train_matrix, names,
            )
            cointegration_evidence = fold_cointegration_evidence(
                eval_train_matrix, det_order=0, k_ar_diff=1,
            )
            lag_order = int(metadata.get("lag_order") or 0)
            coefficient_matrices = [
                np.asarray(block, dtype=float)
                for block in metadata.get("coefficient_matrices") or []
            ]
            # Task 133: модель-специфичный блок диагностики.  VECM --
            # vecm_stability (ровно K - coint_rank единичных корней
            # companion уровневого VAR-представления; спектральная теорема
            # Granger-представления, пересертификация Task 133);
            # VAR -- companion_stability.
            if "k_ar_diff" in metadata:
                model_diagnostics = {
                    "vecm": {
                        "k_ar_diff": int(metadata["k_ar_diff"]),
                        "coint_rank": int(metadata.get("coint_rank") or 0),
                        "rank_selection": metadata.get("rank_selection"),
                        "deterministic_terms": metadata.get("deterministic_terms"),
                        "alpha": metadata.get("alpha"),
                        "nobs": metadata.get("nobs"),
                        **vecm_stability(
                            coefficient_matrices,
                            coint_rank=int(metadata.get("coint_rank") or 0),
                        ),
                    },
                }
            else:
                stability = companion_stability(coefficient_matrices)
                model_diagnostics = {
                    "var": {
                        "lag_order": lag_order,
                        "lag_selection": metadata.get("lag_selection"),
                        "trend": metadata.get("trend"),
                        "alpha": metadata.get("alpha"),
                        "nobs": metadata.get("nobs"),
                        "is_stable": stability["is_stable"],
                        "max_modulus": stability["max_modulus"],
                    },
                }
            residuals_insample = np.asarray(
                metadata.get("in_sample_residuals"), dtype=float,
            )
            # nlags строго больше порядка модели (контракт Portmanteau);
            # нижняя граница 8 -- стандартная ширина окна проверки.
            # Пересертификация Task 133: VECM не имеет ключа lag_order --
            # белый шум системы обязан учитывать фактический порядок
            # модели: окно задаёт уровневый порядок k_ar_diff+1, а df несёт
            # поправку на restricted-параметры ранга K*coint_rank (паритет
            # df с statsmodels VECMResults.test_whiteness).
            if "k_ar_diff" in metadata:
                vecm_model_order = int(metadata["k_ar_diff"]) + 1
                white_noise = system_white_noise_diagnostics(
                    residuals_insample,
                    nlags=max(vecm_model_order + 1, min(8, vecm_model_order + 3)),
                    fitted_var_order=int(metadata["k_ar_diff"]),
                    rank_adjustment=len(names) * int(metadata.get("coint_rank") or 0),
                )
            else:
                nlags = max(lag_order + 1, min(8, lag_order + 3))
                white_noise = system_white_noise_diagnostics(
                    residuals_insample, nlags=nlags,
                    fitted_var_order=lag_order,
                )
        except Exception as exc:
            raise BacktestExecutionError(
                f"{model_name}: fold {fold.fold} завершился ошибкой: {exc}"
            ) from exc
        per_series_dump = {
            name: metric.model_dump(mode="json")
            for name, metric in metrics["per_series"].items()
        }
        baseline_series_dump = {
            name: metric.model_dump(mode="json")
            for name, metric in baseline_metrics["per_series"].items()
        }
        folds.append({
            "fold": fold.fold, "status": "success",
            "train_start": fold.train_indices[0], "train_end": fold.train_indices[-1],
            "test_start": fold.test_indices[0], "test_end": fold.test_indices[-1],
            "gap": fold.gap, "n_train": n_train, "n_test": n_test,
            "train_start_label": fold.train_start_label or (
                timestamps[fold.train_indices[0]] if timestamps else str(fold.train_indices[0])
            ),
            "train_end_label": fold.train_end_label or (
                timestamps[fold.train_indices[-1]] if timestamps else str(fold.train_indices[-1])
            ),
            "test_start_label": fold.test_start_label or (
                timestamps[fold.test_indices[0]] if timestamps else str(fold.test_indices[0])
            ),
            "test_end_label": fold.test_end_label or (
                timestamps[fold.test_indices[-1]] if timestamps else str(fold.test_indices[-1])
            ),
            "metrics": _pointwise_vector_metrics(
                actual_window, y_pred_matrix, metrics["per_series"],
            ).model_dump(mode="json"),
            "predictions": predictions,
            "per_series_metrics": per_series_dump,
            "scaled_loss": metrics["scaled_loss"],
            "vector_baseline": {
                "fold": fold.fold,
                "metrics": _pointwise_vector_metrics(
                    actual_window, baseline_matrix[fold.gap:],
                    baseline_metrics["per_series"],
                ).model_dump(mode="json"),
                "per_series_metrics": baseline_series_dump,
                "scaled_loss": baseline_metrics["scaled_loss"],
                "predictions": baseline_predictions,
            },
            "multivariate_diagnostics": {
                **model_diagnostics,
                "stationarity_evidence": stationarity_evidence,
                "cointegration_evidence": cointegration_evidence,
                "companion_stability": (
                    model_diagnostics["vecm"]
                    if "vecm" in model_diagnostics else stability
                ),
                "white_noise": white_noise,
                "exogenous": (
                    {"names": sorted(consumed_exogenous),
                     "n_exog": len(consumed_exogenous)}
                    if consumed_exogenous else None
                ),
            },
            "mase_scale": None, "rmsse_scale": None,
            "feature_matrix": None, "feature_importance": None,
            "duration_ms": round((time.monotonic() - fold_started) * 1000, 3),
            "error": None,
        })
    aggregate = _aggregate_vector_metrics(folds)
    per_series_aggregate = _aggregate_per_series_metrics(folds)
    oof = [point for fold in folds for point in fold["predictions"]]
    scaled_losses = [fold["scaled_loss"] for fold in folds]
    aggregate_scaled_loss = (
        round(
            float(np.average(
                [float(value) for value in scaled_losses],
                weights=[fold["n_test"] for fold in folds],
            )),
            6,
        )
        if all(value is not None for value in scaled_losses) else None
    )
    baseline_losses = [fold["vector_baseline"]["scaled_loss"] for fold in folds]
    baseline_aggregate_scaled_loss = (
        round(
            float(np.average(
                [float(value) for value in baseline_losses],
                weights=[fold["n_test"] for fold in folds],
            )),
            6,
        )
        if all(value is not None for value in baseline_losses) else None
    )
    warnings = list(warnings)
    if aggregate.mape is None:
        warnings.append("MAPE не определена: во всех OOF-фактах нулевые значения.")
    if aggregate_scaled_loss is None:
        warnings.append(
            "Scaled loss не определена: хотя бы одна серия не имеет train-only "
            "MASE-масштаба (константный train)."
        )
    last_train = len(plan.folds[-1].train_indices)
    preprocessing = (
        dict(fold_preprocessor.summary) if fold_preprocessor is not None else {
            "fit_policy": "none", "evaluation_scale": plan.target_column,
            "source_column": plan.target_column, "target_column": plan.target_column,
        }
    )
    return {
        "model_id": model_id, "model_name": model_name, "family_id": family_id,
        "metrics": aggregate.model_dump(mode="json"),
        "per_series_metrics": {
            name: metric.model_dump(mode="json")
            for name, metric in per_series_aggregate.items()
        },
        "scaled_loss": aggregate_scaled_loss,
        "vector_baseline": {
            "aggregate": _aggregate_vector_metrics([
                {"predictions": fold["vector_baseline"]["predictions"],
                 "metrics": fold["vector_baseline"]["metrics"],
                 "n_test": fold["n_test"]}
                for fold in folds
            ]).model_dump(mode="json"),
            "folds": [
                {"fold": fold["fold"], "metrics": fold["vector_baseline"]["metrics"],
                 "scaled_loss": fold["vector_baseline"]["scaled_loss"]}
                for fold in folds
            ],
            "scaled_loss": baseline_aggregate_scaled_loss,
        },
        "n_train": last_train, "n_test": len(oof),
        "train_ratio": round(last_train / len(target_values), 12),
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
        "data_source": "session", "status": "success",
        "strategy": plan.strategy, "cohort_id": plan.cohort_id,
        "objective": plan.objective, "cohort_contract": plan.cohort_contract,
        "horizon": plan.horizon, "n_folds": len(plan.folds), "gap": plan.gap,
        "folds": folds, "oof_predictions": oof, "warnings": warnings,
        "preprocessing": preprocessing,
        "execution_contract": execution_contract,
    }


# ---------------------------------------------------------------------------
# Task 135: volatility-движок (исполнитель контракта волатильности Task 134)
# ---------------------------------------------------------------------------

def run_volatility_backtest_plan(
    *, model_id: str, model_name: str, family_id: str,
    target: "VolatilityTarget", plan: BacktestPlan,
    seasonal_period: int, params: Optional[Mapping[str, Any]] = None,
    preprocessing_warnings: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Исполнение EDA-плана volatility-моделей (Task 135, зеркало
    run_vector_backtest_plan Task 132, но на контракте Task 134):

    - гейт: исполняются ТОЛЬКО планы objective="volatility" -- «GARCH
      нельзя ранжировать рядом с ETS/ARIMA» (одномерный движок уровня
      отказывает volatility-планам, см. Task 134);
    - fold-local: адаптер через реестр получает ТОЛЬКО train-префикс
      returns (VolatilityTarget; полная история недостижима);
    - OOF-точки -- VOLATILITY_OOF_POINT_KEYS: actual = realized proxy
      (квадрат return тест-окна), predicted = прогноз условной дисперсии,
      label = timestamps[i+1] (return i реализуется между t[i] и t[i+1]);
    - метрики -- compute_volatility_metrics (QLIKE primary, fail-closed
      без clamp) + агрегация aggregate_volatility_metrics (взвешивание
      по n_test, rmse -- корень из взвешенного MSE);
    - baseline -- EWMA RiskMetrics (volatility_naive_baseline) на ТЕХ ЖЕ
      folds; decay -- из cohort-контракта (все модели cohort'а обязаны
      сравниваться против одного baseline);
    - диагностика fold'а -- standardized_residual_diagnostics по
      стандартизованным остаткам адаптера + a priori
      volatility_clustering_evidence train-среза (advisory);
    - никакого доступа к тестовым наблюдениям со стороны модели.
    """
    from apps.api.volatility_contract import (
        REALIZED_PROXIES,
        VOLATILITY_OOF_POINT_KEYS,
        VolatilityContractError,
        aggregate_volatility_metrics,
        compute_volatility_metrics,
        realized_variance_proxy,
        standardized_residual_diagnostics,
        volatility_clustering_evidence,
        volatility_naive_baseline,
    )

    if plan.objective != "volatility":
        raise BacktestExecutionError(
            "Volatility-движок исполняет только volatility-планы, "
            f"получено objective='{plan.objective}'"
        )
    if int(seasonal_period) != plan.seasonal_period:
        raise BacktestExecutionError(
            "Seasonal period расходится с зафиксированным backtest cohort"
        )
    if target.n_returns != plan.n_observations:
        raise BacktestExecutionError(
            f"Длина returns ({target.n_returns}) расходится с длиной "
            f"зафиксированного backtest cohort ({plan.n_observations})"
        )
    try:
        execution_contract = MODEL_EXECUTION_REGISTRY.describe(model_id)
    except ValueError as exc:
        raise BacktestExecutionError(str(exc)) from exc
    if execution_contract.get("objective") != "volatility":
        raise BacktestExecutionError(
            f"Модель '{model_id}' не объявила objective=volatility"
        )
    if execution_contract.get("input_kind") != "univariate":
        raise BacktestExecutionError(
            f"Модель '{model_id}' объявила input_kind="
            f"'{execution_contract.get('input_kind')}', ожидался univariate"
        )

    cohort_contract = plan.cohort_contract or {}
    volatility_policy = (
        cohort_contract.get("metric_policy", {}).get("volatility") or {}
    )
    proxy = volatility_policy.get("realized_proxy")
    if proxy is None:
        raise BacktestExecutionError(
            "Cohort-контракт не объявляет realized_proxy: подмена proxy "
            "между моделями запрещена (all-or-none контракта Task 134)"
        )
    if proxy not in REALIZED_PROXIES:
        raise BacktestExecutionError(
            f"Неизвестный realized proxy {proxy!r} в cohort-контракте"
        )
    baseline_config = volatility_policy.get("baseline") or {}
    if baseline_config.get("type") != "ewma_riskmetrics":
        raise BacktestExecutionError(
            "Cohort-контракт не объявляет EWMA-baseline: volatility-движок "
            "сравнивает модели только против собственного baseline cohort'а"
        )
    try:
        decay = float(baseline_config["decay"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BacktestExecutionError(
            "Cohort-контракт не фиксирует decay EWMA-baseline"
        ) from exc

    returns = target.returns_array
    if not np.isfinite(returns).all():
        raise BacktestExecutionError("Returns содержат NaN/Inf")
    timestamps = target.timestamps
    warnings: list[str] = list(preprocessing_warnings or [])
    parameters = dict(params or {})

    def _oof_points(
        fold_number: int, fold_plan: BacktestFoldPlan,
        realized: np.ndarray, predicted: np.ndarray,
    ) -> list[dict[str, Any]]:
        points: list[dict[str, Any]] = []
        for step, index in enumerate(fold_plan.test_indices, 1):
            label = (
                timestamps[index + 1] if timestamps is not None else None
            )
            actual_value = float(realized[step - 1])
            predicted_value = float(predicted[step - 1])
            points.append({
                "fold": int(fold_number),
                "horizon_step": step,
                "index": int(index),
                "label": None if label is None else str(label),
                "series": None,
                "actual": actual_value,
                "predicted": predicted_value,
                "residual": round(actual_value - predicted_value, 12),
            })
        return points

    folds: list[dict[str, Any]] = []
    started = time.monotonic()
    for fold in plan.folds:
        fold_started = time.monotonic()
        n_train = len(fold.train_indices)
        n_test = len(fold.test_indices)
        if fold.train_indices != list(range(n_train)):
            raise BacktestExecutionError(
                f"Fold {fold.fold}: train-срез volatility-модели должен быть "
                "непрерывным префиксом returns (упорядоченная общая сетка)"
            )
        if min(fold.test_indices) <= fold.train_indices[-1]:
            raise BacktestExecutionError(
                f"Fold {fold.fold}: тестовые наблюдения не могут пересекать "
                "train-срез"
            )
        execution_horizon = fold.gap + n_test
        try:
            train_returns = target.train_slice(n_train)
            # A priori evidence кластеризации волатильности (advisory,
            # только train-срез; источник data.has_volatility_clustering).
            clustering_evidence = volatility_clustering_evidence(
                train_returns, nlags=8,
            )
            execution_result = MODEL_EXECUTION_REGISTRY.execute(
                model_id,
                ModelExecutionRequest(
                    target=[float(value) for value in train_returns],
                    horizon=execution_horizon,
                    objective="volatility",
                    seasonal_period=seasonal_period,
                    params=parameters,
                ),
            )
            warnings.extend(execution_result.warnings)
            metadata = execution_result.metadata
            variance_forecast = np.asarray(
                execution_result.forecast, dtype=float,
            )
            if variance_forecast.shape != (execution_horizon,):
                raise BacktestExecutionError(
                    "Адаптер вернул прогноз дисперсии неверной формы "
                    f"{variance_forecast.shape}, ожидалось "
                    f"({execution_horizon},)"
                )
            if (variance_forecast <= 0).any():
                raise BacktestExecutionError(
                    "Прогноз дисперсии содержит sigma2 <= 0 -- подмена "
                    "target запрещена (fail-closed контракта Task 134)"
                )
            predicted = variance_forecast[fold.gap:]
            test_returns = target.test_slice(
                fold.test_indices[0], fold.test_indices[-1] + 1,
            )
            realized = realized_variance_proxy(test_returns, proxy=proxy)
            metrics = compute_volatility_metrics(
                realized, predicted, proxy=proxy,
            )
            metrics = {
                key: (
                    round(float(value), 6)
                    if key in {"qlike", "rmse", "mae"} else value
                )
                for key, value in metrics.items()
            }
            # Собственный volatility baseline cohort'а: EWMA RiskMetrics на
            # train-префиксе fold'а, плоское продление горизонта.
            baseline_forecast = np.asarray(
                volatility_naive_baseline(
                    train_returns, execution_horizon, decay=decay,
                ),
                dtype=float,
            )
            baseline_predicted = baseline_forecast[fold.gap:]
            baseline_metrics = compute_volatility_metrics(
                realized, baseline_predicted, proxy=proxy,
            )
            baseline_metrics = {
                key: (
                    round(float(value), 6)
                    if key in {"qlike", "rmse", "mae"} else value
                )
                for key, value in baseline_metrics.items()
            }
            point_labels = (
                [timestamps[index + 1] for index in fold.test_indices]
                if timestamps is not None else None
            )
            predictions = _oof_points(
                fold.fold, fold, realized, predicted,
            )
            baseline_predictions = _oof_points(
                fold.fold, fold, realized, baseline_predicted,
            )
            # Diagnostics: стандартизованные остатки адаптера (LB/LB^2/
            # ARCH-LM) + GARCH-блок MLE.  nlags=8 -- стандартная ширина
            # окна проверки; контракт требует len(z) > nlags.
            z = np.asarray(metadata.get("std_residuals"), dtype=float)
            residual_diagnostics = standardized_residual_diagnostics(
                z, nlags=8,
            )
            garch_block = {
                "params": metadata.get("params"),
                "persistence": metadata.get("persistence"),
                "is_covariance_stationary": metadata.get(
                    "is_covariance_stationary",
                ),
                "convergence_flag": metadata.get("convergence_flag"),
                "nobs": metadata.get("nobs"),
                "loglikelihood": metadata.get("loglikelihood"),
                "aic": metadata.get("aic"),
                "bic": metadata.get("bic"),
                "mean_model": metadata.get("mean_model"),
                "dist": metadata.get("dist"),
                "intervals": metadata.get("intervals"),
                "deterministic": metadata.get("deterministic"),
            }
        except (VolatilityContractError, ValueError) as exc:
            raise BacktestExecutionError(
                f"{model_name}: fold {fold.fold} завершился ошибкой: {exc}"
            ) from exc
        folds.append({
            "fold": fold.fold, "status": "success",
            "train_start": fold.train_indices[0],
            "train_end": fold.train_indices[-1],
            "test_start": fold.test_indices[0],
            "test_end": fold.test_indices[-1],
            "gap": fold.gap, "n_train": n_train, "n_test": n_test,
            "train_start_label": fold.train_start_label or (
                timestamps[fold.train_indices[0] + 1]
                if timestamps else str(fold.train_indices[0])
            ),
            "train_end_label": fold.train_end_label or (
                timestamps[fold.train_indices[-1] + 1]
                if timestamps else str(fold.train_indices[-1])
            ),
            "test_start_label": fold.test_start_label or (
                timestamps[fold.test_indices[0] + 1]
                if timestamps else str(fold.test_indices[0])
            ),
            "test_end_label": fold.test_end_label or (
                timestamps[fold.test_indices[-1] + 1]
                if timestamps else str(fold.test_indices[-1])
            ),
            "metrics": {
                "mae": metrics["mae"], "rmse": metrics["rmse"],
                "mape": None, "mase": None, "smape": None, "rmsse": None,
                "mape_valid_points": 0, "weighted_score": None,
                "qlike": metrics["qlike"],
                "realized_proxy": proxy,
            },
            "predictions": predictions,
            "per_series_metrics": None, "scaled_loss": None,
            "volatility_baseline": {
                "fold": fold.fold,
                "metrics": {
                    "mae": baseline_metrics["mae"],
                    "rmse": baseline_metrics["rmse"],
                    "mape": None, "mase": None, "smape": None, "rmsse": None,
                    "mape_valid_points": 0, "weighted_score": None,
                    "qlike": baseline_metrics["qlike"],
                    "realized_proxy": proxy,
                },
                "realized_proxy": proxy,
                "baseline_type": "ewma_riskmetrics",
                "decay": decay,
                "predictions": baseline_predictions,
            },
            "volatility_diagnostics": {
                "garch": garch_block,
                "standardized_residuals": residual_diagnostics,
                "volatility_clustering_evidence": clustering_evidence,
                "realized_proxy": proxy,
            },
            "mase_scale": None, "rmsse_scale": None,
            "feature_matrix": None, "feature_importance": None,
            "duration_ms": round((time.monotonic() - fold_started) * 1000, 3),
            "error": None,
        })

    aggregate = aggregate_volatility_metrics(folds)
    baseline_aggregate = aggregate_volatility_metrics([
        {
            "metrics": fold["volatility_baseline"]["metrics"],
            "n_test": fold["n_test"],
        }
        for fold in folds
    ])
    oof = [point for fold in folds for point in fold["predictions"]]
    last_train = len(plan.folds[-1].train_indices)
    return {
        "model_id": model_id, "model_name": model_name, "family_id": family_id,
        "metrics": {
            "mae": aggregate["mae"], "rmse": aggregate["rmse"],
            "mape": None, "mase": None, "smape": None, "rmsse": None,
            "mape_valid_points": 0, "weighted_score": None,
            "qlike": aggregate["qlike"],
            "primary": aggregate["primary"],
            "realized_proxy": aggregate["realized_proxy"],
            "aggregation": aggregate["aggregation"],
            "n_points": aggregate["n_points"],
        },
        "per_series_metrics": None, "scaled_loss": None,
        "volatility_baseline": {
            "aggregate": {
                "mae": baseline_aggregate["mae"],
                "rmse": baseline_aggregate["rmse"],
                "qlike": baseline_aggregate["qlike"],
                "realized_proxy": baseline_aggregate["realized_proxy"],
                "aggregation": baseline_aggregate["aggregation"],
            },
            "folds": [
                {"fold": fold["fold"],
                 "metrics": fold["volatility_baseline"]["metrics"]}
                for fold in folds
            ],
            "predictions": [
                point
                for fold in folds
                for point in fold["volatility_baseline"]["predictions"]
            ],
        },
        "n_train": last_train, "n_test": len(oof),
        "train_ratio": round(last_train / target.n_returns, 12),
        "duration_ms": round((time.monotonic() - started) * 1000, 3),
        "data_source": "session", "status": "success",
        "strategy": plan.strategy, "cohort_id": plan.cohort_id,
        "objective": plan.objective, "cohort_contract": plan.cohort_contract,
        "horizon": plan.horizon, "n_folds": len(plan.folds), "gap": plan.gap,
        "folds": folds, "oof_predictions": oof, "warnings": warnings,
        "preprocessing": {
            "fit_policy": "none", "evaluation_scale": target.method,
            "source_column": plan.target_column,
            "target_column": plan.target_column,
            "returns_method": target.method,
        },
        "execution_contract": execution_contract,
    }
