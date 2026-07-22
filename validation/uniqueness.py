# validation/uniqueness.py
"""
Проверка уникальности записей (дубликаты).
"""
import pandas as pd
from typing import Dict, Any


def check_uniqueness(df: pd.DataFrame, date_col: str = None) -> Dict[str, Any]:
    """
    Проверяет уникальность записей в DataFrame.
    
    Args:
        df: DataFrame для проверки
        date_col: Колонка с датами (если None, проверяются все колонки)
        
    Returns:
        Словарь с результатами:
        {
            'duplicate_count': int,
            'status': str
        }
    """
    if df.empty:
        return {
            'duplicate_count': 0,
            'status': '✅ Соблюдено'
        }
    
    if date_col and date_col in df.columns:
        dup_count = int(df.duplicated(subset=[date_col], keep=False).sum())
    else:
        dup_count = int(df.duplicated(keep=False).sum())
    
    return {
        'duplicate_count': dup_count,
        'status': '✅ Соблюдено' if dup_count == 0 else '⚠️ Нарушено'
    }


# validation/uniqueness.py - добавить к существующей функции check_uniqueness

def compute_duplicate_mask(
    df: pd.DataFrame, 
    is_panel_data: bool, 
    check_cols: list = None
) -> pd.Series:
    """
    Вычисляет маску дубликатов с учётом типа данных.
    
    Args:
        df: DataFrame для проверки
        is_panel_data: True для панельных данных, False для кросс-секционных
        check_cols: Список колонок для проверки (для панельных данных)
        
    Returns:
        pd.Series с булевой маской дубликатов
        
    Examples:
        >>> import pandas as pd
        >>> df = pd.DataFrame({'a': [1, 1, 2], 'b': [3, 3, 4]})
        >>> mask = compute_duplicate_mask(df, is_panel_data=False, check_cols=None)
        >>> mask.sum()
        2
    """
    if df.empty:
        return pd.Series([], dtype=bool)
    
    if is_panel_data and check_cols:
        return df.duplicated(subset=check_cols, keep=False)
    else:
        return df.duplicated(keep=False)