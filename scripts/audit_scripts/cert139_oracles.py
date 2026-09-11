# scripts/audit_scripts/cert139_oracles.py
"""Независимые оракулы сертификации Task 139 (N-BEATS vertical slice).

Аудит исполненной коллегой задачи, прецедент cert138_oracles.py. Все
оракулы -- на СОБСТВЕННЫХ данных/фикстурах аудитора (синус+шум, seed 2026;
не пересекаются с фикстурами исполнителя _series/default_rng(8)) и
проверяют СВОЙСТВА платформы, а не повторяют ассерты исполнителя:

O1  детерминизм: same-seed бит-паритет, cross-seed различие (свои данные);
O2  stack_config имеет РЕАЛЬНЫЙ эффект (interpretable != generic) -- класс
    silent-swap (исполнитель проверял только "generic запускается");
O3  bounded-ручки имеют реальный эффект (hidden_size/input_size доходят
    до конструктора) -- класс literal-dup;
O4  boundary-семантика гейтов: MIN_TRAIN=30 и окно input_size+horizon
    различаются по сообщениям на точных границах (29/30 точек);
F1  НАХОДКА-1 (characterization): полоса [input+horizon, input+horizon+1]
    -- адаптерный гейт пропускает, библиотека отказывает RAW Exception
    (не ValueError) -- honesty-гэп на границе, не-блокирующая;
F2  НАХОДКА-2 (characterization): ручка mlp_layers [1,4] неисполнима:
    1 -- raw IndexError конструктора, 3/4 -- молча эквивалентны 2
    (библиотека читает только пары [0]->[1] inner-списка);
O5  семантика выбора interval-колонок (lo=levels[0], hi=levels[-1]) через
    fault-injection синтетического кадра + выходной isfinite-гейт;
O6  двухслойный spy проводки бюджета/сида: env-override доходит до
    NeuralTrainingConfig, фабрика разворачивает budget в КОНСТРУКТОР;
O7  тройная согласованность реестр<->dispatch<->readiness (21 модель);
O8  yaml::nbeats param_space: декартово произведение = 8 trials, значения
    внутри adapter-bounds, requires_gpu не тронут (методологическая ось);
O9  metadata executor'а честна (max_steps/seed/stack_config/deterministic);
O10 env-семантика CISSTAT_NEURAL_MAX_STEPS: дефолт/override/whitespace/
    мусор (fail-closed) -- независимо от исполнителя;
O11 таксономия NeuralRuntimeCapacityError + equality-граница guard'а
    (available == required -- пропуск; off-by-one класс);
O12 legacy-эндпоинт: честный отказ на коротком ряде (без Naive-fallback),
    реальные конечные метрики на рабочем ряде.

Запуск: OMP_NUM_THREADS=1 python3 -m pytest scripts/audit_scripts/cert139_oracles.py -q
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("neuralforecast", reason="neural runtime -- опциональная группа")

from apps.api.model_execution import (  # noqa: E402
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionRequest,
    _nbeats_executor,
)
from apps.api.model_impls import nbeats as nbeats_module  # noqa: E402
from apps.api.model_impls.nbeats import (  # noqa: E402
    HIDDEN_SIZE_BOUNDS,
    INPUT_SIZE_BOUNDS,
    MLP_LAYERS_BOUNDS,
    NBEATS_MAX_STEPS,
    NBEATS_MIN_TRAIN,
    STACK_OPTIONS,
    _nbeats_fit_predict,
    _resolve_max_steps,
    run_nbeats_backtest,
)
from apps.api.model_readiness import (  # noqa: E402
    PRODUCTION_BACKTEST_MODEL_IDS,
)
from apps.api.model_jobs import _RESOURCE_POLICIES  # noqa: E402
from apps.api.neural_contract import (  # noqa: E402
    NeuralContractError,
    NeuralRuntimeCapacityError,
    interval_levels_for_alpha,
)
from apps.api.neural_resources import (  # noqa: E402
    NEURAL_MIN_MEMORY_MB,
    ensure_neural_memory_capacity,
)

FAST_BUDGET = "6"


# ── собственные данные аудитора (НЕ фикстуры исполнителя) ────────────────

def _sine_series(n: int = 90, seed: int = 2026) -> list[float]:
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)
    return (5.0 + 1.7 * np.sin(2.0 * np.pi * t / 12.0) + 0.03 * t
            + rng.normal(0.0, 0.15, n)).tolist()


@pytest.fixture()
def fast_env(monkeypatch):
    monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", FAST_BUDGET)
    return FAST_BUDGET


# ── O1: детерминизм на своих данных ──────────────────────────────────────

def test_o1_same_seed_bit_identical_and_cross_seed_differs(fast_env):
    a = _nbeats_fit_predict(_sine_series(), 6, random_state=2026)
    b = _nbeats_fit_predict(_sine_series(), 6, random_state=2026)
    c = _nbeats_fit_predict(_sine_series(), 6, random_state=2027)
    assert np.array_equal(np.asarray(a["forecast"]), np.asarray(b["forecast"]))
    assert not np.array_equal(np.asarray(a["forecast"]), np.asarray(c["forecast"]))
    assert a["seed"] == 2026 and c["seed"] == 2027


# ── O2: стековая альтернатива имеет реальный эффект ─────────────────────

def test_o2_stack_config_alternatives_produce_different_forecasts(fast_env):
    base = dict(zip(
        ("hidden_size", "mlp_layers", "input_size"), (16, 2, 16),
    ))
    inter = _nbeats_fit_predict(
        _sine_series(), 6, params={**base, "stack_config": "interpretable"},
        random_state=2026,
    )
    generic = _nbeats_fit_predict(
        _sine_series(), 6, params={**base, "stack_config": "generic"},
        random_state=2026,
    )
    assert inter["stack_config"] == "interpretable"
    assert generic["stack_config"] == "generic"
    diff = float(np.max(np.abs(np.asarray(inter["forecast"])
                               - np.asarray(generic["forecast"]))))
    assert diff > 0.0, "stack_config не влияет на прогноз (silent-swap?)"


# ── O3: bounded-ручки доходят до конструктора (эффект конфига) ───────────

@pytest.mark.parametrize(
    ("handle", "low", "high"),
    [("hidden_size", 8, 128), ("input_size", 8, 48)],
)
def test_o3_bounded_handles_have_real_effect(handle, low, high, fast_env):
    fixed = {"hidden_size": 16, "mlp_layers": 2, "input_size": 16}
    lo = _nbeats_fit_predict(_sine_series(), 6,
                             params={**fixed, handle: low}, random_state=2026)
    hi = _nbeats_fit_predict(_sine_series(), 6,
                             params={**fixed, handle: high}, random_state=2026)
    diff = float(np.max(np.abs(np.asarray(lo["forecast"])
                               - np.asarray(hi["forecast"]))))
    assert diff > 0.0, f"{handle} не влияет на прогноз (literal-dup?)"


# ── O4: boundary-семантика гейтов окна и MIN_TRAIN ───────────────────────

def test_o4_window_and_min_train_gates_distinct_boundaries():
    # (a) n=29 < input_size=28 + horizon=2 -> гейт ОКНА до MIN_TRAIN? нет:
    # MIN_TRAIN=30 проверяется первым -- 29 < 30 -> сообщение MIN_TRAIN.
    with pytest.raises(ValueError, match="минимум"):
        _nbeats_fit_predict(list(np.arange(29, dtype=float)), 2,
                            params={"input_size": 28})
    # (b) n=29, input_size=28, horizon=1: окно осуществимо (29 >= 29),
    # но MIN_TRAIN=30 -> всё ещё отказ MIN_TRAIN (граница снизу).
    with pytest.raises(ValueError, match="минимум"):
        _nbeats_fit_predict(list(np.arange(29, dtype=float)), 1,
                            params={"input_size": 28})
    # (c) n=30, input=28, horizon=3 -> окно 31 > 30 -> ОТДЕЛИМОЕ сообщение
    #    гейта окна (адаптер отказывает ДО фита).
    with pytest.raises(ValueError, match="окно"):
        _nbeats_fit_predict(_sine_series(30), 3, params={"input_size": 28})


# ── F1/F2: characterization задокументированных НАХОДОК аудита ──────────

@pytest.mark.parametrize("extra", [0, 1])
def test_f1_window_boundary_band_escapes_as_raw_exception(extra, fast_env):
    """НАХОДКА-1: в полосе n == input+horizon и n == input+horizon+1
    адаптерный гейт (nobs < input+horizon) пропускает, а библиотека
    (conformal-конфигурация требует n >= input+horizon+2) отказывает
    RAW Exception -- НЕ NeuralContractError/ValueError.  Движок
    бэктеста оборачивает в честный BacktestExecutionError (метрики не
    подменяются), потому находка НЕ-БЛОКИРУЮЩАЯ.  Регрессия: если
    адаптер ужесточат гейт, тест упадёт -- пересмотреть characterization."""
    n = 28 + 2 + extra
    with pytest.raises(Exception) as excinfo:
        _nbeats_fit_predict(list(np.arange(n, dtype=float)), 2,
                            params={"input_size": 28}, random_state=2026)
    assert not isinstance(excinfo.value, ValueError)
    # за границей полосы библиотека обучается честно:
    payload = _nbeats_fit_predict(
        list(np.arange(32, dtype=float)), 2,
        params={"input_size": 28}, random_state=2026,
    )
    assert len(payload["forecast"]) == 2


def test_f2_mlp_layers_surface_is_infeasible_as_declared(fast_env):
    """НАХОДКА-2: декларированная bounded-ручка MLP_LAYERS_BOUNDS=(1,4)
    фактически неисполнима: mlp_layers=1 проходит validate, но конструктор
    NBEATSBlock падает RAW IndexError (библиотека читает только пары
    [0]->[1] каждого inner-списка mlp_units); значения 3/4 проходят fit,
    но МОЛЧА эквивалентны 2 (лишние entries игнорируются).  Не-блокирующая:
    ручка вне param_space (тюнинг недоступен), дефолт 2 -- единственный
    исполнимый.  Регрессия: исправление маппинга сделает тест честным."""
    assert MLP_LAYERS_BOUNDS == (1, 4)
    with pytest.raises(Exception) as excinfo:
        _nbeats_fit_predict(_sine_series(60), 4, params={"mlp_layers": 1},
                            random_state=2026)
    assert not isinstance(excinfo.value, ValueError)  # raw IndexError
    base = _nbeats_fit_predict(_sine_series(60), 4, params={"mlp_layers": 2},
                               random_state=2026)
    for value in (3, 4):
        same = _nbeats_fit_predict(_sine_series(60), 4,
                                   params={"mlp_layers": value},
                                   random_state=2026)
        assert np.array_equal(np.asarray(base["forecast"]),
                              np.asarray(same["forecast"])), (
            "mlp_layers=3/4 перестали быть эквивалентными 2 -- "
            "пересмотреть characterization НАХОДКИ-2")


# ── O5: выбор interval-колонок + выходной isfinite (fault-injection) ─────

def _synthetic_preds(point: float, lo: dict[float, float],
                     hi: dict[float, float], n: int = 6) -> pd.DataFrame:
    frame = pd.DataFrame({"NBEATS": [point] * n})
    for level, value in lo.items():
        frame[f"NBEATS-lo-{level}"] = [value] * n
    for level, value in hi.items():
        frame[f"NBEATS-hi-{level}"] = [value] * n
    return frame


def test_o5_interval_column_selection_semantics(fast_env, monkeypatch):
    plan = interval_levels_for_alpha(0.05)
    assert plan.levels == (2.5, 50.0, 97.5)
    # lo-97.5 специально ВЫШЕ point: неверный выбор lo-колонки (levels[-1])
    # активирует clamp-гейт -- оракул ловит и выбор, и инвариант сразу.
    frame = _synthetic_preds(
        point=10.0,
        lo={2.5: 9.0, 50.0: 8.0, 97.5: 11.0},
        hi={2.5: 11.5, 50.0: 12.0, 97.5: 13.0},
    )
    monkeypatch.setattr(nbeats_module, "train_and_forecast",
                        lambda **kwargs: frame)
    payload = _nbeats_fit_predict(_sine_series(), 6, random_state=2026)
    assert np.allclose(payload["lower"], 9.0)   # lo уровня levels[0]
    assert np.allclose(payload["upper"], 13.0)  # hi уровня levels[-1]


def test_o5b_output_nonfinite_is_rejected(fast_env, monkeypatch):
    frame = _synthetic_preds(
        point=float("nan"),
        lo={2.5: 9.0, 50.0: 8.0, 97.5: 7.0},
        hi={2.5: 11.5, 50.0: 12.0, 97.5: 13.0},
    )
    monkeypatch.setattr(nbeats_module, "train_and_forecast",
                        lambda **kwargs: frame)
    with pytest.raises(ValueError, match="NaN/Inf"):
        _nbeats_fit_predict(_sine_series(), 6, random_state=2026)


# ── O6: двухслойный spy проводки бюджета и сида ──────────────────────────

def test_o6_budget_and_seed_wiring_two_layer_spy(fast_env, monkeypatch):
    captured: dict = {}

    def _spy_train_and_forecast(**kwargs):
        captured["config"] = kwargs["config"]
        captured["factory"] = kwargs["model_factory"]
        return _synthetic_preds(
            10.0, {2.5: 9.0, 50.0: 8.0, 97.5: 7.0},
            {2.5: 11.5, 50.0: 12.0, 97.5: 13.0},
        )

    monkeypatch.setattr(nbeats_module, "train_and_forecast",
                        _spy_train_and_forecast)
    _nbeats_fit_predict(_sine_series(), 6, random_state=2026)
    # Слой 1: адаптер передаёт в runtime config с env-бюджетом и сидом.
    assert captured["config"].max_steps == int(FAST_BUDGET)
    assert captured["config"].seed == 2026
    # Слой 2: фабрика честно разворачивает budget в КОНСТРУКТОР модели
    # (сконструированная модель несёт пробы бюджета/сида).
    model = captured["factory"]({"max_steps": 77, "random_seed": 91})
    assert int(model.max_steps) == 77
    assert int(model.random_seed) == 91
    assert model.alias == "NBEATS"


# ── O7: тройная согласованность реестр<->dispatch<->readiness ────────────

def test_o7_registry_dispatch_readiness_triple_consistency():
    from apps.api.model_impls.neural_runtime import (
        neuralforecast_runtime_available,
    )
    from apps.api.routers.models import _BACKTEST_IMPLEMENTATIONS

    definition = MODEL_EXECUTION_REGISTRY.get("nbeats")
    assert definition is not None
    assert definition.family_id == "neural"
    assert definition.adapter_id == "neuralforecast-nbeats"
    assert definition.objective == "level_forecast"
    assert definition.input_kind == "univariate"
    assert definition.actions == frozenset({"backtest", "tune", "diagnostics"})
    assert definition.engine == "neuralforecast"
    assert definition.required_packages == ("neuralforecast",)
    assert definition.deterministic is True
    assert definition.dependency_group == "neural"
    assert definition.supports_prediction_intervals is True
    assert definition.supports_future_features is False
    assert definition.resource_capabilities.gpu == "optional"
    assert definition.resource_capabilities.memory_class == "standard"

    available = neuralforecast_runtime_available()
    assert ("nbeats" in _BACKTEST_IMPLEMENTATIONS) is available
    assert ("nbeats" in PRODUCTION_BACKTEST_MODEL_IDS) is available
    # Строгий gate реестр<->dispatch точен в этой среде:
    assert set(_BACKTEST_IMPLEMENTATIONS) == set(PRODUCTION_BACKTEST_MODEL_IDS)
    # Срезы 140-142 остаются честными catalog_only:
    for pending in ("nhits", "tft", "deepar"):
        assert pending not in PRODUCTION_BACKTEST_MODEL_IDS
        assert pending not in _BACKTEST_IMPLEMENTATIONS
        assert MODEL_EXECUTION_REGISTRY.get(pending) is None or (
            MODEL_EXECUTION_REGISTRY.get(pending).dependency_group == "neural"
        )
    if available:
        assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 21


# ── O8: yaml param_space -- grid, bounds, методологическая ось ───────────

def test_o8_yaml_param_space_grid_and_bounds():
    import yaml

    with open("rules/modeling.yaml", "r", encoding="utf-8") as handle:
        rules = yaml.safe_load(handle)
    neural_family = next(
        family for family in rules["families"]
        if any(model.get("id") == "nbeats"
               for model in family.get("models", []))
    )
    entry = next(model for model in neural_family["models"]
                 if model.get("id") == "nbeats")
    space = entry["param_space"]
    product = (
        len(space["stack_config"]) * len(space["hidden_size"])
        * len(space["input_size"])
    )
    assert product == 8, "yaml grid обязан быть 8 trials (<= MAX_TRIALS)"
    assert set(space["stack_config"]) == set(STACK_OPTIONS)
    low_h, high_h = HIDDEN_SIZE_BOUNDS
    assert all(low_h <= value <= high_h for value in space["hidden_size"])
    low_i, high_i = INPUT_SIZE_BOUNDS
    assert all(low_i <= value <= high_i for value in space["input_size"])
    # Методологическая ось D06 не менялась (как у Task 138 -- lstm):
    assert entry["requires_gpu"] is True
    # Adapter bounds -- заявленный контракт (docstring/реестр Task 139):
    assert HIDDEN_SIZE_BOUNDS == (8, 128)
    assert MLP_LAYERS_BOUNDS == (1, 4)
    assert INPUT_SIZE_BOUNDS == (8, 104)


# ── O9: metadata executor'а честна ───────────────────────────────────────

def test_o9_executor_metadata_is_honest(fast_env):
    timestamps = pd.date_range("2025-01-01", periods=90, freq="D")
    request = ModelExecutionRequest(
        target=_sine_series(), horizon=6, random_state=2026,
        train_timestamps=[str(value) for value in timestamps],
    )
    result = _nbeats_executor(request)
    metadata = result.metadata
    assert metadata["adapter_id"] == "neuralforecast-nbeats"
    assert metadata["max_steps"] == int(FAST_BUDGET)
    assert metadata["seed"] == 2026
    assert metadata["deterministic"] is True
    assert metadata["stack_config"] == "interpretable"
    assert metadata["intervals"]["method"] == "conformal"
    assert metadata["freq"]["kind"] == "datetime"
    forecast = np.asarray(result.forecast, dtype=float)
    lower = np.asarray(result.lower_interval, dtype=float)
    upper = np.asarray(result.upper_interval, dtype=float)
    assert forecast.shape == (6,)
    assert (lower <= forecast).all() and (forecast <= upper).all()


# ── O10: env-семантика CISSTAT_NEURAL_MAX_STEPS ──────────────────────────

def test_o10_env_max_steps_default_override_whitespace_and_garbage(monkeypatch):
    monkeypatch.delenv("CISSTAT_NEURAL_MAX_STEPS", raising=False)
    assert _resolve_max_steps() == NBEATS_MAX_STEPS == 300
    monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", "12")
    assert _resolve_max_steps() == 12
    monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", "   ")
    assert _resolve_max_steps() == 300
    for garbage in ("abc", "0", "-3", "3.5"):
        monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", garbage)
        with pytest.raises(ValueError):
            _resolve_max_steps()


# ── O11: таксономия CapacityError + equality-граница guard'а ─────────────

def test_o11_capacity_error_taxonomy_and_equality_boundary():
    assert issubclass(NeuralRuntimeCapacityError, NeuralContractError)
    assert issubclass(NeuralContractError, ValueError)
    assert NEURAL_MIN_MEMORY_MB == _RESOURCE_POLICIES["standard"]["memory_limit_mb"]
    with pytest.raises(NeuralRuntimeCapacityError) as excinfo:
        ensure_neural_memory_capacity(reader=lambda: 512)
    assert "1024" in str(excinfo.value) and "512" in str(excinfo.value)
    # equality-граница: available == required -- ровно достаточный инстанс.
    ensure_neural_memory_capacity(reader=lambda: NEURAL_MIN_MEMORY_MB)
    # неизвестное окружение -- guard слепой (fail-open только здесь).
    ensure_neural_memory_capacity(reader=lambda: None)


# ── O12: legacy-эндпоинт -- честный отказ и реальные метрики ─────────────

def test_o12_legacy_endpoint_honest_refusal_and_real_metrics(fast_env):
    with pytest.raises(ValueError):
        run_nbeats_backtest([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 0.75, 12)
    series = _sine_series(80, seed=4096)
    metrics = run_nbeats_backtest(series, 0.75, 12)
    for value in (metrics.mae, metrics.rmse, metrics.mape,
                  metrics.mase, metrics.weighted_score):
        assert np.isfinite(value)
