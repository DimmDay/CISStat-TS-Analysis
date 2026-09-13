# scripts/audit_scripts/cert141_oracles.py
"""Независимые оракулы сертификации Task 141 (TFT vertical slice).

Методология сертификаций 136-140: оракулы работают на СОБСТВЕННЫХ
данных аудитора (генератор ниже, seed=141 -- НЕ фикстуры исполнителя),
мутируемые kill-подмножества -- в cert141_mutations.py (fresh
subprocess).

Структура:
- A -- реестр v2/dispatch/yaml/константы/импорт-гигиена (без фита);
- B -- fail-closed валидация параметров (мои значения; bool-коэрция,
  bounded-границы, whitelist, делимость d_k);
- C -- гейты данных: MIN_TRAIN, полоса неосуществимого окна
  [input+h-1] (гейт `nobs < input_size + horizon`; у TFT БЕЗ `+2`
  тройки -- conformal-калибровочных окон НЕТ: нативные квантили
  MQLoss, levels=(); граница nobs=input+h адмиссибельна -- проб
  библиотеки «TFT requires at least N timestamp(s)» = input+h);
- D -- живая проводка ручек до КОНСТРУКТОРА (fake-harness без torch:
  kwargs фабрики, MQLoss-quantiles, alias, budget, fold_seed);
- F -- fault-injection на синтетическом отклике: отсутствие медианы,
  отсутствие квантильной колонки, NaN/Inf, длина, квантильное
  пересечение (clamp-гейт), равенство на границе (<= vs <), capacity
  passthrough, contract-wrap, spy resolve_probabilistic_loss;
- G -- provenance-метаданные: intervals.method="neural_quantile_outputs",
  quantiles=[alpha/2, 0.5, 1-alpha/2] для всех alpha whitelist,
  width-суффиксы, ds-ось (integer/datetime);
- H -- executor-маппинг, quartet-когорта lstm/nbeats/nhits/tft,
  deepar catalog_only, легаси-эндпоинт (реальный фит);
- E -- реальные end-to-end фиты на МОИХ данных (env-гейт
  CISSTAT_CERT141_REAL=1; excluded из мутационного kill-прогона
  маркером real_fit): честная ширина интервала (НЕ схлопнута к
  медиане --,width-семантика НАХОДКИ Task 141 п.2), монотонность
  ширины по alpha, same-seed бит-паритет, cross-seed различимость.

Запуск (полный, с реальными фита́ми):
  OMP_NUM_THREADS=1 CISSTAT_CERT141_REAL=1 CISSTAT_NEURAL_MAX_STEPS=50 \
    python -m pytest scripts/audit_scripts/cert141_oracles.py -q
Kill-подмножество мутаций (быстрое, без реальных фитов):
  OMP_NUM_THREADS=1 python -m pytest scripts/audit_scripts/cert141_oracles.py -m "not real_fit" -q
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

REAL_MODE = os.environ.get("CISSTAT_CERT141_REAL") == "1"

from apps.api.neural_contract import (  # noqa: E402
    NEURAL_MAX_STEPS_BOUND,
    NeuralContractError,
    NeuralRuntimeCapacityError,
    fold_seed,
    interval_levels_for_alpha,
    interval_width_for_alpha,
)
from apps.api.model_execution import (  # noqa: E402
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionContractError,
    ModelExecutionRequest,
)
from apps.api.model_readiness import PRODUCTION_BACKTEST_MODEL_IDS  # noqa: E402
from apps.api.model_impls import tft as tft_mod  # noqa: E402
from apps.api.model_impls.tft import (  # noqa: E402
    ALPHA_OPTIONS,
    DEFAULT_PARAMS,
    HIDDEN_SIZE_BOUNDS,
    INPUT_SIZE_BOUNDS,
    N_HEAD_OPTIONS,
    TFT_ADAPTER_ID,
    TFT_MAX_STEPS,
    TFT_MIN_TRAIN,
    _quantile_plan,
    _tft_fit_predict,
    run_tft_backtest,
    validate_tft_params,
)

# ---------------------------------------------------------------------------
# Собственные данные аудитора (seed=141)
# ---------------------------------------------------------------------------


@pytest.fixture()
def my_series() -> np.ndarray:
    rng = np.random.default_rng(141)
    n = 140
    t = np.arange(n, dtype=float)
    return 10.0 + 0.05 * t + 4.0 * np.sin(2.0 * np.pi * t / 14.0) + rng.normal(
        0.0, 1.2, n
    )


# ---------------------------------------------------------------------------
# Fake-harness: детерминированная подмена нейро-runtime (без torch).
# Реальный happy-path на живом runtime закрывается секцией E.
# ---------------------------------------------------------------------------


class _RecordingTFT:
    last: dict[str, Any] | None = None

    def __init__(self, **kwargs):
        self.kwargs = dict(kwargs)
        _RecordingTFT.last = self.kwargs


class _RecordingMQLoss:
    last: list[float] | None = None

    def __init__(self, *, quantiles=None, **kwargs):
        _RecordingMQLoss.last = [float(q) for q in (quantiles or ())]


class _FakePytorchNS:
    MQLoss = _RecordingMQLoss


class _FakeLossesNS:
    pytorch = _FakePytorchNS


class _FakeModelsNS:
    TFT = _RecordingTFT


class _FakeNFModule:
    models = _FakeModelsNS
    losses = _FakeLossesNS


class _Harness:
    """Подмена train_and_forecast/_require_neuralforecast в tft-модуле.

    Оракулы остаются независимыми: синтетический отклик строится ПО
    контракту платформы (interval_width_for_alpha -- единый источник
    истины ширины), реальная живость пути закрывается секцией E.
    """

    def __init__(self, monkeypatch):
        self.calls: dict[str, Any] = {}
        self.loss_spy: list[dict[str, Any]] = []
        self.preds: pd.DataFrame | None = None
        self.raise_on_call: Exception | None = None

        real_resolve = tft_mod.resolve_probabilistic_loss

        def _spy_resolve(loss, *, levels=None):
            self.loss_spy.append({"loss": loss, "levels": tuple(levels or ())})
            return real_resolve(loss, levels=levels)

        def _fake_train_and_forecast(
            *, model_factory, freq, train_long, horizon, config,
            futr_df=None, static_df=None, levels=(), fold_index=0,
        ):
            self.calls.update({
                "freq": freq,
                "horizon": horizon,
                "config": config,
                "levels": tuple(levels),
                "fold_index": fold_index,
                "train_rows": int(len(train_long)),
            })
            if self.raise_on_call is not None:
                raise self.raise_on_call
            # бюджет зеркалит реальный neural_runtime: max_steps + сид,
            # дошедший до КОНСТРУКТОРА (fold_seed, ресертификация Task 137)
            budget = {
                "max_steps": config.max_steps,
                "random_seed": fold_seed(config.seed, fold_index=fold_index),
            }
            model_factory(budget)
            assert self.preds is not None, "тест не задал синтетический отклик"
            return self.preds

        monkeypatch.setattr(
            tft_mod, "_require_neuralforecast", lambda: _FakeNFModule()
        )
        monkeypatch.setattr(tft_mod, "resolve_probabilistic_loss", _spy_resolve)
        monkeypatch.setattr(
            tft_mod, "train_and_forecast", _fake_train_and_forecast
        )

    def set_preds(self, preds: pd.DataFrame) -> None:
        self.preds = preds


@pytest.fixture()
def harness(monkeypatch):
    return _Harness(monkeypatch)


@pytest.fixture()
def fit_guard(monkeypatch):
    """Fast-режим: дошли до fit -- AssertionError (мутант, миновавший
    пре-фит гейт, умирает здесь; в REAL-режиме guard НЕ ставится)."""
    reached: dict[str, bool] = {}
    if REAL_MODE:
        yield reached
        return

    def _guard(*args, **kwargs):
        reached["reached_fit"] = True
        raise AssertionError(
            "ORACLE: пре-фит гейт пропущен -- дошли до train_and_forecast"
        )

    monkeypatch.setattr(tft_mod, "train_and_forecast", _guard)
    yield reached


def _alpha_preds(
    alpha: float, horizon: int,
    lo: float = 1.0, med: float = 3.0, hi: float = 5.0,
) -> pd.DataFrame:
    width = interval_width_for_alpha(alpha)
    return pd.DataFrame({
        f"TFT-lo-{width}": np.full(horizon, lo, dtype=float),
        "TFT-median": np.full(horizon, med, dtype=float),
        f"TFT-hi-{width}": np.full(horizon, hi, dtype=float),
    })


def _run_fit(target, horizon, *, params=None, random_state=141, timestamps=None):
    return _tft_fit_predict(
        target, horizon, params=params, random_state=random_state,
        timestamps=timestamps,
    )


# ---------------------------------------------------------------------------
# Секция E: реальные фиты (env-гейт; маркер real_fit)
# ---------------------------------------------------------------------------

_REAL_CACHE: dict[tuple, dict[str, Any]] = {}

real_fit = pytest.mark.real_fit


def _real_fit(
    my_series, *, alpha, seed, horizon=12, steps=50, fresh=False,
) -> dict[str, Any]:
    key = (alpha, seed, horizon, steps)
    if not fresh and key in _REAL_CACHE:
        return _REAL_CACHE[key]
    previous = os.environ.get("CISSTAT_NEURAL_MAX_STEPS")
    os.environ["CISSTAT_NEURAL_MAX_STEPS"] = str(steps)
    try:
        payload = _run_fit(
            [float(value) for value in my_series], horizon,
            params={"alpha": alpha, "hidden_size": 16, "n_head": 2,
                    "input_size": 24},
            random_state=seed,
        )
    finally:
        if previous is None:
            os.environ.pop("CISSTAT_NEURAL_MAX_STEPS", None)
        else:
            os.environ["CISSTAT_NEURAL_MAX_STEPS"] = previous
    if not fresh:
        _REAL_CACHE[key] = payload
    return payload


def _scale(my_series: np.ndarray) -> float:
    return float(np.std(np.asarray(my_series, dtype=float)))


# ---------------------------------------------------------------------------
# A. Реестр / dispatch / yaml / константы / импорт-гигиена
# ---------------------------------------------------------------------------


class TestARegistryAndConstants:
    def test_a01_registry_record_shape(self):
        definition = MODEL_EXECUTION_REGISTRY.require("tft")
        assert definition.model_id == "tft"
        assert definition.family_id == "neural"
        assert definition.adapter_id == "neuralforecast-tft"
        assert definition.objective == "level_forecast"
        assert definition.input_kind == "univariate"
        assert definition.engine == "neuralforecast"
        assert definition.required_packages == ("neuralforecast",)
        assert definition.actions == frozenset(
            {"backtest", "tune", "diagnostics"}
        )
        assert definition.deterministic is True
        assert definition.dependency_group == "neural"
        assert definition.supports_prediction_intervals is True
        assert definition.supports_future_features is False
        assert definition.resource_capabilities.memory_class == "standard"
        assert definition.resource_capabilities.gpu == "optional"

    def test_a02_production_count_23_tft_in_deepar_out(self):
        ids = PRODUCTION_BACKTEST_MODEL_IDS
        assert len(ids) == 23
        assert "tft" in ids
        assert "deepar" not in ids  # catalog_only до среза Task 142

    def test_a03_dispatch_registered_conditionally(self):
        from apps.api.routers import models as models_router

        impl = models_router._BACKTEST_IMPLEMENTATIONS.get("tft")
        assert impl is run_tft_backtest
        # dispatch<->реестр согласован: bridge-проверка модуля
        assert models_router.PRODUCTION_BACKTEST_MODEL_IDS == frozenset(
            models_router._BACKTEST_IMPLEMENTATIONS
        )

    def test_a04_yaml_param_space_8_trials_gpu_axis_intact(self):
        import yaml

        data = yaml.safe_load(
            (REPO / "rules" / "modeling.yaml").read_text(encoding="utf-8")
        )
        tft_entry = None
        for family in data["families"]:
            for model in family.get("models", []):
                if model.get("id") == "tft":
                    tft_entry = model
        assert tft_entry is not None, "tft отсутствует в rules/modeling.yaml"
        space = tft_entry["param_space"]
        assert space == {
            "n_head": [2, 4],
            "hidden_size": [32, 64],
            "input_size": [24, 48],
        }
        trials = 1
        for values in space.values():
            trials *= len(values)
        assert trials == 8 and trials <= 64
        # методологическая ось D06 НЕ тронута (каталожная требует GPU;
        # production-готовность -- отдельная платформенная ось)
        assert tft_entry["requires_gpu"] is True
        assert tft_entry["min_observations"] == 200

    def test_a05_family_constants(self):
        assert TFT_ADAPTER_ID == "neuralforecast-tft"
        assert TFT_MAX_STEPS == 300
        assert 100 <= TFT_MAX_STEPS <= NEURAL_MAX_STEPS_BOUND
        assert TFT_MIN_TRAIN == 30
        assert N_HEAD_OPTIONS == (2, 4)
        assert HIDDEN_SIZE_BOUNDS == (8, 128)
        assert INPUT_SIZE_BOUNDS == (8, 104)
        assert ALPHA_OPTIONS == (0.01, 0.05, 0.10)
        assert DEFAULT_PARAMS == {
            "n_head": 4, "hidden_size": 32, "input_size": 24, "alpha": 0.05,
        }

    def test_a06_no_torch_at_module_import(self):
        code = (
            "import sys; import apps.api.model_impls.tft as m; "
            "assert 'torch' not in sys.modules, 'torch импортирован eagerly'; "
            "assert 'neuralforecast' not in sys.modules, "
            "'neuralforecast импортирован eagerly'; print('OK')"
        )
        env = dict(os.environ)
        env["OMP_NUM_THREADS"] = "1"
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=str(REPO), env=env,
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr[-500:]
        assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# B. Fail-closed валидация параметров (мои значения)
# ---------------------------------------------------------------------------


class TestBParamValidation:
    @pytest.mark.parametrize(
        "patched",
        [
            {"n_head": True},
            {"n_head": False},
            {"hidden_size": True},
            {"input_size": False},
            {"hidden_size": 32.5},
            {"hidden_size": "32"},
            {"n_head": None},
        ],
    )
    def test_b01_bool_and_non_int_rejected_with_message(self, patched):
        with pytest.raises(ValueError, match="целочисленный"):
            validate_tft_params(patched)

    @pytest.mark.parametrize(
        "patched,match",
        [
            ({"hidden_size": 7}, "вне bounded диапазона"),
            ({"hidden_size": 129}, "вне bounded диапазона"),
            ({"hidden_size": 132, "n_head": 4}, "вне bounded диапазона"),
            ({"input_size": 7}, "вне bounded диапазона"),
            ({"input_size": 105}, "вне bounded диапазона"),
            ({"n_head": 1}, "вне допустимого набора"),
            ({"n_head": 3}, "вне допустимого набора"),
            ({"n_head": 5}, "вне допустимого набора"),
            ({"alpha": 0.025}, "вне допустимого набора"),
            ({"alpha": 0.2}, "вне допустимого набора"),
            ({"alpha": "половина"}, "не числовой"),
        ],
    )
    def test_b02_bounds_and_whitelists(self, patched, match):
        with pytest.raises(ValueError, match=match):
            validate_tft_params(patched)

    @pytest.mark.parametrize(
        "hidden,n_head", [(10, 4), (33, 2), (30, 4), (9, 2)]
    )
    def test_b03_divisibility_gate(self, hidden, n_head):
        with pytest.raises(ValueError, match="кратным"):
            validate_tft_params({"hidden_size": hidden, "n_head": n_head})

    @pytest.mark.parametrize(
        "hidden,n_head",
        [(8, 2), (16, 2), (32, 4), (64, 4), (128, 4), (128, 2)],
    )
    def test_b04_divisible_pairs_admitted(self, hidden, n_head):
        normalized = validate_tft_params({"hidden_size": hidden, "n_head": n_head})
        assert normalized["hidden_size"] == hidden
        assert normalized["n_head"] == n_head

    def test_b05_unknown_keys_ignored_defaults_echoed(self):
        normalized = validate_tft_params({"foo": "bar", "loss": "mse"})
        assert normalized == dict(DEFAULT_PARAMS)

    def test_b06_input_nan_inf_rejected(self, my_series, fit_guard):
        # match -- формулировка ИМЕННО адаптерного гейта (_validated_target,
        # ДО ds-оси): контрактный to_long_format дублирует NaN-гейт ниже по
        # стеку (defense-in-depth, Task 137), но адаптер обязан отказывать
        # на своём слое, а не перекладывать отказ на контракт
        dirty = list(map(float, my_series))
        dirty[3] = float("nan")
        with pytest.raises(ValueError, match="импутация запрещена"):
            _run_fit(dirty, 12, params={"input_size": 24})
        dirty2 = list(map(float, my_series))
        dirty2[5] = float("inf")
        with pytest.raises(ValueError, match="импутация запрещена"):
            _run_fit(dirty2, 12, params={"input_size": 24})
        assert not fit_guard.get("reached_fit")

    def test_b07_empty_target_rejected(self, fit_guard):
        with pytest.raises(ValueError, match="пуст"):
            _run_fit([], 12)
        assert not fit_guard.get("reached_fit")

    @pytest.mark.parametrize("horizon", [0, -1, -7])
    def test_b08_horizon_positive(self, horizon, fit_guard):
        with pytest.raises(ValueError, match="horizon"):
            _run_fit([1.0] * 60, horizon, params={"input_size": 8})
        assert not fit_guard.get("reached_fit")


# ---------------------------------------------------------------------------
# C. Гейты данных: MIN_TRAIN и полоса неосуществимого окна
# ---------------------------------------------------------------------------


class TestCDataGates:
    @pytest.mark.parametrize(
        "input_size,horizon,nobs",
        [
            (24, 24, 47),
            (16, 20, 35),
            (8, 25, 32),
            (24, 10, 33),
            (12, 19, 30),
        ],
    )
    def test_c01_window_gate_honest_band(
        self, input_size, horizon, nobs, fit_guard
    ):
        # nobs = input+h-1 на ВСЕЙ полосе -- честный ValueError ДО фита
        # (у TFT нет conformal-калибровочных окон -- квантили нативны
        # MQLoss, поэтому гейт БЕЗ '+2' тройки; стабильность полосы
        # подтверждена пробом библиотеки «requires at least N» = input+h)
        series = [float(value) for value in np.arange(nobs, dtype=float)]
        with pytest.raises(ValueError, match="неосуществимое окно") as excinfo:
            _run_fit(
                series, horizon,
                params={"input_size": input_size, "hidden_size": 8,
                        "n_head": 2},
            )
        message = str(excinfo.value)
        assert f"input_size={input_size}" in message
        assert f"horizon={horizon}" in message
        assert not fit_guard.get("reached_fit")

    def test_c02_window_boundary_admissible(self, harness, my_series):
        # nobs == input+h -- граница полосы адмиссибельна (мутант
        # over-strict '+2' умрёт здесь: 30 < 14+16+2)
        harness.set_preds(_alpha_preds(0.05, 16))
        series = [float(value) for value in my_series[:30]]
        payload = _run_fit(
            series, 16,
            params={"input_size": 14, "hidden_size": 16, "n_head": 2},
        )
        assert len(payload["forecast"]) == 16
        assert harness.calls["horizon"] == 16

    def test_c03_min_train_gate(self, fit_guard):
        with pytest.raises(ValueError, match="слишком короткая"):
            _run_fit([1.0] * 29, 2, params={"input_size": 8})
        assert not fit_guard.get("reached_fit")

    def test_c04_ds_axis_integer_vs_datetime(self, harness, my_series):
        harness.set_preds(_alpha_preds(0.05, 6))
        series = [float(value) for value in my_series[:60]]
        payload_int = _run_fit(series, 6, params={"input_size": 8})
        assert payload_int["freq"] == {"kind": "integer", "value": 1}
        stamps = [
            stamp.strftime("%Y-%m-%d")
            for stamp in pd.date_range("2024-01-01", periods=60, freq="D")
        ]
        payload_dt = _run_fit(
            series, 6, params={"input_size": 8}, timestamps=stamps,
        )
        assert payload_dt["freq"]["kind"] == "datetime"
        assert str(payload_dt["freq"]["value"]).startswith("D")


# ---------------------------------------------------------------------------
# D. Живая проводка ручек до КОНСТРУКТОРА (fake-harness)
# ---------------------------------------------------------------------------


class TestDConstructorWiring:
    def test_d01_handles_reach_constructor(self, harness, my_series):
        harness.set_preds(_alpha_preds(0.05, 7))
        series = [float(value) for value in my_series[:80]]
        payload = _run_fit(
            series, 7,
            params={"hidden_size": 64, "n_head": 2, "input_size": 48},
            random_state=141,
        )
        kwargs = _RecordingTFT.last
        assert kwargs["h"] == 7
        assert kwargs["input_size"] == 48
        assert kwargs["hidden_size"] == 64
        assert kwargs["n_head"] == 2
        assert kwargs["alias"] == "TFT"
        assert _RecordingMQLoss.last == [0.025, 0.5, 0.975]
        # сид доходит до КОНСТРУКТОРА через fold_seed (ресертификация 137)
        expected_seed = fold_seed(141, fold_index=0)
        assert kwargs["random_seed"] == expected_seed
        assert harness.calls["config"].seed == 141
        assert payload["seed"] == 141
        assert np.array_equal(payload["forecast"], np.full(7, 3.0))
        assert np.array_equal(payload["lower"], np.full(7, 1.0))
        assert np.array_equal(payload["upper"], np.full(7, 5.0))

    def test_d02_env_lever_wiring_and_failclosed(self, harness, my_series, monkeypatch):
        harness.set_preds(_alpha_preds(0.05, 6))
        series = [float(value) for value in my_series[:60]]
        monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", "77")
        payload = _run_fit(series, 6, params={"input_size": 8})
        assert harness.calls["config"].max_steps == 77
        assert payload["max_steps"] == 77
        monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", "  88  ")
        payload = _run_fit(series, 6, params={"input_size": 8})
        assert payload["max_steps"] == 88
        for garbage in ("abc", "2.5", "0", "-3", ""):
            if garbage == "":
                monkeypatch.delenv("CISSTAT_NEURAL_MAX_STEPS", raising=False)
                assert tft_mod._resolve_max_steps() == TFT_MAX_STEPS
                continue
            monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", garbage)
            with pytest.raises(ValueError, match="не целое >= 1"):
                tft_mod._resolve_max_steps()

    def test_d03_conformal_not_activated(self, harness, my_series):
        # levels=() -- conformal-контур НЕ активируется (квантили нативны)
        harness.set_preds(_alpha_preds(0.05, 6))
        series = [float(value) for value in my_series[:60]]
        _run_fit(series, 6, params={"input_size": 8})
        assert harness.calls["levels"] == ()
        assert harness.loss_spy[0]["loss"] == "mqloss"


# ---------------------------------------------------------------------------
# F. Fault-injection на синтетическом отклике
# ---------------------------------------------------------------------------


class TestFFaultInjection:
    def test_f01_median_missing_fail_closed(self, harness, my_series):
        width = interval_width_for_alpha(0.05)
        harness.set_preds(pd.DataFrame({
            "TFT": np.full(6, 3.0),  # bare-колонка при probabilistic-loss
            f"TFT-lo-{width}": np.full(6, 1.0),
            f"TFT-hi-{width}": np.full(6, 5.0),
        }))
        series = [float(value) for value in my_series[:60]]
        with pytest.raises(ValueError, match="без медианы"):
            _run_fit(series, 6, params={"input_size": 8})

    def test_f02_quantile_column_missing(self, harness, my_series):
        harness.set_preds(pd.DataFrame({"TFT-median": np.full(6, 3.0)}))
        series = [float(value) for value in my_series[:60]]
        with pytest.raises(ValueError, match="отсутствует"):
            _run_fit(series, 6, params={"input_size": 8})

    def test_f03_nan_in_output_rejected(self, harness, my_series):
        preds = _alpha_preds(0.05, 6)
        preds.iloc[2, preds.columns.get_loc("TFT-median")] = float("nan")
        harness.set_preds(preds)
        series = [float(value) for value in my_series[:60]]
        with pytest.raises(ValueError, match="NaN/Inf"):
            _run_fit(series, 6, params={"input_size": 8})

    def test_f04_wrong_length_rejected(self, harness, my_series):
        harness.set_preds(_alpha_preds(0.05, 7))  # horizon=6, строк 7
        series = [float(value) for value in my_series[:60]]
        with pytest.raises(ValueError, match="длина прогноза"):
            _run_fit(series, 6, params={"input_size": 8})

    def test_f05_quantile_crossing_honest_failure(self, harness, my_series):
        # heads MQLoss независимы: пересечение теоретически возможно --
        # живой clamp-гейт честно отказывает fold'а, без clamp-подмен
        harness.set_preds(_alpha_preds(0.05, 6, lo=5.0, med=3.0, hi=1.0))
        series = [float(value) for value in my_series[:60]]
        with pytest.raises(NeuralContractError, match="инвариант"):
            _run_fit(series, 6, params={"input_size": 8})

    def test_f06_equality_boundary_admitted(self, harness, my_series):
        # clamp-гейт -- НЕСТРОГИЙ: lower == median на границе допустим
        preds = _alpha_preds(0.05, 6, lo=1.0, med=1.0, hi=5.0)
        preds.iloc[3, preds.columns.get_loc("TFT-median")] = 1.0
        harness.set_preds(preds)
        series = [float(value) for value in my_series[:60]]
        payload = _run_fit(series, 6, params={"input_size": 8})
        assert float(payload["lower"][3]) == float(payload["forecast"][3])

    def test_f07_capacity_error_passthrough(self, harness, my_series):
        harness.raise_on_call = NeuralRuntimeCapacityError("память")
        harness.set_preds(_alpha_preds(0.05, 6))
        series = [float(value) for value in my_series[:60]]
        with pytest.raises(NeuralRuntimeCapacityError):
            _run_fit(series, 6, params={"input_size": 8})

    def test_f08_contract_error_wrapped(self, harness, my_series):
        harness.raise_on_call = NeuralContractError("дс-ось сломана")
        harness.set_preds(_alpha_preds(0.05, 6))
        series = [float(value) for value in my_series[:60]]
        with pytest.raises(ValueError, match="TFT: дс-ось сломана"):
            _run_fit(series, 6, params={"input_size": 8})

    def test_f09_resolve_probabilistic_loss_called(self, harness, my_series):
        # контрактный гейт Task 137 обязан вызываться с планом уровней
        harness.set_preds(_alpha_preds(0.05, 6))
        series = [float(value) for value in my_series[:60]]
        _run_fit(series, 6, params={"input_size": 8})
        assert len(harness.loss_spy) == 1
        assert harness.loss_spy[0]["loss"] == "mqloss"
        assert harness.loss_spy[0]["levels"] == (2.5, 50.0, 97.5)


# ---------------------------------------------------------------------------
# G. Provenance-метаданные и квантильный план
# ---------------------------------------------------------------------------


class TestGProvenance:
    @pytest.mark.parametrize(
        "alpha,q_lo,q_hi,width,levels",
        [
            (0.01, 0.005, 0.995, 99.0, (0.5, 50.0, 99.5)),
            (0.05, 0.025, 0.975, 95.0, (2.5, 50.0, 97.5)),
            (0.10, 0.05, 0.95, 90.0, (5.0, 50.0, 95.0)),
        ],
    )
    def test_g01_quantile_plan_all_alphas(self, alpha, q_lo, q_hi, width, levels):
        plan = _quantile_plan(alpha)
        assert plan["method"] == "neural_quantile_outputs"
        assert plan["loss"] == "mqloss"
        assert plan["quantiles"] == (q_lo, 0.5, q_hi)
        assert plan["width"] == width
        assert plan["levels"] == tuple(float(level) for level in levels)
        # width -- контрактная ШИРИНА (НАХОДКА Task 141 п.2), единый
        # источник истины с тройкой lstm/nbeats/nhits
        assert plan["width"] == interval_width_for_alpha(alpha)
        contract = interval_levels_for_alpha(alpha)
        assert plan["levels"] == tuple(float(level) for level in contract.levels)

    def test_g02_payload_metadata_provenance(self, harness, my_series):
        harness.set_preds(_alpha_preds(0.05, 6))
        series = [float(value) for value in my_series[:60]]
        payload = _run_fit(series, 6, params={"input_size": 8}, random_state=9)
        assert payload["adapter_id"] == "neuralforecast-tft"
        assert payload["deterministic"] is True
        assert payload["random_state"] == 9
        assert payload["intervals"] == {
            "method": "neural_quantile_outputs",
            "loss": "mqloss",
            "alpha": 0.05,
            "quantiles": [0.025, 0.5, 0.975],
            "levels": [2.5, 50.0, 97.5],
        }
        assert payload["params"] == {
            "n_head": 4, "hidden_size": 32, "input_size": 8, "alpha": 0.05,
        }
        assert payload["nobs"] == 60


# ---------------------------------------------------------------------------
# H. Executor / quartet-когорта / deepar / легаси-эндпоинт
# ---------------------------------------------------------------------------


class TestHCohortAndExecutor:
    def test_h01_quartet_cohort_identity(self):
        quartet = ("lstm", "nbeats", "nhits", "tft")
        definitions = [MODEL_EXECUTION_REGISTRY.require(mid) for mid in quartet]
        first = definitions[0]
        for definition in definitions[1:]:
            assert definition.objective == first.objective == "level_forecast"
            assert definition.input_kind == first.input_kind == "univariate"
            assert definition.engine == first.engine == "neuralforecast"
            assert definition.dependency_group == "neural"
            assert definition.actions == first.actions
            assert definition.required_packages == first.required_packages

    def test_h02_deepar_still_catalog_only(self):
        # deepar -- ЧЕСТНЫЙ catalog_only: в реестре исполнения ОТСУТСТВУЕТ
        # до своего среза Task 142 (панель min_series=5)
        assert "deepar" not in MODEL_EXECUTION_REGISTRY.model_ids
        assert "deepar" not in PRODUCTION_BACKTEST_MODEL_IDS

    def test_h03_executor_payload_mapping(self, harness, my_series):
        harness.set_preds(_alpha_preds(0.05, 5))
        series = [float(value) for value in my_series[:60]]
        result = MODEL_EXECUTION_REGISTRY.execute(
            "tft",
            ModelExecutionRequest(
                target=series, horizon=5, seasonal_period=1,
                params={"input_size": 8}, random_state=141,
            ),
        )
        assert len(result.forecast) == 5
        assert result.metadata["adapter_id"] == "neuralforecast-tft"
        assert result.metadata["max_steps"] == TFT_MAX_STEPS
        assert result.metadata["seed"] == 141
        assert result.metadata["deterministic"] is True
        assert result.metadata["intervals"]["method"] == (
            "neural_quantile_outputs"
        )

    def test_h04_feature_channels_rejected_for_univariate(self):
        with pytest.raises(ModelExecutionContractError):
            MODEL_EXECUTION_REGISTRY.execute(
                "tft",
                ModelExecutionRequest(
                    target=[1.0] * 60, horizon=5,
                    train_features={"x1": [1.0] * 60},
                ),
            )

    @real_fit
    @pytest.mark.skipif(
        not REAL_MODE, reason="реальный фит -- CISSTAT_CERT141_REAL=1"
    )
    def test_h05_legacy_endpoint_real_fit(self, my_series):
        metrics = run_tft_backtest(
            [float(value) for value in my_series], 0.75, 7,
        )
        assert np.isfinite(metrics.mae) and metrics.mae >= 0
        assert np.isfinite(metrics.rmse) and metrics.rmse >= 0
        assert metrics.rmse >= metrics.mae  # неравенство Коши-Буняковского
        # короткий ряд -- честный отказ (НЕ zeros, НЕ naive-fallback)
        with pytest.raises(ValueError):
            run_tft_backtest([float(v) for v in my_series[:12]], 0.75, 7)


# ---------------------------------------------------------------------------
# E. Реальные end-to-end фиты на МОИХ данных
# ---------------------------------------------------------------------------


@real_fit
@pytest.mark.skipif(
    not REAL_MODE, reason="реальные фиты -- CISSTAT_CERT141_REAL=1"
)
class TestERealRuntime:
    def test_e01_real_run_shape_provenance_and_honest_width(self, my_series):
        payload = _real_fit(my_series, alpha=0.05, seed=141)
        horizon = 12
        assert len(payload["forecast"]) == horizon
        assert len(payload["lower"]) == horizon
        assert len(payload["upper"]) == horizon
        point = np.asarray(payload["forecast"], dtype=float)
        lower = np.asarray(payload["lower"], dtype=float)
        upper = np.asarray(payload["upper"], dtype=float)
        # clamp-инвариант на живом прогоне
        assert (lower <= point).all() and (point <= upper).all()
        # ЧЕСТНАЯ ШИРИНА (width-семантика НАХОДКИ Task 141 п.2): границы
        # -- 2.5/97.5 процентили, НЕ схлопнуты к медиане (урок тройки:
        # lo-2.5 там был 48.75-м процентилем)
        scale = _scale(my_series)
        assert (lower < point).all() and (point < upper).all()
        assert (point - lower).mean() >= 0.01 * scale
        assert (upper - point).mean() >= 0.01 * scale
        assert payload["intervals"]["method"] == "neural_quantile_outputs"
        assert payload["intervals"]["quantiles"] == [0.025, 0.5, 0.975]
        assert payload["max_steps"] == 50
        assert payload["seed"] == 141
        assert payload["deterministic"] is True

    def test_e02_real_interval_width_monotonic_in_alpha(self, my_series):
        wide = np.asarray(
            _real_fit(my_series, alpha=0.01, seed=141)["lower"], dtype=float
        )
        wide_u = np.asarray(
            _real_fit(my_series, alpha=0.01, seed=141)["upper"], dtype=float
        )
        mid = np.asarray(
            _real_fit(my_series, alpha=0.05, seed=141)["lower"], dtype=float
        )
        mid_u = np.asarray(
            _real_fit(my_series, alpha=0.05, seed=141)["upper"], dtype=float
        )
        narrow = np.asarray(
            _real_fit(my_series, alpha=0.10, seed=141)["lower"], dtype=float
        )
        narrow_u = np.asarray(
            _real_fit(my_series, alpha=0.10, seed=141)["upper"], dtype=float
        )
        # W(0.01) > W(0.05) > W(0.10) по средней ширине
        w_wide = (wide_u - wide).mean()
        w_mid = (mid_u - mid).mean()
        w_narrow = (narrow_u - narrow).mean()
        assert w_wide > w_mid > w_narrow

    def test_e03_real_determinism_same_seed_cross_seed(self, my_series):
        first = _real_fit(my_series, alpha=0.05, seed=141, fresh=True)
        second = _real_fit(my_series, alpha=0.05, seed=141, fresh=True)
        assert np.array_equal(
            np.asarray(first["forecast"], dtype=float),
            np.asarray(second["forecast"], dtype=float),
        )
        assert np.array_equal(
            np.asarray(first["lower"], dtype=float),
            np.asarray(second["lower"], dtype=float),
        )
        assert np.array_equal(
            np.asarray(first["upper"], dtype=float),
            np.asarray(second["upper"], dtype=float),
        )
        other = _real_fit(my_series, alpha=0.05, seed=142, fresh=True)
        assert not np.allclose(
            np.asarray(first["forecast"], dtype=float),
            np.asarray(other["forecast"], dtype=float),
        )

