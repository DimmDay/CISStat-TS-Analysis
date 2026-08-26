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


def coerce_inclusion_rule_to_series(
    series: pd.Series,
    allowed_values: list,
    default_value: Any = None,
) -> tuple[list, Any]:
    """Align text-editor rule values with the actual column scalar type.

    HTML inputs produce strings even for a numeric dataset column.  Membership
    comparison is type-sensitive, so ``"723774"`` must become ``723774`` for
    an integer column.  Conversion is driven by the series (not by the token)
    so string identifiers such as ``"001"`` retain their leading zeroes.
    Values that cannot be safely converted are kept unchanged and simply can
    never match that typed column.
    """
    non_null = series.dropna()
    inferred = pd.api.types.infer_dtype(non_null, skipna=True) if not non_null.empty else "empty"
    numeric_target = (
        pd.api.types.is_numeric_dtype(series.dtype)
        and not pd.api.types.is_bool_dtype(series.dtype)
    ) or inferred in {"integer", "floating", "mixed-integer-float", "decimal"}
    integer_target = pd.api.types.is_integer_dtype(series.dtype) or inferred == "integer"
    boolean_target = pd.api.types.is_bool_dtype(series.dtype) or inferred == "boolean"
    string_target = (
        pd.api.types.is_string_dtype(series.dtype)
        and not pd.api.types.is_object_dtype(series.dtype)
        and not numeric_target
        and not boolean_target
    ) or inferred in {"string", "unicode", "bytes"}

    def convert(value: Any) -> Any:
        if value is None:
            return None
        if numeric_target and not isinstance(value, bool):
            try:
                converted = pd.to_numeric(value, errors="raise")
                converted = converted.item() if hasattr(converted, "item") else converted
                if integer_target and float(converted).is_integer():
                    return int(converted)
                return converted
            except (TypeError, ValueError, OverflowError):
                return value
        if boolean_target and isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1"}:
                return True
            if normalized in {"false", "0"}:
                return False
        if string_target and not isinstance(value, str):
            return str(value)
        return value

    return [convert(value) for value in allowed_values], convert(default_value)


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
            allowed_vals, _default = coerce_inclusion_rule_to_series(
                df[col], allowed_vals, _default
            )
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
            allowed_vals, _default = coerce_inclusion_rule_to_series(
                df[col], allowed_vals, _default
            )
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
