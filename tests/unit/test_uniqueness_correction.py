from __future__ import annotations

import pandas as pd
import pytest

from apps.api.uniqueness_correction import preview_uniqueness_correction
from validation.engine import profile_uniqueness


def _source() -> pd.DataFrame:
    return pd.DataFrame({
        "Country": ["A", "A", "A", "B", "B"],
        "Year": [2020, 2020, 2021, 2020, 2020],
        "Price": [10.0, 14.0, 20.0, 30.0, 30.0],
        "Note": ["first", "second", "single", "same", "same"],
    })


RULES = {"uniqueness": {"composite_key": ["Country", "Year"]}}


def test_profile_distinguishes_duplicate_rows_groups_and_redundant_copies():
    profile = profile_uniqueness(_source(), RULES)

    assert profile["applicable"] is True
    assert profile["mode"] == "composite_key"
    assert profile["key_columns"] == ["Country", "Year"]
    assert profile["total_rows"] == 5
    assert profile["valid_rows"] == 1
    assert profile["duplicate_rows"] == 4
    assert profile["duplicate_groups"] == 2
    assert profile["redundant_rows"] == 2
    assert profile["duplicate_pct"] == 80.0
    assert profile["groups"][0]["key_values"] == {"Country": "A", "Year": "2020"}
    assert profile["groups"][0]["occurrences"] == 2


def test_system_profile_infers_entity_and_time_then_falls_back_to_full_rows():
    inferred = profile_uniqueness(_source(), {"uniqueness": {}})
    assert inferred["mode"] == "inferred_key"
    assert inferred["key_columns"] == ["Country", "Year"]

    plain = pd.DataFrame({"Value": [1, 1, 2], "Label": ["x", "x", "y"]})
    fallback = profile_uniqueness(plain, {"uniqueness": {}})
    assert fallback["mode"] == "full_row"
    assert fallback["key_columns"] == ["Value", "Label"]
    assert fallback["duplicate_rows"] == 2


def test_explicit_key_with_missing_column_is_not_a_false_pass():
    profile = profile_uniqueness(
        _source(),
        {"uniqueness": {"composite_key": ["Country", "Missing"]}},
    )

    assert profile["applicable"] is False
    assert profile["duplicate_rows"] is None
    assert "Missing" in profile["applicability_message"]


@pytest.mark.parametrize(
    ("strategy", "expected_rows", "expected_removed"),
    [("keep_first", 3, 2), ("keep_last", 3, 2), ("drop_all", 1, 4)],
)
def test_deletion_previews_are_transactional(strategy, expected_rows, expected_removed):
    source = _source()
    corrected, summary = preview_uniqueness_correction(source, RULES, strategy)

    assert len(source) == 5
    assert len(corrected) == expected_rows
    assert summary["rows_removed"] == expected_removed
    assert summary["still_duplicate_rows"] == 0


def test_aggregate_uses_mean_for_numeric_and_first_for_other_values():
    corrected, summary = preview_uniqueness_correction(_source(), RULES, "aggregate")

    a_2020 = corrected[(corrected["Country"] == "A") & (corrected["Year"] == 2020)].iloc[0]
    assert a_2020["Price"] == 12.0
    assert a_2020["Note"] == "first"
    assert len(corrected) == 3
    assert summary["rows_removed"] == 2
    assert summary["still_duplicate_rows"] == 0


def test_aggregate_supports_a_key_that_contains_every_column():
    source = pd.DataFrame({"Country": ["A", "A"], "Year": [2020, 2020]})
    rules = {"uniqueness": {"composite_key": ["Country", "Year"]}}

    corrected, summary = preview_uniqueness_correction(source, rules, "aggregate")

    assert len(corrected) == 1
    assert summary["rows_removed"] == 1


def test_flag_preserves_values_and_reports_duplicates_as_remaining():
    source = _source()
    corrected, summary = preview_uniqueness_correction(source, RULES, "flag")

    assert corrected[source.columns].equals(source)
    assert corrected["uniqueness_valid"].tolist() == [False, False, True, False, False]
    assert summary["added_columns"] == ["uniqueness_valid"]
    assert summary["still_duplicate_rows"] == 4
