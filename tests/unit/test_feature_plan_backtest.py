"""Task 126 -- FeaturePlan integration with the backtest engine.

The cohort contract carries the feature plan for every model in the cohort,
and ``run_backtest_plan`` applies it fold-locally:

- future_known/static regressors reach ONLY adapters that explicitly declare
  ``supports_future_features`` (no capability -- no regressors);
- historic features never leave the train slice and never enter the request;
- each fold records an auditable feature-matrix lineage record bound to the
  exact train matrix hash.

The supervised adapter is stubbed here so the engine contract is tested in
isolation from cmdstan; the real Prophet regressor path is covered by
tests/unit/test_prophet_regressors.py and the API-level session test.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from apps.api.backtesting import build_backtest_plan, run_backtest_plan
from apps.api.feature_plan import (
    bind_feature_importance,
    build_feature_plan_from_metadata,
    empty_feature_plan,
)
from apps.api.model_execution import (
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionDefinition,
    ModelExecutionRequest,
    ModelExecutionResult,
)


def _validation() -> dict:
    horizon, gap = 3, 0
    folds = []
    for ordinal, train_end in enumerate([17, 20], 1):
        test_start = train_end + gap + 1
        folds.append({
            "fold": ordinal,
            "train_start": 0, "train_end": train_end,
            "gap_start": train_end + 1, "gap_end": train_end + gap,
            "gap_size": gap,
            "test_start": test_start, "test_end": test_start + horizon - 1,
        })
    return {
        "strategy": "expanding", "horizon": horizon, "n_splits": len(folds),
        "gap": gap, "folds": folds, "effective_splits": len(folds),
    }


def _series(n: int = 24) -> tuple[list[float], list[str]]:
    values = [
        100.0 + index + 4.0 * math.sin(2.0 * math.pi * index / 12.0)
        for index in range(n)
    ]
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    return values, [value.isoformat() for value in dates]


def _plan_metadata() -> dict:
    catalog = [
        {"name": "value_lag_1", "family": "lag", "lookback": 1, "known_in_advance": False},
        {"name": "value_roll_mean_3", "family": "rolling", "lookback": 3, "known_in_advance": False},
        {"name": "date_month_sin", "family": "calendar", "lookback": 0, "known_in_advance": True},
    ]
    return {
        "kind": "feature_generation",
        "source_column": "value", "date_column": "date",
        "feature_names": [item["name"] for item in catalog],
        "feature_catalog": catalog,
        "max_lookback": 3, "causal": True, "target_shift": 1,
    }


def _feature_columns(labels: list[str]) -> dict[str, list[float]]:
    dates = pd.Series(pd.to_datetime(labels))
    month = dates.dt.month.to_numpy(dtype=float) - 1.0
    return {"date_month_sin": list(np.sin(2.0 * np.pi * month / 12.0))}


def _stub_definition(
    *, supports_future_features: bool = True, input_kind: str = "supervised",
    captured: list[ModelExecutionRequest],
) -> ModelExecutionDefinition:
    def execute(request: ModelExecutionRequest) -> ModelExecutionResult:
        captured.append(request)
        return ModelExecutionResult(
            forecast=[float(request.target[-1])] * request.horizon,
            lower_interval=[float(request.target[-1]) - 1.0] * request.horizon,
            upper_interval=[float(request.target[-1]) + 1.0] * request.horizon,
            metadata={"stub": True},
        )

    return ModelExecutionDefinition(
        model_id="prophet", family_id="structural", adapter_id="stub-supervised",
        executor=execute, input_kind=input_kind,  # type: ignore[arg-type]
        supports_future_features=supports_future_features,
        supports_prediction_intervals=True,
        actions=frozenset({"backtest", "diagnostics"}), required_packages=(),
    )


class _StubRegistry:
    """Swap the real prophet adapter for a deterministic supervised stub."""

    def __init__(self, *, supports_future_features: bool = True):
        self.captured: list[ModelExecutionRequest] = []
        self._supports = supports_future_features

    def __enter__(self) -> "_StubRegistry":
        self._patcher = pytest.MonkeyPatch()
        self._original = MODEL_EXECUTION_REGISTRY._definitions
        stub = _stub_definition(
            supports_future_features=self._supports, captured=self.captured,
        )
        self._patcher.setattr(
            MODEL_EXECUTION_REGISTRY, "_definitions",
            {**self._original, "prophet": stub}, raising=False,
        )
        return self

    def __exit__(self, *exc_info) -> None:
        self._patcher.setattr(MODEL_EXECUTION_REGISTRY, "_definitions", self._original)
        self._patcher.undo()


def _build(plan_metadata=None):
    """Build the backtest plan with an optional feature plan attached."""
    values, labels = _series()
    kwargs = {}
    if plan_metadata is not None:
        kwargs["feature_plan"] = build_feature_plan_from_metadata(plan_metadata)
        kwargs["feature_columns"] = _feature_columns(labels)
    backtest_plan = build_backtest_plan(
        _validation(), n_observations=len(values),
        fingerprint="fp-series", target_column="value", seasonal_period=12,
        preprocessing_signature="none", **kwargs,
    )
    return backtest_plan, values, labels


def _run(backtest_plan, values, labels, model_id: str, params=None) -> dict:
    return run_backtest_plan(
        model_id=model_id, model_name=model_id.title(), family_id="structural",
        series=values, labels=labels, plan=backtest_plan,
        seasonal_period=12, params=dict(params or {}),
    )


class TestCohortBinding:
    def test_feature_contract_enters_cohort_contract(self):
        plan_obj = build_feature_plan_from_metadata(_plan_metadata())
        backtest_plan, _, _ = _build(_plan_metadata())

        contract = backtest_plan.cohort_contract["feature_contract"]

        assert contract["plan_id"] == plan_obj.plan_id
        assert contract["fingerprint"] == plan_obj.fingerprint
        assert contract["historic"] == ["value_lag_1", "value_roll_mean_3"]
        assert contract["future_known"] == ["date_month_sin"]

    def test_cohort_id_depends_on_the_feature_plan(self):
        without, _, _ = _build(None)
        with_plan, _, _ = _build(_plan_metadata())

        assert without.cohort_id != with_plan.cohort_id

    def test_default_call_keeps_legacy_contract_shape(self):
        backtest_plan, _, _ = _build(None)

        contract = backtest_plan.cohort_contract["feature_contract"]

        assert contract["policy"] == "none"
        assert contract["historic"] == []
        assert contract["future_known"] == []


class TestFoldLocalExecution:
    def test_supervised_adapter_receives_only_future_known_regressors(self):
        """The headline Task 126 guarantee: the request carries the calendar
        regressor and nothing target-derived."""
        backtest_plan, values, labels = _build(_plan_metadata())

        with _StubRegistry() as stub:
            result = _run(backtest_plan, values, labels, "prophet")

        assert result["status"] == "success"
        assert stub.captured, "Supervised request must be captured"
        for request in stub.captured:
            assert list(request.future_features) == ["date_month_sin"]
            assert list(request.train_features) == ["date_month_sin"]
            assert "value_lag_1" not in request.train_features
            assert "value_roll_mean_3" not in request.train_features
            assert "value_lag_1" not in request.future_features

    def test_fold_records_carry_feature_matrix_lineage(self):
        backtest_plan, values, labels = _build(_plan_metadata())

        with _StubRegistry():
            result = _run(backtest_plan, values, labels, "prophet")

        hashes = [fold["feature_matrix"]["matrix_hash"] for fold in result["folds"]]
        assert all(hashes)
        assert len(set(hashes)) == len(hashes)  # different train windows
        for fold in result["folds"]:
            assert fold["feature_matrix"]["plan_id"].startswith("fp_")
            assert fold["feature_matrix"]["fit_policy"] == "per_train_fold"
            assert fold["feature_matrix"]["columns"] == [
                "value_lag_1", "value_roll_mean_3",
            ]
            assert fold["feature_matrix"]["future_known_columns"] == ["date_month_sin"]

    def test_capability_gate_no_capability_no_regressors(self):
        """A supervised adapter without supports_future_features receives no
        regressor payload and the run reports the excluded plan."""
        backtest_plan, values, labels = _build(_plan_metadata())

        with _StubRegistry(supports_future_features=False) as stub:
            result = _run(backtest_plan, values, labels, "prophet")

        assert result["status"] == "success"
        for request in stub.captured:
            assert request.future_features == {}
            assert request.train_features == {}
        assert any(
            "date_month_sin" in warning for warning in result["warnings"]
        ), result["warnings"]

    def test_univariate_baseline_gets_warning_and_clean_folds(self):
        backtest_plan, values, labels = _build(_plan_metadata())

        result = _run(backtest_plan, values, labels, "naive")

        assert result["status"] == "success"
        assert any(
            "date_month_sin" in warning for warning in result["warnings"]
        ), result["warnings"]
        assert all(
            fold.get("feature_matrix") is None for fold in result["folds"]
        )

    def test_historic_only_plan_never_builds_future_payload(self):
        metadata = _plan_metadata()
        metadata["feature_catalog"] = metadata["feature_catalog"][:2]
        metadata["feature_names"] = [
            item["name"] for item in metadata["feature_catalog"]
        ]
        backtest_plan, values, labels = _build(metadata)

        with _StubRegistry() as stub:
            result = _run(backtest_plan, values, labels, "prophet")

        assert result["status"] == "success"
        for request in stub.captured:
            assert request.future_features == {}
            assert request.train_features == {}

    def test_empty_feature_plan_matches_legacy_run(self):
        legacy_plan, values, labels = _build(None)
        empty_plan, _, _ = _build(None)
        empty_plan.feature_plan = empty_feature_plan(source_column="value")

        legacy = _run(legacy_plan, values, labels, "naive")
        with_empty = _run(empty_plan, values, labels, "naive")

        assert legacy["metrics"] == with_empty["metrics"]
        assert [point["predicted"] for point in legacy["oof_predictions"]] == [
            point["predicted"] for point in with_empty["oof_predictions"]
        ]


class TestImportanceBinding:
    def test_importance_is_bound_to_exact_fold_matrix(self):
        backtest_plan, values, labels = _build(_plan_metadata())

        with _StubRegistry():
            result = _run(backtest_plan, values, labels, "prophet")

        lineage = result["folds"][0]["feature_matrix"]
        record = bind_feature_importance(
            lineage,
            [{"feature_name": "value_lag_1", "importance": 0.42}],
        )
        assert record["matrix_hash"] == lineage["matrix_hash"]
        assert record["importances"][0]["feature_name"] == "value_lag_1"

        with pytest.raises(Exception, match="oracle"):
            bind_feature_importance(
                lineage,
                [{"feature_name": "oracle_feature", "importance": 1.0}],
            )
