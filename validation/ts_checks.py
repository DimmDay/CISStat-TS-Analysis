# validation/ts_checks.py
"""
TS-специфичные проверки (стационарность, частота, пропуски).
"""
import pandas as pd
from typing import Dict, Any


def check_ts_properties(
    df: pd.DataFrame, 
    date_col: str, 
    num_col: str
) -> Dict[str, Any]:
    """
    Выполняет TS-специфичные проверки.
    
    Args:
        df: DataFrame с данными
        date_col: Колонка с датами
        num_col: Числовая колонка для анализа
        
    Returns:
        Словарь с результатами:
        {
            'adf_pvalue': float or None,
            'is_stationary': bool or None,
            'frequency': str,
            'max_gap': pd.Timedelta
        }
    """
    if date_col not in df.columns or num_col not in df.columns:
        return {"error": "Не найдены колонки с датами и числовыми данными"}
    
    # Подготовка временного ряда
    df_ts = df.sort_values(date_col).set_index(date_col)[[num_col]].dropna()
    
    if len(df_ts) < 10:
        return {"error": "Недостаточно данных для TS-проверок"}
    
    result = {}
    
    # ADF тест
    try:
        from statsmodels.tsa.stattools import adfuller
        adf_result = adfuller(df_ts[num_col].dropna())
        result['adf_pvalue'] = adf_result[1]
        result['is_stationary'] = adf_result[1] < 0.05
    except Exception:
        result['adf_pvalue'] = None
        result['is_stationary'] = None
    
    # Частота
    freq = pd.infer_freq(df_ts.index)
    result['frequency'] = freq if freq else "Нерегулярная"
    
    # Максимальный пропуск
    try:
        if pd.api.types.is_datetime64_any_dtype(df_ts.index):
            gaps = df_ts.index.to_series().diff().dropna()
            result['max_gap'] = gaps.max() if len(gaps) > 0 else pd.Timedelta(0)
        else:
            result['max_gap'] = pd.Timedelta(0)
    except Exception:
        result['max_gap'] = pd.Timedelta(0)
    
    return result