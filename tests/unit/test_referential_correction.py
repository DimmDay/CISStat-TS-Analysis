from __future__ import annotations

import pandas as pd
import pytest

from apps.api.referential_correction import preview_referential_corrections
from validation.referential import profile_referential


RULES = {
    "referential": [
        {
            "name": "Код страны существует",
            "child_column": "CountryCode",
            "allowed_values": ["BY", "KZ"],
            "default_value": "BY",
        },
        {
            "name": "Валюта существует",
            "child_column": "Currency",
            "allowed_values": ["USD"],
        },
    ]
}


def _source() -> pd.DataFrame:
    return pd.DataFrame({
        "CountryCode": ["BY", "XX", "KZ", "XX"],
        "Currency": ["USD", "EUR", "USD", None],
        "Value": [1.0, 2.0, 3.0, 4.0],
    })


def test_profile_reports_orphans_and_non_applicable_rules():
    rules = {"referential": [
        *RULES["referential"],
        {"name": "Нет колонки", "child_column": "Missing", "allowed_values": ["A"]},
    ]}

    profile = profile_referential(_source(), rules)

    assert [item["rule_index"] for item in profile] == [0, 1, 2]
    assert profile[0]["applicable"] is True
    assert profile[0]["invalid_count"] == 2
    assert profile[0]["invalid_values"] == [{"value": "XX", "count": 2}]
    assert profile[0]["default_valid"] is True
    assert profile[2]["applicable"] is False
    assert "отсутствует" in profile[2]["applicability_message"]


def test_profile_does_not_infer_foreign_keys_and_coerces_numeric_editor_values():
    assert profile_referential(_source(), {"referential": []}) == []

    source = pd.DataFrame({"parent_id": [101, 102, 103]})
    profile = profile_referential(source, {"referential": [{
        "name": "Родитель существует",
        "child_column": "parent_id",
        "allowed_values": ["101", "102", "103"],
        "default_value": "101",
    }]})

    assert profile[0]["allowed_values"] == [101, 102, 103]
    assert profile[0]["default_value"] == 101
    assert profile[0]["invalid_count"] == 0


@pytest.mark.parametrize("strategy", ["mode", "replace_null", "replace_default"])
def test_replacement_strategies_remove_selected_orphans(strategy):
    corrected, results, rows_removed = preview_referential_corrections(
        _source(), RULES, [0], strategy
    )

    assert rows_removed == 0
    assert results[0]["invalid_count"] == 2
    assert results[0]["still_invalid"] == 0
    if strategy == "replace_null":
        assert pd.isna(corrected.loc[1, "CountryCode"])
    else:
        assert corrected.loc[1, "CountryCode"] == "BY"


def test_drop_rows_uses_union_and_flag_preserves_source_values():
    source = _source()
    dropped, results, rows_removed = preview_referential_corrections(
        source, RULES, [0, 1], "drop_rows"
    )
    assert rows_removed == 2
    assert len(dropped) == 2
    assert [item["invalid_count"] for item in results] == [2, 1]

    flagged, flag_results, _ = preview_referential_corrections(
        source, RULES, [0], "flag"
    )
    assert flagged["CountryCode"].equals(source["CountryCode"])
    assert flagged["CountryCode_ref_valid"].tolist() == [True, False, True, False]
    assert flag_results[0]["still_invalid"] == 2


def test_corrections_reject_non_applicable_rules_and_unsafe_replacements():
    with pytest.raises(ValueError, match="неприменимо"):
        preview_referential_corrections(
            _source(),
            {"referential": [{"name": "Нет", "child_column": "Missing", "allowed_values": ["A"]}]},
            [0],
            "drop_rows",
        )

    with pytest.raises(ValueError, match="нет допустимых значений"):
        preview_referential_corrections(
            pd.DataFrame({"Code": ["X", "Y"]}),
            {"referential": [{"name": "FK", "child_column": "Code", "allowed_values": ["A"]}]},
            [0],
            "mode",
        )

