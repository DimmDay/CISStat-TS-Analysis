from __future__ import annotations

import pandas as pd
import pytest

from apps.api.range_correction import preview_range_corrections
from validation.engine import profile_ranges


RULES = {
    "ranges": [
        {"name": "Цена 0–100", "keywords": ["Price"], "min": 0, "max": 100},
    ]
}


def test_profile_includes_passing_and_failing_metrics_for_each_applicable_rule():
    profile = profile_ranges(pd.DataFrame({"Price": [10.0, -5.0, 150.0, None]}), RULES)

    assert profile == [{
        "column": "Price",
        "rule_name": "Цена 0–100",
        "min_allowed": 0,
        "max_allowed": 100,
        "actual_min": -5.0,
        "actual_max": 150.0,
        "total_count": 3,
        "valid_count": 1,
        "invalid_count": 2,
        "invalid_pct": 66.67,
        "invalid_examples": [-5.0, 150.0],
    }]


def test_clip_preview_changes_only_violations_without_mutating_source():
    source = pd.DataFrame({"Price": [10.0, -5.0, 150.0, None]})

    corrected, results, rows_removed = preview_range_corrections(
        source, RULES, ["Price"], "clip"
    )

    assert source["Price"].tolist()[:3] == [10.0, -5.0, 150.0]
    assert corrected["Price"].tolist()[:3] == [10.0, 0.0, 100.0]
    assert results[0]["invalid_count"] == 2
    assert results[0]["changed_count"] == 2
    assert results[0]["still_invalid"] == 0
    assert rows_removed == 0


def test_median_uses_only_values_that_already_satisfy_the_rule():
    corrected, results, _ = preview_range_corrections(
        pd.DataFrame({"Price": [-5.0, 20.0, 40.0, 150.0]}),
        RULES,
        ["Price"],
        "median",
    )

    assert corrected["Price"].tolist() == [30.0, 20.0, 40.0, 30.0]
    assert results[0]["still_invalid"] == 0


def test_drop_rows_uses_the_union_of_selected_column_violations():
    rules = {"ranges": [
        {"keywords": ["Price"], "min": 0, "max": 100},
        {"keywords": ["Score"], "min": 0, "max": 1},
    ]}
    source = pd.DataFrame({"Price": [-1, 10, 20], "Score": [0.5, 2.0, 0.7]})

    corrected, results, rows_removed = preview_range_corrections(
        source, rules, ["Price", "Score"], "drop_rows"
    )

    assert corrected.to_dict("records") == [{"Price": 20, "Score": 0.7}]
    assert [item["invalid_count"] for item in results] == [1, 1]
    assert rows_removed == 2


def test_flag_preserves_values_and_adds_validity_column():
    source = pd.DataFrame({"Price": [-1, 10]})

    corrected, results, _ = preview_range_corrections(source, RULES, ["Price"], "flag")

    assert corrected["Price"].equals(source["Price"])
    assert corrected["Price_range_valid"].tolist() == [False, True]
    assert results[0]["flag_column"] == "Price_range_valid"
    assert results[0]["still_invalid"] == 1


def test_rejects_columns_without_an_active_range_rule():
    with pytest.raises(ValueError, match="нет активного правила диапазона"):
        preview_range_corrections(
            pd.DataFrame({"Other": [1, 2]}), RULES, ["Other"], "clip"
        )
