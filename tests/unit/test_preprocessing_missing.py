from __future__ import annotations

import pandas as pd
import pytest

from app.preprocessing.missing import (
    missing_correlation,
    missing_distribution_comparison,
    missing_matrix,
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


# ── missing_matrix ──


def test_missing_matrix_reports_share_per_bin_and_column():
    df = pd.DataFrame({
        "A": [None, None, 1.0, 1.0],
        "B": [1.0, 1.0, 1.0, None],
    })
    result = missing_matrix(df, max_bins=4)  # по бину на строку
    assert result["columns"] == ["A", "B"]
    assert len(result["bins"]) == 4
    assert result["bins"][0]["missing_share"] == {"A": 1.0, "B": 0.0}
    assert result["bins"][3]["missing_share"] == {"A": 0.0, "B": 1.0}


def test_missing_matrix_bins_preserve_short_gaps_within_a_bin():
    # Один короткий провал (строка 2) внутри бина из 4 строк не должен
    # пропасть при биновании -- доля должна быть ненулевой для колонки A.
    df = pd.DataFrame({"A": [1.0, 1.0, None, 1.0]})
    result = missing_matrix(df, max_bins=1)
    assert result["bins"][0]["missing_share"]["A"] == pytest.approx(0.25)


def test_missing_matrix_empty_dataframe():
    result = missing_matrix(pd.DataFrame())
    assert result["bins"] == []
    assert result["total_rows"] == 0


# ── missing_correlation ──


def test_missing_correlation_detects_joint_missingness():
    # A и B пропускают ОДНОВРЕМЕННО (индексы 1 и 3) -- корреляция должна
    # быть высокой положительной.
    df = pd.DataFrame({
        "A": [1.0, None, 3.0, None],
        "B": [1.0, None, 3.0, None],
        "C": [1.0, 2.0, 3.0, 4.0],  # без пропусков вовсе
    })
    result = missing_correlation(df)
    assert result["columns"] == ["A", "B"]  # C исключена (нет вариативности -- 0% пропусков)
    a_idx, b_idx = result["columns"].index("A"), result["columns"].index("B")
    assert result["matrix"][a_idx][b_idx] == pytest.approx(1.0)


def test_missing_correlation_returns_empty_when_fewer_than_two_varying_columns():
    df = pd.DataFrame({"A": [1.0, None, 3.0], "B": [1.0, 2.0, 3.0]})
    result = missing_correlation(df)
    assert result["columns"] == []
    assert result["matrix"] == []


# ── missing_distribution_comparison ──


def test_distribution_comparison_reports_five_number_summary_per_group():
    df = pd.DataFrame({
        "Price": [10.0, 20.0, 500.0, 600.0],
        "Region": ["A", "B", None, None],
    })
    result = missing_distribution_comparison(df, value_column="Price", indicator_column="Region")
    assert result["with_missing"]["count"] == 2
    assert result["with_missing"]["median"] == pytest.approx(550.0)
    assert result["without_missing"]["count"] == 2
    assert result["without_missing"]["median"] == pytest.approx(15.0)


def test_distribution_comparison_rejects_non_numeric_value_column():
    df = pd.DataFrame({"Region": ["A", "B"], "Other": [None, "x"]})
    with pytest.raises(ValueError, match="должна быть числовой"):
        missing_distribution_comparison(df, value_column="Region", indicator_column="Other")


def test_distribution_comparison_rejects_same_column_twice():
    df = pd.DataFrame({"Price": [1.0, None]})
    with pytest.raises(ValueError, match="должны различаться"):
        missing_distribution_comparison(df, value_column="Price", indicator_column="Price")


def test_distribution_comparison_rejects_unknown_column():
    df = pd.DataFrame({"Price": [1.0, None]})
    with pytest.raises(ValueError, match="отсутствует в датасете"):
        missing_distribution_comparison(df, value_column="Price", indicator_column="Nope")


def test_distribution_comparison_group_is_none_when_no_valid_values():
    df = pd.DataFrame({"Price": [float("nan"), float("nan")], "Region": ["A", None]})
    result = missing_distribution_comparison(df, value_column="Price", indicator_column="Region")
    assert result["with_missing"] is None
    assert result["without_missing"] is None
