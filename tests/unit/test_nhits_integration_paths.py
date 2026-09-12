# tests/unit/test_nhits_integration_paths.py
"""Task 140 -- N-HiTS: интеграция реестра v2, dispatch, readiness,
матрицы применимости, yaml-спецификации и session-движка (третий
исполнитель neural-runtime контракта Task 137).

Прецедент пар lstm/nbeats (Tasks 138/139): runtime-контракт Task 137
(neural_runtime.py + neural_contract.py) НЕ меняется -- новый адаптер +
запись реестра + условный dispatch + yaml:
- реестр: objective="level_forecast", input_kind="univariate",
  dependency_group="neural", engine="neuralforecast",
  required_packages=("neuralforecast",) -- честный runtime_available
  реестра v2;
- dispatch: _BACKTEST_IMPLEMENTATIONS согласован с реестром (gate) в
  ОБЕИХ средах -- neural-записи (lstm, nbeats, nhits) регистрируются
  УСЛОВНО пробу neuralforecast_runtime_available() (соглашение
  регистрации _register_neural_dispatch прижимается тестами с обеих
  сторон);
- readiness: nhits в PRODUCTION_BACKTEST_MODEL_IDS <=> runtime
  установлен (22 connected на neural-воркере; на хосте без группы
  модель честно остаётся catalog_only);
- yaml: bounded param_space interpolation_config x hidden_size x
  input_size = 8 trials (<= MAX_TRIALS=64), значения -- внутри
  адаптерных границ;
- движок: одномерный level-cohort через run_backtest_plan (реальный
  нейро-фит на укороченном бюджете теста).

Дополнительно (постановка Task 140: «готовая база для сравнения
N-BEATS/N-HiTS на одном runtime»): обе модели исполняются ЕДИНЫМ
runtime-модулем neural_runtime.train_and_forecast в ОДНОМ
level-cohort (objective/input_kind/engine/dependency_group идентичны)
-- честное ранжирование в comparison sectioned by objective применимо
к паре напрямую, без выравнивания контрактов.
"""
from __future__ import annotations

import itertools

import pytest

from apps.api.model_execution import (
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionContractError,
    ModelExecutionRequest,
)
from apps.api.model_impls import run_nhits_backtest as exported_run_nhits_backtest
from apps.api.model_impls.neural_runtime import neuralforecast_runtime_available
from apps.api.model_readiness import (
    PRODUCTION_BACKTEST_MODEL_IDS,
    available_model_actions,
    model_stage_capabilities,
)
from apps.api.routers.models import (
    _BACKTEST_IMPLEMENTATIONS,
    _register_neural_dispatch,
)

_HAS_NEURAL = neuralforecast_runtime_available()

requires_neural = pytest.mark.skipif(
    not _HAS_NEURAL, reason="neural runtime -- опциональная группа",
)


def test_neural_dispatch_registration_convention():
    """Условная регистрация neural-записей в dispatch прижимается с ОБЕИХ
    сторон: без runtime ни одна запись не появляется (gate
    реестр<->dispatch остаётся точным), с runtime -- появляются все три
    (Task 138 lstm + Task 139 nbeats + Task 140 nhits)."""
    without: dict = {}
    _register_neural_dispatch(without, runtime_available=False)
    assert without == {}

    with_runtime: dict = {}
    _register_neural_dispatch(with_runtime, runtime_available=True)
    assert set(with_runtime) == {"lstm", "nbeats", "nhits"}


def test_dispatch_gate_consistency_in_this_environment():
    """Инвариант import-гейта routers/models.py воспроизводим в тесте:
    dispatch и readiness согласованы в текущей среде (обе стороны
    производны одного честного проба runtime)."""
    assert frozenset(_BACKTEST_IMPLEMENTATIONS) == PRODUCTION_BACKTEST_MODEL_IDS
    assert ("nhits" in _BACKTEST_IMPLEMENTATIONS) is _HAS_NEURAL


# ── Реестр v2: контракт neural ───────────────────────────────────────────

def test_nhits_registry_entry_contract():
    descriptor = MODEL_EXECUTION_REGISTRY.describe("nhits")
    assert descriptor["model_id"] == "nhits"
    assert descriptor["family_id"] == "neural"
    assert descriptor["adapter_id"] == "neuralforecast-nhits"
    assert descriptor["engine"] == "neuralforecast"
    assert descriptor["objective"] == "level_forecast"
    assert descriptor["input_kind"] == "univariate"
    assert descriptor["dependency_group"] == "neural"
    assert descriptor["required_packages"] == ["neuralforecast"]
    assert descriptor["supports_prediction_intervals"] is True
    assert descriptor["supports_future_features"] is False
    assert descriptor["deterministic"] is True
    assert descriptor["fit_policy"] == "per_train_fold"
    assert set(descriptor["actions"]) == {"backtest", "tune", "diagnostics"}
    assert descriptor["lifecycle_capabilities"] == {
        "fit": True, "predict": True, "tuning": True, "diagnostics": True,
    }


def test_nbeats_and_nhits_share_one_runtime_for_fair_comparison():
    """Постановка Task 140: «готовая база для сравнения N-BEATS/N-HiTS
    на одном runtime».  Пара исполнителей имеет ИДЕНТИЧНЫЙ контракт
    (objective/input_kind/engine/dependency_group, actions, пакеты,
    детерминизм) и ЕДИНУЮ точку исполнения -- train_and_forecast
    neural_runtime (адаптеры не несут собственной fit/predict-петли):
    обе модели попадают в один level-cohort OOF-бэктеста на одних и тех
    же fold'ах -- comparison sectioned by objective ранжирует пару
    честно, без выравнивания контрактов."""
    nbeats = MODEL_EXECUTION_REGISTRY.describe("nbeats")
    nhits = MODEL_EXECUTION_REGISTRY.describe("nhits")
    for key in ("engine", "objective", "input_kind", "dependency_group",
                "required_packages", "actions", "fit_policy",
                "deterministic", "supports_prediction_intervals",
                "supports_future_features", "lifecycle_capabilities"):
        assert nhits[key] == nbeats[key], key

    import inspect

    import apps.api.model_impls.nbeats as nbeats_module
    import apps.api.model_impls.nhits as nhits_module
    from apps.api.model_impls import neural_runtime

    # ЕДИНСТВЕННАЯ точка исполнения: оба адаптера ссылаются на один
    # и тот же runtime-символ (не собственные копии fit/predict-петли).
    assert nhits_module.train_and_forecast is nbeats_module.train_and_forecast
    assert nhits_module.train_and_forecast.__module__ == neural_runtime.__name__
    # ds-конвенция -- единый источник истины (не дубликат).
    assert nhits_module._resolve_time_axis is nbeats_module._resolve_time_axis
    # Оба адаптера не импортируют torch на уровне модуля.
    assert "torch" not in vars(nhits_module)
    assert "torch" not in vars(nbeats_module)
    del inspect


def test_nhits_runtime_availability_is_the_honest_package_probe():
    definition = MODEL_EXECUTION_REGISTRY.require("nhits")
    assert definition.runtime_available() is _HAS_NEURAL
    assert ("nhits" in MODEL_EXECUTION_REGISTRY.model_ids_for("backtest")) is _HAS_NEURAL


def test_nhits_registry_rejects_wrong_objective_and_features_fail_closed():
    """Гейты реестра v2 работают ДО запуска executor'а (не требуют
    neural-runtime): objective=multivariate -- отказ; train_features для
    univariate-входа -- отказ (каталог: supports_exogenous=false)."""
    request = ModelExecutionRequest(
        target=[1.0, 2.0, 3.0], horizon=2, objective="multivariate",
    )
    with pytest.raises(ModelExecutionContractError, match="objective"):
        MODEL_EXECUTION_REGISTRY.execute("nhits", request)
    feature_request = ModelExecutionRequest(
        target=[1.0, 2.0, 3.0], horizon=2,
        train_features={"x": [1.0, 2.0, 3.0]},
    )
    with pytest.raises(ModelExecutionContractError, match="train_features"):
        MODEL_EXECUTION_REGISTRY.execute("nhits", feature_request)


# ── Readiness и матрица применимости ─────────────────────────────────────

def test_nhits_readiness_and_stage_matrix_reflect_runtime():
    actions = available_model_actions("nhits")
    capabilities = model_stage_capabilities("nhits", "neural")
    if _HAS_NEURAL:
        assert "backtest" in actions and "diagnostics" in actions and "tune" in actions
        assert capabilities["backtest"]["status"] == "available"
        assert capabilities["tuning"]["status"] == "available"
        assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 22
    else:
        assert actions == []
        assert capabilities["backtest"]["status"] == "not_implemented"
        assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 19


# ── yaml: bounded param_space и честная альтернатива интерполяции ────────

def test_yaml_param_space_is_bounded_and_within_adapter_bounds():
    from src.catalog.modeling_spec_loader import ModelingSpec

    from apps.api.model_impls.nhits import (
        HIDDEN_SIZE_BOUNDS,
        INPUT_SIZE_BOUNDS,
        INTERPOLATION_OPTIONS,
    )

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    model = spec.get_model("nhits")
    assert model is not None and model.param_space, "param_space обязан быть задан"
    space = model.param_space
    product = int(
        __import__("math").prod(len(values) for values in space.values())
    )
    assert product <= 64, "bounded search: <= MAX_TRIALS"
    assert set(space["interpolation_config"]) <= set(INTERPOLATION_OPTIONS)
    low, high = HIDDEN_SIZE_BOUNDS
    assert all(low <= value <= high for value in space["hidden_size"])
    low, high = INPUT_SIZE_BOUNDS
    assert all(low <= value <= high for value in space["input_size"])


def test_yaml_catalog_entry_keeps_the_honest_name():
    from src.catalog.modeling_spec_loader import ModelingSpec

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    model = spec.get_model("nhits")
    assert model.name == "N-HiTS"
    assert model.supports_prediction_intervals is True
    assert model.supports_exogenous is False


def test_grid_product_of_yaml_space_is_eight_trials():
    """8 = 2 x 2 x 2 -- фиксированный bounded grid Task 140
    (честная альтернатива степеней иерархии прижимается декларацией)."""
    from src.catalog.modeling_spec_loader import ModelingSpec

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    space = spec.get_model("nhits").param_space
    assert int(
        __import__("math").prod(len(values) for values in space.values())
    ) == len(list(itertools.product(*space.values()))) == 8


# ── Executor и движок (требуют neural-runtime) ───────────────────────────

@requires_neural
def test_nhits_executor_returns_contract_result_with_metadata(monkeypatch):
    import apps.api.model_impls.nhits as nhits_module

    monkeypatch.setattr(nhits_module, "NHITS_MAX_STEPS", 3)
    result = MODEL_EXECUTION_REGISTRY.execute("nhits", ModelExecutionRequest(
        target=[float(value) for value in range(1, 41)],
        horizon=4, params={},
        random_state=42,
    ))
    assert len(result.forecast) == 4
    assert result.lower_interval is not None and result.upper_interval is not None
    assert result.metadata["adapter_id"] == "neuralforecast-nhits"
    assert result.metadata["interpolation_config"] == "hierarchical"
    assert result.metadata["deterministic"] is True


@requires_neural
def test_nhits_executor_runs_through_the_session_engine(monkeypatch):
    import math

    import pandas as pd

    import apps.api.model_impls.nhits as nhits_module
    from apps.api.backtesting import build_backtest_plan, run_backtest_plan

    monkeypatch.setattr(nhits_module, "NHITS_MAX_STEPS", 3)
    series = [
        100 + 0.3 * step + 5 * math.sin(2 * math.pi * step / 12)
        for step in range(72)
    ]
    validation = {
        "strategy": "expanding", "horizon": 3, "n_splits": 2, "gap": 0,
        "folds": [
            {"fold": 1, "train_start": 0, "train_end": 65, "gap_size": 0, "test_start": 66, "test_end": 68},
            {"fold": 2, "train_start": 0, "train_end": 68, "gap_size": 0, "test_start": 69, "test_end": 71},
        ],
    }
    plan = build_backtest_plan(
        validation, n_observations=len(series), fingerprint="nhits-series",
        target_column="value", seasonal_period=12,
    )
    dates = pd.date_range("2018-01-01", periods=len(series), freq="MS")
    result = run_backtest_plan(
        model_id="nhits", model_name="N-HiTS", family_id="neural",
        series=series, labels=[value.isoformat() for value in dates],
        plan=plan, seasonal_period=12,
    )
    assert result["status"] == "success"
    assert len(result["oof_predictions"]) == 6
    assert result["metrics"]["mae"] is not None
    assert result["execution_contract"]["model_id"] == "nhits"


@requires_neural
def test_nbeats_and_nhits_run_the_same_oof_cohort_for_fair_comparison(monkeypatch):
    """E2E-оракул базы сравнения: обе модели на ОДНОМ runtime проходят
    ОДИН и тот же план fold'ов (build_backtest_plan fingerprint-независим
    от модели) в одном level-cohort -- метрики ранжируемы напрямую."""
    import math

    import pandas as pd

    import apps.api.model_impls.nbeats as nbeats_module
    import apps.api.model_impls.nhits as nhits_module
    from apps.api.backtesting import build_backtest_plan, run_backtest_plan

    monkeypatch.setattr(nbeats_module, "NBEATS_MAX_STEPS", 3)
    monkeypatch.setattr(nhits_module, "NHITS_MAX_STEPS", 3)
    series = [
        100 + 0.3 * step + 5 * math.sin(2 * math.pi * step / 12)
        for step in range(72)
    ]
    labels = [
        value.isoformat()
        for value in pd.date_range("2018-01-01", periods=len(series), freq="MS")
    ]
    validation = {
        "strategy": "expanding", "horizon": 3, "n_splits": 2, "gap": 0,
        "folds": [
            {"fold": 1, "train_start": 0, "train_end": 65, "gap_size": 0, "test_start": 66, "test_end": 68},
            {"fold": 2, "train_start": 0, "train_end": 68, "gap_size": 0, "test_start": 69, "test_end": 71},
        ],
    }
    plan = build_backtest_plan(
        validation, n_observations=len(series), fingerprint="pair-compare",
        target_column="value", seasonal_period=12,
    )
    results = {
        model_id: run_backtest_plan(
            model_id=model_id,
            model_name="N-BEATS" if model_id == "nbeats" else "N-HiTS",
            family_id="neural", series=series, labels=labels,
            plan=plan, seasonal_period=12,
        )
        for model_id in ("nbeats", "nhits")
    }
    assert all(result["status"] == "success" for result in results.values())
    assert all(len(result["oof_predictions"]) == 6 for result in results.values())
    assert all(result["metrics"]["mae"] is not None for result in results.values())
    # Один и тот же execution-контракт v2 (различие -- только model_id).
    contracts = {
        model_id: results[model_id]["execution_contract"]
        for model_id in ("nbeats", "nhits")
    }
    assert contracts["nbeats"]["adapter_id"] == "neuralforecast-nbeats"
    assert contracts["nhits"]["adapter_id"] == "neuralforecast-nhits"
    # Когортные ключи идентичны (signature -- модель-специфичен по
    # определению: содержит model_id/adapter_id).
    for key in ("version", "objective", "input_kind", "output_kind",
                "fit_policy", "dependency_group"):
        assert contracts["nhits"][key] == contracts["nbeats"][key], key


@requires_neural
def test_legacy_dispatch_export_executes_real_metrics(monkeypatch):
    import apps.api.model_impls.nhits as nhits_module

    monkeypatch.setattr(nhits_module, "NHITS_MAX_STEPS", 3)
    series = [10.0 + 0.05 * step for step in range(96)]
    metrics = exported_run_nhits_backtest(series, 0.75, 12)
    assert metrics.mae is not None
