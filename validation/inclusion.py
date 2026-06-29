# validation/inclusion.py
"""
Проверка принадлежности значений к справочникам (Inclusion).
"""
import pandas as pd
from typing import Dict, List, Tuple


def check_inclusion(
    df: pd.DataFrame, 
    inclusion_rules: Dict[str, List]
) -> Tuple[List[Dict], Dict[str, pd.Series]]:
    """
    Проверяет принадлежность значений к справочникам.
    
    Args:
        df: DataFrame для проверки
        inclusion_rules: Словарь {колонка: [допустимые_значения]}
        
    Returns:
        Кортеж (results, masks):
        - results: список словарей с нарушениями
        - masks: словарь масок нарушений {колонка: pd.Series}
    """
    results = []
    masks = {}
    
    for col, allowed_vals in inclusion_rules.items():
        if col in df.columns and allowed_vals:
            invalid_mask = ~df[col].isin(allowed_vals) & df[col].notna()
            violations = int(invalid_mask.sum())
            
            if violations > 0:
                masks[col] = invalid_mask
                results.append({
                    "Правило": f"Inclusion: {col}",
                    "Колонка": col,
                    "Нарушений": violations,
                    "% брака": f"{(violations / len(df)) * 100:.2f}%",
                    "Статус": "⚠️ Нарушено"
                })
    
    return results, masks