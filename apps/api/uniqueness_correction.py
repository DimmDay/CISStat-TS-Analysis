"""Транзакционный preview/apply обработки нарушений уникальности."""
from __future__ import annotations

from typing import Any

import pandas as pd

from validation.engine import profile_uniqueness, uniqueness_duplicate_mask


STRATEGIES = {"keep_first", "keep_last", "drop_all", "aggregate", "flag"}


def preview_uniqueness_correction(
    df: pd.DataFrame,
    rules: dict,
    strategy: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Применяет стратегию к глубокой копии и возвращает точные последствия."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Неподдерживаемая стратегия исправления: {strategy}")
    source_profile = profile_uniqueness(df, rules)
    if not source_profile["applicable"]:
        raise ValueError(source_profile["applicability_message"] or "Правило уникальности неприменимо")
    if strategy not in source_profile["supported_actions"]:
        raise ValueError("Агрегация неприменима при проверке полных строк")

    result_df = df.copy(deep=True)
    duplicate_rows = int(source_profile["duplicate_rows"] or 0)
    redundant_rows = int(source_profile["redundant_rows"] or 0)
    rows_removed = 0
    rows_changed = 0
    added_columns: list[str] = []

    if strategy == "keep_first":
        remove_mask = uniqueness_duplicate_mask(result_df, rules, keep="first")
        rows_removed = int(remove_mask.sum())
        rows_changed = rows_removed
        result_df = result_df.loc[~remove_mask].reset_index(drop=True)
    elif strategy == "keep_last":
        remove_mask = uniqueness_duplicate_mask(result_df, rules, keep="last")
        rows_removed = int(remove_mask.sum())
        rows_changed = rows_removed
        result_df = result_df.loc[~remove_mask].reset_index(drop=True)
    elif strategy == "drop_all":
        remove_mask = uniqueness_duplicate_mask(result_df, rules, keep=False)
        rows_removed = int(remove_mask.sum())
        rows_changed = rows_removed
        result_df = result_df.loc[~remove_mask].reset_index(drop=True)
    elif strategy == "aggregate":
        key_columns = source_profile["key_columns"]
        aggregations = {
            column: "mean" if pd.api.types.is_numeric_dtype(result_df[column]) else "first"
            for column in result_df.columns if column not in key_columns
        }
        if aggregations:
            result_df = result_df.groupby(
                key_columns, as_index=False, sort=False, dropna=False
            ).agg(aggregations)
        else:
            result_df = result_df.drop_duplicates(subset=key_columns, keep="first").reset_index(drop=True)
        rows_removed = len(df) - len(result_df)
        rows_changed = redundant_rows
    else:
        flag_column = "uniqueness_valid"
        if flag_column in result_df.columns:
            raise ValueError(f"Колонка '{flag_column}' уже существует")
        result_df[flag_column] = ~uniqueness_duplicate_mask(result_df, rules, keep=False)
        rows_changed = duplicate_rows
        added_columns = [flag_column]

    next_profile = profile_uniqueness(result_df, rules)
    return result_df, {
        "duplicate_rows": duplicate_rows,
        "redundant_rows": redundant_rows,
        "rows_changed": rows_changed,
        "rows_removed": rows_removed,
        "still_duplicate_rows": (
            duplicate_rows if strategy == "flag" else int(next_profile["duplicate_rows"] or 0)
        ),
        "added_columns": added_columns,
    }
