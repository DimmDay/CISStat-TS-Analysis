from __future__ import annotations

import pandas as pd

from validation.sufficiency import profile_sufficiency


def test_profile_counts_only_valid_target_observations_per_group():
    df = pd.DataFrame({
        "Country": ["A"] * 6 + ["B"] * 6,
        "Date": list(pd.date_range("2024-01-01", periods=6, freq="D")) * 2,
        "Value": [1, 2, None, 4, None, 6, 10, 11, 12, 13, 14, 15],
    })
    rules = {"sufficiency": {
        "date_column": "Date", "entity_column": "Country", "target_column": "Value",
        "seasonal_period": 2, "min_obs_trend": 5, "min_obs_seasonality": 4,
        "min_obs_arima": 5, "min_obs_fft": 5, "min_obs_ml": 5, "min_seasons": 2,
    }}

    profile = profile_sufficiency(df, rules)

    assert profile["applicable"] is True
    assert profile["target_column"] == "Value"
    groups = {item["group"]: item for item in profile["groups"]}
    assert groups["A"]["valid_observations"] == 4
    assert groups["A"]["invalid_target_count"] == 2
    assert groups["A"]["failed_checks"] == 4
    assert groups["B"]["valid_observations"] == 6
    assert groups["B"]["seasonal_cycles"] == 3
    assert groups["B"]["failed_checks"] == 0
    assert profile["insufficient_groups"] == 1


def test_profile_detects_iso_date_and_excludes_year_from_target_candidates():
    df = pd.DataFrame({
        "Country": ["A"] * 10,
        "Year": list(range(2010, 2020)),
        "Price": [float(value) for value in range(10)],
    })

    profile = profile_sufficiency(df, {"sufficiency": {"min_obs_ml": 10}})

    assert profile["applicable"] is True
    assert profile["date_column"] == "Year"
    assert profile["target_column"] == "Price"
    assert profile["groups"][0]["valid_observations"] == 10


def test_profile_reports_not_applicable_without_reliable_time_axis():
    profile = profile_sufficiency(pd.DataFrame({"Value": [1.0, 2.0, 3.0]}), {})

    assert profile["applicable"] is False
    assert profile["groups"] == []
    assert "врем" in profile["applicability_message"].lower()

