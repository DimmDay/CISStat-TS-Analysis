import pandas as pd
import pytest

from apps.api.format_correction import preview_format_corrections


RULES = {
    "formats": {
        "Email": {"pattern": r"^[^@\s]+@[^@\s]+\.[^@\s]+$", "threshold": 100},
    }
}


def test_preview_replaces_only_invalid_non_null_values_without_mutating_source():
    source = pd.DataFrame({"Email": ["ok@example.com", "broken", None]})

    corrected, results = preview_format_corrections(
        source, RULES, ["Email"], "replace_null"
    )

    assert source["Email"].tolist() == ["ok@example.com", "broken", None]
    assert corrected["Email"].isna().tolist() == [False, True, True]
    assert results[0]["invalid_count"] == 1
    assert results[0]["changed_count"] == 1
    assert results[0]["still_invalid"] == 0


def test_normalization_rechecks_values_against_the_same_rule():
    source = pd.DataFrame({"Email": [" USER@EXAMPLE.COM ", "broken value"]})

    corrected, results = preview_format_corrections(
        source, RULES, ["Email"], "normalize"
    )

    assert corrected["Email"].tolist() == ["user@example.com", "broken value"]
    assert results[0]["changed_count"] == 1
    assert results[0]["still_invalid"] == 1


def test_flag_strategy_preserves_values_and_adds_boolean_validity_column():
    source = pd.DataFrame({"Email": ["ok@example.com", "broken", None]})

    corrected, results = preview_format_corrections(source, RULES, ["Email"], "flag")

    assert corrected["Email"].equals(source["Email"])
    assert corrected["Email_format_valid"].tolist() == [True, False, True]
    assert results[0]["flag_column"] == "Email_format_valid"
    assert results[0]["changed_count"] == 0


def test_smart_replacement_uses_valid_median_for_numeric_column():
    rules = {"formats": {"Year": {"pattern": r"^20\d{2}$", "threshold": 100}}}
    source = pd.DataFrame({"Year": [2020, 2021, 999]})

    corrected, results = preview_format_corrections(source, rules, ["Year"], "smart_replace")

    assert corrected["Year"].tolist() == [2020, 2021, 2020]
    assert results[0]["still_invalid"] == 0


def test_rejects_string_normalization_for_numeric_column():
    rules = {"formats": {"Year": {"pattern": r"^20\d{2}$", "threshold": 100}}}
    with pytest.raises(ValueError, match="нормализация строк неприменима"):
        preview_format_corrections(
            pd.DataFrame({"Year": [2020, 999]}), rules, ["Year"], "normalize"
        )


def test_rejects_columns_without_an_active_format_rule():
    with pytest.raises(ValueError, match="нет активного правила формата"):
        preview_format_corrections(
            pd.DataFrame({"Other": ["x"]}), RULES, ["Other"], "flag"
        )
