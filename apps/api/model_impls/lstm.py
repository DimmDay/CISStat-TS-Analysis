# apps/api/model_impls/lstm.py
"""
LSTM/GRU -- рекуррентная нейро-модель на едином NeuralForecast-runtime
(Task 138, family=neural).  Первый исполнитель neural-runtime контракта
Task 137 (прецедент пары var/vecm в векторном движке и пары garch/egarch
в volatility-движке: runtime-контракт Task 137 НЕ меняется -- новый
адаптер + запись реестра v2 + условный dispatch + yaml).

Постановка docs/modeling_task_list.md::Tasks 138-142 (Task 138 --
LSTM/GRU) + требования Task 137:

1. **Единый каталожный id ``lstm`` «LSTM / GRU» -- честная альтернатива
   ячеек**: cell_type ∈ {LSTM, GRU} -- bounded-параметр адаптера (и
   yaml::lstm param_space), а не два скрытых каркаса; LSTM -- долгие
   зависимости, GRU -- легковесная альтернатива (ровно как заявлено в
   каталоге).  Дефолт -- LSTM.

2. **ЕДИНСТВЕННАЯ точка импорта torch/neuralforecast** --
   apps/api/model_impls/neural_runtime.py (лениво, fail-closed,
   NeuralRuntimeUnavailableError с установочной подсказкой).  Этот
   модуль torch НЕ импортирует ни на одном уровне.

3. **ds-ось -- задекларированная конвенция**: парсимые метки времени
   (train_timestamps реестра) -> datetime-сетка + честный pd.infer_freq;
   что-либо иное (нераспознаваемые/отсутствующие метки) -- ПОЗИЦИОННАЯ
   целочисленная сетка (freq=1, нативно поддержана NeuralForecast 3.2.2,
   проб scripts/task138_neural_lstm_probe.py).  ds -- только ось:
   значения прогноза рекуррентной модели от меток не зависят; НИКАКОГО
   скрытого ресемплинга/интерполяции/сортировки данных.

4. **Интервалы -- официальный conformal-контур контракта Task 137**:
   fit(prediction_intervals=PredictionIntervals()) + predict(level=[...])
   -> колонки <Model>-lo-<level>/<Model>-hi-<level>; уровни -- из
   сертифицированного interval_levels_for_alpha (двусторонняя alpha,
   включая медиану).  Никаких «MC Dropout / deep ensembles», которых в
   коде нет (каталог обновлён комментарием Task 138).

5. **Fail-closed**: короткий train (< LSTM_MIN_TRAIN), NaN/Inf, ячейка
   вне whitelist, параметры вне bounded-границ, пустой/нефинитный
   прогноз -- отказ fold'а БЕЗ Naive-fallback и clamp-подмен.

6. **Детерминизм**: random_state реестра -> NeuralTrainingConfig.seed ->
   fold_seed -> random_seed КОНСТРУКТОРА модели (блокирующая находка
   сертификации Task 137: BaseModel 3.2.2 перезасеивает весь раном в
   __init__, поэтому сид обязан дойти до конструктора).  Same-seed --
   бит-паритет, другой seed -- другой прогноз (дифференциальные тесты).

7. **Бюджет -- константа модуля** LSTM_MAX_STEPS (единый бюджетный
   рычаг контракта max_steps; max_epochs deprecated в NeuralForecast
   3.x).  Тюнинг бюджета -- вне param_space обоснованно (прецедент
   Task 136: константы движка не тюнятся); константа прижата
   анти-тампер тестом к [100, NEURAL_MAX_STEPS_BOUND].

Exogenous-канал в реестре НЕ декларирован (supports_future_features=
False): контракту Task 137 futr-exog доступен, но для одномерного
input_kind="univariate" гейты реестра v2 отвергают feature-каналы
fail-closed; канал exog для нейро-моделей -- отдельная постановка
(прецедент GARCHX/VARX).
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from apps.api.model_impls._common import train_test_split
from apps.api.model_impls._metrics import compute_metrics
from apps.api.neural_contract import (
    NeuralContractError,
    NeuralRuntimeCapacityError,
    NeuralTrainingConfig,
    interval_levels_for_alpha,
)
from apps.api.model_impls.neural_runtime import train_and_forecast
from apps.api.schemas import BacktestMetrics

LSTM_ADAPTER_ID = "neuralforecast-lstm-gru"

#: Минимальная длина train-среза fold'а (честный минимум рекуррентного
#: фита; мягкий порог применимости каталога min_observations=200
#: применяется readiness-гейтом РАНЬШЕ -- как у garch: gate 100 / адаптер 20).
LSTM_MIN_TRAIN = 30

#: Единый бюджет обучения fold'а (max_steps NeuralForecast 3.x); прижат
#: анти-тампер тестом к [100, NEURAL_MAX_STEPS_BOUND].
LSTM_MAX_STEPS = 300

#: Env-рычаг бюджета слабых инстансов (Task 138c): прокси-таймаут Render
#: ~100 c -- на quota-CPU (free ~0.1 CPU) полный бюджет 300 шагов не
#: укладывается даже при достаточной памяти.  Дефолт (env не задана) --
#: СЕРТИФИЦИРОВАННАЯ константа LSTM_MAX_STEPS (семантика Task 138 не
#: меняется); мусор/меньше 1 -- fail-closed; верхняя граница [1,
#: NEURAL_MAX_STEPS_BOUND] дотягивается валидацией NeuralTrainingConfig.


def _resolve_max_steps() -> int:
    """Бюджет обучения fold'а: CISSTAT_NEURAL_MAX_STEPS или константа 300.

    Пустая env (дефолт) -- сертифицированная семантика Task 138;
    задана -- целое >= 1; мусор -- ValueError (fail-closed, стиль
    локальной валидации адаптера)."""
    raw = os.environ.get("CISSTAT_NEURAL_MAX_STEPS", "").strip()
    if not raw:
        return LSTM_MAX_STEPS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"LSTM/GRU: CISSTAT_NEURAL_MAX_STEPS={raw!r} не целое >= 1 "
            "(fail-closed)"
        ) from exc
    if value < 1:
        raise ValueError(
            f"LSTM/GRU: CISSTAT_NEURAL_MAX_STEPS={raw!r} не целое >= 1 "
            "(fail-closed)"
        )
    return value

#: Честная альтернатива ячеек единого каталожного id «LSTM / GRU».
CELL_OPTIONS = ("LSTM", "GRU")

#: Bounded-границы гиперпараметров (вне тюнинга тоже не могут быть
#: нарушены -- fail-closed).
HIDDEN_SIZE_BOUNDS = (8, 128)
ENCODER_LAYERS_BOUNDS = (1, 3)
INPUT_SIZE_BOUNDS = (8, 104)

#: Уровни интервалов -- конвенция платформы (как у VAR Task 132).
ALPHA_OPTIONS = (0.01, 0.05, 0.10)

DEFAULT_PARAMS: dict[str, Any] = {
    "cell_type": "LSTM",
    "hidden_size": 32,
    "encoder_n_layers": 1,
    "input_size": 24,
    "alpha": 0.05,
}

_PARAM_KEYS = ("cell_type", "hidden_size", "encoder_n_layers", "input_size", "alpha")


def validate_lstm_params(params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Нормализовать и провалидировать гиперпараметры LSTM/GRU (fail-closed).

    Неизвестные ключи игнорируются -- соглашение платформы (в params
    приходят чужие ключи, см. backtesting.py::run_backtest_plan).
    """
    merged = {
        **DEFAULT_PARAMS,
        **{k: v for k, v in dict(params or {}).items() if k in _PARAM_KEYS},
    }
    normalized: dict[str, Any] = {}

    cell_type = merged["cell_type"]
    if cell_type not in CELL_OPTIONS:
        raise ValueError(
            f"LSTM/GRU param 'cell_type'={cell_type!r} вне допустимого "
            f"набора {list(CELL_OPTIONS)}"
        )
    normalized["cell_type"] = str(cell_type)

    for key in ("hidden_size", "encoder_n_layers", "input_size"):
        value = merged[key]
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise ValueError(
                f"LSTM/GRU param '{key}': ожидался целочисленный аргумент, "
                f"получено {value!r}"
            )
        low, high = {
            "hidden_size": HIDDEN_SIZE_BOUNDS,
            "encoder_n_layers": ENCODER_LAYERS_BOUNDS,
            "input_size": INPUT_SIZE_BOUNDS,
        }[key]
        number = int(value)
        if not low <= number <= high:
            raise ValueError(
                f"LSTM/GRU param '{key}'={number} вне bounded диапазона "
                f"[{low}, {high}]"
            )
        normalized[key] = number

    alpha = merged["alpha"]
    try:
        alpha_value = float(alpha)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"LSTM/GRU param 'alpha'={alpha!r} не числовой") from exc
    if alpha_value not in ALPHA_OPTIONS:
        raise ValueError(
            f"LSTM/GRU param 'alpha'={alpha_value} вне допустимого набора "
            f"{sorted(ALPHA_OPTIONS)}"
        )
    normalized["alpha"] = alpha_value
    return normalized


def _validated_target(target: Sequence[float]) -> np.ndarray:
    vector = np.asarray([float(value) for value in target], dtype=float)
    if vector.size == 0:
        raise ValueError("LSTM/GRU: train fold пуст")
    if not np.isfinite(vector).all():
        raise ValueError(
            "LSTM/GRU: ряд содержит NaN/Inf -- импутация запрещена "
            "(fail-closed)"
        )
    return vector


def _resolve_time_axis(
    timestamps: Optional[Sequence[str]], nobs: int,
) -> tuple[pd.Series, str | int]:
    """Задекларированная конвенция ds-оси адаптера (см. докстринг п.3).

    Парсимые метки -- datetime-сетка + pd.infer_freq; иначе --
    позиционная целочисленная сетка (freq=1).  Возвращает (ds, freq).
    """
    if timestamps:
        labels = [str(value) for value in timestamps]
        if len(labels) == nobs:
            try:
                parsed = pd.to_datetime(pd.Series(labels), errors="coerce")
            except (TypeError, ValueError):
                parsed = pd.Series([pd.NaT] * nobs)
            if parsed.notna().all():
                freq = pd.infer_freq(parsed)
                if freq is not None:
                    return parsed, freq
    return (
        pd.Series(np.arange(nobs, dtype=np.int64)),
        1,
    )


def _lstm_fit_predict(
    target: Sequence[float],
    horizon: int,
    *,
    params: Optional[Mapping[str, Any]] = None,
    random_state: int = 42,
    timestamps: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Fit/forecast рекуррентной модели (LSTM или GRU) на train-срезе.

    Возвращает payload: ``forecast`` -- точечный прогноз (horizon,);
    ``lower``/``upper`` -- conformal-границы уровня ``alpha`` (официальный
    контур контракта Task 137); ``params``/``cell_type``/``freq``/
    ``intervals`` -- вход диагностики и metadata executor'а.
    random_state принят по контракту реестра: детерминизм -- сид доходит
    до КОНСТРУКТОРА модели (ресертификация Task 137); фолды платформы
    получают один random_state -- per-fold модели различаются данными,
    прогностический кадр детерминирован.
    """
    if int(horizon) < 1:
        raise ValueError(
            f"LSTM/GRU: horizon должен быть положительным, получено {horizon!r}"
        )
    normalized = validate_lstm_params(params)
    vector = _validated_target(target)
    nobs = vector.size
    if nobs < LSTM_MIN_TRAIN:
        raise ValueError(
            f"LSTM/GRU: история слишком короткая ({nobs} точек); минимум "
            f"{LSTM_MIN_TRAIN} (LSTM_MIN_TRAIN адаптера Task 138)"
        )

    ds, freq = _resolve_time_axis(timestamps, nobs)
    frame = pd.DataFrame({"y": vector}, index=pd.Index(ds, name="ds"))
    from apps.api.neural_contract import to_long_format

    try:
        long = to_long_format(frame, value_column="y")
    except NeuralContractError as exc:
        raise ValueError(f"LSTM/GRU: {exc}") from exc

    config = NeuralTrainingConfig(
        seed=int(random_state), max_steps=_resolve_max_steps(),
    )

    neuralforecast_models = _require_models()
    model_cls = getattr(neuralforecast_models, normalized["cell_type"])
    hidden = normalized["hidden_size"]

    def _factory(budget: Mapping[str, Any]):
        return model_cls(
            h=int(horizon),
            input_size=normalized["input_size"],
            encoder_n_layers=normalized["encoder_n_layers"],
            encoder_hidden_size=hidden,
            decoder_hidden_size=hidden,
            **dict(budget),
        )

    plan = interval_levels_for_alpha(normalized["alpha"])
    try:
        preds = train_and_forecast(
            model_factory=_factory,
            freq=freq,
            train_long=long,
            horizon=int(horizon),
            config=config,
            levels=plan.levels,
            fold_index=0,
        )
    except NeuralRuntimeCapacityError:
        # Task 138c: ресурсный отказ нейро-runtime проходит НАСКВОЗЬ без
        # ValueError-обёртки -- HTTP-слой обязан увидеть честный статус
        # (503 legacy-роутера / 422 session-движка), а не потерять его.
        raise
    except NeuralContractError as exc:
        raise ValueError(f"LSTM/GRU: {exc}") from exc

    model_name = normalized["cell_type"]
    if model_name not in preds.columns:
        raise ValueError(
            f"LSTM/GRU: NeuralForecast вернул колонки {list(preds.columns)} "
            f"без точечного прогноза '{model_name}' (fail-closed)"
        )
    point = preds[model_name].to_numpy(dtype=float)
    lower = _interval_column(preds, model_name, "lo", float(plan.levels[0]))
    upper = _interval_column(preds, model_name, "hi", float(plan.levels[-1]))

    if len(point) != int(horizon):
        raise ValueError(
            f"LSTM/GRU: длина прогноза {len(point)} не равна horizon={int(horizon)}"
        )
    if not (np.isfinite(point).all() and np.isfinite(lower).all()
            and np.isfinite(upper).all()):
        raise ValueError(
            "LSTM/GRU: прогноз содержит NaN/Inf -- отказ без clamp-подмен "
            "(fail-closed)"
        )

    return {
        "adapter_id": LSTM_ADAPTER_ID,
        "forecast": point,
        "lower": lower,
        "upper": upper,
        "params": dict(normalized),
        "cell_type": normalized["cell_type"],
        "nobs": int(nobs),
        "max_steps": int(config.max_steps),
        "seed": int(config.seed),
        "freq": (
            {"kind": "datetime", "value": str(freq)}
            if isinstance(freq, str) else {"kind": "integer", "value": 1}
        ),
        "intervals": {
            "method": "conformal",
            "alpha": normalized["alpha"],
            "levels": [float(level) for level in plan.levels],
        },
        "random_state": int(random_state),
        "deterministic": True,
    }


def _interval_column(
    preds: pd.DataFrame, model_name: str, side: str, level: float,
) -> np.ndarray:
    suffix = f"-{side}-{level}"
    matches = [column for column in preds.columns if str(column).endswith(suffix)]
    if not matches:
        raise ValueError(
            f"LSTM/GRU: conformal-колонка '{model_name}{suffix}' отсутствует "
            f"в отклике NeuralForecast (fail-closed)"
        )
    return preds[matches[0]].to_numpy(dtype=float)


def _require_models():
    """Ленивый импорт neuralforecast.models (единственная точка --
    neural_runtime.require_neuralforecast)."""
    from apps.api.model_impls.neural_runtime import require_neuralforecast

    return require_neuralforecast().models


def run_lstm_backtest(
    series: Sequence[float],
    train_ratio: float,
    seasonal_period: int,
):
    """Legacy synthetic-demo эндпоинт (POST /v1/models/backtest), сигнатура
    как у остальных model_impls; seasonal_period не используется (долгие
    зависимости рекуррентная модель извлекает из данных сама).  Task 138:
    LSTM/GRU -- одномерная level-модель, однорядный эндпоинт ПРИМЕНИМ
    (прецедент random_forest); сознательно БЕЗ safe_backtest/Naive-fallback
    -- ошибку модели нельзя подменять метриками наивного прогноза."""
    y_train, y_test = train_test_split(list(series), train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)
    payload = _lstm_fit_predict(y_train, len(y_test), random_state=42)
    return compute_metrics(y_test, payload["forecast"], y_train)


__all__ = [
    "ALPHA_OPTIONS",
    "CELL_OPTIONS",
    "DEFAULT_PARAMS",
    "ENCODER_LAYERS_BOUNDS",
    "HIDDEN_SIZE_BOUNDS",
    "INPUT_SIZE_BOUNDS",
    "LSTM_ADAPTER_ID",
    "LSTM_MAX_STEPS",
    "LSTM_MIN_TRAIN",
    "_lstm_fit_predict",
    "run_lstm_backtest",
    "validate_lstm_params",
]
