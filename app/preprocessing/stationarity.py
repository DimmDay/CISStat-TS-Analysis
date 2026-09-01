"""Чистые преобразования остановки «Стационарность ряда».

В отличие от legacy ``apply_differencing`` здесь порядок обычной разности
не смешивается с её лагом: ``np.diff(..., n=2)`` означает Δ², а сезонная
разность вычисляется отдельным оператором ``1 - B**s``.
"""
from __future__ import annotations

from typing import Any, Literal, Sequence

import numpy as np
from scipy.signal import detrend as scipy_detrend


StationarityTransformMethod = Literal[
    "linear_detrend",
    "first_difference",
    "second_difference",
    "seasonal_difference",
    "combined_difference",
    "log_difference",
]

STATIONARITY_TRANSFORM_METHODS = {
    "linear_detrend",
    "first_difference",
    "second_difference",
    "seasonal_difference",
    "combined_difference",
    "log_difference",
}


def _values(values: Sequence[float] | np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise ValueError("Временной ряд должен быть одномерным")
    if len(array) < 3:
        raise ValueError("Для преобразования нужно минимум 3 наблюдения")
    if not np.isfinite(array).all():
        raise ValueError("Временной ряд должен содержать только конечные значения")
    return array


def apply_stationarity_series(
    values: Sequence[float] | np.ndarray,
    method: StationarityTransformMethod,
    *,
    seasonal_period: int = 12,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Преобразовать одномерный ряд и вернуть параметры инверсии.

    Результат содержит только определённую часть ряда. Число потерянных
    начальных наблюдений явно возвращается в ``lost_observations``; API
    использует его для синхронного удаления тех же строк из DataFrame.
    """
    array = _values(values)
    if method not in STATIONARITY_TRANSFORM_METHODS:
        raise ValueError(f"Неподдерживаемый метод обеспечения стационарности: {method}")
    if not isinstance(seasonal_period, (int, np.integer)) or seasonal_period < 2:
        raise ValueError("Сезонный период должен быть целым числом не меньше 2")

    regular_order = 0
    seasonal_order = 0
    effective_period: int | None = None
    domain_transform: str | None = None
    trend_intercept: float | None = None
    trend_slope: float | None = None
    causal = True

    if method == "linear_detrend":
        x = np.arange(len(array), dtype=float)
        trend_slope, trend_intercept = np.polyfit(x, array, deg=1)
        transformed = scipy_detrend(array, type="linear")
        lost = 0
        history_tail: list[float] = []
        causal = False
    elif method == "first_difference":
        regular_order = 1
        transformed = np.diff(array, n=1)
        lost = 1
        history_tail = array[-1:].tolist()
    elif method == "second_difference":
        regular_order = 2
        transformed = np.diff(array, n=2)
        lost = 2
        history_tail = array[-2:].tolist()
    elif method == "seasonal_difference":
        if seasonal_period >= len(array):
            raise ValueError("Сезонный период должен быть меньше числа наблюдений")
        seasonal_order = 1
        effective_period = int(seasonal_period)
        transformed = array[seasonal_period:] - array[:-seasonal_period]
        lost = seasonal_period
        history_tail = array[-seasonal_period:].tolist()
    elif method == "combined_difference":
        if seasonal_period + 1 >= len(array):
            raise ValueError("Для комбинированной разности нужно больше наблюдений, чем сезонный период + 1")
        regular_order = 1
        seasonal_order = 1
        effective_period = int(seasonal_period)
        seasonal = array[seasonal_period:] - array[:-seasonal_period]
        transformed = np.diff(seasonal, n=1)
        lost = seasonal_period + 1
        history_tail = array[-(seasonal_period + 1):].tolist()
    else:  # log_difference
        if np.any(array <= 0):
            raise ValueError("Логарифмическая разность требует строго положительных значений")
        regular_order = 1
        domain_transform = "log"
        transformed = np.diff(np.log(array), n=1)
        lost = 1
        history_tail = array[-1:].tolist()

    if not np.isfinite(transformed).all():
        raise ValueError("Преобразование породило бесконечные или неопределённые значения")
    return transformed.astype(float, copy=False), {
        "method": method,
        "regular_order": regular_order,
        "seasonal_order": seasonal_order,
        "seasonal_period": effective_period,
        "domain_transform": domain_transform,
        "causal": causal,
        "modeling_safe": causal,
        "inverse_supported": True,
        "lost_observations": int(lost),
        "history_tail": [float(value) for value in history_tail],
        "trend_intercept": None if trend_intercept is None else float(trend_intercept),
        "trend_slope": None if trend_slope is None else float(trend_slope),
    }
