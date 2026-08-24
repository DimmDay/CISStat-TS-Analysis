"""Безопасное преобразование dtype для активного DataFrame сессии.

Функция строит НОВУЮ копию DataFrame и отчёт по каждой операции. Решение
о применении/отклонении принимает роутер: dry-run никогда не мутирует
сессию, а reject-policy может атомарно отменить весь набор операций.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.data.detectors import smart_to_datetime


TARGET_TYPES = {"integer", "float", "datetime", "string", "boolean"}
_TRUE_TOKENS = {"true", "1", "yes", "y", "да", "истина"}
_FALSE_TOKENS = {"false", "0", "no", "n", "нет", "ложь"}


def _to_boolean(series: pd.Series) -> pd.Series:
    normalized = series.astype("string").str.strip().str.lower()
    mapping = {**{token: True for token in _TRUE_TOKENS}, **{token: False for token in _FALSE_TOKENS}}
    return normalized.map(mapping).astype("boolean")


def _to_datetime(series: pd.Series) -> pd.Series:
    """Переиспользует smart_to_datetime; fallback нужен для грязной
    year-only колонки, где nullable Int64-конверсия встречает мусор."""
    try:
        return smart_to_datetime(series)
    except (TypeError, ValueError):
        numeric = pd.to_numeric(series, errors="coerce")
        valid_numeric = numeric.dropna()
        if not valid_numeric.empty and valid_numeric.between(1800, 2100).mean() >= 0.8:
            years = numeric.round().astype("Int64").astype("string")
            return pd.to_datetime(years, format="%Y", errors="coerce")
        return pd.to_datetime(series, errors="coerce")


def _convert_series(series: pd.Series, target_type: str) -> pd.Series:
    if target_type == "float":
        return pd.to_numeric(series, errors="coerce").astype("Float64")
    if target_type == "integer":
        numeric = pd.to_numeric(series, errors="coerce")
        integral = numeric.isna() | ((numeric % 1).abs() < 1e-12)
        return numeric.where(integral).round().astype("Int64")
    if target_type == "datetime":
        return _to_datetime(series)
    if target_type == "string":
        return series.astype("string")
    if target_type == "boolean":
        return _to_boolean(series)
    raise ValueError(f"Неподдерживаемый целевой тип: {target_type}")


def preview_type_conversions(
    df: pd.DataFrame,
    conversions: list[dict[str, Any]],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Транзакционно рассчитывает преобразования на копии DataFrame.

    converted_count -- число исходно непустых значений, которые удалось
    привести. invalid_count не включает уже существовавшие пропуски.
    """
    if not conversions:
        raise ValueError("Не выбрано ни одной колонки для преобразования")

    columns = [str(item.get("column", "")) for item in conversions]
    if len(columns) != len(set(columns)):
        raise ValueError("Одна колонка не может быть преобразована дважды за одну операцию")

    result_df = df.copy(deep=True)
    results: list[dict[str, Any]] = []

    for item in conversions:
        column = str(item.get("column", ""))
        target_type = str(item.get("target_type", ""))
        if column not in result_df.columns:
            raise ValueError(f"Колонка '{column}' отсутствует в датасете")
        if target_type not in TARGET_TYPES:
            raise ValueError(f"Неподдерживаемый целевой тип: {target_type}")

        source = result_df[column]
        converted = _convert_series(source, target_type)
        invalid_mask = source.notna() & converted.isna()
        invalid_count = int(invalid_mask.sum())
        source_non_null = int(source.notna().sum())

        result_df[column] = converted
        results.append({
            "column": column,
            "from_dtype": str(source.dtype),
            "to_dtype": str(converted.dtype),
            "converted_count": source_non_null - invalid_count,
            "invalid_count": invalid_count,
            "invalid_examples": [str(value) for value in source[invalid_mask].head(3).tolist()],
        })

    return result_df, results
