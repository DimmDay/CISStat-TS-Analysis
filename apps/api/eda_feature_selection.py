"""API-адаптер временной оси для EDA «Отбор признаков»."""
from __future__ import annotations
from typing import Any
import pandas as pd
from app.data.detectors import detect_column_frequency, score_all_columns_as_date, smart_to_datetime
from app.eda.feature_selection import analyze_feature_selection

DATE_CONFIDENCE_THRESHOLD = 0.7

def build_eda_feature_selection(df: pd.DataFrame, column: str, alpha: float = 0.05,
                                max_lag: int = 3, correlation_threshold: float = 0.3,
                                vif_threshold: float = 5.0, difference_order: int = 0) -> dict[str, Any]:
    candidates = [item for item in score_all_columns_as_date(df) if item["name"] != column and item["score"] >= DATE_CONFIDENCE_THRESHOLD]
    order_source, order_column, frequency = "row_order", None, None
    order_warning = "Временная ось не определена: лаг измеряется соседними строками."
    ordered, enabled, reason, excluded = df.reset_index(drop=True).copy(), True, None, []
    if candidates:
        order_column = str(candidates[0]["name"]); excluded.append(order_column)
        dates = smart_to_datetime(df[order_column])
        if dates.isna().any():
            enabled = False; reason = f"В колонке «{order_column}» есть нераспознанные даты; Granger отключён."
        elif dates.duplicated().any():
            enabled = False; reason = f"В колонке «{order_column}» повторяются даты: панельные данные; Granger отключён."
        else:
            order_source = "time_column"
            ordered = df.assign(__eda_date=dates).sort_values("__eda_date", kind="stable").drop(columns="__eda_date").reset_index(drop=True)
            frequency = detect_column_frequency(dates)["code"]
            if frequency is None:
                enabled = False; reason = "Временная сетка нерегулярна; Granger отключён."
            else:
                order_warning = None
        if reason: order_warning = reason
    result = analyze_feature_selection(ordered, column, alpha, max_lag, correlation_threshold, vif_threshold,
                                       difference_order, excluded_columns=excluded, granger_enabled=enabled,
                                       granger_disabled_reason=reason)
    warnings_out = list(result.get("warnings", []))
    if order_warning: warnings_out.insert(0, order_warning)
    return {**result, "order_source": order_source, "order_column": order_column,
            "order_warning": order_warning, "frequency": frequency, "warnings": list(dict.fromkeys(warnings_out))}
