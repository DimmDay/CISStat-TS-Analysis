"""Безопасный preview/apply для исправления принадлежности к наборам."""
from __future__ import annotations

from typing import Any

import pandas as pd

from validation.engine import profile_inclusion
from validation.inclusion import inclusion_invalid_mask


STRATEGIES = {"mode", "replace_null", "drop_rows", "replace_default", "flag"}


def preview_inclusion_corrections(
    df: pd.DataFrame,
    rules: dict,
    columns: list[str],
    strategy: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]], int]:
    """Apply one strategy to a deep copy using the active explicit domains."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Неподдерживаемая стратегия исправления: {strategy}")
    if not columns:
        raise ValueError("Не выбрано ни одной колонки для исправления")
    if len(columns) != len(set(columns)):
        raise ValueError("Одна колонка не может повторяться в операции")

    profiles = {item["column"]: item for item in profile_inclusion(df, rules)}
    missing_rules = [column for column in columns if column not in profiles]
    if missing_rules:
        raise ValueError(
            f"Для колонки '{missing_rules[0]}' нет активного допустимого набора"
        )

    result_df = df.copy(deep=True)
    masks = {
        column: inclusion_invalid_mask(result_df[column], profiles[column]["allowed_values"])
        for column in columns
    }
    rows_removed = 0
    flag_columns: dict[str, str | None] = {column: None for column in columns}
    replacement_values: dict[str, Any] = {column: None for column in columns}

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
            if strategy == "mode":
                valid_values = result_df.loc[
                    result_df[column].notna()
                    & result_df[column].isin(item["allowed_values"]),
                    column,
                ]
                if invalid_count and valid_values.empty:
                    raise ValueError(
                        f"Для колонки '{column}' нет допустимых значений для расчёта моды"
                    )
                if invalid_count:
                    replacement = valid_values.value_counts().index[0]
                    result_df.loc[mask, column] = replacement
                    replacement_values[column] = replacement
            elif strategy == "replace_null":
                result_df.loc[mask, column] = pd.NA
            elif strategy == "replace_default":
                if not item["default_valid"]:
                    raise ValueError(
                        f"Для колонки '{column}' значение по умолчанию отсутствует или не входит в допустимый набор"
                    )
                result_df.loc[mask, column] = item["default_value"]
                replacement_values[column] = item["default_value"]
            else:
                flag_column = f"{column}_inclusion_valid"
                if flag_column in result_df.columns:
                    raise ValueError(f"Колонка '{flag_column}' уже существует")
                result_df[flag_column] = ~mask
                flag_columns[column] = flag_column

    results: list[dict[str, Any]] = []
    for column in columns:
        source_item = profiles[column]
        invalid_count = int(masks[column].sum())
        still_invalid = (
            invalid_count
            if strategy == "flag"
            else int(inclusion_invalid_mask(
                result_df[column], source_item["allowed_values"]
            ).sum())
        )
        results.append({
            "column": column,
            "invalid_count": invalid_count,
            "changed_count": 0 if strategy == "flag" else invalid_count,
            "still_invalid": still_invalid,
            "replacement_value": replacement_values[column],
            "flag_column": flag_columns[column],
        })

    return result_df, results, rows_removed
