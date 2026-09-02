"""TDD-контракт этапа 1: канонический ряд и методология паспорта."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.passport import (
    calculate_ts_passport,
    prepare_passport_series,
    series_fingerprint,
)


def test_prepare_passport_series_cleans_and_stably_sorts_without_mutation():
    frame = pd.DataFrame(
        {
            "when": ["2024-01-03", "bad", "2024-01-01", "2024-01-02"],
            "value": [3, 999, "1", np.inf],
        }
    )
    original = frame.copy(deep=True)

    result = prepare_passport_series(frame, "value", "when", min_points=2)

    assert result.name == "value"
    assert result.tolist() == [1.0, 3.0]
    assert result.index.tolist() == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-03")]
    pd.testing.assert_frame_equal(frame, original)


def test_prepare_passport_series_rejects_panel_duplicates():
    frame = pd.DataFrame(
        {
            "when": ["2024-01-01"] * 2 + list(pd.date_range("2024-01-02", periods=29, freq="D")),
            "value": np.arange(31),
        }
    )

    with pytest.raises(ValueError, match="повторяющиеся даты"):
        prepare_passport_series(frame, "value", "when")


def test_prepare_passport_series_requires_30_valid_observations_after_cleaning():
    frame = pd.DataFrame(
        {
            "when": pd.date_range("2024-01-01", periods=30, freq="D"),
            "value": list(range(29)) + [np.nan],
        }
    )

    with pytest.raises(ValueError, match="30"):
        prepare_passport_series(frame, "value", "when")


def test_series_fingerprint_is_canonical_and_detects_old_aggregate_collision():
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    first = pd.Series([1.0, 2.0, 3.0, 4.0], index=dates)
    # Та же длина, first/last, sum и sumsq, что у first: старый fingerprint
    # считал эти ряды одинаковыми.
    collision = pd.Series([1.0, 3.0, 2.0, 4.0], index=dates)

    assert series_fingerprint(first.sample(frac=1, random_state=7)) == series_fingerprint(first)
    assert series_fingerprint(collision) != series_fingerprint(first)
    assert series_fingerprint(first.set_axis(dates + pd.Timedelta(days=1))) != series_fingerprint(first)


def test_calculate_passport_cleans_non_finite_values_before_length_check():
    values = np.arange(31, dtype=float)
    values[-2:] = [np.nan, np.inf]
    series = pd.Series(values, index=pd.date_range("2024-01-01", periods=31, freq="D"))

    result = calculate_ts_passport(series)

    assert result == {"error": "Недостаточно данных (нужно минимум 30 валидных точек)"}


def test_irregular_series_marks_lag_and_spectral_metrics_not_applicable():
    dates = pd.date_range("2024-01-01", periods=90, freq="D").delete([7, 23])
    values = np.sin(2 * np.pi * np.arange(len(dates)) / 7)

    result = calculate_ts_passport(pd.Series(values, index=dates))

    assert result["freq"]["is_regular"] is False
    for section in (
        "autocorrelation",
        "seasonality",
        "seasonal_periods",
        "hurst",
        "fft",
        "periodogram",
        "wavelet",
    ):
        assert result[section]["applicable"] is False, section
        assert result[section]["reason"]


@pytest.mark.parametrize(
    ("freq", "period"),
    [("D", 7), ("B", 5), ("W", 52), ("MS", 12), ("QS", 4)],
)
def test_frequency_specific_stl_period(freq: str, period: int):
    n = max(120, period * 3)
    series = pd.Series(
        np.sin(2 * np.pi * np.arange(n) / period),
        index=pd.date_range("2010-01-01", periods=n, freq=freq),
    )

    result = calculate_ts_passport(series)

    assert result["seasonality"]["applicable"] is True
    assert result["seasonality"]["period"] == period


def test_yearly_series_does_not_invent_monthly_seasonality():
    series = pd.Series(
        np.arange(40, dtype=float),
        index=pd.date_range("1980-01-01", periods=40, freq="YS"),
    )

    result = calculate_ts_passport(series)

    assert result["freq"]["is_regular"] is True
    assert result["seasonality"]["applicable"] is False
    assert result["seasonality"]["period"] is None


def test_passport_exposes_statistical_assumptions():
    rng = np.random.default_rng(42)
    series = pd.Series(rng.normal(size=200), index=pd.date_range("2024-01-01", periods=200, freq="D"))

    result = calculate_ts_passport(series)

    assert result["stationarity"]["null_hypothesis"]
    assert result["autocorrelation"]["tested_lag"] == 10
    assert result["normality"]["asymptotic_reliable"] is False
    assert result["normality"]["reliability_threshold"] == 2000
