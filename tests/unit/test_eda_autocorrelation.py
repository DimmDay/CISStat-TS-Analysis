from __future__ import annotations

import numpy as np
import pandas as pd

from app.eda.correlation import analyze_autocorrelation


def _ar1(size: int = 160, phi: float = 0.8) -> pd.Series:
    rng = np.random.default_rng(42)
    values = np.zeros(size)
    noise = rng.normal(size=size)
    for index in range(1, size):
        values[index] = phi * values[index - 1] + noise[index]
    return pd.Series(values)


def test_autocorrelation_profiles_an_ar1_series():
    result = analyze_autocorrelation(_ar1(), max_lags=40)

    assert result["applicable"] is True
    assert result["n_observations"] == 160
    assert result["max_lag"] == 40
    assert len(result["acf"]) == 41
    assert len(result["pacf"]) == 41
    assert result["acf"][1]["significant"] is True
    assert result["pacf"][1]["significant"] is True
    assert result["ljung_box_lag"] == 10
    assert 0 <= result["ljung_box_pvalue"] <= 1


def test_autocorrelation_clamps_lags_to_a_safe_pacf_limit():
    result = analyze_autocorrelation(_ar1(size=24), max_lags=100)

    assert result["applicable"] is True
    assert result["requested_max_lags"] == 100
    assert result["max_lag"] == 11


def test_autocorrelation_refuses_short_missing_and_constant_series():
    short = analyze_autocorrelation(pd.Series(range(7)), max_lags=4)
    missing = analyze_autocorrelation(pd.Series([1, 2, 3, np.nan, 5, 6, 7, 8]), max_lags=3)
    constant = analyze_autocorrelation(pd.Series([5.0] * 20), max_lags=5)

    assert short["applicable"] is False
    assert "минимум 8" in short["reason"]
    assert missing["applicable"] is False
    assert missing["missing_count"] == 1
    assert "пропуск" in missing["reason"].lower()
    assert constant["applicable"] is False
    assert "констант" in constant["reason"].lower()

