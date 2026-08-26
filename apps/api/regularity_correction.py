"""Строгий preview/apply исправлений равномерности временного шага."""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.data.detectors import smart_to_datetime
from validation.regularity import (
    normalize_frequency,
    profile_regularity,
    regularity_violation_mask,
)


STRATEGIES = {"sort", "interpolate", "ffill", "bfill", "asfreq", "fictitious_zero", "flag"}


def _aggregate_duplicate_dates(group: pd.DataFrame, date_column: str, entity_column: str | None) -> tuple[pd.DataFrame, int]:
    duplicate_count = int(group[date_column].duplicated(keep="first").sum())
    if duplicate_count == 0:
        return group.copy(), 0
    value_columns = [column for column in group.columns if column not in {date_column, entity_column}]
    aggregations = {
        column: "mean" if pd.api.types.is_numeric_dtype(group[column]) and not pd.api.types.is_bool_dtype(group[column]) else "first"
        for column in value_columns
    }
    if aggregations:
        aggregated = group.groupby(date_column, as_index=False, sort=True).agg(aggregations)
    else:
        aggregated = group[[date_column]].drop_duplicates().sort_values(date_column)
    return aggregated, duplicate_count


def _resample_group(
    group: pd.DataFrame,
    date_column: str,
    entity_column: str | None,
    entity_value: Any,
    frequency: str,
    strategy: str,
) -> tuple[pd.DataFrame, int]:
    group = group.sort_values(date_column)
    aggregated, duplicates = _aggregate_duplicate_dates(group, date_column, entity_column)
    indexed = aggregated.set_index(date_column).sort_index()
    full_index = pd.date_range(indexed.index.min(), indexed.index.max(), freq=frequency)
    result = indexed.reindex(full_index)
    numeric_columns = [
        column for column in result.columns
        if pd.api.types.is_numeric_dtype(result[column]) and not pd.api.types.is_bool_dtype(result[column])
    ]
    other_columns = [column for column in result.columns if column not in numeric_columns]

    if strategy == "interpolate":
        if numeric_columns:
            result[numeric_columns] = result[numeric_columns].interpolate(method="linear")
        if other_columns:
            result[other_columns] = result[other_columns].ffill().bfill()
    elif strategy == "ffill":
        result = result.ffill()
    elif strategy == "bfill":
        result = result.bfill()
    elif strategy == "fictitious_zero":
        if numeric_columns:
            result[numeric_columns] = result[numeric_columns].fillna(0)
        if other_columns:
            result[other_columns] = result[other_columns].ffill().bfill()
    # asfreq оставляет новые значения пропусками.

    result.index.name = date_column
    result = result.reset_index()
    if entity_column is not None:
        result[entity_column] = entity_value
    return result, duplicates


def _resample(
    df: pd.DataFrame,
    date_column: str,
    entity_column: str | None,
    frequency: str,
    strategy: str,
) -> tuple[pd.DataFrame, int]:
    frames: list[pd.DataFrame] = []
    duplicates = 0
    if entity_column is None:
        frame, count = _resample_group(df, date_column, None, None, frequency, strategy)
        frames.append(frame); duplicates += count
    else:
        for value, group in df.groupby(entity_column, dropna=False, sort=False):
            frame, count = _resample_group(group, date_column, entity_column, value, frequency, strategy)
            frames.append(frame); duplicates += count
    result = pd.concat(frames, ignore_index=True) if frames else df.iloc[:0].copy()
    # Восстанавливаем исходный порядок и набор колонок: legacy-функция
    # теряла bool/extension-колонки, строгая версия сохраняет их все.
    for column in df.columns:
        if column not in result.columns:
            result[column] = pd.NA
    return result[df.columns.tolist()], duplicates


def preview_regularity_correction(
    df: pd.DataFrame,
    rules: dict[str, Any],
    strategy: str,
    frequency: str | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Применяет одну стратегию к глубокой копии и возвращает последствия."""
    if strategy not in STRATEGIES:
        raise ValueError(f"Неподдерживаемая стратегия исправления: {strategy}")
    before = profile_regularity(df, rules)
    if not before["applicable"]:
        raise ValueError(before["applicability_message"] or "Проверка равномерности неприменима")
    date_column = before["date_column"]
    entity_column = before["entity_column"]
    assert date_column is not None
    normalized_frequency = normalize_frequency(frequency or before["target_frequency"])
    if strategy in {"interpolate", "ffill", "bfill", "asfreq", "fictitious_zero"} and normalized_frequency is None:
        raise ValueError("Не удалось определить частоту для ресемплирования")

    result = df.copy(deep=True)
    converted = smart_to_datetime(result[date_column])
    if int((result[date_column].notna() & converted.isna()).sum()) > 0 and strategy != "flag":
        raise ValueError("Временная колонка содержит некорректные даты; сначала исправьте типы или форматы")
    result[date_column] = converted
    duplicates_aggregated = 0
    added_columns: list[str] = []

    if strategy == "sort":
        sort_columns = [column for column in (entity_column, date_column) if column is not None]
        result = result.sort_values(sort_columns, na_position="last").reset_index(drop=True)
    elif strategy == "flag":
        flag_column = "_has_gap"
        if flag_column in result.columns:
            raise ValueError(f"Колонка '{flag_column}' уже существует")
        result[flag_column] = regularity_violation_mask(df, rules).to_numpy()
        added_columns.append(flag_column)
    else:
        assert normalized_frequency is not None
        result, duplicates_aggregated = _resample(
            result, date_column, entity_column, normalized_frequency, strategy
        )

    after = profile_regularity(result, rules)
    summary = {
        "strategy": strategy,
        "frequency": normalized_frequency,
        "rows_before": int(len(df)),
        "rows_after": int(len(result)),
        "rows_added": max(int(len(result) - len(df)), 0),
        "duplicates_aggregated": duplicates_aggregated,
        "total_violations_before": int(before["total_violations"]),
        "total_violations_after": int(after["total_violations"]),
        "sort_violations_before": int(before["sort_violations"]),
        "sort_violations_after": int(after["sort_violations"]),
        "added_columns": added_columns,
        "profile": after,
    }
    return result, summary
