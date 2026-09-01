# app/preprocessing/decomposition.py
"""
Модуль декомпозиции временных рядов.
Поддерживает STL и классическую (additive/multiplicative) декомпозицию.
"""
import numpy as np
import pandas as pd
from typing import Optional, Literal, Dict, Any
from statsmodels.tsa.seasonal import STL, seasonal_decompose


DecompMethod = Literal['STL', 'Additive', 'Multiplicative']


def apply_decomposition(
    series: pd.Series,
    method: DecompMethod = 'STL',
    period: Optional[int] = None,
    seasonal_window: Optional[int] = None,
    trend_window: Optional[int] = None,
    robust: bool = True
) -> Dict[str, pd.Series]:
    """
    Применяет декомпозицию к временному ряду.
    
    Args:
        series: исходный ряд с DatetimeIndex
        method: метод декомпозиции ('STL', 'Additive', 'Multiplicative')
        period: сезонный период (если None, определяется автоматически)
        seasonal_window: окно сезонной компоненты (только для STL)
        trend_window: окно трендовой компоненты (только для STL)
        robust: использовать робастную оценку (только для STL)
    
    Returns:
        dict с ключами: 'observed', 'trend', 'seasonal', 'resid', 'method'
    """
    # Определяем период, если не задан
    if period is None:
        inferred_freq = pd.infer_freq(series.index)
        if inferred_freq and 'D' in str(inferred_freq):
            period = 7  # недельная сезонность для дневных данных
        elif inferred_freq and 'M' in str(inferred_freq):
            period = 12  # годовая сезонность для месячных данных
        else:
            period = 12  # default

    if period < 2:
        raise ValueError("Сезонный период должен быть не меньше 2")
    if series.empty or len(series) < 2 * period:
        raise ValueError(f"Недостаточно данных для декомпозиции (нужно минимум {2 * period} точек)")
    if series.isna().any():
        raise ValueError("Ряд содержит пропуски; декомпозиция требует полных наблюдений")
    
    if method == 'STL':
        # БАГ (найден 2026-08-19 при первом реальном вызове этой функции --
        # ни одного теста на apply_decomposition не было, ни одного
        # продакшен-вызова с её собственными дефолтами seasonal_window=None/
        # trend_window=None): statsmodels.tsa.seasonal.STL падает
        # ValueError'ом на ЯВНО переданном seasonal=None/trend=None
        # ("seasonal must be an odd positive integer >= 3"), хотя при
        # ПОЛНОСТЬЮ ОПУЩЕННОМ параметре использует свой собственный
        # разумный дефолт без ошибок (см. compute_decomposition_stats
        # ниже -- она НЕ передаёт seasonal=/trend= вовсе и работает).
        # Собираем kwargs условно, чтобы None не долетал до STL().
        stl_kwargs = {"period": period, "robust": robust}
        if seasonal_window is not None:
            stl_kwargs["seasonal"] = seasonal_window
        if trend_window is not None:
            stl_kwargs["trend"] = trend_window
        stl = STL(series, **stl_kwargs)
        result = stl.fit()
        return {
            'observed': series,
            'trend': result.trend,
            'seasonal': result.seasonal,
            'resid': result.resid,
            'method': 'STL'
        }
    
    elif method == 'Additive':
        result = seasonal_decompose(series, model='additive', period=period)
        return {
            'observed': result.observed,
            'trend': result.trend,
            'seasonal': result.seasonal,
            'resid': result.resid,
            'method': 'Additive'
        }
    
    elif method == 'Multiplicative':
        result = seasonal_decompose(series, model='multiplicative', period=period)
        return {
            'observed': result.observed,
            'trend': result.trend,
            'seasonal': result.seasonal,
            'resid': result.resid,
            'method': 'Multiplicative'
        }
    
    else:
        raise ValueError(f"Неизвестный метод декомпозиции: {method}")


def compute_decomposition_stats(
    series: pd.Series,
    period: Optional[int] = None
) -> Dict[str, float]:
    """
    Вычисляет статистики декомпозиции (дисперсии компонент).
    
    Args:
        series: исходный ряд с DatetimeIndex
        period: сезонный период (если None, определяется автоматически)
    
    Returns:
        dict с ключами: 'trend_var', 'seasonal_var', 'cyclical_var', 'resid_var'
    """
    if period is None:
        inferred_freq = pd.infer_freq(series.index)
        if inferred_freq and 'D' in str(inferred_freq):
            period = 7
        elif inferred_freq and 'M' in str(inferred_freq):
            period = 12
        else:
            period = 12
    
    stl_res = STL(series, period=period, robust=True).fit()
    
    trend_var = float(stl_res.trend.var())
    seasonal_var = float(stl_res.seasonal.var())
    resid_var = float(stl_res.resid.var())
    
    # Цикличность = тренд минус сглаженный тренд
    trend_smoothed = stl_res.trend.rolling(30, min_periods=1).mean()
    cyclical_var = float((stl_res.trend - trend_smoothed).var())
    
    return {
        'trend_var': trend_var,
        'seasonal_var': seasonal_var,
        'cyclical_var': cyclical_var,
        'resid_var': resid_var
    }
