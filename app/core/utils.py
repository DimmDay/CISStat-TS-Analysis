# app/core/utils.py
"""
Общие утилиты для бизнес-логики.
Содержит безопасные обёртки для статистических вычислений.

⚠️ ВАЖНО: Этот модуль НЕ импортирует streamlit.
Все функции — stateless, с явными аргументами (Правило 14).
"""
from typing import Callable, Optional, Any, List, Tuple

import numpy as np
import pandas as pd


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


# Дефолтный список служебных/системных колонок, которые обычно попадают
# в данные как побочный эффект экспорта/парсинга (индексы, авто-нумерация и т.п.),
# а не как реальные признаки для анализа.
DEFAULT_SERVICE_COLUMN_NAMES = [
    'row_id', 'index', 'level_0', 'level_1', 'unnamed', 'unnamed: 0'
]


def drop_service_columns(
    df: pd.DataFrame,
    service_names: Optional[List[str]] = None
) -> Tuple[pd.DataFrame, List[str]]:
    """
    Удаляет служебные/системные колонки (row_id, index, unnamed и т.п.).
    Сравнение имён регистронезависимое.

    ЗАМЕНА ДЛЯ: 2 независимые инлайн-копии этой логики в app.py (ветка
    загрузки файла и ветка загрузки из БД) -- вторая копия ссылалась на
    неверную переменную (df вместо df_db), что приводило к NameError при
    первой загрузке из БД в новой сессии.

    Args:
        df: DataFrame для очистки
        service_names: список имён служебных колонок (регистронезависимо).
            Если не передан, используется DEFAULT_SERVICE_COLUMN_NAMES.

    Returns:
        Tuple (df_cleaned, dropped_column_names): очищенный DataFrame и
        список реально удалённых колонок (в исходном написании).
    """
    names_to_match = service_names if service_names is not None else DEFAULT_SERVICE_COLUMN_NAMES
    names_lower = {str(n).lower() for n in names_to_match}

    cols_to_drop = [c for c in df.columns if str(c).lower() in names_lower]

    if not cols_to_drop:
        return df, []

    return df.drop(columns=cols_to_drop), cols_to_drop