# app/core/utils.py
"""
Общие утилиты для бизнес-логики.
Содержит безопасные обёртки для статистических вычислений.

⚠️ ВАЖНО: Этот модуль НЕ импортирует streamlit.
Все функции — stateless, с явными аргументами (Правило 14).
"""
from typing import Callable, Optional, Any

import numpy as np
import pandas as pd


def safe_stat(df: pd.DataFrame, col: str, func: Callable) -> float:
    """
    Безопасное применение статистической функции к колонке DataFrame.
    
    Возвращает 0.0, если:
    - DataFrame пустой
    - Колонка отсутствует
    - Все значения в колонке — NaN
    
    Args:
        df: Исходный DataFrame
        col: Имя колонки
        func: Статистическая функция (np.mean, np.std, np.median и т.д.)
    
    Returns:
        float: Результат функции или 0.0 при ошибке/отсутствии данных
    
    Examples:
        >>> safe_stat(df, 'price', np.mean)
        42.5
        >>> safe_stat(empty_df, 'price', np.mean)
        0.0
    """
    try:
        if df.empty or col not in df.columns:
            return 0.0
        series = df[col].dropna()
        if series.empty:
            return 0.0
        result = func(series)
        return float(result) if pd.notna(result) else 0.0
    except (TypeError, ValueError, AttributeError):
        return 0.0
    except Exception:
        return 0.0



def _safe_nunique(series: pd.Series, min_val: int = 1, max_val: int = 100) -> bool:
    """
    Безопасный подсчёт уникальных значений для колонок с возможными нехэшируемыми типами.
    Возвращает True, если количество уникальных значений в диапазоне (min_val, max_val).
    
    Args:
        series: pandas Series для анализа
        min_val: нижняя граница диапазона (исключительно)
        max_val: верхняя граница диапазона (исключительно)
    
    Returns:
        True если min_val < nunique < max_val, иначе False
    """
    try:
        sample = series.dropna().head(100)
        if len(sample) == 0:
            return False
        first_val = sample.iloc[0]
        if isinstance(first_val, (dict, list, set, pd.Series, pd.DataFrame)):
            return False
        uniq = series.nunique()
        return min_val < uniq < max_val
    except TypeError:
        return False
    except Exception:
        return False
    

# app/core/utils.py
import pandas as pd
from typing import Callable, Optional, Any

def safe_stat(df: pd.DataFrame, col: str, func: Callable[[pd.Series], Any]) -> Optional[float]:
    """
    Безопасно вычисляет статистическую функцию для колонки DataFrame.
    Возвращает None, если колонка отсутствует, пуста, состоит только из NaN,
    или если вычисление вызвало исключение / вернуло NaN.
    
    ЗАМЕНА ДЛЯ: 8 локальных копий safe_stat / safe_text_stat из app.py.
    """
    if col not in df.columns:
        return None
        
    series = df[col].dropna()
    if series.empty:
        return None
        
    try:
        result = func(series)
        if pd.isna(result):
            return None
        return float(result)
    except Exception:
        # Логирование в AppState.error_log должно происходить на уровне UI/оркестратора,
        # здесь мы просто гарантируем, что пайплайн не упадет (Graceful Degradation).
        return None