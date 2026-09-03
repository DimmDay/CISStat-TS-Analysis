from __future__ import annotations

import pandas as pd
import pytest

from app.preprocessing.transforms import apply_variance_transform
from apps.api.backtesting import build_backtest_plan, run_backtest_plan
from apps.api.fold_preprocessing import prepare_modeling_target
from apps.api.modeling_tuning import execute_tuning_plan


def _sliding_plan():
    validation = {
        "strategy": "sliding",
        "horizon": 2,
        "n_splits": 2,
        "gap": 1,
        "train_window": 4,
        "folds": [
            {"fold": 1, "train_start": 0, "train_end": 3, "gap_size": 1,
             "test_start": 5, "test_end": 6},
            {"fold": 2, "train_start": 2, "train_end": 5, "gap_size": 1,
             "test_start": 7, "test_end": 8},
        ],
    }
    return build_backtest_plan(
        validation, n_observations=9, fingerprint="fp",
        target_column="value", seasonal_period=1,
    )


def test_tuning_executes_the_exact_sliding_eda_backtest_plan():
    plan = _sliding_plan()
    seen_train: list[list[float]] = []

    def predictor(train, horizon, _period, params):
        seen_train.append(list(train))
        return [train[-1] + params["offset"]] * horizon

    result = execute_tuning_plan(
        model_id="test", model_name="Test", family_id="test",
        param_space={"offset": [0.0, 1.0]},
        series=[float(value) for value in range(9)],
        labels=[f"t{value}" for value in range(9)],
        plan=plan, seasonal_period=1, max_trials=None,
        metric="rmse", random_state=42, predictors={"test": predictor},
    )

    assert result.strategy == "sliding"
    assert result.cohort_id == plan.cohort_id
    assert [(fold.train_start, fold.train_end, fold.test_start, fold.test_end) for fold in result.folds] == [
        (0, 3, 5, 6), (2, 5, 7, 8),
    ]
    assert result.cv_config.n_splits == 2
    assert result.cv_config.min_train_size == 4
    assert result.n_trials == 2
    assert seen_train == [
        [0.0, 1.0, 2.0, 3.0], [2.0, 3.0, 4.0, 5.0],
        [0.0, 1.0, 2.0, 3.0], [2.0, 3.0, 4.0, 5.0],
    ]


def test_box_cox_is_refitted_per_fold_and_predictions_return_to_source_scale():
    dates = pd.date_range("2024-01-01", periods=9, freq="D")
    frame = pd.DataFrame({
        "date": dates,
        "raw": [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0],
        # Deliberately wrong full-history materialization: production must not use it.
        "raw_box_cox": [999.0] * 9,
    })
    prepared = prepare_modeling_target(
        frame, target_column="raw_box_cox", date_column="date",
        transformations={
            "raw_box_cox": {
                "source_column": "raw", "output_column": "raw_box_cox",
                "method": "box_cox", "lambda_value": 0.77,
                "inverse_supported": True, "fitted_on_n": 9,
            },
        },
        scaling_recipe={},
    )
    plan = build_backtest_plan(
        {
            "strategy": "single", "horizon": 2, "n_splits": 1, "gap": 1,
            "folds": [{"fold": 1, "train_start": 0, "train_end": 5,
                       "gap_size": 1, "test_start": 7, "test_end": 8}],
        },
        n_observations=9, fingerprint="fp", target_column="raw_box_cox",
        seasonal_period=1,
    )
    captured: list[list[float]] = []

    def predictor(train, horizon, _period, _params):
        captured.append(list(train))
        return [train[-1]] * horizon

    result = run_backtest_plan(
        model_id="test", model_name="Test", family_id="test",
        series=prepared.series, labels=prepared.labels, plan=plan,
        seasonal_period=1, predictors={"test": predictor},
        fold_preprocessor=prepared.fold_preprocessor,
        preprocessing_warnings=prepared.warnings,
    )

    assert prepared.source_column == "raw"
    expected_train, _ = apply_variance_transform(
        frame["raw"].iloc[:6].to_numpy(dtype=float), "box_cox", None,
    )
    full_history_lambda_train, _ = apply_variance_transform(
        frame["raw"].iloc[:6].to_numpy(dtype=float), "box_cox", 0.77,
    )
    assert captured[0] == pytest.approx(expected_train.tolist())
    assert captured[0] != pytest.approx(full_history_lambda_train.tolist())
    assert [point["actual"] for point in result["oof_predictions"]] == [128.0, 256.0]
    assert all(abs(point["predicted"] - 32.0) < 1e-6 for point in result["oof_predictions"])
    assert result["preprocessing"]["fit_policy"] == "per_train_fold"
    assert result["preprocessing"]["evaluation_scale"] == "raw"


def test_target_scaler_is_fit_on_train_only_and_inverse_transformed_for_metrics():
    frame = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=6, freq="D"),
        "value": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
    })
    prepared = prepare_modeling_target(
        frame, target_column="value", date_column="date", transformations={},
        scaling_recipe={
            "kind": "scaling_recipe", "target_column": "value",
            "columns": ["value"], "method": "standard", "parameters": {},
            "fit_policy": "per_train_fold", "target_included": True,
        },
    )
    plan = build_backtest_plan(
        {
            "strategy": "single", "horizon": 2, "n_splits": 1, "gap": 0,
            "folds": [{"fold": 1, "train_start": 0, "train_end": 3,
                       "gap_size": 0, "test_start": 4, "test_end": 5}],
        },
        n_observations=6, fingerprint="fp", target_column="value", seasonal_period=1,
    )

    result = run_backtest_plan(
        model_id="zero", model_name="Zero", family_id="test",
        series=prepared.series, labels=prepared.labels, plan=plan,
        seasonal_period=1, predictors={"zero": lambda _train, horizon, _period, _params: [0.0] * horizon},
        fold_preprocessor=prepared.fold_preprocessor,
    )

    assert [point["predicted"] for point in result["oof_predictions"]] == [25.0, 25.0]
    assert [point["actual"] for point in result["oof_predictions"]] == [50.0, 60.0]
    assert result["metrics"]["mae"] == 30.0


def test_stationarity_transform_is_fit_and_inverted_inside_the_fold():
    frame = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=6, freq="D"),
        "raw": [1.0, 2.0, 4.0, 7.0, 11.0, 16.0],
        "raw_diff1": [1.0, 2.0, 3.0, 4.0, 5.0, 999.0],
    })
    prepared = prepare_modeling_target(
        frame, target_column="raw_diff1", date_column="date",
        transformations={
            "raw_diff1": {
                "kind": "stationarity", "source_column": "raw",
                "method": "first_difference", "inverse_supported": True,
            },
        }, scaling_recipe={},
    )
    plan = build_backtest_plan(
        {
            "strategy": "single", "horizon": 2, "n_splits": 1, "gap": 0,
            "folds": [{"fold": 1, "train_start": 0, "train_end": 3,
                       "gap_size": 0, "test_start": 4, "test_end": 5}],
        },
        n_observations=6, fingerprint="fp", target_column="raw_diff1", seasonal_period=1,
        preprocessing_signature=prepared.preprocessing_signature,
    )
    result = run_backtest_plan(
        model_id="naive", model_name="Naive", family_id="baselines",
        series=prepared.series, labels=prepared.labels, plan=plan,
        seasonal_period=1, fold_preprocessor=prepared.fold_preprocessor,
    )

    assert [point["actual"] for point in result["oof_predictions"]] == [11.0, 16.0]
    assert [point["predicted"] for point in result["oof_predictions"]] == [10.0, 13.0]
    assert result["preprocessing"]["evaluation_scale"] == "raw"
