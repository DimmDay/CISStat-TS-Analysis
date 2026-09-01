from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.preprocessing_stationarity import (
    build_stationarity_profile,
    preview_stationarity_transformation,
)
from apps.api.schemas import DatasetPreprocessingStationarityProfileResponse


def _random_walk_frame(size: int = 180) -> pd.DataFrame:
    rng = np.random.default_rng(27)
    values = np.cumsum(rng.normal(size=size))
    return pd.DataFrame({
        "Date": pd.date_range("2010-01-01", periods=size, freq="MS"),
        "Price": values,
    })


def test_profile_reuses_complementary_tests_and_builds_five_visual_payloads():
    result = build_stationarity_profile(
        _random_walk_frame(), "Price", method="auto", alpha=0.05,
        seasonal_period=12, rolling_window=12,
    )
    response = DatasetPreprocessingStationarityProfileResponse(
        mode="auto", status="warning", status_reason=None, profile=result,
    )

    assert response.profile.applicable is True
    assert response.profile.consensus_before in {"non-stationary", "inconclusive"}
    assert response.profile.selected_method == "first_difference"
    assert response.profile.consensus_after in {"stationary", "trend-stationary"}
    assert response.profile.tests
    assert response.profile.points
    assert response.profile.acf
    assert response.profile.candidates


def test_preview_sorts_time_drops_only_unavailable_prefix_and_saves_inverse_state():
    frame = _random_walk_frame(80).iloc[::-1].reset_index(drop=True)
    original = frame.copy(deep=True)

    transformed, summary = preview_stationarity_transformation(
        frame, "Price", "first_difference", seasonal_period=12,
    )

    pd.testing.assert_frame_equal(frame, original)
    assert len(transformed) == 79
    assert transformed["Date"].is_monotonic_increasing
    assert summary["rows_dropped"] == 1
    assert summary["output_column"] == "Price_diff1"
    assert transformed["Price_diff1"].notna().all()
    assert summary["metadata"]["inverse_supported"] is True
    assert len(summary["metadata"]["history_tail"]) == 1


def test_linear_detrend_requires_explicit_offline_confirmation():
    frame = _random_walk_frame(80)
    with pytest.raises(ValueError, match="некаузаль"):
        preview_stationarity_transformation(
            frame, "Price", "linear_detrend", seasonal_period=12,
            confirm_non_causal=False,
        )
    result, summary = preview_stationarity_transformation(
        frame, "Price", "linear_detrend", seasonal_period=12,
        confirm_non_causal=True,
    )
    assert len(result) == len(frame)
    assert summary["metadata"]["causal"] is False


def test_profile_refuses_missing_irregular_panel_and_constant_series():
    missing = _random_walk_frame(80)
    missing.loc[4, "Price"] = np.nan
    assert build_stationarity_profile(missing, "Price")["applicable"] is False

    irregular = _random_walk_frame(80).drop(index=7).reset_index(drop=True)
    assert "нерегуляр" in build_stationarity_profile(irregular, "Price")["reason"].lower()

    panel = pd.concat([_random_walk_frame(40), _random_walk_frame(40)], ignore_index=True)
    assert "панель" in build_stationarity_profile(panel, "Price")["reason"].lower()

    constant = _random_walk_frame(80)
    constant["Price"] = 1.0
    assert "констант" in build_stationarity_profile(constant, "Price")["reason"].lower()
