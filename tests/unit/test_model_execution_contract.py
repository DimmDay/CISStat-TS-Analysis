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
    "ets_damped", "theta", "arima", "arima_auto", "prophet", "tbats",
    # Task 127: первый dependency_group="ml" адаптер, recursive-стратегия.
    "random_forest",
    # Task 128: XGBoost -- второй ML-адаптер (quantile-regression интервалы).
    "xgboost",
    # Task 129: LightGBM -- третий ML-адаптер (native API, leaf-wise).
    "lightgbm",
    # Task 130: CatBoost -- четвёртый ML-адаптер (native CatBoostRegressor,
    # Quantile:alpha интервалы, ordered boosting).
    "catboost",
    # Task 132: VAR -- первый multivariate-исполнитель контракта Task 131
    # (native statsmodels, fold-local порядок лага, нативные интервалы).
    "var",
    # Task 133: VECM -- второй multivariate-исполнитель (fold-local ранг
    # Йохансена, нативный VECMResults.predict; supports_future_features=False).
    "vecm",
    # Task 135: GARCH -- первый volatility-исполнитель контракта Task 134
    # (native arch, fold-local MLE, rescale=False, QLIKE volatility-cohort).
    "garch",
    # Task 136: EGARCH -- второй volatility-исполнитель (прецедент пары
    # var/vecm: тот же volatility-движок; o >= 1 -- параметризация
    # leverage/asymmetry, официальный симуляционный контур arch).
    "egarch",
    # Task 138: LSTM/GRU -- первый исполнитель neural-runtime контракта
    # Task 137 (единый NeuralForecast-runtime; ЗАПИСЬ реестра существует
    # всегда, а в readiness модель попадает только при установленной
    # опциональной группе requirements-neural.txt -- честный
    # runtime_available; см. test_lstm_integration_paths.py).
    "lstm",
    # Task 139: N-BEATS -- второй исполнитель neural-runtime контракта
    # Task 137 (прецедент пары lstm: runtime не меняется -- адаптер +
    # реестр + условный dispatch + yaml; stack_config ∈ {interpretable,
    # generic}; same-seed бит-в-бит, проб Task 139).
    "nbeats",
    # Task 140: N-HiTS -- третий исполнитель neural-runtime контракта
    # Task 137 (прецедент пар lstm/nbeats: runtime не меняется --
    # адаптер + реестр + условный dispatch + yaml; interpolation_config
    # ∈ {hierarchical, light}; same-seed бит-в-бит, проб Task 140;
    # пара nbeats/nhits -- готовая база сравнения на одном runtime).
    "nhits",
    # Task 141: TFT -- четвёртый исполнитель neural-runtime контракта
    # Task 137 и ПЕРВЫЙ срез с probabilistic-поверхностью
    # MQLoss/quantiles (точка = медиана MQLoss; native quantiles,
    # НЕ conformal; attention-ось n_head с гейтом делимости; проб
    # Task 141).
    "tft",
})

# Task 126/127/128/129/130: supervised-адаптеры с regressor-каналом future_known/static.
SUPERVISED_IDS = frozenset({"prophet", "random_forest", "xgboost", "lightgbm", "catboost"})

# Task 127/128/129/130: ML-семейство (dependency_group="ml").
ML_IDS = frozenset({"random_forest", "xgboost", "lightgbm", "catboost"})

# Task 132/133: multivariate-адаптеры (objective="multivariate",
# input_kind="multivariate", requires_related_series -- векторный движок).
# Task 133: var -- supports_future_features=True (VARX-канал), vecm -- False.
MULTIVARIATE_IDS = frozenset({"var", "vecm"})
# Task 133: multivariate-носители future-known экзогенных регрессоров.
MULTIVARIATE_EXOG_IDS = frozenset({"var"})
# Task 135/136: volatility-адаптеры (objective="volatility", input_kind=
# "univariate" -- volatility-движок поверх VolatilityTarget Task 134;
# garch/egarch -- пара исполнителей одного движка, прецедент var/vecm).
VOLATILITY_IDS = frozenset({"garch", "egarch"})
# Task 138/139/140/141: neural-адаптеры (dependency_group="neural",
# единый NeuralForecast-runtime Task 137; исполнители Tasks 138-142;
# deepar -- Task 142, панель).
NEURAL_IDS = frozenset({"lstm", "nbeats", "nhits", "tft"})


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
        # Task 126/127/128/129/130: prophet, random_forest, xgboost, lightgbm
        # и catboost -- supervised-адаптеры (capability supports_future_features
        # для future_known/static регрессоров), var/vecm -- multivariate
        # (Task 132/133; supports_future_features -- только VARX у var),
        # остальные остаются univariate.
        if model_id in MULTIVARIATE_IDS:
            expected_input_kind = "multivariate"
        elif model_id in SUPERVISED_IDS:
            expected_input_kind = "supervised"
        else:
            expected_input_kind = "univariate"
        assert descriptor["input_kind"] == expected_input_kind
        assert descriptor["supports_future_features"] is (
            model_id in SUPERVISED_IDS or model_id in MULTIVARIATE_EXOG_IDS
        )
        assert descriptor["fit_policy"] == "per_train_fold"
        if model_id in ML_IDS:
            expected_dependency_group = "ml"
        elif model_id in VOLATILITY_IDS:
            expected_dependency_group = "volatility"
        elif model_id in NEURAL_IDS:
            expected_dependency_group = "neural"
        else:
            expected_dependency_group = "classical"
        assert descriptor["dependency_group"] == expected_dependency_group
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
    # Task 129/130: lightgbm и catboost стали production-моделями.
    # Task 138/139/140/141: lstm, nbeats, nhits и tft получили
    # реестровые записи; catalog-only пример -- deepar (Task 142 ещё
    # не реализована, записи нет).
    assert catalog["xgboost"].execution_contract == MODEL_EXECUTION_REGISTRY.describe("xgboost")
    assert catalog["lightgbm"].execution_contract == MODEL_EXECUTION_REGISTRY.describe("lightgbm")
    assert catalog["catboost"].execution_contract == MODEL_EXECUTION_REGISTRY.describe("catboost")
    assert catalog["lstm"].execution_contract == MODEL_EXECUTION_REGISTRY.describe("lstm")
    assert catalog["nbeats"].execution_contract == MODEL_EXECUTION_REGISTRY.describe("nbeats")
    assert catalog["nhits"].execution_contract == MODEL_EXECUTION_REGISTRY.describe("nhits")
    assert catalog["tft"].execution_contract == MODEL_EXECUTION_REGISTRY.describe("tft")
    assert catalog["deepar"].execution_contract is None


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
