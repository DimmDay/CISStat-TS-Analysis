# validation/referential.py
"""Единый профиль и маски ссылочной целостности.

Текущий контракт проекта хранит эталон родительского ключа непосредственно
в правиле ``allowed_values``. Он не выводится из проверяемого датасета:
иначе любая наблюдаемая «сирота» автоматически стала бы допустимой.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pandas as pd

from validation.inclusion import (
    coerce_inclusion_rule_to_series,
    inclusion_invalid_mask,
)


def referential_invalid_mask(series: pd.Series, allowed_values: list) -> pd.Series:
    """Общая маска «сирот»: непустой дочерний ключ отсутствует в эталоне."""
    return inclusion_invalid_mask(series, allowed_values)


def _value_label(value: Any) -> str:
    if value is None or pd.isna(value):
        return "—"
    return str(value.item() if hasattr(value, "item") else value)


def profile_referential(df: pd.DataFrame, rules: dict) -> list[dict[str, Any]]:
    """Профиль всех настроенных FK-правил, включая неприменимые."""
    profiles: list[dict[str, Any]] = []
    for index, raw_rule in enumerate(rules.get("referential", []) or []):
        rule = raw_rule if isinstance(raw_rule, dict) else {}
        rule_name = str(rule.get("name") or f"Связь {index + 1}")
        child_column = rule.get("child_column") or rule.get("column")
        raw_allowed = rule.get("allowed_values", [])
        allowed_values = list(raw_allowed) if isinstance(raw_allowed, (list, tuple, set)) else []
        default_value = rule.get("default_value")
        base = {
            "rule_index": index,
            "rule_name": rule_name,
            "child_column": str(child_column or ""),
            "allowed_values": allowed_values,
            "reference_count": len(allowed_values),
            "default_value": default_value,
            "default_valid": False,
            "supported_actions": [],
        }

        if not child_column:
            profiles.append({
                **base,
                "applicable": False,
                "applicability_message": "Не задана дочерняя колонка",
                "total_count": 0,
                "valid_count": 0,
                "invalid_count": None,
                "invalid_pct": None,
                "invalid_values": [],
            })
            continue
        if child_column not in df.columns:
            profiles.append({
                **base,
                "applicable": False,
                "applicability_message": f"Колонка '{child_column}' отсутствует в датасете",
                "total_count": 0,
                "valid_count": 0,
                "invalid_count": None,
                "invalid_pct": None,
                "invalid_values": [],
            })
            continue
        if not allowed_values:
            profiles.append({
                **base,
                "applicable": False,
                "applicability_message": "Справочник родительских ключей пуст",
                "total_count": 0,
                "valid_count": 0,
                "invalid_count": None,
                "invalid_pct": None,
                "invalid_values": [],
            })
            continue

        series = df[child_column]
        allowed_values, default_value = coerce_inclusion_rule_to_series(
            series, allowed_values, default_value
        )
        invalid_mask = referential_invalid_mask(series, allowed_values)
        total_count = int(series.notna().sum())
        invalid_count = int(invalid_mask.sum())
        valid_count = total_count - invalid_count
        invalid_pct = invalid_count / total_count * 100 if total_count else None
        valid_observed = series[series.notna() & series.isin(allowed_values)]
        default_valid = default_value is not None and default_value in allowed_values
        supported_actions = ["replace_null", "drop_rows", "flag"]
        if not valid_observed.empty:
            supported_actions.insert(0, "mode")
        if default_valid:
            supported_actions.insert(-1, "replace_default")

        profiles.append({
            **base,
            "child_column": str(child_column),
            "allowed_values": allowed_values,
            "reference_count": len(allowed_values),
            "default_value": default_value,
            "default_valid": default_valid,
            "applicable": True,
            "applicability_message": None,
            "total_count": total_count,
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "invalid_pct": round(invalid_pct, 2) if invalid_pct is not None else None,
            "invalid_values": [
                {"value": _value_label(value), "count": int(count)}
                for value, count in series[invalid_mask].value_counts(dropna=False).head(10).items()
            ],
            "supported_actions": supported_actions,
        })
    return profiles


def compute_referential_violations(
    df: pd.DataFrame,
    ref_results: List[Dict],
) -> List[Dict]:
    """Legacy-контракт Streamlit поверх общей dtype-aware маски."""
    violations = []
    for result in ref_results:
        column = result.get("Колонка") or result.get("child_column")
        raw_allowed = result.get("allowed_values", [])
        allowed_values = list(raw_allowed) if isinstance(raw_allowed, (list, tuple, set)) else []
        default_value = result.get("default_value", "Unknown")
        if column and column in df.columns and allowed_values:
            allowed_values, default_value = coerce_inclusion_rule_to_series(
                df[column], allowed_values, default_value
            )
            mask = referential_invalid_mask(df[column], allowed_values)
            if mask.any():
                violations.append({
                    "column": column,
                    "allowed_values": allowed_values,
                    "default_value": default_value,
                    "invalid_values": df.loc[mask, column].unique(),
                    "count": int(mask.sum()),
                    "mask": mask,
                })
    return violations
