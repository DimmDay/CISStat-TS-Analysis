from __future__ import annotations

import numpy as np
import pandas as pd

from app.features.spectral import analyze_spectral_seasonality


def test_spectral_analysis_finds_multiple_periods_and_builds_phase_profile():
    rng = np.random.default_rng(42)
    time = np.arange(240, dtype=float)
    values = (
        3.0 * np.sin(2 * np.pi * time / 12)
        + 1.4 * np.sin(2 * np.pi * time / 5)
        + rng.normal(0, 0.25, len(time))
    )

    result = analyze_spectral_seasonality(
        pd.Series(values), min_cycles=3, max_candidates=6
    )

    assert result["applicable"] is True
    periods = [item["period"] for item in result["candidates"]]
    assert any(abs(period - 12) < 0.7 for period in periods)
    assert any(abs(period - 5) < 0.4 for period in periods)
    assert result["dominant_period"] == result["candidates"][0]["period"]
    assert result["phase_period"] == 12
    assert len(result["phase_profile"]) == 12
    assert 0 <= result["spectral_entropy"] <= 1
    assert result["candidates"][0]["confirmed"] is True


def test_spectral_analysis_detrends_linear_signal_without_inventing_confirmed_period():
    values = pd.Series(100 + 2.5 * np.arange(120, dtype=float))

    result = analyze_spectral_seasonality(values, min_cycles=3, max_candidates=5)

    assert result["applicable"] is True
    assert result["detrend"] == "linear"
    assert result["window"] == "hann"
    assert not any(item["confirmed"] for item in result["candidates"])


def test_spectral_analysis_refuses_missing_values_instead_of_collapsing_time():
    values = pd.Series(np.sin(2 * np.pi * np.arange(48) / 12))
    values.iloc[10] = np.nan

    result = analyze_spectral_seasonality(values)

    assert result["applicable"] is False
    assert result["missing_count"] == 1
    assert "пропуск" in result["reason"].lower()

