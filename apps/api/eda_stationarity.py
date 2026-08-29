"""API-адаптер временной оси и графиков EDA «Верификация стационарности»."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.data.detectors import detect_column_frequency, score_all_columns_as_date, smart_to_datetime
from app.eda.stationarity import analyze_stationarity, stationarity_not_applicable
from apps.api.chart_data import TARGET_SAMPLED_POINTS, _lttb_indices


DATE_CONFIDENCE_THRESHOLD = 0.7


def _test_item(
    test_id: str,
    label: str,
    raw: dict[str, Any],
    null_hypothesis: str,
    alternative_hypothesis: str,
    unit_root_null: bool,
) -> dict[str, Any]:
    pvalue = raw.get("pvalue")
    available = bool(raw.get("available", pvalue is not None))
    reject_null = bool(pvalue < raw["alpha"]) if available and pvalue is not None else None
    supports_stationarity = (
        reject_null if unit_root_null else not reject_null
    ) if reject_null is not None else None
    return {
        "id": test_id,
        "label": label,
        "null_hypothesis": null_hypothesis,
        "alternative_hypothesis": alternative_hypothesis,
        "available": available,
        "statistic": raw.get("stat"),
        "p_value": pvalue,
        "lags": raw.get("lags"),
        "reject_null": reject_null,
        "supports_stationarity": supports_stationarity,
        "critical_values": raw.get("critical_values", {}),
        "note": raw.get("note"),
    }


def _build_test_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    alpha = float(result["alpha"])
    adf_level = {**result["adf"], "alpha": alpha}
    adf_trend = {**result["adf_trend"], "alpha": alpha}
    kpss = result["kpss"]
    kpss_level = {
        "available": kpss.get("available", False),
        "stat": kpss.get("stat_level"),
        "pvalue": kpss.get("pvalue_level"),
        "lags": kpss.get("lags_level"),
        "critical_values": kpss.get("critical_values_level", {}),
        "note": kpss.get("note_level"),
        "alpha": alpha,
    }
    kpss_trend = {
        "available": kpss.get("available", False),
        "stat": kpss.get("stat_trend"),
        "pvalue": kpss.get("pvalue_trend"),
        "lags": kpss.get("lags_trend"),
        "critical_values": kpss.get("critical_values_trend", {}),
        "note": kpss.get("note_trend"),
        "alpha": alpha,
    }
    pp = {**result["pp"], "alpha": alpha}
    za = {**result["za"], "alpha": alpha}
    return [
        _test_item("adf_level", "ADF (уровень)", adf_level, "Единичный корень", "Стационарность вокруг уровня", True),
        _test_item("adf_trend", "ADF (тренд)", adf_trend, "Единичный корень", "Стационарность вокруг тренда", True),
        _test_item("kpss_level", "KPSS (уровень)", kpss_level, "Стационарность вокруг уровня", "Единичный корень", False),
        _test_item("kpss_trend", "KPSS (тренд)", kpss_trend, "Стационарность вокруг тренда", "Единичный корень", False),
        _test_item("pp", "Phillips–Perron", pp, "Единичный корень", "Стационарность вокруг уровня", True),
        _test_item("zivot_andrews", "Zivot–Andrews", za, "Единичный корень с одним разрывом", "Стационарность с одним разрывом", True),
    ]


def _rolling_points(
    values: pd.Series,
    labels: pd.Series | None,
    requested_window: int,
) -> tuple[list[dict[str, Any]], int, bool]:
    n = len(values)
    window = min(requested_window, max(3, n // 2))
    mean = values.rolling(window=window, min_periods=window).mean()
    std = values.rolling(window=window, min_periods=window).std(ddof=1)
    indices = np.arange(n, dtype=np.int64)
    sampled = n > TARGET_SAMPLED_POINTS
    if sampled:
        indices = _lttb_indices(
            np.arange(n, dtype=float),
            values.to_numpy(dtype=float),
            TARGET_SAMPLED_POINTS,
        )

    points: list[dict[str, Any]] = []
    for index in indices:
        label = None
        if labels is not None:
            label = pd.Timestamp(labels.iloc[int(index)]).isoformat()
        rolling_mean = mean.iloc[int(index)]
        rolling_std = std.iloc[int(index)]
        points.append({
            "index": int(index),
            "label": label,
            "value": float(values.iloc[int(index)]),
            "rolling_mean": float(rolling_mean) if pd.notna(rolling_mean) else None,
            "rolling_std": float(rolling_std) if pd.notna(rolling_std) else None,
        })
    return points, window, sampled


def build_eda_stationarity(
    df: pd.DataFrame,
    column: str,
    alpha: float = 0.05,
    rolling_window: int = 12,
) -> dict[str, Any]:
    """Сортирует ряд, валидирует регулярность и строит полный EDA-профиль."""
    values = df[column]
    candidates = [
        item for item in score_all_columns_as_date(df)
        if item["name"] != column and item["score"] >= DATE_CONFIDENCE_THRESHOLD
    ]
    order_source = "row_order"
    order_column: str | None = None
    order_warning: str | None = (
        "Временная ось уверенно не определена: тесты используют текущий порядок строк, а окно измеряется в наблюдениях."
    )
    frequency: str | None = None
    labels: pd.Series | None = None

    if candidates:
        order_column = str(candidates[0]["name"])
        converted_dates = smart_to_datetime(df[order_column])
        if converted_dates.isna().any():
            result = stationarity_not_applicable(
                values,
                f"В временной колонке «{order_column}» есть нераспознанные даты. Сначала исправьте временную ось.",
                alpha,
            )
        elif converted_dates.duplicated().any():
            duplicate_count = int(converted_dates.duplicated(keep=False).sum())
            result = stationarity_not_applicable(
                values,
                f"В колонке «{order_column}» повторяются даты ({duplicate_count} строк). Это похоже на панельные данные: выберите одну сущность; автоматическая агрегация не выполняется.",
                alpha,
            )
        else:
            frequency = detect_column_frequency(converted_dates)["code"]
            if frequency is None:
                result = stationarity_not_applicable(
                    values,
                    "Временная сетка нерегулярна. Unit-root тесты с лагами предполагают равноотстоящие наблюдения; сначала регуляризуйте ряд.",
                    alpha,
                )
            else:
                ordered = pd.DataFrame({"date": converted_dates, "value": values}).sort_values(
                    "date", kind="stable"
                ).reset_index(drop=True)
                values = pd.to_numeric(ordered["value"], errors="coerce")
                labels = ordered["date"]
                order_source = "time_column"
                order_warning = None
                result = analyze_stationarity(values, alpha=alpha)
    else:
        values = pd.to_numeric(values.reset_index(drop=True), errors="coerce")
        result = analyze_stationarity(values, alpha=alpha)

    tests = _build_test_items(result) if result["applicable"] else []
    rolling: list[dict[str, Any]] = []
    effective_window = rolling_window
    rolling_sampled = False
    if result["applicable"]:
        rolling, effective_window, rolling_sampled = _rolling_points(
            values.astype(float).reset_index(drop=True),
            labels,
            rolling_window,
        )

    breakpoint_index = result["za"].get("breakpoint") if result["applicable"] else None
    breakpoint_label = None
    if breakpoint_index is not None and labels is not None and 0 <= breakpoint_index < len(labels):
        breakpoint_label = pd.Timestamp(labels.iloc[breakpoint_index]).isoformat()

    warnings_out = list(result.get("warnings", []))
    if order_warning:
        warnings_out.insert(0, order_warning)

    return {
        "column": column,
        "applicable": result["applicable"],
        "reason": result["reason"],
        "n_observations": result["n_observations"],
        "missing_count": result["missing_count"],
        "min_observations": result["min_observations"],
        "alpha": result["alpha"],
        "requested_rolling_window": rolling_window,
        "rolling_window": effective_window,
        "consensus": result["consensus"],
        "recommendation": result["recommendation"],
        "order_source": order_source,
        "order_column": order_column,
        "order_warning": order_warning,
        "frequency": frequency,
        "breakpoint_index": breakpoint_index,
        "breakpoint_label": breakpoint_label,
        "tests": tests,
        "rolling": rolling,
        "rolling_sampled": rolling_sampled,
        "rolling_original_count": int(result["n_observations"]),
        "recommendations": result.get("recommendations", []),
        "warnings": list(dict.fromkeys(warnings_out)),
    }
