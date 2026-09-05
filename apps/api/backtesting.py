"""Leakage-safe rolling-origin backtest engine.

The EDA validation strategy owns fold boundaries.  This module validates and
executes that immutable plan for every production model.  Predictors receive
only the train slice and forecast a fixed multi-step horizon; test observations
are never passed to model code.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import time
from typing import Any, Callable, Mapping, Optional, Protocol

import numpy as np

from apps.api.model_execution import (
    LegacyPredictor as Predictor,
    MODEL_EXECUTION_CONTRACT_VERSION,
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionRequest,
    fixed_origin_baseline_predict,
    legacy_predictor_registry,
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
) -> BacktestPlan:
    """Validate and freeze the exact folds produced by EDA."""
    strategy = str(validation.get("strategy", ""))
    if strategy not in {"single", "expanding", "sliding"}:
        raise BacktestExecutionError(f"Неподдерживаемая стратегия бэктеста: {strategy!r}")
    horizon = int(validation.get("horizon") or 0)
    gap = int(validation.get("gap") or 0)
    metric_period = int(seasonal_period)
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
    payload = {
        "fingerprint": fingerprint, "target_column": target_column,
        "strategy": strategy, "horizon": horizon, "gap": gap,
        "metric_seasonal_period": metric_period,
        "preprocessing_signature": preprocessing_signature,
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


def run_backtest_plan(
    *, model_id: str, model_name: str, family_id: str,
    series: list[float], labels: list[str], plan: BacktestPlan,
    seasonal_period: int, params: Optional[Mapping[str, Any]] = None,
    predictors: Optional[Mapping[str, Predictor]] = None,
    preprocessing_warnings: Optional[list[str]] = None,
    fold_preprocessor: Optional[FoldPreprocessorProtocol] = None,
) -> dict[str, Any]:
    """Execute every EDA fold with strict, fixed-origin model predictions."""
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
            "adapter_version": "compat-v1",
            "input_kind": "univariate",
            "output_kind": "point",
            "fit_policy": "per_train_fold",
            "actions": ["backtest"],
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
    folds: list[dict[str, Any]] = []
    adapter_warnings: list[str] = []
    started = time.monotonic()
    for fold in plan.folds:
        raw_train = [values[index] for index in fold.train_indices]
        fold_started = time.monotonic()
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
                execution_result = MODEL_EXECUTION_REGISTRY.execute(
                    model_id,
                    ModelExecutionRequest(
                        target=y_train,
                        horizon=execution_horizon,
                        seasonal_period=seasonal_period,
                        params=parameters,
                        train_timestamps=train_timestamps,
                        future_timestamps=future_timestamps,
                    ),
                )
                model_forecast = list(execution_result.forecast)
                adapter_warnings.extend(execution_result.warnings)
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
            "duration_ms": round((time.monotonic() - fold_started) * 1000, 3),
            "error": None,
        })
    aggregate = _aggregate_metrics(folds)
    oof = [point for fold in folds for point in fold["predictions"]]
    warnings: list[str] = list(preprocessing_warnings or [])
    warnings.extend(adapter_warnings)
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
        "horizon": plan.horizon, "n_folds": len(plan.folds), "gap": plan.gap,
        "folds": folds, "oof_predictions": oof, "warnings": warnings,
        "preprocessing": preprocessing,
        "execution_contract": execution_contract,
    }
