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


def compute_inclusion_violations(
    df: pd.DataFrame, 
    inclusion_rules: Dict[str, List]
) -> List[Dict]:
    """
    Вычисляет нарушения принадлежности к справочникам для DataFrame.
    
    Args:
        df: DataFrame для проверки
        inclusion_rules: Словарь {колонка: [допустимые_значения]}
        
    Returns:
        Список словарей с нарушениями:
        [
            {
                'column': str,
                'invalid_values': array,
                'count': int,
                'mask': pd.Series
            },
            ...
        ]
        
    Examples:
        >>> import pandas as pd
        >>> df = pd.DataFrame({'country': ['Russia', 'France']})
        >>> rules = {'country': ['Russia', 'USA']}
        >>> violations = compute_inclusion_violations(df, rules)
        >>> len(violations)
        1
    """
    violations = []
    for col, allowed_vals in inclusion_rules.items():
        if col in df.columns:
            invalid_mask = ~df[col].isin(allowed_vals) & df[col].notna()
            if invalid_mask.any():
                invalid_values = df.loc[invalid_mask, col].unique()
                violations.append({
                    'column': col,
                    'invalid_values': invalid_values,
                    'count': int(invalid_mask.sum()),
                    'mask': invalid_mask
                })
    return violations