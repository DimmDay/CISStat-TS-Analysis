# tests/unit/test_lstm_integration_paths.py
"""Task 138 -- LSTM/GRU: интеграция реестра v2, dispatch, readiness,
матрицы применимости, yaml-спецификации и session-движка (первый
исполнитель neural-runtime контракта Task 137).

Прецедент пары var/vecm и garch/egarch: runtime-контракт Task 137
(neural_runtime.py + neural_contract.py) НЕ меняется -- новый адаптер +
запись реестра + условный dispatch + yaml:
- реестр: objective="level_forecast", input_kind="univariate",
  dependency_group="neural", engine="neuralforecast",
  required_packages=("neuralforecast",) -- честный runtime_available
  реестра v2 (пакеты группы НЕ входят в production-сборку Docker,
  requirements-neural.txt -- опциональный deploy-манифест Task 137);
- dispatch: _BACKTEST_IMPLEMENTATIONS согласован с реестром (gate) в
  ОБЕИХ средах -- neural-запись регистрируется УСЛОВНО пробу
  neuralforecast_runtime_available() (соглашение регистрации
  _register_neural_dispatch прижимается тестами с обеих сторон);
- readiness: lstm в PRODUCTION_BACKTEST_MODEL_IDS <=> runtime установлен
  (19 -> 20 connected на neural-воркере; на хосте без группы модель
  честно остаётся catalog_only);
- yaml: bounded param_space cell_type x hidden_size x input_size = 8
  trials (<= MAX_TRIALS=64), значения -- внутри адаптерных границ;
- движок: одномерный level-cohort через run_backtest_plan (реальный
  нейро-фит на укороченном бюджете теста).
"""
from __future__ import annotations

import itertools

import pytest

from apps.api.model_execution import (
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionContractError,
    ModelExecutionRequest,
)
from apps.api.model_impls import run_lstm_backtest as exported_run_lstm_backtest
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
    """Условная регистрация neural-записи в dispatch прижимается с ОБЕИХ
    сторон: без runtime запись не появляется (gate реестр<->dispatch
    остаётся точным), с runtime -- появляется."""
    without: dict = {}
    _register_neural_dispatch(without, runtime_available=False)
    assert without == {}

    with_runtime: dict = {}
    _register_neural_dispatch(with_runtime, runtime_available=True)
    assert set(with_runtime) == {"lstm"}


def test_dispatch_gate_consistency_in_this_environment():
    """Инвариант import-гейта routers/models.py воспроизводим в тесте:
    dispatch и readiness согласованы в текущей среде (обе стороны
    производны одного честного проба runtime)."""
    assert frozenset(_BACKTEST_IMPLEMENTATIONS) == PRODUCTION_BACKTEST_MODEL_IDS
    assert ("lstm" in _BACKTEST_IMPLEMENTATIONS) is _HAS_NEURAL


# ── Реестр v2: контракт neural ───────────────────────────────────────────

def test_lstm_registry_entry_contract():
    descriptor = MODEL_EXECUTION_REGISTRY.describe("lstm")
    assert descriptor["model_id"] == "lstm"
    assert descriptor["family_id"] == "neural"
    assert descriptor["adapter_id"] == "neuralforecast-lstm-gru"
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


def test_lstm_runtime_availability_is_the_honest_package_probe():
    definition = MODEL_EXECUTION_REGISTRY.require("lstm")
    assert definition.runtime_available() is _HAS_NEURAL
    assert ("lstm" in MODEL_EXECUTION_REGISTRY.model_ids_for("backtest")) is _HAS_NEURAL


def test_lstm_registry_rejects_wrong_objective_and_features_fail_closed():
    """Гейты реестра v2 работают ДО запуска executor'а (не требуют
    neural-runtime): objective=multivariate -- отказ; train_features для
    univariate-входа -- отказ."""
    request = ModelExecutionRequest(
        target=[1.0, 2.0, 3.0], horizon=2, objective="multivariate",
    )
    with pytest.raises(ModelExecutionContractError, match="objective"):
        MODEL_EXECUTION_REGISTRY.execute("lstm", request)
    feature_request = ModelExecutionRequest(
        target=[1.0, 2.0, 3.0], horizon=2,
        train_features={"x": [1.0, 2.0, 3.0]},
    )
    with pytest.raises(ModelExecutionContractError, match="train_features"):
        MODEL_EXECUTION_REGISTRY.execute("lstm", feature_request)


# ── Readiness и матрица применимости ─────────────────────────────────────

def test_lstm_readiness_and_stage_matrix_reflect_runtime():
    actions = available_model_actions("lstm")
    capabilities = model_stage_capabilities("lstm", "neural")
    if _HAS_NEURAL:
        assert "backtest" in actions and "diagnostics" in actions and "tune" in actions
        assert capabilities["backtest"]["status"] == "available"
        assert capabilities["tuning"]["status"] == "available"
        assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 20
    else:
        assert actions == []
        assert capabilities["backtest"]["status"] == "not_implemented"
        assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 19


# ── yaml: bounded param_space и честная альтернатива LSTM/GRU ────────────

def test_yaml_param_space_is_bounded_and_within_adapter_bounds():
    from src.catalog.modeling_spec_loader import ModelingSpec

    from apps.api.model_impls.lstm import (
        CELL_OPTIONS,
        HIDDEN_SIZE_BOUNDS,
        INPUT_SIZE_BOUNDS,
    )

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    model = spec.get_model("lstm")
    assert model is not None and model.param_space, "param_space обязан быть задан"
    space = model.param_space
    product = int(
        __import__("math").prod(len(values) for values in space.values())
    )
    assert product <= 64, "bounded search: <= MAX_TRIALS"
    assert set(space["cell_type"]) <= set(CELL_OPTIONS)
    low, high = HIDDEN_SIZE_BOUNDS
    assert all(low <= value <= high for value in space["hidden_size"])
    low, high = INPUT_SIZE_BOUNDS
    assert all(low <= value <= high for value in space["input_size"])


def test_yaml_catalog_entry_keeps_the_honest_family_name():
    from src.catalog.modeling_spec_loader import ModelingSpec

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    model = spec.get_model("lstm")
    assert model.name == "LSTM / GRU"
    assert model.supports_prediction_intervals is True


# ── Executor и движок (требуют neural-runtime) ───────────────────────────

@requires_neural
def test_lstm_executor_returns_contract_result_with_metadata():
    result = MODEL_EXECUTION_REGISTRY.execute("lstm", ModelExecutionRequest(
        target=[float(value) for value in range(1, 41)],
        horizon=4, params={},
        random_state=42,
    ))
    assert len(result.forecast) == 4
    assert result.lower_interval is not None and result.upper_interval is not None
    assert result.metadata["adapter_id"] == "neuralforecast-lstm-gru"
    assert result.metadata["cell_type"] == "LSTM"
    assert result.metadata["deterministic"] is True


@requires_neural
def test_lstm_executor_runs_through_the_session_engine(monkeypatch):
    import math

    import pandas as pd

    import apps.api.model_impls.lstm as lstm_module
    from apps.api.backtesting import build_backtest_plan, run_backtest_plan

    monkeypatch.setattr(lstm_module, "LSTM_MAX_STEPS", 3)
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
        validation, n_observations=len(series), fingerprint="lstm-series",
        target_column="value", seasonal_period=12,
    )
    dates = pd.date_range("2018-01-01", periods=len(series), freq="MS")
    result = run_backtest_plan(
        model_id="lstm", model_name="LSTM / GRU", family_id="neural",
        series=series, labels=[value.isoformat() for value in dates],
        plan=plan, seasonal_period=12,
    )
    assert result["status"] == "success"
    assert len(result["oof_predictions"]) == 6
    assert result["metrics"]["mae"] is not None
    assert result["execution_contract"]["model_id"] == "lstm"


@requires_neural
def test_legacy_dispatch_export_executes_real_metrics(monkeypatch):
    import apps.api.model_impls.lstm as lstm_module

    monkeypatch.setattr(lstm_module, "LSTM_MAX_STEPS", 3)
    series = [10.0 + 0.05 * step for step in range(96)]
    metrics = exported_run_lstm_backtest(series, 0.75, 12)
    assert metrics.mae is not None


def test_grid_product_of_yaml_space_is_eight_trials():
    """8 = 2 x 2 x 2 -- фиксированный bounded grid Task 138
    (честная альтернатива LSTM/GRU прижимается декларацией)."""
    from src.catalog.modeling_spec_loader import ModelingSpec

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    space = spec.get_model("lstm").param_space
    assert int(
        __import__("math").prod(len(values) for values in space.values())
    ) == len(list(itertools.product(*space.values()))) == 8
