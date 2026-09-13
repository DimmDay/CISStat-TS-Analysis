# tests/unit/test_deepar_adapter.py
"""Task 142 -- DeepAR: адаптер на едином NeuralForecast-runtime
(neural_runtime.py Task 137), ПЯТЫЙ исполнитель нейро-семейства,
panel-постановка и ВТОРОЙ срез с probabilistic-поверхностью
MQLoss/quantiles.

Прецедент quartet'а lstm/nbeats/nhits/tft (Tasks 138-141) в
neural-runtime: ЕДИНСТВЕННАЯ точка импорта torch/neuralforecast --
apps/api/model_impls/neural_runtime.py (лениво, fail-closed); адаптер:
- ПАНЕЛЬ -- ЯДРО постановки Task 142 (правило моделирования: «DeepAR
  активируется только для настоящей панели с несколькими рядами;
  несколько числовых колонок одного объекта не выдаются за панель»):
  гейт n_series = 1 + len(related_series) >= DEEPAR_MIN_SERIES (yaml
  min_series=5, правило F05) -- отказ ДО фита; панель -- target +
  related-ряды движка, НЕ feature-колонки одного объекта;
- ГЛОБАЛЬНАЯ модель -- суть DeepAR: ОДИН фит на ВСЕЙ панели
  (long-format unique_id/ds/y через сертифицированный to_long_format
  контракта Task 137 с явным series_column); точечный прогноз --
  медиана MQLoss ЦЕЛЕВОГО ряда (unique_id "series_0");
- probabilistic-поверхность -- та же конвенция Task 141 (MQLoss
  зарезервирован за срезами 141-142): квантили декларируются ПРЯМО
  (MQLoss(quantiles=[alpha/2, 0.5, 1-alpha/2])), метод интервалов --
  NeuralIntervalPlan.method="neural_quantile_outputs"; ЭМПИРИКА пробы
  (scripts/task142_deepar_probe.py): DeepAR с loss=MQLoss требует
  valid_loss=MQLoss С ТЕМИ ЖЕ quantiles (честный отказ конструктора
  3.2.2 иначе), колонки отклика "DeepAR-median"/"DeepAR-lo-<w>"/
  "DeepAR-hi-<w>" (width-семантика НАХОДКИ Task 141 п.2);
- clamp-инвариант lower <= median <= upper -- живой гейт поверх
  isfinite (квантильное пересечение MQLoss теоретически возможно --
  heads независимы; честный отказ fold'а вместо clamp-подмен) +
  fault-injection тест (урок НАХОДКИ-3/M10 сертификации Task 138);
- ds-ось -- задекларированная конвенция neural-семейства,
  ПЕРЕИСПОЛЬЗОВАНА из Task 138 (lstm._resolve_time_axis -- единый
  источник истины): datetime + pd.infer_freq либо позиционная
  целочисленная сетка freq=1 (проб);
- гейт неосуществимого окна: n_train < input_size + horizon -- отказ
  ДО фита (MQLoss БЕЗ conformal-калибровки -- потребность +2 НЕ
  следует, прецедент tft; граница n == input+h исполнима -- проб;
  конструктор 3.2.2 хранит input_size+1 -- внутренний сдвиг
  авторегрессии, прижат spy-тестом);
- fail-closed: короткий train, NaN/Inf, значения вне bounded-границ,
  bool-коэрция целочисленных ручек (урок НАХОДКИ-2/M6 сертификации
  Task 138) -- отказ fold'а БЕЗ Naive-fallback и clamp-подмен;
- детерминизм: random_state -> NeuralTrainingConfig.seed -> fold_seed
  -> random_seed КОНСТРУКТОРА модели (ресертификация Task 137; same-
  seed бит-паритет подтверждён пробом: max|diff| = 0.0, другой seed --
  другой прогноз 0.0299);
- проводка бюджета до конструктора прижата spy-тестом (урок
  НАХОДКИ-1/M18 сертификации Task 138).

Бюджет: DEEPAR_MAX_STEPS -- КОНСТАНТА модуля (единый бюджетный рычаг
контракта; семейная конвенция 300; тюнинг бюджета -- вне param_space,
прецедент Task 136), прижата анти-тампер тестом; в тестах
укорачивается monkeypatch'ем для скорости (реальное значение прижато
отдельным тестом БЕЗ monkeypatch).
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

from apps.api.model_impls import deepar as deepar_module  # noqa: E402
from apps.api.model_impls.deepar import (  # noqa: E402
    ALPHA_OPTIONS,
    DEFAULT_PARAMS,
    DEEPAR_ADAPTER_ID,
    DEEPAR_MAX_STEPS,
    DEEPAR_MIN_SERIES,
    DEEPAR_MIN_TRAIN,
    INPUT_SIZE_BOUNDS,
    LSTM_HIDDEN_SIZE_BOUNDS,
    _deepar_fit_predict,
    _quantile_plan,
    _resolve_max_steps,
    run_deepar_backtest,
    validate_deepar_params,
)
from apps.api.schemas import BacktestMetrics  # noqa: E402


# ── 1. Bounded params (fail-closed) ──────────────────────────────────────

def test_default_params_are_declared_and_normalization_fills_defaults():
    normalized = validate_deepar_params(None)
    assert normalized == DEFAULT_PARAMS
    # Чужие ключи (tbats_seasonal_periods и т.п.) игнорируются --
    # соглашение платформы (backtesting.py присылает общие params).
    merged = validate_deepar_params({"tbats_seasonal_periods": 12})
    assert merged == DEFAULT_PARAMS


def test_numeric_params_outside_bounds_are_rejected():
    with pytest.raises(ValueError, match="lstm_hidden_size"):
        validate_deepar_params({"lstm_hidden_size": 4})
    with pytest.raises(ValueError, match="lstm_hidden_size"):
        validate_deepar_params({"lstm_hidden_size": 10_000})
    with pytest.raises(ValueError, match="input_size"):
        validate_deepar_params({"input_size": 2})
    with pytest.raises(ValueError, match="input_size"):
        validate_deepar_params({"input_size": 10_000})
    with pytest.raises(ValueError, match="alpha"):
        validate_deepar_params({"alpha": 0.5})


@pytest.mark.parametrize("handle", ["lstm_hidden_size", "input_size"])
def test_bool_coercion_rejected_for_every_int_handle(handle):
    """Урок НАХОДКИ-2/M6 сертификации Task 138: bool -- подкласс int;
    True->1 проходит нижнюю границу ручек с low=1.  Тест параметризован
    по ВСЕМ целочисленным ручкам адаптера (без надежды на bounds-слой)."""
    with pytest.raises(ValueError, match=handle):
        validate_deepar_params({handle: True})


def test_adapter_budget_constant_is_pinned_to_the_contract_bound():
    """Анти-тампер (урок M1/M7 сертификации Task 136): бюджет обучения --
    константа модуля в честном диапазоне [100, NEURAL_MAX_STEPS_BOUND].
    Тест выполняется БЕЗ monkeypatch (в отличие от скоростных тестов)."""
    assert isinstance(DEEPAR_MAX_STEPS, int)
    assert 100 <= DEEPAR_MAX_STEPS <= NEURAL_MAX_STEPS_BOUND
    assert DEEPAR_MIN_TRAIN >= 1
    assert DEEPAR_MIN_SERIES == 5


# ── 2. ПАНЕЛЬ -- ядро постановки Task 142 ────────────────────────────────

def _series(n: int = 64, level: float = 10.0, seed: int = 8) -> list[float]:
    rng = np.random.default_rng(seed)
    return (level + 0.05 * np.arange(n)
            + rng.standard_normal(n) * 0.2).tolist()


def _panel(n: int = 64, n_related: int = 4, seed: int = 8) -> dict[str, list[float]]:
    """Панель: target + n_related связанных рядов (всего 1 + n_related)."""
    return {
        f"related_{chr(ord('a') + index)}": _series(
            n, level=12.0 + 2.0 * index, seed=seed + index,
        )
        for index in range(n_related)
    }


def test_single_series_is_not_a_panel():
    """Правило моделирования Task 142: одиночный ряд -- НЕ панель;
    честный отказ ДО фита (не «несколько числовых колонок одного
    объекта» и не синтетическая имитация панели)."""
    with pytest.raises(ValueError, match="панель"):
        _deepar_fit_predict(_series(), 4)


def test_panel_below_min_series_is_rejected():
    """yaml::deepar min_series=5 (правило F05): 1 + 3 = 4 < 5 -- отказ
    с честным сообщением о требуемом числе рядов."""
    panel = {name: values for name, values in _panel().items() if name
             in ("related_a", "related_b", "related_c")}
    with pytest.raises(ValueError, match="5"):
        _deepar_fit_predict(_series(), 4, related_series=panel)


def test_panel_gate_message_is_honest_about_numeric_columns():
    with pytest.raises(ValueError, match="не выдаются за панель"):
        _deepar_fit_predict(_series(), 4)


def test_min_series_constant_matches_yaml_declaration():
    from src.catalog.modeling_spec_loader import ModelingSpec

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    model = spec.get_model("deepar")
    assert model.min_series == DEEPAR_MIN_SERIES


def test_panel_series_must_share_one_length():
    """Панель платформы -- общая регулярная сетка: related-ряд короче
    target -- отказ ДО фита (никакого скрытого ресемплинга/обрезки)."""
    panel = _panel()
    first_name = next(iter(panel))
    panel[first_name] = panel[first_name][:-4]
    with pytest.raises(ValueError, match="длин"):
        _deepar_fit_predict(_series(), 4, related_series=panel)


# ── 3. Fail-closed вход адаптера ─────────────────────────────────────────

def test_fit_predict_rejects_horizon_below_one():
    panel = _panel()
    with pytest.raises(ValueError, match="horizon"):
        _deepar_fit_predict(_series(), 0, related_series=panel)


def test_fit_predict_rejects_short_train_without_fallback():
    """Согласованная панель из 24-точечных рядов < DEEPAR_MIN_TRAIN=30:
    честный отказ ДО фита (гейты панели/длины проходят -- отказ именно
    про короткую историю)."""
    with pytest.raises(ValueError, match="слишком короткая"):
        _deepar_fit_predict(_series(24), 2, related_series=_panel(24))


def test_fit_predict_rejects_nonfinite_input():
    panel = _panel()
    with pytest.raises(ValueError, match="NaN/Inf"):
        _deepar_fit_predict([float("nan")] * 64, 2, related_series=panel)


def test_fit_predict_rejects_nonfinite_related_series():
    panel = _panel()
    panel["related_a"] = [float("inf")] * 64
    with pytest.raises(ValueError, match="NaN/Inf"):
        _deepar_fit_predict(_series(), 2, related_series=panel)


def test_fit_predict_rejects_infeasible_window():
    """Гейт неосуществимого окна: n_train=32 < input_size=48 + horizon=4 --
    отказ ДО фита; молчаливое ужатие/паддинг окна запрещены."""
    panel = _panel(32)
    with pytest.raises(ValueError, match="окно"):
        _deepar_fit_predict(_series(32), 4,
                            related_series=panel, params={"input_size": 48})


# ── 4. Probabilistic-поверхность MQLoss/quantiles ────────────────────────

def test_contract_gate_mqloss_requires_levels():
    with pytest.raises(NeuralContractError, match="уровней"):
        resolve_probabilistic_loss("mqloss", levels=())
    plan = interval_levels_for_alpha(0.05)
    assert resolve_probabilistic_loss("mqloss", levels=plan.levels) == "mqloss"


def test_quantile_plan_is_the_shared_contract_plan():
    """Единый источник истины: план квантилей DeepAR -- ТОТ ЖЕ
    контрактный _quantile_plan, что у TFT (Task 141; без дубля)."""
    import apps.api.model_impls.tft as tft_module

    assert deepar_module._quantile_plan is tft_module._quantile_plan
    plan = _quantile_plan(0.05)
    assert plan["quantiles"] == (0.025, 0.5, 0.975)
    assert plan["levels"] == (2.5, 50.0, 97.5)
    assert plan["width"] == 95.0


@pytest.fixture()
def fast_budget(monkeypatch):
    # Скоростной бюджет: панель 5 серий x 64 точки x max_steps=20 --
    # приемлемое время прогона; квантильное пересечение на DeepAR
    # не наблюдалось даже при 3 шагах (проб), clamp-инвариант прижат
    # fault-injection'ом.  Production-константа 300 прижата отдельно.
    monkeypatch.setattr(deepar_module, "DEEPAR_MAX_STEPS", 20)


def test_fit_predict_payload_contract(fast_budget):
    payload = _deepar_fit_predict(_series(), 5, related_series=_panel())
    assert payload["adapter_id"] == DEEPAR_ADAPTER_ID
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
    """Точка = медиана MQLoss целевого ряда; интервалы -- нативные
    квантили (метод NeuralIntervalPlan контракта), НЕ conformal."""
    payload = _deepar_fit_predict(_series(), 4, related_series=_panel())
    intervals = payload["intervals"]
    assert intervals["method"] == "neural_quantile_outputs"
    assert intervals["loss"] == "mqloss"
    assert intervals["alpha"] == DEFAULT_PARAMS["alpha"]
    assert list(intervals["quantiles"]) == [0.025, 0.5, 0.975]
    assert list(intervals["levels"]) == [2.5, 50.0, 97.5]


def test_panel_metadata_declares_the_honest_panel(fast_budget):
    """Панельная фактура дисклоужена: n_series = 1 + len(related);
    ids содержат target "series_0" и related-серии."""
    payload = _deepar_fit_predict(_series(), 4, related_series=_panel())
    assert payload["n_series"] == 5
    assert payload["panel_ids"][0] == "series_0"
    assert len(payload["panel_ids"]) == 5


def test_forecast_is_extracted_for_the_target_series(fast_budget):
    """Глобальная модель обучается на ВСЕЙ панели, но прогноз payload --
    прогноз ЦЕЛЕВОГО ряда: панель с различимыми уровнями (target=10,
    related=30/50/70/90) -- медиана target не может слиться с
    чужими уровнями (честное извлечение по unique_id, не по позиции)."""
    panel = {
        "related_a": _series(level=30.0, seed=11),
        "related_b": _series(level=50.0, seed=12),
        "related_c": _series(level=70.0, seed=13),
        "related_d": _series(level=90.0, seed=14),
    }
    payload = _deepar_fit_predict(_series(level=10.0), 4, related_series=panel)
    forecast = np.asarray(payload["forecast"], dtype=float)
    assert (forecast < 25.0).all(), forecast


@pytest.mark.parametrize("alpha", [0.01, 0.05, 0.10])
def test_all_alpha_whitelist_levels_run_native_quantiles(fast_budget, alpha):
    """Все уровни whitelist'а проходят единый quantiles-путь (проб:
    колонки DeepAR-lo-<w>/DeepAR-median/DeepAR-hi-<w> для всех alpha)."""
    payload = _deepar_fit_predict(_series(), 4,
                                  related_series=_panel(),
                                  params={"alpha": alpha})
    assert payload["params"]["alpha"] == alpha
    assert len(payload["forecast"]) == 4
    assert (np.asarray(payload["lower"]) <= np.asarray(payload["upper"])).all()


def test_same_seed_gives_bit_identical_panel_forecast(fast_budget):
    a = _deepar_fit_predict(_series(), 4, related_series=_panel(),
                            random_state=21)
    b = _deepar_fit_predict(_series(), 4, related_series=_panel(),
                            random_state=21)
    np.testing.assert_array_equal(
        np.asarray(a["forecast"]), np.asarray(b["forecast"]),
    )


def test_different_seed_gives_different_forecast(fast_budget):
    """Дифференциальный оракул (урок OR14c сертификации Task 137):
    сид обязан ДОХОДИТЬ до конструктора модели -- иначе same-seed тест
    вакуумен (всегда seed 1)."""
    a = _deepar_fit_predict(_series(), 4, related_series=_panel(),
                            random_state=21)
    b = _deepar_fit_predict(_series(), 4, related_series=_panel(),
                            random_state=31337)
    assert float(np.abs(
        np.asarray(a["forecast"]) - np.asarray(b["forecast"]),
    ).max()) > 0.0


# ── 5. ds-ось: datetime-метки и позиционная сетка ────────────────────────

def test_datetime_labels_infer_frequency_axis(fast_budget):
    dates = pd.date_range("2024-01-01", periods=64, freq="D")
    labels = [value.strftime("%Y-%m-%d") for value in dates]
    payload = _deepar_fit_predict(_series(), 4, related_series=_panel(),
                                  timestamps=labels)
    assert payload["freq"]["kind"] == "datetime"
    assert payload["freq"]["value"] == "D"


def test_unparseable_labels_fall_back_to_positional_integer_grid(fast_budget):
    """Задекларированная конвенция neural-семейства (переиспользована из
    Task 138): нераспознаваемые метки -- позиционная целочисленная сетка
    (freq=1; проб DeepAR int-ds freq=1 OK)."""
    labels = [f"obs_{index}" for index in range(64)]
    payload = _deepar_fit_predict(_series(), 4, related_series=_panel(),
                                  timestamps=labels)
    assert payload["freq"] == {"kind": "integer", "value": 1}


# ── 6. Проводка бюджета и MQLoss-конвенции конструктора (уроки M18) ──────

class _WiringProbeDone(Exception):
    """Sentinel: короткое замыкание spy-обёртки train_and_forecast."""


def test_budget_wiring_reaches_the_constructor(monkeypatch, fast_budget):
    """Двухслойный spy (урок НАХОДКИ-1/M18 сертификации Task 138):
    (1) адаптер передаёт в runtime config с бюджетом константы модуля;
    (2) фабрика честно разворачивает budget в КОНСТРУКТОР и несёт
    MQLoss как loss И valid_loss С ТЕМИ ЖЕ квантилями (эмпирика пробы
    Task 142: конструктор 3.2.2 честно отказывает на рассогласовании;
    NeuralForecast core валидирует идентичность quantiles loss/valid_loss).
    Внутренний сдвиг input_size+1 (авторегрессия DeepAR 3.2.2) прижат."""
    captured: dict = {}

    def spy(*, model_factory, config, **_kwargs):
        captured["config"] = config
        probe_budget = {
            "max_steps": 321, "random_seed": 777, "accelerator": "cpu",
            "enable_progress_bar": False, "early_stop_patience_steps": -1,
        }
        captured["model"] = model_factory(dict(probe_budget))
        raise _WiringProbeDone()

    monkeypatch.setattr(deepar_module, "train_and_forecast", spy)
    with pytest.raises(_WiringProbeDone):
        _deepar_fit_predict(_series(), 4, related_series=_panel())
    assert captured["config"].max_steps == deepar_module.DEEPAR_MAX_STEPS
    model = captured["model"]
    assert int(model.max_steps) == 321
    assert int(model.random_seed) == 777
    # Внутренний сдвиг авторегрессии: конструктор 3.2.2 хранит
    # input_size+1 (проб scripts/task142_deepar_probe.py, секция 7).
    assert int(model.input_size) == DEFAULT_PARAMS["input_size"] + 1
    assert type(model.loss).__name__ == "MQLoss"
    assert type(model.valid_loss).__name__ == "MQLoss"
    # quantiles хранятся float32 (эмпирика пробы Task 142) -- сравнение
    # с допуском машинной точности float32.
    assert list(map(float, model.loss.quantiles)) == pytest.approx(
        [0.025, 0.5, 0.975], abs=1e-6)
    assert list(map(float, model.valid_loss.quantiles)) == pytest.approx(
        [0.025, 0.5, 0.975], abs=1e-6)
    # lstm_hidden_size доходит до энкодера (конструктор 3.2.2 хранит
    # ширину рекуррентного энкодера в hist_encoder.hidden_size --
    # снятая эмпирика пробы Task 142).
    assert int(model.encoder_hidden_size) == DEFAULT_PARAMS["lstm_hidden_size"]
    assert int(model.hist_encoder.hidden_size) == DEFAULT_PARAMS["lstm_hidden_size"]


# ── 7. Clamp-инвариант и ресурсный отказ (уроки M10/138c) ────────────────

def test_fault_injected_quantile_crossing_is_rejected(monkeypatch, fast_budget):
    """Урок НАХОДКИ-3/M10 сертификации Task 138: clamp-инвариант --
    живой гейт, закреплённый fault-injection тестом.  Для MQLoss гейт
    ловит квантильное пересечение (heads независимы): честный отказ
    fold'а вместо clamp-подмен."""
    def broken_train(*, model_factory, **_kwargs):
        frame = pd.DataFrame({
            "unique_id": ["series_0"] * 4,
            "ds": np.arange(4),
            "DeepAR-median": [1.0, 1.0, 1.0, 1.0],
            "DeepAR-lo-95.0": [5.0] * 4,
            "DeepAR-hi-95.0": [6.0] * 4,
        })
        return frame

    monkeypatch.setattr(deepar_module, "train_and_forecast", broken_train)
    with pytest.raises(NeuralContractError, match="инвариант"):
        _deepar_fit_predict(_series(), 4, related_series=_panel())


def test_missing_native_quantile_column_is_fail_closed(monkeypatch, fast_budget):
    """Библиотека вернула отклик БЕЗ квантильной колонки -- отказ БЕЗ
    молчаливой деградации до точечного прогноза."""
    def incomplete_train(*, model_factory, **_kwargs):
        return pd.DataFrame({
            "unique_id": ["series_0"] * 4,
            "ds": np.arange(4),
            "DeepAR-median": [1.0, 1.0, 1.0, 1.0],
        })

    monkeypatch.setattr(deepar_module, "train_and_forecast", incomplete_train)
    with pytest.raises(ValueError, match="отсутствуют"):
        _deepar_fit_predict(_series(), 4, related_series=_panel())


def test_missing_target_rows_in_response_is_fail_closed(monkeypatch, fast_budget):
    """Отклик без строк целевого ряда (unique_id "series_0") -- отказ:
    глобальная модель обязана вернуть прогноз КАЖДОЙ серии панели."""
    def no_target(*, model_factory, **_kwargs):
        return pd.DataFrame({
            "unique_id": ["series_1"] * 4,
            "ds": np.arange(4),
            "DeepAR-median": [1.0, 1.0, 1.0, 1.0],
            "DeepAR-lo-95.0": [0.5] * 4,
            "DeepAR-hi-95.0": [1.5] * 4,
        })

    monkeypatch.setattr(deepar_module, "train_and_forecast", no_target)
    with pytest.raises(ValueError, match="сери"):
        _deepar_fit_predict(_series(), 4, related_series=_panel())


def test_capacity_error_passes_through_unwrapped(monkeypatch, fast_budget):
    """Прецедент Task 138c: NeuralRuntimeCapacityError проходит сквозь
    адаптер БЕЗ ValueError-обёртки -- HTTP-слой обязан увидеть честный
    статус (503/422), а не потерять его."""

    def capacity_refused(*, model_factory, **_kwargs):
        raise NeuralRuntimeCapacityError("инстанс ниже контрактуемого бюджета")

    monkeypatch.setattr(deepar_module, "train_and_forecast", capacity_refused)
    with pytest.raises(NeuralRuntimeCapacityError):
        _deepar_fit_predict(_series(), 4, related_series=_panel())


# ── 8. Env-рычаг бюджета слабых инстансов (паттерн Task 138c/139/140) ────

def test_env_max_steps_default_override_and_fail_closed(monkeypatch):
    """Пустая env -- сертифицированная константа; задана -- честное
    значение; мусор/меньше 1 -- fail-closed ValueError."""
    monkeypatch.delenv("CISSTAT_NEURAL_MAX_STEPS", raising=False)
    assert _resolve_max_steps() == DEEPAR_MAX_STEPS

    monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", "120")
    assert _resolve_max_steps() == 120

    monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", " 120 ")
    assert _resolve_max_steps() == 120

    for garbage in ("abc", "0", "-5", "1.5"):
        monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", garbage)
        with pytest.raises(ValueError, match="CISSTAT_NEURAL_MAX_STEPS"):
            _resolve_max_steps()


# ── 9. Legacy synthetic-demo dispatch (прецедент var/vecm) ───────────────

def test_legacy_backtest_honestly_refuses_single_series():
    """Legacy synthetic-эндпоинт (POST /v1/models/backtest) передаёт
    ОДИН ряд: panel-постановка Task 142 несовместима с ним по
    определению -- честный отказ БЕЗ Naive-fallback и демо-подмен
    (прецедент var/vecm)."""
    with pytest.raises(ValueError, match="панель"):
        run_deepar_backtest(_series(96), 0.75, 12)


def test_training_config_carries_the_adapter_budget(fast_budget):
    config = NeuralTrainingConfig(seed=1, max_steps=DEEPAR_MAX_STEPS)
    assert config.as_dict()["max_steps"] == DEEPAR_MAX_STEPS


# ── 10. Контрактный план уровней -- согласован с Task 137 ────────────────

def test_interval_plan_default_levels_untouched():
    """DEFAULT_NEURAL_QUANTILE_LEVELS контракта (10/50/90) не тронут:
    DeepAR строит план из alpha адаптера, а не подменяет константу."""
    assert DEFAULT_NEURAL_QUANTILE_LEVELS == (10.0, 50.0, 90.0)


def test_legacy_backtest_export_signature_is_metrics_shaped():
    """run_deepar_backtest существует с сигнатурой model_impls (для
    dispatch-гейта) и ДО фита честно отказывает на одиночном ряде --
    return-путь недостижим без панели (метрики не подменяются)."""
    assert callable(run_deepar_backtest)
    with pytest.raises(ValueError):
        run_deepar_backtest([1.0] * 96, 0.75, 12)
    assert BacktestMetrics is not None
