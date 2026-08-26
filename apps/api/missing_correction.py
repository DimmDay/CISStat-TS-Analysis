"""Безопасный preview/apply для исправления пропусков (остановка «Пропуски»
модуля «Предобработка»).

Стратегии -- прямой перенос шести опций из легаси app.py (секция "Стратегии
обработки пропусков", ~строки 7936-8010: "Удалить строки", "Медиана/мода",
"Среднее/мода", "Ноль/Unknown", "Интерполяция", "Индикатор"), но с двумя
осознанными отличиями от Streamlit-прототипа:

1. Стратегия применяется ТОЛЬКО к явно выбранным колонкам, а не ко всем
   колонкам датасета разом. В Streamlit fill_strategy молча трогал все
   числовые/категориальные колонки, включая те, где пользователь не
   рассматривал пропуски -- то же архитектурное решение, что уже принято
   для apps/api/range_correction.py/format_correction.py (явный список
   columns), чтобы аналитик управлял ровно тем, что видит в обзоре.
2. drop_rows использует ОБЪЕДИНЕНИЕ пропусков только по выбранным колонкам
   (как preview_range_corrections), а не df.dropna() по всему датасету --
   иначе удаление строк из-за пропуска в непроверяемой колонке было бы
   неожиданным побочным эффектом.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.preprocessing.missing import profile_missing

STRATEGIES = {"drop_rows", "median_mode", "mean_mode", "constant", "interpolate", "flag"}


def preview_missing_corrections(
    df: pd.DataFrame,
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

    missing_columns = [column for column in columns if column not in df.columns]
    if missing_columns:
        raise ValueError(f"Колонка '{missing_columns[0]}' отсутствует в датасете")

    result_df = df.copy(deep=True)
    masks = {column: result_df[column].isnull() for column in columns}
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
            mask = masks[column]
            missing_count = int(mask.sum())
            if missing_count == 0:
                continue
            is_numeric = pd.api.types.is_numeric_dtype(result_df[column])

            if strategy == "median_mode":
                if is_numeric:
                    valid_values = result_df.loc[~mask, column]
                    if valid_values.empty:
                        raise ValueError(
                            f"Для колонки '{column}' нет корректных значений для расчёта медианы"
                        )
                    result_df[column] = result_df[column].fillna(valid_values.median())
                else:
                    mode = result_df.loc[~mask, column].mode()
                    fill_value = mode.iloc[0] if not mode.empty else "Unknown"
                    result_df[column] = result_df[column].fillna(fill_value)

            elif strategy == "mean_mode":
                if is_numeric:
                    valid_values = result_df.loc[~mask, column]
                    if valid_values.empty:
                        raise ValueError(
                            f"Для колонки '{column}' нет корректных значений для расчёта среднего"
                        )
                    result_df[column] = result_df[column].fillna(valid_values.mean())
                else:
                    mode = result_df.loc[~mask, column].mode()
                    fill_value = mode.iloc[0] if not mode.empty else "Unknown"
                    result_df[column] = result_df[column].fillna(fill_value)

            elif strategy == "constant":
                result_df[column] = result_df[column].fillna(0 if is_numeric else "Unknown")

            elif strategy == "interpolate":
                if not is_numeric:
                    raise ValueError(
                        f"Интерполяция доступна только для числовых колонок ('{column}' -- {result_df[column].dtype})"
                    )
                result_df[column] = result_df[column].interpolate(method="linear")

            else:  # flag
                flag_column = f"{column}_missing_flag"
                if flag_column in result_df.columns:
                    raise ValueError(f"Колонка '{flag_column}' уже существует")
                result_df[flag_column] = mask.astype(int)
                added_columns[column] = flag_column

    results: list[dict[str, Any]] = []
    for column in columns:
        missing_count = int(masks[column].sum())
        if strategy == "flag":
            still_missing = missing_count
            changed_count = 0
        elif strategy == "drop_rows":
            still_missing = int(result_df[column].isnull().sum()) if column in result_df.columns else 0
            changed_count = 0
        else:
            still_missing = int(result_df[column].isnull().sum())
            changed_count = missing_count - still_missing
        results.append({
            "column": column,
            "missing_count": missing_count,
            "changed_count": changed_count,
            "still_missing": still_missing,
            "missing_examples": [
                int(i) for i in df.index[masks[column]][:5].tolist()
            ],
            "flag_column": added_columns[column],
        })

    return result_df, results, rows_removed


def missing_correction_profile(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Тонкая обёртка над profile_missing для переиспользования в ответе
    /dataset/missing-corrections (next-profile после preview/apply) --
    тот же профиль, что отдаёт GET /dataset/missing-profile."""
    return profile_missing(df)
