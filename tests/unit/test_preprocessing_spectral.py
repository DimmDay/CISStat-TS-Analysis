from __future__ import annotations

import numpy as np

from app.preprocessing.spectral import analyze_spectral_extensions


def test_extensions_build_welch_bands_and_wavelet_for_periodic_signal():
    rng = np.random.default_rng(85)
    time = np.arange(240, dtype=float)
    values = (
        3.0 * np.sin(2 * np.pi * time / 12)
        + 1.2 * np.sin(2 * np.pi * time / 5)
        + rng.normal(0, 0.25, len(time))
    )

    result = analyze_spectral_extensions(
        values,
        labels=[f"t{index}" for index in range(len(values))],
        max_period=80,
        welch_segment_length=64,
        wavelet_scales=24,
    )

    assert result["welch_segment_length"] == 64
    assert result["welch_segments"] >= 3
    assert result["welch"]
    assert abs(sum(item["power_share"] for item in result["bands"]) - 1.0) < 1e-6
    assert result["wavelet_method"] == "cmor1.5-1.0"
    assert result["wavelet"]
    assert result["wavelet_global"]
    dominant_global = max(result["wavelet_global"], key=lambda item: item["power_share"])
    assert abs(dominant_global["period"] - 12) < 3


def test_extensions_auto_segment_is_deterministic_and_does_not_mutate_values():
    values = np.sin(2 * np.pi * np.arange(96, dtype=float) / 12)
    original = values.copy()

    result = analyze_spectral_extensions(values, max_period=32)

    np.testing.assert_array_equal(values, original)
    assert 8 <= result["welch_segment_length"] <= len(values) // 2
    assert result["frequency_resolution"] == 1 / len(values)
    assert result["nyquist_frequency"] == 0.5


def test_extensions_validate_segment_and_input_contract():
    values = np.arange(32, dtype=float)
    try:
        analyze_spectral_extensions(values, max_period=10, welch_segment_length=4)
    except ValueError as exc:
        assert "8" in str(exc)
    else:
        raise AssertionError("Сегмент короче 8 должен быть отклонён")

    values[4] = np.nan
    try:
        analyze_spectral_extensions(values, max_period=10)
    except ValueError as exc:
        assert "конечн" in str(exc).lower()
    else:
        raise AssertionError("NaN не должен незаметно удаляться")
