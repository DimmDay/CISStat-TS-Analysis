from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.preprocessing.feature_engineering import generate_time_series_features


def _frame(size: int = 36) -> pd.DataFrame:
    return pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=size, freq="MS"),
        "Price": np.arange(1, size + 1, dtype=float),
    })


def test_target_features_are_strictly_past_only():
    frame = _frame(12)
    frame.loc[11, "Price"] = 10_000.0

    result, catalog = generate_time_series_features(
        frame,
        "Price",
        date_column="Date",
        lags=[1, 3],
        rolling_windows=[3],
        rolling_statistics=["mean", "std"],
        difference_lags=[1],
        calendar_features=[],
        fourier_periods=[],
        include_time_index=False,
    )

    assert result.loc[11, "Price_lag_1"] == 11.0
    assert result.loc[11, "Price_roll_mean_3"] == 10.0
    assert result.loc[11, "Price_diff_lagged_1"] == 1.0
    assert result.loc[0, "Price_lag_1"] != result.loc[0, "Price_lag_1"]
    assert {item["family"] for item in catalog} == {"lag", "rolling", "difference"}


def test_fourier_uses_observation_position_and_calendar_encoding_is_cyclic():
    result, catalog = generate_time_series_features(
        _frame(25),
        "Price",
        date_column="Date",
        lags=[],
        rolling_windows=[],
        rolling_statistics=[],
        difference_lags=[],
        calendar_features=["month_cyclic", "quarter", "year"],
        fourier_periods=[12],
        fourier_harmonics=2,
        include_time_index=True,
    )

    assert result.loc[0, "fourier_p12_k1_sin"] == pytest.approx(result.loc[12, "fourier_p12_k1_sin"])
    assert result.loc[0, "fourier_p12_k1_cos"] == pytest.approx(result.loc[12, "fourier_p12_k1_cos"])
    assert result.loc[0, "Date_month_sin"] == pytest.approx(result.loc[12, "Date_month_sin"])
    assert result["time_idx"].tolist() == list(range(25))
    assert {item["family"] for item in catalog} >= {"calendar", "fourier", "trend"}


def test_validation_blocks_non_positive_lags_duplicates_and_feature_collisions():
    with pytest.raises(ValueError, match="положитель"):
        generate_time_series_features(_frame(), "Price", lags=[0])
    with pytest.raises(ValueError, match="повтор"):
        generate_time_series_features(_frame(), "Price", lags=[1, 1])
    with pytest.raises(ValueError, match="меньше длины"):
        generate_time_series_features(_frame(12), "Price", lags=[12])

    frame = _frame()
    frame["Price_lag_1"] = 0.0
    with pytest.raises(ValueError, match="уже существуют"):
        generate_time_series_features(frame, "Price", lags=[1])


def test_period_two_adds_only_identifiable_nyquist_cosine():
    result, _ = generate_time_series_features(
        _frame(12), "Price", fourier_periods=[2], fourier_harmonics=1,
    )
    assert "fourier_p2_k1_cos" in result
    assert "fourier_p2_k1_sin" not in result


def test_numeric_year_axis_reuses_platform_parser_instead_of_unix_nanoseconds():
    frame = pd.DataFrame({"Year": [2019, 2020, 2021], "Price": [1.0, 2.0, 3.0]})
    result, _ = generate_time_series_features(
        frame, "Price", date_column="Year", calendar_features=["year"],
    )
    assert result["Year_year"].tolist() == [2019.0, 2020.0, 2021.0]
