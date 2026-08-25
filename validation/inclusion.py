# validation/inclusion.py
"""
Проверка принадлежности значений к справочникам (Inclusion).
"""
import pandas as pd
from typing import Any, Dict, List, Tuple


def normalize_inclusion_rule(config: Any, fallback_default: Any = None) -> tuple[list, Any]:
    """Return ``(allowed_values, default)`` for current and legacy rules.

    Rule templates use ``{allowed_values: [...], default_value: ...}``, while
    early user rules stored the list directly.  Keeping the normalization here
    prevents validators and correction tools from interpreting mapping keys as
    allowed dataset values.
    """
    if isinstance(config, dict):
        allowed = config.get("allowed_values", [])
        default = config.get("default_value", fallback_default)
    else:
        allowed = config
        default = fallback_default
    return (list(allowed) if isinstance(allowed, (list, tuple, set)) else []), default


def inclusion_invalid_mask(series: pd.Series, allowed_values: list) -> pd.Series:
    """Build the shared membership-violation mask; nulls are checked elsewhere."""
    return series.notna() & ~series.isin(allowed_values)


def check_inclusion(
    df: pd.DataFrame, 
    inclusion_rules: Dict[str, Any]
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
    
    for col, config in inclusion_rules.items():
        allowed_vals, _default = normalize_inclusion_rule(config)
        if col in df.columns and allowed_vals:
            invalid_mask = inclusion_invalid_mask(df[col], allowed_vals)
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
    inclusion_rules: Dict[str, Any]
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
    for col, config in inclusion_rules.items():
        allowed_vals, _default = normalize_inclusion_rule(config)
        if col in df.columns and allowed_vals:
            invalid_mask = inclusion_invalid_mask(df[col], allowed_vals)
            if invalid_mask.any():
                invalid_values = df.loc[invalid_mask, col].unique()
                violations.append({
                    'column': col,
                    'invalid_values': invalid_values,
                    'count': int(invalid_mask.sum()),
                    'mask': invalid_mask
                })
    return violations
