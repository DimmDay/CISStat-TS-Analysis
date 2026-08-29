"""API-адаптер временной оси для EDA «Сезонность и периодичность»."""
from __future__ import annotations

import pandas as pd

from app.data.detectors import detect_column_frequency, score_all_columns_as_date, smart_to_datetime
from app.features.spectral import analyze_spectral_seasonality, spectral_not_applicable


DATE_CONFIDENCE_THRESHOLD = 0.7


def build_eda_seasonality(
    df: pd.DataFrame,
    column: str,
    min_cycles: int = 3,
    max_candidates: int = 5,
) -> dict:
    """Проверяет временную сетку и строит спектральный профиль ряда.

    FFT и классическая периодограмма предполагают равные интервалы. Поэтому
    нерегулярные даты, нераспознанные значения и панельные дубли блокируют
    расчёт вместо неявного сжатия/агрегации. При отсутствии уверенно найденной
    даты текущий порядок строк допускается как равномерная индексная шкала и
    явно маркируется предупреждением.
    """
    values = df[column]
    candidates = [
        item for item in score_all_columns_as_date(df)
        if item["name"] != column and item["score"] >= DATE_CONFIDENCE_THRESHOLD
    ]
    order_source = "row_order"
    order_column: str | None = None
    order_warning: str | None = (
        "Временная ось уверенно не определена: точки считаются равномерными в текущем порядке строк, период измеряется в наблюдениях."
    )
    frequency: str | None = None

    if candidates:
        order_column = str(candidates[0]["name"])
        order_source = "time_column"
        order_warning = None
        converted_dates = smart_to_datetime(df[order_column])
        if converted_dates.isna().any():
            result = spectral_not_applicable(
                values,
                min_cycles,
                max_candidates,
                f"В временной колонке «{order_column}» есть нераспознанные даты. Сначала исправьте временную ось.",
            )
        elif converted_dates.duplicated().any():
            duplicate_count = int(converted_dates.duplicated(keep=False).sum())
            result = spectral_not_applicable(
                values,
                min_cycles,
                max_candidates,
                f"В колонке «{order_column}» повторяются даты ({duplicate_count} строк). Это похоже на панельные данные: выберите одну сущность; автоматическая агрегация не выполняется.",
            )
        else:
            frequency = detect_column_frequency(converted_dates)["code"]
            if frequency is None:
                result = spectral_not_applicable(
                    values,
                    min_cycles,
                    max_candidates,
                    "Временная сетка нерегулярна. FFT и классическая периодограмма требуют равных интервалов; сначала регуляризуйте ряд или примените специализированный Lomb–Scargle анализ.",
                )
            else:
                ordered = pd.DataFrame({"date": converted_dates, "value": values}).sort_values(
                    "date", kind="stable"
                )
                result = analyze_spectral_seasonality(
                    ordered["value"].reset_index(drop=True),
                    min_cycles=min_cycles,
                    max_candidates=max_candidates,
                    frequency=frequency,
                )
                order_warning = None
    else:
        result = analyze_spectral_seasonality(
            values.reset_index(drop=True),
            min_cycles=min_cycles,
            max_candidates=max_candidates,
        )

    return {
        "column": column,
        **result,
        "order_source": order_source,
        "order_column": order_column,
        "order_warning": order_warning,
        "frequency": frequency,
    }
