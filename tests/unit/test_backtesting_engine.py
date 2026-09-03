from __future__ import annotations

import math

import pytest

from apps.api.backtesting import (
    BacktestExecutionError,
    build_backtest_plan,
    compute_backtest_metrics,
    fixed_origin_baseline_predict,
    run_backtest_plan,
    validate_target_preprocessing,
)


def _validation() -> dict:
    return {
        "strategy": "expanding",
        "horizon": 2,
        "n_splits": 2,
        "gap": 1,
        "folds": [
            {
                "fold": 1,
                "train_start": 0,
                "train_end": 3,
                "gap_start": 4,
                "gap_end": 4,
                "gap_size": 1,
                "test_start": 5,
                "test_end": 6,
                "train_start_label": "t0",
                "train_end_label": "t3",
                "test_start_label": "t5",
                "test_end_label": "t6",
            },
            {
                "fold": 2,
                "train_start": 0,
                "train_end": 5,
                "gap_start": 6,
                "gap_end": 6,
                "gap_size": 1,
                "test_start": 7,
                "test_end": 8,
                "train_start_label": "t0",
                "train_end_label": "t5",
                "test_start_label": "t7",
                "test_end_label": "t8",
            },
        ],
    }


def test_plan_uses_exact_eda_fold_boundaries_and_stable_cohort():
    first = build_backtest_plan(
        _validation(), n_observations=9, fingerprint="fp", target_column="value", seasonal_period=1,
    )
    second = build_backtest_plan(
        _validation(), n_observations=9, fingerprint="fp", target_column="value", seasonal_period=1,
    )
    different_metric_scale = build_backtest_plan(
        _validation(), n_observations=9, fingerprint="fp", target_column="value", seasonal_period=2,
    )

    assert first.cohort_id == second.cohort_id
    assert first.cohort_id != different_metric_scale.cohort_id
    different_preprocessing = build_backtest_plan(
        _validation(), n_observations=9, fingerprint="fp", target_column="value",
        seasonal_period=1, preprocessing_signature="scaled-standard",
    )
    assert first.cohort_id != different_preprocessing.cohort_id
    assert first.strategy == "expanding"
    assert [(fold.train_indices, fold.test_indices) for fold in first.folds] == [
        (list(range(0, 4)), [5, 6]),
        (list(range(0, 6)), [7, 8]),
    ]
    assert all(max(fold.train_indices) < min(fold.test_indices) for fold in first.folds)


def test_naive_is_fixed_origin_and_never_reads_test_observations():
    assert fixed_origin_baseline_predict("naive", [1.0, 2.0, 3.0], 3, 1) == [3.0, 3.0, 3.0]


def test_seasonal_naive_recurses_without_reading_test_when_horizon_exceeds_period():
    prediction = fixed_origin_baseline_predict(
        "seasonal_naive", [1.0, 2.0, 3.0, 4.0], horizon=6, seasonal_period=4,
    )
    assert prediction == [1.0, 2.0, 3.0, 4.0, 1.0, 2.0]


def test_mase_uses_train_only_seasonal_scaling_denominator():
    metrics = compute_backtest_metrics(
        y_true=[10.0, 12.0], y_pred=[8.0, 11.0],
        y_train=[1.0, 2.0, 2.0, 4.0], seasonal_period=2,
    )
    assert metrics.mae == 1.5
    assert metrics.mase == 1.0
    assert metrics.weighted_score is None


def test_failed_model_is_never_silently_relabelled_as_naive():
    plan = build_backtest_plan(
        {**_validation(), "n_splits": 1, "folds": _validation()["folds"][1:]},
        n_observations=9, fingerprint="fp", target_column="value", seasonal_period=1,
    )

    def fail(_train, _horizon, _period, _params):
        raise ValueError("fit failed")

    with pytest.raises(BacktestExecutionError, match="fit failed"):
        run_backtest_plan(
            model_id="broken", model_name="Broken", family_id="test",
            series=[float(value) for value in range(9)],
            labels=[f"t{value}" for value in range(9)],
            plan=plan, seasonal_period=1, predictors={"broken": fail},
        )


def test_gap_steps_are_forecast_but_excluded_from_oof_scoring():
    plan = build_backtest_plan(
        {**_validation(), "n_splits": 1, "folds": _validation()["folds"][1:]},
        n_observations=9, fingerprint="fp", target_column="value", seasonal_period=1,
    )
    requested_horizons = []

    def step_predictor(_train, horizon, _period, _params):
        requested_horizons.append(horizon)
        return [float(step) for step in range(1, horizon + 1)]

    result = run_backtest_plan(
        model_id="steps", model_name="Steps", family_id="test",
        series=[float(value) for value in range(9)], labels=[f"t{value}" for value in range(9)],
        plan=plan, seasonal_period=1, predictors={"steps": step_predictor},
    )

    assert requested_horizons == [3]
    assert [point["predicted"] for point in result["oof_predictions"]] == [2.0, 3.0]


def test_run_persists_oof_predictions_and_fold_residuals():
    plan = build_backtest_plan(
        _validation(), n_observations=9, fingerprint="fp", target_column="value", seasonal_period=1,
    )
    result = run_backtest_plan(
        model_id="naive", model_name="Naive", family_id="baselines",
        series=[float(value) for value in range(9)],
        labels=[f"t{value}" for value in range(9)],
        plan=plan, seasonal_period=1,
    )

    assert result["status"] == "success"
    assert result["n_folds"] == 2
    assert len(result["folds"]) == 2
    assert len(result["oof_predictions"]) == 4
    assert [point["index"] for point in result["oof_predictions"]] == [5, 6, 7, 8]
    assert all(point["residual"] == point["actual"] - point["predicted"] for point in result["oof_predictions"])


@pytest.mark.parametrize(
    "metadata",
    [
        {"kind": "smoothing", "method": "lowess", "modeling_safe": False},
        {"kind": "stationarity", "method": "linear_detrend", "modeling_safe": False},
        {"method": "box_cox", "fitted_on_n": 96, "lambda_value": 0.2},
    ],
)
def test_full_history_target_transform_is_rejected_until_fold_refit_exists(metadata):
    with pytest.raises(BacktestExecutionError, match="train fold"):
        validate_target_preprocessing({"target_derived": metadata}, "target_derived")


def test_all_nine_production_models_execute_the_same_real_oof_cohort():
    from apps.api.model_readiness import PRODUCTION_BACKTEST_MODEL_IDS

    series = [100 + 0.3 * step + 5 * math.sin(2 * math.pi * step / 12) for step in range(72)]
    validation = {
        "strategy": "expanding", "horizon": 3, "n_splits": 2, "gap": 0,
        "folds": [
            {"fold": 1, "train_start": 0, "train_end": 65, "gap_size": 0, "test_start": 66, "test_end": 68},
            {"fold": 2, "train_start": 0, "train_end": 68, "gap_size": 0, "test_start": 69, "test_end": 71},
        ],
    }
    plan = build_backtest_plan(
        validation, n_observations=len(series), fingerprint="real-series", target_column="value",
        seasonal_period=12,
    )

    results = {
        model_id: run_backtest_plan(
            model_id=model_id, model_name=model_id, family_id="test",
            series=series, labels=[str(index) for index in range(len(series))],
            plan=plan, seasonal_period=12,
        )
        for model_id in PRODUCTION_BACKTEST_MODEL_IDS
    }

    assert len(results) == 9
    assert {result["cohort_id"] for result in results.values()} == {plan.cohort_id}
    assert all(len(result["oof_predictions"]) == 6 for result in results.values())
    assert all(result["metrics"]["weighted_score"] is None for result in results.values())
