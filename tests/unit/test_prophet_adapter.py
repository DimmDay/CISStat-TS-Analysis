"""Task 124 -- Prophet production vertical slice: adapter contract tests."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from apps.api.backtesting import build_backtest_plan, run_backtest_plan
from apps.api.model_execution import (
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionContractError,
    ModelExecutionRequest,
)
from apps.api.model_impls.prophet import (
    SUPPORTED_COUNTRY_HOLIDAYS,
    _prophet_fit_predict,
)


def _monthly_series(n: int = 48) -> tuple[list[float], list[str]]:
    values = [
        100.0 + 0.5 * step + 8.0 * math.sin(2.0 * math.pi * step / 12.0)
        for step in range(n)
    ]
    dates = pd.date_range("2019-01-01", periods=n, freq="MS")
    return values, [value.isoformat() for value in dates]


def test_fit_predict_returns_forecast_and_intervals_of_exact_horizon():
    values, timestamps = _monthly_series(48)
    train_timestamps = timestamps[:42]
    future_timestamps = timestamps[42:]

    forecast, lower, upper = _prophet_fit_predict(
        y_train=values[:42], horizon=6,
        train_timestamps=train_timestamps, future_timestamps=future_timestamps,
    )

    assert len(forecast) == len(lower) == len(upper) == 6
    assert all(math.isfinite(value) for value in forecast)
    assert all(lo <= point <= hi for lo, point, hi in zip(lower, forecast, upper))


def test_multiplicative_seasonality_requires_strictly_positive_series():
    values, timestamps = _monthly_series(36)
    values[10] = -1.0

    with pytest.raises(ValueError, match="strictly positive"):
        _prophet_fit_predict(
            y_train=values[:30], horizon=6,
            train_timestamps=timestamps[:30], future_timestamps=timestamps[30:36],
            seasonality_mode="multiplicative",
        )


def test_unsupported_country_holidays_is_rejected():
    values, timestamps = _monthly_series(36)

    with pytest.raises(ValueError, match="country_holidays"):
        _prophet_fit_predict(
            y_train=values[:30], horizon=6,
            train_timestamps=timestamps[:30], future_timestamps=timestamps[30:36],
            country_holidays="ZZ",
        )


def test_supported_country_holidays_fold_local_no_leakage_by_construction():
    """Each call builds a fresh Prophet instance -- no cross-fold reuse."""
    assert "RU" in SUPPORTED_COUNTRY_HOLIDAYS
    values, timestamps = _monthly_series(48)

    forecast, _lower, _upper = _prophet_fit_predict(
        y_train=values[:42], horizon=6,
        train_timestamps=timestamps[:42], future_timestamps=timestamps[42:],
        country_holidays="RU",
    )

    assert len(forecast) == 6
    assert all(math.isfinite(value) for value in forecast)


def test_timestamp_length_mismatch_is_rejected():
    values, timestamps = _monthly_series(36)

    with pytest.raises(ValueError, match="train_timestamp"):
        _prophet_fit_predict(
            y_train=values[:30], horizon=6,
            train_timestamps=timestamps[:29], future_timestamps=timestamps[30:36],
        )
    with pytest.raises(ValueError, match="future_timestamps"):
        _prophet_fit_predict(
            y_train=values[:30], horizon=6,
            train_timestamps=timestamps[:30], future_timestamps=timestamps[30:35],
        )


def test_registry_descriptor_declares_prophet_as_tunable_with_intervals():
    descriptor = MODEL_EXECUTION_REGISTRY.describe("prophet")

    assert descriptor["model_id"] == "prophet"
    assert descriptor["family_id"] == "structural"
    assert descriptor["input_kind"] == "univariate"
    assert descriptor["supports_prediction_intervals"] is True
    assert set(descriptor["actions"]) == {"backtest", "tune", "diagnostics"}
    assert descriptor["dependency_group"] == "classical"
    assert descriptor["runtime_available"] is True


def test_registry_execute_requires_train_and_future_timestamps():
    with pytest.raises(ModelExecutionContractError, match="train_timestamps"):
        MODEL_EXECUTION_REGISTRY.execute("prophet", ModelExecutionRequest(
            target=[1.0, 2.0, 3.0], horizon=2,
        ))


def test_registry_execute_produces_prediction_interval_containing_point_forecast():
    values, timestamps = _monthly_series(48)
    result = MODEL_EXECUTION_REGISTRY.execute("prophet", ModelExecutionRequest(
        target=values[:42], horizon=6,
        train_timestamps=timestamps[:42], future_timestamps=timestamps[42:],
    ))

    assert len(result.forecast) == 6
    assert result.lower_interval is not None and result.upper_interval is not None
    assert all(
        lower <= point <= upper
        for lower, point, upper in zip(result.lower_interval, result.forecast, result.upper_interval)
    )


def test_prophet_runs_through_the_real_eda_backtest_plan_with_real_dates():
    values, timestamps = _monthly_series(60)
    validation = {
        "strategy": "expanding", "horizon": 3, "n_splits": 2, "gap": 0,
        "folds": [
            {"fold": 1, "train_start": 0, "train_end": 53, "gap_size": 0, "test_start": 54, "test_end": 56},
            {"fold": 2, "train_start": 0, "train_end": 56, "gap_size": 0, "test_start": 57, "test_end": 59},
        ],
    }
    plan = build_backtest_plan(
        validation, n_observations=len(values), fingerprint="prophet-cohort",
        target_column="value", seasonal_period=12,
    )

    result = run_backtest_plan(
        model_id="prophet", model_name="Prophet", family_id="structural",
        series=values, labels=timestamps, plan=plan, seasonal_period=12,
    )

    assert result["status"] == "success"
    assert len(result["oof_predictions"]) == 6
    assert result["execution_contract"]["model_id"] == "prophet"


def test_prophet_bounded_tuning_param_space_grid_size_is_within_max_trials():
    from src.catalog.modeling_spec_loader import ModelingSpec

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    prophet_model = next(
        model
        for family in spec.families
        for model in family.models
        if model.id == "prophet"
    )

    assert prophet_model.param_space is not None
    grid_size = math.prod(len(values) for values in prophet_model.param_space.values())
    assert grid_size <= 64
    assert set(prophet_model.param_space) == {
        "changepoint_prior_scale", "seasonality_prior_scale", "seasonality_mode",
    }
