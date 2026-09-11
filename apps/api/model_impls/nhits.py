# apps/api/model_impls/nhits.py
"""
N-HiTS -- нейро-модель иерархической интерполяции на едином
NeuralForecast-runtime (Task 140, family=neural).  Третий исполнитель
neural-runtime контракта Task 137 (прецедент пар lstm Task 138 /
nbeats Task 139 в нейро-семействе и пары garch/egarch в
volatility-движке: runtime-контракт Task 137 НЕ меняется -- новый
адаптер + запись реестра v2 + условный dispatch + yaml).

Постановка docs/modeling_task_list.md::Tasks 138-142 (Task 140 --
N-HiTS) + требования Task 137 + комментарий тимлида: «скелет среза
повторяется, плюс готовая база для сравнения N-BEATS/N-HiTS на одном
runtime» -- сравнительная база закреплена в
tests/unit/test_nhits_integration_paths.py
(test_nbeats_and_nhits_share_one_runtime_for_fair_comparison:
идентичный контракт пары + ЕДИНАЯ точка исполнения
neural_runtime.train_and_forecast -- один level-cohort, честное
ранжирование comparison sectioned by objective без выравнивания
контрактов).

1. **Архитектурный выбор степени иерархической интерполяции -- честная
   альтернатива каталожного описания**: rules/modeling.yaml::nhits --
   «Hierarchical interpolation N-BEATS. Быстрее и точнее на долгих
   горизонтах прогнозирования».  Оба обещания -- bounded-параметр
   interpolation_config ∈ {hierarchical, light}, а не один скрытый
   каркас (оба механизма N-HiTS активны в обеих конфигурациях:
   multi-rate input pooling + hierarchical interpolation выходов
   Challu et al. 2023):
   - hierarchical (дефолт) -- канонический N-HiTS: официальные дефолты
     3.2.2 n_pool_kernel_size=[2,2,1], n_freq_downsample=[4,2,1]
     (агрессивная интерполяция -- эффективность длинных горизонтов);
   - light -- минимальная иерархия: n_pool_kernel_size=[2,1,1],
     n_freq_downsample=[2,1,1] (фактор 2 только на самом грубом
     стеке -- максимум разрешения коротких горизонтов).
   (поверхность конструктора снята ЭМПИРИЧЕСКИ пробом
   scripts/task140_nhits_probe.py: NHITS использует mlp_units как
   NBEATS, три identity-стека; обе конфигурации конструируются и
   фитятся на 3.2.2).

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
   -- проб).  ds -- только ось: значения прогноза N-HiTS от меток не
   зависят; НИКАКОГО скрытого ресемплинга/интерполяции/сортировки
   данных.

4. **Гейт неосуществимого окна**: n_train < input_size + horizon --
   отказ ДО фита: полностью наблюдаемое supervised-окно (первое окно
   обучается на input_size точках входа и horizon точках цели).
   start_padding_enabled=False (официальный дефолт) согласован:
   библиотека тоже fail-closed (проб: «NHITS requires at least 48
   training timestamp(s)»), адаптерный гейт даёт детерминированное
   сообщение до затрат на fit.  Молчаливое ужатие/паддинг окна
   запрещены.

5. **Интервалы -- официальный conformal-контур контракта Task 137**:
   fit(prediction_intervals=PredictionIntervals()) + predict(level=[...])
   -> колонки NHITS-lo-<level>/NHITS-hi-<level> (проб); уровни -- из
   сертифицированного interval_levels_for_alpha (двусторонняя alpha,
   включая медиану).  NHITS 3.2.2 -- point-loss модель (loss=MAE --
   официальный дефолт); probabilistic-путь MQLoss -- поверхность
   контракта для срезов 141-142 (граница Task 138).

6. **Clamp-инвариант с первого дня** (урок НАХОДКИ-3/M10 сертификации
   Task 138): lower <= point <= upper -- живой гейт поверх isfinite,
   закреплённый fault-injection тестом, а не только happy-path ассертом.

7. **Fail-closed**: короткий train (< NHITS_MIN_TRAIN), NaN/Inf,
   конфигурация вне whitelist, параметры вне bounded-границ,
   bool-коэрция целочисленных ручек (урок НАХОДКИ-2/M6) -- отказ
   fold'а БЕЗ Naive-fallback и clamp-подмен.

8. **Детерминизм**: random_state реестра -> NeuralTrainingConfig.seed ->
   fold_seed -> random_seed КОНСТРУКТОРА модели (ресертификация Task
   137).  Same-seed -- бит-паритет (проб: max|diff| = 0.0), другой seed
   -- другой прогноз (проб: max|diff| = 0.44; дифференциальные тесты).

9. **Бюджет -- константа модуля** NHITS_MAX_STEPS (единый бюджетный
   рычаг контракта max_steps) + env-рычаг слабых инстансов
   CISSTAT_NEURAL_MAX_STEPS (паттерн Task 138c/139: прокси-таймаут
   Render ~100 c; дефолт env не задана -- сертифицированная константа).
   Тюнинг бюджета -- вне param_space обоснованно (прецедент Task 136);
   константа прижата анти-тампер тестом к [100, NEURAL_MAX_STEPS_BOUND].

10. **Проводка бюджета до конструктора прижата spy-тестом** (урок
    НАХОДКИ-1/M18 сертификации Task 138): metadata не должна лгать о
    фактическом бюджете (literal-dup класс артефактов).

Exogenous-канал в реестре НЕ декларирован (supports_future_features=
False; каталог: supports_exogenous=false): контракту Task 137 futr-exog
технически доступен (hist_exog_list в поверхности конструктора), но для
одномерного input_kind="univariate" гейты реестра v2 отвергают
feature-каналы fail-closed; канал exog для нейро-моделей -- отдельная
постановка (прецедент GARCHX/VARX).
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

NHITS_ADAPTER_ID = "neuralforecast-nhits"

#: Минимальная длина train-среза fold'а (честный минимум нейро-фита;
#: мягкий порог применимости каталога min_observations=200 применяется
#: readiness-гейтом РАНЬШЕ -- как у lstm/nbeats: gate 30 / каталог 200).
NHITS_MIN_TRAIN = 30

#: Единый бюджет обучения fold'а (max_steps NeuralForecast 3.x); прижат
#: анти-тампер тестом к [100, NEURAL_MAX_STEPS_BOUND].
NHITS_MAX_STEPS = 300


def _resolve_max_steps() -> int:
    """Бюджет обучения fold'а: CISSTAT_NEURAL_MAX_STEPS или константа 300.

    Паттерн Task 138c/139: пустая env (дефолт) -- сертифицированная
    семантика семейства; задана -- целое >= 1; мусор -- ValueError
    (fail-closed, стиль локальной валидации адаптера)."""
    raw = os.environ.get("CISSTAT_NEURAL_MAX_STEPS", "").strip()
    if not raw:
        return NHITS_MAX_STEPS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"N-HiTS: CISSTAT_NEURAL_MAX_STEPS={raw!r} не целое >= 1 "
            "(fail-closed)"
        ) from exc
    if value < 1:
        raise ValueError(
            f"N-HiTS: CISSTAT_NEURAL_MAX_STEPS={raw!r} не целое >= 1 "
            "(fail-closed)"
        )
    return value


#: Честная альтернатива степеней иерархической интерполяции единого
#: каталожного описания N-HiTS.
INTERPOLATION_OPTIONS = ("hierarchical", "light")

#: Bounded-границы гиперпараметров (вне тюнинга тоже не могут быть
#: нарушены -- fail-closed).
HIDDEN_SIZE_BOUNDS = (8, 128)
MLP_LAYERS_BOUNDS = (1, 4)
INPUT_SIZE_BOUNDS = (8, 104)

#: Уровни интервалов -- конвенция платформы (как у lstm/nbeats).
ALPHA_OPTIONS = (0.01, 0.05, 0.10)

DEFAULT_PARAMS: dict[str, Any] = {
    "interpolation_config": "hierarchical",
    "hidden_size": 32,
    "mlp_layers": 2,
    "input_size": 24,
    "alpha": 0.05,
}

_PARAM_KEYS = (
    "interpolation_config", "hidden_size", "mlp_layers", "input_size", "alpha",
)


def validate_nhits_params(params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Нормализовать и провалидировать гиперпараметры N-HiTS (fail-closed).

    Неизвестные ключи игнорируются -- соглашение платформы (в params
    приходят чужие ключи, см. backtesting.py::run_backtest_plan).
    """
    merged = {
        **DEFAULT_PARAMS,
        **{k: v for k, v in dict(params or {}).items() if k in _PARAM_KEYS},
    }
    normalized: dict[str, Any] = {}

    interpolation_config = merged["interpolation_config"]
    if interpolation_config not in INTERPOLATION_OPTIONS:
        raise ValueError(
            f"N-HiTS param 'interpolation_config'={interpolation_config!r} "
            f"вне допустимого набора {list(INTERPOLATION_OPTIONS)}"
        )
    normalized["interpolation_config"] = str(interpolation_config)

    for key in ("hidden_size", "mlp_layers", "input_size"):
        value = merged[key]
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise ValueError(
                f"N-HiTS param '{key}': ожидался целочисленный аргумент, "
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
                f"N-HiTS param '{key}'={number} вне bounded диапазона "
                f"[{low}, {high}]"
            )
        normalized[key] = number

    alpha = merged["alpha"]
    try:
        alpha_value = float(alpha)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"N-HiTS param 'alpha'={alpha!r} не числовой") from exc
    if alpha_value not in ALPHA_OPTIONS:
        raise ValueError(
            f"N-HiTS param 'alpha'={alpha_value} вне допустимого набора "
            f"{sorted(ALPHA_OPTIONS)}"
        )
    normalized["alpha"] = alpha_value
    return normalized


def _interpolation_kwargs(interpolation_config: str) -> dict[str, Any]:
    """Официальная поверхность конструктора NHITS 3.2.2 (проб).

    Три identity-стека в обеих конфигурациях (канон N-HiTS); различие --
    СТЕПЕНЬ иерархии (честная альтернатива каталожного «Hierarchical
    interpolation... на долгих горизонтах»): hierarchical -- официальные
    дефолты 3.2.2; light -- фактор 2 только на самом грубом стеке."""
    if interpolation_config == "hierarchical":
        return {
            "n_pool_kernel_size": [2, 2, 1],
            "n_freq_downsample": [4, 2, 1],
        }
    return {
        "n_pool_kernel_size": [2, 1, 1],
        "n_freq_downsample": [2, 1, 1],
    }


def _validated_target(target: Sequence[float]) -> np.ndarray:
    vector = np.asarray([float(value) for value in target], dtype=float)
    if vector.size == 0:
        raise ValueError("N-HiTS: train fold пуст")
    if not np.isfinite(vector).all():
        raise ValueError(
            "N-HiTS: ряд содержит NaN/Inf -- импутация запрещена "
            "(fail-closed)"
        )
    return vector


def _nhits_fit_predict(
    target: Sequence[float],
    horizon: int,
    *,
    params: Optional[Mapping[str, Any]] = None,
    random_state: int = 42,
    timestamps: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Fit/forecast N-HiTS на train-срезе.

    Возвращает payload: ``forecast`` -- точечный прогноз (horizon,);
    ``lower``/``upper`` -- conformal-границы уровня ``alpha`` (официальный
    контур контракта Task 137); ``params``/``interpolation_config``/
    ``freq``/``intervals`` -- вход диагностики и metadata executor'а.
    random_state принят по контракту реестра: детерминизм -- сид доходит
    до КОНСТРУКТОРА модели (ресертификация Task 137); фолды платформы
    получают один random_state -- per-fold модели различаются данными,
    прогностический кадр детерминирован.
    """
    if int(horizon) < 1:
        raise ValueError(
            f"N-HiTS: horizon должен быть положительным, получено {horizon!r}"
        )
    normalized = validate_nhits_params(params)
    vector = _validated_target(target)
    nobs = vector.size
    if nobs < NHITS_MIN_TRAIN:
        raise ValueError(
            f"N-HiTS: история слишком короткая ({nobs} точек); минимум "
            f"{NHITS_MIN_TRAIN} (NHITS_MIN_TRAIN адаптера Task 140)"
        )
    if nobs < normalized["input_size"] + int(horizon):
        raise ValueError(
            f"N-HiTS: неосуществимое окно ({nobs} точек < input_size="
            f"{normalized['input_size']} + horizon={int(horizon)}); "
            "молчаливое ужатие/паддинг окна запрещены (fail-closed)"
        )

    ds, freq = _resolve_time_axis(timestamps, nobs)
    frame = pd.DataFrame({"y": vector}, index=pd.Index(ds, name="ds"))
    from apps.api.neural_contract import to_long_format

    try:
        long = to_long_format(frame, value_column="y")
    except NeuralContractError as exc:
        raise ValueError(f"N-HiTS: {exc}") from exc

    config = NeuralTrainingConfig(
        seed=int(random_state), max_steps=_resolve_max_steps(),
    )

    neuralforecast_models = _require_models()
    model_cls = neuralforecast_models.NHITS
    interpolation_kwargs = _interpolation_kwargs(
        normalized["interpolation_config"],
    )

    def _factory(budget: Mapping[str, Any]):
        return model_cls(
            h=int(horizon),
            input_size=normalized["input_size"],
            alias="NHITS",
            **interpolation_kwargs,
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
        raise ValueError(f"N-HiTS: {exc}") from exc

    model_name = "NHITS"
    if model_name not in preds.columns:
        raise ValueError(
            f"N-HiTS: NeuralForecast вернул колонки {list(preds.columns)} "
            f"без точечного прогноза '{model_name}' (fail-closed)"
        )
    point = preds[model_name].to_numpy(dtype=float)
    lower = _interval_column(preds, model_name, "lo", float(plan.levels[0]))
    upper = _interval_column(preds, model_name, "hi", float(plan.levels[-1]))

    if len(point) != int(horizon):
        raise ValueError(
            f"N-HiTS: длина прогноза {len(point)} не равна horizon={int(horizon)}"
        )
    if not (np.isfinite(point).all() and np.isfinite(lower).all()
            and np.isfinite(upper).all()):
        raise ValueError(
            "N-HiTS: прогноз содержит NaN/Inf -- отказ без clamp-подмен "
            "(fail-closed)"
        )
    # Clamp-инвариант (урок НАХОДКИ-3/M10 сертификации Task 138): живой
    # гейт поверх isfinite -- fault-injection тест, а не только happy-path
    # ассерт; никаких молчаливых clamp-подмен границ.
    lower_arr = np.asarray(lower, dtype=float)
    upper_arr = np.asarray(upper, dtype=float)
    if not ((lower_arr <= point).all() and (point <= upper_arr).all()):
        raise NeuralContractError(
            "N-HiTS: нарушен инвариант lower <= point <= upper (fail-closed)"
        )

    return {
        "adapter_id": NHITS_ADAPTER_ID,
        "forecast": point,
        "lower": lower,
        "upper": upper,
        "params": dict(normalized),
        "interpolation_config": normalized["interpolation_config"],
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
            f"N-HiTS: conformal-колонка '{model_name}{suffix}' отсутствует "
            f"в отклике NeuralForecast (fail-closed)"
        )
    return preds[matches[0]].to_numpy(dtype=float)


def _require_models():
    """Ленивый импорт neuralforecast.models (единственная точка --
    neural_runtime.require_neuralforecast)."""
    from apps.api.model_impls.neural_runtime import require_neuralforecast

    return require_neuralforecast().models


def run_nhits_backtest(
    series: Sequence[float],
    train_ratio: float,
    seasonal_period: int,
):
    """Legacy synthetic-demo эндпоинт (POST /v1/models/backtest), сигнатура
    как у остальных model_impls; seasonal_period не используется
    (иерархическая интерполяция извлекает тренд/сезонность из данных
    сама).  Task 140: N-HiTS -- одномерная level-модель, однорядный
    эндпоинт ПРИМЕНИМ (прецедент lstm Task 138 / nbeats Task 139 /
    random_forest); сознательно БЕЗ safe_backtest/Naive-fallback --
    ошибку модели нельзя подменять метриками наивного прогноза."""
    y_train, y_test = train_test_split(list(series), train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)
    payload = _nhits_fit_predict(y_train, len(y_test), random_state=42)
    return compute_metrics(y_test, payload["forecast"], y_train)


__all__ = [
    "ALPHA_OPTIONS",
    "DEFAULT_PARAMS",
    "HIDDEN_SIZE_BOUNDS",
    "INPUT_SIZE_BOUNDS",
    "INTERPOLATION_OPTIONS",
    "MLP_LAYERS_BOUNDS",
    "NHITS_ADAPTER_ID",
    "NHITS_MAX_STEPS",
    "NHITS_MIN_TRAIN",
    "_interpolation_kwargs",
    "_nhits_fit_predict",
    "run_nhits_backtest",
    "validate_nhits_params",
]
