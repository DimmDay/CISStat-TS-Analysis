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


# app/validation/regularity.py (продолжение)

def _aggregate_duplicate_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    Агрегирует дубликаты в индексе (датах).
    Для числовых колонок используется mean, для категориальных — first.
    """
    if not df.index.duplicated().any():
        return df
        
    num_cols = df.select_dtypes(include=['number']).columns.tolist()
    cat_cols = df.select_dtypes(include=['object', 'string', 'category']).columns.tolist()
    
    agg_dict = {col: 'mean' for col in num_cols}
    agg_dict.update({col: 'first' for col in cat_cols})
    
    return df.groupby(df.index).agg(agg_dict)


def _resample_and_fill(df_indexed: pd.DataFrame, freq: str, fill_method: str) -> pd.DataFrame:
    """
    Выполняет resample и заполнение пропусков для числовых и категориальных колонок.
    """
    num_cols = df_indexed.select_dtypes(include=['number']).columns.tolist()
    cat_cols = df_indexed.select_dtypes(include=['object', 'string', 'category']).columns.tolist()
    
    filled_num = pd.DataFrame()
    filled_cat = pd.DataFrame()
    
    if num_cols:
        resampled_num = df_indexed[num_cols].resample(freq)
        if fill_method == 'interpolate':
            filled_num = resampled_num.mean().interpolate(method='linear')
        elif fill_method == 'ffill':
            filled_num = resampled_num.mean().ffill()
        elif fill_method == 'bfill':
            filled_num = resampled_num.mean().bfill()
        else:  # asfreq
            filled_num = resampled_num.asfreq()
            
    if cat_cols:
        resampled_cat = df_indexed[cat_cols].resample(freq)
        if fill_method in ['interpolate', 'ffill']:
            filled_cat = resampled_cat.ffill()
        elif fill_method == 'bfill':
            filled_cat = resampled_cat.bfill()
        else:  # asfreq
            filled_cat = resampled_cat.asfreq()
            
    if not filled_num.empty and not filled_cat.empty:
        return pd.concat([filled_num, filled_cat], axis=1)
    elif not filled_num.empty:
        return filled_num
    elif not filled_cat.empty:
        return filled_cat
    return pd.DataFrame()


def _process_single_group_resample(group_df: pd.DataFrame, date_col: str, freq: str, fill_method: str) -> pd.DataFrame:
    """Обрабатывает одну группу (или весь DataFrame) стратегией ресемплирования."""
    df_temp = group_df.set_index(date_col).sort_index()
    df_temp = _aggregate_duplicate_dates(df_temp)
    filled = _resample_and_fill(df_temp, freq, fill_method)
    return filled.reset_index()


def _process_single_group_fictitious(group_df: pd.DataFrame, date_col: str, freq: str) -> pd.DataFrame:
    """Добавляет фиктивные записи (нули для чисел, ffill для категорий) для одной группы."""
    df_temp = group_df.set_index(date_col).sort_index()
    df_temp = _aggregate_duplicate_dates(df_temp)
    
    full_range = pd.date_range(start=df_temp.index.min(), end=df_temp.index.max(), freq=freq)
    reindexed = df_temp.reindex(full_range)
    
    cat_cols = reindexed.select_dtypes(include=['object', 'string', 'category']).columns.tolist()
    for col in cat_cols:
        reindexed[col] = reindexed[col].ffill().bfill()
        
    num_cols = reindexed.select_dtypes(include=['number']).columns.tolist()
    for col in num_cols:
        reindexed[col] = reindexed[col].fillna(0)
        
    return reindexed.reset_index().rename(columns={'index': date_col})


def apply_regularity_strategy(
    df: pd.DataFrame,
    strategy: str,
    freq: str,
    date_col: str,
    entity_col: Optional[str] = None
) -> pd.DataFrame:
    """
    Применяет стратегию обработки нарушений регулярности.
    Строго следует Правилу 14 (явная адресация) и Правилу 16 (Graceful Degradation).
    """
    df_result = df.copy()
    
    if not pd.api.types.is_datetime64_any_dtype(df_result[date_col]):
        df_result[date_col] = pd.to_datetime(df_result[date_col], errors='coerce')
        
    try:
        if "Interpolate" in strategy or "Forward Fill" in strategy or \
           "Backward Fill" in strategy or "AsFreq" in strategy:
            
            if "Interpolate" in strategy:
                fill_method = 'interpolate'
            elif "Forward Fill" in strategy:
                fill_method = 'ffill'
            elif "Backward Fill" in strategy:
                fill_method = 'bfill'
            else:
                fill_method = 'asfreq'
                
            if entity_col and entity_col in df_result.columns:
                grouped_results = []
                for group_name, group_df in df_result.groupby(entity_col):
                    filled = _process_single_group_resample(group_df, date_col, freq, fill_method)
                    filled[entity_col] = group_name
                    grouped_results.append(filled)
                df_result = pd.concat(grouped_results, ignore_index=True)
            else:
                df_result = _process_single_group_resample(df_result, date_col, freq, fill_method)
                
        elif "фиктивные" in strategy:
            if entity_col and entity_col in df_result.columns:
                grouped_results = []
                for group_name, group_df in df_result.groupby(entity_col):
                    reindexed = _process_single_group_fictitious(group_df, date_col, freq)
                    reindexed[entity_col] = group_name
                    grouped_results.append(reindexed)
                df_result = pd.concat(grouped_results, ignore_index=True)
            else:
                df_result = _process_single_group_fictitious(df_result, date_col, freq)
                
        elif "флагом" in strategy:
            # 🔧 ИСПРАВЛЕНИЕ: Явная передача date_col и entity_col (Правило 14)
            res = compute_regularity_violations(df_result, date_col=date_col, entity_col=entity_col)
            df_result['_has_gap'] = res["mask"]
            
    except Exception as e:
        # Правило 16: Graceful Degradation
        logger.error(f"Ошибка при применении стратегии регулярности '{strategy}': {e}", exc_info=True)
        # В реальном приложении здесь можно было бы записать в AppState.error_log
        
    return df_result