"""Acceptance tests for the full Task 122 plan, closed by Task 122.1."""
from typing import get_args

import pytest

from apps.api.backtesting import build_backtest_plan
from apps.api.model_execution import (
    ExecutionInputKind,
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionContractError,
    ModelExecutionDefinition,
    ModelExecutionRegistry,
    ModelExecutionRequest,
    ModelExecutionResult,
)


def _noop(request: ModelExecutionRequest) -> ModelExecutionResult:
    return ModelExecutionResult(forecast=[request.target[-1]] * request.horizon)


def test_descriptor_covers_objective_lifecycle_resources_and_runtime_lineage():
    descriptor = MODEL_EXECUTION_REGISTRY.describe("ets")

    assert descriptor["objective"] == "level_forecast"
    assert set(get_args(ExecutionInputKind)) == {
        "univariate", "supervised", "multivariate", "panel",
    }
    assert descriptor["lifecycle_capabilities"] == {
        "fit": True, "predict": True, "tuning": True, "diagnostics": True,
    }
    assert descriptor["resource_capabilities"]["cpu"] == "required"
    assert descriptor["resource_capabilities"]["gpu"] in {
        "unsupported", "optional", "required",
    }
    assert descriptor["model_version"]
    assert descriptor["library_versions"]["python"]
    assert descriptor["library_versions"]["statsmodels"] != "not-installed"
    assert descriptor["runtime_available"] is True


def test_dependency_probe_is_lazy_and_removes_unavailable_adapter_from_readiness():
    registry = ModelExecutionRegistry([
        ModelExecutionDefinition(
            model_id="missing", family_id="test", adapter_id="missing-adapter",
            executor=_noop, required_packages=("cisstat-package-that-does-not-exist",),
        ),
    ])

    assert registry.model_ids == frozenset({"missing"})
    assert registry.model_ids_for("backtest") == frozenset()
    descriptor = registry.describe("missing")
    assert descriptor["runtime_available"] is False
    assert descriptor["dependency_status"][0]["available"] is False
    with pytest.raises(ModelExecutionContractError, match="зависим"):
        registry.execute(
            "missing", ModelExecutionRequest(target=[1.0, 2.0], horizon=1),
        )


def test_cohort_identity_covers_objective_series_features_and_metric_policy():
    validation = {
        "strategy": "single", "horizon": 1, "n_splits": 1, "gap": 0,
        "folds": [{
            "fold": 1, "train_start": 0, "train_end": 2,
            "gap_size": 0, "test_start": 3, "test_end": 3,
        }],
    }
    common = {
        "n_observations": 4, "fingerprint": "target-fp",
        "target_column": "y", "seasonal_period": 1,
    }
    base = build_backtest_plan(validation, **common)
    different_objective = build_backtest_plan(
        validation, **common, objective="volatility",
    )
    different_series = build_backtest_plan(
        validation, **common,
        series_fingerprints={"y": "target-fp", "x": "x-fp"},
    )
    different_features = build_backtest_plan(
        validation, **common,
        feature_contract={"historic": ["lag_1"], "future_known": []},
    )
    different_metrics = build_backtest_plan(
        validation, **common,
        metric_policy={"primary": "mae", "aggregation": "mean"},
    )

    assert base.objective == "level_forecast"
    assert len({
        base.cohort_id, different_objective.cohort_id,
        different_series.cohort_id, different_features.cohort_id,
        different_metrics.cohort_id,
    }) == 5
    assert base.cohort_contract["objective"] == "level_forecast"
    assert base.cohort_contract["series_fingerprints"] == {"y": "target-fp"}

