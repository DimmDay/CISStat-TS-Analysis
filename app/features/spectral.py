# app/features/spectral.py
"""
Модуль спектрального анализа временных рядов.
Поддерживает FFT, Periodogram, Wavelet, спектральную энтропию.
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from scipy.fft import fft, fftfreq
from scipy.signal import find_peaks, periodogram, welch


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