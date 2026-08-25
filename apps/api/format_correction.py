"""Безопасный preview/apply для исправления regex-форматов."""
from __future__ import annotations

from typing import Any

import pandas as pd

from validation.engine import format_invalid_mask, profile_formats


STRATEGIES = {"replace_null", "smart_replace", "normalize", "flag"}


def _normalized(series: pd.Series) -> pd.Series:
    return (
        series.astype("string")
        .str.strip()
        .str.lower()
        .str.replace(r"[^\w\s@.\-+]", "", regex=True)
        .str.replace(r"\s+", " ", regex=True)
    )


def _smart_replacement(
    series: pd.Series,
    valid_mask: pd.Series,
    column: str,
    pattern: str,
) -> Any:
    if pd.api.types.is_numeric_dtype(series):
        valid_values = pd.to_numeric(series[valid_mask], errors="coerce").dropna()
        if valid_values.empty:
            return pd.NA
        median = valid_values.median()
        return int(round(median)) if pd.api.types.is_integer_dtype(series) else median
    signature = f"{column} {pattern}".lower()
    if "mail" in signature or "@" in pattern:
        return "unknown@example.com"
    if "phone" in signature or "тел" in signature or "\\+7" in pattern:
        return "+79990000000"
    if "date" in signature or "дата" in signature or "\\d{4}" in pattern:
        return pd.NaT
    if "currency" in signature or "валют" in signature:
        return "USD"
    return pd.NA


def preview_format_corrections(
    df: pd.DataFrame,
    rules: dict,
    columns: list[str],
    strategy: str,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Выполняет выбранную Streamlit-стратегию только на копии DataFrame."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Неподдерживаемая стратегия исправления: {strategy}")
    if not columns:
        raise ValueError("Не выбрано ни одной колонки для исправления")
    if len(columns) != len(set(columns)):
        raise ValueError("Одна колонка не может повторяться в операции")

    profiles = {item["column"]: item for item in profile_formats(df, rules)}
    missing_rules = [column for column in columns if column not in profiles]
    if missing_rules:
        raise ValueError(f"Для колонки '{missing_rules[0]}' нет активного правила формата")

    result_df = df.copy(deep=True)
    results: list[dict[str, Any]] = []
    for column in columns:
        item = profiles[column]
        pattern = item["pattern"]
        source = result_df[column].copy()
        invalid_mask = format_invalid_mask(source, pattern)
        invalid_count = int(invalid_mask.sum())
        changed_count = 0
        flag_column = None

        if strategy == "flag":
            flag_column = f"{column}_format_valid"
            if flag_column in result_df.columns:
                raise ValueError(f"Колонка '{flag_column}' уже существует")
            result_df[flag_column] = ~format_invalid_mask(source, pattern)
        elif strategy == "replace_null":
            result_df.loc[invalid_mask, column] = pd.NA
            changed_count = invalid_count
        elif strategy == "smart_replace":
            if isinstance(source.dtype, pd.CategoricalDtype):
                result_df[column] = source.astype("object")
            result_df.loc[invalid_mask, column] = _smart_replacement(
                source, source.notna() & ~invalid_mask, column, pattern
            )
            changed_count = invalid_count
        else:
            if pd.api.types.is_numeric_dtype(source):
                raise ValueError(
                    f"Колонка '{column}' числовая: нормализация строк неприменима"
                )
            normalized = _normalized(source)
            changed_mask = invalid_mask & normalized.ne(source.astype("string")).fillna(False)
            if isinstance(source.dtype, pd.CategoricalDtype):
                result_df[column] = source.astype("string")
            result_df.loc[invalid_mask, column] = normalized[invalid_mask]
            changed_count = int(changed_mask.sum())

        still_invalid = invalid_count if strategy == "flag" else int(
            format_invalid_mask(result_df[column], pattern).sum()
        )
        results.append({
            "column": column,
            "invalid_count": invalid_count,
            "changed_count": changed_count,
            "still_invalid": still_invalid,
            "invalid_examples": item["invalid_examples"],
            "flag_column": flag_column,
        })

    return result_df, results
