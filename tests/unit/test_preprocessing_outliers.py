from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.preprocessing.outliers import (
    detect_outlier_mask,
    outliers_summary,
    profile_outliers,
)


def _series(values):
    return pd.Series(values, dtype=float)


def test_iqr_detects_extreme_values():
    values = [10.0] * 20 + [1000.0]
    mask = detect_outlier_mask(_series(values), "iqr", 1.5)
    assert mask.iloc[-1]
    assert not mask.iloc[:-1].any()


def test_zscore_detects_extreme_values():
    rng = np.random.default_rng(42)
    values = list(rng.normal(0, 1, 100)) + [50.0]
    mask = detect_outlier_mask(_series(values), "zscore", 3.0)
    assert mask.iloc[-1]


def test_mad_detects_extreme_values_even_with_skew():
    values = list(range(1, 31)) + [500.0]  # разброс достаточен, чтобы MAD > 0
    mask = detect_outlier_mask(_series(values), "mad", 3.5)
    assert mask.iloc[-1]


def test_percentile_uses_explicit_bounds():
    values = list(range(1, 101))  # 1..100
    mask = detect_outlier_mask(_series([float(v) for v in values]), "percentile", (5.0, 95.0))
    assert mask.sum() > 0
    assert mask.iloc[0]  # значение 1 -- ниже 5-го процентиля
    assert mask.iloc[-1]  # значение 100 -- выше 95-го процентиля


def test_returns_all_false_for_small_sample():
    mask = detect_outlier_mask(_series([1.0, 2.0, 1000.0]), "iqr", 1.5)
    assert not mask.any()


def test_zscore_returns_all_false_when_std_is_zero():
    mask = detect_outlier_mask(_series([5.0] * 15), "zscore", 3.0)
    assert not mask.any()


def test_rejects_unknown_method():
    with pytest.raises(ValueError, match="Неподдерживаемый метод"):
        detect_outlier_mask(_series([1.0] * 15), "bogus", None)


def test_recommends_mad_for_extreme_skew():
    values = [1.0] * 150 + [10_000.0]  # экстремальная асимметрия, большая выборка
    profiles = profile_outliers(pd.DataFrame({"Price": values}), method="iqr")
    assert profiles[0]["recommended_method"] == "mad"


def test_recommends_iqr_for_small_sample():
    values = [1.0] * 20 + [50.0]
    profiles = profile_outliers(pd.DataFrame({"Price": values}), method="iqr")
    assert profiles[0]["recommended_method"] == "iqr"


def test_profile_includes_every_numeric_column_including_zero_outliers():
    df = pd.DataFrame({
        "Clean": list(range(1, 21)),
        "Region": ["A"] * 20,  # нечисловая -- не входит в профиль
    })
    profiles = profile_outliers(df, method="iqr")
    assert [item["column"] for item in profiles] == ["Clean"]
    assert profiles[0]["outlier_count"] == 0


def test_profile_marks_insufficient_sample_without_crashing():
    df = pd.DataFrame({"Price": [1.0, 2.0, 3.0]})
    profiles = profile_outliers(df, method="iqr")
    assert profiles[0]["insufficient_sample"] is True
    assert profiles[0]["outlier_count"] == 0
    assert profiles[0]["bounds"] is None


def test_bounds_reported_for_iqr_and_percentile_not_for_zscore_mad():
    values = list(range(1, 101))
    df = pd.DataFrame({"Price": [float(v) for v in values]})
    assert profile_outliers(df, method="iqr")[0]["bounds"] is not None
    assert profile_outliers(df, method="percentile", param=(1.0, 99.0))[0]["bounds"] is not None
    assert profile_outliers(df, method="zscore")[0]["bounds"] is None
    assert profile_outliers(df, method="mad")[0]["bounds"] is None


def test_outliers_summary_aggregates_profile():
    df = pd.DataFrame({
        "A": [10.0] * 20 + [1000.0],
        "B": list(range(1, 22)),
    })
    profiles = profile_outliers(df, method="iqr")
    summary = outliers_summary(profiles, total_rows=len(df))
    assert summary["total_outliers"] == 1
    assert summary["affected_columns"] == ["A"]
    assert summary["total_numeric_columns"] == 2
