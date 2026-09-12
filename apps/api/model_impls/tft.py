# apps/api/model_impls/tft.py
"""
TFT (Temporal Fusion Transformer) -- нейро-модель attention-архитектуры
на едином NeuralForecast-runtime и ПЕРВЫЙ срез платформы с
probabilistic-поверхностью MQLoss/quantiles (Task 141, family=neural).
Четвёртый исполнитель neural-runtime контракта Task 137 (прецедент
тройки lstm Task 138 / nbeats Task 139 / nhits Task 140 в
нейро-семействе и пары garch/egarch в volatility-движке:
runtime-контракт Task 137 НЕ меняется -- новый адаптер + запись
реестра v2 + условный dispatch + yaml).

Постановка docs/modeling_task_list.md::Tasks 138-142 (Task 141 --
TFT) + требования Task 137 ("probabilistic losses и quantiles").
MQLoss был явно зарезервирован под срезы 141-142 границей Task 138
(«probabilistic-путь MQLoss -- поверхность контракта для срезов
141-142») и рекомендацией ресертификации Task 137.

1. **Probabilistic-поверхность -- ЯДРО постановки**: интервалы
   строятся NATIVE-квантилями функции потерь MQLoss (первая
   probabilistic-модель платформы), а не сертифицированным
   conformal-контуром point-loss моделей (fit
   prediction_intervals + predict level -- путь тройки
   lstm/nbeats/nhits).  Квантили декларируются ПРЯМО:
   MQLoss(quantiles=[alpha/2, 0.5, 1-alpha/2]) -- честный двусторонний
   интервал [alpha/2; 1-alpha/2] процентилей; точечный прогноз --
   медиана (колонка "TFT-median", канонический point-прогноз под
   pinball-loss 0.5).  Контрактный гейт Task 137
   resolve_probabilistic_loss("mqloss", levels=...) пропускает план
   только с уровнями (NEURAL_PROBABILISTIC_LOSSES); метод интервалов
   в metadata -- NeuralIntervalPlan.method="neural_quantile_outputs".

2. **Эмпирика level-семантики 3.2.2** (проб
   scripts/task141_tft_probe.py + исходники level_to_outputs/
   quantiles_to_outputs): суффикс колонок "-lo-<w>"/"-hi-<w>"
   кодирует ШИРИНУ интервала w (границы при 50±w/2 процентилях), а
   НЕ прямой квантиль.  Поэтому для alpha=0.05 адаптер передаёт
   quantiles=[0.025, 0.5, 0.975] (границы честно в 2.5/97.5
   процентилях), а суффикс колонок -- "-lo-95.0"/"-hi-95.0"
   (w = 100*(1-alpha); конвенция round(100-200*q, 2)).  Прямая
   декларация quantiles= устраняет зависимость от width-семантики
   level= и делает план квантилей самодокументированным.
   (Эмпирическое следствие для сертифицированной тройки
   lstm/nbeats/nhits -- уровни plan.levels=(2.5, 50.0, 97.5) в
   conformal-вызове трактуются как ШИРИНЫ: извлечённая пара
   lo-2.5/hi-97.5 соответствовала (48.75, 98.75) процентилям, а не
   (2.5, 97.5); нижняя граница схлопывалась к медиане.  Находка
   отработана ПОСТАНОВКОЙ ТИМЛИДА сразу после Task 141: width-семантика
   исправлена во всей тройке (level=[100*(1-alpha)] из
   interval_width_for_alpha) с ресертификацией; контрактная функция
   interval_width_for_alpha -- единый источник истины ширины,
   _quantile_plan TFT переиспользует её же.)

3. **Архитектурный выбор attention-оси -- честная альтернатива
   каталожного описания**: rules/modeling.yaml::tft -- «Attention-
   based architecture (Google). Интерпретируемость через attention
   weights».  Обещание -- bounded-параметр n_head ∈ {2, 4} (число
   голов InterpretableMultiHeadAttention; дефолт библиотеки 4).
   Constraint архитектуры: d_k = hidden_size // n_head -- на
   неделимой паре библиотека падает AssertionError (проб);
   адаптерный гейт hidden_size % n_head == 0 даёт детерминированное
   сообщение ДО конструирования (стиль гейта неосуществимого окна).

4. **ЕДИНСТВЕННАЯ точка импорта torch/neuralforecast** --
   apps/api/model_impls/neural_runtime.py (лениво, fail-closed,
   NeuralRuntimeUnavailableError с установочной подсказкой; гейт
   памяти Task 138c -- ensure_neural_memory_capacity ДО импорта).
   Этот модуль torch НЕ импортирует ни на одном уровне; MQLoss
   берётся через require_neuralforecast().losses.pytorch -- та же
   единственная точка тяжёлого импорта.

5. **ds-ось -- задекларированная конвенция neural-семейства,
   ПЕРЕИСПОЛЬЗОВАНА из Task 138** (lstm._resolve_time_axis -- единый
   источник истины, НЕ продублирован): парсимые метки времени ->
   datetime-сетка + честный pd.infer_freq; что-либо иное --
   ПОЗИЦИОННАЯ целочисленная сетка (freq=1, нативно поддержана
   NeuralForecast 3.2.2 -- проб).  ds -- только ось: значения
   прогноза TFT от меток не зависят; НИКАКОГО скрытого
   ресемплинга/интерполяции/сортировки данных.

6. **Гейт неосуществимого окна**: n_train < input_size + horizon --
   отказ ДО фита: полностью наблюдаемое supervised-окно (первое окно
   обучается на input_size точках входа и horizon точках цели).
   start_padding_enabled=False (официальный дефолт) согласован:
   библиотека тоже fail-closed (проб: «TFT requires at least 48
   training timestamp(s)»), адаптерный гейт даёт детерминированное
   сообщение до затрат на fit.  Молчаливое ужатие/паддинг окна
   запрещены.  TFT_MIN_TRAIN=30 (абсолютный пол; каталоговский мягкий
   порог 200 -- раньше, readiness-гейтом F04).

7. **Clamp-инвариант с первого дня** (урок НАХОДКИ-3/M10
   сертификации Task 138): lower <= median <= upper -- живой гейт
   поверх isfinite, закреплённый fault-injection тестом.  Для MQLoss
   гейт ловит квантильное пересечение (quantile crossing): головы
   квантилей независимы, пересечение теоретически возможно --
   честный отказ fold'а вместо молчаливого clamp'а границ.

8. **Fail-closed**: короткий train (< TFT_MIN_TRAIN), NaN/Inf,
   n_head вне whitelist, конфигурация вне bounded-границ, нарушение
   делимости, bool-коэрция целочисленных ручек (урок НАХОДКИ-2/M6) --
   отказ fold'а БЕЗ Naive-fallback и clamp-подмен.

9. **Детерминизм**: random_state реестра -> NeuralTrainingConfig.seed
   -> fold_seed -> random_seed КОНСТРУКТОРА модели (ресертификация
   Task 137).  Same-seed -- бит-паритет (проб: max|diff| = 0.0),
   другой seed -- другой прогноз (проб: max|diff| = 0.0147).

10. **Бюджет -- константа модуля** TFT_MAX_STEPS (единый бюджетный
    рычаг контракта max_steps; семейная конвенция 300 -- как
    lstm/nbeats/nhits) + env-рычаг слабых инстансов
    CISSTAT_NEURAL_MAX_STEPS (паттерн Task 138c/139/140: прокси-
    таймаут Render ~100 c; дефолт env не задана -- сертифицированная
    константа).  Тюнинг бюджета -- вне param_space обоснованно
    (прецедент Task 136); константа прижата анти-тампер тестом к
    [100, NEURAL_MAX_STEPS_BOUND].

11. **Проводка бюджета до конструктора прижата spy-тестом** (урок
    НАХОДКИ-1/M18 сертификации Task 138): metadata не должна лгать о
    фактическом бюджете (literal-dup класс артефактов).

Exogenous-канал в реестре НЕ декларирован (supports_future_features
=False; exog-канал нейро-моделей -- отдельная постановка, прецедент
GARCHX/VARX): контракту Task 137 futr/hist-exog технически доступен
(hist_exog_list в поверхности конструктора; каталожное
«Поддержка ... экзогенных» -- обещание этого канала), но для
одномерного input_kind="univariate" гейты реестра v2 отвергают
feature-каналы fail-closed (прецедент lstm: каталожное
supports_exogenous=true не декларировано в реестре до отдельного
среза exog-канала).
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
    interval_width_for_alpha,
    resolve_probabilistic_loss,
)
from apps.api.model_impls.neural_runtime import train_and_forecast
from apps.api.schemas import BacktestMetrics

TFT_ADAPTER_ID = "neuralforecast-tft"

#: Минимальная длина train-среза fold'а (честный минимум нейро-фита;
#: мягкий порог применимости каталога min_observations=200 применяется
#: readiness-гейтом РАНЬШЕ -- как у lstm/nbeats/nhits: gate 30 /
#: каталог 200).
TFT_MIN_TRAIN = 30

#: Единый бюджет обучения fold'а (max_steps NeuralForecast 3.x); семейная
#: конвенция 300 (lstm/nbeats/nhits); прижат анти-тампер тестом к
#: [100, NEURAL_MAX_STEPS_BOUND].
TFT_MAX_STEPS = 300


def _resolve_max_steps() -> int:
    """Бюджет обучения fold'а: CISSTAT_NEURAL_MAX_STEPS или константа 300.

    Паттерн Task 138c/139/140: пустая env (дефолт) -- сертифицированная
    семантика семейства; задана -- целое >= 1; мусор -- ValueError
    (fail-closed, стиль локальной валидации адаптера)."""
    raw = os.environ.get("CISSTAT_NEURAL_MAX_STEPS", "").strip()
    if not raw:
        return TFT_MAX_STEPS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"TFT: CISSTAT_NEURAL_MAX_STEPS={raw!r} не целое >= 1 "
            "(fail-closed)"
        ) from exc
    if value < 1:
        raise ValueError(
            f"TFT: CISSTAT_NEURAL_MAX_STEPS={raw!r} не целое >= 1 "
            "(fail-closed)"
        )
    return value


#: Честная альтернатива attention-оси единого каталожного описания TFT
#: («Attention-based architecture»): число голов attention.
N_HEAD_OPTIONS = (2, 4)

#: Bounded-границы гиперпараметров (вне тюнинга тоже не могут быть
#: нарушены -- fail-closed).
HIDDEN_SIZE_BOUNDS = (8, 128)
INPUT_SIZE_BOUNDS = (8, 104)

#: Уровни интервалов -- конвенция платформы (как у lstm/nbeats/nhits).
ALPHA_OPTIONS = (0.01, 0.05, 0.10)

DEFAULT_PARAMS: dict[str, Any] = {
    "n_head": 4,
    "hidden_size": 32,
    "input_size": 24,
    "alpha": 0.05,
}

_PARAM_KEYS = ("n_head", "hidden_size", "input_size", "alpha")


def validate_tft_params(params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Нормализовать и провалидировать гиперпараметры TFT (fail-closed).

    Неизвестные ключи игнорируются -- соглашение платформы (в params
    приходят чужие ключи, см. backtesting.py::run_backtest_plan).
    """
    merged = {
        **DEFAULT_PARAMS,
        **{k: v for k, v in dict(params or {}).items() if k in _PARAM_KEYS},
    }
    normalized: dict[str, Any] = {}

    n_head = merged["n_head"]
    if isinstance(n_head, bool) or not isinstance(n_head, (int, np.integer)):
        raise ValueError(
            f"TFT param 'n_head': ожидался целочисленный аргумент, "
            f"получено {n_head!r}"
        )
    n_head = int(n_head)
    if n_head not in N_HEAD_OPTIONS:
        raise ValueError(
            f"TFT param 'n_head'={n_head} вне допустимого набора "
            f"{list(N_HEAD_OPTIONS)}"
        )
    normalized["n_head"] = n_head

    for key in ("hidden_size", "input_size"):
        value = merged[key]
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise ValueError(
                f"TFT param '{key}': ожидался целочисленный аргумент, "
                f"получено {value!r}"
            )
        low, high = {
            "hidden_size": HIDDEN_SIZE_BOUNDS,
            "input_size": INPUT_SIZE_BOUNDS,
        }[key]
        number = int(value)
        if not low <= number <= high:
            raise ValueError(
                f"TFT param '{key}'={number} вне bounded диапазона "
                f"[{low}, {high}]"
            )
        normalized[key] = number

    # Constraint архитектуры InterpretableMultiHeadAttention:
    # d_k = hidden_size // n_head -- на неделимой паре библиотека падает
    # AssertionError (проб scripts/task141_tft_probe.py); детерминированное
    # сообщение ДО конструирования (стиль гейта неосуществимого окна).
    if normalized["hidden_size"] % normalized["n_head"] != 0:
        raise ValueError(
            f"TFT param 'hidden_size'={normalized['hidden_size']} обязан "
            f"быть кратным n_head={normalized['n_head']} "
            "(InterpretableMultiHeadAttention: d_k = hidden_size // n_head)"
        )

    alpha = merged["alpha"]
    try:
        alpha_value = float(alpha)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"TFT param 'alpha'={alpha!r} не числовой") from exc
    if alpha_value not in ALPHA_OPTIONS:
        raise ValueError(
            f"TFT param 'alpha'={alpha_value} вне допустимого набора "
            f"{sorted(ALPHA_OPTIONS)}"
        )
    normalized["alpha"] = alpha_value
    return normalized


def _quantile_plan(alpha: float) -> dict[str, Any]:
    """Probabilistic-план MQLoss/quantiles из двусторонней alpha.

    Прямая декларация квантилей (alpha/2, 0.5, 1-alpha/2) -- честный
    двусторонний интервал в процентилях; "levels" -- тот же план в
    процентилях interval_levels_for_alpha (контракт Task 137, включая
    медиану); "width" -- ШИРИНА интервала w = 100*(1-alpha), задающая
    суффикс колонок отклика 3.2.2 ('-lo-<w>'/'-hi-<w>': конвенция
    quantiles_to_outputs round(100-200*q, 2) -- проб + исходники).
    "method" -- NeuralIntervalPlan.method контракта (нативные
    квантильные выходы, НЕ conformal).
    """
    plan = interval_levels_for_alpha(alpha)
    q_lo = round(alpha / 2.0, 6)
    q_hi = round(1.0 - alpha / 2.0, 6)
    # Единый источник истины ширины (НАХОДКА Task 141 п.2, правка
    # width-семантики тройки): та же interval_width_for_alpha контракта,
    # что и у lstm/nbeats/nhits -- без локального дубля.
    width = interval_width_for_alpha(alpha)
    return {
        "method": "neural_quantile_outputs",
        "loss": "mqloss",
        "alpha": float(alpha),
        "quantiles": (q_lo, 0.5, q_hi),
        "levels": tuple(float(level) for level in plan.levels),
        "width": float(width),
    }


def _validated_target(target: Sequence[float]) -> np.ndarray:
    vector = np.asarray([float(value) for value in target], dtype=float)
    if vector.size == 0:
        raise ValueError("TFT: train fold пуст")
    if not np.isfinite(vector).all():
        raise ValueError(
            "TFT: ряд содержит NaN/Inf -- импутация запрещена "
            "(fail-closed)"
        )
    return vector


def _tft_fit_predict(
    target: Sequence[float],
    horizon: int,
    *,
    params: Optional[Mapping[str, Any]] = None,
    random_state: int = 42,
    timestamps: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Fit/forecast TFT на train-срезе.

    Возвращает payload: ``forecast`` -- точечный прогноз (horizon,) =
    медиана MQLoss; ``lower``/``upper`` -- нативные квантильные границы
    уровня ``alpha`` (probabilistic-поверхность Task 141); ``params``/
    ``freq``/``intervals`` -- вход диагностики и metadata executor'а.
    random_state принят по контракту реестра: детерминизм -- сид доходит
    до КОНСТРУКТОРА модели (ресертификация Task 137); фолды платформы
    получают один random_state -- per-fold модели различаются данными,
    прогностический кадр детерминирован.
    """
    if int(horizon) < 1:
        raise ValueError(
            f"TFT: horizon должен быть положительным, получено {horizon!r}"
        )
    normalized = validate_tft_params(params)
    vector = _validated_target(target)
    nobs = vector.size
    if nobs < TFT_MIN_TRAIN:
        raise ValueError(
            f"TFT: история слишком короткая ({nobs} точек); минимум "
            f"{TFT_MIN_TRAIN} (TFT_MIN_TRAIN адаптера Task 141)"
        )
    if nobs < normalized["input_size"] + int(horizon):
        raise ValueError(
            f"TFT: неосуществимое окно ({nobs} точек < input_size="
            f"{normalized['input_size']} + horizon={int(horizon)}); "
            "молчаливое ужатие/паддинг окна запрещены (fail-closed)"
        )

    ds, freq = _resolve_time_axis(timestamps, nobs)
    frame = pd.DataFrame({"y": vector}, index=pd.Index(ds, name="ds"))
    from apps.api.neural_contract import to_long_format

    try:
        long = to_long_format(frame, value_column="y")
    except NeuralContractError as exc:
        raise ValueError(f"TFT: {exc}") from exc

    config = NeuralTrainingConfig(
        seed=int(random_state), max_steps=_resolve_max_steps(),
    )

    plan = _quantile_plan(normalized["alpha"])
    # Контрактный гейт Task 137: probabilistic-функция потерь требует
    # объявленного плана уровней (NEURAL_PROBABILISTIC_LOSSES).
    resolve_probabilistic_loss("mqloss", levels=plan["levels"])

    nf_module = _require_neuralforecast()
    model_cls = nf_module.models.TFT
    mqloss_cls = nf_module.losses.pytorch.MQLoss

    def _factory(budget: Mapping[str, Any]):
        return model_cls(
            h=int(horizon),
            input_size=normalized["input_size"],
            hidden_size=normalized["hidden_size"],
            n_head=normalized["n_head"],
            alias="TFT",
            # Прямая декларация квантилей: (alpha/2, 0.5, 1-alpha/2) --
            # честный двусторонний интервал; точка = медиана.
            loss=mqloss_cls(quantiles=list(plan["quantiles"])),
            **dict(budget),
        )

    try:
        # levels=() -- conformal-контур НЕ активируется: квантильные
        # выходы нативны loss=MQLoss (PredictionIntervals не нужен).
        preds = train_and_forecast(
            model_factory=_factory,
            freq=freq,
            train_long=long,
            horizon=int(horizon),
            config=config,
            levels=(),
            fold_index=0,
        )
    except NeuralRuntimeCapacityError:
        # Task 138c: ресурсный отказ нейро-runtime проходит НАСКВОЗЬ без
        # ValueError-обёртки -- HTTP-слой обязан увидеть честный статус
        # (503 legacy-роутера / 422 session-движка), а не потерять его.
        raise
    except NeuralContractError as exc:
        raise ValueError(f"TFT: {exc}") from exc

    point = _median_column(preds)
    width = float(plan["width"])
    lower = _quantile_column(preds, "lo", width)
    upper = _quantile_column(preds, "hi", width)

    if len(point) != int(horizon):
        raise ValueError(
            f"TFT: длина прогноза {len(point)} не равна horizon={int(horizon)}"
        )
    if not (np.isfinite(point).all() and np.isfinite(lower).all()
            and np.isfinite(upper).all()):
        raise ValueError(
            "TFT: прогноз содержит NaN/Inf -- отказ без clamp-подмен "
            "(fail-closed)"
        )
    # Clamp-инвариант (урок НАХОДКИ-3/M10 сертификации Task 138): живой
    # гейт поверх isfinite -- ловит и квантильное пересечение MQLoss
    # (heads независимы); fault-injection тест, а не только happy-path
    # ассерт; никаких молчаливых clamp-подмен границ.
    lower_arr = np.asarray(lower, dtype=float)
    upper_arr = np.asarray(upper, dtype=float)
    point_arr = np.asarray(point, dtype=float)
    if not ((lower_arr <= point_arr).all() and (point_arr <= upper_arr).all()):
        raise NeuralContractError(
            "TFT: нарушен инвариант lower <= point <= upper "
            "(квантильное пересечение MQLoss; fail-closed)"
        )

    return {
        "adapter_id": TFT_ADAPTER_ID,
        "forecast": point,
        "lower": lower,
        "upper": upper,
        "params": dict(normalized),
        "nobs": int(nobs),
        "max_steps": int(config.max_steps),
        "seed": int(config.seed),
        "freq": (
            {"kind": "datetime", "value": str(freq)}
            if isinstance(freq, str) else {"kind": "integer", "value": 1}
        ),
        "intervals": {
            "method": "neural_quantile_outputs",
            "loss": "mqloss",
            "alpha": float(normalized["alpha"]),
            "quantiles": [float(q) for q in plan["quantiles"]],
            "levels": [float(level) for level in plan["levels"]],
        },
        "random_state": int(random_state),
        "deterministic": True,
    }


def _median_column(preds: pd.DataFrame) -> np.ndarray:
    """Точечный прогноз TFT -- медиана MQLoss (колонка 'TFT-median').

    При probabilistic-loss NeuralForecast НЕ возвращает bare-колонку
    'TFT' (проб): отсутствие медианы -- fail-closed."""
    if "TFT-median" not in preds.columns:
        raise ValueError(
            f"TFT: NeuralForecast вернул колонки {list(preds.columns)} "
            "без медианы 'TFT-median' (probabilistic-поверхность "
            "MQLoss; fail-closed)"
        )
    return preds["TFT-median"].to_numpy(dtype=float)


def _quantile_column(
    preds: pd.DataFrame, side: str, width: float,
) -> np.ndarray:
    """Квантильная граница по суффиксу ширины ('-lo-<w>'/'-hi-<w>').

    Суффикс кодирует ШИРИНУ интервала (эмпирика 3.2.2: конвенция
    quantiles_to_outputs round(100-200*q, 2)); поиск по endswith --
    fail-closed к переименованию формата."""
    suffix = f"-{side}-{width}"
    matches = [column for column in preds.columns if str(column).endswith(suffix)]
    if not matches:
        raise ValueError(
            f"TFT: квантильная колонка 'TFT{suffix}' отсутствует "
            "в отклике NeuralForecast (fail-closed)"
        )
    return preds[matches[0]].to_numpy(dtype=float)


def _require_neuralforecast():
    """Ленивый импорт neuralforecast (единственная точка --
    neural_runtime.require_neuralforecast): модели + losses.pytorch
    (MQLoss) -- одна и та же точка тяжёлого импорта платформы."""
    from apps.api.model_impls.neural_runtime import require_neuralforecast

    return require_neuralforecast()


def run_tft_backtest(
    series: Sequence[float],
    train_ratio: float,
    seasonal_period: int,
):
    """Legacy synthetic-demo эндпоинт (POST /v1/models/backtest), сигнатура
    как у остальных model_impls; seasonal_period не используется
    (attention-архитектура извлекает тренд/сезонность из данных сама).
    Task 141: TFT -- одномерная level-модель, однорядный эндпоинт
    ПРИМЕНИМ (прецедент lstm Task 138 / nbeats Task 139 / nhits Task 140
    / random_forest); сознательно БЕЗ safe_backtest/Naive-fallback --
    ошибку модели нельзя подменять метриками наивного прогноза."""
    y_train, y_test = train_test_split(list(series), train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)
    payload = _tft_fit_predict(y_train, len(y_test), random_state=42)
    return compute_metrics(y_test, payload["forecast"], y_train)


__all__ = [
    "ALPHA_OPTIONS",
    "DEFAULT_PARAMS",
    "HIDDEN_SIZE_BOUNDS",
    "INPUT_SIZE_BOUNDS",
    "N_HEAD_OPTIONS",
    "TFT_ADAPTER_ID",
    "TFT_MAX_STEPS",
    "TFT_MIN_TRAIN",
    "_quantile_plan",
    "_tft_fit_predict",
    "run_tft_backtest",
    "validate_tft_params",
]
