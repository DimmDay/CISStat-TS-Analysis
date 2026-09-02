"""API-адаптер остановки «Предобработка → Спектральный анализ»."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.preprocessing.spectral import (
    WAVELET_METHOD,
    analyze_spectral_extensions,
    resolve_welch_segment_length,
)
from apps.api.eda_seasonality import build_eda_seasonality
from app.data.detectors import smart_to_datetime


def _ordered_values_and_labels(
    df: pd.DataFrame, column: str, order_column: str | None,
) -> tuple[np.ndarray, list[str]]:
    if order_column:
        dates = smart_to_datetime(df[order_column])
        order = np.argsort(dates.to_numpy(), kind="stable")
        values = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)[order]
        labels = [pd.Timestamp(value).isoformat() for value in dates.iloc[order]]
        return values, labels
    values = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
    return values, [str(index + 1) for index in range(len(values))]


def _empty_extensions(saved_periods: list[int]) -> dict[str, Any]:
    return {
        "frequency_resolution": None,
        "nyquist_frequency": None,
        "welch_segment_length": None,
        "welch_segments": 0,
        "welch": [],
        "bands": [],
        "wavelet_method": WAVELET_METHOD,
        "wavelet_period_min": None,
        "wavelet_period_max": None,
        "wavelet": [],
        "wavelet_global": [],
        "analysis_only": True,
        "causal": False,
        "modeling_safe": False,
        "saved_periods": saved_periods,
        "warnings": [],
        "methodology_note": (
            "FFT/periodogram требуют равномерной сетки. Пики — диагностические кандидаты; "
            "Welch снижает дисперсию PSD, CWT показывает локализацию во времени."
        ),
    }


def build_preprocessing_spectral_profile(
    df: pd.DataFrame,
    column: str,
    *,
    min_cycles: int = 3,
    max_candidates: int = 6,
    welch_segment_length: int | None = None,
    wavelet_scales: int = 24,
    saved_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Переиспользовать EDA-кандидаты и дополнить их Welch/CWT."""
    base = build_eda_seasonality(
        df, column, min_cycles=min_cycles, max_candidates=max_candidates,
    )
    saved_periods = []
    if saved_selection and saved_selection.get("source_column") == column:
        saved_periods = [int(period) for period in saved_selection.get("selected_periods", [])]
    if not base["applicable"]:
        return {
            **base,
            **_empty_extensions(saved_periods),
            "recommendations": list(base.get("recommendations", [])),
        }

    values, labels = _ordered_values_and_labels(df, column, base.get("order_column"))
    extensions = analyze_spectral_extensions(
        values,
        labels=labels,
        max_period=float(base["max_period"]),
        welch_segment_length=welch_segment_length,
        wavelet_scales=wavelet_scales,
    )
    peak_frequencies = [float(item["frequency"]) for item in base["candidates"]]
    resolution = 1.0 / float(extensions["welch_segment_length"])
    for point in extensions["welch"]:
        point["is_peak"] = any(
            abs(float(point["frequency"]) - peak) <= resolution
            for peak in peak_frequencies
        )

    warnings = list(extensions.pop("warnings"))
    if base.get("order_warning"):
        warnings.append(str(base["order_warning"]))
    if extensions["welch_segments"] < 3:
        warnings.append(
            "Welch использует меньше трёх сегментов: оценка мало отличается от одной периодограммы."
        )
    recommendations = list(base.get("recommendations", []))
    recommendations.append(
        "Фиксируйте целочисленный период только после проверки периодограммы, Welch, CWT и предметной интерпретации."
    )
    recommendations.append(
        "Выбор периода по полной истории — EDA-решение; при честном backtest отбор лагов повторяется только внутри train-fold."
    )
    return {
        **base,
        **extensions,
        "saved_periods": saved_periods,
        "warnings": list(dict.fromkeys(warnings)),
        "recommendations": recommendations,
        "methodology_note": (
            "Глобальная Hann-periodogram ищет пики на равномерной сетке; медианный Welch с 50% overlap проверяет устойчивость PSD, "
            "а CWT cmor1.5-1.0 локализует энергию во времени. ACF и фазовая сила подтверждают кандидат, но не являются формальным тестом значимости. "
            "Lomb–Scargle не включён автоматически: нерегулярность должна быть осознанно обработана на предыдущей остановке."
        ),
    }


def preview_spectral_selection(
    df: pd.DataFrame,
    column: str,
    periods: list[int],
    *,
    min_cycles: int = 3,
    max_candidates: int = 6,
    welch_segment_length: int | None = None,
    confirm_unconfirmed: bool = False,
) -> dict[str, Any]:
    """Проверить и описать решение аналитика без изменения DataFrame."""
    profile = build_eda_seasonality(
        df, column, min_cycles=min_cycles, max_candidates=max_candidates,
    )
    if not profile["applicable"]:
        raise ValueError(str(profile["reason"]))
    selected = sorted(set(int(period) for period in periods))
    max_period = float(profile["max_period"])
    invalid = [period for period in selected if period < 2 or period > max_period]
    if invalid:
        raise ValueError(
            f"Периоды {invalid} вне допустимого диапазона 2…{max_period:.2f} при min_cycles={min_cycles}"
        )
    confirmed_values = {
        int(item["period_rounded"])
        for item in profile["candidates"]
        if item["confirmed"]
    }
    confirmed = [period for period in selected if period in confirmed_values]
    unconfirmed = [period for period in selected if period not in confirmed_values]
    if unconfirmed and not confirm_unconfirmed:
        raise ValueError(
            f"Периоды {unconfirmed} не подтверждены одновременно спектром, ACF и фазовым профилем; требуется отдельное подтверждение"
        )
    segment = resolve_welch_segment_length(int(profile["n_observations"]), welch_segment_length)
    metadata = {
        "kind": "spectral_selection",
        "source_column": column,
        "selected_periods": selected,
        "frequencies": [float(1.0 / period) for period in selected],
        "confirmed_periods": confirmed,
        "unconfirmed_periods": unconfirmed,
        "min_cycles": int(min_cycles),
        "max_candidates": int(max_candidates),
        "welch_segment_length": segment,
        "detrend": "linear",
        "window": "hann",
        "wavelet": WAVELET_METHOD,
        "analysis_only": True,
        "causal": False,
        "modeling_safe": False,
        "analyzed_on_n": int(profile["n_observations"]),
        "order_source": profile["order_source"],
        "order_column": profile["order_column"],
        "frequency": profile["frequency"],
    }
    return {
        "column": column,
        "selected_periods": selected,
        "confirmed_periods": confirmed,
        "unconfirmed_periods": unconfirmed,
        "suggested_lags": selected,
        "metadata": metadata,
    }
