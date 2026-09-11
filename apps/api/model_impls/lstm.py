# apps/api/model_impls/lstm.py
"""
LSTM/GRU -- рекуррентные сети на едином NeuralForecast-runtime (Task 138,
family=neural).  Первый исполнитель Neural Runtime Contract Task 137.

Постановка docs/modeling_task_list.md::Task 138 («Task 138 -- LSTM/GRU»)
+ требования Task 137 (единый long-format unique_id/ds/y, exogenous-
контракт, seed/бюджет, честные интервалы).  Каталог rules/modeling.yaml
декларирует id="lstm", name="LSTM / GRU": «LSTM -- долгие зависимости;
GRU -- легковесная альтернатива», поэтому ядро среза -- АРХИТЕКТУРНЫЙ
ВЫБОР ячейки (cell ∈ {lstm, gru}) как bounded tuning-параметр на ОДНОМ
runtime (прецедент каркас -> исполнитель: volatility-контракт Task 134 ->
GARCH/EGARCH; нейро-контракт Task 137 -> LSTM/GRU).

1. **Единый runtime, без собственной的训练 петли**: fit/predict --
   только apps/api/model_impls/neural_runtime.py::train_and_forecast
   (бюджет max_steps, явный accelerator, early_stop_patience_steps,
   random_seed=fold_seed в КОНСТРУКТОРЕ модели -- seed-дисциплина
   ресертификации Task 137).  Этот модуль не импортирует torch
   напрямую: единственная точка тяжёлых импортов -- neural_runtime.

2. **Временная ось -- реальная, регулярная**: train_timestamps
   обязательны (прецедент prophet); частота -- validate_regular_grid
   сертифицированного контракта Task 131 (ЕДИНЫЙ источник истины
   регулярной сетки; та же функция переиспользована
   neural_contract.validate_long_format).  Нерегулярная сетка,
   дубликаты дат, row-order метки -- честный отказ: нейро-модель
   строит окна по равноотстоящей сетке, скрытая регуляризация
   запрещена.

3. **Exogenous -- granted-канал Task 126 -> futr-роль контракта
   Task 137**: будущие-known/static колонки приходят парой
   (train_features -- срез train, future_features -- срез горизонта);
   они объявляются в NeuralExogenousPlan РОЛЬЮ futr (hist/stat явно
   пустые -- решения не прячутся: исторические target-derived колонки
   не проходят capability-гейт платформы, а платформенные static
   приходят как timestamped числовые ряды, поэтому futr сохраняет
   полную информацию; stat_exog со скрытой агрегацией «первое
   значение» запрещён).  Роль объявляется вызовом build_exogenous_plan
   -- никакого угадывания (паритет с keyword-выборами Task 134).

4. **Интервалы -- сертифицированный conformal-путь** (Task 137):
   point-loss (MAE) + fit(prediction_intervals=PredictionIntervals())
   + predict(level=...); уровни -- interval_levels_for_alpha(alpha)
   (0.05 -> 2.5/50/97.5).  Семантика conformal-колонок neuralforecast
   снята ЭМПИРИЧЕСКИ (проб scripts/task138_neural_api_probe.py):
   lo-L = point - q(L/100), hi-L = point + q(L/100), где q(p) -- p-квантиль
   |остатков| conformal-окон; L монотонен.  Двусторонний (1-alpha)-интервал
   (нижняя alpha/2-квантиль, верхняя 1-alpha/2) => ОБЕ границы на уровне
   L = 100*(1 - alpha/2) = levels[-1] плана контракта: lo-97.5 = alpha/2-
   квантиль, hi-97.5 = 1-alpha/2-квантиль (для alpha=0.05).  MQLoss в 3.2.2
   рабочий (проб Task 137), но для level-среза выбран point-loss +
   conformal: точка -- прямой выход сети, интервал -- conformal-квантили;
   probabilistic-пути остаются поверхностью контракта для срезов 139-142.

5. **Fail-closed**: никаких Naive-fallback и синтетических подмен.
   Короткая история (< LSTM_MIN_TRAIN), неосуществимое окно
   (n_train <= input_size + horizon), NaN/Inf в ряде и регрессорах,
   коллизия имён регрессоров с сервисными колонками long-format,
   несоответствие train/future-набора регрессоров, bare-ряд legacy
   synthetic-эндпоинта без временной оси -- ошибка fold'а
   (BacktestExecutionError на движке).

Bounded params (fail-closed, см. PARAM_BOUNDS и rules/modeling.yaml):
cell (lstm/gru), input_size (4..128), encoder_hidden_size (8..256),
encoder_n_layers (1..3), encoder_dropout (0..0.5), learning_rate
(1e-4..0.1), max_steps (1..10000 -- граница контракта Task 137),
alpha {0.01, 0.05, 0.10} -- как у VAR/GARCH/EGARCH.  В tuning-пространство
yaml вынесены только 4 архитектурно-бюджетных ручки (16 trials <= 64);
остальные -- валидируемые константы с явными границами.

Детерминизм: seed=random_state -> NeuralTrainingConfig.seed ->
fold_seed -> random_seed конструктора neuralforecast (ресертификация
Task 137: BaseModel перезасеивает ран в __init__) + seed_neural_runtime
до конструирования (defense-in-depth).  Одинаковый random_state -- бит-в-
бит одинаковый прогноз, другой -- другой (дифференциальные тесты).
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from apps.api.neural_contract import (
    NEURAL_CONTRACT_VERSION,
    NEURAL_RUNTIME,
    NeuralContractError,
    NeuralExogenousPlan,
    NeuralTrainingConfig,
    build_exogenous_plan,
    interval_levels_for_alpha,
    to_long_format,
    validate_future_exogenous_frame,
    validate_long_format,
)
from apps.api.model_impls.neural_runtime import (
    train_and_forecast,
)

LSTM_ADAPTER_ID = "neuralforecast-lstm"

#: Абсолютный минимум train-среза для честного рекуррентного обучения.
#: Окно/горизонт проверяются ОТДЕЛЬНО (n_train > input_size + horizon):
#: эта граница отсекает вырожденно короткие ряды независимо от params.
LSTM_MIN_TRAIN = 32

#: Сервисные колонки long-format (Task 137); имя регрессора не имеет права
#: с ними сталкиваться -- to_long_format молча перезаписал бы target.
_SERVICE_COLUMNS = frozenset({"unique_id", "ds", "y"})

#: Нормализованные дефолты + строгие границы (bounded param_space вне
#: тюнинга тоже не может выйти за границы -- fail-closed).
DEFAULT_PARAMS: dict[str, Any] = {
    "cell": "lstm",
    "input_size": 24,
    "encoder_hidden_size": 32,
    "encoder_n_layers": 1,
    "encoder_dropout": 0.0,
    "learning_rate": 0.01,
    "max_steps": 200,
    "alpha": 0.05,
}
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "input_size": (4, 128),
    "encoder_hidden_size": (8, 256),
    "encoder_n_layers": (1, 3),
    "encoder_dropout": (0.0, 0.5),
    "learning_rate": (1e-4, 0.1),
    "max_steps": (1, 10_000),  # NEURAL_MAX_STEPS_BOUND контракта Task 137
}
CELL_OPTIONS = {"lstm", "gru"}
ALPHA_OPTIONS = {0.01, 0.05, 0.10}

_PARAM_KEYS = (
    "cell", "input_size", "encoder_hidden_size", "encoder_n_layers",
    "encoder_dropout", "learning_rate", "max_steps", "alpha",
)

_INT_PARAMS = ("input_size", "encoder_hidden_size", "encoder_n_layers", "max_steps")


def validate_lstm_params(params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Нормализовать и провалидировать гиперпараметры LSTM/GRU (fail-closed).

    Неизвестные ключи игнорируются -- соглашение платформы (в params всегда
    приходят чужие ключи вроде tbats_seasonal_periods, см.
    backtesting.py::run_backtest_plan).  bool явно отклоняется для
    целочисленных ручек (bool -- подкласс int, True->1 -- скрытая коэрция).
    """
    merged = {
        **DEFAULT_PARAMS,
        **{k: v for k, v in dict(params or {}).items() if k in _PARAM_KEYS},
    }
    normalized: dict[str, Any] = {}

    cell = merged["cell"]
    if cell not in CELL_OPTIONS:
        raise ValueError(
            f"LSTM param 'cell'={cell!r} вне допустимого набора "
            f"{sorted(CELL_OPTIONS)} (ядро Task 138: LSTM/GRU на одном runtime)"
        )
    normalized["cell"] = str(cell)

    for key in _INT_PARAMS:
        value = merged[key]
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise ValueError(
                f"LSTM param '{key}': ожидался целочисленный аргумент, "
                f"получено {value!r}"
            )
        number = int(value)
        low, high = PARAM_BOUNDS[key]
        if not low <= number <= high:
            raise ValueError(
                f"LSTM param '{key}'={number} вне bounded диапазона [{low}, {high}]"
            )
        normalized[key] = number

    dropout = merged["encoder_dropout"]
    if isinstance(dropout, bool) or not isinstance(dropout, (int, float, np.floating)):
        raise ValueError(
            f"LSTM param 'encoder_dropout'={dropout!r} не числовой"
        )
    dropout = float(dropout)
    low, high = PARAM_BOUNDS["encoder_dropout"]
    if not low <= dropout <= high:
        raise ValueError(
            f"LSTM param 'encoder_dropout'={dropout} вне bounded диапазона "
            f"[{low}, {high}]"
        )
    normalized["encoder_dropout"] = dropout

    learning_rate = merged["learning_rate"]
    if isinstance(learning_rate, bool) or not isinstance(
        learning_rate, (int, float, np.floating),
    ):
        raise ValueError(
            f"LSTM param 'learning_rate'={learning_rate!r} не числовой"
        )
    learning_rate = float(learning_rate)
    low, high = PARAM_BOUNDS["learning_rate"]
    if not low <= learning_rate <= high:
        raise ValueError(
            f"LSTM param 'learning_rate'={learning_rate} вне bounded диапазона "
            f"[{low}, {high}]"
        )
    normalized["learning_rate"] = learning_rate

    alpha = merged["alpha"]
    try:
        alpha_value = float(alpha)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"LSTM param 'alpha'={alpha!r} не числовой") from exc
    if alpha_value not in ALPHA_OPTIONS:
        raise ValueError(
            f"LSTM param 'alpha'={alpha_value} вне допустимого набора "
            f"{sorted(ALPHA_OPTIONS)}"
        )
    normalized["alpha"] = alpha_value
    return normalized


def _validated_target(target: Sequence[float]) -> np.ndarray:
    vector = np.asarray([float(value) for value in target], dtype=float)
    if vector.size == 0:
        raise ValueError("LSTM: train fold пуст")
    if not np.isfinite(vector).all():
        raise ValueError(
            "LSTM: target содержит NaN/Inf -- импутация запрещена (fail-closed)"
        )
    return vector


def _validated_timestamps(
    timestamps: Optional[Sequence[str]], *, field_name: str,
) -> list[pd.Timestamp]:
    """Реальная временная ось: нераспознанные метки -- честный отказ
    (контракт не выполняет скрытую коэрцию row-order в даты)."""
    if timestamps is None or len(timestamps) == 0:
        raise ValueError(
            f"LSTM: {field_name} обязательны: нейро-модель строит окна по "
            "равноотстоящей сетке; row-order метки частоту не дают "
            "(прецедент prophet -- строгий future-known contract)"
        )
    from app.data.detectors import smart_to_datetime

    converted = smart_to_datetime(pd.Series(list(timestamps)))
    if converted.isna().any():
        raise ValueError(
            f"LSTM: {field_name} содержат нераспознанные даты; контракт не "
            "выполняет скрытую коэрцию"
        )
    return [pd.Timestamp(value) for value in converted]


def _frequency_from_grid(timestamps: Sequence[pd.Timestamp]) -> str:
    """Частота сетки -- validate_regular_grid контракта Task 131
    (единый источник истины; нерегулярная сетка/дубликаты -- отказ)."""
    from apps.api.multivariate_contract import (
        MultivariateContractError,
        validate_regular_grid,
    )

    try:
        grid = validate_regular_grid(
            [value.isoformat() for value in timestamps]
        )
    except MultivariateContractError as exc:
        raise ValueError(f"LSTM: {exc}") from exc
    return str(grid["frequency"])


def _build_exogenous_context(
    *,
    train_features: Optional[Mapping[str, Sequence[float]]],
    future_features: Optional[Mapping[str, Sequence[float]]],
    n_train: int,
    horizon: int,
) -> tuple[list[str], Optional[pd.DataFrame]]:
    """Granted-канал Task 126 -> futr-план контракта Task 137.

    Возвращает (имена-регрессоры, futr_df для predict).  Fail-closed:
    набор регрессоров обязан быть симметричным (train<->future), длины --
    точными, имена -- вне сервисных колонок long-format.
    """
    train_features = dict(train_features or {})
    future_features = dict(future_features or {})
    if not train_features and not future_features:
        return [], None

    train_names = set(train_features)
    future_names = set(future_features)
    if train_names != future_names:
        only_train = sorted(train_names - future_names)
        only_future = sorted(future_names - train_names)
        raise ValueError(
            "LSTM: regressor-канал несимметричен: train_features="
            f"{sorted(train_names)}, future_features={sorted(future_names)} "
            f"(только в train: {only_train}; только в future: {only_future}); "
            "granted-канал Task 126 обязан дать train-срез и срез горизонта"
        )
    collision = sorted(train_names & _SERVICE_COLUMNS)
    if collision:
        raise ValueError(
            f"LSTM: имена регрессоров {collision} сталкиваются со служебными "
            "колонками long-format {unique_id, ds, y} -- переименуйте колонку "
            "на стороне FeaturePlan"
        )
    for name, column in train_features.items():
        if len(column) != n_train:
            raise ValueError(
                f"LSTM: train_features['{name}']: длина {len(column)} != {n_train}"
            )
    for name, column in future_features.items():
        if len(column) != horizon:
            raise ValueError(
                f"LSTM: future_features['{name}']: длина {len(column)} != "
                f"{horizon} (покрытие горизонта неполное)"
            )
    names = sorted(train_names)
    return names, None  # futr_df строит вызывающая сторона (нужны future ds)


def _lstm_fit_predict(
    target: Sequence[float],
    horizon: int,
    *,
    params: Optional[Mapping[str, Any]] = None,
    random_state: int = 42,
    train_features: Optional[Mapping[str, Sequence[float]]] = None,
    future_features: Optional[Mapping[str, Sequence[float]]] = None,
    train_timestamps: Optional[Sequence[str]] = None,
    future_timestamps: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """LSTM/GRU fit/forecast на едином NeuralForecast-runtime (Task 137).

    Возвращает payload: ``forecast`` -- точечный прогноз (horizon,);
    ``lower``/``upper`` -- conformal-интервал на уровне ``alpha``
    (interval_levels_for_alpha); ``exogenous_plan`` -- подписанный план
    Task 137; ``neural`` -- конфиг обучения/версии runtime.  Детерминизм:
    random_state -> NeuralTrainingConfig.seed -> fold_seed -> конструктор
    модели (ресертификация Task 137); одинаковый seed -- бит-в-бит.
    """
    if int(horizon) < 1:
        raise ValueError(
            f"LSTM: horizon должен быть положительным, получено {horizon!r}"
        )
    normalized = validate_lstm_params(params)
    vector = _validated_target(target)
    n_train = int(vector.size)
    if n_train < LSTM_MIN_TRAIN:
        raise ValueError(
            f"LSTM: история слишком короткая ({n_train} наблюдений); минимум "
            f"{LSTM_MIN_TRAIN} (рекуррентное обучение на меньшем -- не честный "
            "прогноз, а шум)"
        )
    input_size = int(normalized["input_size"])
    if n_train <= input_size + int(horizon):
        raise ValueError(
            "LSTM: неосуществимое окно для истории: n_train "
            f"({n_train}) <= input_size ({input_size}) + horizon ({horizon}); "
            "ни одного полного учебного окна -- ужать окно молча контракт "
            "не может (fail-closed)"
        )

    train_ds = _validated_timestamps(
        train_timestamps, field_name="train_timestamps",
    )
    if len(train_ds) != n_train:
        raise ValueError(
            f"LSTM: train_timestamps: длина {len(train_ds)} != {n_train}"
        )
    freq = _frequency_from_grid(train_ds)

    feature_names, _ = _build_exogenous_context(
        train_features=train_features,
        future_features=future_features,
        n_train=n_train,
        horizon=int(horizon),
    )

    frame = pd.DataFrame({"ds": pd.DatetimeIndex(train_ds), "y": vector})
    for name in feature_names:
        frame[name] = [
            float(value) for value in train_features[name]  # type: ignore[index]
        ]
    long_frame = to_long_format(
        frame, value_column="y", time_column="ds", keep_columns=feature_names,
    )
    summary = validate_long_format(long_frame)
    if summary["n_series"] != 1:  # pragma: no cover -- level-срез одномерный
        raise NeuralContractError(
            f"LSTM: level-срез обязан быть одной серией, получено "
            f"{summary['n_series']}"
        )

    plan: NeuralExogenousPlan = build_exogenous_plan(
        long_frame, futr=feature_names, hist=(), stat=(),
    )

    futr_df: Optional[pd.DataFrame] = None
    if feature_names:
        future_ds = _validated_timestamps(
            future_timestamps, field_name="future_timestamps",
        )
        if len(future_ds) != int(horizon):
            raise ValueError(
                f"LSTM: future_timestamps: длина {len(future_ds)} != horizon "
                f"{horizon} (futr_df обязан покрыть горизонт прогноза)"
            )
        futr_df = pd.DataFrame({
            "unique_id": ["series_0"] * int(horizon),
            "ds": pd.DatetimeIndex(future_ds),
        })
        for name in feature_names:
            futr_df[name] = [
                float(value) for value in future_features[name]  # type: ignore[index]
            ]
        validate_future_exogenous_frame(
            plan, futr_df, n_series=1, horizon=int(horizon),
        )

    config = NeuralTrainingConfig(
        seed=int(random_state), max_steps=int(normalized["max_steps"]),
    )
    interval_plan = interval_levels_for_alpha(normalized["alpha"])
    cell = str(normalized["cell"])
    alias = "LSTM" if cell == "lstm" else "GRU"

    def model_factory(budget: Mapping[str, Any]) -> Any:
        from apps.api.model_impls.neural_runtime import require_neuralforecast

        model_cls = getattr(require_neuralforecast().models, alias)
        return model_cls(
            h=int(horizon),
            input_size=input_size,
            encoder_n_layers=int(normalized["encoder_n_layers"]),
            encoder_hidden_size=int(normalized["encoder_hidden_size"]),
            encoder_dropout=float(normalized["encoder_dropout"]),
            learning_rate=float(normalized["learning_rate"]),
            futr_exog_list=list(plan.futr_exog_list),
            alias=alias,
            **dict(budget),
        )

    predictions = train_and_forecast(
        model_factory=model_factory,
        freq=freq,
        train_long=long_frame,
        horizon=int(horizon),
        config=config,
        futr_df=futr_df,
        static_df=None,
        levels=interval_plan.levels,
        fold_index=0,
    )

    point_column = alias
    if point_column not in predictions.columns:
        raise NeuralContractError(
            f"LSTM: в прогнозе отсутствует точечная колонка '{point_column}'; "
            f"получены колонки {list(predictions.columns)}"
        )
    # Семантика conformal-колонок (эмпирика neuralforecast 3.2.2, см.
    # докстринг п.4): lo-L = point - q(L/100), hi-L = point + q(L/100).
    # Двусторонний (1-alpha)-интервал => обе границы на уровне L =
    # 100*(1-alpha/2) = levels[-1] плана interval_levels_for_alpha.
    interval_level = interval_plan.levels[-1]
    lo_column = f"{alias}-lo-{interval_level}"
    hi_column = f"{alias}-hi-{interval_level}"
    missing = [
        column for column in (lo_column, hi_column)
        if column not in predictions.columns
    ]
    if missing:
        raise NeuralContractError(
            f"LSTM: conformal-колонки {missing} отсутствуют в прогнозе "
            f"{list(predictions.columns)} (levels={list(interval_plan.levels)})"
        )

    forecast = predictions[point_column].to_numpy(dtype=float)
    lower = predictions[lo_column].to_numpy(dtype=float)
    upper = predictions[hi_column].to_numpy(dtype=float)
    if not (np.isfinite(forecast).all() and np.isfinite(lower).all()
            and np.isfinite(upper).all()):
        raise NeuralContractError(
            "LSTM: прогноз/интервалы содержат NaN/Inf -- fold отклоняется "
            "(никаких синтетических подмен)"
        )
    if not (
        (lower <= forecast).all() and (forecast <= upper).all()
    ):
        raise NeuralContractError(
            "LSTM: нарушен инвариант lower <= point <= upper -- fold "
            "отклоняется (clamp-подмены запрещены)"
        )

    from importlib import metadata as _metadata

    def _package_version(distribution: str) -> str:
        try:
            return _metadata.version(distribution)
        except _metadata.PackageNotFoundError:  # pragma: no cover
            return "unknown"

    return {
        "adapter_id": LSTM_ADAPTER_ID,
        "forecast": [float(value) for value in forecast],
        "lower": [float(value) for value in lower],
        "upper": [float(value) for value in upper],
        "params": normalized,
        "alias": alias,
        "n_train": n_train,
        "frequency": freq,
        "exogenous_plan": plan.as_dict(),
        "intervals": {
            "method": "conformal",
            "levels": [float(level) for level in interval_plan.levels],
            "alpha": normalized["alpha"],
            "interval_level": float(interval_level),
            "lower": "alpha/2 percentile (point - q(1-alpha/2) of |residuals|)",
            "upper": "1-alpha/2 percentile (point + q(1-alpha/2) of |residuals|)",
        },
        "neural": {
            "runtime": NEURAL_RUNTIME,
            "contract_version": NEURAL_CONTRACT_VERSION,
            "config": config.as_dict(),
            "fold_index": 0,
            "library_versions": {
                "neuralforecast": _package_version("neuralforecast"),
                "torch": _package_version("torch"),
            },
        },
        "random_state": int(random_state),
        "deterministic": True,
    }


def run_lstm_backtest(
    series: Sequence[float],
    train_ratio: float,
    seasonal_period: int,
) -> None:
    """Legacy synthetic-demo эндпоинт (POST /v1/models/backtest), сигнатура
    как у остальных model_impls.  Task 138: нейро-контракт Task 137 строит
    окна по РЕАЛЬНОЙ равноотстоящей сетке; bare-ряд synthetic-эндпоинта не
    несёт временной оси, а изобретать её внутри обёртки (целочисленный
    индекс/скрытая регуляризация) -- скрытый выбор, который контракт
    запрещает.  Никаких синтетических демо и Naive-fallback: честный отказ
    (ValueError), как у VAR/VECM/GARCH/EGARCH; исполняйте LSTM/GRU через
    session workflow (run_backtest_plan), где метки дат гарантированы EDA."""
    raise ValueError(
        "LSTM/GRU строит окна по реальной равноотстоящей сетке "
        "(нейро-контракт Task 137): bare-ряд synthetic-эндпоинта не несёт "
        "временной оси, скрытая регуляризация/целочисленный индекс "
        "запрещены -- исполняйте модель через session backtest "
        "(run_backtest_plan), где метки дат гарантированы EDA"
    )


__all__ = [
    "ALPHA_OPTIONS",
    "CELL_OPTIONS",
    "DEFAULT_PARAMS",
    "LSTM_ADAPTER_ID",
    "LSTM_MIN_TRAIN",
    "PARAM_BOUNDS",
    "_lstm_fit_predict",
    "run_lstm_backtest",
    "validate_lstm_params",
]
