# app/features/temporal.py
"""
Модуль создания временных признаков из даты.
Извлекает календарные компоненты (год, месяц, день, день недели и т.д.).
"""
import pandas as pd
from typing import Optional


def create_temporal_features(
    df: pd.DataFrame,
    date_col: str,
    add_quarter: bool = True,
    add_dayofyear: bool = True,
    add_is_weekend: bool = True,
    add_is_holiday: bool = False
) -> pd.DataFrame:
    """
    Создаёт временные признаки из колонки с датой.
    
    Args:
        df: исходный DataFrame
        date_col: название колонки с датой
        add_quarter: добавить квартал (quarter)
        add_dayofyear: добавить день года (dayofyear)
        add_is_weekend: добавить флаг выходного (is_weekend)
        add_is_holiday: добавить флаг праздника (is_holiday) — требует библиотеку holidays
    
    Returns:
        DataFrame с добавленными временными признаками
    """
    if date_col not in df.columns:
        raise ValueError(f"Колонка '{date_col}' не найдена в DataFrame")
    
    df_result = df.copy()
    
    # Преобразуем в datetime, если нужно
    if not pd.api.types.is_datetime64_any_dtype(df_result[date_col]):
        df_result[date_col] = pd.to_datetime(df_result[date_col])
    
    # Базовые признаки
    df_result['year'] = df_result[date_col].dt.year
    df_result['month'] = df_result[date_col].dt.month
    df_result['day'] = df_result[date_col].dt.day
    df_result['dayofweek'] = df_result[date_col].dt.dayofweek
    
    # Опциональные признаки
    if add_quarter:
        df_result['quarter'] = df_result[date_col].dt.quarter
    
    if add_dayofyear:
        df_result['dayofyear'] = df_result[date_col].dt.dayofyear
    
    if add_is_weekend:
        df_result['is_weekend'] = (df_result[date_col].dt.dayofweek >= 5).astype(int)
    
    if add_is_holiday:
        try:
            import holidays
            years = df_result[date_col].dt.year.unique()
            country_holidays = holidays.country_holidays('RU', years=years)
            df_result['is_holiday'] = df_result[date_col].dt.date.apply(
                lambda x: 1 if x in country_holidays else 0
            )
        except ImportError:
            df_result['is_holiday'] = 0  # Заглушка, если библиотека не установлена
    
    return df_result


def create_fourier_features(
    df: pd.DataFrame,
    date_col: str,
    periods: list,
    prefix: str = 'fourier'
) -> pd.DataFrame:
    """
    Создаёт Fourier features (sin/cos) для заданных периодов.
    
    Args:
        df: исходный DataFrame
        date_col: название колонки с датой
        periods: список периодов (например, [7, 30.5, 365.25])
        prefix: префикс для названий колонок
    
    Returns:
        DataFrame с добавленными Fourier features
    """
    import numpy as np
    
    if date_col not in df.columns:
        raise ValueError(f"Колонка '{date_col}' не найдена в DataFrame")
    
    df_result = df.copy()
    
    if not pd.api.types.is_datetime64_any_dtype(df_result[date_col]):
        df_result[date_col] = pd.to_datetime(df_result[date_col])
    
    # Преобразуем дату в числовой формат (дни с начала отсчёта)
    t = (df_result[date_col] - df_result[date_col].min()).dt.days.astype(float)
    
    for period in periods:
        df_result[f'{prefix}_sin_{period}'] = np.sin(2 * np.pi * t / period)
        df_result[f'{prefix}_cos_{period}'] = np.cos(2 * np.pi * t / period)
    
    return df_result