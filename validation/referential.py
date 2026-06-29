# validation/referential.py
"""
Проверка ссылочной целостности (Referential Integrity).
"""
import pandas as pd
from typing import Dict, List


def compute_referential_violations(
    df: pd.DataFrame, 
    ref_results: List[Dict]
) -> List[Dict]:
    """
    Вычисляет нарушения ссылочной целостности для DataFrame.
    
    Args:
        df: DataFrame для проверки
        ref_results: Список словарей с правилами ссылочной целостности.
                    Каждый словарь должен содержать:
                    - 'Колонка' или 'child_column': имя колонки
                    - 'allowed_values': список допустимых значений
                    - 'default_value': значение по умолчанию (опционально)
        
    Returns:
        Список словарей с нарушениями:
        [
            {
                'column': str,
                'allowed_values': list,
                'default_value': str,
                'invalid_values': array,
                'count': int,
                'mask': pd.Series
            },
            ...
        ]
        
    Examples:
        >>> import pandas as pd
        >>> df = pd.DataFrame({'code': ['A', 'X', 'B']})
        >>> rules = [{'Колонка': 'code', 'allowed_values': ['A', 'B'], 'default_value': '?'}]
        >>> violations = compute_referential_violations(df, rules)
        >>> len(violations)
        1
    """
    violations = []
    for r in ref_results:
        col = r.get('Колонка') or r.get('child_column')
        allowed_values = r.get('allowed_values', [])
        default_val = r.get('default_value', 'Unknown')
        
        if col and col in df.columns and allowed_values:
            mask = ~df[col].isin(allowed_values) & df[col].notna()
            if mask.any():
                invalid_values = df.loc[mask, col].unique()
                violations.append({
                    'column': col,
                    'allowed_values': allowed_values,
                    'default_value': default_val,
                    'invalid_values': invalid_values,
                    'count': int(mask.sum()),
                    'mask': mask
                })
    return violations