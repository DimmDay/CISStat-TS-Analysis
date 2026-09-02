"""Расширенная спектральная диагностика для остановки «Предобработка».

Глобальные FFT/periodogram-кандидаты остаются в ``app.features.spectral``.
Этот модуль добавляет два независимых представления: медианный Welch PSD
и CWT-скалограмму. Они предназначены для диагностики, а не для скрытого
преобразования ряда или автоматической генерации признаков.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import pywt
from scipy.signal import detrend as scipy_detrend
from scipy.signal import periodogram, welch


MIN_WELCH_SEGMENT = 8
MAX_WAVELET_PERIOD = 512.0
MAX_WAVELET_TIME_POINTS = 120
WAVELET_METHOD = "cmor1.5-1.0"


def _validated_values(values: Sequence[float] | np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1:
        raise ValueError("Спектральный анализ требует одномерный ряд")
    if len(array) < 24:
        raise ValueError("Для спектрального анализа нужно минимум 24 наблюдения")
    if not np.isfinite(array).all():
        raise ValueError("Спектральный анализ требует только конечные значения")
    if float(np.ptp(array)) <= np.finfo(float).eps:
        raise ValueError("Спектральный анализ не определён для константного ряда")
    return array


def resolve_welch_segment_length(n_observations: int, requested: int | None) -> int:
    """Вернуть размер сегмента с минимум тремя окнами при auto."""
    if requested is not None:
        if requested < MIN_WELCH_SEGMENT:
            raise ValueError(f"Сегмент Welch должен содержать минимум {MIN_WELCH_SEGMENT} наблюдений")
        if requested > n_observations:
            raise ValueError("Сегмент Welch не может быть длиннее ряда")
        return int(requested)
    half = max(MIN_WELCH_SEGMENT, n_observations // 2)
    power = int(np.floor(np.log2(half)))
    return max(MIN_WELCH_SEGMENT, min(n_observations, 2 ** power))


def _spectrum_points(frequencies: np.ndarray, power: np.ndarray) -> list[dict[str, Any]]:
    positive = frequencies > 0
    total = max(float(power[positive].sum()), np.finfo(float).tiny)
    return [
        {
            "frequency": float(frequency),
            "period": float(1.0 / frequency),
            "amplitude": None,
            "power": float(value),
            "power_share": float(value / total),
            "is_peak": False,
        }
        for frequency, value in zip(frequencies[positive], power[positive])
    ]


def _power_bands(values: np.ndarray) -> list[dict[str, Any]]:
    frequencies, power = periodogram(
        values, fs=1.0, window="hann", detrend=False, scaling="spectrum",
    )
    positive = frequencies > 0
    total = max(float(power[positive].sum()), np.finfo(float).tiny)
    definitions = (
        ("low", "Низкие", 0.0, 0.1, positive & (frequencies < 0.1)),
        ("mid", "Средние", 0.1, 0.25, (frequencies >= 0.1) & (frequencies < 0.25)),
        ("high", "Высокие", 0.25, 0.5, frequencies >= 0.25),
    )
    return [
        {
            "id": band_id,
            "label": label,
            "frequency_min": lower,
            "frequency_max": upper,
            "power_share": float(power[mask].sum() / total),
        }
        for band_id, label, lower, upper, mask in definitions
    ]


def _wavelet_payload(
    values: np.ndarray,
    labels: list[str],
    max_period: float,
    wavelet_scales: int,
) -> tuple[list[dict[str, Any]], list[dict[str, float]], float, list[str]]:
    period_limit = max(2.0, min(float(max_period), MAX_WAVELET_PERIOD))
    periods_requested = np.geomspace(2.0, period_limit, num=max(8, int(wavelet_scales)))
    normalized_frequencies = 1.0 / periods_requested
    scales = pywt.frequency2scale(WAVELET_METHOD, normalized_frequencies)
    coefficients, frequencies = pywt.cwt(
        values,
        scales,
        WAVELET_METHOD,
        sampling_period=1.0,
        method="fft",
    )
    periods = 1.0 / np.asarray(frequencies, dtype=float)
    power = np.abs(coefficients) ** 2
    positive_power = power[power > 0]
    baseline = float(np.median(positive_power)) if len(positive_power) else 1.0
    logged = np.log1p(power / max(baseline, np.finfo(float).tiny))
    cap = float(np.quantile(logged, 0.99)) if logged.size else 1.0
    normalized = np.clip(logged / max(cap, np.finfo(float).tiny), 0.0, 1.0)

    time_indices = np.arange(len(values), dtype=int)
    if len(time_indices) > MAX_WAVELET_TIME_POINTS:
        time_indices = np.linspace(
            0, len(values) - 1, MAX_WAVELET_TIME_POINTS, dtype=int,
        )
    points: list[dict[str, Any]] = []
    for scale_index, period in enumerate(periods):
        for time_index in time_indices:
            points.append({
                "x": labels[int(time_index)],
                "index": int(time_index),
                "period": float(period),
                "power": float(power[scale_index, time_index]),
                "normalized_power": float(normalized[scale_index, time_index]),
                # Простая консервативная метка края: коэффициент ближе одного
                # анализируемого периода к границе не интерпретируется как факт.
                "edge_affected": bool(
                    time_index < period or (len(values) - 1 - time_index) < period
                ),
            })
    mean_power = power.mean(axis=1)
    total_global = max(float(mean_power.sum()), np.finfo(float).tiny)
    global_power = [
        {"period": float(period), "power_share": float(value / total_global)}
        for period, value in zip(periods, mean_power)
    ]
    warnings = []
    if float(max_period) > MAX_WAVELET_PERIOD:
        warnings.append(
            f"CWT-визуализация ограничена периодом {int(MAX_WAVELET_PERIOD)} для контроля памяти; глобальная периодограмма анализирует полный диапазон."
        )
    return points, global_power, period_limit, warnings


def analyze_spectral_extensions(
    values: Sequence[float] | np.ndarray,
    *,
    labels: Sequence[str] | None = None,
    max_period: float,
    welch_segment_length: int | None = None,
    wavelet_scales: int = 24,
) -> dict[str, Any]:
    """Построить Welch PSD, диапазоны энергии и CWT для валидного ряда."""
    array = _validated_values(values)
    label_values = list(labels) if labels is not None else [str(index + 1) for index in range(len(array))]
    if len(label_values) != len(array):
        raise ValueError("Число временных меток должно совпадать с длиной ряда")
    if not 8 <= int(wavelet_scales) <= 64:
        raise ValueError("Число CWT-масштабов должно быть от 8 до 64")
    detrended = scipy_detrend(array, type="linear")
    segment = resolve_welch_segment_length(len(array), welch_segment_length)
    overlap = segment // 2
    frequencies, power = welch(
        detrended,
        fs=1.0,
        window="hann",
        nperseg=segment,
        noverlap=overlap,
        detrend="constant",
        scaling="spectrum",
        average="median",
    )
    step = segment - overlap
    segments = 1 + max(0, (len(array) - segment) // step)
    wavelet, wavelet_global, wavelet_period_max, warnings = _wavelet_payload(
        detrended, label_values, max_period, wavelet_scales,
    )
    return {
        "frequency_resolution": float(1.0 / len(array)),
        "nyquist_frequency": 0.5,
        "welch_segment_length": segment,
        "welch_segments": int(segments),
        "welch": _spectrum_points(frequencies, power),
        "bands": _power_bands(detrended),
        "wavelet_method": WAVELET_METHOD,
        "wavelet_period_min": 2.0,
        "wavelet_period_max": float(wavelet_period_max),
        "wavelet": wavelet,
        "wavelet_global": wavelet_global,
        "analysis_only": True,
        "causal": False,
        "modeling_safe": False,
        "warnings": warnings,
    }
