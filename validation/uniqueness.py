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