"""Contract tests for the extensible Modeling execution boundary (v2)."""

import math

import pytest

from apps.api.backtesting import build_backtest_plan, run_backtest_plan
from apps.api.model_execution import (
    MODEL_EXECUTION_CONTRACT_VERSION,
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionContractError,
    ModelExecutionDefinition,
    ModelExecutionRegistry,
    ModelExecutionRequest,
    ModelExecutionResult,
)
from apps.api.model_readiness import (
    PRODUCTION_BACKTEST_MODEL_IDS,
    PRODUCTION_DIAGNOSTICS_MODEL_IDS,
    PRODUCTION_TUNING_MODEL_IDS,
)
from apps.api.routers.models import _compute_candidates
from apps.api.schemas import CandidatesRequest, DataProfileRequest


CERTIFIED_IDS = frozenset({
    "naive", "seasonal_naive", "drift", "mean", "ets",
    "ets_damped", "theta", "arima", "arima_auto",
})


def test_registry_is_the_single_source_of_truth_for_production_actions():
    assert MODEL_EXECUTION_CONTRACT_VERSION == "model-execution-v2"
    assert MODEL_EXECUTION_REGISTRY.model_ids == CERTIFIED_IDS
    assert MODEL_EXECUTION_REGISTRY.model_ids_for("backtest") == PRODUCTION_BACKTEST_MODEL_IDS
    assert MODEL_EXECUTION_REGISTRY.model_ids_for("diagnostics") == PRODUCTION_DIAGNOSTICS_MODEL_IDS
    assert MODEL_EXECUTION_REGISTRY.model_ids_for("tune") == PRODUCTION_TUNING_MODEL_IDS

    for model_id in CERTIFIED_IDS:
        descriptor = MODEL_EXECUTION_REGISTRY.describe(model_id)
        assert descriptor["version"] == MODEL_EXECUTION_CONTRACT_VERSION
        assert descriptor["model_id"] == model_id
        assert descriptor["input_kind"] == "univariate"
        assert descriptor["fit_policy"] == "per_train_fold"
        assert descriptor["dependency_group"] == "classical"
        assert len(descriptor["signature"]) == 64
        assert "executor" not in descriptor


def test_candidates_publish_v2_descriptors_only_for_executable_models():
    response = _compute_candidates(CandidatesRequest(profile=DataProfileRequest(
        n_observations=500, n_series=1, n_exogenous=2,
        is_regular=True, frequency="M", has_seasonality=True,
        seasonal_periods=[12], is_stationary_or_diffable=True,
        domain="macro", gpu_available=True, feature_engineering_applied=True,
    )))
    catalog = {candidate.model_id: candidate for candidate in response.catalog}

    assert response.execution_contract_version == "model-execution-v2"
    assert catalog["naive"].execution_contract == MODEL_EXECUTION_REGISTRY.describe("naive")
    assert catalog["xgboost"].execution_contract is None


def test_request_and_result_fail_closed_on_misaligned_or_nonfinite_data():
    with pytest.raises(ModelExecutionContractError, match="horizon"):
        ModelExecutionRequest(target=[1.0, 2.0], horizon=0)
    with pytest.raises(ModelExecutionContractError, match="NaN/Inf"):
        ModelExecutionRequest(target=[1.0, math.nan], horizon=1)
    with pytest.raises(ModelExecutionContractError, match="train_features"):
        ModelExecutionRequest(
            target=[1.0, 2.0], horizon=1,
            train_features={"x": [1.0]}, future_features={"x": [3.0]},
        )

    bad_registry = ModelExecutionRegistry([
        ModelExecutionDefinition(
            model_id="bad", family_id="test", adapter_id="bad-adapter",
            executor=lambda _request: ModelExecutionResult(forecast=[1.0, math.inf]),
        ),
    ])
    with pytest.raises(ModelExecutionContractError, match="NaN/Inf"):
        bad_registry.execute("bad", ModelExecutionRequest(target=[1.0, 2.0], horizon=2))


def test_contract_can_carry_future_covariates_for_ml_adapters_without_test_targets():
    seen = {}

    def execute(request: ModelExecutionRequest) -> ModelExecutionResult:
        seen["target"] = request.target
        seen["train_features"] = request.train_features
        seen["future_features"] = request.future_features
        return ModelExecutionResult(
            forecast=[request.target[-1] + request.future_features["promo"][0]],
            metadata={"seed": request.random_state},
        )

    registry = ModelExecutionRegistry([
        ModelExecutionDefinition(
            model_id="future_ml", family_id="tree_ml",
            adapter_id="future-ml-v1", executor=execute,
            input_kind="supervised", requires_train_features=True,
            supports_future_features=True,
            actions=frozenset({"backtest", "tune", "diagnostics"}),
        ),
    ])
    result = registry.execute(
        "future_ml",
        ModelExecutionRequest(
            target=[10.0, 12.0], horizon=1,
            train_features={"promo": [0.0, 1.0]},
            future_features={"promo": [2.0]}, random_state=7,
        ),
    )

    assert result.forecast == (14.0,)
    assert result.metadata == {"seed": 7}
    assert seen == {
        "target": (10.0, 12.0),
        "train_features": {"promo": (0.0, 1.0)},
        "future_features": {"promo": (2.0,)},
    }


def test_backtest_artifact_records_the_exact_execution_adapter():
    plan = build_backtest_plan(
        {
            "strategy": "single", "horizon": 2, "n_splits": 1, "gap": 0,
            "folds": [{
                "fold": 1, "train_start": 0, "train_end": 3,
                "gap_size": 0, "test_start": 4, "test_end": 5,
            }],
        },
        n_observations=6, fingerprint="contract-v2", target_column="value",
        seasonal_period=1,
    )
    artifact = run_backtest_plan(
        model_id="naive", model_name="Naive", family_id="baselines",
        series=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        labels=[f"t{index}" for index in range(6)], plan=plan,
        seasonal_period=1,
    )

    assert artifact["execution_contract"]["version"] == "model-execution-v2"
    assert artifact["execution_contract"]["model_id"] == "naive"
    assert artifact["execution_contract"]["adapter_id"] == "baseline-naive"
    assert artifact["execution_contract"]["signature"]
