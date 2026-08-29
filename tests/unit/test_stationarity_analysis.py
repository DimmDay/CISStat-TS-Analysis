from __future__ import annotations

import builtins

import numpy as np
import pandas as pd

from app.eda.stationarity import analyze_stationarity


def test_white_noise_is_level_stationary_with_complementary_tests():
    rng = np.random.default_rng(42)
    result = analyze_stationarity(pd.Series(rng.normal(size=300)), alpha=0.05)

    assert result["applicable"] is True
    assert result["consensus"] == "stationary"
    assert result["adf"]["is_stationary"] is True
    assert result["adf_trend"]["is_stationary"] is True
    assert result["kpss"]["is_stationary_level"] is True
    assert result["kpss"]["is_stationary_trend"] is True
    assert result["pp"]["available"] is True
    assert result["pp"]["is_stationary"] is True


def test_random_walk_is_non_stationary_and_trend_stationary_is_distinguished():
    rng = np.random.default_rng(7)
    walk = analyze_stationarity(pd.Series(np.cumsum(rng.normal(size=500))))
    assert walk["applicable"] is True
    assert walk["consensus"] == "non-stationary"

    rng = np.random.default_rng(8)
    trend = 0.4 * np.arange(400) + rng.normal(scale=0.5, size=400)
    trend_result = analyze_stationarity(pd.Series(trend))
    assert trend_result["applicable"] is True
    assert trend_result["consensus"] == "trend-stationary"
    assert trend_result["adf_trend"]["is_stationary"] is True
    assert trend_result["kpss"]["is_stationary_trend"] is True


def test_missing_pp_dependency_is_reported_without_adf_proxy(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "arch.unitroot" or name.startswith("arch."):
            raise ModuleNotFoundError("arch intentionally unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    rng = np.random.default_rng(11)
    result = analyze_stationarity(pd.Series(rng.normal(size=160)))

    assert result["applicable"] is True
    assert result["pp"]["available"] is False
    assert result["pp"]["stat"] is None
    assert result["pp"]["pvalue"] is None
    assert result["pp"]["is_stationary"] is None
    assert "ADF" not in result["pp"]["note"]


def test_zivot_andrews_returns_real_breakpoint_index_not_critical_values_dict():
    rng = np.random.default_rng(17)
    values = np.r_[rng.normal(0, 0.35, 120), rng.normal(4, 0.35, 120)]
    result = analyze_stationarity(pd.Series(values))

    assert result["za"]["available"] is True
    assert isinstance(result["za"]["breakpoint"], int)
    assert 80 <= result["za"]["breakpoint"] <= 160
    assert result["za"]["is_stationary"] == (result["za"]["pvalue"] < 0.05)


def test_short_missing_infinite_and_constant_series_are_honestly_not_applicable():
    short = analyze_stationarity(pd.Series(np.arange(20, dtype=float)))
    assert short["applicable"] is False
    assert "30" in short["reason"]

    missing_values = np.arange(60, dtype=float)
    missing_values[5] = np.nan
    missing = analyze_stationarity(pd.Series(missing_values))
    assert missing["applicable"] is False
    assert missing["missing_count"] == 1
    assert "пропуск" in missing["reason"].lower()

    infinite_values = np.arange(60, dtype=float)
    infinite_values[7] = np.inf
    infinite = analyze_stationarity(pd.Series(infinite_values))
    assert infinite["applicable"] is False
    assert infinite["missing_count"] == 1

    constant = analyze_stationarity(pd.Series(np.ones(60)))
    assert constant["applicable"] is False
    assert "констант" in constant["reason"].lower()
