from __future__ import annotations

import pandas as pd
import pytest

from apps.api.consistency_correction import preview_consistency_corrections
from validation.engine import profile_consistency, validate_consistency


RULES = {
    "consistency": [
        {
            "name": "Хронология по странам",
            "type": "chronology",
            "columns": ["Year"],
            "group_column": "Country",
        },
        {
            "name": "Цена неотрицательна",
            "type": "negative_price",
            "columns": ["Price"],
        },
        {
            "name": "Прибыль не выше выручки",
            "type": "profit_revenue",
            "columns": ["Revenue", "Profit"],
        },
    ]
}


def _source() -> pd.DataFrame:
    return pd.DataFrame({
        "Country": ["A", "A", "A", "B", "B"],
        "Year": [2020, 2022, 2021, 2020, 2021],
        "Price": [10.0, -5.0, 20.0, 30.0, 40.0],
        "Revenue": [100.0, 50.0, 100.0, 80.0, 90.0],
        "Profit": [50.0, 40.0, 120.0, 30.0, 40.0],
    })


def test_profile_reuses_one_evaluator_for_chronology_and_business_rules():
    profile = profile_consistency(_source(), RULES)

    assert [item["applicable"] for item in profile] == [True, True, True]
    assert [item["invalid_count"] for item in profile] == [1, 1, 1]
    assert profile[0]["checked_count"] == 3
    assert profile[0]["affected_rows"] == 2
    assert profile[0]["group_column"] == "Country"
    assert profile[1]["columns"] == ["Price"]

    legacy = validate_consistency(_source(), RULES)
    assert [item["Нарушений"] for item in legacy] == [1, 1, 1]
    assert int(legacy[0]["mask"].sum()) == 2


def test_missing_or_unsupported_rule_is_not_reported_as_a_false_pass():
    profile = profile_consistency(_source(), {
        "consistency": [
            {"name": "Нет колонки", "type": "chronology", "columns": ["Missing"]},
            {"name": "Неизвестный алгоритм", "type": "mystery", "columns": ["Price"]},
        ]
    })

    assert all(item["applicable"] is False for item in profile)
    assert all(item["invalid_count"] is None for item in profile)
    assert all(item["applicability_message"] for item in profile)
    assert validate_consistency(_source(), {"consistency": [{"type": "mystery"}]}) == []


def test_typed_comparison_rule_checks_only_rows_with_both_values():
    source = _source()
    source.loc[0, "Profit"] = None
    profile = profile_consistency(source, {"consistency": [{
        "name": "Прибыль не выше выручки",
        "type": "comparison",
        "columns": ["Profit", "Revenue"],
        "operator": "<=",
    }]})

    assert profile[0]["applicable"] is True
    assert profile[0]["checked_count"] == 4
    assert profile[0]["invalid_count"] == 1


def test_sort_preview_is_group_aware_and_does_not_mutate_source():
    source = _source()
    chronology_only = {"consistency": [RULES["consistency"][0]]}

    corrected, results, rows_removed = preview_consistency_corrections(
        source, chronology_only, [0], "sort_chronology"
    )

    assert source["Year"].tolist() == [2020, 2022, 2021, 2020, 2021]
    assert corrected["Year"].tolist() == [2020, 2021, 2022, 2020, 2021]
    assert corrected["Country"].tolist() == ["A", "A", "A", "B", "B"]
    assert results[0]["invalid_count"] == 1
    assert results[0]["still_invalid"] == 0
    assert rows_removed == 0


def test_drop_rows_uses_union_and_flag_preserves_values():
    source = _source()

    dropped, results, rows_removed = preview_consistency_corrections(
        source, RULES, [1, 2], "drop_rows"
    )
    assert rows_removed == 2
    assert len(dropped) == 3
    assert [item["invalid_count"] for item in results] == [1, 1]

    flagged, flag_results, _ = preview_consistency_corrections(
        source, RULES, [1], "flag"
    )
    assert flagged["Price"].equals(source["Price"])
    assert flag_results[0]["flag_column"] in flagged.columns
    assert flagged[flag_results[0]["flag_column"]].tolist() == [True, False, True, True, True]
    assert flag_results[0]["still_invalid"] == 1


def test_sort_rejects_non_chronology_rules():
    with pytest.raises(ValueError, match="только к правилам хронологии"):
        preview_consistency_corrections(_source(), RULES, [1], "sort_chronology")
