"""Чистые методы сглаживания для preprocessing/session-контура.

Каузальные методы используют только текущее и прошлые наблюдения. LOWESS и
Savitzky–Golay намеренно помечены как offline: их полное историческое
представление использует точки по обе стороны от момента времени.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter

from app.features.rolling import apply_smoothing


SMOOTHING_METHODS = ("sma", "ema", "wma", "median", "savgol", "lowess")
CAUSAL_METHODS = {"sma", "ema", "wma", "median"}


def _positive_int(value: int, label: str, minimum: int = 2) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or int(value) < minimum:
        raise ValueError(f"{label} должен быть целым числом не меньше {minimum}")
    return int(value)


def apply_smoothing_series(
    values: np.ndarray | pd.Series,
    method: str,
    *,
    window: int = 7,
    span: int = 7,
    frac: float = 0.2,
    polyorder: int = 2,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Сгладить одномерный конечный ряд и вернуть параметры контракта.

    SMA/WMA/median используют trailing-window (``center=False``), EMA —
    рекурсию ``adjust=False``. Поэтому изменение будущего не меняет уже
    рассчитанное прошлое. LOWESS и Savitzky–Golay доступны только как
    явно некаузальные offline-фильтры.
    """
    if method not in SMOOTHING_METHODS:
        raise ValueError(f"Неподдерживаемый метод сглаживания: {method}")
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise ValueError("Сглаживание поддерживает только одномерный ряд")
    if len(array) < 3:
        raise ValueError("Для сглаживания нужно минимум 3 наблюдения")
    if not np.isfinite(array).all():
        raise ValueError("Ряд содержит пропуски или бесконечные значения")

    series = pd.Series(array, dtype=float)
    parameters: dict[str, int | float]
    if method == "sma":
        resolved = _positive_int(window, "window")
        smoothed = apply_smoothing(series, "SMA", window=resolved, center=False)
        parameters = {"window": resolved}
    elif method == "ema":
        resolved = _positive_int(span, "span")
        smoothed = apply_smoothing(series, "EMA", span=resolved)
        parameters = {"span": resolved, "alpha": 2.0 / (resolved + 1.0)}
    elif method == "wma":
        resolved = _positive_int(window, "window")
        smoothed = apply_smoothing(series, "WMA", window=resolved)
        parameters = {"window": resolved}
    elif method == "median":
        resolved = _positive_int(window, "window")
        smoothed = apply_smoothing(series, "Median", window=resolved, center=False)
        parameters = {"window": resolved}
    elif method == "savgol":
        resolved = _positive_int(window, "window", minimum=3)
        if resolved % 2 == 0:
            raise ValueError("Для Savitzky–Golay window должен быть нечётным")
        if resolved > len(array):
            raise ValueError("Для Savitzky–Golay window не может превышать длину ряда")
        order = _positive_int(polyorder, "polyorder", minimum=1)
        if order >= resolved:
            raise ValueError("Для Savitzky–Golay polyorder должен быть меньше window")
        smoothed = pd.Series(
            savgol_filter(array, window_length=resolved, polyorder=order, mode="interp"),
            index=series.index,
        )
        parameters = {"window": resolved, "polyorder": order}
    else:
        if not isinstance(frac, (int, float, np.floating)) or not 0 < float(frac) <= 1:
            raise ValueError("Для LOWESS frac должен находиться в интервале (0, 1]")
        resolved_frac = float(frac)
        smoothed = apply_smoothing(series, "LOWESS", frac=resolved_frac)
        parameters = {"frac": resolved_frac}

    result = smoothed.to_numpy(dtype=float)
    if not np.isfinite(result).all():
        raise ValueError("Метод сглаживания вернул неконечные значения")
    causal = method in CAUSAL_METHODS
    return result, {
        "method": method,
        "parameters": parameters,
        "causal": causal,
        "modeling_safe": causal,
        "inverse_supported": False,
    }

