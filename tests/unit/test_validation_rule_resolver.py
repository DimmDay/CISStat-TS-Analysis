from __future__ import annotations

import pandas as pd

from validation.rule_resolver import resolve_validation_rules


def _fao_df() -> pd.DataFrame:
    return pd.DataFrame({
        "Country": ["Азербайджан", "Беларусь", "Казахстан"],
        "Year": [2022, 2023, 2024],
        "Price": [10.5, 11.0, 12.25],
        "usd/tonne": ["usd", "usd", "usd"],
    })


def test_system_rules_infer_a_complete_type_schema_without_user_setup():
    rules, sources = resolve_validation_rules(_fao_df())

    columns = rules["schema"]["columns"]
    assert {name: spec["type"] for name, spec in columns.items()} == {
        "Country": "string",
        "Year": "integer",
        "Price": "float",
        "usd/tonne": "string",
    }
    assert sources["data_types"] == "system"
    assert rules["inclusion"] == {}
    assert sources["inclusion"] == "not_applicable"


def test_template_overrides_system_rules_but_keeps_missing_system_defaults():
    rules, sources = resolve_validation_rules(_fao_df(), template_id="fao_prices")

    assert rules["schema"]["columns"]["Price"]["nullable"] is False
    assert rules["schema"]["columns"]["usd/tonne"]["type"] == "string"
    assert rules["uniqueness"]["composite_key"] == ["Country", "Year"]
    assert sources["data_types"] == "template"
    assert sources["uniqueness"] == "template"
    assert sources["formats"] == "template"
    assert set(rules["formats"]) == {"Country", "Year", "usd/tonne"}
    assert sources["text_quality"] == "system"


def test_session_type_schema_has_highest_priority():
    rules, sources = resolve_validation_rules(
        _fao_df(),
        template_id="fao_prices",
        type_schema={"Price": "integer"},
    )

    assert rules["schema"]["columns"]["Price"]["type"] == "integer"
    assert sources["data_types"] == "session"
