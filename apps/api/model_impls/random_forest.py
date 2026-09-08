# apps/api/model_impls/random_forest.py
"""
Random Forest -- первый ML-адаптер платформы (Task 127, family=tree_ml).

Recursive supervised-стратегия.  Модель обучается на supervised-матрице,
собранной из ДВУХ источников, и предсказывает многошагово рекурсивно:

1. Каузальные target-derived historic-признаки, построенные через
   ``RecursiveFeatureState`` (Task 126) -- лаги 1..n_lags, rolling mean/std
   по окну n_lags, первая разность.  ОДИН И ТОТ ЖЕ код (peek_row/push)
   строит и train-матрицу (история = реальный train-срез), и будущие строки
   (история = train-хвост + накопленные прогнозы модели) -- классический
   train/serve skew рекурсивного прогнозирования устранён по построению.
   Никакой oracle-утечки: на шаге h признаки зависят только от y<h
   (train) и прогнозов модели (future), факты теста недостижимы.
2. Платформенные future_known/static регрессоры от fold-local FeaturePlan
   (granted-канал Task 126/124): симметричный train/future канал,
   fail-closed валидация длин/множеств/NaN -- тот же стандарт, что и у
   Prophet.  Historic-экзогены платформа не передаёт никогда (строгий
   future-known contract).

Feature importance: sklearn impurity importances, привязанные к ТОЧНОЙ
fold-матрице через ``bind_feature_importance`` -- адаптер считает
matrix_hash своей X-матрицы (та же схема canonical-JSON sha256, что и
FoldFeatureMatrixBuilder) и возвращает lineage в metadata; движок
бэктеста связывает его в fold["feature_importance"] (oracle-защита:
чужие колонки отклоняются).

Prediction intervals: эмпирические квантили по предсказаниям отдельных
деревьев (fixed 80%: p10/p90), как и у Prophet интервал не тюнится
(bounded scope Task 127).  Границы расширяются до point-прогноза, если
квантили численно его не содержат -- инвариант реестра lower <= point
<= upper обязан держаться при любом распределении.

Bounded params (fail-closed, см. PARAM_BOUNDS и rules/modeling.yaml):
n_estimators, max_depth, min_samples_leaf, n_lags.  Никаких
Naive-fallback: ошибка fit/predict -- ошибка fold'а
(BacktestExecutionError), синтетические метрики запрещены.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional, Sequence

import numpy as np

from apps.api.feature_plan import (
    FeatureSpec,
    RecursiveFeatureState,
    bind_feature_importance,
)
from apps.api.model_impls._supervised_recursion import (
    MIN_USABLE_ROWS,
    matrix_digest as _matrix_digest,
    supervised_feature_specs,
    supervised_matrix as _shared_supervised_matrix,
    validated_known_features,
)
from apps.api.model_impls._common import train_test_split
from apps.api.model_impls._metrics import compute_metrics
from apps.api.schemas import BacktestMetrics


RF_ADAPTER_ID = "sklearn-random-forest"

# Интервал фиксирован 80% (p10/p90 по деревьям) -- тот же bounded-scope
# подход, что и у Prophet в Task 124 (interval_width не тюнится).
INTERVAL_LOWER_Q = 0.1
INTERVAL_UPPER_Q = 0.9

# Минимум usable-строк supervised-матрицы -- общий контракт семейства tree_ml
# (импортируется из _supervised_recursion; значения не переопределяются).

DEFAULT_N_LAGS = 7

# Нормализованные дефолты + строгие границы (bounded param_space вне
# тюнинга тоже не может выйти за границы -- fail-closed).
DEFAULT_PARAMS: dict[str, Any] = {
    "n_estimators": 200,
    "max_depth": None,
    "min_samples_leaf": 1,
    "n_lags": DEFAULT_N_LAGS,
}
PARAM_BOUNDS: dict[str, tuple[int, int]] = {
    "n_estimators": (10, 1000),
    "max_depth": (1, 64),
    "min_samples_leaf": (1, 100),
    "n_lags": (1, 32),
}

_PARAM_KEYS = ("n_estimators", "max_depth", "min_samples_leaf", "n_lags")


def validate_rf_params(params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Нормализовать и провалидировать гиперпараметры (fail-closed).

    Неизвестные ключи игнорируются -- соглашение платформы (в params всегда
    приходят чужие ключи вроде tbats_seasonal_periods, см.
    backtesting.py::run_backtest_plan).
    """
    merged = {**DEFAULT_PARAMS, **{k: v for k, v in dict(params or {}).items() if k in _PARAM_KEYS}}
    normalized: dict[str, Any] = {}
    for key in _PARAM_KEYS:
        value = merged[key]
        low, high = PARAM_BOUNDS[key]
        if key == "max_depth" and value is None:
            normalized[key] = None
            continue
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise ValueError(
                f"Random Forest param '{key}': ожидался целочисленный аргумент, "
                f"получено {value!r}"
            )
        number = int(value)
        if not low <= number <= high:
            raise ValueError(
                f"Random Forest param '{key}'={number} вне bounded диапазона "
                f"[{low}, {high}]"
            )
        normalized[key] = number
    return normalized


def rf_feature_specs(n_lags: int) -> dict[str, FeatureSpec]:
    """Каузальные target-derived спеки адаптера (роль=historic, Task 126).

    Task 128: делегирование в общее ядро _supervised_recursion; имена
    префиксованы ``rf_`` и не могут столкнуться с колонками платформенного
    каталога генерации признаков.
    """
    return supervised_feature_specs("rf", n_lags)


def supervised_matrix(
    target: Sequence[float],
    *,
    known: Mapping[str, Sequence[float]],
    specs: Mapping[str, FeatureSpec],
):
    """Supervised train-матрица RF (Task 127): делегирование в общее ядро
    _supervised_recursion с фиксированным label; публичный API Task 127
    (импорты тестов из random_forest) сохранён."""
    return _shared_supervised_matrix(
        target, known=known, specs=specs, model_label="Random Forest",
    )


def _validated_known_features(
    y_train: Sequence[float],
    horizon: int,
    *,
    train_features: Optional[Mapping[str, Sequence[float]]],
    future_features: Optional[Mapping[str, Sequence[float]]],
) -> dict[str, dict[str, list[float]]]:
    """Fail-closed валидация regressor-канала (Task 128: общее ядро)."""
    return validated_known_features(
        y_train, horizon,
        train_features=train_features, future_features=future_features,
    )


def _rf_fit_predict(
    y_train: Sequence[float],
    horizon: int,
    *,
    train_features: Optional[Mapping[str, Sequence[float]]] = None,
    future_features: Optional[Mapping[str, Sequence[float]]] = None,
    params: Optional[Mapping[str, Any]] = None,
    random_state: int = 42,
) -> dict[str, Any]:
    """Recursive Random Forest: fit на supervised-матрице train-среза,
    многошаговый прогноз через RecursiveFeatureState (peek_row/push).

    Возвращает dict: forecast/lower/upper (длина == horizon),
    feature_importances (records) и feature_importance_lineage (привязка
    к точной X-матрице для bind_feature_importance в движке бэктеста).
    """
    if int(horizon) < 1:
        raise ValueError(f"Random Forest: horizon должен быть положительным, получен {horizon}")
    y = [float(value) for value in y_train]
    if len(y) == 0:
        raise ValueError("Random Forest requires at least one training observation")
    if not np.isfinite(np.asarray(y, dtype=float)).all():
        raise ValueError("Random Forest: target содержит NaN/Inf (fail-closed)")
    hyper = validate_rf_params(params)
    regressors = _validated_known_features(
        y, int(horizon),
        train_features=train_features, future_features=future_features,
    )
    specs = rf_feature_specs(hyper["n_lags"])

    columns, x_rows, target_rows, warmup = supervised_matrix(
        y, known={name: channel["train"] for name, channel in regressors.items()},
        specs=specs,
    )
    design = np.asarray(x_rows, dtype=float)
    labels = np.asarray(target_rows, dtype=float)

    from sklearn.ensemble import RandomForestRegressor

    # n_jobs=1: float-суммирование по деревьям детерминировано независимо
    # от окружения; воспроизводимость держится на random_state.
    model = RandomForestRegressor(
        n_estimators=hyper["n_estimators"],
        max_depth=hyper["max_depth"],
        min_samples_leaf=hyper["min_samples_leaf"],
        random_state=int(random_state),
        n_jobs=1,
    )
    model.fit(design, labels)

    # -- рекурсивный прогноз: peek -> predict -> push -----------------------
    # Порядок потребителя RecursiveFeatureState (Task 127): peek_row строит
    # строку шага из текущей истории (train-хвост + прогнозы модели), затем
    # модель предсказывает по строке, и прогноз кладётся в историю (push).
    # Никаких фактов теста: единственный источник истории -- train и прогнозы.
    state = RecursiveFeatureState(
        history=y, columns=list(specs), specs=dict(specs),
    )
    known_names = sorted(regressors)
    forecast: list[float] = []
    future_design = np.zeros((int(horizon), len(columns)), dtype=float)
    for step in range(int(horizon)):
        row = state.peek_row() + [regressors[name]["future"][step] for name in known_names]
        future_design[step, :] = row
        point = float(model.predict(future_design[step : step + 1])[0])
        if not math.isfinite(point):
            raise ValueError("Random Forest: модель вернула нечисловой прогноз (fail-closed)")
        forecast.append(point)
        state.push(point)

    # -- интервалы по деревьям (p10/p90, fixed 80%) -------------------------
    lower: list[float] = []
    upper: list[float] = []
    per_tree = np.asarray([
        estimator.predict(future_design)  # type: ignore[attr-defined]
        for estimator in model.estimators_
    ], dtype=float)
    for step in range(int(horizon)):
        point = forecast[step]
        step_low = float(np.quantile(per_tree[:, step], INTERVAL_LOWER_Q))
        step_high = float(np.quantile(per_tree[:, step], INTERVAL_UPPER_Q))
        # Инвариант реестра (lower <= point <= upper) обязан держаться и на
        # скошенных распределениях: квантили расширяются до point-прогноза.
        lower.append(min(step_low, point))
        upper.append(max(step_high, point))

    # -- importance, привязанный к ТОЧНОЙ fold-матрице ----------------------
    importances = [
        {"feature_name": name, "importance": float(value)}
        for name, value in zip(columns, model.feature_importances_, strict=True)
    ]
    lineage = {
        "adapter_id": RF_ADAPTER_ID,
        "columns": list(columns),
        "future_known_columns": list(known_names),
        "matrix_hash": _matrix_digest({
            "adapter_id": RF_ADAPTER_ID,
            "columns": columns,
            "rows": x_rows,
            "target": target_rows,
            "random_state": int(random_state),
            "params": hyper,
        }),
        "fit_policy": "per_train_fold",
        "n_rows": len(x_rows),
        "warmup": warmup,
    }
    # Самопроверка oracle-защиты: важность обязана валидироваться против
    # собственной матрицы -- иначе fold-запись получила бы непривязываемый
    # артефакт (fail-closed на этапе адаптера, а не движка).
    bind_feature_importance(lineage, importances)
    return {
        "forecast": forecast,
        "lower": lower,
        "upper": upper,
        "feature_importances": importances,
        "feature_importance_lineage": lineage,
    }


def run_random_forest_backtest(
    series: Sequence[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """Legacy synthetic-demo эндпоинт (POST /v1/models/backtest), сигнатура
    как у остальных model_impls; seasonal_period не используется (лаги
    задаются n_lags).  Task 127: сознательно БЕЗ safe_backtest/Naive-fallback
    -- для ML-среза ошибку модели нельзя подменять метриками наивного
    прогноза (никаких штрафных синтетических результатов); ошибка
    поднимается вызывающей стороне как есть."""
    y_train, y_test = train_test_split(list(series), train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)
    payload = _rf_fit_predict(y_train, len(y_test), random_state=42)
    return compute_metrics(y_test, payload["forecast"], y_train)
