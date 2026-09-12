# scripts/audit_scripts/cert140_oracles.py
"""Независимые оракулы сертификации Task 140 (N-HiTS vertical slice).

Методология сертификаций 136-139: оракулы работают на СОБСТВЕННЫХ
данных аудитора (генератор ниже, seed=140 -- НЕ фикстуры исполнителя),
мутируемые kill-подмножества -- в cert140_mutations.py (fresh
subprocess).

Структура (ревизия Task 140a -- находки F1'/F2' исправлены, оракулы
исправленного состояния; width-семантика Task 141a; реестровая
актуальность Task 141 -- 23 модели, нейро-четверка):
- A -- реестр/dispatch/yaml/константы (без нейро-runtime);
- B -- fail-closed валидация (мои значения);
- C -- гейт окна: честная полоса (F1' ИСПРАВЛЕНА в Task 140a: гейт
  `nobs < input_size + horizon + 2` -- честный ValueError с калибровоч-
  ной причиной на всей полосе [input+h, input+h+1]; проб
  task140a_fix_probe.py: формула стабильна на 5 конфигах);
- D -- живые ручки (F2' ИСПРАВЛЕНА в Task 140a: hidden_size/mlp_layers
  доходят до конструктора через pair-маппинг mlp_units -- конвенция
  пар [in, out] Task 139a; весь диапазон исполним и различим;
  скрытые слои КАЖДОГО из трёх identity-блоков несут маппинг);
- E -- интерполяция/детерминизм/env/ds-ось (мои данные);
- F -- fault-injection (clamp/isfinite/длина/capacity/wrap/guard) на
  суффиксах ШИРИНЫ lo-95.0/hi-95.0 (правка width-семантики Task 141a;
  дефектные колонки старого запроса lo-2.5/hi-97.5 -- ловушки);
- G -- уровни интервалов (процентили плана + width-дисклоужер) и выбор
  колонок;
- H -- сквозные: executor/session-движок/пара nbeats-nhits на ОДНОМ
  cohort'е (постановка Task 140), легаси-эндпоинт.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from apps.api.neural_contract import (  # noqa: E402
    NEURAL_MAX_STEPS_BOUND,
    NeuralContractError,
    NeuralRuntimeCapacityError,
    interval_levels_for_alpha,
    interval_width_for_alpha,
)

pytest.importorskip("neuralforecast", reason="neural runtime -- опциональная группа")

from apps.api.model_execution import (  # noqa: E402
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionContractError,
    ModelExecutionRequest,
)
from apps.api.model_impls import nhits as nhits_module  # noqa: E402
from apps.api.model_impls import nbeats as nbeats_module  # noqa: E402
from apps.api.model_impls.nhits import (  # noqa: E402
    DEFAULT_PARAMS,
    MLP_LAYERS_BOUNDS,
    NHITS_MAX_STEPS,
    NHITS_MIN_TRAIN,
    _interpolation_kwargs,
    _interval_column,
    _mlp_units_kwargs,
    _nhits_fit_predict,
    _resolve_max_steps,
    run_nhits_backtest,
    validate_nhits_params,
)
from apps.api.model_readiness import (  # noqa: E402
    PRODUCTION_BACKTEST_MODEL_IDS,
)
from apps.api.routers.models import (  # noqa: E402
    _BACKTEST_IMPLEMENTATIONS,
    _register_neural_dispatch,
)
from apps.api.schemas import BacktestMetrics  # noqa: E402


# ── Данные аудитора (НЕ фикстуры исполнителя) ────────────────────────────

def my_series(n: int = 90, seed: int = 140) -> list[float]:
    """Синус + тренд + шум, seed=140 -- собственный ряд аудитора."""
    rng = np.random.default_rng(seed)
    step = np.arange(n, dtype=float)
    values = 50.0 + 0.12 * step + 4.0 * np.sin(2.0 * np.pi * step / 12.0)
    values += rng.standard_normal(n) * 0.3
    return values.astype(float).tolist()


@pytest.fixture()
def fast_env(monkeypatch):
    """Скоростной бюджет: константа модуля укорочена, env не задана."""
    monkeypatch.delenv("CISSTAT_NEURAL_MAX_STEPS", raising=False)
    monkeypatch.setattr(nhits_module, "NHITS_MAX_STEPS", 6)
    monkeypatch.setattr(nbeats_module, "NBEATS_MAX_STEPS", 6)


# ── A. Реестр / dispatch / yaml / константы ──────────────────────────────

def test_o01_registry_entry_22_and_contract():
    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY

    descriptor = MODEL_EXECUTION_REGISTRY.describe("nhits")
    assert descriptor["model_id"] == "nhits"
    assert descriptor["family_id"] == "neural"
    assert descriptor["adapter_id"] == "neuralforecast-nhits"
    assert descriptor["objective"] == "level_forecast"
    assert descriptor["input_kind"] == "univariate"
    assert descriptor["engine"] == "neuralforecast"
    assert descriptor["deterministic"] is True
    assert set(descriptor["actions"]) == {"backtest", "tune", "diagnostics"}
    # Реестровая актуальность Task 141 (TFT -- четвертый исполнитель):
    # 23 модели, прецедент O7 cert139_oracles.
    assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 23
    assert "nhits" in PRODUCTION_BACKTEST_MODEL_IDS
    # Анти-тампер констант адаптера (моя копия, без надежды на тесты
    # исполнителя): бюджет в честном диапазоне, пол -- константа.
    assert isinstance(NHITS_MAX_STEPS, int)
    assert 100 <= NHITS_MAX_STEPS <= NEURAL_MAX_STEPS_BOUND
    assert NHITS_MIN_TRAIN == 30


def test_o02_dispatch_convention_and_env_gate():
    without: dict = {}
    _register_neural_dispatch(without, runtime_available=False)
    assert without == {}
    with_runtime: dict = {}
    _register_neural_dispatch(with_runtime, runtime_available=True)
    # Нейро-четверка Task 141 (lstm + nbeats + nhits + tft).
    assert set(with_runtime) == {"lstm", "nbeats", "nhits", "tft"}
    # Среда аудита имеет нейро-группу -- dispatch полный и согласован.
    assert "nhits" in _BACKTEST_IMPLEMENTATIONS
    assert frozenset(_BACKTEST_IMPLEMENTATIONS) == PRODUCTION_BACKTEST_MODEL_IDS


def test_o03_yaml_param_space_documents_the_hidden_axis():
    """param_space 2x2x2=8 с осью hidden_size [32, 64] -- ось задокументи-
    рована; с Task 140a ось ЖИВАЯ (F2' исправлена: ручки доходят до
    конструктора через pair-маппинг mlp_units, D-блок)."""
    from src.catalog.modeling_spec_loader import ModelingSpec

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    space = spec.get_model("nhits").param_space
    assert space == {
        "interpolation_config": ["hierarchical", "light"],
        "hidden_size": [32, 64],
        "input_size": [24, 48],
    }
    product = int(np.prod([len(v) for v in space.values()]))
    assert product == 8


# ── B. Fail-closed валидация (мои значения) ──────────────────────────────

def test_o04_bounds_and_whitelists_reject_my_values():
    for key, bad in (("hidden_size", 4), ("hidden_size", 10_000),
                     ("mlp_layers", 0), ("mlp_layers", 5),
                     ("input_size", 2), ("input_size", 200)):
        with pytest.raises(ValueError, match=key):
            validate_nhits_params({key: bad})
    with pytest.raises(ValueError, match="alpha"):
        validate_nhits_params({"alpha": 0.5})
    with pytest.raises(ValueError, match="interpolation_config"):
        validate_nhits_params({"interpolation_config": "wavelet"})


@pytest.mark.parametrize("handle", ["hidden_size", "mlp_layers", "input_size"])
def test_o05_bool_coercion_rejected_for_every_int_handle(handle):
    with pytest.raises(ValueError, match=handle):
        validate_nhits_params({handle: True})


def test_o06_horizon_zero_short_series_and_nonfinite_fail_closed():
    with pytest.raises(ValueError, match="horizon"):
        _nhits_fit_predict(my_series(40), 0)
    with pytest.raises(ValueError, match="слишком короткая"):
        _nhits_fit_predict(my_series(5), 2)
    # Пин АДАПТЕРНОГО гейта (не только контрактного слоя to_long_format,
    # который дублирует fail-closed глубже): уникальная фраза адаптера.
    with pytest.raises(ValueError, match="импутация запрещена"):
        _nhits_fit_predict([float("nan")] * 40, 2)
    with pytest.raises(ValueError, match="импутация запрещена"):
        _nhits_fit_predict([float("inf")] * 40, 2)


# ── C. Гейт окна: честная полоса (F1' исправлена в Task 140a) ─────────────

def test_o07_window_gate_honest_below_boundary(fast_env):
    """n = input+horizon-1 = 30 (input=28, h=3): адаптерный гейт даёт
    детерминированный ValueError ДО фита (fail-closed, мои данные)."""
    with pytest.raises(ValueError, match="неосуществимое окно"):
        _nhits_fit_predict(
            my_series()[:30], 3, params={"input_size": 28}, random_state=140,
        )


@pytest.mark.parametrize("nobs", [31, 32])
def test_o08_window_boundary_band_gets_honest_value_error_before_fit(
    fast_env, nobs,
):
    """F1' ИСПРАВЛЕНА (Task 140a; ранее -- characterization сырой полосы
    сертификации Task 140): полоса [input+h, input+h+1] -- теперь честный
    ValueError адаптера (сообщение называет калибровочные окна conformal)
    ДО фита, а не сырой Exception библиотеки; за границей полосы
    (n == input+h+2) библиотека обучается честно (O09; проб
    task140a_fix_probe.py: формула n_min = input+horizon+2 стабильна
    на 5 конфигах)."""
    with pytest.raises(ValueError, match="калибров"):
        _nhits_fit_predict(
            my_series()[:nobs], 3, params={"input_size": 28}, random_state=140,
        )


def test_o09_boundary_plus_two_fits_ok(fast_env):
    """n = input+horizon+2 = 33 -- фактический минимум конформного
    контура 3.2.2: фит проходит, payload полон и инвариантен."""
    payload = _nhits_fit_predict(
        my_series()[:33], 3, params={"input_size": 28}, random_state=140,
    )
    forecast = np.asarray(payload["forecast"], dtype=float)
    assert forecast.shape == (3,)
    assert np.isfinite(forecast).all()
    assert (np.asarray(payload["lower"]) <= forecast).all()
    assert (forecast <= np.asarray(payload["upper"])).all()
    assert payload["params"]["input_size"] == 28


# ── D. Живые ручки (F2' исправлена в Task 140a) ──────────────────────────

def test_o10_hidden_size_is_a_live_knob(fast_env):
    """F2' ИСПРАВЛЕНА (Task 140a; ранее -- characterization мёртвой
    ручки): hidden_size 8 vs 128 -- РАЗЛИЧИМЫЙ прогноз (pair-маппинг
    mlp_units доходит до конструктора), params-эхо честно значимо.
    Контраст-конвенция семейства: nbeats hidden_size 8 vs 128 -- тоже
    живая ручка (Task 139a)."""
    lo = _nhits_fit_predict(
        my_series(), 4, params={"hidden_size": 8}, random_state=140,
    )
    hi = _nhits_fit_predict(
        my_series(), 4, params={"hidden_size": 128}, random_state=140,
    )
    assert float(np.abs(
        np.asarray(lo["forecast"]) - np.asarray(hi["forecast"]),
    ).max()) > 0.0, "hidden_size не влияет на прогноз (ручка мертва?)"
    assert lo["params"]["hidden_size"] == 8
    assert hi["params"]["hidden_size"] == 128

    nb_lo = nbeats_module._nbeats_fit_predict(
        my_series(), 4, params={"hidden_size": 8}, random_state=140,
    )
    nb_hi = nbeats_module._nbeats_fit_predict(
        my_series(), 4, params={"hidden_size": 128}, random_state=140,
    )
    assert float(np.abs(
        np.asarray(nb_lo["forecast"]) - np.asarray(nb_hi["forecast"]),
    ).max()) > 0.0


def test_o11_mlp_layers_range_executable_and_distinguishable(fast_env):
    """F2' ИСПРАВЛЕНА (Task 140a; ранее -- characterization мёртвой
    ручки): весь диапазон mlp_layers [1, 4] исполним и попарно различим
    (pair-маппинг mlp_units = [[hidden, hidden] * layers] -- конвенция
    пар [in, out] Task 139a; проб task140a_fix_probe.py секция 3)."""
    assert MLP_LAYERS_BOUNDS == (1, 4)
    forecasts = {}
    for value in (1, 2, 3, 4):
        payload = _nhits_fit_predict(
            my_series(), 4, params={"mlp_layers": value}, random_state=140,
        )
        forecasts[value] = np.asarray(payload["forecast"], dtype=float)
    for low in (1, 2, 3):
        for high in (2, 3, 4):
            if low >= high:
                continue
            diff = float(np.abs(forecasts[low] - forecasts[high]).max())
            assert diff > 0.0, (
                f"mlp_layers={low} и {high} идентичны -- ручка мертва"
            )


class _SpyDone(Exception):
    """Sentinel: короткое замыкание spy-обёртки train_and_forecast."""


def test_o12_constructor_receives_declared_knobs(monkeypatch, fast_env):
    """Конструкторный spy (двухслойный, паттерн M18-урока), оракул
    ИСПРАВЛЕННОГО состояния (Task 140a): при hidden_size=128/mlp_layers=4
    модель НЕСЕТ pair-маппинг (первый Linear В 128, последний ИЗ 128,
    скрытые пары (128, 128) x 4 -- дефолт 512 не остаётся нигде);
    interpolation-kwargs ДОХОДЯТ (живая ручка) в обеих конфигурациях."""
    captured: dict = {}

    def spy(*, model_factory, config, **_kwargs):
        probe_budget = {
            "max_steps": 321, "random_seed": 777, "accelerator": "cpu",
            "enable_progress_bar": False, "early_stop_patience_steps": -1,
        }
        captured["model"] = model_factory(dict(probe_budget))
        raise _SpyDone()

    monkeypatch.setattr(nhits_module, "train_and_forecast", spy)
    for params in (
        {"hidden_size": 128, "mlp_layers": 4},
        {"interpolation_config": "light", "hidden_size": 8, "mlp_layers": 1},
    ):
        with pytest.raises(_SpyDone):
            _nhits_fit_predict(my_series(), 4, params=params, random_state=140)
        model = captured["model"]
        widths = [
            tuple(linear.weight.shape)
            for _, linear in model.blocks[0].named_modules()
            if isinstance(linear, torch.nn.Linear)
        ]
        declared = params["hidden_size"]
        assert widths, "ожидались Linear-слои блока"
        assert widths[0][0] == declared, widths
        assert widths[-1][1] == declared, widths
        inner = widths[1:-1]
        assert len(inner) == params["mlp_layers"], widths
        assert all(
            shape == (declared, declared) for shape in inner
        ), widths
        assert int(model.max_steps) == 321
        assert int(model.random_seed) == 777
        assert int(model.input_size) == DEFAULT_PARAMS["input_size"]
        assert model.alias == "NHITS"
        # n_pool_kernel_size не хранится атрибутом -- читается из
        # MaxPool1d.kernel_size блоков: hier -> [2,2,1], light -> [2,1,1].
        pools = []
        for block in model.blocks:
            kernel = block.pooling_layer.kernel_size
            pools.append(kernel[0] if isinstance(kernel, tuple) else kernel)
        if params.get("interpolation_config") == "light":
            assert pools == [2, 1, 1]
        else:
            assert pools == [2, 2, 1]


# ── E. Интерполяция / детерминизм / env / ds-ось (мои данные) ────────────

def test_o13_interpolation_config_is_live(fast_env):
    hier = _nhits_fit_predict(
        my_series(), 4, params={"interpolation_config": "hierarchical"},
        random_state=140,
    )
    light = _nhits_fit_predict(
        my_series(), 4, params={"interpolation_config": "light"},
        random_state=140,
    )
    assert hier["interpolation_config"] == "hierarchical"
    assert light["interpolation_config"] == "light"
    assert float(np.abs(
        np.asarray(hier["forecast"]) - np.asarray(light["forecast"]),
    ).max()) > 0.0


def test_o14_same_seed_bit_parity_and_cross_seed_divergence(fast_env):
    a = _nhits_fit_predict(my_series(), 4, random_state=140)
    b = _nhits_fit_predict(my_series(), 4, random_state=140)
    np.testing.assert_array_equal(
        np.asarray(a["forecast"]), np.asarray(b["forecast"]),
    )
    c = _nhits_fit_predict(my_series(), 4, random_state=314)
    assert float(np.abs(
        np.asarray(a["forecast"]) - np.asarray(c["forecast"]),
    ).max()) > 0.0


def test_o15_env_max_steps_default_override_and_garbage(monkeypatch):
    monkeypatch.delenv("CISSTAT_NEURAL_MAX_STEPS", raising=False)
    assert _resolve_max_steps() == NHITS_MAX_STEPS
    monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", "140")
    assert _resolve_max_steps() == 140
    monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", " 140 ")
    assert _resolve_max_steps() == 140
    for garbage in ("abc", "0", "-7", "1.5"):
        monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", garbage)
        with pytest.raises(ValueError, match="CISSTAT_NEURAL_MAX_STEPS"):
            _resolve_max_steps()


def test_o16_ds_axis_datetime_positional_and_missing(fast_env):
    dates = pd.date_range("2024-03-01", periods=90, freq="D")
    labeled = _nhits_fit_predict(
        my_series(), 4,
        timestamps=[value.strftime("%Y-%m-%d") for value in dates],
        random_state=140,
    )
    assert labeled["freq"] == {"kind": "datetime", "value": "D"}
    junk = _nhits_fit_predict(
        my_series(), 4,
        timestamps=[f"point_{index}" for index in range(90)],
        random_state=140,
    )
    assert junk["freq"] == {"kind": "integer", "value": 1}
    bare = _nhits_fit_predict(my_series(), 4, random_state=140)
    assert bare["freq"] == {"kind": "integer", "value": 1}


# ── F. Fault-injection (мои значения) ────────────────────────────────────

def _synthetic_preds(rows: int = 4, point: float = 1.0, lower: float = 0.0,
                     upper: float = 2.0) -> pd.DataFrame:
    """Суффиксы ШИРИНЫ 95.0 (правка width-семантики Task 141a: адаптер
    извлекает lo-95.0/hi-95.0); дефектные колонки старого запроса
    lo-2.5/hi-97.5 (48.75/98.75 процентили) присутствуют как ЛОВУШКИ
    (прецедент O5 cert139_oracles) -- неверный выбор ловушки активирует
    clamp-гейт в o17."""
    return pd.DataFrame({
        "NHITS": [point] * rows,
        "NHITS-lo-2.5": [lower + 0.1] * rows,   # ловушка (схлопнута к медиане)
        "NHITS-hi-97.5": [upper - 0.1] * rows,  # ловушка
        "NHITS-lo-95.0": [lower] * rows,
        "NHITS-hi-95.0": [upper] * rows,
    })


def test_o17_fault_injected_broken_clamp_is_rejected(monkeypatch, fast_env):
    monkeypatch.setattr(
        nhits_module, "train_and_forecast", lambda **_kw: _synthetic_preds(lower=5.0),
    )
    with pytest.raises(NeuralContractError, match="инвариант"):
        _nhits_fit_predict(my_series(), 4)


def test_o18_fault_injected_nan_point_is_rejected(monkeypatch, fast_env):
    preds = _synthetic_preds()
    preds.loc[1, "NHITS"] = float("nan")
    monkeypatch.setattr(nhits_module, "train_and_forecast", lambda **_kw: preds)
    with pytest.raises(ValueError, match="NaN/Inf"):
        _nhits_fit_predict(my_series(), 4)


def test_o19_fault_injected_wrong_length_is_rejected(monkeypatch, fast_env):
    monkeypatch.setattr(
        nhits_module, "train_and_forecast", lambda **_kw: _synthetic_preds(rows=2),
    )
    with pytest.raises(ValueError, match="длина прогноза"):
        _nhits_fit_predict(my_series(), 4)


def test_o20_capacity_error_passes_through(monkeypatch, fast_env):
    def capacity_refused(*, model_factory, **_kwargs):
        raise NeuralRuntimeCapacityError("инстанс ниже контрактуемого бюджета")

    monkeypatch.setattr(nhits_module, "train_and_forecast", capacity_refused)
    with pytest.raises(NeuralRuntimeCapacityError):
        _nhits_fit_predict(my_series(), 4)


def test_o21_contract_error_is_wrapped_with_adapter_prefix(monkeypatch, fast_env):
    def contract_boom(*, model_factory, **_kwargs):
        raise NeuralContractError("boom140")

    monkeypatch.setattr(nhits_module, "train_and_forecast", contract_boom)
    with pytest.raises(ValueError, match="N-HiTS: boom140"):
        _nhits_fit_predict(my_series(), 4)


def test_o22_memory_guard_refuses_below_budget(monkeypatch, fast_env):
    """Task 138c guard наследуется nhits-адаптером автоматически (через
    require_neuralforecast): читатель памяти -> 100 MB < 1024 MB --
    NeuralRuntimeCapacityError ДО тяжёлого импорта."""
    from apps.api import neural_resources

    monkeypatch.setattr(
        neural_resources, "read_instance_memory_mb", lambda: 100,
    )
    with pytest.raises(NeuralRuntimeCapacityError):
        _nhits_fit_predict(my_series(), 4)


# ── G. Уровни интервалов и выбор колонок ─────────────────────────────────

@pytest.mark.parametrize(("alpha", "levels", "width"), [
    (0.01, (0.5, 50.0, 99.5), 99.0),
    (0.05, (2.5, 50.0, 97.5), 95.0),
    (0.10, (5.0, 50.0, 95.0), 90.0),
])
def test_o23_alpha_plan_levels(fast_env, alpha, levels, width):
    """Процентили плана + width-дисклоужер (правка width-семантики
    Task 141a: metadata дисклоужирует ОБА плана -- levels и ширину
    запроса)."""
    payload = _nhits_fit_predict(
        my_series(), 4, params={"alpha": alpha}, random_state=140,
    )
    assert payload["intervals"]["alpha"] == alpha
    assert list(payload["intervals"]["levels"]) == list(levels)
    assert payload["intervals"]["width"] == width
    assert payload["intervals"]["width"] == interval_width_for_alpha(alpha)
    assert payload["intervals"]["method"] == "conformal"


def test_o24_interval_column_suffix_selection_is_exact():
    frame = pd.DataFrame({
        "NHITS": [1.0, 1.0],
        "NHITS-lo-2.5": [0.5, 0.5],
        "NHITS-lo-50.0": [0.9, 0.9],
        "NHITS-lo-97.5": [1.1, 1.1],
        "NHITS-hi-2.5": [1.2, 1.2],
        "NHITS-hi-50.0": [1.5, 1.5],
        "NHITS-hi-97.5": [1.9, 1.9],
    })
    np.testing.assert_array_equal(
        _interval_column(frame, "NHITS", "lo", 2.5), [0.5, 0.5],
    )
    np.testing.assert_array_equal(
        _interval_column(frame, "NHITS", "lo", 97.5), [1.1, 1.1],
    )
    np.testing.assert_array_equal(
        _interval_column(frame, "NHITS", "hi", 97.5), [1.9, 1.9],
    )
    with pytest.raises(ValueError, match="отсутствует"):
        _interval_column(frame, "NHITS", "lo", 42.0)


def test_o25_interpolation_kwargs_are_the_official_surface():
    assert _interpolation_kwargs("hierarchical") == {
        "n_pool_kernel_size": [2, 2, 1],
        "n_freq_downsample": [4, 2, 1],
    }
    assert _interpolation_kwargs("light") == {
        "n_pool_kernel_size": [2, 1, 1],
        "n_freq_downsample": [2, 1, 1],
    }


# ── H. Сквозные пути на моих данных ──────────────────────────────────────

def test_o26_executor_via_registry_contract(fast_env):
    result = MODEL_EXECUTION_REGISTRY.execute("nhits", ModelExecutionRequest(
        target=my_series(40), horizon=4, params={}, random_state=140,
    ))
    assert len(result.forecast) == 4
    assert result.lower_interval is not None and result.upper_interval is not None
    assert result.metadata["adapter_id"] == "neuralforecast-nhits"
    assert result.metadata["interpolation_config"] == "hierarchical"
    assert result.metadata["deterministic"] is True
    assert result.metadata["max_steps"] == 6
    assert result.metadata["seed"] == 140


def test_o27_registry_v2_gates_reject_objective_and_features():
    with pytest.raises(ModelExecutionContractError, match="objective"):
        MODEL_EXECUTION_REGISTRY.execute("nhits", ModelExecutionRequest(
            target=[1.0, 2.0, 3.0], horizon=2, objective="multivariate",
        ))
    with pytest.raises(ModelExecutionContractError, match="train_features"):
        MODEL_EXECUTION_REGISTRY.execute("nhits", ModelExecutionRequest(
            target=[1.0, 2.0, 3.0], horizon=2,
            train_features={"x140": [1.0, 2.0, 3.0]},
        ))


def test_o28_session_engine_cohort_and_fair_pair_on_my_data(fast_env):
    """Постановка Task 140 на МОИХ данных: nhits и nbeats проходят ОДИН
    план fold'ов в одном level-cohort; execution_contract различается
    только model-полями; OOF полон."""
    from apps.api.backtesting import build_backtest_plan, run_backtest_plan

    series = my_series(77, seed=2140)  # последний test_end=76 == n-1
    labels = [
        value.isoformat()
        for value in pd.date_range("2019-03-01", periods=len(series), freq="MS")
    ]
    validation = {
        "strategy": "expanding", "horizon": 3, "n_splits": 2, "gap": 0,
        "folds": [
            {"fold": 1, "train_start": 0, "train_end": 70, "gap_size": 0,
             "test_start": 71, "test_end": 73},
            {"fold": 2, "train_start": 0, "train_end": 73, "gap_size": 0,
             "test_start": 74, "test_end": 76},
        ],
    }
    plan = build_backtest_plan(
        validation, n_observations=len(series), fingerprint="cert140-audit",
        target_column="value", seasonal_period=12,
    )
    results = {
        model_id: run_backtest_plan(
            model_id=model_id,
            model_name="N-HiTS" if model_id == "nhits" else "N-BEATS",
            family_id="neural", series=series, labels=labels,
            plan=plan, seasonal_period=12,
        )
        for model_id in ("nhits", "nbeats")
    }
    assert all(result["status"] == "success" for result in results.values())
    assert all(len(result["oof_predictions"]) == 6 for result in results.values())
    assert all(result["metrics"]["mae"] is not None for result in results.values())
    contracts = {
        model_id: results[model_id]["execution_contract"]
        for model_id in ("nhits", "nbeats")
    }
    assert contracts["nhits"]["adapter_id"] == "neuralforecast-nhits"
    for key in ("version", "objective", "input_kind", "output_kind",
                "fit_policy", "dependency_group"):
        assert contracts["nhits"][key] == contracts["nbeats"][key], key


def test_o29_legacy_endpoint_metrics_and_honest_short_refusal(fast_env):
    metrics = run_nhits_backtest(my_series(96, seed=140), 0.75, 12)
    assert isinstance(metrics, BacktestMetrics)
    assert metrics.mae is not None and metrics.mae >= 0
    with pytest.raises(ValueError, match="слишком короткая"):
        run_nhits_backtest(my_series(10, seed=140), 0.8, 12)
