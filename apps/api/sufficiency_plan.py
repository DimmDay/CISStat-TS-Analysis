"""Безопасный preview/apply решений по достаточности наблюдений."""
from __future__ import annotations

from typing import Any

import pandas as pd

from validation.sufficiency import profile_sufficiency


def preview_sufficiency_plan(
    df: pd.DataFrame,
    rules: dict[str, Any],
    strategy: str,
    *,
    target_column: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    profile = profile_sufficiency(df, rules, target_column=target_column)
    if not profile["applicable"]:
        raise ValueError(profile["applicability_message"] or "Проверка достаточности неприменима")
    if strategy not in profile["supported_actions"]:
        raise ValueError(f"Стратегия '{strategy}' не поддерживается")

    sufficient = [item["group"] for item in profile["groups"] if item["failed_checks"] == 0]
    insufficient = [item["group"] for item in profile["groups"] if item["failed_checks"] > 0]
    corrected = df.copy(deep=True)
    added_columns: list[str] = []
    rows_removed = 0

    if strategy == "flag_groups":
        flag_column = "_sufficiency_eligible"
        entity_column = profile["entity_column"]
        if entity_column:
            corrected[flag_column] = corrected[entity_column].astype(str).isin(set(sufficient))
        else:
            corrected[flag_column] = len(insufficient) == 0
        added_columns.append(flag_column)
    elif strategy == "drop_groups":
        entity_column = profile["entity_column"]
        if entity_column is None:
            raise ValueError("Исключение доступно только для панельного ряда с группирующей колонкой")
        if not sufficient:
            raise ValueError("Нельзя исключить все группы: выберите ограничение моделей или маркировку")
        keep = corrected[entity_column].astype(str).isin(set(sufficient))
        rows_removed = int((~keep).sum())
        corrected = corrected.loc[keep].reset_index(drop=True)

    return corrected, {
        "strategy": strategy,
        "rows_before": int(len(df)),
        "rows_after": int(len(corrected)),
        "rows_removed": rows_removed,
        "added_columns": added_columns,
        "eligible_groups": sufficient,
        "insufficient_groups": insufficient,
        "profile": profile_sufficiency(corrected, rules, target_column=target_column),
    }
