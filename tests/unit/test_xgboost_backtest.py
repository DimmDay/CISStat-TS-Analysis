"""Task 128 -- XGBoost в движке бэктеста и тюнинга (real registry).

E2E-контракт вертикального среза (зеркало Task 127):
- xgboost зарегистрирован в MODEL_EXECUTION_REGISTRY как supervised-адаптер
  с supports_future_features: fold-local FeaturePlan передаёт ему
  future_known/static регрессоры (granted-режим, без exclusion-warning);
- каждая fold-запись несёт feature_matrix (lineage плана Task 126) и
  feature_importance (importance, привязанный к ТОЧНОЙ матрице адаптера);
- OOF-точки совпадают с фактами test-срезов, детерминированы повторным прогоном;
- bounded param_space из rules/modeling.yaml вписывается в MAX_TRIALS и
  исполняется тем же движком на тех же folds.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from apps.api.backtesting import build_backtest_plan, run_backtest_plan
from apps.api.feature_plan import build_feature_plan_from_metadata
from apps.api.model_execution import MODEL_EXECUTION_REGISTRY
from apps.api.model_readiness import (
    PRODUCTION_BACKTEST_MODEL_IDS,
    PRODUCTION_TUNING_MODEL_IDS,
)
from apps.api.modeling_tuning import execute_tuning_plan


def _validation(n_observations: int) -> dict:
    horizon, gap = 4, 0
    folds = []
    for ordinal, train_end in enumerate([55, 75], 1):
        test_start = train_end + gap + 1
        folds.append({
            "fold": ordinal,
            "train_start": 0, "train_end": train_end,
            "gap_start": train_end + 1, "gap_end": train_end + gap,
            "gap_size": gap,
            "test_start": test_start, "test_end": test_start + horizon - 1,
        })
    assert folds[-1]["test_end"] == n_observations - 1
    return {
        "strategy": "expanding", "horizon": horizon, "n_splits": len(folds),
        "gap": gap, "folds": folds, "effective_splits": len(folds),
    }


def _series(n: int = 80) -> tuple[list[float], list[str]]:
    values = [
        100.0 + 0.6 * index + 6.0 * math.sin(2.0 * math.pi * index / 12.0)
        for index in range(n)
    ]
    dates = pd.date_range("2022-01-01", periods=n, freq="D")
    return values, [value.isoformat() for value in dates]


def _plan_metadata() -> dict:
    catalog = [
        {"name": "value_lag_1", "family": "lag", "lookback": 1, "known_in_advance": False},
        {"name": "date_month_sin", "family": "calendar", "lookback": 0, "known_in_advance": True},
    ]
    return {
        "kind": "feature_generation",
        "source_column": "value", "date_column": "date",
        "feature_names": [item["name"] for item in catalog],
        "feature_catalog": catalog,
        "max_lookback": 1, "causal": True, "target_shift": 1,
    }


def _feature_columns(labels: list[str]) -> dict[str, list[float]]:
    dates = pd.to_datetime(labels)
    return {
        "date_month_sin": [
            math.sin(2.0 * math.pi * (value.month - 1) / 12.0) for value in dates
        ],
    }


def _backtest_plan() -> tuple[object, list[float], list[str]]:
    values, labels = _series()
    plan = build_feature_plan_from_metadata(_plan_metadata())
    backtest_plan = build_backtest_plan(
        _validation(len(values)), n_observations=len(values),
        fingerprint="task128-xgb", target_column="value", seasonal_period=12,
        feature_plan=plan, feature_columns=_feature_columns(labels),
    )
    return backtest_plan, values, labels


XGB_PARAMS = {"n_estimators": 40, "n_lags": 3}


# ══════════════════════════════════════════════════════════════════════════════
# Registry / capability
# ══════════════════════════════════════════════════════════════════════════════

class TestXgboostRegistry:
    def test_registered_as_supervised_ml_adapter(self):
        descriptor = MODEL_EXECUTION_REGISTRY.describe("xgboost")
        assert descriptor["family_id"] == "tree_ml"
        assert descriptor["adapter_id"] == "xgboost-native"
        assert descriptor["input_kind"] == "supervised"
        assert descriptor["supports_future_features"] is True
        assert descriptor["supports_prediction_intervals"] is True
        assert descriptor["deterministic"] is True
        assert descriptor["dependency_group"] == "ml"
        assert descriptor["engine"] == "xgboost"
        assert descriptor["required_packages"] == ["xgboost"]
        assert descriptor["runtime_available"] is True
        assert set(descriptor["actions"]) == {"backtest", "tune", "diagnostics"}

    def test_production_actions_include_xgboost(self):
        assert "xgboost" in PRODUCTION_BACKTEST_MODEL_IDS
        assert "xgboost" in PRODUCTION_TUNING_MODEL_IDS


# ══════════════════════════════════════════════════════════════════════════════
# E2E бэктест: granted-канал, importance, детерминизм
# ══════════════════════════════════════════════════════════════════════════════

class TestXgboostBacktest:
    def test_run_backtest_plan_end_to_end(self):
        plan, values, labels = _backtest_plan()
        result = run_backtest_plan(
            model_id="xgboost", model_name="XGBoost",
            family_id="tree_ml", series=values, labels=labels, plan=plan,
            seasonal_period=12, params=XGB_PARAMS,
        )
        assert result["status"] == "success"
        assert result["n_folds"] == 2
        feature_warnings = [
            warning for warning in result["warnings"] if "FeaturePlan" in warning
        ]
        assert feature_warnings == []
        oof = result["oof_predictions"]
        assert len(oof) == 2 * 4
        for point in oof:
            assert math.isfinite(point["predicted"])
            assert math.isfinite(point["residual"])

    def test_folds_record_importance_bound_to_exact_matrix(self):
        plan, values, labels = _backtest_plan()
        result = run_backtest_plan(
            model_id="xgboost", model_name="XGBoost",
            family_id="tree_ml", series=values, labels=labels, plan=plan,
            seasonal_period=12, params=XGB_PARAMS,
        )
        for fold in result["folds"]:
            assert fold["status"] == "success"
            assert fold["feature_matrix"] is not None
            assert fold["feature_matrix"]["plan_id"] == plan.feature_plan.plan_id
            importance = fold["feature_importance"]
            assert importance is not None
            assert importance["matrix_hash"]
            assert importance["fold"] == fold["fold"]
            assert importance["plan_id"] == plan.feature_plan.plan_id
            names = {item["feature_name"] for item in importance["importances"]}
            assert "xgb_lag_1" in names
            assert "date_month_sin" in names
            total = sum(item["importance"] for item in importance["importances"])
            # XGBoost нормализует gain-importances во float32: сумма 1.0 ± 1e-7.
        assert total == pytest.approx(1.0, abs=1e-6)

    def test_backtest_is_deterministic(self):
        plan, values, labels = _backtest_plan()
        first = run_backtest_plan(
            model_id="xgboost", model_name="XGBoost",
            family_id="tree_ml", series=values, labels=labels, plan=plan,
            seasonal_period=12, params=XGB_PARAMS,
        )
        second = run_backtest_plan(
            model_id="xgboost", model_name="XGBoost",
            family_id="tree_ml", series=values, labels=labels, plan=plan,
            seasonal_period=12, params=XGB_PARAMS,
        )
        assert first["oof_predictions"] == second["oof_predictions"]
        assert first["metrics"] == second["metrics"]

    def test_metrics_are_computed_not_fabricated(self):
        plan, values, labels = _backtest_plan()
        result = run_backtest_plan(
            model_id="xgboost", model_name="XGBoost",
            family_id="tree_ml", series=values, labels=labels, plan=plan,
            seasonal_period=12, params=XGB_PARAMS,
        )
        metrics = result["metrics"]
        assert metrics["mae"] > 0
        assert metrics["rmse"] > 0
        assert metrics["weighted_score"] is None

    def test_run_without_feature_plan_still_works(self):
        values, labels = _series()
        plan = build_backtest_plan(
            _validation(len(values)), n_observations=len(values),
            fingerprint="task128-xgb-bare", target_column="value", seasonal_period=12,
        )
        result = run_backtest_plan(
            model_id="xgboost", model_name="XGBoost",
            family_id="tree_ml", series=values, labels=labels, plan=plan,
            seasonal_period=12, params=XGB_PARAMS,
        )
        assert result["status"] == "success"
        for fold in result["folds"]:
            assert fold["feature_matrix"] is None
            importance = fold["feature_importance"]
            assert importance is not None
            assert importance["plan_id"] is None
            assert importance["matrix_hash"]
            assert {item["feature_name"] for item in importance["importances"]} <= {
                "xgb_lag_1", "xgb_lag_2", "xgb_lag_3",
                "xgb_roll_mean", "xgb_roll_std", "xgb_diff_1",
            }


# ══════════════════════════════════════════════════════════════════════════════
# Tuning: bounded param_space на том же движке
# ══════════════════════════════════════════════════════════════════════════════

class TestXgboostTuning:
    def test_yaml_param_space_is_bounded_and_complete(self):
        from src.catalog.modeling_spec_loader import ModelingSpec
        spec = ModelingSpec.from_yaml("rules/modeling.yaml")
        model = spec.get_model("xgboost")
        assert model is not None and model.param_space
        param_space = model.param_space
        assert set(param_space) == {
            "n_estimators", "max_depth", "learning_rate", "n_lags",
        }
        grid_size = 1
        for values in param_space.values():
            grid_size *= len(values)
        assert grid_size <= 64  # MAX_TRIALS

    def test_tuning_runs_on_same_folds_and_picks_best(self):
        plan, values, labels = _backtest_plan()
        response = execute_tuning_plan(
            model_id="xgboost", model_name="XGBoost",
            family_id="tree_ml",
            param_space={"n_estimators": [30, 50], "n_lags": [2, 3]},
            series=values, labels=labels, plan=plan, seasonal_period=12,
            max_trials=4, metric="rmse", random_state=42,
        )
        assert response.n_trials == 4
        assert response.grid_size == 4
        assert response.truncated is False
        assert response.best_metrics.rmse is not None
        assert response.best_params["n_estimators"] in {30, 50}
        assert response.best_params["n_lags"] in {2, 3}
        assert response.metric == "rmse"
        assert response.cohort_id == plan.cohort_id
