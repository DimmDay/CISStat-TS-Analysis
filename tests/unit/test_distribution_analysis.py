from __future__ import annotations

import numpy as np
import pandas as pd

from app.eda.distributions import analyze_distribution


def test_normal_sample_runs_complementary_tests_with_holm_adjustment():
    values = pd.Series(np.random.default_rng(42).normal(size=320))

    result = analyze_distribution(values, alpha=0.05)

    assert result["applicable"] is True
    assert result["normality_applicable"] is True
    assert result["normality_status"] == "compatible"
    assert {item["id"] for item in result["tests"]} == {
        "shapiro", "jarque_bera", "lilliefors",
    }
    assert all(item["adjusted_p_value"] is not None for item in result["tests"])
    assert all(item["reject_normality"] is False for item in result["tests"])
    jarque_bera = next(item for item in result["tests"] if item["id"] == "jarque_bera")
    assert jarque_bera["calibration"] == "monte_carlo"
    assert result["qq_r"] > 0.99


def test_skewed_sample_is_not_compatible_with_normal_distribution():
    values = pd.Series(np.random.default_rng(7).exponential(size=400))

    result = analyze_distribution(values, alpha=0.05)

    assert result["applicable"] is True
    assert result["normality_status"] == "departed"
    assert result["skewness"] > 1
    assert sum(item["reject_normality"] is True for item in result["tests"]) >= 2
    assert "асиммет" in result["shape_label"].lower()


def test_shapiro_limit_and_jarque_bera_asymptotic_calibration_are_explicit():
    values = pd.Series(np.random.default_rng(11).normal(size=5_100))

    result = analyze_distribution(values)

    shapiro = next(item for item in result["tests"] if item["id"] == "shapiro")
    jarque_bera = next(item for item in result["tests"] if item["id"] == "jarque_bera")
    assert shapiro["available"] is False
    assert "5000" in shapiro["note"]
    assert jarque_bera["available"] is True
    assert jarque_bera["calibration"] == "asymptotic"


def test_discrete_missing_short_and_constant_series_are_handled_honestly():
    discrete = analyze_distribution(pd.Series(np.tile([0, 1, 2], 40)))
    assert discrete["applicable"] is True
    assert discrete["is_discrete"] is True
    assert discrete["normality_applicable"] is False
    assert discrete["normality_status"] == "not_applicable"
    assert all(item["available"] is False for item in discrete["tests"])

    missing_values = np.arange(80, dtype=float)
    missing_values[9] = np.nan
    missing = analyze_distribution(pd.Series(missing_values))
    assert missing["applicable"] is False
    assert missing["missing_count"] == 1
    assert "пропуск" in missing["reason"].lower()

    infinite_values = np.arange(80, dtype=float)
    infinite_values[10] = np.inf
    infinite = analyze_distribution(pd.Series(infinite_values))
    assert infinite["applicable"] is False
    assert infinite["missing_count"] == 1

    short = analyze_distribution(pd.Series(np.arange(7, dtype=float)))
    assert short["applicable"] is False
    assert "8" in short["reason"]

    constant = analyze_distribution(pd.Series(np.ones(40)))
    assert constant["applicable"] is False
    assert "констант" in constant["reason"].lower()
