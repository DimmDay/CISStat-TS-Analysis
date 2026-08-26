from __future__ import annotations

import pandas as pd
import pytest

from apps.api.regularity_correction import preview_regularity_correction
from validation.regularity import profile_regularity


RULES = {
    "regularity": {
        "date_column": "date",
        "entity_column": "country",
        "frequency": "D",
        "gap_threshold_multiplier": 1.5,
    }
}


def _panel() -> pd.DataFrame:
    return pd.DataFrame({
        "country": ["A", "A", "A", "B", "B", "B"],
        "date": pd.to_datetime([
            "2024-01-01", "2024-01-03", "2024-01-04",
            "2024-01-01", "2024-01-02", "2024-01-03",
        ]),
        "value": [1.0, 3.0, 4.0, 10.0, 20.0, 30.0],
        "label": ["x", "x", "x", "y", "y", "y"],
    })


def test_profile_detects_gap_only_inside_affected_panel_group():
    profile = profile_regularity(_panel(), RULES)

    assert profile["applicable"] is True
    assert profile["date_column"] == "date"
    assert profile["entity_column"] == "country"
    assert profile["target_frequency"] == "D"
    assert profile["gap_count"] == 1
    assert profile["missing_period_count"] == 1
    assert profile["duplicate_count"] == 0
    assert [item["group"] for item in profile["groups"]] == ["A", "B"]
    assert [item["gap_count"] for item in profile["groups"]] == [1, 0]


def test_profile_distinguishes_sort_duplicates_and_bad_dates():
    source = pd.DataFrame({
        "date": ["2024-01-02", "bad", "2024-01-01", "2024-01-01"],
        "value": [2, 9, 1, 3],
    })
    profile = profile_regularity(source, {"regularity": {"date_column": "date", "frequency": "D"}})

    assert profile["invalid_date_count"] == 1
    assert profile["is_sorted"] is False
    assert profile["sort_violations"] == 1
    assert profile["duplicate_count"] == 1
    assert profile["total_violations"] == 3


def test_explicit_frequency_is_the_reference_even_when_observed_step_is_stable():
    source = pd.DataFrame({
        "date": pd.to_datetime(["2024-01-01", "2024-01-03", "2024-01-05"]),
        "value": [1, 2, 3],
    })

    profile = profile_regularity(source, {"regularity": {
        "date_column": "date", "frequency": "D", "gap_threshold_multiplier": 1.5,
    }})

    assert profile["gap_count"] == 2
    assert profile["missing_period_count"] == 2


def test_profile_is_not_applicable_without_a_reliable_time_axis():
    profile = profile_regularity(pd.DataFrame({"country": ["A", "B"], "value": [1, 2]}), {})

    assert profile["applicable"] is False
    assert profile["date_column"] is None
    assert "временная колонка" in profile["applicability_message"]


@pytest.mark.parametrize("strategy", ["interpolate", "ffill", "bfill", "asfreq", "fictitious_zero"])
def test_resampling_strategies_fill_the_grid_without_mutating_source(strategy):
    source = _panel()
    corrected, summary = preview_regularity_correction(source, RULES, strategy, "D")

    assert len(source) == 6
    assert summary["rows_added"] == 1
    assert len(corrected) == 7
    assert summary["total_violations_before"] == 1
    assert summary["total_violations_after"] == 0
    assert corrected.columns.tolist() == source.columns.tolist()
    inserted = corrected[(corrected["country"] == "A") & (corrected["date"] == pd.Timestamp("2024-01-02"))]
    assert len(inserted) == 1
    if strategy == "interpolate":
        assert inserted.iloc[0]["value"] == 2.0
    if strategy == "fictitious_zero":
        assert inserted.iloc[0]["value"] == 0


def test_sort_and_flag_strategies_are_non_destructive():
    source = _panel().iloc[[1, 0, 2, 3, 4, 5]].reset_index(drop=True)
    sorted_df, summary = preview_regularity_correction(source, RULES, "sort", None)
    assert summary["sort_violations_before"] == 1
    assert summary["sort_violations_after"] == 0
    assert sorted_df.groupby("country")["date"].apply(lambda values: values.is_monotonic_increasing).all()

    flagged, flag_summary = preview_regularity_correction(_panel(), RULES, "flag", None)
    assert "_has_gap" in flagged.columns
    assert flagged["_has_gap"].sum() == 1
    assert flag_summary["total_violations_after"] == 1


def test_strict_preview_rejects_bad_frequency_invalid_dates_and_existing_flag():
    with pytest.raises(ValueError, match="частот"):
        preview_regularity_correction(_panel(), RULES, "interpolate", "INVALID")
    bad = _panel().astype({"date": "object"})
    bad.loc[0, "date"] = "bad"
    with pytest.raises(ValueError, match="некорректные даты"):
        preview_regularity_correction(bad, RULES, "interpolate", "D")
    flagged = _panel().assign(_has_gap=False)
    with pytest.raises(ValueError, match="уже существует"):
        preview_regularity_correction(flagged, RULES, "flag", None)
