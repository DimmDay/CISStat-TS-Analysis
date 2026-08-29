# app/features/spectral.py
"""
Модуль спектрального анализа временных рядов.
Поддерживает FFT, Periodogram, Wavelet, спектральную энтропию.
"""
import numpy as np
import pandas as pd
from typing import Any, Dict, List, Tuple
from scipy.fft import fft, fftfreq, rfft, rfftfreq
from scipy.signal import detrend as scipy_detrend
from scipy.signal import find_peaks, get_window, peak_prominences, periodogram, welch


MIN_SPECTRAL_OBSERVATIONS = 24
MAX_SPECTRUM_POINTS = 420


def _spectral_not_applicable(series: pd.Series, min_cycles: int, max_candidates: int, reason: str) -> dict:
    numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    finite_count = int(np.isfinite(numeric).sum())
    return {
        "applicable": False,
        "reason": reason,
        "n_observations": int(len(numeric)),
        "missing_count": int(len(numeric) - finite_count),
        "min_cycles": int(min_cycles),
        "max_candidates": int(max_candidates),
        "max_period": None,
        "detrend": "linear",
        "window": "hann",
        "spectral_entropy": None,
        "dominant_period": None,
        "dominant_strength": None,
        "confirmed_periods": 0,
        "fft": [],
        "periodogram": [],
        "candidates": [],
        "phase_period": None,
        "phase_profile": [],
        "recommendations": [],
    }


def spectral_not_applicable(
    series: pd.Series, min_cycles: int, max_candidates: int, reason: str
) -> dict:
    """Публичный конструктор честного отказа для API-проверок временной сетки."""
    return _spectral_not_applicable(series, min_cycles, max_candidates, reason)


def _calendar_hint(period: float, frequency: str | None) -> str | None:
    if not frequency:
        return None
    base = "".join(char for char in frequency if not char.isdigit()).split("-")[0]
    expected: dict[str, list[tuple[float, str]]] = {
        "D": [(7, "недельный цикл"), (365.25, "годовой цикл")],
        "B": [(5, "рабочая неделя"), (252, "рабочий год")],
        "W": [(52.18, "годовой цикл")],
        "M": [(12, "годовой цикл")],
        "ME": [(12, "годовой цикл")],
        "MS": [(12, "годовой цикл")],
        "Q": [(4, "годовой цикл")],
        "QE": [(4, "годовой цикл")],
        "QS": [(4, "годовой цикл")],
        "H": [(24, "суточный цикл"), (168, "недельный цикл")],
        "h": [(24, "суточный цикл"), (168, "недельный цикл")],
        "T": [(60, "часовой цикл"), (1440, "суточный цикл")],
        "min": [(60, "часовой цикл"), (1440, "суточный цикл")],
    }
    for expected_period, label in expected.get(base, []):
        if abs(period - expected_period) / expected_period <= 0.08:
            return label
    return None


def _phase_profile(values: np.ndarray, period: int) -> tuple[list[dict], float]:
    phases = np.arange(len(values)) % period
    seasonal_means = np.array([values[phases == phase].mean() for phase in range(period)])
    residual = values - seasonal_means[phases]
    total_variance = float(np.var(values))
    strength = max(0.0, min(1.0, 1.0 - float(np.var(residual)) / total_variance)) if total_variance > 0 else 0.0
    profile: list[dict] = []
    for phase in range(period):
        phase_values = values[phases == phase]
        mean = float(phase_values.mean())
        if len(phase_values) > 1:
            standard_error = float(phase_values.std(ddof=1) / np.sqrt(len(phase_values)))
            margin = 1.96 * standard_error
        else:
            margin = 0.0
        profile.append({
            "phase": phase + 1,
            "mean": mean,
            "lower": mean - margin,
            "upper": mean + margin,
            "count": int(len(phase_values)),
        })
    return profile, strength


def _remove_phase_profile(values: np.ndarray, period: int) -> np.ndarray:
    phases = np.arange(len(values)) % period
    seasonal_means = np.array([values[phases == phase].mean() for phase in range(period)])
    return values - seasonal_means[phases]


def _sample_spectrum(points: list[dict], peak_frequencies: set[float]) -> list[dict]:
    if len(points) <= MAX_SPECTRUM_POINTS:
        return points
    regular_indices = set(np.linspace(0, len(points) - 1, MAX_SPECTRUM_POINTS, dtype=int).tolist())
    peak_indices = {
        index for index, point in enumerate(points)
        if any(np.isclose(point["frequency"], peak) for peak in peak_frequencies)
    }
    return [points[index] for index in sorted(regular_indices | peak_indices)]


def analyze_spectral_seasonality(
    series: pd.Series,
    min_cycles: int = 3,
    max_candidates: int = 5,
    frequency: str | None = None,
) -> dict:
    """Ищет периодические компоненты в равномерно дискретизированном ряде.

    Функция намеренно не знает временную ось: её равномерность, сортировку и
    панельные дубли проверяет API-адаптер. Здесь пропуски также не удаляются,
    потому что сжатие ряда меняет частоты. Линейный detrend и окно Hann
    уменьшают утечку энергии тренда; кандидаты из периодограммы подтверждаются
    ACF и долей дисперсии фазового профиля, а не объявляются формальным тестом.
    """
    min_cycles = max(2, int(min_cycles))
    max_candidates = max(1, int(max_candidates))
    numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    invalid_count = int((~np.isfinite(numeric)).sum())
    if invalid_count:
        return _spectral_not_applicable(
            series,
            min_cycles,
            max_candidates,
            f"В ряду {invalid_count} пропусков или бесконечных значений. Сначала обработайте их: удаление здесь исказило бы частоты.",
        )
    if len(numeric) < MIN_SPECTRAL_OBSERVATIONS:
        return _spectral_not_applicable(
            series,
            min_cycles,
            max_candidates,
            f"Недостаточно наблюдений: {len(numeric)}, требуется минимум {MIN_SPECTRAL_OBSERVATIONS}.",
        )
    if float(np.ptp(numeric)) <= np.finfo(float).eps:
        return _spectral_not_applicable(
            series,
            min_cycles,
            max_candidates,
            "Ряд константный (нулевая дисперсия): спектральный анализ не определён.",
        )

    n_observations = len(numeric)
    max_period = float(n_observations / min_cycles)
    detrended = scipy_detrend(numeric, type="linear")
    detrended_variance = float(np.var(detrended))
    raw_variance = float(np.var(numeric))

    base = {
        "applicable": True,
        "reason": None,
        "n_observations": n_observations,
        "missing_count": 0,
        "min_cycles": min_cycles,
        "max_candidates": max_candidates,
        "max_period": max_period,
        "detrend": "linear",
        "window": "hann",
    }
    # Чистый линейный тренд после detrend содержит только машинный шум.
    if detrended_variance <= max(np.finfo(float).eps, raw_variance * 1e-12):
        return {
            **base,
            "spectral_entropy": 0.0,
            "dominant_period": None,
            "dominant_strength": None,
            "confirmed_periods": 0,
            "fft": [],
            "periodogram": [],
            "candidates": [],
            "phase_period": None,
            "phase_profile": [],
            "recommendations": ["После удаления линейного тренда периодическая компонента не обнаружена."],
        }

    hann = get_window("hann", n_observations, fftbins=True)
    fft_frequencies = rfftfreq(n_observations, d=1.0)
    fft_amplitudes = 2.0 * np.abs(rfft(detrended * hann)) / float(hann.sum())
    pg_frequencies, pg_power = periodogram(
        detrended,
        fs=1.0,
        window="hann",
        detrend=False,
        scaling="spectrum",
    )

    positive = pg_frequencies > 0
    entropy_power = pg_power[positive]
    entropy_total = float(entropy_power.sum())
    if entropy_total > 0 and len(entropy_power) > 1:
        probabilities = entropy_power / entropy_total
        spectral_entropy = float(-np.sum(probabilities * np.log(probabilities + np.finfo(float).tiny)) / np.log(len(probabilities)))
    else:
        spectral_entropy = 0.0

    periods = np.full_like(pg_frequencies, np.inf, dtype=float)
    np.divide(1.0, pg_frequencies, out=periods, where=positive)
    candidate_mask = positive & (pg_frequencies <= 0.5) & (periods >= 2.0) & (periods <= max_period)
    candidate_indices = np.flatnonzero(candidate_mask)
    candidates: list[dict] = []
    if len(candidate_indices):
        band_power = pg_power[candidate_indices]
        local_peaks, _ = find_peaks(band_power)
        if len(local_peaks):
            prominences = peak_prominences(band_power, local_peaks)[0]
            peak_rows = list(zip(local_peaks.tolist(), prominences.tolist()))
        else:
            peak_rows = []
        global_peak = int(np.argmax(band_power))
        if global_peak not in {row[0] for row in peak_rows}:
            peak_rows.append((global_peak, float(band_power[global_peak])))

        raw_candidates: list[dict] = []
        band_total = max(float(band_power.sum()), np.finfo(float).tiny)
        for local_index, prominence in peak_rows:
            absolute_index = int(candidate_indices[local_index])
            frequency_value = float(pg_frequencies[absolute_index])
            period_value = float(1.0 / frequency_value)
            period_rounded = max(2, int(round(period_value)))
            half_width = 4
            left = max(0, local_index - half_width)
            right = min(len(band_power), local_index + half_width + 1)
            neighbours = np.delete(band_power[left:right], min(local_index - left, right - left - 1))
            noise_floor = float(np.median(neighbours)) if len(neighbours) else 0.0
            power_value = float(pg_power[absolute_index])
            spectral_snr = power_value / max(noise_floor, np.finfo(float).eps)
            prominence_ratio = float(prominence / max(power_value, np.finfo(float).eps))
            raw_candidates.append({
                "rank": 0,
                "period": period_value,
                "period_rounded": period_rounded,
                "frequency": frequency_value,
                "amplitude": float(fft_amplitudes[absolute_index]),
                "power": power_value,
                "power_share": float(100.0 * power_value / band_total),
                "prominence": float(prominence),
                "spectral_snr": float(spectral_snr),
                "autocorrelation": 0.0,
                "seasonal_strength": 0.0,
                "cycles": float(n_observations / period_value),
                "confirmed": False,
                "calendar_hint": _calendar_hint(period_value, frequency),
                "harmonic_of": None,
            })

        # Проверяем пики по убыванию мощности. После подтверждения компонента
        # удаляем её средний фазовый профиль, чтобы сильный период не маскировал
        # ACF следующей сезонности (типичный случай множественных периодов).
        raw_candidates.sort(key=lambda item: (-item["power"], item["period"]))
        validation_signal = detrended.copy()
        acf_threshold = 1.96 / np.sqrt(n_observations)
        for item in raw_candidates:
            period_rounded = int(item["period_rounded"])
            autocorrelation = float(np.corrcoef(
                validation_signal[:-period_rounded], validation_signal[period_rounded:]
            )[0, 1])
            if not np.isfinite(autocorrelation):
                autocorrelation = 0.0
            _, seasonal_strength = _phase_profile(validation_signal, period_rounded)
            prominence_ratio = float(item["prominence"] / max(item["power"], np.finfo(float).eps))
            confirmed = bool(
                item["spectral_snr"] >= 4.0
                and prominence_ratio >= 0.2
                and autocorrelation > acf_threshold
                and seasonal_strength >= 0.1
            )
            item["autocorrelation"] = autocorrelation
            item["seasonal_strength"] = float(seasonal_strength)
            item["confirmed"] = confirmed
            if confirmed:
                validation_signal = _remove_phase_profile(validation_signal, period_rounded)

        raw_candidates.sort(
            key=lambda item: (
                not item["confirmed"],
                -item["power"],
                item["period"],
            )
        )
        for item in raw_candidates:
            if any(abs(item["period"] - kept["period"]) / kept["period"] < 0.05 for kept in candidates):
                continue
            candidates.append(item)
            if len(candidates) >= max_candidates:
                break
        for rank, item in enumerate(candidates, start=1):
            item["rank"] = rank
        # Более короткий пик может быть гармоникой уже найденного длинного периода.
        for item in candidates:
            longer = [
                other for other in candidates
                if other["confirmed"] and other["period"] > item["period"] * 1.5
            ]
            for other in sorted(longer, key=lambda value: value["period"]):
                ratio = other["period"] / item["period"]
                harmonic = round(ratio)
                if 2 <= harmonic <= 6 and abs(ratio - harmonic) <= 0.08 * harmonic:
                    item["harmonic_of"] = other["period"]
                    break

    peak_frequencies = {float(item["frequency"]) for item in candidates}
    fft_points = [
        {
            "frequency": float(freq),
            "period": float(1.0 / freq),
            "amplitude": float(amplitude),
            "is_peak": any(np.isclose(freq, peak) for peak in peak_frequencies),
        }
        for freq, amplitude in zip(fft_frequencies[1:], fft_amplitudes[1:])
    ]
    periodogram_points = [
        {
            "frequency": float(freq),
            "period": float(1.0 / freq),
            "power": float(power),
            "is_peak": any(np.isclose(freq, peak) for peak in peak_frequencies),
        }
        for freq, power in zip(pg_frequencies[1:], pg_power[1:])
    ]

    dominant = candidates[0] if candidates else None
    phase_period = int(dominant["period_rounded"]) if dominant else None
    phase_profile, dominant_strength = _phase_profile(detrended, phase_period) if phase_period else ([], None)
    confirmed_count = sum(1 for item in candidates if item["confirmed"])
    recommendations = []
    if confirmed_count:
        recommendations.append(
            f"Подтверждено периодов-кандидатов: {confirmed_count}; доминирующий период ≈ {dominant['period']:.2f} наблюдения."
        )
    else:
        recommendations.append("Устойчивый период не подтверждён одновременно спектром, ACF и фазовым профилем.")
    recommendations.append(
        "Спектральные пики — диагностические кандидаты: проверьте их устойчивость на временных срезах и после структурных сдвигов."
    )

    return {
        **base,
        "spectral_entropy": max(0.0, min(1.0, spectral_entropy)),
        "dominant_period": float(dominant["period"]) if dominant else None,
        "dominant_strength": float(dominant_strength) if dominant_strength is not None else None,
        "confirmed_periods": confirmed_count,
        "fft": _sample_spectrum(fft_points, peak_frequencies),
        "periodogram": _sample_spectrum(periodogram_points, peak_frequencies),
        "candidates": candidates,
        "phase_period": phase_period,
        "phase_profile": phase_profile,
        "recommendations": recommendations,
    }


def compute_fft_features(
    series: pd.Series,
    min_height_sigma: float = 1.0
) -> Dict[str, any]:
    """
    Вычисляет FFT и находит доминирующие периоды.
    
    Args:
        series: исходный ряд
        min_height_sigma: порог для поиска пиков (в стандартных отклонениях)
    
    Returns:
        dict с ключами: 'freqs', 'amplitudes', 'dominant_periods', 'n_dominant'
    """
    if series.empty or len(series) < 10:
        return {
            'freqs': np.array([]),
            'amplitudes': np.array([]),
            'dominant_periods': [],
            'n_dominant': 0
        }
    
    n = len(series)
    y = series.values - series.mean()
    yf = fft(y)
    xf = fftfreq(n, 1)[:n//2]
    amplitude = 2.0/n * np.abs(yf[0:n//2])
    
    # Доминирующие частоты
    threshold = np.mean(amplitude) + min_height_sigma * np.std(amplitude)
    peaks, _ = find_peaks(amplitude, height=threshold)
    dominant_periods = [1/xf[p] for p in peaks if xf[p] > 0 and xf[p] < 0.5]
    
    return {
        'freqs': xf,
        'amplitudes': amplitude,
        'dominant_periods': dominant_periods,
        'n_dominant': len(dominant_periods)
    }


def compute_periodogram_features(
    series: pd.Series,
    window: str = 'hann'
) -> Dict[str, any]:
    """
    Вычисляет периодограмму и спектральную энергию.
    
    Args:
        series: исходный ряд
        window: окно для периодограммы (по умолчанию 'hann')
    
    Returns:
        dict с ключами: 'freqs', 'psd', 'spectral_energy'
    """
    if series.empty or len(series) < 10:
        return {
            'freqs': np.array([]),
            'psd': np.array([]),
            'spectral_energy': 0.0
        }
    
    freq_per, pxx_per = periodogram(series.values, fs=1.0, window=window)
    spectral_energy = np.sum(pxx_per)
    
    return {
        'freqs': freq_per,
        'psd': pxx_per,
        'spectral_energy': spectral_energy
    }


def compute_spectral_entropy(
    series: pd.Series
) -> float:
    """
    Вычисляет спектральную энтропию (мера сложности сигнала).
    
    Args:
        series: исходный ряд
    
    Returns:
        спектральная энтропия (чем выше, тем сложнее сигнал)
    """
    if series.empty or len(series) < 10:
        return 0.0
    
    n = len(series)
    y = series.values - series.mean()
    yf = fft(y)
    spectrum = np.abs(yf)**2
    spectrum_norm = spectrum / np.sum(spectrum)
    spectral_entropy = -np.sum(spectrum_norm * np.log(spectrum_norm + 1e-10))
    
    return float(spectral_entropy)


def compute_low_high_freq_ratio(
    series: pd.Series
) -> float:
    """
    Вычисляет соотношение энергии низких и высоких частот.
    
    Args:
        series: исходный ряд
    
    Returns:
        ratio > 2 → низкочастотный сигнал, ratio < 0.5 → высокочастотный
    """
    if series.empty or len(series) < 10:
        return 0.0
    
    n = len(series)
    y = series.values - series.mean()
    yf = fft(y)
    xf = fftfreq(n, 1)[:n//2]
    amplitude = 2.0/n * np.abs(yf[0:n//2])
    
    mid_freq = len(xf)//4
    low_energy = np.sum(amplitude[:mid_freq]**2)
    high_energy = np.sum(amplitude[mid_freq:]**2)
    ratio = low_energy / (high_energy + 1e-10)
    
    return float(ratio)


def compute_all_spectral_features(
    series: pd.Series
) -> Dict[str, any]:
    """
    Вычисляет все спектральные метрики за один проход.
    
    Args:
        series: исходный ряд
    
    Returns:
        dict с ключами:
        - 'fft': результат compute_fft_features()
        - 'periodogram': результат compute_periodogram_features()
        - 'spectral_entropy': float
        - 'low_high_freq_ratio': float
    """
    fft_features = compute_fft_features(series)
    periodogram_features = compute_periodogram_features(series)
    spectral_entropy = compute_spectral_entropy(series)
    low_high_ratio = compute_low_high_freq_ratio(series)
    
    return {
        'fft': fft_features,
        'periodogram': periodogram_features,
        'spectral_entropy': spectral_entropy,
        'low_high_freq_ratio': low_high_ratio
    }
