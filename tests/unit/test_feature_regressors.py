"""Task 124 final certification -- arbitrary fold-local regressors end-to-end.

Task 124 required "fold-local holidays/regressors and a strict future-known
contract".  The Prophet adapter regressor channel shipped role-agnostic in
Task 126, but the session upstream could not declare arbitrary regressors at
all: the feature catalog generator never emits ``family=exogenous`` and
``_session_feature_plan`` materialized only future_known/static columns, so a
historic exogenous regressor would have failed the fold.  These tests close
that gap:

- ``with_regressor_specs`` merges user regressor declarations into an
  immutable FeaturePlan (roles derived from known_in_advance/static);
- ``_session_feature_plan`` materializes declared regressor columns for ALL
  roles (historic exogenous included -- the builder consumes only the train
  slice; the future is never materialized);
- ``run_backtest_plan`` passes future_known/static declarations through the
  capability gate into the supervised request and NEVER passes historic ones.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from apps.api.backtesting import build_backtest_plan, run_backtest_plan
from apps.api.feature_plan import (
    FeaturePlan,
    FeaturePlanError,
    KIND_EXOGENOUS,
    ROLE_FUTURE_KNOWN,
    ROLE_HISTORIC,
    ROLE_STATIC,
    build_feature_plan_from_metadata,
    with_regressor_specs,
)
from apps.api.model_execution import (
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionDefinition,
    ModelExecutionRequest,
    ModelExecutionResult,
)
from apps.api.routers.modeling_session import _session_feature_plan
from apps.api.session_store import AnalysisSession


# -- helpers -----------------------------------------------------------------

def _catalog_metadata() -> dict:
    catalog = [
        {"name": "value_lag_1", "family": "lag", "lookback": 1, "known_in_advance": False},
    ]
    return {
        "kind": "feature_generation", "source_column": "value", "date_column": "date",
        "feature_names": [item["name"] for item in catalog],
        "feature_catalog": catalog,
        "max_lookback": 1, "causal": True, "target_shift": 1,
    }


def _session(n: int = 24) -> AnalysisSession:
    session = AnalysisSession(session_id="regressors-test")
    dates = pd.date_range("2020-01-01", periods=n, freq="D")
    session.dataframe = pd.DataFrame({
        "date": dates,
        "value": [100.0 + index for index in range(n)],
        "price_known": [1.0 + 0.01 * index for index in range(n)],
        "humidity_unknown": [0.5 + math.sin(index / 3.0) for index in range(n)],
        "segment": ["eu"] * n,
    })
    session.target_column = "value"
    return session


def _prepared(session: AnalysisSession) -> SimpleNamespace:
    return SimpleNamespace(series=session.dataframe["value"].tolist())


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


# -- with_regressor_specs (pure core) -----------------------------------------

class TestWithRegressorSpecs:
    def test_roles_follow_known_in_advance_and_static(self):
        plan = with_regressor_specs(
            build_feature_plan_from_metadata(_catalog_metadata()),
            [
                {"column": "price_known", "known_in_advance": True},
                {"column": "humidity_unknown", "known_in_advance": False},
                {"column": "segment", "known_in_advance": True, "static": True},
            ],
        )

        by_name = plan.feature_by_name()
        assert by_name["price_known"].role == ROLE_FUTURE_KNOWN
        assert by_name["price_known"].kind == KIND_EXOGENOUS
        assert by_name["humidity_unknown"].role == ROLE_HISTORIC
        assert by_name["segment"].role == ROLE_STATIC
        # catalog feature preserved untouched
        assert "value_lag_1" in by_name

    def test_identity_changes_and_source_column_is_inherited(self):
        base = build_feature_plan_from_metadata(_catalog_metadata())
        merged = with_regressor_specs(
            base, [{"column": "price_known", "known_in_advance": True}],
        )

        assert merged.plan_id != base.plan_id
        assert merged.fingerprint != base.fingerprint
        assert merged.source_column == base.source_column
        assert merged.policy == base.policy

    def test_base_plan_is_not_mutated(self):
        base = build_feature_plan_from_metadata(_catalog_metadata())
        before = (base.plan_id, len(base.features))

        with_regressor_specs(
            base, [{"column": "price_known", "known_in_advance": True}],
        )

        assert (base.plan_id, len(base.features)) == before

    def test_duplicate_against_catalog_is_rejected(self):
        base = build_feature_plan_from_metadata(_catalog_metadata())

        with pytest.raises(FeaturePlanError, match="value_lag_1"):
            with_regressor_specs(
                base, [{"column": "value_lag_1", "known_in_advance": True}],
            )

    def test_duplicate_inside_declarations_is_rejected(self):
        base = build_feature_plan_from_metadata(_catalog_metadata())

        with pytest.raises(FeaturePlanError, match="price_known"):
            with_regressor_specs(
                base,
                [
                    {"column": "price_known", "known_in_advance": True},
                    {"column": "price_known", "known_in_advance": False},
                ],
            )

    def test_static_requires_known_in_advance(self):
        base = build_feature_plan_from_metadata(_catalog_metadata())

        with pytest.raises(FeaturePlanError, match="static"):
            with_regressor_specs(
                base, [{"column": "segment", "known_in_advance": False, "static": True}],
            )

    def test_missing_known_in_advance_flag_is_rejected(self):
        base = build_feature_plan_from_metadata(_catalog_metadata())

        with pytest.raises(FeaturePlanError, match="known_in_advance"):
            with_regressor_specs(base, [{"column": "price_known"}])

    def test_empty_column_name_is_rejected(self):
        base = build_feature_plan_from_metadata(_catalog_metadata())

        with pytest.raises(FeaturePlanError, match="column"):
            with_regressor_specs(base, [{"column": "", "known_in_advance": True}])

    def test_empty_declarations_return_equivalent_plan(self):
        base = build_feature_plan_from_metadata(_catalog_metadata())

        merged = with_regressor_specs(base, [])

        assert merged.plan_id == base.plan_id
        assert merged.features == base.features

    def test_regressor_only_plan_on_empty_base(self):
        from apps.api.feature_plan import empty_feature_plan

        plan = with_regressor_specs(
            empty_feature_plan(source_column="value"),
            [{"column": "price_known", "known_in_advance": True}],
            policy="recursive",
        )

        assert [spec.name for spec in plan.features] == ["price_known"]
        assert plan.policy == "recursive"
        assert plan.future_known_names() == ["price_known"]


# -- session wiring (_session_feature_plan) -----------------------------------

class TestSessionFeaturePlanMaterializesDeclaredRegressors:
    def test_future_known_declaration_is_materialized_into_feature_columns(self):
        session = _session()
        session.preprocessing_feature_generation = _catalog_metadata()
        session.modeling_feature_regressors = [
            {"column": "price_known", "known_in_advance": True},
        ]

        plan, columns, warnings = _session_feature_plan(session, _prepared(session))

        assert plan is not None
        assert plan.future_known_names() == ["price_known"]
        assert columns["price_known"] == session.dataframe["price_known"].tolist()

    def test_historic_declaration_is_materialized_for_fold_builder(self):
        """Без материализации historic-экзогены fold упал бы по
        _platform_column (FeaturePlanError) -- разрыв end-to-end Task 124."""
        session = _session()
        session.preprocessing_feature_generation = _catalog_metadata()
        session.modeling_feature_regressors = [
            {"column": "humidity_unknown", "known_in_advance": False},
        ]

        plan, columns, warnings = _session_feature_plan(session, _prepared(session))

        assert plan is not None
        assert "humidity_unknown" in plan.historic_names()
        assert plan.feature_by_name()["humidity_unknown"].kind == KIND_EXOGENOUS
        assert columns["humidity_unknown"] == (
            session.dataframe["humidity_unknown"].tolist()
        )

    def test_regressor_only_plan_without_feature_catalog(self):
        session = _session()
        session.modeling_feature_regressors = [
            {"column": "price_known", "known_in_advance": True},
        ]

        plan, columns, warnings = _session_feature_plan(session, _prepared(session))

        assert plan is not None
        assert [spec.name for spec in plan.features] == ["price_known"]
        assert columns["price_known"] == session.dataframe["price_known"].tolist()
        assert not any("исключ" in warning for warning in warnings)

    def test_missing_column_downgrades_whole_plan_fail_closed(self):
        session = _session()
        session.preprocessing_feature_generation = _catalog_metadata()
        session.modeling_feature_regressors = [
            {"column": "price_known", "known_in_advance": True},
        ]
        session.dataframe = session.dataframe.drop(columns=["price_known"])

        plan, columns, warnings = _session_feature_plan(session, _prepared(session))

        assert plan is None
        assert columns == {}
        assert any("price_known" in warning for warning in warnings)

    def test_future_known_nan_downgrades_plan_fail_closed(self):
        session = _session()
        session.preprocessing_feature_generation = _catalog_metadata()
        session.modeling_feature_regressors = [
            {"column": "price_known", "known_in_advance": True},
        ]
        session.dataframe.loc[5, "price_known"] = np.nan

        plan, _columns, warnings = _session_feature_plan(session, _prepared(session))

        assert plan is None
        assert any("price_known" in warning for warning in warnings)

    def test_declaration_equal_to_target_is_downgraded(self):
        session = _session()
        session.modeling_feature_regressors = [
            {"column": "value", "known_in_advance": True},
        ]

        plan, _columns, warnings = _session_feature_plan(session, _prepared(session))

        assert plan is None
        assert any("target" in warning or "value" in warning for warning in warnings)

    def test_no_catalog_and_no_declarations_keeps_legacy_path(self):
        session = _session()

        plan, columns, warnings = _session_feature_plan(session, _prepared(session))

        assert plan is None
        assert columns == {}
        assert warnings == []


# -- backtest engine integration ----------------------------------------------

def _stub_definition(
    *, captured: list[ModelExecutionRequest],
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
        executor=execute, input_kind="supervised",
        supports_future_features=True, supports_prediction_intervals=True,
        actions=frozenset({"backtest", "diagnostics"}), required_packages=(),
    )


class _StubRegistry:
    def __init__(self):
        self.captured: list[ModelExecutionRequest] = []

    def __enter__(self) -> "_StubRegistry":
        self._patcher = pytest.MonkeyPatch()
        self._original = MODEL_EXECUTION_REGISTRY._definitions
        stub = _stub_definition(captured=self.captured)
        self._patcher.setattr(
            MODEL_EXECUTION_REGISTRY, "_definitions",
            {**self._original, "prophet": stub}, raising=False,
        )
        return self

    def __exit__(self, *exc_info) -> None:
        self._patcher.setattr(MODEL_EXECUTION_REGISTRY, "_definitions", self._original)
        self._patcher.undo()


def _backtest_plan_for(session: AnalysisSession):
    prepared = _prepared(session)
    plan_obj, feature_columns, _warnings = _session_feature_plan(session, prepared)
    return build_backtest_plan(
        _validation(), n_observations=len(prepared.series),
        fingerprint="fp-series", target_column=session.target_column,
        seasonal_period=12, preprocessing_signature="none",
        feature_plan=plan_obj, feature_columns=feature_columns,
    ), prepared.series, [value.isoformat() for value in session.dataframe["date"]]


class TestBacktestEngineIntegration:
    def test_future_known_declaration_reaches_supervised_request(self):
        session = _session()
        session.preprocessing_feature_generation = _catalog_metadata()
        session.modeling_feature_regressors = [
            {"column": "price_known", "known_in_advance": True},
        ]
        plan, values, labels = _backtest_plan_for(session)

        with _StubRegistry() as stub:
            result = run_backtest_plan(
                model_id="prophet", model_name="Prophet", family_id="structural",
                series=values, labels=labels, plan=plan, seasonal_period=12,
            )

        assert result["status"] == "success"
        assert stub.captured
        for request in stub.captured:
            assert list(request.train_features) == ["price_known"]
            assert list(request.future_features) == ["price_known"]
            assert len(request.train_features["price_known"]) == len(request.target)
            assert len(request.future_features["price_known"]) == request.horizon

    def test_historic_declaration_stays_out_of_regressor_channel(self):
        """Строгий future-known contract: humidность с неизвестным будущим
        не может попасть в Prophet; пользователь получает явный warning."""
        session = _session()
        session.preprocessing_feature_generation = _catalog_metadata()
        session.modeling_feature_regressors = [
            {"column": "humidity_unknown", "known_in_advance": False},
        ]
        plan, values, labels = _backtest_plan_for(session)

        with _StubRegistry() as stub:
            result = run_backtest_plan(
                model_id="prophet", model_name="Prophet", family_id="structural",
                series=values, labels=labels, plan=plan, seasonal_period=12,
            )

        assert result["status"] == "success"
        for request in stub.captured:
            assert request.train_features == {}
            assert request.future_features == {}
        assert any(
            "humidity_unknown" in warning for warning in result["warnings"]
        ), result["warnings"]
        # historic-экзогена всё же вошла в fold-матрицу (lineage/аудит)
        for fold in result["folds"]:
            assert fold["feature_matrix"]["columns"] == [
                "value_lag_1", "humidity_unknown",
            ]

    def test_mixed_declarations_split_by_role(self):
        session = _session()
        session.preprocessing_feature_generation = _catalog_metadata()
        session.modeling_feature_regressors = [
            {"column": "price_known", "known_in_advance": True},
            {"column": "humidity_unknown", "known_in_advance": False},
        ]
        plan, values, labels = _backtest_plan_for(session)

        with _StubRegistry() as stub:
            result = run_backtest_plan(
                model_id="prophet", model_name="Prophet", family_id="structural",
                series=values, labels=labels, plan=plan, seasonal_period=12,
            )

        assert result["status"] == "success"
        for request in stub.captured:
            assert list(request.train_features) == ["price_known"]
            assert list(request.future_features) == ["price_known"]
        assert any(
            "humidity_unknown" in warning for warning in result["warnings"]
        ), result["warnings"]

    def test_cohort_contract_carries_declared_regressors(self):
        session = _session()
        session.preprocessing_feature_generation = _catalog_metadata()
        session.modeling_feature_regressors = [
            {"column": "price_known", "known_in_advance": True},
        ]
        plan, _values, _labels = _backtest_plan_for(session)

        contract = plan.cohort_contract["feature_contract"]

        assert contract["future_known"] == ["price_known"]
        assert contract["historic"] == ["value_lag_1"]
        assert contract["policy"] == "recursive"
