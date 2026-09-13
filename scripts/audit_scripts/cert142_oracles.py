# scripts/audit_scripts/cert142_oracles.py
"""Независимые оракулы ПЕРЕСЕРТИФИКАЦИИ Task 142 (DeepAR vertical slice)
после исправления блокирующей находки F3 первого аудита.

Исправление F3 (ошибка коллеги, устранена аудитором -- Task 142a):
probabilistic-поверхность среза переведена с MQLoss на DistributionLoss
(StudentT) + scaler_type="robust" (семейная конвенция lstm/tft):
- M1: рекуррентный predict 3.2.2 (_base_model.py) для не-distribution
  losses перезаписывает output_batch СРЕДНИМ квантилей ДО сохранения
  y_hat -- все квантильные каналы получают одно значение, ширина 0;
  лечится ТОЛЬКО сменой loss-головы (DistributionLoss: y_hat =
  concat(mean, quants) -- раздельные значения; проб E1/E2);
- M2: DeepAR default scaler_type="identity" -- рекуррентный декодер
  с Adam(1e-3) за семейный бюджет 300 шагов не выходит на масштаб
  данных; LSTM/TFT не страдают (их default "robust"); лечится явным
  scaler_type="robust" (проб E1/E3: у коллапса точки иная ось, чем у
  коллапса ширины -- каждый механизм убивается своим рычагом).

Методология сертификаций 136-141 сохранена: оракулы работают на
СОБСТВЕННЫХ данных аудитора (панельный генератор ниже, seed=142 -- НЕ
фикстуры исполнителя), мутационные kill-подмножества -- в
cert142_mutations.py (fresh subprocess).

Структура:
- A -- реестр v2/dispatch/yaml/константы/импорт-гигиена (без фита);
  ПАНЕЛЬНАЯ ось: input_kind="panel", requires_related_series=True,
  PRODUCTION_BACKTEST_MODEL_IDS == 24 (каталог 24/24 полон);
- B -- fail-closed валидация параметров (мои значения; bool-коэрция
  ВСЕХ целочисленных ручек, bounded-границы, alpha whitelist);
- C -- ПАНЕЛЬНЫЕ гейты + гейты данных: min_series=5 (полоса
  n_series=1..4 -- отказ, 5 -- адмиссибельна), MIN_TRAIN, полоса
  неосуществимого окна [input+h-1] (гейт БЕЗ '+2' -- MQLoss без
  conformal-калибровки, прецедент tft), граница nobs=input+h,
  related-ряды: NaN/Inf, длина != target;
- D -- живая проводка до КОНСТРУКТОРА (fake-harness без torch):
  kwargs фабрики (h/input_size/lstm_hidden_size/alias), DistributionLoss
  (StudentT, квантили плана) как loss + MAE как valid_loss +
  scaler_type="robust" + trajectory_samples, fold_seed, env-рычаг,
  ПАНЕЛЬ доходит до train_and_forecast (long-format n_series x nobs);
- F -- fault-injection на синтетическом ПАНЕЛЬНОМ отклике: выбор
  целевого ряда ПО unique_id (не по позиции!), сортировка по ds,
  missing-строки целевого ряда, отсутствие медианы/квантиля, NaN,
  квантильное пересечение (clamp-гейт), равенство на границе,
  capacity passthrough, contract-wrap, spy resolve_probabilistic_loss;
- G -- provenance-метаданные: intervals.method/loss/quantiles для
  всех alpha, width-суффиксы, identity плана с tft (единый источник
  истины), panel-фактура payload (n_series/panel_ids);
- H -- executor-мэппинг, quintet-когорта (quartet univariate + deepar
  panel), cohort-контракт (n_series/min_series/input_kind), EDA shape-
  критерий (n_series >= 5), panel-движок (гейты objective/input_kind/
  префикс/пересечение/leakage related-префиксов/panel-блок), schema
  BacktestResponse.panel, легаси-эндпоинт (честный отказ);
- E -- реальные end-to-end фиты на МОИХ данных (env-гейт
  CISSTAT_CERT142_REAL=1; исключены из мутационного kill-прогона
  маркером real_fit): честная ШИРИНА интервала (lower < median <
  upper строго, отступ >= 1% масштаба -- НЕ схлопнут к медиане; e01,
  был RED из-за F3 -- теперь GREEN на исправленной поверхности),
  монотонность W(0.01) > W(0.05) > W(0.10) (e02, был RED -- F3),
  масштаб ТОЧКИ (e05, НОВЫЙ -- убивает мутанта scaler-а: медиана
  живого прогона отслеживает уровень данных, интервал ПОКРЫВАЕТ
  уровень), same-seed бит-паритет, cross-seed различимость,
  РЕАЛЬНЫЙ panel-движок (глобальный OOF cohort на моих 5 рядах,
  2 folds).

Запуск: OMP_NUM_THREADS=1 python3 -m pytest
scripts/audit_scripts/cert142_oracles.py -q            (fast, 46)
CISSTAT_CERT142_REAL=1 ... -m real_fit -q              (реальные фиты)
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

REAL_MODE = os.environ.get("CISSTAT_CERT142_REAL") == "1"

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
    ModelExecutionResult,
)
from apps.api.model_readiness import PRODUCTION_BACKTEST_MODEL_IDS  # noqa: E402
from apps.api.model_impls import tft as tft_mod  # noqa: E402
from apps.api.model_impls import deepar as deepar_mod  # noqa: E402
from apps.api.model_impls.deepar import (  # noqa: E402
    ALPHA_OPTIONS,
    DEFAULT_PARAMS,
    DEEPAR_ADAPTER_ID,
    DEEPAR_LOSS_KEY,
    DEEPAR_MAX_STEPS,
    DEEPAR_MIN_SERIES,
    DEEPAR_MIN_TRAIN,
    DEEPAR_TRAJECTORY_SAMPLES,
    INPUT_SIZE_BOUNDS,
    LSTM_HIDDEN_SIZE_BOUNDS,
    _deepar_fit_predict,
    _quantile_plan,
    _resolve_max_steps,
    run_deepar_backtest,
    validate_deepar_params,
)

# ---------------------------------------------------------------------------
# Собственные данные аудитора (seed=142): ПАНЕЛЬ -- target + 4 related
# ---------------------------------------------------------------------------

PANEL_N = 120
PANEL_HORIZON = 12


def _panel_data(n: int = PANEL_N, seed: int = 142):
    rng = np.random.default_rng(seed)
    t = np.arange(n, dtype=float)
    target = 100.0 + 0.08 * t + 6.0 * np.sin(2.0 * np.pi * t / 14.0) + rng.normal(
        0.0, 1.5, n
    )
    related = {
        "flow": 40.0 + 0.05 * t + 3.0 * np.cos(2.0 * np.pi * t / 7.0)
        + rng.normal(0.0, 1.0, n),
        "pressure": 12.0 + 2.5 * np.sin(2.0 * np.pi * t / 10.0)
        + rng.normal(0.0, 0.8, n),
        "load": 70.0 - 0.06 * t + rng.normal(0.0, 1.2, n),
        "price": 25.0 + 0.03 * t + 2.0 * np.sin(2.0 * np.pi * t / 21.0)
        + rng.normal(0.0, 1.0, n),
    }
    return target, related


@pytest.fixture()
def my_panel():
    return _panel_data()


# ---------------------------------------------------------------------------
# Fake-harness: детерминированная подмена нейро-runtime (без torch).
# ---------------------------------------------------------------------------


class _RecordingDeepAR:
    last: dict[str, Any] | None = None

    def __init__(self, **kwargs):
        self.kwargs = dict(kwargs)
        _RecordingDeepAR.last = self.kwargs


class _RecordingMQLoss:
    last: list[float] | None = None

    def __init__(self, *, quantiles=None, **kwargs):
        _RecordingMQLoss.last = [float(q) for q in (quantiles or ())]


class _RecordingDistributionLoss:
    last: dict[str, Any] | None = None

    def __init__(self, *, distribution=None, quantiles=None, **kwargs):
        _RecordingDistributionLoss.last = {
            "distribution": distribution,
            "quantiles": [float(q) for q in (quantiles or ())],
        }


class _RecordingMAE:
    calls: int = 0

    def __init__(self, **kwargs):
        _RecordingMAE.calls += 1


class _FakePytorchNS:
    MQLoss = _RecordingMQLoss
    DistributionLoss = _RecordingDistributionLoss
    MAE = _RecordingMAE


class _FakeLossesNS:
    pytorch = _FakePytorchNS


class _FakeModelsNS:
    DeepAR = _RecordingDeepAR


class _FakeNFModule:
    models = _FakeModelsNS
    losses = _FakeLossesNS


class _Harness:
    """Подмена train_and_forecast/_require_neuralforecast в deepar-модуле.

    Синтетический отклик строится ПО контракту платформы
    (interval_width_for_alpha -- единый источник истины ширины,
    unique_id/ds long-format), реальная живость пути -- секция E.
    """

    def __init__(self, monkeypatch):
        self.calls: dict[str, Any] = {}
        self.loss_spy: list[dict[str, Any]] = []
        self.preds: pd.DataFrame | None = None
        self.raise_on_call: Exception | None = None

        real_resolve = deepar_mod.resolve_probabilistic_loss

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
                "train_long": train_long,
            })
            if self.raise_on_call is not None:
                raise self.raise_on_call
            budget = {
                "max_steps": config.max_steps,
                "random_seed": fold_seed(config.seed, fold_index=fold_index),
            }
            model_factory(budget)
            assert self.preds is not None, "тест не задал синтетический отклик"
            return self.preds

        monkeypatch.setattr(
            deepar_mod, "_require_neuralforecast", lambda: _FakeNFModule()
        )
        monkeypatch.setattr(
            deepar_mod, "resolve_probabilistic_loss", _spy_resolve
        )
        monkeypatch.setattr(
            deepar_mod, "train_and_forecast", _fake_train_and_forecast
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

    monkeypatch.setattr(deepar_mod, "train_and_forecast", _guard)
    yield reached


def _panel_preds(
    alpha: float,
    horizon: int,
    *,
    lo: float = 1.0,
    med: float = 3.0,
    hi: float = 5.0,
    ids: tuple[str, ...] = tuple(f"series_{i}" for i in range(5)),
    rows_per_series: int | None = None,
    include_unique_id: bool = True,
    shuffle: bool = False,
) -> pd.DataFrame:
    """Синтетический отклик NeuralForecast (long-format, panel).

    Ключевая фактура для оракулов честности выборки: колонки ЗНАЧЕНИЙ
    идут в порядке lo -> median -> hi (позиционный экстрактор 'первая
    колонка' получит lo, а не медиану); медиана series_0 РАСТЁТ по ds
    (3.0 + 0.1*step), прочие серии -- другой уровень (100 + 0.1*step):
    выбор целевого ряда по позиции/по другой серии детектируется;
    shuffle -- строки серий перемешаны по ds: экстрактор обязан
    отсортировать по ds (payload строго возрастает).
    """
    width = interval_width_for_alpha(alpha)
    rng = np.random.default_rng(7)
    frames = []
    for uid in ids:
        rows = horizon if rows_per_series is None else rows_per_series
        ds = np.arange(rows, dtype=float)
        if shuffle:
            order = rng.permutation(rows)
        else:
            order = np.arange(rows)
        ds_col = ds[order]
        if uid == "series_0":
            med_col = med + 0.1 * ds_col
        else:
            med_col = 100.0 + 0.1 * ds_col
        frames.append(pd.DataFrame({
            **({"unique_id": uid} if include_unique_id else {}),
            "ds": ds_col,
            f"DeepAR-lo-{width}": np.full(rows, lo, dtype=float),
            "DeepAR-median": med_col,
            f"DeepAR-hi-{width}": np.full(rows, hi, dtype=float),
        }))
    frame = pd.concat(frames, ignore_index=True)
    if shuffle:
        frame = frame.sample(frac=1.0, random_state=11).reset_index(drop=True)
    return frame


def _run_fit(
    target, horizon, *, related_series=None, params=None, random_state=142,
    timestamps=None,
):
    """Публичная поверхность адаптера на МОИХ данных.

    related_series ДОЛГОЛЕЕ target автоматически подрезается до его
    длины (панель -- общая регулярная сетка: нормализация подготовки
    данных аудитора); КОРОТКИЕ related остаются как есть -- оракул
    несоответствия длин (b09) подрезкой НЕ маскируется."""
    values = list(target)
    if related_series:
        related_series = {
            name: (list(series_values[: len(values)])
                   if len(series_values) > len(values) else series_values)
            for name, series_values in related_series.items()
        }
    return _deepar_fit_predict(
        target, horizon, related_series=related_series, params=params,
        random_state=random_state, timestamps=timestamps,
    )


def _fit_panel(my_panel, horizon=PANEL_HORIZON, *, harness=None, params=None,
               random_state=142, timestamps=None, n_series=5):
    """Полная панель (target + 4 related) через публичную поверхность."""
    target, related = my_panel
    if n_series < 5:
        related = dict(list(related.items())[: n_series - 1])
    kwargs: dict[str, Any] = {}
    if harness is not None:
        kwargs["related_series"] = related
        harness.set_preds(_panel_preds(0.05, horizon))
    payload = _run_fit(
        [float(value) for value in target], horizon,
        related_series=kwargs.get("related_series", related),
        params=params, random_state=random_state, timestamps=timestamps,
    )
    return payload


# ---------------------------------------------------------------------------
# Секция E: реальные фиты (env-гейт; маркер real_fit)
# ---------------------------------------------------------------------------

_REAL_CACHE: dict[tuple, dict[str, Any]] = {}

real_fit = pytest.mark.real_fit


def _real_panel_fit(
    my_panel, *, alpha, seed, horizon=PANEL_HORIZON, steps=50, fresh=False,
) -> dict[str, Any]:
    key = (alpha, seed, horizon, steps, fresh)
    if not fresh and key in _REAL_CACHE:
        return _REAL_CACHE[key]
    previous = os.environ.get("CISSTAT_NEURAL_MAX_STEPS")
    os.environ["CISSTAT_NEURAL_MAX_STEPS"] = str(steps)
    try:
        target, related = my_panel
        payload = _run_fit(
            [float(value) for value in target], horizon,
            related_series={name: [float(v) for v in values]
                            for name, values in related.items()},
            params={"alpha": alpha, "lstm_hidden_size": 16, "input_size": 24},
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


def _scale(my_panel) -> float:
    target, _ = my_panel
    return float(np.std(np.asarray(target, dtype=float)))


# ---------------------------------------------------------------------------
# A. Реестр / dispatch / yaml / константы / импорт-гигиена
# ---------------------------------------------------------------------------


class TestARegistryAndConstants:
    def test_a01_registry_record_shape_panel_axis(self):
        definition = MODEL_EXECUTION_REGISTRY.require("deepar")
        assert definition.model_id == "deepar"
        assert definition.family_id == "neural"
        assert definition.adapter_id == "neuralforecast-deepar"
        assert definition.objective == "level_forecast"
        # ПАНЕЛЬНАЯ ось Task 142 -- единственный такой носитель в семействе
        assert definition.input_kind == "panel"
        assert definition.requires_related_series is True
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

    def test_a02_production_count_24_catalog_full(self):
        # Каталог нейро-семейства полон: 24/24 production, catalog_only нет
        ids = PRODUCTION_BACKTEST_MODEL_IDS
        assert len(ids) == 24
        assert "deepar" in ids
        assert MODEL_EXECUTION_REGISTRY.model_ids == ids
        assert len(MODEL_EXECUTION_REGISTRY.model_ids) == 24

    def test_a03_dispatch_registered_conditionally(self):
        from apps.api.routers import models as models_router

        impl = models_router._BACKTEST_IMPLEMENTATIONS.get("deepar")
        assert impl is run_deepar_backtest
        # dispatch<->реестр согласован: bridge-проверка модуля
        assert models_router.PRODUCTION_BACKTEST_MODEL_IDS == frozenset(
            models_router._BACKTEST_IMPLEMENTATIONS
        )

    def test_a04_yaml_param_space_4_trials_min_series(self):
        import yaml

        data = yaml.safe_load(
            (REPO / "rules" / "modeling.yaml").read_text(encoding="utf-8")
        )
        entry = None
        for family in data["families"]:
            for model in family.get("models", []):
                if model.get("id") == "deepar":
                    entry = model
        assert entry is not None, "deepar отсутствует в rules/modeling.yaml"
        space = entry["param_space"]
        assert space == {"lstm_hidden_size": [32, 64], "input_size": [24, 48]}
        trials = 1
        for values in space.values():
            trials *= len(values)
        assert trials == 4 and trials <= 64
        # правило F05 в yaml (панель) + методологическая ось D06 не тронута
        assert entry["min_series"] == DEEPAR_MIN_SERIES == 5
        assert entry["requires_gpu"] is True
        assert entry["min_observations"] == 200

    def test_a05_family_constants(self):
        assert DEEPAR_ADAPTER_ID == "neuralforecast-deepar"
        assert DEEPAR_MAX_STEPS == 300
        assert 100 <= DEEPAR_MAX_STEPS <= NEURAL_MAX_STEPS_BOUND
        assert DEEPAR_MIN_TRAIN == 30
        assert DEEPAR_MIN_SERIES == 5
        assert LSTM_HIDDEN_SIZE_BOUNDS == (8, 128)
        assert INPUT_SIZE_BOUNDS == (8, 104)
        assert ALPHA_OPTIONS == (0.01, 0.05, 0.10)
        assert DEFAULT_PARAMS == {
            "lstm_hidden_size": 32, "input_size": 24, "alpha": 0.05,
        }

    def test_a06_no_torch_at_module_import(self):
        code = (
            "import sys; import apps.api.model_impls.deepar as m; "
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
        "key,patched",
        [
            ("lstm_hidden_size", True),
            ("lstm_hidden_size", False),
            ("input_size", True),
            ("input_size", False),
            ("lstm_hidden_size", 32.5),
            ("lstm_hidden_size", "32"),
            ("input_size", None),
        ],
    )
    def test_b01_bool_and_non_int_rejected_all_int_handles(self, key, patched):
        # урок НАХОДКИ-2/M6: bool-коэрция целочисленных ручек отклоняется
        with pytest.raises(ValueError, match="целочисленный"):
            validate_deepar_params({key: patched})

    @pytest.mark.parametrize(
        "patched,match",
        [
            ({"lstm_hidden_size": 7}, "вне bounded диапазона"),
            ({"lstm_hidden_size": 129}, "вне bounded диапазона"),
            ({"input_size": 7}, "вне bounded диапазона"),
            ({"input_size": 105}, "вне bounded диапазона"),
            ({"alpha": 0.025}, "вне допустимого набора"),
            ({"alpha": 0.2}, "вне допустимого набора"),
            ({"alpha": "половина"}, "не числовой"),
        ],
    )
    def test_b02_bounds_and_whitelists(self, patched, match):
        with pytest.raises(ValueError, match=match):
            validate_deepar_params(patched)

    @pytest.mark.parametrize(
        "hidden,size", [(8, 8), (16, 24), (32, 48), (64, 104), (128, 8)],
    )
    def test_b03_bounded_pairs_admitted(self, hidden, size):
        normalized = validate_deepar_params(
            {"lstm_hidden_size": hidden, "input_size": size}
        )
        assert normalized["lstm_hidden_size"] == hidden
        assert normalized["input_size"] == size

    def test_b04_unknown_keys_ignored_defaults_echoed(self):
        normalized = validate_deepar_params({"foo": "bar", "loss": "mse"})
        assert normalized == dict(DEFAULT_PARAMS)

    def test_b05_input_nan_inf_target_rejected_adapter_layer(
        self, my_panel, fit_guard
    ):
        # match -- формулировка ИМЕННО адаптерного гейта (_validated_series,
        # ДО to_long_format): контрактный to_long_format дублирует NaN-гейт
        # ниже по стеку (defense-in-depth, Task 137), но адаптер обязан
        # отказывать на своём слое (урок эквивалентного действия M04/141)
        target, related = my_panel
        dirty = [float(value) for value in target]
        dirty[3] = float("nan")
        with pytest.raises(ValueError, match="импутация запрещена"):
            _run_fit(dirty, 12, related_series=related)
        dirty2 = [float(value) for value in target]
        dirty2[5] = float("inf")
        with pytest.raises(ValueError, match="импутация запрещена"):
            _run_fit(dirty2, 12, related_series=related)
        assert not fit_guard.get("reached_fit")

    def test_b06_input_nan_inf_related_rejected(self, my_panel, fit_guard):
        # ПАНЕЛЬ-специфика: NaN/Inf в ЛЮБОЙ related-серии -- отказ
        target, related = my_panel
        dirty_related = {name: [float(v) for v in values]
                         for name, values in related.items()}
        dirty_related["pressure"][7] = float("nan")
        with pytest.raises(ValueError, match="импутация запрещена"):
            _run_fit([float(v) for v in target], 12,
                     related_series=dirty_related)
        dirty_related["load"][2] = float("-inf")
        with pytest.raises(ValueError, match="импутация запрещена"):
            _run_fit([float(v) for v in target], 12,
                     related_series=dirty_related)
        assert not fit_guard.get("reached_fit")

    def test_b07_empty_target_rejected(self, my_panel, fit_guard):
        # панельный гейт срабатывает РАНЬШЕ: чтобы дойти до честного
        # 'серия пуста' адаптера, подаём 4 related (n_series == 5)
        _, related = my_panel
        with pytest.raises(ValueError, match="пуст"):
            _run_fit([], 12, related_series=related)
        assert not fit_guard.get("reached_fit")

    @pytest.mark.parametrize("horizon", [0, -1, -7])
    def test_b08_horizon_positive(self, horizon, fit_guard, my_panel):
        target, related = my_panel
        with pytest.raises(ValueError, match="horizon"):
            _run_fit([float(v) for v in target], horizon,
                     related_series=related)
        assert not fit_guard.get("reached_fit")

    def test_b09_related_length_mismatch_rejected(
        self, my_panel, fit_guard
    ):
        # панель -- общая регулярная сетка: короче-длиннее related -- отказ
        target, related = my_panel
        short = {name: [float(v) for v in values][:100]
                 for name, values in related.items()}
        with pytest.raises(ValueError, match="не совпадает с длиной target"):
            _run_fit([float(v) for v in target], 12, related_series=short)
        assert not fit_guard.get("reached_fit")

# ---------------------------------------------------------------------------
# C. ПАНЕЛЬНЫЕ гейты + гейты данных
# ---------------------------------------------------------------------------


class TestCPanelAndDataGates:
    @pytest.mark.parametrize("n_series", [1, 2, 3, 4])
    def test_c01_min_series_gate_honest_band(self, my_panel, n_series,
                                             fit_guard):
        # ЯДРО постановки: n_series = 1 + len(related) < 5 -- отказ ДО фита
        target, related = my_panel
        with pytest.raises(ValueError, match="min_series=5") as excinfo:
            _run_fit(
                [float(v) for v in target], 12,
                related_series=dict(list(related.items())[: n_series - 1]),
            )
        message = str(excinfo.value)
        # честная формулировка правила моделирования (несколько числовых
        # колонок одного объекта -- НЕ панель)
        assert "не выдаются за панель" in message
        assert f"n_series={n_series}" in message
        assert not fit_guard.get("reached_fit")

    def test_c02_min_series_boundary_admissible(self, harness, my_panel):
        # n_series == 5 ровно -- панель адмиссибельна (мутант min_series-1
        # умрёт на полосе c01; over-strict min_series+1 -- здесь)
        harness.set_preds(_panel_preds(0.05, 8))
        target, related = my_panel
        payload = _run_fit(
            [float(v) for v in target], 8, related_series=related,
            params={"input_size": 24},
        )
        assert len(payload["forecast"]) == 8
        assert payload["n_series"] == 5
        assert harness.calls["horizon"] == 8

    def test_c03_min_train_gate(self, my_panel, fit_guard):
        target, related = my_panel
        with pytest.raises(ValueError, match="слишком короткая"):
            _run_fit(
                [float(v) for v in target[:29]], 2,
                related_series={name: values[:29]
                                for name, values in related.items()},
            )
        assert not fit_guard.get("reached_fit")

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
    def test_c04_window_gate_honest_band(self, my_panel, input_size, horizon,
                                         nobs, fit_guard):
        # nobs = input+h-1 на ВСЕЙ полосе -- честный ValueError ДО фита
        # (MQLoss без conformal-калибровки -- гейт БЕЗ '+2' тройки,
        # прецедент tft; стабильность полосы -- проб исполнителя
        # «DeepAR requires at least N» = input+h)
        target, related = my_panel
        with pytest.raises(
            ValueError, match="неосуществимое окно"
        ) as excinfo:
            _run_fit(
                [float(v) for v in target[:nobs]], horizon,
                related_series={name: values[:nobs]
                                for name, values in related.items()},
                params={"input_size": input_size},
            )
        message = str(excinfo.value)
        assert f"input_size={input_size}" in message
        assert f"horizon={horizon}" in message
        assert not fit_guard.get("reached_fit")

    def test_c05_window_boundary_admissible(self, harness, my_panel):
        # nobs == input+h -- граница полосы адмиссибельна (мутант
        # over-strict '+2' тройки умрёт здесь: 30 < 14+16+2)
        harness.set_preds(_panel_preds(0.05, 16))
        target, related = my_panel
        payload = _run_fit(
            [float(v) for v in target[:30]], 16, related_series=related,
            params={"input_size": 14, "lstm_hidden_size": 16},
        )
        assert len(payload["forecast"]) == 16
        assert harness.calls["horizon"] == 16

    def test_c06_ds_axis_integer_vs_datetime(self, harness, my_panel):
        harness.set_preds(_panel_preds(0.05, 6))
        target, related = my_panel
        payload_int = _run_fit(
            [float(v) for v in target[:60]], 6, related_series=related,
            params={"input_size": 8},
        )
        assert payload_int["freq"] == {"kind": "integer", "value": 1}
        stamps = [
            stamp.strftime("%Y-%m-%d")
            for stamp in pd.date_range("2024-01-01", periods=60, freq="D")
        ]
        payload_dt = _run_fit(
            [float(v) for v in target[:60]], 6, related_series=related,
            params={"input_size": 8}, timestamps=stamps,
        )
        assert payload_dt["freq"]["kind"] == "datetime"
        assert str(payload_dt["freq"]["value"]).startswith("D")


# ---------------------------------------------------------------------------
# D. Живая проводка ручек и ПАНЕЛИ до конструктора/runtime (fake-harness)
# ---------------------------------------------------------------------------


class TestDConstructorWiring:
    def test_d01_handles_and_heads_reach_constructor(self, harness, my_panel):
        harness.set_preds(_panel_preds(0.05, 7))
        target, related = my_panel
        payload = _run_fit(
            [float(v) for v in target[:80]], 7, related_series=related,
            params={"lstm_hidden_size": 64, "input_size": 48},
            random_state=142,
        )
        kwargs = _RecordingDeepAR.last
        assert kwargs["h"] == 7
        assert kwargs["input_size"] == 48
        assert kwargs["lstm_hidden_size"] == 64
        assert kwargs["alias"] == "DeepAR"
        # Исправление F3: голова -- DistributionLoss(StudentT, квантили
        # плана), valid_loss -- MAE (дефолт библиотеки для distribution-
        # потерь), per-window robust-скейлер и траекторный бюджет
        # доходят до КОНСТРУКТОРА (каждый рычаг -- против своего
        # механизма деградации F3: M1 ширина / M2 масштаб)
        assert _RecordingDistributionLoss.last == {
            "distribution": "StudentT",
            "quantiles": [0.025, 0.5, 0.975],
        }
        assert kwargs["loss"].__class__ is _RecordingDistributionLoss
        assert kwargs["valid_loss"].__class__ is _RecordingMAE
        assert kwargs["scaler_type"] == "robust"
        assert kwargs["trajectory_samples"] == DEEPAR_TRAJECTORY_SAMPLES
        # сид доходит до КОНСТРУКТОРА через fold_seed (ресертификация 137)
        expected_seed = fold_seed(142, fold_index=0)
        assert kwargs["random_seed"] == expected_seed
        assert harness.calls["config"].seed == 142
        assert payload["seed"] == 142
        assert np.array_equal(payload["forecast"], 3.0 + 0.1 * np.arange(7.0))
        assert np.array_equal(payload["lower"], np.full(7, 1.0))
        assert np.array_equal(payload["upper"], np.full(7, 5.0))

    def test_d02_env_lever_wiring_and_failclosed(self, harness, my_panel,
                                                 monkeypatch):
        harness.set_preds(_panel_preds(0.05, 6))
        target, related = my_panel
        monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", "77")
        payload = _run_fit([float(v) for v in target[:60]], 6,
                           related_series=related, params={"input_size": 8})
        assert harness.calls["config"].max_steps == 77
        assert payload["max_steps"] == 77
        monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", "  88  ")
        payload = _run_fit([float(v) for v in target[:60]], 6,
                           related_series=related, params={"input_size": 8})
        assert payload["max_steps"] == 88
        for garbage in ("abc", "2.5", "0", "-3", ""):
            if garbage == "":
                monkeypatch.delenv("CISSTAT_NEURAL_MAX_STEPS", raising=False)
                assert _resolve_max_steps() == DEEPAR_MAX_STEPS
                continue
            monkeypatch.setenv("CISSTAT_NEURAL_MAX_STEPS", garbage)
            with pytest.raises(ValueError, match="не целое >= 1"):
                _resolve_max_steps()

    def test_d03_conformal_not_activated(self, harness, my_panel):
        # levels=() -- conformal-контур НЕ активируется (квантили нативны)
        harness.set_preds(_panel_preds(0.05, 6))
        target, related = my_panel
        _run_fit([float(v) for v in target[:60]], 6, related_series=related,
                 params={"input_size": 8})
        assert harness.calls["levels"] == ()
        assert harness.loss_spy[0]["loss"] == DEEPAR_LOSS_KEY == "distribution"

    def test_d04_panel_reaches_runtime_long_format(self, harness, my_panel):
        # ПАНЕЛЬ доходит до train_and_forecast: long-format
        # n_series * nobs строк, уникальные id всех серий панели,
        # общая ds-сетка; target-only мутант умрёт на длине/множестве
        harness.set_preds(_panel_preds(0.05, 6))
        target, related = my_panel
        nobs = 60
        _run_fit([float(v) for v in target[:nobs]], 6, related_series=related,
                 params={"input_size": 8})
        long_frame = harness.calls["train_long"]
        assert len(long_frame) == 5 * nobs
        assert set(long_frame["unique_id"].astype(str)) == {
            f"series_{index}" for index in range(5)
        }
        ds_by_series = {
            uid: set(group["ds"])
            for uid, group in long_frame.groupby("unique_id")
        }
        grids = list(ds_by_series.values())
        assert all(grid == grids[0] for grid in grids), "ds-сетка общая"
        assert len(grids[0]) == nobs

    def test_d05_payload_panel_facture(self, harness, my_panel):
        harness.set_preds(_panel_preds(0.05, 6))
        target, related = my_panel
        payload = _run_fit([float(v) for v in target[:60]], 6,
                           related_series=related, params={"input_size": 8})
        assert payload["n_series"] == 5
        assert payload["panel_ids"] == [f"series_{i}" for i in range(5)]
        assert payload["nobs"] == 60
        assert payload["adapter_id"] == "neuralforecast-deepar"


# ---------------------------------------------------------------------------
# F. Fault-injection на синтетическом панельном отклике
# ---------------------------------------------------------------------------


class TestFFaultInjection:
    def test_f01_median_missing_fail_closed(self, harness, my_panel):
        width = interval_width_for_alpha(0.05)
        preds = _panel_preds(0.05, 6)
        harness.set_preds(preds.drop(columns=["DeepAR-median"]))
        target, related = my_panel
        with pytest.raises(ValueError, match="без медианы"):
            _run_fit([float(v) for v in target[:60]], 6,
                     related_series=related, params={"input_size": 8})
        assert width == 95.0

    def test_f02_quantile_column_missing(self, harness, my_panel):
        # (a) lo-колонка отсутствует -- fail-closed _width_suffix (считывает
        # ШИРИНУ с отклика): точное сообщение, не просто 'отсутствуют'
        preds = _panel_preds(0.05, 6)
        harness.set_preds(preds.drop(columns=["DeepAR-lo-95.0"]))
        target, related = my_panel
        with pytest.raises(
            ValueError, match=r"квантильные колонки 'DeepAR-lo-<w>'"
        ):
            _run_fit([float(v) for v in target[:60]], 6,
                     related_series=related, params={"input_size": 8})
        # (b) lo есть, hi отсутствует -- гейт выборки _quantile_column
        # (медиана жива, lower извлечена, верхняя граница отсутствует)
        preds2 = _panel_preds(0.05, 6)
        harness.set_preds(preds2.drop(columns=["DeepAR-hi-95.0"]))
        with pytest.raises(
            ValueError, match=r"квантильная колонка 'DeepAR-hi-95.0'"
        ):
            _run_fit([float(v) for v in target[:60]], 6,
                     related_series=related, params={"input_size": 8})

    def test_f03_nan_in_output_rejected(self, harness, my_panel):
        preds = _panel_preds(0.05, 6)
        preds.loc[preds["unique_id"] == "series_0", "DeepAR-median"] *= np.nan
        harness.set_preds(preds)
        target, related = my_panel
        with pytest.raises(ValueError, match="NaN/Inf"):
            _run_fit([float(v) for v in target[:60]], 6,
                     related_series=related, params={"input_size": 8})

    def test_f04_target_rows_missing_fail_closed(self, harness, my_panel):
        # глобальная модель обязана вернуть прогноз КАЖДОЙ серии панели:
        # целевой ряд короче horizon -- честный отказ (missing-строки)
        harness.set_preds(_panel_preds(0.05, 6, rows_per_series=5))
        target, related = my_panel
        with pytest.raises(ValueError, match="вместо horizon"):
            _run_fit([float(v) for v in target[:60]], 6,
                     related_series=related, params={"input_size": 8})

    def test_f05_unique_id_column_missing(self, harness, my_panel):
        harness.set_preds(_panel_preds(0.05, 6, include_unique_id=False))
        target, related = my_panel
        with pytest.raises(ValueError, match="unique_id"):
            _run_fit([float(v) for v in target[:60]], 6,
                     related_series=related, params={"input_size": 8})

    def test_f06_target_extraction_by_unique_id_not_position(
        self, harness, my_panel,
    ):
        # КЛЮЧЕВОЙ панельный оракул: series_0 НЕ первая в отклике --
        # точечный прогноз обязан прийти ИМЕННО от целевого ряда
        # (позиционный экстрактор/'первая группа' умрёт: медианы прочих
        # серий -- уровень 100+, у целевого -- 3.0 + 0.1*ds)
        preds = _panel_preds(
            0.05, 6,
            ids=("series_3", "series_1", "series_0", "series_4", "series_2"),
        )
        harness.set_preds(preds)
        target, related = my_panel
        payload = _run_fit([float(v) for v in target[:60]], 6,
                           related_series=related, params={"input_size": 8})
        assert np.allclose(
            payload["forecast"], 3.0 + 0.1 * np.arange(6.0)
        )
        assert np.allclose(payload["lower"], np.full(6, 1.0))
        assert np.allclose(payload["upper"], np.full(6, 5.0))

    def test_f07_rows_sorted_by_ds(self, harness, my_panel):
        # строки целевого ряда перемешаны по ds -- сортировка обязательна:
        # payload строго возрастает (медиана растёт по ds)
        harness.set_preds(_panel_preds(0.05, 8, shuffle=True))
        target, related = my_panel
        payload = _run_fit([float(v) for v in target[:60]], 8,
                           related_series=related, params={"input_size": 8})
        point = np.asarray(payload["forecast"], dtype=float)
        assert (np.diff(point) > 0).all()

    def test_f08_quantile_crossing_honest_failure(self, harness, my_panel):
        # heads MQLoss независимы: пересечение -- живой clamp-гейт честно
        # отказывает fold'а, без clamp-подмен
        harness.set_preds(_panel_preds(0.05, 6, lo=5.0, med=3.0, hi=1.0))
        target, related = my_panel
        with pytest.raises(NeuralContractError, match="инвариант"):
            _run_fit([float(v) for v in target[:60]], 6,
                     related_series=related, params={"input_size": 8})

    def test_f09_equality_boundary_admitted(self, harness, my_panel):
        # clamp-гейт -- НЕСТРОГИЙ: lower == median на границе допустим
        preds = _panel_preds(0.05, 6)
        mask = (preds["unique_id"] == "series_0") & (preds["ds"] == 3.0)
        preds.loc[mask, "DeepAR-median"] = 1.0
        harness.set_preds(preds)
        target, related = my_panel
        payload = _run_fit([float(v) for v in target[:60]], 6,
                           related_series=related, params={"input_size": 8})
        assert float(payload["lower"][3]) == float(payload["forecast"][3])

    def test_f10_capacity_error_passthrough(self, harness, my_panel):
        harness.raise_on_call = NeuralRuntimeCapacityError("память")
        harness.set_preds(_panel_preds(0.05, 6))
        target, related = my_panel
        with pytest.raises(NeuralRuntimeCapacityError):
            _run_fit([float(v) for v in target[:60]], 6,
                     related_series=related, params={"input_size": 8})

    def test_f11_contract_error_wrapped(self, harness, my_panel):
        harness.raise_on_call = NeuralContractError("дс-ось сломана")
        harness.set_preds(_panel_preds(0.05, 6))
        target, related = my_panel
        with pytest.raises(ValueError, match="DeepAR: дс-ось сломана"):
            _run_fit([float(v) for v in target[:60]], 6,
                     related_series=related, params={"input_size": 8})

    def test_f12_to_long_format_wrap(self, harness, my_panel, monkeypatch):
        # контрактные отказы to_long_format (дубликаты (unique_id, ds) и
        # пр.) оборачиваются в ValueError С ПРЕФИКСОМ адаптера
        import apps.api.neural_contract as contract_mod

        def _broken(*args, **kwargs):
            raise NeuralContractError("дубликаты (unique_id, ds)")

        monkeypatch.setattr(contract_mod, "to_long_format", _broken)
        target, related = my_panel
        with pytest.raises(ValueError, match="DeepAR: дубликаты"):
            _run_fit([float(v) for v in target[:60]], 6,
                     related_series=related, params={"input_size": 8})

    def test_f13_resolve_probabilistic_loss_called(self, harness, my_panel):
        # контрактный гейт Task 137 обязан вызываться с планом уровней
        harness.set_preds(_panel_preds(0.05, 6))
        target, related = my_panel
        _run_fit([float(v) for v in target[:60]], 6, related_series=related,
                 params={"input_size": 8})
        assert len(harness.loss_spy) == 1
        assert harness.loss_spy[0]["loss"] == "distribution"
        assert harness.loss_spy[0]["levels"] == (2.5, 50.0, 97.5)


# ---------------------------------------------------------------------------
# G. Provenance-метаданные и квантильный план
# ---------------------------------------------------------------------------


class TestGProvenance:
    def test_g01_plan_is_tft_identity_all_alphas(self):
        # единый источник истины probabilistic-плана (конвенция Task 141):
        # deepar._quantile_plan -- ТОТ ЖЕ объект, что у tft (НЕ дубликат)
        assert deepar_mod._quantile_plan is tft_mod._quantile_plan
        for alpha, q_lo, q_hi, levels in [
            (0.01, 0.005, 0.995, (0.5, 50.0, 99.5)),
            (0.05, 0.025, 0.975, (2.5, 50.0, 97.5)),
            (0.10, 0.05, 0.95, (5.0, 50.0, 95.0)),
        ]:
            plan = _quantile_plan(alpha)
            assert plan["method"] == "neural_quantile_outputs"
            assert plan["loss"] == "mqloss"
            assert plan["quantiles"] == (q_lo, 0.5, q_hi)
            assert plan["width"] == interval_width_for_alpha(alpha)
            assert plan["levels"] == tuple(
                float(level) for level in levels
            )
            contract = interval_levels_for_alpha(alpha)
            assert plan["levels"] == tuple(
                float(level) for level in contract.levels
            )

    def test_g02_payload_metadata_provenance(self, harness, my_panel):
        harness.set_preds(_panel_preds(0.05, 6))
        target, related = my_panel
        payload = _run_fit([float(v) for v in target[:60]], 6,
                           related_series=related, params={"input_size": 8},
                           random_state=9)
        assert payload["adapter_id"] == "neuralforecast-deepar"
        assert payload["deterministic"] is True
        assert payload["random_state"] == 9
        assert payload["intervals"] == {
            "method": "neural_quantile_outputs",
            "loss": "distribution",
            "distribution": "StudentT",
            "trajectory_samples": DEEPAR_TRAJECTORY_SAMPLES,
            "alpha": 0.05,
            "quantiles": [0.025, 0.5, 0.975],
            "levels": [2.5, 50.0, 97.5],
        }
        assert payload["params"] == {
            "lstm_hidden_size": 32, "input_size": 8, "alpha": 0.05,
        }
        assert payload["nobs"] == 60
        assert payload["n_series"] == 5

# ---------------------------------------------------------------------------
# H. Executor / quintet-когорта / cohort-контракт / EDA / panel-движок /
#    легаси-эндпоинт
# ---------------------------------------------------------------------------


class TestHCohortAndExecutor:
    def test_h01_quintet_cohort_panel_is_the_honest_difference(self):
        # quartet lstm/nbeats/nhits/tft -- univariate; deepar -- panel
        quintet = ("lstm", "nbeats", "nhits", "tft", "deepar")
        definitions = {mid: MODEL_EXECUTION_REGISTRY.require(mid)
                       for mid in quintet}
        for mid in ("lstm", "nbeats", "nhits", "tft"):
            definition = definitions[mid]
            assert definition.objective == "level_forecast"
            assert definition.input_kind == "univariate"
            assert definition.requires_related_series is False
        deepar = definitions["deepar"]
        assert deepar.objective == "level_forecast"
        assert deepar.input_kind == "panel"
        assert deepar.requires_related_series is True
        for mid in ("lstm", "nbeats", "nhits", "tft"):
            assert definitions[mid].engine == deepar.engine
            assert definitions[mid].dependency_group == deepar.dependency_group
            assert definitions[mid].actions == deepar.actions
            assert definitions[mid].required_packages == (
                deepar.required_packages
            )

    def test_h02_executor_payload_mapping_panel(self, harness, my_panel):
        harness.set_preds(_panel_preds(0.05, 5))
        target, related = my_panel
        result = MODEL_EXECUTION_REGISTRY.execute(
            "deepar",
            ModelExecutionRequest(
                target=[float(v) for v in target[:60]], horizon=5,
                seasonal_period=1, params={"input_size": 8},
                random_state=142,
                related_series={name: [float(v) for v in values[:60]]
                                for name, values in related.items()},
            ),
        )
        assert len(result.forecast) == 5
        assert result.metadata["adapter_id"] == "neuralforecast-deepar"
        assert result.metadata["max_steps"] == DEEPAR_MAX_STEPS
        assert result.metadata["seed"] == 142
        assert result.metadata["deterministic"] is True
        assert result.metadata["intervals"]["method"] == (
            "neural_quantile_outputs"
        )
        assert result.metadata["intervals"]["loss"] == "distribution"
        assert result.metadata["intervals"]["distribution"] == "StudentT"
        assert result.metadata["n_series"] == 5
        assert result.metadata["panel_ids"] == [
            f"series_{index}" for index in range(5)
        ]

    def test_h03_feature_channels_actual_contract_semantics(
        self, my_panel, monkeypatch,
    ):
        # ФАКТИЧЕСКАЯ семантика реестрового гейта (прикалывается оракулом):
        # future_features для panel-модели (supports_future_features=False)
        # -- честный отказ ModelExecutionContractError; train_features на
        # уровне РЕЕСТРА НЕ отвергаются (гейт покрывает только
        # univariate -- наследие до-142 гейта, находка F2 аудита:
        # docstring адаптера обещает "честный отказ гейта реестра" для
        # train_features -- НЕ соответствует факту; потребление
        # отсутствует, honest-warning даёт panel-движок через FeaturePlan)
        target, related = my_panel
        with pytest.raises(ModelExecutionContractError):
            MODEL_EXECUTION_REGISTRY.execute(
                "deepar",
                ModelExecutionRequest(
                    target=[float(v) for v in target[:60]], horizon=5,
                    related_series={name: [float(v) for v in values[:60]]
                                    for name, values in related.items()},
                    future_features={"x1": [1.0] * 5},
                ),
            )
        # train_features проходят реестровый гейт ДЛЯ panel (без фита:
        # адаптер подменён), никак не потребляются -- честный warning
        # даёт panel-движок (FeaturePlan)
        def _fake_fit(*args, **kwargs):
            return {
                "adapter_id": DEEPAR_ADAPTER_ID,
                "forecast": [1.0, 2.0, 3.0, 4.0, 5.0],
                "lower": [0.0] * 5, "upper": [2.0, 3.0, 4.0, 5.0, 6.0],
                "params": {"lstm_hidden_size": 32, "input_size": 24,
                           "alpha": 0.05},
                "nobs": 60, "n_series": 5,
                "panel_ids": [f"series_{i}" for i in range(5)],
                "max_steps": 300, "seed": 142,
                "freq": {"kind": "integer", "value": 1},
                "intervals": {"method": "neural_quantile_outputs",
                              "loss": "distribution",
                              "distribution": "StudentT",
                              "alpha": 0.05,
                              "quantiles": [0.025, 0.5, 0.975],
                              "levels": [2.5, 50.0, 97.5]},
                "random_state": 142, "deterministic": True,
            }

        monkeypatch.setattr(deepar_mod, "_deepar_fit_predict", _fake_fit)
        passed = MODEL_EXECUTION_REGISTRY.execute(
            "deepar",
            ModelExecutionRequest(
                target=[float(v) for v in target[:60]], horizon=5,
                related_series={name: [float(v) for v in values[:60]]
                                for name, values in related.items()},
                train_features={"x1": [1.0] * 60},
            ),
        )
        assert len(passed.forecast) == 5
        assert passed.metadata["n_series"] == 5

    def test_h04_legacy_endpoint_honest_refusal(self, my_panel):
        # одиночный synthetic-эндпоинт для panel-постановки НЕ применим:
        # честный отказ (прецедент var/vecm), НЕ синтетическая панель
        target, _ = my_panel
        with pytest.raises(ValueError, match="панель") as excinfo:
            run_deepar_backtest([float(v) for v in target], 0.75, 12)
        assert "не менее 5 рядов" in str(excinfo.value)

    def test_h05_eda_shape_criterion_panel(self):
        from apps.api.eda_model_matrix import _shape_criterion

        model = type("M", (), {"id": "deepar", "min_series": 5})()
        family = type("F", (), {"id": "neural"})()
        task = type("T", (), {})()
        enough = _shape_criterion(model, family, task, 5)
        assert enough["status"] == "pass"
        assert enough["blocking"] is False
        plenty = _shape_criterion(model, family, task, 9)
        assert plenty["status"] == "pass"
        short = _shape_criterion(model, family, task, 4)
        assert short["status"] == "fail"
        assert short["blocking"] is True
        assert "панель" in short["conclusion"]
        # не-deepar ветка не тронута (одномерные -- not_required)
        tft_like = type("M", (), {"id": "tft", "min_series": None})()
        univariate = _shape_criterion(tft_like, family, task, 1)
        assert univariate["status"] == "not_required"
        # fallback при min_series=None (yaml-ось потеряна): честный пол 5
        no_min = type("M", (), {"id": "deepar", "min_series": None})()
        assert _shape_criterion(no_min, family, task, 4)["status"] == "fail"
        assert _shape_criterion(no_min, family, task, 5)["status"] == "pass"

    def test_h06_cohort_contract_panel_gates(self):
        from apps.api.neural_contract import (
            NeuralTrainingConfig,
            build_exogenous_plan,
            interval_levels_for_alpha,
            neural_cohort_contract,
        )

        base = dict(
            fingerprint="cert142",
            exogenous=build_exogenous_plan(pd.DataFrame(
                {"unique_id": [], "ds": [], "y": []})),
            interval=interval_levels_for_alpha(0.05),
            loss="distribution",
            config=NeuralTrainingConfig(seed=0, max_steps=1),
        )
        # n_series < min_series -- отказ на слое контракта (дубль гейта)
        with pytest.raises(NeuralContractError, match="панель"):
            neural_cohort_contract(n_series=4, min_series=5, **base)
        contract = neural_cohort_contract(n_series=5, min_series=5, **base)
        assert contract["panel"] is True
        assert contract["n_series"] == 5
        assert contract["min_series"] == 5
        # перекрёстная сверка: объявленный univariate против данных panel
        with pytest.raises(NeuralContractError, match="input_kind"):
            neural_cohort_contract(
                n_series=5, min_series=5, input_kind="univariate", **base
            )

    def test_h07_backtest_response_panel_field(self):
        from apps.api.schemas import BacktestResponse

        assert "panel" in BacktestResponse.model_fields
        assert BacktestResponse.model_fields["panel"].default is None


class _StubRegistry:
    """Stub реестра для fast-оракулов panel-движка (БЕЗ реального фита):
    describe -- честный словарь контракта; execute -- детерминированный
    синтетический отклик с записью запроса (leakage-детектив related)."""

    def __init__(self, nobs_total: int):
        self.requests: list[ModelExecutionRequest] = []
        self.nobs_total = nobs_total

    def describe(self, model_id):
        # модель-зависимый контракт: panel -- только deepar (мутант,
        # ослабивший input_kind-гейт движка, умрёт на tft-запросе)
        return {"model_id": model_id, "objective": "level_forecast",
                "input_kind": "panel" if model_id == "deepar"
                else "univariate"}

    def execute(self, model_id, request):
        self.requests.append(request)
        n = int(request.horizon)
        step = np.arange(n, dtype=float)
        return ModelExecutionResult(
            forecast=[100.0 + 0.5 * value for value in step],
            lower_interval=[90.0 + 0.5 * value for value in step],
            upper_interval=[110.0 + 0.5 * value for value in step],
            metadata={"n_series": 5, "adapter_id": "neuralforecast-deepar"},
        )


def _stub_panel_plan(monkeypatch, my_panel, *, nobs=100, n_train=90,
                     horizon=10):
    """Быстрый panel-движок: настоящий build_backtest_plan/система на
    МОИХ данных + подмена реестра (без фита)."""
    import apps.api.backtesting as backtesting_mod
    from apps.api.backtesting import build_backtest_plan
    from apps.api.multivariate_contract import build_endogenous_system
    from apps.api.neural_contract import (
        NeuralTrainingConfig,
        build_exogenous_plan,
        interval_levels_for_alpha,
        neural_cohort_contract,
    )

    target, related = my_panel
    system = build_endogenous_system(
        {"value": [float(v) for v in target[:nobs]],
         **{name: [float(v) for v in values[:nobs]]
            for name, values in related.items()}},
        timestamps=[value.isoformat() for value in pd.date_range(
            "2023-01-01", periods=nobs, freq="D")],
    )
    validation = {
        "strategy": "expanding", "horizon": horizon, "n_splits": 1, "gap": 0,
        "folds": [{"fold": 1, "train_start": 0, "train_end": n_train - 1,
                   "gap_size": 0, "test_start": n_train,
                   "test_end": n_train + horizon - 1}],
    }
    cohort = neural_cohort_contract(
        fingerprint="cert142-engine",
        n_series=5, min_series=DEEPAR_MIN_SERIES,
        exogenous=build_exogenous_plan(pd.DataFrame(
            {"unique_id": [], "ds": [], "y": []})),
        interval=interval_levels_for_alpha(0.05),
        loss="distribution",
        config=NeuralTrainingConfig(seed=142, max_steps=1),
    )
    plan = build_backtest_plan(
        validation, n_observations=nobs, fingerprint="cert142-engine",
        target_column="value", seasonal_period=14,
        series_fingerprints={"value": "cert142-engine", **{
            name: f"fp-{name}" for name in related}},
        cohort_contract_override=cohort,
    )
    stub = _StubRegistry(nobs_total=nobs)
    monkeypatch.setattr(backtesting_mod, "MODEL_EXECUTION_REGISTRY", stub)
    return system, plan, stub


class TestHPanelEngine:
    def test_h08_panel_engine_happy_path_fast(self, monkeypatch, my_panel):
        system, plan, stub = _stub_panel_plan(monkeypatch, my_panel)
        from apps.api.backtesting import run_panel_backtest_plan

        result = run_panel_backtest_plan(
            model_id="deepar", model_name="DeepAR", family_id="neural",
            system=system, plan=plan, seasonal_period=14,
        )
        assert result["status"] == "success"
        assert len(result["oof_predictions"]) == 10
        assert result["metrics"]["mae"] is not None
        assert result["objective"] == "level_forecast"
        assert result["cohort_contract"]["panel"] is True
        assert result["cohort_contract"]["n_series"] == 5
        assert result["panel"]["series_names"][0] == "value"
        assert result["panel"]["n_series"] == 5
        assert result["panel"]["target_series"] == "value"
        assert result["execution_contract"]["input_kind"] == "panel"
        # детерминированный синтетический отклик дошёл до метрик:
        # прогнозы OOF == 100 + 0.5*step (запись факта живого провода)
        oof_predicted = [point["predicted"] for point in
                         result["oof_predictions"]]
        assert oof_predicted[0] == 100.0
        assert result["warnings"] == [] or all(
            "FeaturePlan" not in warning for warning in result["warnings"]
        )

    def test_h09_engine_gates_objective_input_kind_single_series(
        self, monkeypatch, my_panel,
    ):
        from apps.api.backtesting import run_panel_backtest_plan

        system, plan, stub = _stub_panel_plan(monkeypatch, my_panel)
        with pytest.raises(Exception, match="panel"):
            run_panel_backtest_plan(
                model_id="tft", model_name="TFT", family_id="neural",
                system=system, plan=plan, seasonal_period=14,
            )
        # одиночная система -- панелью НЕ является (честность Task 142).
        # EndogenousSystem сам отказывает <2 рядов (__post_init__), поэтому
        # гейт движка недостижим через честные объекты (defense-in-depth);
        # для мутационной убиваемости подаётся engine-дабл (SimpleNamespace
        # с атрибутами, которые читает движок) -- fault-injection стиль
        from types import SimpleNamespace as _NS

        target, _ = my_panel
        single = _NS(
            names=("value",),
            series={"value": tuple(float(v) for v in target[:100])},
            n_observations=100,
            timestamps=tuple(value.isoformat() for value in pd.date_range(
                "2023-01-01", periods=100, freq="D")),
        )
        with pytest.raises(Exception, match="несколько рядов"):
            run_panel_backtest_plan(
                model_id="deepar", model_name="DeepAR", family_id="neural",
                system=single, plan=plan, seasonal_period=14,
            )

    def test_h10_engine_fold_integrity_gates(self, monkeypatch, my_panel):
        # непрерывный префикс train + тест не пересекает train -- живые
        # гейты движка (leakage-safe, как vector-движок)
        from apps.api.backtesting import run_panel_backtest_plan

        system, plan, stub = _stub_panel_plan(monkeypatch, my_panel)
        import copy as _copy
        from dataclasses import replace as _dc_replace

        broken_plan = _copy.deepcopy(plan)
        broken_fold = _dc_replace(
            broken_plan.folds[0], train_indices=[0, 1, 3, 4],
        )
        broken_plan.folds[0] = broken_fold
        with pytest.raises(Exception, match="непрерывным префиксом"):
            run_panel_backtest_plan(
                model_id="deepar", model_name="DeepAR", family_id="neural",
                system=system, plan=broken_plan, seasonal_period=14,
            )
        overlap_plan = _copy.deepcopy(plan)
        overlap_fold = _dc_replace(
            overlap_plan.folds[0],
            test_indices=[overlap_plan.folds[0].train_indices[-1],
                          *overlap_plan.folds[0].test_indices[1:]],
        )
        overlap_plan.folds[0] = overlap_fold
        with pytest.raises(Exception, match="пересекать"):
            run_panel_backtest_plan(
                model_id="deepar", model_name="DeepAR", family_id="neural",
                system=system, plan=overlap_plan, seasonal_period=14,
            )

    def test_h11_engine_related_prefixes_leakage_safe(
        self, monkeypatch, my_panel,
    ):
        # related-ряды приходят адаптеру ТОЛЬКО train-префиксами
        # (семантика VAR); full-series утечка -- мутант умрёт здесь
        system, plan, stub = _stub_panel_plan(
            monkeypatch, my_panel, nobs=100, n_train=90, horizon=10,
        )
        from apps.api.backtesting import run_panel_backtest_plan

        run_panel_backtest_plan(
            model_id="deepar", model_name="DeepAR", family_id="neural",
            system=system, plan=plan, seasonal_period=14,
        )
        assert len(stub.requests) == 1
        request = stub.requests[0]
        assert len(request.target) == 90
        assert request.horizon == 10
        for name, values in request.related_series.items():
            assert len(values) == 90, (
                f"related '{name}' утёк за train-префикс: {len(values)}"
            )
        assert set(request.related_series) == {
            "flow", "pressure", "load", "price"
        }

    def test_h12_session_panel_context_gate(self, my_panel):
        # контекст роутера: honest_system_profile на МОИХ данных, гейт
        # n_series (третий слой честности панели), cohort-override panel
        import apps.api.routers.modeling_session as session_mod
        from types import SimpleNamespace

        target, related = my_panel
        nobs = 100
        frame = pd.DataFrame({
            "date": pd.date_range("2023-01-01", periods=nobs, freq="D"),
            "value": [float(v) for v in target[:nobs]],
            **{name: [float(v) for v in values[:nobs]]
               for name, values in related.items()},
        })
        prepared = SimpleNamespace(
            series=[float(v) for v in target[:nobs]],
            labels=[stamp.isoformat() for stamp in frame["date"]],
            preprocessing_signature="none",
        )
        context = {"fingerprint": "cert142-session"}
        validation_strategy = {
            "strategy": "expanding", "horizon": 3, "n_splits": 2, "gap": 0,
            "folds": [
                {"fold": 1, "train_start": 0, "train_end": 93,
                 "gap_size": 0, "test_start": 94, "test_end": 96},
                {"fold": 2, "train_start": 0, "train_end": 96,
                 "gap_size": 0, "test_start": 97, "test_end": 99},
            ],
        }
        session = SimpleNamespace(
            dataframe=frame, date_column="date", target_column="value",
            modeling_artifacts={"validation_strategy": validation_strategy},
        )
        kwargs = dict(
            period=14, plan_obj=None, feature_plan_columns={},
            model_id="deepar",
        )
        system, plan, warnings = session_mod._panel_neural_context(
            session, prepared, context, **kwargs,
        )
        assert list(system.names) == [
            "value", *related.keys()
        ]
        assert plan.cohort_contract["panel"] is True
        assert plan.cohort_contract["n_series"] == 5
        # исправление F3: cohort-контракт декларирует ФАКТИЧЕСКУЮ
        # поверхность среза (distribution-голова), а не mqloss
        assert plan.cohort_contract["loss"] == "distribution"
        assert warnings == []
        # 4 ряда (один related удалён из датафрейма) -- честный отказ
        short_frame = frame.drop(columns=["price"])
        short_session = SimpleNamespace(
            dataframe=short_frame, date_column="date",
            target_column="value",
        )
        with pytest.raises(Exception, match="min_series=5"):
            session_mod._panel_neural_context(
                short_session, prepared, context, **kwargs,
            )

    @real_fit
    @pytest.mark.skipif(
        not REAL_MODE, reason="реальный panel-движок -- CISSTAT_CERT142_REAL=1"
    )
    def test_h13_panel_engine_real_run_own_data(self, my_panel):
        # РЕАЛЬНЫЙ panel-движок на моих данных (глобальный OOF cohort,
        # 2 folds, слабый бюджет через сертифицированный env-рычаг)
        from apps.api.backtesting import build_backtest_plan
        from apps.api.backtesting import run_panel_backtest_plan
        from apps.api.multivariate_contract import build_endogenous_system
        from apps.api.neural_contract import (
            NeuralTrainingConfig,
            build_exogenous_plan,
            interval_levels_for_alpha,
            neural_cohort_contract,
        )

        target, related = my_panel
        nobs = PANEL_N
        system = build_endogenous_system(
            {"value": [float(v) for v in target],
             **{name: [float(v) for v in values]
                for name, values in related.items()}},
            timestamps=[value.isoformat() for value in pd.date_range(
                "2023-01-01", periods=nobs, freq="D")],
        )
        validation = {
            "strategy": "expanding", "horizon": 3, "n_splits": 2, "gap": 0,
            "folds": [
                {"fold": 1, "train_start": 0, "train_end": nobs - 7,
                 "gap_size": 0, "test_start": nobs - 6, "test_end": nobs - 4},
                {"fold": 2, "train_start": 0, "train_end": nobs - 4,
                 "gap_size": 0, "test_start": nobs - 3, "test_end": nobs - 1},
            ],
        }
        cohort = neural_cohort_contract(
            fingerprint="cert142-real-engine",
            n_series=5, min_series=DEEPAR_MIN_SERIES,
            exogenous=build_exogenous_plan(pd.DataFrame(
                {"unique_id": [], "ds": [], "y": []})),
            interval=interval_levels_for_alpha(0.05),
            loss="distribution",
            config=NeuralTrainingConfig(seed=142, max_steps=50),
        )
        plan = build_backtest_plan(
            validation, n_observations=nobs,
            fingerprint="cert142-real-engine", target_column="value",
            seasonal_period=14,
            series_fingerprints={"value": "cert142-real-engine", **{
                name: f"fp-{name}" for name in related}},
            cohort_contract_override=cohort,
        )
        previous = os.environ.get("CISSTAT_NEURAL_MAX_STEPS")
        os.environ["CISSTAT_NEURAL_MAX_STEPS"] = "50"
        try:
            result = run_panel_backtest_plan(
                model_id="deepar", model_name="DeepAR", family_id="neural",
                system=system, plan=plan, seasonal_period=14,
            )
        finally:
            if previous is None:
                os.environ.pop("CISSTAT_NEURAL_MAX_STEPS", None)
            else:
                os.environ["CISSTAT_NEURAL_MAX_STEPS"] = previous
        assert result["status"] == "success"
        assert len(result["oof_predictions"]) == 6
        metrics = result["metrics"]
        assert metrics["mae"] is not None and metrics["mae"] >= 0
        assert metrics["rmse"] >= metrics["mae"]
        assert result["cohort_contract"]["panel"] is True
        assert result["panel"]["target_series"] == "value"
        assert result["panel"]["n_series"] == 5


# ---------------------------------------------------------------------------
# E. Реальные end-to-end фиты на МОИХ данных
# ---------------------------------------------------------------------------


@real_fit
@pytest.mark.skipif(
    not REAL_MODE, reason="реальные фиты -- CISSTAT_CERT142_REAL=1"
)
class TestERealRuntime:
    def test_e01_real_panel_run_shape_provenance_honest_width(
        self, my_panel,
    ):
        payload = _real_panel_fit(my_panel, alpha=0.05, seed=142)
        horizon = PANEL_HORIZON
        assert len(payload["forecast"]) == horizon
        assert len(payload["lower"]) == horizon
        assert len(payload["upper"]) == horizon
        point = np.asarray(payload["forecast"], dtype=float)
        lower = np.asarray(payload["lower"], dtype=float)
        upper = np.asarray(payload["upper"], dtype=float)
        # clamp-инвариант на живом прогоне
        assert (lower <= point).all() and (point <= upper).all()
        # ЧЕСТНАЯ ШИРИНА (width-семантика НАХОДКИ Task 141 п.2): границы
        # -- 2.5/97.5 процентили, НЕ схлопнуты к медиане
        scale = _scale(my_panel)
        assert (lower < point).all() and (point < upper).all()
        assert (point - lower).mean() >= 0.01 * scale
        assert (upper - point).mean() >= 0.01 * scale
        assert payload["intervals"]["method"] == "neural_quantile_outputs"
        assert payload["intervals"]["loss"] == "distribution"
        assert payload["intervals"]["distribution"] == "StudentT"
        assert payload["intervals"]["quantiles"] == [0.025, 0.5, 0.975]
        assert payload["max_steps"] == 50
        assert payload["seed"] == 142
        assert payload["deterministic"] is True
        assert payload["n_series"] == 5
        assert payload["panel_ids"] == [f"series_{i}" for i in range(5)]
        assert payload["freq"]["kind"] == "integer"

    def test_e02_real_interval_width_monotonic_in_alpha(self, my_panel):
        widths = {}
        for alpha in (0.01, 0.05, 0.10):
            payload = _real_panel_fit(my_panel, alpha=alpha, seed=142)
            lower = np.asarray(payload["lower"], dtype=float)
            upper = np.asarray(payload["upper"], dtype=float)
            widths[alpha] = float((upper - lower).mean())
        assert widths[0.01] > widths[0.05] > widths[0.10]

    def test_e05_real_point_scale_tracks_data_level(self, my_panel):
        """НОВЫЙ оракул (закрывает механизм M2 находки F3): медиана живого
        прогона отслеживает уровень данных, интервал ПОКРЫВАЕТ уровень.
        На статус-кво коллеги (identity-скейлер) медиана ~4.3 при уровне
        ~105 -- интервал лгал и по точке; robust-скейлер возвращает
        масштаб (проб E1/E4: |медиана-хвост| ~4 против ~100)."""
        payload = _real_panel_fit(my_panel, alpha=0.05, seed=142)
        point = np.asarray(payload["forecast"], dtype=float)
        lower = np.asarray(payload["lower"], dtype=float)
        upper = np.asarray(payload["upper"], dtype=float)
        target, _ = my_panel
        tail = float(np.mean(np.asarray(target, dtype=float)[-24:]))
        # уровень данных отслеживается точкой (не коллапс к нулю/масштабу
        # нормализации) и накрывается интервалом (поверхность не лжёт)
        assert abs(float(np.mean(point)) - tail) <= 20.0
        assert float(np.mean(lower)) < tail < float(np.mean(upper))

    def test_e03_real_determinism_same_seed_cross_seed(self, my_panel):
        first = _real_panel_fit(my_panel, alpha=0.05, seed=142, fresh=True)
        second = _real_panel_fit(my_panel, alpha=0.05, seed=142, fresh=True)
        for key in ("forecast", "lower", "upper"):
            assert np.array_equal(
                np.asarray(first[key], dtype=float),
                np.asarray(second[key], dtype=float),
            ), key
        other = _real_panel_fit(my_panel, alpha=0.05, seed=143, fresh=True)
        assert not np.allclose(
            np.asarray(first["forecast"], dtype=float),
            np.asarray(other["forecast"], dtype=float),
        )

    def test_e04_real_min_series_gate_before_fit(self, my_panel):
        # на живом runtime: n_series=4 -- отказ ДО затрат на фит
        target, related = my_panel
        with pytest.raises(ValueError, match="min_series=5"):
            _run_fit(
                [float(v) for v in target], 12,
                related_series=dict(list(related.items())[:3]),
                params={"input_size": 24},
            )

