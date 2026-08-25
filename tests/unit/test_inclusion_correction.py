from __future__ import annotations

import pandas as pd
import pytest

from apps.api.inclusion_correction import preview_inclusion_corrections
from validation.engine import profile_inclusion


RULES = {
    "inclusion": {
        "Country": {"allowed_values": ["A", "B"], "default_value": "A"},
        "Currency": ["USD"],
    },
    "inclusion_defaults": {"Currency": "USD"},
}


def _source() -> pd.DataFrame:
    return pd.DataFrame({
        "Country": ["A", "X", "B", "X"],
        "Currency": ["USD", "EUR", "USD", None],
        "Value": [1.0, 2.0, 3.0, 4.0],
    })


def test_profile_normalizes_yaml_dict_and_legacy_list_rules():
    profile = profile_inclusion(_source(), RULES)

    assert [item["column"] for item in profile] == ["Country", "Currency"]
    assert profile[0]["allowed_values"] == ["A", "B"]
    assert profile[0]["total_count"] == 4
    assert profile[0]["valid_count"] == 2
    assert profile[0]["invalid_count"] == 2
    assert profile[0]["invalid_values"] == [{"value": "X", "count": 2}]
    assert profile[0]["default_value"] == "A"
    assert profile[0]["default_valid"] is True
    assert profile[1]["invalid_count"] == 1
    assert profile[1]["default_value"] == "USD"


def test_profile_does_not_infer_a_domain_from_observed_values():
    assert profile_inclusion(_source(), {"inclusion": {}}) == []
    assert profile_inclusion(_source(), {
        "inclusion": {"Missing": {"allowed_values": ["A"]}}
    }) == []


@pytest.mark.parametrize("strategy", ["mode", "replace_null", "replace_default"])
def test_value_replacement_strategies_remove_selected_violations(strategy):
    corrected, results, rows_removed = preview_inclusion_corrections(
        _source(), RULES, ["Country"], strategy
    )

    assert rows_removed == 0
    assert results[0]["invalid_count"] == 2
    assert results[0]["still_invalid"] == 0
    if strategy == "replace_null":
        assert pd.isna(corrected.loc[1, "Country"])
    else:
        assert corrected.loc[1, "Country"] == "A"


def test_drop_rows_uses_union_and_flag_preserves_source_values():
    source = _source()
    dropped, results, rows_removed = preview_inclusion_corrections(
        source, RULES, ["Country", "Currency"], "drop_rows"
    )
    assert rows_removed == 2
    assert len(dropped) == 2
    assert [item["invalid_count"] for item in results] == [2, 1]

    flagged, flag_results, _ = preview_inclusion_corrections(
        source, RULES, ["Country"], "flag"
    )
    assert flagged["Country"].equals(source["Country"])
    assert flagged["Country_inclusion_valid"].tolist() == [True, False, True, False]
    assert flag_results[0]["still_invalid"] == 2


def test_mode_requires_an_observed_valid_value_and_default_must_be_allowed():
    source = pd.DataFrame({"Code": ["X", "Y"]})
    with pytest.raises(ValueError, match="нет допустимых значений"):
        preview_inclusion_corrections(
            source, {"inclusion": {"Code": ["A", "B"]}}, ["Code"], "mode"
        )
    with pytest.raises(ValueError, match="значение по умолчанию"):
        preview_inclusion_corrections(
            source,
            {"inclusion": {"Code": {"allowed_values": ["A"], "default_value": "Unknown"}}},
            ["Code"],
            "replace_default",
        )
