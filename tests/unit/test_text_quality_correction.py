from __future__ import annotations

import pandas as pd
import pytest

from apps.api.text_quality_correction import preview_text_quality_corrections
from validation.text_quality import profile_text_quality


RULES = {
    "text_quality": {
        "min_length": 1,
        "max_length": 8,
        "garbage_chars": ["", "\\x00", "ï¿½"],
    }
}


def _source() -> pd.DataFrame:
    return pd.DataFrame({
        "label": ["Clean", "  padded  ", "bad\x00", "", "very-long-value", None],
        "value": [1, 2, 3, 4, 5, 6],
    })


def test_profile_reports_every_text_column_and_disjoint_row_count():
    profile = profile_text_quality(_source(), RULES)

    assert [item["column"] for item in profile] == ["label"]
    item = profile[0]
    assert item["total_count"] == 5
    assert item["invalid_count"] == 4
    assert item["valid_count"] == 1
    assert item["issue_counts"] == {
        "garbage": 1,
        "empty": 1,
        "too_short": 1,
        "too_long": 2,
        "whitespace": 1,
        "pattern": 0,
    }
    assert item["invalid_count"] <= item["total_count"]


def test_empty_garbage_rule_never_matches_every_value():
    profile = profile_text_quality(
        pd.DataFrame({"label": ["Москва", "Минск"]}),
        {"text_quality": {"garbage_chars": [""]}},
    )

    assert profile[0]["invalid_count"] == 0


@pytest.mark.parametrize("strategy", ["normalize", "replace_null", "replace_unknown"])
def test_value_strategies_operate_on_a_copy(strategy):
    source = _source()
    corrected, results, rows_removed = preview_text_quality_corrections(
        source, RULES, ["label"], strategy
    )

    assert source.loc[1, "label"] == "  padded  "
    assert rows_removed == 0
    assert results[0]["invalid_count"] == 4
    assert len(corrected) == len(source)


def test_drop_rows_uses_union_and_flag_preserves_values():
    source = pd.DataFrame({
        "left": ["ok", "bad\x00", "ok"],
        "right": ["ok", "ok", "   "],
    })
    dropped, results, rows_removed = preview_text_quality_corrections(
        source, RULES, ["left", "right"], "drop_rows"
    )
    assert rows_removed == 2
    assert len(dropped) == 1
    assert [item["invalid_count"] for item in results] == [1, 1]

    flagged, flag_results, _ = preview_text_quality_corrections(
        source, RULES, ["left"], "flag"
    )
    assert flagged["left"].equals(source["left"])
    assert flagged["left_text_valid"].tolist() == [True, False, True]
    assert flag_results[0]["still_invalid"] == 1


def test_rejects_numeric_columns_and_duplicate_selection():
    with pytest.raises(ValueError, match="не является текстовой"):
        preview_text_quality_corrections(_source(), RULES, ["value"], "normalize")
    with pytest.raises(ValueError, match="повторяться"):
        preview_text_quality_corrections(_source(), RULES, ["label", "label"], "normalize")
