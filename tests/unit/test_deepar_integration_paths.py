# tests/unit/test_deepar_integration_paths.py
"""Task 142 -- DeepAR: интеграция реестра v2, dispatch, readiness,
yaml-спецификации, panel-движка session-контура и cohort-изоляции
(ПЯТЫЙ исполнитель neural-runtime контракта Task 137, panel-постановка,
ВТОРОЙ срез с probabilistic-поверхностью MQLoss/quantiles).

Прецедент quartet'а lstm/nbeats/nhits/tft (Tasks 138-141): runtime-
контракт Task 137 НЕ меняется -- новый адаптер + запись реестра +
условный dispatch + yaml.  НОВОЕ оси среза 142:
- реестр: input_kind="panel" + requires_related_series=True (единственный
  такой носитель в нейро-семействе и второй после var/vecm вообще) --
  панельная честность активации (правило моделирования: несколько
  числовых колонок одного объекта не выдаются за панель);
- движок: panel-исполнение через run_panel_backtest_plan (Task 134-
  прецедент отдельного движка под input_kind: main-движок не передаёт
  related_series, vector-движок -- objective=multivariate); cohort --
  нейро-контракт Task 137 (neural_cohort_contract: panel=true,
  n_series, min_series=5) -- cohort_id ОТЛИЧЕН от univariate-планов на
  тех же fold'ах (comparison честно изолирует panel-cohort);
- dispatch: legacy synthetic-эндпоинт -- честный отказ (прецедент
  var/vecm), регистрация УСЛОВНА пробу runtime (_register_neural_dispatch).
"""
from __future__ import annotations

import itertools
import math

import pandas as pd
import pytest

from apps.api.model_execution import (
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionContractError,
    ModelExecutionRequest,
)
from apps.api.model_impls import run_deepar_backtest as exported_run_deepar_backtest
from apps.api.model_impls.deepar import (
    DEEPAR_MIN_SERIES,
    INPUT_SIZE_BOUNDS,
    LSTM_HIDDEN_SIZE_BOUNDS,
)
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
    сторон: без runtime ни одна запись не появляется, с runtime --
    появляются все ПЯТЬ (Tasks 138-142)."""
    without: dict = {}
    _register_neural_dispatch(without, runtime_available=False)
    assert without == {}

    with_runtime: dict = {}
    _register_neural_dispatch(with_runtime, runtime_available=True)
    assert set(with_runtime) == {"lstm", "nbeats", "nhits", "tft", "deepar"}


def test_dispatch_gate_consistency_in_this_environment():
    """Инвариант import-гейта routers/models.py воспроизводим в тесте."""
    assert frozenset(_BACKTEST_IMPLEMENTATIONS) == PRODUCTION_BACKTEST_MODEL_IDS
    assert ("deepar" in _BACKTEST_IMPLEMENTATIONS) is _HAS_NEURAL


# ── Реестр v2: панельная запись neural ───────────────────────────────────

def test_deepar_registry_entry_contract():
    descriptor = MODEL_EXECUTION_REGISTRY.describe("deepar")
    assert descriptor["model_id"] == "deepar"
    assert descriptor["family_id"] == "neural"
    assert descriptor["adapter_id"] == "neuralforecast-deepar"
    assert descriptor["engine"] == "neuralforecast"
    assert descriptor["objective"] == "level_forecast"
    assert descriptor["input_kind"] == "panel"
    assert descriptor["requires_related_series"] is True
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


def test_deepar_panel_input_kind_is_the_honest_difference_in_the_family():
    """Панельная ось -- ЗАДЕКЛАРИРОВАННОЕ различие внутри нейро-семейства:
    quartet lstm/nbeats/nhits/tft -- univariate; deepar -- panel
    (requires_related_series).  Движок/группа/действия -- общие."""
    deepar = MODEL_EXECUTION_REGISTRY.describe("deepar")
    tft = MODEL_EXECUTION_REGISTRY.describe("tft")
    assert deepar["input_kind"] == "panel"
    assert tft["input_kind"] == "univariate"
    assert deepar["requires_related_series"] is True
    assert tft["requires_related_series"] is False
    for key in ("engine", "objective", "dependency_group", "required_packages",
                "actions", "fit_policy", "deterministic",
                "supports_prediction_intervals"):
        assert deepar[key] == tft[key], key


def test_deepar_runtime_availability_is_the_honest_package_probe():
    definition = MODEL_EXECUTION_REGISTRY.require("deepar")
    assert definition.runtime_available() is _HAS_NEURAL
    assert ("deepar" in MODEL_EXECUTION_REGISTRY.model_ids_for("backtest")) is _HAS_NEURAL


def test_deepar_registry_requires_related_series_fail_closed():
    """Гейты реестра v2 работают ДО запуска executor'а: без related_series
    panel-модель отказывает ("требует related_series"); objective
    multivariate -- отказ.  Панель из НЕСКОЛЬКИХ числовых колонок одного
    объекта не имитируется: related_series -- единственный канал."""
    request = ModelExecutionRequest(
        target=[float(value) for value in range(1, 41)], horizon=4,
    )
    with pytest.raises(ModelExecutionContractError, match="related_series"):
        MODEL_EXECUTION_REGISTRY.execute("deepar", request)
    wrong_objective = ModelExecutionRequest(
        target=[float(value) for value in range(1, 41)], horizon=4,
        objective="multivariate",
        related_series={"a": [1.0] * 40, "b": [2.0] * 40,
                        "c": [3.0] * 40, "d": [4.0] * 40},
    )
    with pytest.raises(ModelExecutionContractError, match="objective"):
        MODEL_EXECUTION_REGISTRY.execute("deepar", wrong_objective)


def test_deepar_readiness_and_stage_matrix_reflect_runtime():
    actions = available_model_actions("deepar")
    capabilities = model_stage_capabilities("deepar", "neural")
    if _HAS_NEURAL:
        assert "backtest" in actions and "diagnostics" in actions and "tune" in actions
        assert capabilities["backtest"]["status"] == "available"
        assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 24
    else:
        assert actions == []
        assert capabilities["backtest"]["status"] == "not_implemented"
        assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 19


# ── yaml: bounded param_space и честная панельная декларация ─────────────

def test_yaml_param_space_is_bounded_and_within_adapter_bounds():
    from src.catalog.modeling_spec_loader import ModelingSpec

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    model = spec.get_model("deepar")
    assert model is not None and model.param_space, "param_space обязан быть задан"
    space = model.param_space
    product = int(math.prod(len(values) for values in space.values()))
    assert product <= 64, "bounded search: <= MAX_TRIALS"
    low, high = LSTM_HIDDEN_SIZE_BOUNDS
    assert all(low <= value <= high for value in space["lstm_hidden_size"])
    low, high = INPUT_SIZE_BOUNDS
    assert all(low <= value <= high for value in space["input_size"])


def test_yaml_catalog_entry_keeps_the_honest_panel_declaration():
    from src.catalog.modeling_spec_loader import ModelingSpec

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    model = spec.get_model("deepar")
    assert model.name == "DeepAR"
    assert model.min_series == 5
    assert model.supports_prediction_intervals is True


def test_grid_product_of_yaml_space_is_four_trials():
    """4 = 2 x 2 -- фиксированный bounded grid Task 142
    (capacity x окно прижимается декларацией; alpha -- вне тюнинга)."""
    from src.catalog.modeling_spec_loader import ModelingSpec

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    space = spec.get_model("deepar").param_space
    assert int(math.prod(len(values) for values in space.values())) == len(
        list(itertools.product(*space.values()))
    ) == 4


# ── Executor и panel-движок (требуют neural-runtime) ─────────────────────

@requires_neural
def test_deepar_executor_returns_contract_result_with_metadata(monkeypatch):
    import apps.api.model_impls.deepar as deepar_module

    monkeypatch.setattr(deepar_module, "DEEPAR_MAX_STEPS", 20)
    result = MODEL_EXECUTION_REGISTRY.execute("deepar", ModelExecutionRequest(
        target=[float(value) for value in range(1, 41)],
        horizon=4, params={},
        related_series={
            "a": [2.0 * value for value in range(1, 41)],
            "b": [3.0 * value for value in range(1, 41)],
            "c": [4.0 * value for value in range(1, 41)],
            "d": [5.0 * value for value in range(1, 41)],
        },
        random_state=42,
    ))
    assert len(result.forecast) == 4
    assert result.lower_interval is not None and result.upper_interval is not None
    assert result.metadata["adapter_id"] == "neuralforecast-deepar"
    assert result.metadata["intervals"]["method"] == "neural_quantile_outputs"
    assert result.metadata["n_series"] == 5
    assert result.metadata["deterministic"] is True


@requires_neural
def test_deepar_executor_enforces_the_panel_gate(monkeypatch):
    """Панель < min_series ДОХОДИТ до адаптера и честно отказывается:
    registry-гейт требует related_series, адаптер -- min_series=5."""
    import apps.api.model_impls.deepar as deepar_module

    monkeypatch.setattr(deepar_module, "DEEPAR_MAX_STEPS", 20)
    request = ModelExecutionRequest(
        target=[float(value) for value in range(1, 41)],
        horizon=4, params={},
        related_series={"a": [1.0] * 40, "b": [2.0] * 40},
    )
    with pytest.raises(ValueError, match="панель"):
        MODEL_EXECUTION_REGISTRY.execute("deepar", request)


@requires_neural
def test_deepar_panel_engine_runs_oof_cohort(monkeypatch):
    """Panel-движок: реальный нейро-фит на панели (глобальная модель) на
    точных EDA folds; OOF-точки target-ряда; cohort -- нейро-контракт
    Task 137 с panel=true/n_series/min_series."""
    import pandas as pd

    import apps.api.model_impls.deepar as deepar_module
    from apps.api.backtesting import build_backtest_plan, run_panel_backtest_plan
    from apps.api.multivariate_contract import build_endogenous_system
    from apps.api.neural_contract import (
        NeuralTrainingConfig,
        build_exogenous_plan,
        interval_levels_for_alpha,
        neural_cohort_contract,
    )

    monkeypatch.setattr(deepar_module, "DEEPAR_MAX_STEPS", 20)
    target = [100.0 + 0.3 * step + 5 * math.sin(2 * math.pi * step / 12)
              for step in range(72)]
    related = {
        "co2": [50.0 + 0.1 * step for step in range(72)],
        "temp": [10.0 + 3.0 * math.sin(2 * math.pi * step / 12)
                 for step in range(72)],
        "load": [80.0 - 0.2 * step for step in range(72)],
        "price": [20.0 + 0.4 * step for step in range(72)],
    }
    system = build_endogenous_system(
        {"value": target, **related},
        timestamps=[
            value.isoformat()
            for value in pd.date_range("2018-01-01", periods=72, freq="MS")
        ],
    )
    validation = {
        "strategy": "expanding", "horizon": 3, "n_splits": 2, "gap": 0,
        "folds": [
            {"fold": 1, "train_start": 0, "train_end": 65, "gap_size": 0, "test_start": 66, "test_end": 68},
            {"fold": 2, "train_start": 0, "train_end": 68, "gap_size": 0, "test_start": 69, "test_end": 71},
        ],
    }
    cohort = neural_cohort_contract(
        fingerprint="deepar-panel",
        n_series=len(system.names),
        min_series=DEEPAR_MIN_SERIES,
        exogenous=build_exogenous_plan(pd.DataFrame(
            {"unique_id": [], "ds": [], "y": []})),
        interval=interval_levels_for_alpha(0.05),
        loss="mqloss",
        config=NeuralTrainingConfig(seed=42, max_steps=20),
    )
    plan = build_backtest_plan(
        validation, n_observations=len(target), fingerprint="deepar-panel",
        target_column="value", seasonal_period=12,
        series_fingerprints={"value": "deepar-panel", **{
            name: f"fp-{name}" for name in related}},
        cohort_contract_override=cohort,
    )
    result = run_panel_backtest_plan(
        model_id="deepar", model_name="DeepAR", family_id="neural",
        system=system, plan=plan, seasonal_period=12,
    )
    assert result["status"] == "success"
    assert len(result["oof_predictions"]) == 6
    assert result["metrics"]["mae"] is not None
    assert result["objective"] == "level_forecast"
    assert result["cohort_contract"]["panel"] is True
    assert result["cohort_contract"]["n_series"] == 5
    assert result["cohort_contract"]["min_series"] == DEEPAR_MIN_SERIES
    assert result["panel"]["series_names"][0] == "value"
    assert result["execution_contract"]["model_id"] == "deepar"


def test_panel_cohort_is_isolated_from_univariate_cohorts():
    """Cohort-изоляция panel-постановки: план DeepAR (panel-контракт,
    fingerprints ВСЕЙ панели) даёт ДРУГОЙ cohort_id, чем univariate-план
    на ТЕХ ЖЕ fold'ах; comparison честно не смешивает их
    ("Cohort contracts моделей не совпадают" -- контрактный гейт)."""
    from apps.api.backtesting import build_backtest_plan
    from apps.api.neural_contract import (
        NeuralTrainingConfig,
        build_exogenous_plan,
        interval_levels_for_alpha,
        neural_cohort_contract,
    )

    validation = {
        "strategy": "expanding", "horizon": 3, "n_splits": 2, "gap": 0,
        "folds": [
            {"fold": 1, "train_start": 0, "train_end": 65, "gap_size": 0, "test_start": 66, "test_end": 68},
            {"fold": 2, "train_start": 0, "train_end": 68, "gap_size": 0, "test_start": 69, "test_end": 71},
        ],
    }
    univariate = build_backtest_plan(
        validation, n_observations=72, fingerprint="isolation",
        target_column="value", seasonal_period=12,
    )
    cohort = neural_cohort_contract(
        fingerprint="isolation",
        n_series=5, min_series=DEEPAR_MIN_SERIES,
        exogenous=build_exogenous_plan(pd.DataFrame(
            {"unique_id": [], "ds": [], "y": []})),
        interval=interval_levels_for_alpha(0.05),
        loss="mqloss",
        config=NeuralTrainingConfig(seed=42, max_steps=300),
    )
    panel = build_backtest_plan(
        validation, n_observations=72, fingerprint="isolation",
        target_column="value", seasonal_period=12,
        series_fingerprints={"value": "isolation", **{
            f"rel_{index}": f"fp-{index}" for index in range(4)}},
        cohort_contract_override=cohort,
    )
    assert panel.cohort_id != univariate.cohort_id
    assert panel.cohort_contract != univariate.cohort_contract
    assert panel.objective == univariate.objective == "level_forecast"


@requires_neural
def test_legacy_dispatch_export_honestly_refuses(monkeypatch):
    with pytest.raises(ValueError, match="панель"):
        exported_run_deepar_backtest([float(value) for value in range(96)],
                                     0.75, 12)
