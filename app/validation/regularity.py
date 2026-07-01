# app/validation/regularity.py
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

def compute_regularity_violations(
    df: pd.DataFrame, 
    date_col: str, 
    entity_col: Optional[str] = None,
    gap_threshold_multiplier: float = 1.5
) -> Dict[str, Any]:
    """
    Вычисляет нарушения регулярности временного шага (gaps).
    Строго следует Правилу 14 (явная адресация) и Правилу 15 (Panel Data).
    
    Args:
        df: DataFrame для проверки.
        date_col: Явно переданная колонка даты.
        entity_col: Колонка сущности (для Panel Data). Если None - single-series.
        gap_threshold_multiplier: Множитель для определения аномального разрыва.
        
    Returns:
        Dict с маской нарушений, информацией о частоте и количеством гэпов.
    """
    if date_col not in df.columns:
        raise ValueError(f"Колонка даты '{date_col}' отсутствует в DataFrame.")
    
    df_temp = df.copy()
    
    # Приведение к datetime
    if not pd.api.types.is_datetime64_any_dtype(df_temp[date_col]):
        df_temp[date_col] = pd.to_datetime(df_temp[date_col], errors='coerce')
        
    combined_mask = pd.Series(False, index=df_temp.index)
    freq_info = {}
    
    try:
        if entity_col and entity_col in df_temp.columns:
            # 🔧 Panel Data: строгая группировка (Правило 15)
            for _, group_df in df_temp.groupby(entity_col):
                group_sorted = group_df.sort_values(date_col)
                intervals = group_sorted[date_col].diff()
                
                # Защита от NaT при вычислении статистик
                valid_intervals = intervals.dropna()
                if valid_intervals.empty:
                    continue
                    
                modal_interval = (
                    valid_intervals.mode().iloc[0] 
                    if not valid_intervals.mode().empty 
                    else valid_intervals.median()
                )
                
                gap_mask = intervals > (modal_interval * gap_threshold_multiplier)
                if gap_mask.any():
                    combined_mask.loc[gap_mask[gap_mask].index] = True
                    
                inferred = pd.infer_freq(group_sorted[date_col].drop_duplicates().sort_values())
                if inferred and 'inferred_freq' not in freq_info:
                    freq_info['inferred_freq'] = inferred 
        else:
            # Single-series TS
            df_sorted = df_temp.sort_values(date_col)
            intervals = df_sorted[date_col].diff()
            
            valid_intervals = intervals.dropna()
            if not valid_intervals.empty:
                modal_interval = (
                    valid_intervals.mode().iloc[0] 
                    if not valid_intervals.mode().empty 
                    else valid_intervals.median()
                )
                
                gap_mask = intervals > (modal_interval * gap_threshold_multiplier)
                if gap_mask.any():
                    combined_mask.loc[gap_mask[gap_mask].index] = True
                    
                freq_info['inferred_freq'] = pd.infer_freq(
                    df_sorted[date_col].drop_duplicates().sort_values()
                )
                
    except Exception as e:
        # Правило 16: Graceful Degradation
        logger.error(f"Ошибка при вычислении регулярности: {e}", exc_info=True)
        return {
            "mask": pd.Series(False, index=df.index),
            "freq_info": {},
            "gaps_count": 0,
            "error": str(e)
        }

    return {
        "mask": combined_mask,
        "freq_info": freq_info,
        "gaps_count": int(combined_mask.sum())
    }