# app/features/rolling.py
"""
Модуль скользящих статистик и сглаживания временных рядов.
Поддерживает SMA, EMA, WMA, Median, LOWESS.
"""
import numpy as np
import pandas as pd
from typing import Optional, Literal


SmoothingMethod = Literal['SMA', 'EMA', 'WMA', 'Median', 'LOWESS']


def apply_sma(
    series: pd.Series,
    window: int,
    center: bool = True
) -> pd.Series:
    """
    Simple Moving Average (простое скользящее среднее).
    
    Args:
        series: исходный ряд
        window: размер окна
        center: центрировать окно
    
    Returns:
        сглаженный ряд
    """
    return series.rolling(window=window, center=center, min_periods=1).mean()


def apply_ema(
    series: pd.Series,
    span: int
) -> pd.Series:
    """
    Exponential Moving Average (экспоненциальное скользящее среднее).
    
    Args:
        series: исходный ряд
        span: размер span (аналог window)
    
    Returns:
        сглаженный ряд
    """
    return series.ewm(span=span, adjust=False).mean()


def apply_wma(
    series: pd.Series,
    window: int
) -> pd.Series:
    """
    Weighted Moving Average (линейно-взвешенное скользящее среднее).
    
    Args:
        series: исходный ряд
        window: размер окна
    
    Returns:
        сглаженный ряд
    """
    weights = np.arange(1, window + 1)
    smoothed = series.rolling(window=window).apply(
        lambda x: np.dot(x, weights) / weights.sum(), raw=True
    )
    return smoothed.bfill()


def apply_median_smoothing(
    series: pd.Series,
    window: int,
    center: bool = True
) -> pd.Series:
    """
    Median filter (медианный фильтр).
    
    Args:
        series: исходный ряд
        window: размер окна
        center: центрировать окно
    
    Returns:
        сглаженный ряд
    """
    return series.rolling(window=window, center=center, min_periods=1).median()


def apply_lowess(
    series: pd.Series,
    frac: float
) -> pd.Series:
    """
    LOWESS (Locally Weighted Scatterplot Smoothing).
    
    Args:
        series: исходный ряд
        frac: параметр сглаживания (0-1)
    
    Returns:
        сглаженный ряд
    """
    from statsmodels.nonparametric.smoothers_lowess import lowess
    
    x = np.arange(len(series))
    y = series.values
    lowess_result = lowess(y, x, frac=frac, return_sorted=False)
    return pd.Series(lowess_result, index=series.index)


def apply_smoothing(
    series: pd.Series,
    method: SmoothingMethod,
    window: Optional[int] = None,
    span: Optional[int] = None,
    frac: Optional[float] = None,
    center: bool = True
) -> pd.Series:
    """
    Универсальная функция сглаживания.
    
    Args:
        series: исходный ряд
        method: метод сглаживания ('SMA', 'EMA', 'WMA', 'Median', 'LOWESS')
        window: размер окна (для SMA, WMA, Median)
        span: размер span (для EMA)
        frac: параметр сглаживания (для LOWESS)
        center: центрировать окно (для SMA, Median)
    
    Returns:
        сглаженный ряд
    """
    if method == 'SMA':
        if window is None:
            raise ValueError("window required for SMA")
        return apply_sma(series, window, center)
    
    elif method == 'EMA':
        if span is None:
            raise ValueError("span required for EMA")
        return apply_ema(series, span)
    
    elif method == 'WMA':
        if window is None:
            raise ValueError("window required for WMA")
        return apply_wma(series, window)
    
    elif method == 'Median':
        if window is None:
            raise ValueError("window required for Median")
        return apply_median_smoothing(series, window, center)
    
    elif method == 'LOWESS':
        if frac is None:
            raise ValueError("frac required for LOWESS")
        return apply_lowess(series, frac)
    
    else:
        raise ValueError(f"Unknown smoothing method: {method}")