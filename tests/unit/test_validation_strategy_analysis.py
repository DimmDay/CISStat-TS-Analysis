from __future__ import annotations

import numpy as np
import pandas as pd

from apps.api.eda_validation_strategy import build_eda_validation_strategy


def _frame(size: int = 100) -> pd.DataFrame:
    return pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=size, freq="D")[::-1],
        "Price": np.arange(size, dtype=float)[::-1],
    })


def test_expanding_plan_is_tail_anchored_and_has_no_future_leakage():
    result = build_eda_validation_strategy(
        _frame(),
        column="Price",
        strategy="expanding",
        horizon=10,
        n_splits=3,
        gap=2,
        train_window=40,
    )

    assert result["applicable"] is True
    assert result["order_source"] == "time_column"
    assert result["frequency"] == "D"
    assert result["initial_train_size"] == 68
    assert result["required_observations"] == 52
    assert len(result["folds"]) == 3
    assert result["folds"][-1]["test_end"] == 99
    for fold in result["folds"]:
        assert fold["train_end"] < fold["gap_start"] <= fold["gap_end"] < fold["test_start"]
        assert fold["train_end"] < fold["test_start"]
        assert fold["test_size"] == 10


def test_sliding_plan_uses_fixed_recent_window_and_preserves_old_history_as_unused():
    result = build_eda_validation_strategy(
        _frame(),
        column="Price",
        strategy="sliding",
        horizon=10,
        n_splits=3,
        gap=2,
        train_window=40,
    )

    assert result["applicable"] is True
    assert result["initial_train_size"] == 40
    assert result["unused_observations"] == 28
    assert [fold["train_size"] for fold in result["folds"]] == [40, 40, 40]
    assert result["folds"][0]["train_start"] == 28
    assert result["folds"][-1]["test_end"] == 99


def test_single_split_is_final_holdout_not_cross_validation():
    result = build_eda_validation_strategy(
        _frame(60),
        column="Price",
        strategy="single",
        horizon=12,
        n_splits=5,
        gap=1,
        train_window=40,
    )

    assert result["applicable"] is True
    assert result["effective_splits"] == 1
    assert result["folds"][0]["test_start"] == 48
    assert "финаль" in result["recommendation"].lower()


def test_insufficient_series_returns_explainable_profile_without_partial_folds():
    result = build_eda_validation_strategy(
        _frame(35),
        column="Price",
        strategy="expanding",
        horizon=6,
        n_splits=3,
        gap=0,
        train_window=20,
    )

    assert result["applicable"] is False
    assert result["required_observations"] == 38
    assert result["folds"] == []
    assert "38" in result["reason"]


def test_irregular_axis_keeps_observation_folds_but_marks_duration_incomparable():
    frame = _frame(80).sort_values("Date").reset_index(drop=True)
    frame = frame.drop(index=13).reset_index(drop=True)

    result = build_eda_validation_strategy(
        frame,
        column="Price",
        strategy="expanding",
        horizon=8,
        n_splits=3,
        gap=0,
        train_window=30,
    )

    assert result["applicable"] is True
    assert result["frequency"] is None
    assert result["comparable_duration"] is False
    assert any("нерегуляр" in warning.lower() for warning in result["warnings"])


def test_panel_dates_are_rejected_without_implicit_aggregation():
    dates = pd.date_range("2024-01-01", periods=40, freq="D")
    frame = pd.DataFrame({"Date": np.repeat(dates, 2), "Price": np.arange(80.0)})

    result = build_eda_validation_strategy(frame, column="Price")

    assert result["applicable"] is False
    assert "панель" in result["reason"].lower()
    assert result["folds"] == []
