"""Безопасный preview/apply для исправления нарушений min/max."""
from __future__ import annotations

from typing import Any

import pandas as pd

from validation.engine import profile_ranges, range_invalid_mask


STRATEGIES = {"clip", "median", "replace_null", "drop_rows", "flag"}


def preview_range_corrections(
    df: pd.DataFrame,
    rules: dict,
    columns: list[str],
    strategy: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]], int]:
    """Выполняет выбранную стратегию на глубокой копии DataFrame."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Неподдерживаемая стратегия исправления: {strategy}")
    if not columns:
        raise ValueError("Не выбрано ни одной колонки для исправления")
    if len(columns) != len(set(columns)):
        raise ValueError("Одна колонка не может повторяться в операции")

    profiles = {item["column"]: item for item in profile_ranges(df, rules)}
    missing_rules = [column for column in columns if column not in profiles]
    if missing_rules:
        raise ValueError(
            f"Для колонки '{missing_rules[0]}' нет активного правила диапазона"
        )

    result_df = df.copy(deep=True)
    masks = {
        column: range_invalid_mask(
            result_df[column],
            profiles[column]["min_allowed"],
            profiles[column]["max_allowed"],
        )
        for column in columns
    }
    rows_removed = 0
    added_columns: dict[str, str | None] = {column: None for column in columns}

    if strategy == "drop_rows":
        combined_mask = pd.Series(False, index=result_df.index)
        for mask in masks.values():
            combined_mask |= mask
        rows_removed = int(combined_mask.sum())
        result_df = result_df.loc[~combined_mask].reset_index(drop=True)
    else:
        for column in columns:
            item = profiles[column]
            mask = masks[column]
            invalid_count = int(mask.sum())
            if strategy == "clip":
                result_df[column] = result_df[column].clip(
                    lower=item["min_allowed"],
                    upper=item["max_allowed"],
                )
            elif strategy == "median":
                valid_values = result_df.loc[result_df[column].notna() & ~mask, column]
                if invalid_count and valid_values.empty:
                    raise ValueError(
                        f"Для колонки '{column}' нет корректных значений для расчёта медианы"
                    )
                if invalid_count:
                    result_df.loc[mask, column] = valid_values.median()
            elif strategy == "replace_null":
                result_df.loc[mask, column] = pd.NA
            else:
                flag_column = f"{column}_range_valid"
                if flag_column in result_df.columns:
                    raise ValueError(f"Колонка '{flag_column}' уже существует")
                result_df[flag_column] = ~mask
                added_columns[column] = flag_column

    results: list[dict[str, Any]] = []
    for column in columns:
        source_item = profiles[column]
        invalid_count = int(masks[column].sum())
        still_invalid = (
            invalid_count
            if strategy == "flag"
            else int(range_invalid_mask(
                result_df[column],
                source_item["min_allowed"],
                source_item["max_allowed"],
            ).sum())
        )
        results.append({
            "column": column,
            "invalid_count": invalid_count,
            "changed_count": 0 if strategy == "flag" else invalid_count,
            "still_invalid": still_invalid,
            "invalid_examples": source_item["invalid_examples"],
            "flag_column": added_columns[column],
        })

    return result_df, results, rows_removed
