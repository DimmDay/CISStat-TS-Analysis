# apps/api/model_impls/nbeats.py
"""
N-BEATS -- нейро-модель basis expansion на едином NeuralForecast-runtime
(Task 139, family=neural).  Второй исполнитель neural-runtime контракта
Task 137 (прецедент пары lstm Task 138 в нейро-семействе и пары
garch/egarch в volatility-движке: runtime-контракт Task 137 НЕ меняется --
новый адаптер + запись реестра v2 + условный dispatch + yaml).

Постановка docs/modeling_task_list.md::Tasks 138-142 (Task 139 --
N-BEATS) + требования Task 137:

1. **Архитектурный выбор стека -- честная альтернатива каталожного
   описания**: rules/modeling.yaml::nbeats -- «Basis expansion network.
   Интерпретируемая декомпозиция (тренд + сезонность) через архитектуру
   сети».  Оба обещания -- bounded-параметр stack_config ∈
   {interpretable, generic}, а не один скрытый каркас:
   - interpretable (дефолт) -- каноническая интерпретируемая
     декомпозиция Oreshkin et al. 2019: stack_types=["trend",
     "seasonality"], трендовая/сезонная базы библиотеки (n_polynomials/
     n_harmonics -- официальные дефолты 3.2.2);
   - generic -- генеричная basis-expansion сеть: identity-стеки с
     basis='polynomial' (n_basis -- официальный дефолт).
   (поверхность конструктора снята ЭМПИРИЧЕСКИ пробом
   scripts/task139_nbeats_probe.py: mlp_units вместо encoder_hidden_size
   LSTM; оба стека конструируются и фитятся на 3.2.2).

2. **ЕДИНСТВЕННАЯ точка импорта torch/neuralforecast** --
   apps/api/model_impls/neural_runtime.py (лениво, fail-closed,
   NeuralRuntimeUnavailableError с установочной подсказкой; гейт памяти
   Task 138c -- ensure_neural_memory_capacity ДО импорта).  Этот модуль
   torch НЕ импортирует ни на одном уровне.

3. **ds-ось -- задекларированная конвенция neural-семейства,
   ПЕРЕИСПОЛЬЗОВАНА из Task 138** (lstm._resolve_time_axis -- единый
   источник истины, НЕ продублирован): парсимые метки времени ->
   datetime-сетка + честный pd.infer_freq; что-либо иное -- ПОЗИЦИОННАЯ
   целочисленная сетка (freq=1, нативно поддержана NeuralForecast 3.2.2
   -- проб).  ds -- только ось: значения прогноза N-BEATS от меток не
   зависят; НИКАКОГО скрытого ресемплинга/интерполяции/сортировки данных.

4. **Гейт неосуществимого окна**: n_train < input_size + horizon --
   отказ ДО фита: полностью наблюдаемое supervised-окно (первое окно
   обучается на input_size точках входа и horizon точках цели).
   start_padding_enabled=False (официальный дефолт) согласован: библиотека
   тоже fail-closed (проб: «NBEATS requires at least 48 training
   timestamp(s)»), адаптерный гейт даёт детерминированное сообщение до
   затрат на fit.  Молчаливое ужатие/паддинг окна запрещены.

5. **Интервалы -- официальный conformal-контур контракта Task 137**:
   fit(prediction_intervals=PredictionIntervals()) + predict(level=[...])
   -> колонки NBEATS-lo-<level>/NBEATS-hi-<level> (проб); уровни -- из
   сертифицированного interval_levels_for_alpha (двусторонняя alpha,
   включая медиану).  NBEATS 3.2.2 -- point-loss модель (loss=MAE --
   официальный дефолт); probabilistic-путь MQLoss -- поверхность
   контракта для срезов 140-142 (граница Task 138).

6. **Clamp-инвариант с первого дня** (урок НАХОДКИ-3/M10 сертификации
   Task 138): lower <= point <= upper -- живой гейт поверх isfinite,
   закреплённый fault-injection тестом, а не только happy-path ассертом.

7. **Fail-closed**: короткий train (< NBEATS_MIN_TRAIN), NaN/Inf, стек
   вне whitelist, параметры вне bounded-границ, bool-коэрция
   целочисленных ручек (урок НАХОДКИ-2/M6) -- отказ fold'а БЕЗ
   Naive-fallback и clamp-подмен.

8. **Детерминизм**: random_state реестра -> NeuralTrainingConfig.seed ->
   fold_seed -> random_seed КОНСТРУКТОРА модели (ресертификация Task
   137).  Same-seed -- бит-паритет (проб: max|diff| = 0.0), другой seed
   -- другой прогноз (проб: max|diff| = 0.53; дифференциальные тесты).

9. **Бюджет -- константа модуля** NBEATS_MAX_STEPS (единый бюджетный
   рычаг контракта max_steps) + env-рычаг слабых инстансов
   CISSTAT_NEURAL_MAX_STEPS (паттерн Task 138c: прокси-таймаут Render
   ~100 c; дефолт env не задана -- сертифицированная константа).
   Тюнинг бюджета -- вне param_space обоснованно (прецедент Task 136);
   константа прижата анти-тампер тестом к [100, NEURAL_MAX_STEPS_BOUND].

10. **Проводка бюджета до конструктора прижата spy-тестом** (урок
    НАХОДКИ-1/M18 сертификации Task 138): metadata не должна лгать о
    фактическом бюджете (literal-dup класс артефактов).

Exogenous-канал в реестре НЕ декларирован (supports_future_features=
False; каталог: supports_exogenous=false): контракту Task 137 futr-exog
технически доступен, но для одномерного input_kind="univariate" гейты
реестра v2 отвергают feature-каналы fail-closed; канал exog для
нейро-моделей -- отдельная постановка (прецедент GARCHX/VARX).
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from apps.api.model_impls._common import train_test_split
from apps.api.model_impls._metrics import compute_metrics
from apps.api.model_impls.lstm import _resolve_time_axis
from apps.api.neural_contract import (
    NeuralContractError,
    NeuralRuntimeCapacityError,
    NeuralTrainingConfig,
    interval_levels_for_alpha,
)
from apps.api.model_impls.neural_runtime import train_and_forecast
from apps.api.schemas import BacktestMetrics

NBEATS_ADAPTER_ID = "neuralforecast-nbeats"

#: Минимальная длина train-среза fold'а (честный минимум нейро-фита;
#: мягкий порог применимости каталога min_observations=200 применяется
#: readiness-гейтом РАНЬШЕ -- как у lstm: gate 30 / каталог 200).
NBEATS_MIN_TRAIN = 30

#: Единый бюджет обучения fold'а (max_steps NeuralForecast 3.x); прижат
#: анти-тампер тестом к [100, NEURAL_MAX_STEPS_BOUND].
NBEATS_MAX_STEPS = 300


def _resolve_max_steps() -> int:
    """Бюджет обучения fold'а: CISSTAT_NEURAL_MAX_STEPS или константа 300.

    Паттерн Task 138c: пустая env (дефолт) -- сертифицированная семантика
    Task 138; задана -- целое >= 1; мусор -- ValueError (fail-closed,
    стиль локальной валидации адаптера)."""
    raw = os.environ.get("CISSTAT_NEURAL_MAX_STEPS", "").strip()
    if not raw:
        return NBEATS_MAX_STEPS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"N-BEATS: CISSTAT_NEURAL_MAX_STEPS={raw!r} не целое >= 1 "
            "(fail-closed)"
        ) from exc
    if value < 1:
        raise ValueError(
            f"N-BEATS: CISSTAT_NEURAL_MAX_STEPS={raw!r} не целое >= 1 "
            "(fail-closed)"
        )
    return value


#: Честная альтернатива стеков единого каталожного описания N-BEATS.
STACK_OPTIONS = ("interpretable", "generic")

#: Bounded-границы гиперпараметров (вне тюнинга тоже не могут быть
#: нарушены -- fail-closed).
HIDDEN_SIZE_BOUNDS = (8, 128)
MLP_LAYERS_BOUNDS = (1, 4)
INPUT_SIZE_BOUNDS = (8, 104)

#: Уровни интервалов -- конвенция платформы (как у lstm Task 138).
ALPHA_OPTIONS = (0.01, 0.05, 0.10)

DEFAULT_PARAMS: dict[str, Any] = {
    "stack_config": "interpretable",
    "hidden_size": 32,
    "mlp_layers": 2,
    "input_size": 24,
    "alpha": 0.05,
}

_PARAM_KEYS = ("stack_config", "hidden_size", "mlp_layers", "input_size", "alpha")


def validate_nbeats_params(params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Нормализовать и провалидировать гиперпараметры N-BEATS (fail-closed).

    Неизвестные ключи игнорируются -- соглашение платформы (в params
    приходят чужие ключи, см. backtesting.py::run_backtest_plan).
    """
    merged = {
        **DEFAULT_PARAMS,
        **{k: v for k, v in dict(params or {}).items() if k in _PARAM_KEYS},
    }
    normalized: dict[str, Any] = {}

    stack_config = merged["stack_config"]
    if stack_config not in STACK_OPTIONS:
        raise ValueError(
            f"N-BEATS param 'stack_config'={stack_config!r} вне допустимого "
            f"набора {list(STACK_OPTIONS)}"
        )
    normalized["stack_config"] = str(stack_config)

    for key in ("hidden_size", "mlp_layers", "input_size"):
        value = merged[key]
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise ValueError(
                f"N-BEATS param '{key}': ожидался целочисленный аргумент, "
                f"получено {value!r}"
            )
        low, high = {
            "hidden_size": HIDDEN_SIZE_BOUNDS,
            "mlp_layers": MLP_LAYERS_BOUNDS,
            "input_size": INPUT_SIZE_BOUNDS,
        }[key]
        number = int(value)
        if not low <= number <= high:
            raise ValueError(
                f"N-BEATS param '{key}'={number} вне bounded диапазона "
                f"[{low}, {high}]"
            )
        normalized[key] = number

    alpha = merged["alpha"]
    try:
        alpha_value = float(alpha)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"N-BEATS param 'alpha'={alpha!r} не числовой") from exc
    if alpha_value not in ALPHA_OPTIONS:
        raise ValueError(
            f"N-BEATS param 'alpha'={alpha_value} вне допустимого набора "
            f"{sorted(ALPHA_OPTIONS)}"
        )
    normalized["alpha"] = alpha_value
    return normalized


def _stack_kwargs(stack_config: str, hidden: int, mlp_layers: int) -> dict[str, Any]:
    """Официальная поверхность конструктора NBEATS 3.2.2 (проб).

    Два стека в обоих конфигах: n_blocks=[1, 1] -- по одному блоку на
    стек (mlp_units -- один inner-список на стек); mlp_layers -- глубина
    FC-блока (bounded-ручка вне тюнинга, прецедент encoder_n_layers
    Task 138).  interpretable -- тренд/сезонность с официальными базами
    библиотеки (n_polynomials/n_harmonics -- дефолты 3.2.2); generic --
    identity-стеки с basis='polynomial' (n_basis -- дефолт)."""
    mlp_units = [[hidden] * mlp_layers for _ in range(2)]
    if stack_config == "interpretable":
        return {
            "stack_types": ["trend", "seasonality"],
            "n_blocks": [1, 1],
            "mlp_units": mlp_units,
        }
    return {
        "stack_types": ["identity", "identity"],
        "n_blocks": [1, 1],
        "mlp_units": mlp_units,
        "basis": "polynomial",
    }


def _validated_target(target: Sequence[float]) -> np.ndarray:
    vector = np.asarray([float(value) for value in target], dtype=float)
    if vector.size == 0:
        raise ValueError("N-BEATS: train fold пуст")
    if not np.isfinite(vector).all():
        raise ValueError(
            "N-BEATS: ряд содержит NaN/Inf -- импутация запрещена "
            "(fail-closed)"
        )
    return vector


def _nbeats_fit_predict(
    target: Sequence[float],
    horizon: int,
    *,
    params: Optional[Mapping[str, Any]] = None,
    random_state: int = 42,
    timestamps: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Fit/forecast N-BEATS на train-срезе.

    Возвращает payload: ``forecast`` -- точечный прогноз (horizon,);
    ``lower``/``upper`` -- conformal-границы уровня ``alpha`` (официальный
    контур контракта Task 137); ``params``/``stack_config``/``freq``/
    ``intervals`` -- вход диагностики и metadata executor'а.
    random_state принят по контракту реестра: детерминизм -- сид доходит
    до КОНСТРУКТОРА модели (ресертификация Task 137); фолды платформы
    получают один random_state -- per-fold модели различаются данными,
    прогностический кадр детерминирован.
    """
    if int(horizon) < 1:
        raise ValueError(
            f"N-BEATS: horizon должен быть положительным, получено {horizon!r}"
        )
    normalized = validate_nbeats_params(params)
    vector = _validated_target(target)
    nobs = vector.size
    if nobs < NBEATS_MIN_TRAIN:
        raise ValueError(
            f"N-BEATS: история слишком короткая ({nobs} точек); минимум "
            f"{NBEATS_MIN_TRAIN} (NBEATS_MIN_TRAIN адаптера Task 139)"
        )
    if nobs < normalized["input_size"] + int(horizon):
        raise ValueError(
            f"N-BEATS: неосуществимое окно ({nobs} точек < input_size="
            f"{normalized['input_size']} + horizon={int(horizon)}); "
            "молчаливое ужатие/паддинг окна запрещены (fail-closed)"
        )

    ds, freq = _resolve_time_axis(timestamps, nobs)
    frame = pd.DataFrame({"y": vector}, index=pd.Index(ds, name="ds"))
    from apps.api.neural_contract import to_long_format

    try:
        long = to_long_format(frame, value_column="y")
    except NeuralContractError as exc:
        raise ValueError(f"N-BEATS: {exc}") from exc

    config = NeuralTrainingConfig(
        seed=int(random_state), max_steps=_resolve_max_steps(),
    )

    neuralforecast_models = _require_models()
    model_cls = neuralforecast_models.NBEATS
    stack_kwargs = _stack_kwargs(
        normalized["stack_config"], normalized["hidden_size"],
        normalized["mlp_layers"],
    )

    def _factory(budget: Mapping[str, Any]):
        return model_cls(
            h=int(horizon),
            input_size=normalized["input_size"],
            alias="NBEATS",
            **stack_kwargs,
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
        raise ValueError(f"N-BEATS: {exc}") from exc

    model_name = "NBEATS"
    if model_name not in preds.columns:
        raise ValueError(
            f"N-BEATS: NeuralForecast вернул колонки {list(preds.columns)} "
            f"без точечного прогноза '{model_name}' (fail-closed)"
        )
    point = preds[model_name].to_numpy(dtype=float)
    lower = _interval_column(preds, model_name, "lo", float(plan.levels[0]))
    upper = _interval_column(preds, model_name, "hi", float(plan.levels[-1]))

    if len(point) != int(horizon):
        raise ValueError(
            f"N-BEATS: длина прогноза {len(point)} не равна horizon={int(horizon)}"
        )
    if not (np.isfinite(point).all() and np.isfinite(lower).all()
            and np.isfinite(upper).all()):
        raise ValueError(
            "N-BEATS: прогноз содержит NaN/Inf -- отказ без clamp-подмен "
            "(fail-closed)"
        )
    # Clamp-инвариант (урок НАХОДКИ-3/M10 сертификации Task 138): живой
    # гейт поверх isfinite -- fault-injection тест, а не только happy-path
    # ассерт; никаких молчаливых clamp-подмен границ.
    lower_arr = np.asarray(lower, dtype=float)
    upper_arr = np.asarray(upper, dtype=float)
    if not ((lower_arr <= point).all() and (point <= upper_arr).all()):
        raise NeuralContractError(
            "N-BEATS: нарушен инвариант lower <= point <= upper (fail-closed)"
        )

    return {
        "adapter_id": NBEATS_ADAPTER_ID,
        "forecast": point,
        "lower": lower,
        "upper": upper,
        "params": dict(normalized),
        "stack_config": normalized["stack_config"],
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
            f"N-BEATS: conformal-колонка '{model_name}{suffix}' отсутствует "
            f"в отклике NeuralForecast (fail-closed)"
        )
    return preds[matches[0]].to_numpy(dtype=float)


def _require_models():
    """Ленивый импорт neuralforecast.models (единственная точка --
    neural_runtime.require_neuralforecast)."""
    from apps.api.model_impls.neural_runtime import require_neuralforecast

    return require_neuralforecast().models


def run_nbeats_backtest(
    series: Sequence[float],
    train_ratio: float,
    seasonal_period: int,
):
    """Legacy synthetic-demo эндпоинт (POST /v1/models/backtest), сигнатура
    как у остальных model_impls; seasonal_period не используется (архитектура
    basis expansion извлекает тренд/сезонность из данных сама).  Task 139:
    N-BEATS -- одномерная level-модель, однорядный эндпоинт ПРИМЕНИМ
    (прецедент lstm Task 138 / random_forest); сознательно БЕЗ
    safe_backtest/Naive-fallback -- ошибку модели нельзя подменять метриками
    наивного прогноза."""
    y_train, y_test = train_test_split(list(series), train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)
    payload = _nbeats_fit_predict(y_train, len(y_test), random_state=42)
    return compute_metrics(y_test, payload["forecast"], y_train)


__all__ = [
    "ALPHA_OPTIONS",
    "DEFAULT_PARAMS",
    "HIDDEN_SIZE_BOUNDS",
    "INPUT_SIZE_BOUNDS",
    "MLP_LAYERS_BOUNDS",
    "NBEATS_ADAPTER_ID",
    "NBEATS_MAX_STEPS",
    "NBEATS_MIN_TRAIN",
    "STACK_OPTIONS",
    "_nbeats_fit_predict",
    "run_nbeats_backtest",
    "validate_nbeats_params",
]
