# tests/unit/test_nbeats_adapter.py
"""Task 139 -- N-BEATS: адаптер на едином NeuralForecast-runtime
(neural_runtime.py Task 137), второй исполнитель нейро-семейства.

Прецедент пары lstm (Task 138) в neural-runtime и garch/egarch в
volatility-движке: ЕДИНСТВЕННАЯ точка импорта torch/neuralforecast --
apps/api/model_impls/neural_runtime.py (лениво, fail-closed); адаптер:
- архитектурный выбор стека stack_config ∈ {interpretable, generic}
  (аналог cell_type Task 138): каталог декларирует «Basis expansion
  network. Интерпретируемая декомпозиция (тренд + сезонность)» --
  interpretable = каноническая интерпретируемая декомпозиция
  (stack_types=["trend", "seasonality"], Oreshkin et al. 2019),
  generic = генеричная basis-expansion сеть (identity-стеки,
  basis='polynomial'); дефолт -- interpretable;
- ds-ось -- ЗАДЕКЛАРИРОВАННАЯ конвенция neural-семейства,
  ПЕРЕИСПОЛЬЗОВАНА из адаптера Task 138 (lstm._resolve_time_axis --
  единый источник истины, НЕ продублирована): парсимые метки ->
  datetime + честный pd.infer_freq, иначе -- позиционная целочисленная
  сетка (freq=1, подтверждено пробом scripts/task139_nbeats_probe.py);
- интервалы -- официальный conformal-контур контракта Task 137
  (fit prediction_intervals + predict level), уровни из
  interval_levels_for_alpha; NBEATS 3.2.2 -- point-loss модель
  (loss=MAE по умолчанию);
- гейт неосуществимого окна: n_train < input_size + horizon -- отказ
  ДО фита (полностью наблюдаемое supervised-окно; молчаливое ужатие
  запрещено; библиотека с start_padding_enabled=False fail-closed
  согласована -- проб scripts/task139_nbeats_probe.py);
- clamp-инвариант lower <= point <= upper -- с первого дня (урок
  НАХОДКИ-3/M10 сертификации Task 138) + fault-injection тест;
- fail-closed: короткий train, NaN/Inf, неизвестный стек, значения вне
  bounded-границ, bool-коэрция целочисленных ручек (урок НАХОДКИ-2/M6
  сертификации Task 138 -- параметризовано по ВСЕМ int-ручкам) --
  отказ fold'а БЕЗ Naive-fallback и clamp-подмен;
- детерминизм: random_state -> NeuralTrainingConfig.seed -> fold_seed ->
  random_seed КОНСТРУКТОРА модели (ресертификация Task 137; same-seed
  бит-паритет подтверждён пробом: max|diff| = 0.0, другой seed --
  другой прогноз, max|diff| = 0.53);
- проводка бюджета до конструктора прижата spy-тестом (урок НАХОДКИ-1/
  M18 сертификации Task 138: metadata не должна лгать о фактическом
  бюджете -- literal-dup класс артефактов).

Бюджет: NBEATS_MAX_STEPS -- КОНСТАНТА модуля (единый бюджетный рычаг
контракта; тюнинг бюджета -- вне param_space, прецедент Task 136),
прижата анти-тампер тестом; в тестах укорачивается monkeypatch'ем для
скорости (реальное значение прижато отдельным тестом БЕЗ monkeypatch).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.neural_contract import (
    NEURAL_MAX_STEPS_BOUND,
    NeuralContractError,
    NeuralRuntimeCapacityError,
    NeuralTrainingConfig,
    interval_levels_for_alpha,
)

pytest.importorskip("neuralforecast", reason="neural runtime -- опциональная группа")

from apps.api.model_impls import nbeats as nbeats_module  # noqa: E402
from apps.api.model_impls.nbeats import (  # noqa: E402
    ALPHA_OPTIONS,
    DEFAULT_PARAMS,
    INPUT_SIZE_BOUNDS,
    MLP_LAYERS_BOUNDS,
    NBEATS_ADAPTER_ID,
    NBEATS_MAX_STEPS,
    NBEATS_MIN_TRAIN,
    STACK_OPTIONS,
    _nbeats_fit_predict,
    run_nbeats_backtest,
    validate_nbeats_params,
)
from apps.api.schemas import BacktestMetrics  # noqa: E402


# ── 1. Bounded params (fail-closed) ──────────────────────────────────────

def test_default_params_are_declared_and_normalization_fills_defaults():
    normalized = validate_nbeats_params(None)
    assert normalized == DEFAULT_PARAMS
    # Чужие ключи (tbats_seasonal_periods и т.п.) игнорируются --
    # соглашение платформы (backtesting.py присылает общие params).
    merged = validate_nbeats_params(
        {"tbats_seasonal_periods": 12, "stack_config": "generic"}
    )
    assert merged["stack_config"] == "generic"
    assert "tbats_seasonal_periods" not in merged


def test_unknown_stack_config_is_rejected_fail_closed():
    with pytest.raises(ValueError, match="stack_config"):
        validate_nbeats_params({"stack_config": "wavelet"})
    assert set(STACK_OPTIONS) == {"interpretable", "generic"}


def test_numeric_params_outside_bounds_are_rejected():
    with pytest.raises(ValueError, match="hidden_size"):
        validate_nbeats_params({"hidden_size": 4})
    with pytest.raises(ValueError, match="hidden_size"):
        validate_nbeats_params({"hidden_size": 10_000})
    with pytest.raises(ValueError, match="mlp_layers"):
        validate_nbeats_params({"mlp_layers": 0})
    with pytest.raises(ValueError, match="mlp_layers"):
        validate_nbeats_params({"mlp_layers": 5})
    with pytest.raises(ValueError, match="input_size"):
        validate_nbeats_params({"input_size": 2})
    with pytest.raises(ValueError, match="alpha"):
        validate_nbeats_params({"alpha": 0.5})


@pytest.mark.parametrize("handle", ["hidden_size", "mlp_layers", "input_size"])
def test_bool_coercion_rejected_for_every_int_handle(handle):
    """Урок НАХОДКИ-2/M6 сертификации Task 138: bool -- подкласс int;
    True->1 проходит нижнюю границу ручек с low=1.  Тест параметризован
    по ВСЕМ целочисленным ручкам адаптера (без надежды на bounds-слой)."""
    with pytest.raises(ValueError, match=handle):
        validate_nbeats_params({handle: True})


def test_adapter_budget_constant_is_pinned_to_the_contract_bound():
    """Анти-тампер (урок M1/M7 сертификации Task 136): бюджет обучения --
    константа модуля в честном диапазоне [100, NEURAL_MAX_STEPS_BOUND].
    Тест выполняется БЕЗ monkeypatch (в отличие от скоростных тестов)."""
    assert isinstance(NBEATS_MAX_STEPS, int)
    assert 100 <= NBEATS_MAX_STEPS <= NEURAL_MAX_STEPS_BOUND
    assert NBEATS_MIN_TRAIN >= 1


# ── 2. Fail-closed вход адаптера ─────────────────────────────────────────

def test_fit_predict_rejects_horizon_below_one():
    with pytest.raises(ValueError, match="horizon"):
        _nbeats_fit_predict(list(np.arange(40, dtype=float)), 0)


def test_fit_predict_rejects_short_train_without_fallback():
    with pytest.raises(ValueError, match="слишком короткая"):
        _nbeats_fit_predict([1.0, 2.0, 3.0], 2)


def test_fit_predict_rejects_nonfinite_input():
    with pytest.raises(ValueError, match="NaN/Inf"):
        _nbeats_fit_predict([float("nan")] * 40, 2)


def test_fit_predict_rejects_infeasible_window():
    """Гейт неосуществимого окна: n_train=32 < input_size=48 + horizon=4 --
    отказ ДО фита; молчаливое ужатие/паддинг окна запрещены."""
    with pytest.raises(ValueError, match="окно"):
        _nbeats_fit_predict(list(np.arange(32, dtype=float)), 4,
                            params={"input_size": 48})


# ── 3. Реальный fit/predict (скоростной бюджет max_steps=3) ──────────────

def _series(n: int = 64, seed: int = 8) -> list[float]:
    rng = np.random.default_rng(seed)
    return (10.0 + 0.05 * np.arange(n) + rng.standard_normal(n) * 0.2).tolist()


@pytest.fixture()
def fast_budget(monkeypatch):
    monkeypatch.setattr(nbeats_module, "NBEATS_MAX_STEPS", 3)


def test_fit_predict_payload_contract(fast_budget):
    payload = _nbeats_fit_predict(_series(), 5)
    assert payload["adapter_id"] == NBEATS_ADAPTER_ID
    forecast = np.asarray(payload["forecast"], dtype=float)
    lower = np.asarray(payload["lower"], dtype=float)
    upper = np.asarray(payload["upper"], dtype=float)
    assert forecast.shape == (5,)
    assert lower.shape == (5,) and upper.shape == (5,)
    assert np.isfinite(forecast).all()
    assert (lower <= forecast).all() and (forecast <= upper).all()
    assert payload["stack_config"] == "interpretable"
    assert payload["deterministic"] is True
    assert payload["params"]["alpha"] in ALPHA_OPTIONS


def test_fit_predict_generic_stack_runs_on_the_same_runtime(fast_budget):
    payload = _nbeats_fit_predict(_series(), 4, params={"stack_config": "generic"})
    assert payload["stack_config"] == "generic"
    assert len(payload["forecast"]) == 4


def test_conformal_intervals_match_the_alpha_plan(fast_budget):
    alpha = 0.10
    plan = interval_levels_for_alpha(alpha)
    payload = _nbeats_fit_predict(_series(), 4, params={"alpha": alpha})
    assert payload["intervals"]["alpha"] == alpha
    assert list(payload["intervals"]["levels"]) == list(plan.levels)
    lower, upper = payload["lower"], payload["upper"]
    assert len(lower) == len(upper) == 4


def test_same_seed_gives_bit_identical_forecast(fast_budget):
    a = _nbeats_fit_predict(_series(), 4, random_state=21)
    b = _nbeats_fit_predict(_series(), 4, random_state=21)
    np.testing.assert_array_equal(
        np.asarray(a["forecast"]), np.asarray(b["forecast"]),
    )


def test_different_seed_gives_different_forecast(fast_budget):
    """Дифференциальный оракул (урок OR14c сертификации Task 137):
    сид обязан ДОХОДИТЬ до конструктора модели -- иначе same-seed тест
    вакуумен (всегда seed 1)."""
    a = _nbeats_fit_predict(_series(), 4, random_state=21)
    b = _nbeats_fit_predict(_series(), 4, random_state=31337)
    assert float(np.abs(
        np.asarray(a["forecast"]) - np.asarray(b["forecast"]),
    ).max()) > 0.0


# ── 4. ds-ось: datetime-метки и позиционная сетка ────────────────────────

def test_datetime_labels_infer_frequency_axis(fast_budget):
    dates = pd.date_range("2024-01-01", periods=64, freq="D")
    labels = [value.strftime("%Y-%m-%d") for value in dates]
    payload = _nbeats_fit_predict(_series(), 4, timestamps=labels)
    assert payload["freq"]["kind"] == "datetime"
    assert payload["freq"]["value"] == "D"


def test_unparseable_labels_fall_back_to_positional_integer_grid(fast_budget):
    """Задекларированная конвенция neural-семейства (переиспользована из
    Task 138): нераспознаваемые метки -- позиционная целочисленная сетка
    (freq=1); ds -- только ось, значения прогноза от меток не зависят.
    Никакого скрытого ресемплинга/интерполяции."""
    labels = [f"obs_{index}" for index in range(64)]
    payload = _nbeats_fit_predict(_series(), 4, timestamps=labels)
    assert payload["freq"] == {"kind": "integer", "value": 1}


def test_without_labels_the_axis_is_positional(fast_budget):
    payload = _nbeats_fit_predict(_series(), 4)
    assert payload["freq"] == {"kind": "integer", "value": 1}


# ── 5. Проводка бюджета до конструктора (урок M18 сертификации 138) ─────

class _WiringProbeDone(Exception):
    """Sentinel: короткое замыкание spy-обёртки train_and_forecast."""


def test_budget_wiring_reaches_the_constructor(monkeypatch, fast_budget):
    """Двухслойный spy (урок НАХОДКИ-1/M18 сертификации Task 138 --
    metadata не должна лгать о фактическом бюджете, literal-dup класс):
    (1) адаптер передаёт в runtime config с бюджетом константы модуля;
    (2) фабрика адаптера честно разворачивает budget в КОНСТРУКТОР --
    сконструированная модель несёт max_steps/random_seed пробы."""
    captured: dict = {}

    def spy(*, model_factory, config, **_kwargs):
        captured["config"] = config
        probe_budget = {
            "max_steps": 321, "random_seed": 777, "accelerator": "cpu",
            "enable_progress_bar": False, "early_stop_patience_steps": -1,
        }
        captured["model"] = model_factory(dict(probe_budget))
        raise _WiringProbeDone()

    monkeypatch.setattr(nbeats_module, "train_and_forecast", spy)
    with pytest.raises(_WiringProbeDone):
        _nbeats_fit_predict(_series(), 4)
    assert captured["config"].max_steps == nbeats_module.NBEATS_MAX_STEPS
    model = captured["model"]
    assert int(model.max_steps) == 321
    assert int(model.random_seed) == 777
    assert int(model.input_size) == DEFAULT_PARAMS["input_size"]


# ── 6. Clamp-инвариант и ресурсный отказ (уроки M10/138c) ────────────────

def test_fault_injected_broken_bounds_are_rejected(monkeypatch, fast_budget):
    """Урок НАХОДКИ-3/M10 сертификации Task 138: clamp-инвариант --
    живой гейт, закреплённый fault-injection тестом (happy-path никогда
    не нарушает границы, поэтому нужен явный ломающий монитор)."""
    def broken_train(*, model_factory, **_kwargs):
        return pd.DataFrame({
            "NBEATS": [1.0, 1.0, 1.0, 1.0],
            "NBEATS-lo-2.5": [5.0] * 4,
            "NBEATS-hi-97.5": [6.0] * 4,
        })

    monkeypatch.setattr(nbeats_module, "train_and_forecast", broken_train)
    with pytest.raises(NeuralContractError, match="инвариант"):
        _nbeats_fit_predict(_series(), 4)


def test_capacity_error_passes_through_unwrapped(monkeypatch, fast_budget):
    """Прецедент Task 138c: NeuralRuntimeCapacityError проходит сквозь
    адаптер БЕЗ ValueError-обёртки -- HTTP-слой обязан увидеть честный
    статус (503/422), а не потерять его."""

    def capacity_refused(*, model_factory, **_kwargs):
        raise NeuralRuntimeCapacityError("инстанс ниже контрактуемого бюджета")

    monkeypatch.setattr(nbeats_module, "train_and_forecast", capacity_refused)
    with pytest.raises(NeuralRuntimeCapacityError):
        _nbeats_fit_predict(_series(), 4)


# ── 7. Legacy synthetic-demo dispatch (прецедент lstm/random_forest) ─────

def test_legacy_backtest_returns_real_metrics(fast_budget):
    metrics = run_nbeats_backtest(_series(96), 0.75, 12)
    assert isinstance(metrics, BacktestMetrics)
    assert metrics.mae is not None and metrics.mae >= 0


def test_legacy_backtest_short_series_fails_honestly(fast_budget):
    # 10 точек -> train 8 < NBEATS_MIN_TRAIN: честный отказ, БЕЗ Naive-подмен.
    with pytest.raises(ValueError, match="слишком короткая"):
        run_nbeats_backtest(_series(10), 0.8, 12)


def test_training_config_carries_the_adapter_budget(fast_budget):
    config = NeuralTrainingConfig(seed=1, max_steps=NBEATS_MAX_STEPS)
    assert config.as_dict()["max_steps"] == NBEATS_MAX_STEPS


# ── 8. Env-рычаг бюджета слабых инстансов (паттерн Task 138c) ────────────

def test_env_max_steps_default_override_and_fail_closed(monkeypatch):
    """Пустая env -- сертифицированная константа; задана -- честное
    значение; мусор/меньше 1 -- fail-closed ValueError."""
    from apps.api.model_impls.nbeats import _resolve_max_steps

    monkeypatch.delenv("CISSTAT_NEURAL_MAX_STEPS", raising=False)
    assert _resolve_max_steps() == NBEATS_MAX_STEPS

    monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", "120")
    assert _resolve_max_steps() == 120

    monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", " 120 ")
    assert _resolve_max_steps() == 120

    for garbage in ("abc", "0", "-5", "1.5"):
        monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", garbage)
        with pytest.raises(ValueError, match="CISSTAT_NEURAL_MAX_STEPS"):
            _resolve_max_steps()
