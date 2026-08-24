from __future__ import annotations

import pandas as pd

from apps.api.type_conversion import preview_type_conversions


def test_numeric_preview_reports_invalid_values_without_mutating_source():
    source = pd.DataFrame({"amount": ["10.5", "bad", "30"]})

    converted, results = preview_type_conversions(
        source,
        [{"column": "amount", "target_type": "float"}],
    )

    assert source["amount"].dtype == object
    assert str(converted["amount"].dtype) == "Float64"
    assert converted["amount"].isna().sum() == 1
    assert results == [{
        "column": "amount",
        "from_dtype": "object",
        "to_dtype": "Float64",
        "converted_count": 2,
        "invalid_count": 1,
        "invalid_examples": ["bad"],
    }]


def test_integer_preview_treats_fractional_values_as_invalid():
    source = pd.DataFrame({"count": ["1", "2.5", "3"]})
    converted, results = preview_type_conversions(
        source,
        [{"column": "count", "target_type": "integer"}],
    )

    assert str(converted["count"].dtype) == "Int64"
    assert converted["count"].tolist() == [1, pd.NA, 3]
    assert results[0]["invalid_count"] == 1
    assert results[0]["invalid_examples"] == ["2.5"]


def test_datetime_preview_reuses_smart_year_conversion():
    source = pd.DataFrame({"Year": [2020, 2021, 2022]})
    converted, results = preview_type_conversions(
        source,
        [{"column": "Year", "target_type": "datetime"}],
    )

    assert pd.api.types.is_datetime64_any_dtype(converted["Year"])
    assert converted["Year"].dt.year.tolist() == [2020, 2021, 2022]
    assert results[0]["invalid_count"] == 0


def test_boolean_preview_uses_explicit_tokens_not_python_truthiness():
    source = pd.DataFrame({"active": ["true", "Нет", "1", "unknown"]})
    converted, results = preview_type_conversions(
        source,
        [{"column": "active", "target_type": "boolean"}],
    )

    assert str(converted["active"].dtype) == "boolean"
    assert converted["active"].tolist() == [True, False, True, pd.NA]
    assert results[0]["invalid_examples"] == ["unknown"]
