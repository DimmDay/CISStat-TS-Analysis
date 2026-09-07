"""Task 125 -- TBATS production vertical slice: adapter contract tests."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from apps.api.backtesting import build_backtest_plan, run_backtest_plan
from apps.api.model_execution import MODEL_EXECUTION_REGISTRY, ModelExecutionRequest
from apps.api.model_impls.tbats import (
    _TREND_SPECS,
    _resolve_seasonal_periods,
    _tbats_fit_predict,
)


def _monthly_series(n: int = 60) -> list[float]:
    return [
        100.0 + 0.5 * step + 8.0 * math.sin(2.0 * math.pi * step / 12.0)
        for step in range(n)
    ]


def test_fit_predict_returns_forecast_and_intervals_of_exact_horizon():
    values = _monthly_series(60)

    forecast, lower, upper = _tbats_fit_predict(
        y_train=values[:54], horizon=6, seasonal_period=12,
    )

    assert len(forecast) == len(lower) == len(upper) == 6
    assert all(math.isfinite(value) for value in forecast)
    assert all(lo <= point <= hi for lo, point, hi in zip(lower, forecast, upper))


def test_multiple_seasonal_periods_from_spectral_handoff_are_used_natively():
    values = _monthly_series(72)

    forecast, _lower, _upper = _tbats_fit_predict(
        y_train=values[:66], horizon=6, seasonal_period=12,
        seasonal_periods=[6, 12],
    )

    assert len(forecast) == 6
    assert all(math.isfinite(value) for value in forecast)


def test_resolve_seasonal_periods_falls_back_to_singular_when_no_list_given():
    assert _resolve_seasonal_periods(12, None) == [12]
    assert _resolve_seasonal_periods(12, []) == [12]
    assert _resolve_seasonal_periods(12, [7, 365]) == [7, 365]


def test_resolve_seasonal_periods_rejects_non_positive_values():
    with pytest.raises(ValueError, match="положительными"):
        _resolve_seasonal_periods(12, [7, 0])


def test_unsupported_trend_spec_is_rejected():
    values = _monthly_series(48)

    with pytest.raises(ValueError, match="trend_spec"):
        _tbats_fit_predict(
            y_train=values[:42], horizon=6, seasonal_period=12,
            trend_spec="exotic",
        )


@pytest.mark.parametrize("trend_spec", sorted(_TREND_SPECS))
def test_every_bounded_trend_spec_produces_a_distinct_valid_model(trend_spec):
    """Task 125: damped-without-trend is structurally invalid in TBATS
    (raises ValueError upstream) -- trend_spec must never expose that
    combination, so every one of its 3 values must fit cleanly."""
    values = _monthly_series(48)

    forecast, _lower, _upper = _tbats_fit_predict(
        y_train=values[:42], horizon=6, seasonal_period=12, trend_spec=trend_spec,
    )

    assert len(forecast) == 6
    assert all(math.isfinite(value) for value in forecast)


def test_registry_descriptor_declares_tbats_as_tunable_with_intervals():
    descriptor = MODEL_EXECUTION_REGISTRY.describe("tbats")

    assert descriptor["model_id"] == "tbats"
    assert descriptor["family_id"] == "structural"
    assert descriptor["input_kind"] == "univariate"
    assert descriptor["supports_prediction_intervals"] is True
    assert set(descriptor["actions"]) == {"backtest", "tune", "diagnostics"}
    assert descriptor["dependency_group"] == "classical"
    assert descriptor["runtime_available"] is True


def test_registry_execute_reads_seasonal_periods_from_params():
    values = _monthly_series(72)
    result = MODEL_EXECUTION_REGISTRY.execute("tbats", ModelExecutionRequest(
        target=values[:66], horizon=6, seasonal_period=12,
        params={"tbats_seasonal_periods": [6, 12], "use_boxcox": True, "trend_spec": "trend"},
    ))

    assert len(result.forecast) == 6
    assert result.lower_interval is not None and result.upper_interval is not None
    assert all(
        lower <= point <= upper
        for lower, point, upper in zip(result.lower_interval, result.forecast, result.upper_interval)
    )


def test_tbats_runs_through_the_real_eda_backtest_plan_with_multi_period_handoff():
    """Task 125, п.2+5: сквозная передача полного списка периодов через
    run_backtest_plan (не только singular seasonal_period)."""
    values = _monthly_series(72)
    validation = {
        "strategy": "expanding", "horizon": 3, "n_splits": 2, "gap": 0,
        "folds": [
            {"fold": 1, "train_start": 0, "train_end": 65, "gap_size": 0, "test_start": 66, "test_end": 68},
            {"fold": 2, "train_start": 0, "train_end": 68, "gap_size": 0, "test_start": 69, "test_end": 71},
        ],
    }
    plan = build_backtest_plan(
        validation, n_observations=len(values), fingerprint="tbats-cohort",
        target_column="value", seasonal_period=12,
    )
    dates = pd.date_range("2019-01-01", periods=len(values), freq="MS")

    result = run_backtest_plan(
        model_id="tbats", model_name="TBATS", family_id="structural",
        series=values, labels=[value.isoformat() for value in dates],
        plan=plan, seasonal_period=12, seasonal_periods=[6, 12],
    )

    assert result["status"] == "success"
    assert len(result["oof_predictions"]) == 6
    assert result["execution_contract"]["model_id"] == "tbats"


def test_seasonal_periods_plumbing_does_not_collide_with_ets_override_key():
    """Regression: run_backtest_plan's seasonal_periods pass-through must use
    a distinct params key ("tbats_seasonal_periods"), not "seasonal_periods" --
    that key was already claimed, pre-Task-125, by the ETS executor as a
    single-value seasonal_period override (see model_execution.py).
    Reusing it here would silently corrupt every ETS backtest whenever the
    session router forwards the spectral hand-off (which it always does).
    """
    values = _monthly_series(48)
    result = run_backtest_plan(
        model_id="ets", model_name="ETS", family_id="exponential_smoothing",
        series=values, labels=[str(index) for index in range(len(values))],
        plan=build_backtest_plan(
            {
                "strategy": "expanding", "horizon": 3, "n_splits": 1, "gap": 0,
                "folds": [{"fold": 1, "train_start": 0, "train_end": 44, "gap_size": 0, "test_start": 45, "test_end": 47}],
            },
            n_observations=len(values), fingerprint="ets-vs-tbats-periods", target_column="value",
            seasonal_period=12,
        ),
        seasonal_period=12, seasonal_periods=[6, 12],
    )

    assert result["status"] == "success"


def test_tbats_bounded_tuning_param_space_grid_size_is_within_max_trials():
    from src.catalog.modeling_spec_loader import ModelingSpec

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    tbats_model = next(
        model
        for family in spec.families
        for model in family.models
        if model.id == "tbats"
    )

    assert tbats_model.param_space is not None
    grid_size = math.prod(len(values) for values in tbats_model.param_space.values())
    assert grid_size <= 64
    assert set(tbats_model.param_space) == {"use_boxcox", "trend_spec"}
