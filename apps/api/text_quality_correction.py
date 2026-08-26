"""Безопасный preview/apply исправлений целостности текста."""
from __future__ import annotations

from typing import Any

import pandas as pd

from validation.text_quality import _normalize_values, profile_text_quality, text_quality_masks


STRATEGIES = {"normalize", "replace_null", "drop_rows", "replace_unknown", "flag"}


def preview_text_quality_corrections(
    df: pd.DataFrame,
    rules: dict[str, Any],
    columns: list[str],
    strategy: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]], int]:
    """Применяет стратегию к глубокой копии выбранных текстовых колонок."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Неподдерживаемая стратегия исправления: {strategy}")
    if not columns:
        raise ValueError("Не выбрано ни одной колонки для исправления")
    if len(columns) != len(set(columns)):
        raise ValueError("Одна колонка не может повторяться в операции")

    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"Колонка '{missing[0]}' отсутствует в датасете")
    non_text = [
        column for column in columns
        if not (pd.api.types.is_object_dtype(df[column]) or pd.api.types.is_string_dtype(df[column]))
    ]
    if non_text:
        raise ValueError(f"Колонка '{non_text[0]}' не является текстовой")

    result = df.copy(deep=True)
    masks = {
        column: text_quality_masks(result[column], rules, column=column)["combined"]
        for column in columns
    }
    rows_removed = 0
    flag_columns: dict[str, str | None] = {column: None for column in columns}

    if strategy == "drop_rows":
        combined = pd.Series(False, index=result.index, dtype=bool)
        for mask in masks.values():
            combined |= mask
        rows_removed = int(combined.sum())
        result = result.loc[~combined].reset_index(drop=True)
    else:
        for column, mask in masks.items():
            if strategy == "normalize":
                result.loc[mask, column] = _normalize_values(result.loc[mask, column])
            elif strategy == "replace_null":
                result.loc[mask, column] = pd.NA
            elif strategy == "replace_unknown":
                result.loc[mask, column] = "Неизвестно"
            else:
                flag_column = f"{column}_text_valid"
                if flag_column in result.columns:
                    raise ValueError(f"Колонка '{flag_column}' уже существует")
                result[flag_column] = ~mask
                flag_columns[column] = flag_column

    next_profile = {item["column"]: item for item in profile_text_quality(result, rules)}
    results = []
    for column in columns:
        invalid_count = int(masks[column].sum())
        still_invalid = (
            invalid_count
            if strategy == "flag"
            else int(next_profile.get(column, {}).get("invalid_count", 0))
        )
        results.append({
            "column": column,
            "invalid_count": invalid_count,
            "changed_count": 0 if strategy == "flag" else invalid_count,
            "still_invalid": still_invalid,
            "flag_column": flag_columns[column],
        })
    return result, results, rows_removed
