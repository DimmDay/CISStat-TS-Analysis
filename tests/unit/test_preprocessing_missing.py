from __future__ import annotations

import pandas as pd

from app.preprocessing.missing import (
    missing_per_row_histogram,
    missing_summary,
    profile_missing,
)


def test_profile_includes_every_column_including_zero_missing():
    df = pd.DataFrame({
        "Price": [10.0, None, 30.0, None],
        "Region": ["A", "B", None, "A"],
    })

    profile = profile_missing(df)

    assert [item["column"] for item in profile] == ["Price", "Region"]
    price = profile[0]
    assert price["missing_count"] == 2
    assert price["non_missing_count"] == 2
    assert price["missing_pct"] == 50.0
    assert price["semantic"] == "numeric"
    assert price["missing_examples"] == [1, 3]

    region = profile[1]
    assert region["missing_count"] == 1
    assert region["semantic"] in ("categorical", "text")


def test_profile_recommends_median_mode_for_moderate_numeric_gaps():
    # 2/10 = 20% -- между 5% и 50%, признак числовой -> "median_mode"
    df = pd.DataFrame({"Price": [1.0, 2.0, None, 4.0, 5.0, 6.0, 7.0, None, 9.0, 10.0]})
    profile = profile_missing(df)
    assert profile[0]["recommended_strategy"] == "median_mode"


def test_profile_recommends_drop_rows_for_sparse_numeric_gaps():
    # 1/100 = 1% -- < 5% -> "Обработать строки" -> drop_rows
    df = pd.DataFrame({"Price": [1.0] * 99 + [None]})
    profile = profile_missing(df)
    assert profile[0]["recommended_strategy"] == "drop_rows"


def test_profile_reports_none_when_column_has_no_missing_values():
    df = pd.DataFrame({"Price": [1.0, 2.0, 3.0]})
    profile = profile_missing(df)
    assert profile[0]["missing_count"] == 0
    assert profile[0]["missing_pct"] == 0.0
    assert profile[0]["recommended_strategy"] == "none"


def test_missing_summary_matches_manual_counts():
    df = pd.DataFrame({
        "A": [1.0, None, None],
        "B": [None, None, 3.0],
    })
    summary = missing_summary(df)
    assert summary["total_rows"] == 3
    assert summary["total_columns"] == 2
    assert summary["total_missing"] == 4
    assert summary["rows_with_missing"] == 3
    assert summary["empty_rows"] == 1  # row index 1: both A and B missing


def test_missing_summary_handles_empty_dataframe():
    summary = missing_summary(pd.DataFrame())
    assert summary["total_rows"] == 0
    assert summary["total_missing"] == 0
    assert summary["missing_rate_pct"] is None
    assert summary["rows_with_missing_pct"] is None


def test_missing_per_row_histogram_buckets_by_missing_count():
    df = pd.DataFrame({
        "A": [None, None, 1.0, 1.0],
        "B": [None, 1.0, None, 1.0],
    })
    # row0: 2 missing, row1: 1 missing, row2: 1 missing, row3: 0 missing
    histogram = missing_per_row_histogram(df)
    as_dict = {item["missing_in_row"]: item["row_count"] for item in histogram}
    assert as_dict == {1: 2, 2: 1}


def test_missing_per_row_histogram_empty_when_no_missing_values():
    df = pd.DataFrame({"A": [1.0, 2.0]})
    assert missing_per_row_histogram(df) == []
