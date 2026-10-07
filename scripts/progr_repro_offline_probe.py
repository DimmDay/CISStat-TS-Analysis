#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Офлайн-прикидка (read-only, без API): что происходит с IQR-профилем
выбросов на демо-датасете forecast_monitor_synthetic_n150 после
(1) cap-исправления выбросов, (2) добавления diff-колонки стационарности,
(3) повторного cap-исправления. Только функции платформы
(app.preprocessing.outliers), никакой пере-имплементации."""
import sys
from pathlib import Path

import pandas as pd

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
sys.path.insert(0, str(REPO))

from app.preprocessing.outliers import (  # noqa: E402
    detect_outlier_mask,
    profile_outliers,
    outliers_summary,
)

CSV = Path("/home/z/my-project/scripts/repro_data/forecast_monitor_synthetic_n150.csv")


def summarize(df: pd.DataFrame, label: str) -> None:
    profiles = profile_outliers(df, method="iqr")
    summary = outliers_summary(profiles, total_rows=len(df))
    print(f"== {label}")
    print(f"   rows={summary['total_rows']} numeric_cols={summary['total_numeric_columns']} "
          f"total_outliers={summary['total_outliers']} affected={summary['affected_columns']}")
    for item in profiles:
        if item["outlier_count"]:
            print(f"   - {item['column']}: {item['outlier_count']} @ {item['outlier_examples']}")
    print()


def cap_column(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Точная копия стратегии 'cap' из apps/api/outliers_correction.py
    (границы всегда IQR 1.5 по исходной колонке, clip)."""
    out = df.copy(deep=True)
    valid = df[column].dropna()
    q1, q3 = valid.quantile(0.25), valid.quantile(0.75)
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    out[column] = out[column].clip(lower=lower, upper=upper)
    return out


def main() -> None:
    df0 = pd.read_csv(CSV)
    summarize(df0, "ШАГ 0. Исходный датасет (3 пропуска + 4 выброса)")

    # Шаг 1: чинит пропуски (интерполяция не важна для выбросов; возьмём
    # медиану как одну из стратегий мастера -- на IQR-профиль выбросов
    # влияет мало что) -- фактически заполним линейной интерполяцией.
    df1 = df0.copy()
    df1["value"] = df1["value"].interpolate(limit_direction="both")
    summarize(df1, "ШАГ 1. Пропуски исправлены (интерполяция)")

    # Шаг 2: чинит выбросы (cap, как в мастере по умолчанию)
    df2 = cap_column(df1, "value")
    summarize(df2, "ШАГ 2. Выбросы исправлены (cap value)")

    # Шаг 3: остановка «Стационарность» -- добавляет колонку по
    # рекомендации. Варианты метода: first_difference / seasonal_difference
    # / combined_difference / log_difference -- добавляем по очереди.
    for method, col in [
        ("first_difference", "value_diff1"),
        ("seasonal_difference", "value_seasonal_diff1"),
        ("second_difference", "value_diff2"),
    ]:
        if method == "first_difference":
            col_values = df2["value"].diff()
            prefix = 1
        elif method == "second_difference":
            col_values = df2["value"].diff().diff()
            prefix = 2
        else:  # seasonal_difference, period 12
            col_values = df2["value"].diff(12)
            prefix = 12
        df3 = df2.copy()
        df3[col] = col_values
        # платформа УДАЛЯЕТ неопределённый префикс (докстринг apply)
        df3 = df3.iloc[prefix:].reset_index(drop=True)
        summarize(df3, f"ШАГ 3. + колонка {col} ({method}), префикс {prefix} строк удалён")

        # Шаг 4: повторное cap-исправление колонки(и) с выбросами
        df4 = df3
        for c in [c for c in df4.select_dtypes("number") if detect_outlier_mask(df4[c], "iqr").any()]:
            df4 = cap_column(df4, c)
        summarize(df4, f"ШАГ 4. Повторный cap по всем колонкам с выбросами (после {col})")


if __name__ == "__main__":
    main()
