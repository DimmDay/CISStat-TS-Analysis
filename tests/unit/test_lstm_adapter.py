# tests/unit/test_lstm_adapter.py
"""Task 138 -- LSTM/GRU: адаптер на едином NeuralForecast-runtime
(neural_runtime.py Task 137), первый исполнитель нейро-семейства.

Прецедент пары garch/egarch в volatility-движке и random_forest в
legacy-dispatch: ЕДИНСТВЕННАЯ точка импорта torch/neuralforecast --
apps/api/model_impls/neural_runtime.py (лениво, fail-closed); адаптер:
- рекуррентная ячейка cell_type ∈ {LSTM, GRU} (единый каталожный id
  ``lstm`` «LSTM / GRU»; честная альтернатива -- bounded param_space
  yaml, а не два скрытых каркаса);
- ds-ось: парсимые регулярные метки времени -> datetime + честный
  pd.infer_freq; что-либо иное -> ПОЗИЦИОННАЯ целочисленная сетка
  (freq=1): NeuralForecast требует регулярную сетку, значения прогноза
  рекуррентной модели от меток не зависят -- конвенция задекларирована,
  никакого скрытого ресемплинга;
- интервалы -- официальный conformal-контур контракта Task 137
  (fit prediction_intervals + predict level), уровни из
  interval_levels_for_alpha; никаких «MC Dropout», которых нет в коде;
- fail-closed: короткий train, NaN/Inf, неизвестная ячейка, значения вне
  bounded-границ -- отказ fold'а БЕЗ Naive-fallback и clamp-подмен;
- детерминизм: random_state -> NeuralTrainingConfig.seed -> fold_seed ->
  random_seed КОНСТРУКТОРА модели (блокирующая находка сертификации
  Task 137): same-seed -- бит-паритет, другой seed -- другой прогноз
  (дифференциальные тесты, урок мутационной методологии).

Бюджет: LSTM_MAX_STEPS -- КОНСТАНТА модуля (единый бюджетный рычаг
контракта; тюнинг бюджета -- вне param_space, прецедент Task 136),
прижат анти-тампер тестом; в тестах укорачивается monkeypatch'ем для
скорости (реальное значение прижато отдельным тестом БЕЗ monkeypatch).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.neural_contract import (
    NEURAL_MAX_STEPS_BOUND,
    NeuralContractError,
    NeuralTrainingConfig,
    interval_levels_for_alpha,
)

pytest.importorskip("neuralforecast", reason="neural runtime -- опциональная группа")

from apps.api.model_impls import lstm as lstm_module  # noqa: E402
from apps.api.model_impls.lstm import (  # noqa: E402
    ALPHA_OPTIONS,
    CELL_OPTIONS,
    DEFAULT_PARAMS,
    LSTM_ADAPTER_ID,
    LSTM_MAX_STEPS,
    LSTM_MIN_TRAIN,
    _lstm_fit_predict,
    run_lstm_backtest,
    validate_lstm_params,
)
from apps.api.schemas import BacktestMetrics  # noqa: E402


# ── 1. Bounded params (fail-closed) ──────────────────────────────────────

def test_default_params_are_declared_and_normalization_fills_defaults():
    normalized = validate_lstm_params(None)
    assert normalized == DEFAULT_PARAMS
    # Чужие ключи (tbats_seasonal_periods и т.п.) игнорируются --
    # соглашение платформы (backtesting.py присылает общие params).
    merged = validate_lstm_params({"tbats_seasonal_periods": 12, "cell_type": "GRU"})
    assert merged["cell_type"] == "GRU"
    assert "tbats_seasonal_periods" not in merged


def test_unknown_cell_type_is_rejected_fail_closed():
    with pytest.raises(ValueError, match="cell_type"):
        validate_lstm_params({"cell_type": "RNN"})
    assert set(CELL_OPTIONS) == {"LSTM", "GRU"}


def test_numeric_params_outside_bounds_are_rejected():
    with pytest.raises(ValueError, match="hidden_size"):
        validate_lstm_params({"hidden_size": 4})
    with pytest.raises(ValueError, match="hidden_size"):
        validate_lstm_params({"hidden_size": 10_000})
    with pytest.raises(ValueError, match="encoder_n_layers"):
        validate_lstm_params({"encoder_n_layers": 0})
    with pytest.raises(ValueError, match="input_size"):
        validate_lstm_params({"input_size": 2})
    with pytest.raises(ValueError, match="alpha"):
        validate_lstm_params({"alpha": 0.5})


def test_adapter_budget_constant_is_pinned_to_the_contract_bound():
    """Анти-тампер (урок M1/M7 сертификации Task 136): бюджет обучения --
    константа модуля в честном диапазоне [100, NEURAL_MAX_STEPS_BOUND].
    Тест выполняется БЕЗ monkeypatch (в отличие от скоростных тестов)."""
    assert isinstance(LSTM_MAX_STEPS, int)
    assert 100 <= LSTM_MAX_STEPS <= NEURAL_MAX_STEPS_BOUND
    assert LSTM_MIN_TRAIN >= 1


# ── 2. Fail-closed вход адаптера ─────────────────────────────────────────

def test_fit_predict_rejects_horizon_below_one():
    with pytest.raises(ValueError, match="horizon"):
        _lstm_fit_predict(list(np.arange(40, dtype=float)), 0)


def test_fit_predict_rejects_short_train_without_fallback():
    with pytest.raises(ValueError, match="слишком короткая"):
        _lstm_fit_predict([1.0, 2.0, 3.0], 2)


def test_fit_predict_rejects_nonfinite_input():
    with pytest.raises(ValueError, match="NaN/Inf"):
        _lstm_fit_predict([float("nan")] * 40, 2)


# ── 3. Реальный fit/predict (скоростной бюджет max_steps=3) ──────────────

def _series(n: int = 64, seed: int = 8) -> list[float]:
    rng = np.random.default_rng(seed)
    return (10.0 + 0.05 * np.arange(n) + rng.standard_normal(n) * 0.2).tolist()


@pytest.fixture()
def fast_budget(monkeypatch):
    monkeypatch.setattr(lstm_module, "LSTM_MAX_STEPS", 3)


def test_fit_predict_payload_contract(fast_budget):
    payload = _lstm_fit_predict(_series(), 5)
    assert payload["adapter_id"] == LSTM_ADAPTER_ID
    forecast = np.asarray(payload["forecast"], dtype=float)
    lower = np.asarray(payload["lower"], dtype=float)
    upper = np.asarray(payload["upper"], dtype=float)
    assert forecast.shape == (5,)
    assert lower.shape == (5,) and upper.shape == (5,)
    assert np.isfinite(forecast).all()
    assert (lower <= forecast).all() and (forecast <= upper).all()
    assert payload["cell_type"] == "LSTM"
    assert payload["deterministic"] is True
    assert payload["params"]["alpha"] in ALPHA_OPTIONS


def test_fit_predict_gru_cell_runs_on_the_same_runtime(fast_budget):
    payload = _lstm_fit_predict(_series(), 4, params={"cell_type": "GRU"})
    assert payload["cell_type"] == "GRU"
    assert len(payload["forecast"]) == 4


def test_conformal_intervals_match_the_alpha_plan(fast_budget):
    alpha = 0.10
    plan = interval_levels_for_alpha(alpha)
    payload = _lstm_fit_predict(_series(), 4, params={"alpha": alpha})
    assert payload["intervals"]["alpha"] == alpha
    assert list(payload["intervals"]["levels"]) == list(plan.levels)
    lower, upper = payload["lower"], payload["upper"]
    assert len(lower) == len(upper) == 4


def test_same_seed_gives_bit_identical_forecast(fast_budget):
    a = _lstm_fit_predict(_series(), 4, random_state=21)
    b = _lstm_fit_predict(_series(), 4, random_state=21)
    np.testing.assert_array_equal(
        np.asarray(a["forecast"]), np.asarray(b["forecast"]),
    )


def test_different_seed_gives_different_forecast(fast_budget):
    """Дифференциальный оракул (урок OR14c сертификации Task 137):
    сид обязан ДОХОДИТЬ до конструктора модели -- иначе same-seed тест
    вакуумен (всегда seed 1)."""
    a = _lstm_fit_predict(_series(), 4, random_state=21)
    b = _lstm_fit_predict(_series(), 4, random_state=31337)
    assert float(np.abs(
        np.asarray(a["forecast"]) - np.asarray(b["forecast"]),
    ).max()) > 0.0


# ── 4. ds-ось: datetime-метки и позиционная сетка ────────────────────────

def test_datetime_labels_infer_frequency_axis(fast_budget):
    dates = pd.date_range("2024-01-01", periods=64, freq="D")
    labels = [value.strftime("%Y-%m-%d") for value in dates]
    payload = _lstm_fit_predict(_series(), 4, timestamps=labels)
    assert payload["freq"]["kind"] == "datetime"
    assert payload["freq"]["value"] == "D"


def test_unparseable_labels_fall_back_to_positional_integer_grid(fast_budget):
    """Задекларированная конвенция адаптера: нераспознаваемые метки --
    позиционная целочисленная сетка (freq=1); ds -- только ось,
    значения прогноза от меток не зависят.  Никакого скрытого
    ресемплинга/интерполяции."""
    labels = [f"obs_{index}" for index in range(64)]
    payload = _lstm_fit_predict(_series(), 4, timestamps=labels)
    assert payload["freq"] == {"kind": "integer", "value": 1}


def test_without_labels_the_axis_is_positional(fast_budget):
    payload = _lstm_fit_predict(_series(), 4)
    assert payload["freq"] == {"kind": "integer", "value": 1}


# ── 5. Legacy synthetic-demo dispatch (прецедент random_forest) ──────────

def test_legacy_backtest_returns_real_metrics(fast_budget):
    metrics = run_lstm_backtest(_series(96), 0.75, 12)
    assert isinstance(metrics, BacktestMetrics)
    assert metrics.mae is not None and metrics.mae >= 0


def test_legacy_backtest_short_series_fails_honestly(fast_budget):
    # 10 точек -> train 8 < LSTM_MIN_TRAIN: честный отказ, БЕЗ Naive-подмен.
    with pytest.raises(ValueError, match="слишком короткая"):
        run_lstm_backtest(_series(10), 0.8, 12)


# ── 7. Закрытие НАХОДОК 1-3 сертификации Task 138 (M6/M10/M18) ───────────
# Сертификация Task 138 (вербикт CERTIFIED, находки не-блокирующие)
# рекомендовала исполнителю следующих срезов (139-142) включить три
# класса тестов.  Ниже -- аддитивные тесты ТЕКУЩЕЙ поверхности 138a
# (cert138_mutations.py -- characterization-артефакт поверхности a7cdf90,
# прецедент OR11i ресертификации Task 137: пробы описывают предыдущее
# состояние дерева; эквивалентное покрытие -- новыми тестами).

def test_bool_coercion_rejected_for_every_int_handle():
    """M6-класс: bool -- подкласс int; True->1 проходит нижнюю границу
    encoder_n_layers (low=1).  Тест параметризован по ВСЕМ целочисленным
    ручкам адаптера (без надежды на bounds-слой)."""
    for handle in ("hidden_size", "encoder_n_layers", "input_size"):
        with pytest.raises(ValueError, match=handle):
            validate_lstm_params({handle: True})


class _WiringProbeDone(Exception):
    """Sentinel: короткое замыкание spy-обёртки train_and_forecast."""


def test_budget_wiring_reaches_the_constructor(monkeypatch, fast_budget):
    """M18-класс: metadata не должна лгать о фактическом бюджете
    (literal-dup).  Двухслойный spy: (1) адаптер передаёт в runtime
    config с бюджетом константы модуля; (2) фабрика честно разворачивает
    budget в КОНСТРУКТОР -- модель несёт max_steps/random_seed пробы."""
    captured: dict = {}

    def spy(*, model_factory, config, **_kwargs):
        captured["config"] = config
        probe_budget = {
            "max_steps": 321, "random_seed": 777, "accelerator": "cpu",
            "enable_progress_bar": False, "early_stop_patience_steps": -1,
        }
        captured["model"] = model_factory(dict(probe_budget))
        raise _WiringProbeDone()

    monkeypatch.setattr(lstm_module, "train_and_forecast", spy)
    with pytest.raises(_WiringProbeDone):
        _lstm_fit_predict(_series(), 4)
    assert captured["config"].max_steps == lstm_module.LSTM_MAX_STEPS
    model = captured["model"]
    assert int(model.max_steps) == 321
    assert int(model.random_seed) == 777


def test_fault_injected_broken_bounds_are_rejected(monkeypatch, fast_budget):
    """M10-класс: clamp-инвариант lower <= point <= upper -- живой гейт,
    закреплённый fault-injection тестом (happy-path никогда не нарушает
    границы, поэтому нужен явный ломающий монитор)."""

    def broken_train(*, model_factory, **_kwargs):
        return pd.DataFrame({
            "LSTM": [1.0, 1.0, 1.0, 1.0],
            "LSTM-lo-2.5": [5.0] * 4,
            "LSTM-hi-97.5": [6.0] * 4,
        })

    monkeypatch.setattr(lstm_module, "train_and_forecast", broken_train)
    with pytest.raises(NeuralContractError, match="инвариант"):
        _lstm_fit_predict(_series(), 4)


# ── 8. Контрактная поверхность (импорты для находимых классов) ───────────

def test_neural_contract_error_taxonomy_is_importable():
    """NeuralContractError -- ValueError-подтип (таксономия 138c):
    адаптерные отказы ловятся и ValueError-, и NeuralContractError-ветками."""
    from apps.api.neural_contract import NeuralContractError as _nce

    assert issubclass(_nce, ValueError)


def test_training_config_carries_the_adapter_budget(fast_budget):
    config = NeuralTrainingConfig(seed=1, max_steps=LSTM_MAX_STEPS)
    assert config.as_dict()["max_steps"] == LSTM_MAX_STEPS
