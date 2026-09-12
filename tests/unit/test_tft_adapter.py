# tests/unit/test_tft_adapter.py
"""Task 141 -- TFT: адаптер на едином NeuralForecast-runtime
(neural_runtime.py Task 137), четвёртый исполнитель нейро-семейства и
ПЕРВЫЙ срез с probabilistic-поверхностью MQLoss/quantiles.

Прецедент тройки lstm/nbeats/nhits (Tasks 138/139/140) в neural-runtime:
ЕДИНСТВЕННАЯ точка импорта torch/neuralforecast --
apps/api/model_impls/neural_runtime.py (лениво, fail-closed); адаптер:
- probabilistic-поверхность -- ЯДРО постановки Task 141: loss=MQLoss --
  первая нейро-модель платформы с нативными квантильными выходами
  вместо сертифицированного conformal-контура point-loss моделей
  (lstm/nbeats/nhits); квантили декларируются ПРЯМО
  (MQLoss(quantiles=[alpha/2, 0.5, 1-alpha/2])) -- честный двусторонний
  интервал [alpha/2; 1-alpha/2] процентилей, точечный прогноз = медиана
  (TFT-median); контрактный гейт resolve_probabilistic_loss("mqloss",
  levels=...) пропускает план только с уровнями (Task 137:
  NEURAL_PROBABILISTIC_LOSSES);
- эмпирика level-семантики 3.2.2 (проб scripts/task141_tft_probe.py +
  исходники level_to_outputs/quantiles_to_outputs): суффикс колонки
  "-lo-<w>"/"-hi-<w>" кодирует ШИРИНУ интервала w = 100*(1-alpha)
  (границы при 50±w/2 процентилях); прямая декларация quantiles=
  устраняет зависимость от width-семантики;
- attention-ось каталожного описания «Attention-based architecture
  (Google)» -- bounded-параметр n_head ∈ {2, 4}; constraint
  InterpretableMultiHeadAttention d_k = hidden_size // n_head прижат
  адаптерным гейтом hidden_size % n_head == 0 ДО конструирования
  (эмпирика: библиотека падает AssertionError на неделимости -- проб);
- clamp-инвариант lower <= median <= upper -- живой гейт поверх
  isfinite (квантильное пересечение MQLoss теоретически возможно --
  heads независимы; честный отказ fold'а вместо clamp-подмен) +
  fault-injection тест (урок НАХОДКИ-3/M10 сертификации Task 138);
- ds-ось -- задекларированная конвенция neural-семейства,
  ПЕРЕИСПОЛЬЗОВАНА из Task 138 (lstm._resolve_time_axis -- единый
  источник истины, НЕ продублирована): datetime + pd.infer_freq либо
  позиционная целочисленная сетка freq=1 (проб);
- гейт неосуществимого окна: n_train < input_size + horizon -- отказ
  ДО фита (молчаливое ужатие/паддинг запрещены; библиотека с
  start_padding_enabled=False согласована -- проб);
- fail-closed: короткий train, NaN/Inf, n_head вне whitelist,
  значения вне bounded-границ, bool-коэрция целочисленных ручек (урок
  НАХОДКИ-2/M6 сертификации Task 138 -- параметризовано по ВСЕМ
  int-ручкам) -- отказ fold'а БЕЗ Naive-fallback и clamp-подмен;
- детерминизм: random_state -> NeuralTrainingConfig.seed -> fold_seed ->
  random_seed КОНСТРУКТОРА модели (ресертификация Task 137; same-seed
  бит-паритет подтверждён пробом: max|diff| = 0.0, другой seed --
  другой прогноз);
- проводка бюджета до конструктора прижата spy-тестом (урок НАХОДКИ-1/
  M18 сертификации Task 138: metadata не должна лгать о фактическом
  бюджете -- literal-dup класс артефактов).

Бюджет: TFT_MAX_STEPS -- КОНСТАНТА модуля (единый бюджетный рычаг
контракта; тюнинг бюджета -- вне param_space, прецедент Task 136),
прижата анти-тампер тестом; в тестах укорачивается monkeypatch'ем для
скорости (реальное значение прижато отдельным тестом БЕЗ monkeypatch).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.neural_contract import (
    DEFAULT_NEURAL_QUANTILE_LEVELS,
    NEURAL_MAX_STEPS_BOUND,
    NeuralContractError,
    NeuralRuntimeCapacityError,
    NeuralTrainingConfig,
    interval_levels_for_alpha,
    resolve_probabilistic_loss,
)

pytest.importorskip("neuralforecast", reason="neural runtime -- опциональная группа")

from apps.api.model_impls import tft as tft_module  # noqa: E402
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
from apps.api.schemas import BacktestMetrics  # noqa: E402


# ── 1. Bounded params (fail-closed) ──────────────────────────────────────

def test_default_params_are_declared_and_normalization_fills_defaults():
    normalized = validate_tft_params(None)
    assert normalized == DEFAULT_PARAMS
    # Чужие ключи (tbats_seasonal_periods и т.п.) игнорируются --
    # соглашение платформы (backtesting.py присылает общие params).
    merged = validate_tft_params({"tbats_seasonal_periods": 12, "n_head": 2})
    assert merged["n_head"] == 2
    assert "tbats_seasonal_periods" not in merged


def test_n_head_whitelist_is_the_honest_attention_axis():
    """Attention-ось каталожного описания «Attention-based architecture»
    -- bounded-параметр n_head; whitelist фиксирован декларацией."""
    assert N_HEAD_OPTIONS == (2, 4)
    with pytest.raises(ValueError, match="n_head"):
        validate_tft_params({"n_head": 3})
    with pytest.raises(ValueError, match="n_head"):
        validate_tft_params({"n_head": 8})


def test_numeric_params_outside_bounds_are_rejected():
    with pytest.raises(ValueError, match="hidden_size"):
        validate_tft_params({"hidden_size": 4})
    with pytest.raises(ValueError, match="hidden_size"):
        validate_tft_params({"hidden_size": 10_000})
    with pytest.raises(ValueError, match="input_size"):
        validate_tft_params({"input_size": 2})
    with pytest.raises(ValueError, match="input_size"):
        validate_tft_params({"input_size": 10_000})
    with pytest.raises(ValueError, match="alpha"):
        validate_tft_params({"alpha": 0.5})


def test_hidden_size_must_be_divisible_by_n_head():
    """Constraint InterpretableMultiHeadAttention: d_k = d_model // n_head
    -- библиотека падает AssertionError на неделимости (проб
    scripts/task141_tft_probe.py); адаптер даёт детерминированное
    сообщение ДО конструирования (стиль гейта неосуществимого окна)."""
    with pytest.raises(ValueError, match="кратным"):
        validate_tft_params({"hidden_size": 10, "n_head": 4})
    with pytest.raises(ValueError, match="кратным"):
        validate_tft_params({"hidden_size": 33, "n_head": 2})
    # Делимые комбинации проходят
    assert validate_tft_params({"hidden_size": 32, "n_head": 4})["hidden_size"] == 32
    assert validate_tft_params({"hidden_size": 64, "n_head": 2})["hidden_size"] == 64


@pytest.mark.parametrize("handle", ["n_head", "hidden_size", "input_size"])
def test_bool_coercion_rejected_for_every_int_handle(handle):
    """Урок НАХОДКИ-2/M6 сертификации Task 138: bool -- подкласс int;
    True->1 проходит нижнюю границу ручек с low=1.  Тест параметризован
    по ВСЕМ целочисленным ручкам адаптера (без надежды на bounds-слой)."""
    with pytest.raises(ValueError, match=handle):
        validate_tft_params({handle: True})


def test_adapter_budget_constant_is_pinned_to_the_contract_bound():
    """Анти-тампер (урок M1/M7 сертификации Task 136): бюджет обучения --
    константа модуля в честном диапазоне [100, NEURAL_MAX_STEPS_BOUND].
    Тест выполняется БЕЗ monkeypatch (в отличие от скоростных тестов)."""
    assert isinstance(TFT_MAX_STEPS, int)
    assert 100 <= TFT_MAX_STEPS <= NEURAL_MAX_STEPS_BOUND
    assert TFT_MIN_TRAIN >= 1


# ── 2. Fail-closed вход адаптера ─────────────────────────────────────────

def test_fit_predict_rejects_horizon_below_one():
    with pytest.raises(ValueError, match="horizon"):
        _tft_fit_predict(list(np.arange(40, dtype=float)), 0)


def test_fit_predict_rejects_short_train_without_fallback():
    with pytest.raises(ValueError, match="слишком короткая"):
        _tft_fit_predict([1.0, 2.0, 3.0], 2)


def test_fit_predict_rejects_nonfinite_input():
    with pytest.raises(ValueError, match="NaN/Inf"):
        _tft_fit_predict([float("nan")] * 40, 2)


def test_fit_predict_rejects_infeasible_window():
    """Гейт неосуществимого окна: n_train=32 < input_size=48 + horizon=4 --
    отказ ДО фита; молчаливое ужатие/паддинг окна запрещены."""
    with pytest.raises(ValueError, match="окно"):
        _tft_fit_predict(list(np.arange(32, dtype=float)), 4,
                         params={"input_size": 48})


# ── 3. Probabilistic-поверхность MQLoss/quantiles (ядро Task 141) ────────

def _series(n: int = 64, seed: int = 8) -> list[float]:
    rng = np.random.default_rng(seed)
    return (10.0 + 0.05 * np.arange(n) + rng.standard_normal(n) * 0.2).tolist()


@pytest.fixture()
def fast_budget(monkeypatch):
    # Скоростной бюджет подобран эмпирически (проб Task 141): головы
    # квантилей MQLoss на недообученном TFT пересекаются (4/5 seeds при
    # 3 шагах) и сходятся стабильно (0/5 при >= 10) на тестовом ряде;
    # 20 -- запас устойчивости при приемлемом времени прогона.
    # Production-константа 300 прижата отдельным тестом БЕЗ monkeypatch.
    monkeypatch.setattr(tft_module, "TFT_MAX_STEPS", 20)


def test_contract_gate_mqloss_requires_levels():
    """Контракт Task 137: probabilistic-функция БЕЗ уровней -- отказ;
    план interval_levels_for_alpha гейт проходит."""
    with pytest.raises(NeuralContractError, match="уровней"):
        resolve_probabilistic_loss("mqloss", levels=())
    plan = interval_levels_for_alpha(0.05)
    assert resolve_probabilistic_loss("mqloss", levels=plan.levels) == "mqloss"


def test_quantile_plan_maps_alpha_to_direct_quantiles():
    """Прямая декларация квантилей: alpha -> (alpha/2, 0.5, 1-alpha/2)
    -- честный двусторонний интервал в процентилях; суффикс колонок
    кодирует ШИРИНУ w = 100*(1-alpha) (конвенция quantiles_to_outputs
    3.2.2: '-lo-' + round(100-200*q, 2) -- проб + исходники)."""
    plan = _quantile_plan(0.05)
    assert plan["quantiles"] == (0.025, 0.5, 0.975)
    assert plan["levels"] == (2.5, 50.0, 97.5)
    assert plan["width"] == 95.0
    for alpha, width in ((0.01, 99.0), (0.05, 95.0), (0.10, 90.0)):
        assert _quantile_plan(alpha)["width"] == width


def test_quantile_plan_width_is_the_contract_width():
    """Единый источник истины (НАХОДКА Task 141 п.2): ширина плана TFT
    берётся из interval_width_for_alpha контракта -- той же функции, что
    и у исправленной тройки lstm/nbeats/nhits (ресертификация
    width-семантики), а не из локального дубля."""
    from apps.api.neural_contract import interval_width_for_alpha

    for alpha in (0.01, 0.05, 0.10, 0.20):
        assert _quantile_plan(alpha)["width"] == interval_width_for_alpha(alpha)


def test_fit_predict_payload_contract(fast_budget):
    payload = _tft_fit_predict(_series(), 5)
    assert payload["adapter_id"] == TFT_ADAPTER_ID
    forecast = np.asarray(payload["forecast"], dtype=float)
    lower = np.asarray(payload["lower"], dtype=float)
    upper = np.asarray(payload["upper"], dtype=float)
    assert forecast.shape == (5,)
    assert lower.shape == (5,) and upper.shape == (5,)
    assert np.isfinite(forecast).all()
    assert (lower <= forecast).all() and (forecast <= upper).all()
    assert payload["deterministic"] is True
    assert payload["params"]["alpha"] in ALPHA_OPTIONS


def test_intervals_metadata_declares_native_quantile_surface(fast_budget):
    """Точка = медиана MQLoss; интервалы -- нативные квантили
    (метод NeuralIntervalPlan контракта), НЕ conformal; loss-дисклоужер
    честен: mqloss -- первая probabilistic-модель семейства."""
    payload = _tft_fit_predict(_series(), 4)
    intervals = payload["intervals"]
    assert intervals["method"] == "neural_quantile_outputs"
    assert intervals["loss"] == "mqloss"
    assert intervals["alpha"] == DEFAULT_PARAMS["alpha"]
    assert list(intervals["quantiles"]) == [0.025, 0.5, 0.975]
    assert list(intervals["levels"]) == [2.5, 50.0, 97.5]


def test_quantile_bounds_match_the_alpha_plan(fast_budget):
    alpha = 0.10
    plan = _quantile_plan(alpha)
    payload = _tft_fit_predict(_series(), 4, params={"alpha": alpha})
    assert payload["intervals"]["alpha"] == alpha
    assert list(payload["intervals"]["quantiles"]) == list(plan["quantiles"])
    lower, upper = payload["lower"], payload["upper"]
    assert len(lower) == len(upper) == 4


@pytest.mark.parametrize("alpha", [0.01, 0.05, 0.10])
def test_all_alpha_whitelist_levels_run_native_quantiles(fast_budget, alpha):
    """Все уровни whitelist'а проходят единый quantiles-путь (проб:
    колонки TFT-lo-<w>/TFT-median/TFT-hi-<w> для всех трёх alpha)."""
    payload = _tft_fit_predict(_series(), 4, params={"alpha": alpha})
    assert payload["params"]["alpha"] == alpha
    assert len(payload["forecast"]) == 4
    assert (np.asarray(payload["lower"]) <= np.asarray(payload["upper"])).all()


def test_same_seed_gives_bit_identical_forecast(fast_budget):
    a = _tft_fit_predict(_series(), 4, random_state=21)
    b = _tft_fit_predict(_series(), 4, random_state=21)
    np.testing.assert_array_equal(
        np.asarray(a["forecast"]), np.asarray(b["forecast"]),
    )


def test_different_seed_gives_different_forecast(fast_budget):
    """Дифференциальный оракул (урок OR14c сертификации Task 137):
    сид обязан ДОХОДИТЬ до конструктора модели -- иначе same-seed тест
    вакуумен (всегда seed 1)."""
    a = _tft_fit_predict(_series(), 4, random_state=21)
    b = _tft_fit_predict(_series(), 4, random_state=31337)
    assert float(np.abs(
        np.asarray(a["forecast"]) - np.asarray(b["forecast"]),
    ).max()) > 0.0


# ── 4. ds-ось: datetime-метки и позиционная сетка ────────────────────────

def test_datetime_labels_infer_frequency_axis(fast_budget):
    dates = pd.date_range("2024-01-01", periods=64, freq="D")
    labels = [value.strftime("%Y-%m-%d") for value in dates]
    payload = _tft_fit_predict(_series(), 4, timestamps=labels)
    assert payload["freq"]["kind"] == "datetime"
    assert payload["freq"]["value"] == "D"


def test_unparseable_labels_fall_back_to_positional_integer_grid(fast_budget):
    """Задекларированная конвенция neural-семейства (переиспользована из
    Task 138): нераспознаваемые метки -- позиционная целочисленная сетка
    (freq=1); ds -- только ось, значения прогноза от меток не зависят.
    Никакого скрытого ресемплинга/интерполяции."""
    labels = [f"obs_{index}" for index in range(64)]
    payload = _tft_fit_predict(_series(), 4, timestamps=labels)
    assert payload["freq"] == {"kind": "integer", "value": 1}


def test_without_labels_the_axis_is_positional(fast_budget):
    payload = _tft_fit_predict(_series(), 4)
    assert payload["freq"] == {"kind": "integer", "value": 1}


# ── 5. Проводка бюджета до конструктора (урок M18 сертификации 138) ─────

class _WiringProbeDone(Exception):
    """Sentinel: короткое замыкание spy-обёртки train_and_forecast."""


def test_budget_wiring_reaches_the_constructor(monkeypatch, fast_budget):
    """Двухслойный spy (урок НАХОДКИ-1/M18 сертификации Task 138 --
    metadata не должна лгать о фактическом бюджете, literal-dup класс):
    (1) адаптер передаёт в runtime config с бюджетом константы модуля;
    (2) фабрика адаптера честно разворачивает budget в КОНСТРУКТОР --
    сконструированная модель несёт max_steps/random_seed/input_size
    пробы и MQLoss как loss."""
    captured: dict = {}

    def spy(*, model_factory, config, **_kwargs):
        captured["config"] = config
        probe_budget = {
            "max_steps": 321, "random_seed": 777, "accelerator": "cpu",
            "enable_progress_bar": False, "early_stop_patience_steps": -1,
        }
        captured["model"] = model_factory(dict(probe_budget))
        raise _WiringProbeDone()

    monkeypatch.setattr(tft_module, "train_and_forecast", spy)
    with pytest.raises(_WiringProbeDone):
        _tft_fit_predict(_series(), 4)
    assert captured["config"].max_steps == tft_module.TFT_MAX_STEPS
    model = captured["model"]
    assert int(model.max_steps) == 321
    assert int(model.random_seed) == 777
    assert int(model.input_size) == DEFAULT_PARAMS["input_size"]
    assert type(model.loss).__name__ == "MQLoss"


# ── 6. Clamp-инвариант и ресурсный отказ (уроки M10/138c) ────────────────

def test_fault_injected_quantile_crossing_is_rejected(monkeypatch, fast_budget):
    """Урок НАХОДКИ-3/M10 сертификации Task 138: clamp-инвариант --
    живой гейт, закреплённый fault-injection тестом.  Для MQLoss гейт
    ловит квантильное пересечение (heads независимы -- пересечение
    теоретически возможно): честный отказ fold'а вместо clamp-подмен."""
    def broken_train(*, model_factory, **_kwargs):
        return pd.DataFrame({
            "TFT-median": [1.0, 1.0, 1.0, 1.0],
            "TFT-lo-95.0": [5.0] * 4,
            "TFT-hi-95.0": [6.0] * 4,
        })

    monkeypatch.setattr(tft_module, "train_and_forecast", broken_train)
    with pytest.raises(NeuralContractError, match="инвариант"):
        _tft_fit_predict(_series(), 4)


def test_missing_native_quantile_column_is_fail_closed(monkeypatch, fast_budget):
    """Библиотека вернула отклик БЕЗ квантильной колонки -- отказ БЕЗ
    молчаливой деградации до точечного прогноза."""
    def incomplete_train(*, model_factory, **_kwargs):
        return pd.DataFrame({
            "TFT-median": [1.0, 1.0, 1.0, 1.0],
        })

    monkeypatch.setattr(tft_module, "train_and_forecast", incomplete_train)
    with pytest.raises(ValueError, match="колонка"):
        _tft_fit_predict(_series(), 4)


def test_capacity_error_passes_through_unwrapped(monkeypatch, fast_budget):
    """Прецедент Task 138c: NeuralRuntimeCapacityError проходит сквозь
    адаптер БЕЗ ValueError-обёртки -- HTTP-слой обязан увидеть честный
    статус (503/422), а не потерять его."""

    def capacity_refused(*, model_factory, **_kwargs):
        raise NeuralRuntimeCapacityError("инстанс ниже контрактуемого бюджета")

    monkeypatch.setattr(tft_module, "train_and_forecast", capacity_refused)
    with pytest.raises(NeuralRuntimeCapacityError):
        _tft_fit_predict(_series(), 4)


# ── 7. Legacy synthetic-demo dispatch (прецедент lstm/nbeats/nhits) ──────

def test_legacy_backtest_returns_real_metrics(fast_budget):
    metrics = run_tft_backtest(_series(96), 0.75, 12)
    assert isinstance(metrics, BacktestMetrics)
    assert metrics.mae is not None and metrics.mae >= 0


def test_legacy_backtest_short_series_fails_honestly(fast_budget):
    # 10 точек -> train 8 < TFT_MIN_TRAIN: честный отказ, БЕЗ Naive-подмен.
    with pytest.raises(ValueError, match="слишком короткая"):
        run_tft_backtest(_series(10), 0.8, 12)


def test_training_config_carries_the_adapter_budget(fast_budget):
    config = NeuralTrainingConfig(seed=1, max_steps=TFT_MAX_STEPS)
    assert config.as_dict()["max_steps"] == TFT_MAX_STEPS


# ── 8. Env-рычаг бюджета слабых инстансов (паттерн Task 138c/139/140) ────

def test_env_max_steps_default_override_and_fail_closed(monkeypatch):
    """Пустая env -- сертифицированная константа; задана -- честное
    значение; мусор/меньше 1 -- fail-closed ValueError."""
    from apps.api.model_impls.tft import _resolve_max_steps

    monkeypatch.delenv("CISSTAT_NEURAL_MAX_STEPS", raising=False)
    assert _resolve_max_steps() == TFT_MAX_STEPS

    monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", "120")
    assert _resolve_max_steps() == 120

    monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", " 120 ")
    assert _resolve_max_steps() == 120

    for garbage in ("abc", "0", "-5", "1.5"):
        monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", garbage)
        with pytest.raises(ValueError, match="CISSTAT_NEURAL_MAX_STEPS"):
            _resolve_max_steps()


# ── 9. Контрактный план уровней -- согласован с Task 137 ─────────────────

def test_interval_plan_default_levels_untouched():
    """DEFAULT_NEURAL_QUANTILE_LEVELS контракта (10/50/90) не тронут:
    TFT строит план из alpha адаптера, а не подменяет константу."""
    assert DEFAULT_NEURAL_QUANTILE_LEVELS == (10.0, 50.0, 90.0)
