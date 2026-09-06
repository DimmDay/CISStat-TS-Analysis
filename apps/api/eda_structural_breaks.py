"""API-адаптер временной оси и графиков EDA «Структурные сдвиги»."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.data.detectors import detect_column_frequency, score_all_columns_as_date, smart_to_datetime
from app.eda.structural_breaks import analyze_structural_breaks, structural_breaks_not_applicable
from apps.api.chart_data import EXPANDED_TARGET_SAMPLED_POINTS, TARGET_SAMPLED_POINTS, _lttb_indices


DATE_CONFIDENCE_THRESHOLD = 0.7


def _display_sampling_target(detail_level: str) -> int:
    """Целевое число точек LTTB-сэмплинга ОТРИСОВКИ (Task 97.3, §6.2).

    Методология PELT/CUSUM/Chow не зависит от detail_level -- уровень
    влияет только на объём точек series/cusum_path, отдаваемых графику.
    """
    return EXPANDED_TARGET_SAMPLED_POINTS if detail_level == "expanded" else TARGET_SAMPLED_POINTS


def _label(labels: pd.Series | None, index: int) -> str | None:
    if labels is None or index < 0 or index >= len(labels):
        return None
    return pd.Timestamp(labels.iloc[index]).isoformat()


def build_eda_structural_breaks(
    df: pd.DataFrame,
    column: str,
    alpha: float = 0.05,
    min_segment: int = 20,
    penalty_multiplier: float = 2.0,
    detail_level: str = "compact",
) -> dict[str, Any]:
    """Валидирует порядок ряда и формирует данные пяти представлений.

    detail_level (Task 97.3, spec_max_graf_fix.md §6.2): "compact" --
    текущее поведение; "expanded" -- тот же расчёт с более высоким
    вторичным потолком точек отображения (см. _display_sampling_target).
    """
    values = df[column]
    candidates = [
        item for item in score_all_columns_as_date(df)
        if item["name"] != column and item["score"] >= DATE_CONFIDENCE_THRESHOLD
    ]
    order_source = "row_order"
    order_column: str | None = None
    order_warning: str | None = (
        "Временная ось уверенно не определена: анализ использует текущий порядок строк, а положение сдвига измеряется наблюдениями."
    )
    frequency: str | None = None
    labels: pd.Series | None = None

    if candidates:
        order_column = str(candidates[0]["name"])
        dates = smart_to_datetime(df[order_column])
        if dates.isna().any():
            result = structural_breaks_not_applicable(
                values,
                f"В временной колонке «{order_column}» есть нераспознанные даты. Сначала исправьте временную ось.",
                alpha, min_segment, penalty_multiplier,
            )
        elif dates.duplicated().any():
            duplicate_count = int(dates.duplicated(keep=False).sum())
            result = structural_breaks_not_applicable(
                values,
                f"В колонке «{order_column}» повторяются даты ({duplicate_count} строк). Это похоже на панельные данные: выберите одну сущность; автоматическая агрегация не выполняется.",
                alpha, min_segment, penalty_multiplier,
            )
        else:
            frequency = detect_column_frequency(dates)["code"]
            if frequency is None:
                result = structural_breaks_not_applicable(
                    values,
                    "Временная сетка нерегулярна. Сначала регуляризуйте ряд: расстояние между кандидатами должно иметь однозначный временной смысл.",
                    alpha, min_segment, penalty_multiplier,
                )
            else:
                ordered = pd.DataFrame({"date": dates, "value": values}).sort_values(
                    "date", kind="stable"
                ).reset_index(drop=True)
                values = pd.to_numeric(ordered["value"], errors="coerce")
                labels = ordered["date"]
                order_source = "time_column"
                order_warning = None
                result = analyze_structural_breaks(values, alpha, min_segment, penalty_multiplier)
    else:
        values = pd.to_numeric(values.reset_index(drop=True), errors="coerce")
        result = analyze_structural_breaks(values, alpha, min_segment, penalty_multiplier)

    enriched_candidates = [
        {**item, "label": _label(labels, int(item["index"]))}
        for item in result["candidates"]
    ]
    enriched_segments = [
        {
            **item,
            "start_label": _label(labels, int(item["start_index"])),
            "end_label": _label(labels, int(item["end_index"])),
        }
        for item in result["segments"]
    ]
    enriched_sensitivity = [
        {**item, "label": _label(labels, int(item["index"]))}
        for item in result["sensitivity"]
    ]

    series: list[dict[str, Any]] = []
    cusum_path: list[dict[str, Any]] = []
    series_sampled = False
    cusum_sampled = False
    if result["applicable"]:
        display_target = _display_sampling_target(detail_level)
        raw = values.to_numpy(dtype=float)
        indices = np.arange(len(raw), dtype=np.int64)
        if len(raw) > display_target:
            indices = _lttb_indices(np.arange(len(raw), dtype=float), raw, display_target)
            series_sampled = True
        segment_ends = [int(item["end_index"]) for item in result["segments"]]
        for index in indices:
            i = int(index)
            segment_id = next(position + 1 for position, end in enumerate(segment_ends) if i <= end)
            series.append({
                "index": i,
                "label": _label(labels, i),
                "value": float(raw[i]),
                "fitted": float(result["fitted"][i]),
                "segment_id": segment_id,
            })

        full_path = result["cusum_path"]
        path_indices = np.arange(len(full_path), dtype=np.int64)
        if len(full_path) > display_target:
            path_values = np.asarray([item["value"] for item in full_path], dtype=float)
            path_indices = _lttb_indices(np.arange(len(full_path), dtype=float), path_values, display_target)
            cusum_sampled = True
        cusum_path = [
            {**full_path[int(index)], "label": _label(labels, int(index))}
            for index in path_indices
        ]

    warnings_out = list(result.get("warnings", []))
    if order_warning:
        warnings_out.insert(0, order_warning)
    return {
        "column": column,
        **{key: value for key, value in result.items() if key not in {"candidates", "segments", "fitted", "cusum_path", "sensitivity", "warnings"}},
        "order_source": order_source,
        "order_column": order_column,
        "order_warning": order_warning,
        "frequency": frequency,
        "candidates": enriched_candidates,
        "segments": enriched_segments,
        "series": series,
        "cusum_path": cusum_path,
        "sensitivity": enriched_sensitivity,
        "series_sampled": series_sampled,
        "series_original_count": int(result["n_observations"]),
        "cusum_sampled": cusum_sampled,
        "warnings": list(dict.fromkeys(warnings_out)),
    }
