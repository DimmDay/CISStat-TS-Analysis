"""Leakage-safe target preprocessing for Modeling folds.

Preprocessing tabs persist recipes and diagnostic full-history previews.  This
module reconstructs the selected target from its raw source and fits every
estimated parameter on the train slice of each immutable BacktestPlan fold.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.preprocessing import (
    MaxAbsScaler,
    MinMaxScaler,
    QuantileTransformer,
    RobustScaler,
    StandardScaler,
)

from app.core.passport import prepare_passport_series
from app.preprocessing.smoothing import CAUSAL_METHODS, apply_smoothing_series
from app.preprocessing.stationarity import (
    STATIONARITY_TRANSFORM_METHODS,
    apply_stationarity_series,
)
from app.preprocessing.transforms import (
    VARIANCE_TRANSFORM_METHODS,
    apply_variance_transform,
    inverse_variance_transform,
)
from apps.api.backtesting import BacktestExecutionError, BacktestFoldPlan


@dataclass
class PreparedFold:
    model_train: list[float]
    evaluation_train: list[float]
    evaluation_actual: list[float]
    restore_forecast: Callable[[list[float]], list[float]]


@dataclass
class PreparedModelingTarget:
    series: list[float]
    labels: list[str]
    source_column: str
    target_column: str
    fold_preprocessor: "FoldLocalTargetPreprocessor | None"
    warnings: list[str]
    preprocessing_signature: str


def _transform_kind(metadata: Mapping[str, Any]) -> str:
    kind = str(metadata.get("kind") or "")
    method = str(metadata.get("method") or "")
    if kind:
        return kind
    if method in VARIANCE_TRANSFORM_METHODS:
        return "variance"
    if method in STATIONARITY_TRANSFORM_METHODS:
        return "stationarity"
    return "unknown"


def _resolve_chain(
    transformations: Mapping[str, Mapping[str, Any]], target_column: str,
) -> tuple[str, list[dict[str, Any]]]:
    chain: list[dict[str, Any]] = []
    current = target_column
    seen: set[str] = set()
    while current in transformations:
        if current in seen:
            raise BacktestExecutionError("Цепочка preprocessing target содержит цикл")
        seen.add(current)
        metadata = dict(transformations[current])
        source = metadata.get("source_column")
        if not isinstance(source, str) or not source or source == current:
            raise BacktestExecutionError(
                f"Для производной цели '{current}' не сохранён корректный source_column; "
                "fit внутри train fold невозможен"
            )
        metadata["output_column"] = current
        metadata["source_column"] = source
        chain.append(metadata)
        current = source
    chain.reverse()
    return current, chain


def _make_scaler(recipe: Mapping[str, Any], n_samples: int):
    method = str(recipe.get("method") or "")
    parameters = dict(recipe.get("parameters") or {})
    if method == "standard":
        return StandardScaler(
            with_mean=bool(parameters.get("with_mean", True)),
            with_std=bool(parameters.get("with_std", True)),
        )
    if method == "minmax":
        bounds = tuple(parameters.get("feature_range", (0.0, 1.0)))
        return MinMaxScaler(feature_range=bounds, clip=bool(parameters.get("clip", False)))
    if method == "robust":
        bounds = tuple(parameters.get("quantile_range", (25.0, 75.0)))
        return RobustScaler(
            with_centering=bool(parameters.get("with_centering", True)),
            with_scaling=bool(parameters.get("with_scaling", True)),
            quantile_range=bounds,
            unit_variance=bool(parameters.get("unit_variance", False)),
        )
    if method == "maxabs":
        return MaxAbsScaler()
    if method == "quantile":
        requested = int(parameters.get("n_quantiles", 1000))
        return QuantileTransformer(
            n_quantiles=min(requested, n_samples),
            output_distribution=str(parameters.get("output_distribution", "normal")),
            random_state=int(parameters.get("random_state", 0)), copy=True,
        )
    raise BacktestExecutionError(f"Неподдерживаемый fold-local scaler: {method!r}")


def _stationarity_forward(
    values: np.ndarray, method: str, state: Mapping[str, Any],
) -> np.ndarray:
    if method == "linear_detrend":
        x = np.arange(len(values), dtype=float)
        return values - (
            float(state["trend_intercept"]) + float(state["trend_slope"]) * x
        )
    period = int(state.get("seasonal_period") or 1)
    if method == "first_difference":
        return np.diff(values, n=1)
    if method == "second_difference":
        return np.diff(values, n=2)
    if method == "seasonal_difference":
        return values[period:] - values[:-period]
    if method == "combined_difference":
        seasonal = values[period:] - values[:-period]
        return np.diff(seasonal, n=1)
    if method == "log_difference":
        if np.any(values <= 0):
            raise ValueError("Логарифмическая разность требует строго положительных значений")
        return np.diff(np.log(values), n=1)
    raise BacktestExecutionError(f"Неподдерживаемое stationarity-преобразование: {method}")


def _inverse_stationarity(
    forecast: np.ndarray, method: str, input_train: np.ndarray,
    state: Mapping[str, Any],
) -> np.ndarray:
    if method == "linear_detrend":
        x = np.arange(len(input_train), len(input_train) + len(forecast), dtype=float)
        return forecast + float(state["trend_intercept"]) + float(state["trend_slope"]) * x
    if method == "first_difference":
        return input_train[-1] + np.cumsum(forecast)
    if method == "second_difference":
        previous = float(input_train[-1])
        first_difference = float(input_train[-1] - input_train[-2])
        restored = []
        for value in forecast:
            first_difference += float(value)
            previous += first_difference
            restored.append(previous)
        return np.asarray(restored, dtype=float)
    if method == "log_difference":
        return np.exp(np.log(input_train[-1]) + np.cumsum(forecast))
    period = int(state.get("seasonal_period") or 0)
    if period < 2:
        raise BacktestExecutionError("Для inverse seasonal difference не сохранён период")
    history = input_train.astype(float).tolist()
    restored: list[float] = []
    if method == "seasonal_difference":
        for value in forecast:
            current = float(value) + history[-period]
            history.append(current)
            restored.append(current)
        return np.asarray(restored, dtype=float)
    if method == "combined_difference":
        seasonal_difference = float(input_train[-1] - input_train[-1 - period])
        for value in forecast:
            seasonal_difference += float(value)
            current = seasonal_difference + history[-period]
            history.append(current)
            restored.append(current)
        return np.asarray(restored, dtype=float)
    raise BacktestExecutionError(f"Неподдерживаемый inverse stationarity: {method}")


class FoldLocalTargetPreprocessor:
    def __init__(
        self, *, source_column: str, target_column: str,
        transformations: Sequence[Mapping[str, Any]],
        scaling_recipe: Mapping[str, Any] | None,
    ) -> None:
        self.source_column = source_column
        self.target_column = target_column
        self.transformations = [dict(item) for item in transformations]
        self.scaling_recipe = dict(scaling_recipe or {})
        self.target_scaled = target_column in set(self.scaling_recipe.get("columns") or [])
        if self.target_scaled and self.scaling_recipe.get("fit_policy") != "per_train_fold":
            raise BacktestExecutionError("Target scaler должен иметь fit_policy=per_train_fold")
        reversible = all(bool(item.get("inverse_supported", True)) for item in self.transformations)
        self.evaluation_scale = source_column if reversible else target_column
        methods = [str(item.get("method") or "unknown") for item in self.transformations]
        contract = {
            "source_column": source_column,
            "target_column": target_column,
            "transformations": [
                {
                    "kind": _transform_kind(item),
                    "method": item.get("method"),
                    "parameters": item.get("parameters"),
                    "seasonal_period": item.get("seasonal_period"),
                    "lambda_policy": item.get("lambda_policy"),
                    "fixed_lambda": (
                        item.get("lambda_value")
                        if item.get("lambda_policy") == "fixed" else None
                    ),
                }
                for item in self.transformations
            ],
            "target_scaling": {
                "method": self.scaling_recipe.get("method"),
                "parameters": self.scaling_recipe.get("parameters"),
            } if self.target_scaled else None,
        }
        self.signature = sha256(
            json.dumps(contract, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.summary = {
            "fit_policy": "per_train_fold",
            "source_column": source_column,
            "target_column": target_column,
            "transformations": methods,
            "target_scaling": self.scaling_recipe.get("method") if self.target_scaled else None,
            "evaluation_scale": self.evaluation_scale,
            "inverse_transform_applied": reversible and bool(self.transformations or self.target_scaled),
            "signature": self.signature,
        }

    def _fit_transform(
        self, train: np.ndarray, extended: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
        train_current = train
        extended_current = extended
        states: list[dict[str, Any]] = []
        for metadata in self.transformations:
            kind = _transform_kind(metadata)
            method = str(metadata.get("method") or "")
            input_train = train_current.copy()
            if kind == "variance":
                # Stored lambda belongs to a full-history diagnostic preview.
                # Estimated power transforms are deliberately re-estimated here.
                requested_lambda = (
                    metadata.get("lambda_value")
                    if metadata.get("lambda_policy") == "fixed"
                    else None
                )
                train_current, fitted_lambda = apply_variance_transform(
                    train_current, method, requested_lambda,
                )
                extended_current, _ = apply_variance_transform(
                    extended_current, method, fitted_lambda,
                )
                state = {"kind": kind, "method": method, "lambda_value": fitted_lambda,
                         "input_train": input_train}
            elif kind == "stationarity":
                period = int(metadata.get("seasonal_period") or 12)
                train_current, fitted = apply_stationarity_series(
                    train_current, method, seasonal_period=period,
                )
                extended_current = _stationarity_forward(extended_current, method, fitted)
                state = {"kind": kind, "method": method, **fitted,
                         "input_train": input_train}
            elif kind == "smoothing":
                if method not in CAUSAL_METHODS or metadata.get("causal") is False:
                    raise BacktestExecutionError(
                        f"Некаузальный target smoother '{method}' неприменим в production backtest"
                    )
                parameters = dict(metadata.get("parameters") or {})
                if method == "ema":
                    parameters = {"span": int(parameters.get("span", 7))}
                else:
                    parameters = {"window": int(parameters.get("window", 7))}
                train_current, _ = apply_smoothing_series(train_current, method, **parameters)
                extended_current, _ = apply_smoothing_series(extended_current, method, **parameters)
                state = {"kind": kind, "method": method, "input_train": input_train}
            else:
                raise BacktestExecutionError(
                    f"Неизвестное preprocessing-преобразование target: {method or kind}"
                )
            states.append(state)
        return train_current, extended_current, states

    def prepare(self, values: list[float], fold: BacktestFoldPlan) -> PreparedFold:
        if fold.train_indices != list(range(fold.train_indices[0], fold.train_indices[-1] + 1)):
            raise BacktestExecutionError("Fold-local preprocessing требует непрерывный train-интервал")
        forecast_start = fold.train_indices[-1] + 1
        forecast_end = fold.test_indices[-1]
        raw_train = np.asarray([values[index] for index in fold.train_indices], dtype=float)
        raw_extended = np.asarray(
            [values[index] for index in range(fold.train_indices[0], forecast_end + 1)],
            dtype=float,
        )
        train_target, extended_target, states = self._fit_transform(raw_train, raw_extended)
        forecast_size = forecast_end - forecast_start + 1
        test_size = len(fold.test_indices)
        actual_target = extended_target[-test_size:]
        scaler = None
        model_train = train_target
        if self.target_scaled:
            scaler = _make_scaler(self.scaling_recipe, len(train_target))
            model_train = scaler.fit_transform(train_target.reshape(-1, 1)).ravel()

        reversible = self.evaluation_scale == self.source_column

        def restore_forecast(model_forecast: list[float]) -> list[float]:
            restored = np.asarray(model_forecast, dtype=float)
            if scaler is not None:
                restored = scaler.inverse_transform(restored.reshape(-1, 1)).ravel()
            if reversible:
                for state in reversed(states):
                    if state["kind"] == "variance":
                        restored = inverse_variance_transform(
                            restored, state["method"], state.get("lambda_value"),
                        )
                    elif state["kind"] == "stationarity":
                        restored = _inverse_stationarity(
                            restored, state["method"], state["input_train"], state,
                        )
            if not np.isfinite(restored).all():
                raise BacktestExecutionError("Inverse preprocessing породил NaN/Inf")
            return restored.astype(float).tolist()

        if reversible:
            evaluation_train = raw_train
            evaluation_actual = raw_extended[-test_size:]
        else:
            evaluation_train = train_target
            evaluation_actual = actual_target
        return PreparedFold(
            model_train=model_train.astype(float).tolist(),
            evaluation_train=evaluation_train.astype(float).tolist(),
            evaluation_actual=evaluation_actual.astype(float).tolist(),
            restore_forecast=restore_forecast,
        )


def prepare_modeling_target(
    dataframe: pd.DataFrame, *, target_column: str, date_column: str,
    transformations: Mapping[str, Mapping[str, Any]],
    scaling_recipe: Mapping[str, Any],
) -> PreparedModelingTarget:
    """Resolve the raw source and create a fold-local target pipeline."""
    source_column, chain = _resolve_chain(transformations, target_column)
    target_series = prepare_passport_series(
        dataframe, target_column, date_column, min_points=1,
    )
    source_series = prepare_passport_series(
        dataframe, source_column, date_column, min_points=1,
    )
    if not target_series.index.equals(source_series.index):
        raise BacktestExecutionError(
            "Source и target preprocessing имеют разные временные оси"
        )
    target_scaled = target_column in set(scaling_recipe.get("columns") or [])
    needs_pipeline = bool(chain) or target_scaled
    warnings: list[str] = []
    preprocessor = None
    if needs_pipeline:
        preprocessor = FoldLocalTargetPreprocessor(
            source_column=source_column, target_column=target_column,
            transformations=chain, scaling_recipe=scaling_recipe,
        )
        warnings.append(
            "Preprocessing target переоценён отдельно на train каждого EDA fold; "
            f"метрики рассчитаны в шкале '{preprocessor.evaluation_scale}'."
        )
    elif scaling_recipe and scaling_recipe.get("columns"):
        warnings.append(
            "Рецепт scaling относится только к X-признакам и не применяется univariate-моделью."
        )
    return PreparedModelingTarget(
        series=source_series.to_numpy(dtype=float).tolist(),
        labels=[value.isoformat() for value in source_series.index],
        source_column=source_column, target_column=target_column,
        fold_preprocessor=preprocessor, warnings=warnings,
        preprocessing_signature=preprocessor.signature if preprocessor is not None else "none",
    )
