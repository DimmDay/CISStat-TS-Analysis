# apps/api/model_impls/deepar.py
"""
DeepAR -- авторегрессионная рекуррентная сеть (Amazon) на едином
NeuralForecast-runtime, ПЯТЫЙ исполнитель Neural Runtime Contract
Task 137 и ВТОРОЙ срез с probabilistic-поверхностью -- DistributionLoss
(StudentT, квантили плана; Task 142/142a, family=neural).  PANEL-
постановка: глобальная модель, обучаемая на НЕСКОЛЬКИХ рядах
одновременно (прецедент quartet'а lstm Task 138 / nbeats Task 139 /
nhits Task 140 / tft Task 141 в нейро-семействе: runtime-контракт
Task 137 НЕ меняется -- новый адаптер + запись реестра v2 + условный
dispatch + yaml).

Постановка docs/modeling_task_list.md::Tasks 138-142 (Task 142 --
DeepAR) + правило моделирования: «DeepAR активируется только для
настоящей панели с несколькими рядами; несколько числовых колонок
одного объекта не выдаются за панель» (yaml::deepar min_series=5,
правило F05).

1. **ПАНЕЛЬ -- ядро постановки**: адаптер принимает target +
   related_series (канал реестра v2; все ряды одной длины на общей
   сетке) и отказывает ДО фита, если n_series = 1 + len(related) <
   DEEPAR_MIN_SERIES (=5).  Панель собирается из РЯДОВ датасета
   (target + связанные числовые ряды, как endogenous-система Task
   131), а НЕ из feature-колонок одного объекта: future_features
   отвергаются гейтом реестра (supports_future_features=False);
   train_features реестровым гейтом для panel-модели НЕ отвергаются
   (гейт покрывает только univariate), но и НЕ потребляются адаптером
   -- честный warning даёт panel-движок через FeaturePlan (уточнение
   находки F2 пересертификации 142).  Честность панели продублирована
   контрактом Task 137 (neural_cohort_contract: n_series <
   min_series -- отказ) и panel-движком session-контура.

2. **ГЛОБАЛЬНАЯ модель -- суть DeepAR**: ОДИН фит на ВСЕЙ панели в
   long-format unique_id/ds/y через сертифицированный to_long_format
   контракта (явный series_column; NaN/Inf, дубликаты (unique_id, ds),
   нерегулярная сетка -- отказ).  Точечный прогноз payload -- медиана
   (0.5-процентиль MC-квантилей) distribution-головы ЦЕЛЕВОГО ряда
   (unique_id "series_0"; прогноз извлекается по unique_id, а не по
   позиции); missing-строки целевого ряда в отклике -- fail-closed
   (глобальная модель обязана вернуть прогноз каждой серии панели).

3. **Probabilistic-поверхность -- DistributionLoss (StudentT) -- Task
   142a** (исправление блокирующей находки F3 пересертификации 142;
   MQLoss был зарезервирован за срезами 141-142 границей Task 138 и
   использовался коллегой здесь ПЕРВОНАЧАЛЬНО): квантили декларируются
   ПРЯМО -- DistributionLoss(distribution="StudentT", quantiles=
   [alpha/2, 0.5, 1-alpha/2]) -- честный двусторонний интервал
   [alpha/2; 1-alpha/2] процентилей; план _quantile_plan
   ПЕРЕИСПОЛЬЗОВАН из tft.py (единый источник истины, НЕ дубликат);
   метод интервалов в metadata -- NeuralIntervalPlan.method=
   "neural_quantile_outputs" (нативные выходы модели, НЕ conformal);
   происхождение дисклоужено в metadata.intervals (loss="distribution",
   distribution="StudentT", trajectory_samples).
   ПОЧЕМУ НЕ MQLoss (эмпирика пересертификации, проб E1-E4 и
   task142_cert_surface_diag.py): рекуррентный predict neuralforecast
   3.2.2 (_base_model.py::_predict_step_recurrent_single) для
   не-distribution losses перезаписывает output_batch СРЕДНИМ
   квантилей (mean(dim=-1), библиотечный «Todo») ДО сохранения y_hat
   -- ВСЕ квантильные каналы отклика получают одно значение (среднее
   квантилей) -- ширина интервала тождественно 0 (находка F3:
   max|median-lo| = max|hi-median| = 0.0 бит-в-бит на любом
   бюджете/сиде/скейлере).  DistributionLoss идёт по ветке
   is_distribution_output: y_hat = concat(mean, MC-квантили) --
   раздельные значения (проб E3/E4: mean_width > 0).  MQLoss остаётся
   поверхностью ПРЯМОЙ (direct) TFT (Task 141) -- там рекуррентный
   путь не задействован.

4. **Масштаб точки -- scaler_type="robust" -- Task 142a** (второй
   механизм той же находки F3): дефолт DeepAR scaler_type="identity"
   не позволяет рекуррентному декодеру выйти на масштаб данных за
   семейный бюджет 300 шагов (Adam(1e-3) сдвигает выход ~на lr за
   шаг: проб -- прогноз ~4.3 при уровнях 103/40/12; ~4.7 на
   константной серии y=100; 21.8 при 1000 шагов).  LSTM/TFT не
   страдают -- их дефолт "robust" (per-window медиана/MAD);
   DeepAR выравнен явным scaler_type="robust" (проб E4: медиана ~109
   при хвосте ~105; |медиана-хвост| ~4 против ~100 на identity).
   Инверсия нормализации -- per-window статистики ЦЕЛЕВОГО окна
   (утечки нет: окно -- train-префикс), фидбек рекуррентного вывода
   возвращается в нормализованное пространство тем же скейлером.

5. **ЕДИНСТВЕННАЯ точка импорта torch/neuralforecast** --
   apps/api/model_impls/neural_runtime.py (лениво, fail-closed,
   NeuralRuntimeUnavailableError с установочной подсказкой; гейт
   памяти Task 138c -- ensure_neural_memory_capacity ДО импорта).
   Этот модуль torch НЕ импортирует ни на одном уровне; DistributionLoss
   и MAE -- через require_neuralforecast().losses.pytorch -- та же
   единственная точка тяжёлого импорта.  valid_loss=MAE() -- дефолт
   библиотеки для distribution-головы (валидация средним распределения;
   mirror-правило «valid_loss=MQLoss с теми же quantiles» -- только
   для mqloss-голов, конструктор 3.2.2).

6. **ds-ось -- конвенция neural-семейства ПЕРЕИСПОЛЬЗОВАНА из Task
   138** (lstm._resolve_time_axis -- единый источник истины):
   datetime + pd.infer_freq либо позиционная целочисленная сетка
   freq=1 (проб: DeepAR int-ds freq=1 OK).  ds -- только ось; НИКАКОГО
   скрытого ресемплинга/интерполяции/сортировки данных.

7. **Гейт неосуществимого окна**: n_train < input_size + horizon --
   отказ ДО фита (полностью наблюдаемое supervised-окно).
   DistributionLoss БЕЗ conformal-калибровки -- потребность +2 НЕ
   следует (прецедент tft); граница n == input_size + horizon
   исполнима (проб, секция 9).  Библиотека с
   start_padding_enabled=False согласована (проб: сырой отказ «DeepAR
   requires at least ... training timestamp(s)»); адаптерный гейт даёт
   детерминированное сообщение до затрат на fit.  Конструктор 3.2.2
   хранит input_size+1 (внутренний сдвиг авторегрессии) -- прижат
   spy-тестом.  DEEPAR_MIN_TRAIN=30 (семейный пол; каталоговский мягкий
   порог 200 -- раньше, readiness-гейтом F04).

8. **Clamp-инвариант с первого дня** (урок НАХОДКИ-3/M10 сертификации
   Task 138): lower <= median <= upper -- живой гейт поверх isfinite,
   закреплённый fault-injection тестом; для MC-квантилей StudentT
   порядок гарантирован сортировкой выборки, гейт -- defense-in-depth
   (пересечение -- честный отказ fold'а вместо clamp-подмен).

9. **Fail-closed**: короткий train, NaN/Inf (в ЛЮБОЙ серии панели),
   короче-длиннее related-ряды, alpha вне whitelist, значения вне
   bounded-границ, bool-коэрция целочисленных ручек (урок НАХОДКИ-2/
   M6) -- отказ fold'а БЕЗ Naive-fallback и clamp-подмен.

10. **Детерминизм**: random_state реестра -> NeuralTrainingConfig.seed
    -> fold_seed -> random_seed КОНСТРУКТОРА модели (ресертификация
    Task 137); MC-сэмплирование квантилей на predict детерминировано
    перезапуском сида (torch.manual_seed в predict-пути) -- same-seed
    бит-паритет (проб/оракул e03), другой seed -- другой прогноз.

11. **Бюджет -- константа модуля** DEEPAR_MAX_STEPS (семейная
    конвенция 300 -- как lstm/nbeats/nhits/tft) + env-рычаг слабых
    инстансов CISSTAT_NEURAL_MAX_STEPS (паттерн Task 138c/139/140/141;
    дефолт env не задана -- сертифицированная константа).  Тюнинг
    бюджета -- вне param_space обоснованно (прецедент Task 136);
    константа прижата анти-тампер тестом к [100, NEURAL_MAX_STEPS_BOUND].
    Траекторный бюджет MC-квантилей -- константа DEEPAR_TRAJECTORY_SAMPLES
    (1000 -- дефолт DistributionLoss.sample; стабильность хвостов 0.5%
    процентиля alpha=0.01 против дефолтных 100 траекторий модели).

Exogenous-канал (cat/hist/futr/stat lists в поверхности конструктора)
в реестре НЕ декларирован (supports_future_features=False; exog-канал
нейро-моделей -- отдельная постановка, прецедент lstm/tft).
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from apps.api.model_impls._common import train_test_split
from apps.api.model_impls._metrics import compute_metrics
from apps.api.model_impls.lstm import _resolve_time_axis
# Единый источник истины probabilistic-плана (конвенция Task 141):
# план квантилей DeepAR -- ТОТ ЖЕ контрактный construction, что у TFT.
from apps.api.model_impls.tft import _quantile_plan
from apps.api.neural_contract import (
    NeuralContractError,
    NeuralRuntimeCapacityError,
    NeuralTrainingConfig,
    resolve_probabilistic_loss,
)
from apps.api.model_impls.neural_runtime import train_and_forecast
from apps.api.schemas import BacktestMetrics

DEEPAR_ADAPTER_ID = "neuralforecast-deepar"

#: Минимальный размер ПАНЕЛИ (правило моделирования Task 142:
#: «DeepAR активируется только для настоящей панели»; yaml::deepar
#: min_series=5, правило F05).
DEEPAR_MIN_SERIES = 5

#: Ключ probabilistic-поверхности в whitelist'е контракта Task 137
#: (NEURAL_ALLOWED_LOSSES/NEURAL_PROBABILISTIC_LOSSES) и в
#: metadata.intervals: параметрическая distribution-голова (Task 142a:
#: исправление F3 -- MQLoss вырожден на рекуррентном выводе 3.2.2).
#: Единый источник истины ключа: контрактный гейт адаптера,
#: metadata payload'а и session-контекст (_panel_neural_context).
DEEPAR_LOSS_KEY = "distribution"

#: Траекторный бюджет MC-квантилей DistributionLoss на predict
#: (DeepAR trajectory_samples): 1000 -- дефолт DistributionLoss.sample;
#: стабилизирует хвостовые MC-процентили alpha=0.01 (0.5% процентиль
#: из 100 траекторий -- шумный порядок-статистик; детерминизм сида
#: сохраняется).  Прижат wiring-оракулом d01.
DEEPAR_TRAJECTORY_SAMPLES = 1000

#: Минимальная длина train-среза fold'а (честный минимум нейро-фита;
#: мягкий порог применимости каталога min_observations=200 применяется
#: readiness-гейтом РАНЬШЕ -- как у lstm/nbeats/nhits/tft: gate 30 /
#: каталог 200).
DEEPAR_MIN_TRAIN = 30

#: Единый бюджет обучения fold'а (max_steps NeuralForecast 3.x); семейная
#: конвенция 300 (lstm/nbeats/nhits/tft); прижат анти-тампер тестом к
#: [100, NEURAL_MAX_STEPS_BOUND].
DEEPAR_MAX_STEPS = 300

#: Bounded-границы гиперпараметров (вне тюнинга тоже не могут быть
#: нарушены -- fail-closed).
LSTM_HIDDEN_SIZE_BOUNDS = (8, 128)
INPUT_SIZE_BOUNDS = (8, 104)

#: Уровни интервалов -- конвенция платформы (как у всего нейро-семейства).
ALPHA_OPTIONS = (0.01, 0.05, 0.10)

DEFAULT_PARAMS: dict[str, Any] = {
    "lstm_hidden_size": 32,
    "input_size": 24,
    "alpha": 0.05,
}

_PARAM_KEYS = ("lstm_hidden_size", "input_size", "alpha")

_TARGET_UNIQUE_ID = "series_0"


def _resolve_max_steps() -> int:
    """Бюджет обучения fold'а: CISSTAT_NEURAL_MAX_STEPS или константа 300.

    Паттерн Task 138c/139/140/141: пустая env (дефолт) -- сертифицированная
    семантика семейства; задана -- целое >= 1; мусор -- ValueError
    (fail-closed, стиль локальной валидации адаптера)."""
    raw = os.environ.get("CISSTAT_NEURAL_MAX_STEPS", "").strip()
    if not raw:
        return DEEPAR_MAX_STEPS
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"DeepAR: CISSTAT_NEURAL_MAX_STEPS={raw!r} не целое >= 1 "
            "(fail-closed)"
        ) from exc
    if value < 1:
        raise ValueError(
            f"DeepAR: CISSTAT_NEURAL_MAX_STEPS={raw!r} не целое >= 1 "
            "(fail-closed)"
        )
    return value


def validate_deepar_params(params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Нормализовать и провалидировать гиперпараметры DeepAR (fail-closed).

    Неизвестные ключи игнорируются -- соглашение платформы (в params
    приходят чужие ключи, см. backtesting.py::run_backtest_plan).
    """
    merged = {
        **DEFAULT_PARAMS,
        **{k: v for k, v in dict(params or {}).items() if k in _PARAM_KEYS},
    }
    normalized: dict[str, Any] = {}

    for key in ("lstm_hidden_size", "input_size"):
        value = merged[key]
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise ValueError(
                f"DeepAR param '{key}': ожидался целочисленный аргумент, "
                f"получено {value!r}"
            )
        low, high = {
            "lstm_hidden_size": LSTM_HIDDEN_SIZE_BOUNDS,
            "input_size": INPUT_SIZE_BOUNDS,
        }[key]
        number = int(value)
        if not low <= number <= high:
            raise ValueError(
                f"DeepAR param '{key}'={number} вне bounded диапазона "
                f"[{low}, {high}]"
            )
        normalized[key] = number

    alpha = merged["alpha"]
    try:
        alpha_value = float(alpha)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"DeepAR param 'alpha'={alpha!r} не числовой") from exc
    if alpha_value not in ALPHA_OPTIONS:
        raise ValueError(
            f"DeepAR param 'alpha'={alpha_value} вне допустимого набора "
            f"{sorted(ALPHA_OPTIONS)}"
        )
    normalized["alpha"] = alpha_value
    return normalized


def _validated_series(name: str, values: Sequence[float]) -> np.ndarray:
    vector = np.asarray([float(value) for value in values], dtype=float)
    if vector.size == 0:
        raise ValueError(f"DeepAR: серия '{name}' пуста")
    if not np.isfinite(vector).all():
        raise ValueError(
            "DeepAR: панель содержит NaN/Inf -- импутация запрещена "
            "(fail-closed)"
        )
    return vector


def _panel_frame(
    target: Sequence[float],
    related_series: Mapping[str, Sequence[float]],
) -> tuple[pd.DataFrame, int]:
    """Собирает широкую панель (series/ds/y) для сертифицированного
    to_long_format: target -> "series_0", related в ПОРЯДКЕ ОБЪЯВЛЕНИЯ
    -> "series_<i+1>" (позиционные id -- без коллизий имён колонок)."""
    target_vector = _validated_series("series_0", target)
    nobs = int(target_vector.size)
    frames = [
        pd.DataFrame({
            "series": _TARGET_UNIQUE_ID,
            "y": target_vector,
        })
    ]
    for position, (name, values) in enumerate(related_series.items(), start=1):
        unique_id = f"series_{position}"
        vector = _validated_series(unique_id, values)
        if vector.size != nobs:
            raise ValueError(
                f"DeepAR: related-ряд '{name}' длины {vector.size} не "
                f"совпадает с длиной target {nobs}; панель -- общая "
                "регулярная сетка (fail-closed)"
            )
        frames.append(pd.DataFrame({
            "series": unique_id,
            "y": vector,
        }))
    return pd.concat(frames, ignore_index=True), nobs


def _deepar_fit_predict(
    target: Sequence[float],
    horizon: int,
    *,
    related_series: Optional[Mapping[str, Sequence[float]]] = None,
    params: Optional[Mapping[str, Any]] = None,
    random_state: int = 42,
    timestamps: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Fit/forecast DeepAR на train-срезе ПАНЕЛИ.

    ``related_series`` -- связанные ряды панели (target + related --
    глобальная обучающая выборка DeepAR).  Возвращает payload:
    ``forecast`` -- точечный прогноз ЦЕЛЕВОГО ряда (horizon,) = медиана
    MQLoss unique_id "series_0"; ``lower``/``upper`` -- нативные
    квантильные границы уровня ``alpha`` (probabilistic-поверхность);
    ``n_series``/``panel_ids`` -- честная панельная фактура;
    ``params``/``freq``/``intervals`` -- вход диагностики и metadata
    executor'а.  random_state принят по контракту реестра: детерминизм
    -- сид доходит до КОНСТРУКТОРА модели (ресертификация Task 137).
    """
    if int(horizon) < 1:
        raise ValueError(
            f"DeepAR: horizon должен быть положительным, получено {horizon!r}"
        )
    normalized = validate_deepar_params(params)
    related = dict(related_series or {})

    # ── ПАНЕЛЬ -- ядро постановки Task 142 ──────────────────────────────
    n_series = 1 + len(related)
    if n_series < DEEPAR_MIN_SERIES:
        raise ValueError(
            f"DeepAR: требуется панель из min_series={DEEPAR_MIN_SERIES} "
            f"рядов, доступно n_series={n_series} (target + related); "
            "одиночный ряд и несколько числовых колонок одного объекта "
            "не выдаются за панель (честность Task 142, fail-closed)"
        )

    panel_wide, nobs = _panel_frame(target, related)
    if nobs < DEEPAR_MIN_TRAIN:
        raise ValueError(
            f"DeepAR: история слишком короткая ({nobs} точек); минимум "
            f"{DEEPAR_MIN_TRAIN} (DEEPAR_MIN_TRAIN адаптера Task 142)"
        )
    if nobs < normalized["input_size"] + int(horizon):
        raise ValueError(
            f"DeepAR: неосуществимое окно ({nobs} точек < input_size="
            f"{normalized['input_size']} + horizon={int(horizon)}); "
            "молчаливое ужатие/паддинг окна запрещены (fail-closed)"
        )

    ds, freq = _resolve_time_axis(timestamps, nobs)
    panel_wide["ds"] = list(ds) * n_series
    from apps.api.neural_contract import to_long_format

    try:
        long = to_long_format(panel_wide, value_column="y",
                              time_column="ds", series_column="series")
    except NeuralContractError as exc:
        raise ValueError(f"DeepAR: {exc}") from exc

    config = NeuralTrainingConfig(
        seed=int(random_state), max_steps=_resolve_max_steps(),
    )

    plan = _quantile_plan(normalized["alpha"])
    # Контрактный гейт Task 137: probabilistic-функция потерь требует
    # объявленного плана уровней (NEURAL_PROBABILISTIC_LOSSES;
    # Task 142a: ключ DEEPAR_LOSS_KEY -- distribution-голова).
    resolve_probabilistic_loss(DEEPAR_LOSS_KEY, levels=plan["levels"])

    nf_module = _require_neuralforecast()
    model_cls = nf_module.models.DeepAR
    distribution_loss_cls = nf_module.losses.pytorch.DistributionLoss
    mae_cls = nf_module.losses.pytorch.MAE

    def _factory(budget: Mapping[str, Any]):
        quantiles = list(plan["quantiles"])
        return model_cls(
            h=int(horizon),
            input_size=normalized["input_size"],
            lstm_hidden_size=normalized["lstm_hidden_size"],
            alias="DeepAR",
            # Task 142a (исправление F3): голова -- DistributionLoss
            # (StudentT, квантили плана) -- честный двусторонний интервал;
            # MQLoss на рекуррентном выводе 3.2.2 вырожден (все
            # квантильные каналы = среднему квантилей, ширина 0 -- проб
            # E1/E2).  valid_loss=MAE -- дефолт библиотеки для
            # distribution-голов.  scaler_type="robust" -- семейная
            # конвенция lstm/tft: без per-window нормализации декодер
            # не выходит на масштаб данных за бюджет 300 шагов (проб
            # E1/E3/E4).  trajectory_samples -- стабильность хвостов
            # MC-квантилей (alpha=0.01).
            loss=distribution_loss_cls(
                distribution="StudentT", quantiles=quantiles,
            ),
            valid_loss=mae_cls(),
            scaler_type="robust",
            trajectory_samples=DEEPAR_TRAJECTORY_SAMPLES,
            **dict(budget),
        )

    try:
        # levels=() -- conformal-контур НЕ активируется: квантильные
        # выходы нативны loss=DistributionLoss (PredictionIntervals
        # не нужен).
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
        raise ValueError(f"DeepAR: {exc}") from exc

    rows = _target_rows(preds, int(horizon))
    width = _width_suffix(rows)
    point = _median_column(rows)
    lower = _quantile_column(rows, "lo", width)
    upper = _quantile_column(rows, "hi", width)

    if not (np.isfinite(point).all() and np.isfinite(lower).all()
            and np.isfinite(upper).all()):
        raise ValueError(
            "DeepAR: прогноз содержит NaN/Inf -- отказ без clamp-подмен "
            "(fail-closed)"
        )
    # Clamp-инвариант (урок НАХОДКИ-3/M10 сертификации Task 138): живой
    # гейт поверх isfinite -- defense-in-depth поверх MC-квантилей
    # StudentT (порядок гарантирован сортировкой выборки);
    # fault-injection тест, а не только happy-path ассерт; никаких
    # молчаливых clamp-подмен границ.
    lower_arr = np.asarray(lower, dtype=float)
    upper_arr = np.asarray(upper, dtype=float)
    point_arr = np.asarray(point, dtype=float)
    if not ((lower_arr <= point_arr).all() and (point_arr <= upper_arr).all()):
        raise NeuralContractError(
            "DeepAR: нарушен инвариант lower <= point <= upper "
            "(квантильное пересечение MQLoss; fail-closed)"
        )

    return {
        "adapter_id": DEEPAR_ADAPTER_ID,
        "forecast": point,
        "lower": lower,
        "upper": upper,
        "params": dict(normalized),
        "nobs": int(nobs),
        "n_series": int(n_series),
        "panel_ids": [f"series_{index}" for index in range(n_series)],
        "max_steps": int(config.max_steps),
        "seed": int(config.seed),
        "freq": (
            {"kind": "datetime", "value": str(freq)}
            if isinstance(freq, str) else {"kind": "integer", "value": 1}
        ),
        "intervals": {
            "method": "neural_quantile_outputs",
            "loss": DEEPAR_LOSS_KEY,
            "distribution": "StudentT",
            "trajectory_samples": int(DEEPAR_TRAJECTORY_SAMPLES),
            "alpha": float(normalized["alpha"]),
            "quantiles": [float(q) for q in plan["quantiles"]],
            "levels": [float(level) for level in plan["levels"]],
        },
        "random_state": int(random_state),
        "deterministic": True,
    }


def _target_rows(preds: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Строки отклика ЦЕЛЕВОГО ряда (unique_id "series_0"), упорядоченные
    по ds (детерминированный порядок горизонта)."""
    if "unique_id" not in preds.columns:
        raise ValueError(
            "DeepAR: отклик NeuralForecast без колонки unique_id "
            "(panel-прогноз; fail-closed)"
        )
    rows = preds[preds["unique_id"].astype(str) == _TARGET_UNIQUE_ID]
    if len(rows) != horizon:
        raise ValueError(
            f"DeepAR: глобальная модель вернула {len(rows)} строк для "
            f"целевой серии вместо horizon={horizon} -- прогноз каждой "
            "серии панели обязателен (fail-closed)"
        )
    return rows.sort_values("ds", kind="stable").reset_index(drop=True)


def _median_column(rows: pd.DataFrame) -> np.ndarray:
    """Точечный прогноз DeepAR -- медиана (колонка 'DeepAR-median')
    distribution-головы (0.5-процентиль MC-квантилей; Task 142a).

    При probabilistic-loss NeuralForecast НЕ возвращает bare-колонку
    'DeepAR' как точку адаптера (проб; bare-колонка DistributionLoss --
    среднее распределения, точкой платформы служит медиана); отсутствие
    медианы -- fail-closed."""
    if "DeepAR-median" not in rows.columns:
        raise ValueError(
            f"DeepAR: NeuralForecast вернул колонки {list(rows.columns)} "
            "без медианы 'DeepAR-median' (probabilistic-поверхность "
            "MQLoss; fail-closed)"
        )
    return rows["DeepAR-median"].to_numpy(dtype=float)


def _width_suffix(rows: pd.DataFrame) -> float:
    """Ширина суффикса квантильных колонок отклика ('DeepAR-lo-<w>').

    Width-семантика НАХОДКИ Task 141 п.2; отсутствие квантильных колонок
    -- fail-closed (probabilistic-поверхность обязана вернуть обе
    границы)."""
    for column in rows.columns:
        name = str(column)
        if name.startswith("DeepAR-lo-"):
            return float(name.rsplit("-", 1)[-1])
    raise ValueError(
        "DeepAR: квантильные колонки 'DeepAR-lo-<w>' отсутствуют в "
        "отклике NeuralForecast (fail-closed)"
    )


def _quantile_column(
    rows: pd.DataFrame, side: str, width: float,
) -> np.ndarray:
    """Квантильная граница ЦЕЛЕВОГО ряда по суффиксу ширины
    ('-lo-<w>'/'-hi-<w>'; width-семантика НАХОДКИ Task 141 п.2).

    Суффикс кодирует ШИРИНУ интервала (конвенция quantiles_to_outputs
    round(100-200*q, 2)); поиск по endswith -- fail-closed к
    переименованию формата."""
    suffix = f"-{side}-{width}"
    matches = [column for column in rows.columns
               if str(column).endswith(suffix)]
    if not matches:
        raise ValueError(
            f"DeepAR: квантильная колонка 'DeepAR{suffix}' отсутствует "
            "в отклике NeuralForecast (fail-closed)"
        )
    return rows[matches[0]].to_numpy(dtype=float)


def _require_neuralforecast():
    """Ленивый импорт neuralforecast (единственная точка --
    neural_runtime.require_neuralforecast): модели + losses.pytorch
    (DistributionLoss/MAE) -- одна и та же точка тяжёлого импорта
    платформы."""
    from apps.api.model_impls.neural_runtime import require_neuralforecast

    return require_neuralforecast()


def run_deepar_backtest(
    series: Sequence[float],
    train_ratio: float,
    seasonal_period: int,
):
    """Legacy synthetic-demo эндпоинт (POST /v1/models/backtest), сигнатура
    как у остальных model_impls.  Task 142: DeepAR -- panel-постановка
    (min_series=5) -- на одиночном синтетическом ряде исполнение
    НЕВОЗМОЖНО без подмены.  Никаких синтетических панельных демо и
    Naive-fallback: честный отказ (ValueError), прецедент var/vecm."""
    raise ValueError(
        "DeepAR требует панель из не менее 5 рядов (target + related_series); "
        "однорядный synthetic-эндпоинт не применим -- исполняйте DeepAR "
        "через panel-движок session backtest (run_panel_backtest_plan)"
    )


__all__ = [
    "ALPHA_OPTIONS",
    "DEFAULT_PARAMS",
    "DEEPAR_ADAPTER_ID",
    "DEEPAR_LOSS_KEY",
    "DEEPAR_MAX_STEPS",
    "DEEPAR_MIN_SERIES",
    "DEEPAR_MIN_TRAIN",
    "DEEPAR_TRAJECTORY_SAMPLES",
    "INPUT_SIZE_BOUNDS",
    "LSTM_HIDDEN_SIZE_BOUNDS",
    "_quantile_plan",
    "_deepar_fit_predict",
    "_resolve_max_steps",
    "run_deepar_backtest",
    "validate_deepar_params",
]
