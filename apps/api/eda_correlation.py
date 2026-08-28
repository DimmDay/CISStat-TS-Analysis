"""API-адаптер порядка наблюдений для остановки EDA «Корреляция»."""
from __future__ import annotations

import pandas as pd

from app.data.detectors import detect_column_frequency, score_all_columns_as_date, smart_to_datetime
from app.eda.correlation import analyze_autocorrelation, autocorrelation_not_applicable


DATE_CONFIDENCE_THRESHOLD = 0.7


def build_eda_correlation(df: pd.DataFrame, column: str, max_lags: int = 40) -> dict:
    """Сортирует один ряд по уверенно найденной оси времени и строит ACF/PACF.

    Агрегация панельных наблюдений намеренно не выполняется: без выбора
    сущности она меняет статистический объект исследования.
    """
    values = df[column]
    candidates = [
        item for item in score_all_columns_as_date(df)
        if item["name"] != column and item["score"] >= DATE_CONFIDENCE_THRESHOLD
    ]
    order_source = "row_order"
    order_column: str | None = None
    order_warning: str | None = (
        "Временная ось уверенно не определена: лаги рассчитаны в текущем порядке строк."
    )
    frequency: str | None = None

    if candidates:
        order_column = str(candidates[0]["name"])
        converted_dates = smart_to_datetime(df[order_column])
        if converted_dates.isna().any():
            result = autocorrelation_not_applicable(
                values,
                max_lags,
                f"В временной колонке «{order_column}» есть нераспознанные даты. "
                "Сначала исправьте временную ось.",
            )
        elif converted_dates.duplicated().any():
            duplicate_count = int(converted_dates.duplicated(keep=False).sum())
            result = autocorrelation_not_applicable(
                values,
                max_lags,
                f"В колонке «{order_column}» повторяются даты ({duplicate_count} строк). "
                "Это похоже на панельные данные: выберите одну сущность до расчёта; "
                "автоматическая агрегация не выполняется.",
            )
        else:
            ordered = pd.DataFrame({"date": converted_dates, "value": values}).sort_values(
                "date", kind="stable"
            )
            values = ordered["value"].reset_index(drop=True)
            frequency_result = detect_column_frequency(converted_dates)
            frequency = frequency_result["code"]
            order_source = "time_column"
            order_warning = None if frequency else (
                "Интервалы времени нерегулярны: лаг означает один соседний шаг наблюдения, "
                "а не фиксированную календарную длительность."
            )
            result = analyze_autocorrelation(values, max_lags=max_lags)
    else:
        result = analyze_autocorrelation(values.reset_index(drop=True), max_lags=max_lags)

    return {
        "column": column,
        **result,
        "order_source": order_source,
        "order_column": order_column,
        "order_warning": order_warning,
        "frequency": frequency,
    }
