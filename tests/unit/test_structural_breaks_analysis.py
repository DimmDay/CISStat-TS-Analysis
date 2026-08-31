from __future__ import annotations

import numpy as np
import pandas as pd

from app.eda.structural_breaks import analyze_structural_breaks


def test_level_shift_is_localized_and_supported_by_complementary_diagnostics():
    rng = np.random.default_rng(42)
    values = np.r_[rng.normal(0, 0.25, 120), rng.normal(4, 0.25, 120)]

    result = analyze_structural_breaks(pd.Series(values), alpha=0.05, min_segment=20)

    assert result["applicable"] is True
    assert result["cusum"]["reject_stability"] is True
    assert result["break_count"] >= 1
    candidate = min(result["candidates"], key=lambda item: abs(item["index"] - 120))
    assert abs(candidate["index"] - 120) <= 3
    assert candidate["adjusted_p_value"] < 0.05
    assert candidate["supported"] is True
    assert candidate["level_change"] > 3
    assert result["status"] == "breaks_detected"


def test_stable_linear_trend_is_not_split_into_false_regimes():
    rng = np.random.default_rng(7)
    index = np.arange(240, dtype=float)
    values = 1.5 + 0.03 * index + rng.normal(0, 0.3, len(index))

    result = analyze_structural_breaks(pd.Series(values), min_segment=20)

    assert result["applicable"] is True
    assert result["break_count"] == 0
    assert result["supported_count"] == 0
    assert result["status"] == "stable"
    assert result["cusum"]["reject_stability"] is False


def test_slope_change_is_detected_by_piecewise_linear_cost():
    rng = np.random.default_rng(19)
    index = np.arange(260, dtype=float)
    values = np.where(index < 130, 2 + 0.01 * index, 3.3 + 0.09 * (index - 130))
    values += rng.normal(0, 0.2, len(index))

    result = analyze_structural_breaks(pd.Series(values), min_segment=25)

    candidate = min(result["candidates"], key=lambda item: abs(item["index"] - 130))
    assert abs(candidate["index"] - 130) <= 5
    assert candidate["slope_change"] > 0.05
    assert candidate["supported"] is True


def test_penalty_controls_complexity_and_invalid_series_are_refused_honestly():
    rng = np.random.default_rng(21)
    values = np.r_[rng.normal(0, 0.7, 80), rng.normal(2, 0.7, 80), rng.normal(-1, 0.7, 80)]
    low = analyze_structural_breaks(pd.Series(values), penalty_multiplier=0.75)
    high = analyze_structural_breaks(pd.Series(values), penalty_multiplier=5.0)
    assert high["break_count"] <= low["break_count"]

    missing_values = np.arange(80, dtype=float)
    missing_values[5] = np.nan
    missing = analyze_structural_breaks(pd.Series(missing_values))
    assert missing["applicable"] is False
    assert missing["missing_count"] == 1
    assert "пропуск" in missing["reason"].lower()

    short = analyze_structural_breaks(pd.Series(np.arange(30, dtype=float)))
    assert short["applicable"] is False
    assert "60" in short["reason"]

    constant = analyze_structural_breaks(pd.Series(np.ones(100)))
    assert constant["applicable"] is False
    assert "констант" in constant["reason"].lower()


def test_long_series_bounds_pelt_grid_and_preserves_break_localization():
    rng = np.random.default_rng(31)
    values = np.r_[rng.normal(0, 0.3, 500), rng.normal(2.5, 0.3, 500)]

    result = analyze_structural_breaks(pd.Series(values), min_segment=30)

    assert result["jump"] == 4
    assert min(abs(item["index"] - 500) for item in result["candidates"]) <= result["jump"]
    assert any("вычисл" in warning.lower() and "шаг" in warning.lower() for warning in result["warnings"])


def test_exact_linear_series_is_reported_as_numerically_degenerate():
    result = analyze_structural_breaks(pd.Series(np.arange(100, dtype=float)))

    assert result["applicable"] is False
    assert "линейн" in result["reason"].lower()
