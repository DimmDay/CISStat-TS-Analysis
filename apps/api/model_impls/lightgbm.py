# apps/api/model_impls/lightgbm.py
"""
LightGBM -- третий ML-адаптер платформы (Task 129, family=tree_ml).

Recursive supervised-стратегия на общей рекурсивной базе
``_supervised_recursion`` (извлечено из Task 127, сертифицировано в
Task 127/128): каузальные target-derived historic-признаки (лаги 1..n_lags,
rolling mean/std, diff_1) через ``RecursiveFeatureState`` (peek_row/push) --
train/serve skew устранён по построению; платформенные future_known/static
регрессоры от fold-local FeaturePlan (granted-канал Task 126/124),
fail-closed валидация.  Никакой oracle-утечки: на шаге h признаки зависят
только от train-хвоста и прогнозов модели.

Prediction intervals -- ЧЕРЕЗ QUANTILE REGRESSION (как декларировано в
rules/modeling.yaml::lightgbm.supports_prediction_intervals): три бустера на
одной supervised-матрице -- point (objective="regression") и две квантильные
(objective="quantile", alpha=0.1/0.9, fixed 80% -- тот же bounded-scope
подход, что interval_width у Prophet и quantileerror у XGBoost).  Рекурсию
ведёт point-модель (её прогнозы питают историю), квантильные предсказывают
на ТЕХ ЖЕ future-строках.  Границы расширяются до point-прогноза --
инвариант реестра lower <= point <= upper обязан держаться при любом
распределении.

Feature importance: нативный ``booster.feature_importance("gain")``
возвращает СЫРЫЕ суммы гейнов (в отличие от нормализованного
``feature_importances_`` XGBoost) -- адаптер НОРМАЛИЗУЕТ их к сумме 1.0
(контракт платформы; при вырожденном нуле суммарного гейна -- константный
target без единого сплита -- используется равномерное распределение,
документированный детерминированный fallback).  Привязка к ТОЧНОЙ
fold-матрице через ``bind_feature_importance``: адаптер считает matrix_hash
своей X-матрицы (та же схема canonical-JSON sha256) и возвращает lineage в
metadata; движок бэктеста связывает его в fold["feature_importance"]
(oracle-защита: чужие колонки отклоняются).

Bounded params (fail-closed, см. PARAM_BOUNDS и rules/modeling.yaml):
n_estimators, num_leaves, learning_rate, min_data_in_leaf, lambda_l2,
feature_fraction, n_lags.  LightGBM -- leaf-wise бустинг, поэтому сложность
дерева ограничивает num_leaves (идиоматично для библиотеки), а не max_depth.
Детерминизм: num_threads=1, deterministic=True, force_col_wise=True
(фиксирует построение гистограмм), random_state через
ModelExecutionRequest проводятся в master-параметр ``seed`` -- от него
LightGBM детерминированно порождает все подчинённые сиды
(feature_fraction_seed и др.); при полном сэмплировании
(feature_fraction=1.0, bagging выключен) бустер детерминирован независимо
от seed -- скрытой стохастичности нет (покрыто тестом).  Никаких
Naive-fallback: ошибка fit/predict -- ошибка fold'а, синтетические метрики
запрещены.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional, Sequence

import numpy as np

from apps.api.feature_plan import (
    RecursiveFeatureState,
    bind_feature_importance,
)
from apps.api.model_impls._supervised_recursion import (
    matrix_digest,
    supervised_feature_specs,
    supervised_matrix,
    validated_known_features,
    widen_intervals,
)
from apps.api.model_impls._common import train_test_split
from apps.api.model_impls._metrics import compute_metrics
from apps.api.schemas import BacktestMetrics


LGB_ADAPTER_ID = "lightgbm-native"

# Fixed 80%: quantile alpha нижней/верхней моделей (bounded scope, не тюнится).
INTERVAL_LOWER_ALPHA = 0.1
INTERVAL_UPPER_ALPHA = 0.9

DEFAULT_N_LAGS = 7

# Нормализованные дефолты + строгие границы (bounded param_space вне
# тюнинга тоже не может выйти за границы -- fail-closed).  Дефолты --
# официальные дефолты LightGBM (num_leaves=31, min_data_in_leaf=20).
DEFAULT_PARAMS: dict[str, Any] = {
    "n_estimators": 200,
    "num_leaves": 31,
    "learning_rate": 0.1,
    "min_data_in_leaf": 20,
    "lambda_l2": 0.0,
    "feature_fraction": 1.0,
    "n_lags": DEFAULT_N_LAGS,
}
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "n_estimators": (10, 1000),
    "num_leaves": (2, 256),
    "learning_rate": (0.001, 1.0),
    "min_data_in_leaf": (1, 100),
    "lambda_l2": (0.0, 1000.0),
    "feature_fraction": (0.1, 1.0),
    "n_lags": (1, 32),
}

_INT_KEYS = ("n_estimators", "num_leaves", "min_data_in_leaf", "n_lags")
_FLOAT_KEYS = ("learning_rate", "lambda_l2", "feature_fraction")
_PARAM_KEYS = (*_INT_KEYS, *_FLOAT_KEYS)


def validate_lgb_params(params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Нормализовать и провалидировать гиперпараметры (fail-closed).

    Целочисленные поля принимают только целые (bool отклоняется),
    вещественные -- int/float.  Неизвестные ключи игнорируются --
    соглашение платформы (в params всегда приходят чужие ключи вроде
    tbats_seasonal_periods, см. backtesting.py::run_backtest_plan).
    """
    merged = {
        **DEFAULT_PARAMS,
        **{k: v for k, v in dict(params or {}).items() if k in _PARAM_KEYS},
    }
    normalized: dict[str, Any] = {}
    for key in _INT_KEYS:
        value = merged[key]
        low, high = PARAM_BOUNDS[key]
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise ValueError(
                f"LightGBM param '{key}': ожидался целочисленный аргумент, "
                f"получено {value!r}"
            )
        number = int(value)
        if not low <= number <= high:
            raise ValueError(
                f"LightGBM param '{key}'={number} вне bounded диапазона [{low}, {high}]"
            )
        normalized[key] = number
    for key in _FLOAT_KEYS:
        value = merged[key]
        low, high = PARAM_BOUNDS[key]
        if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
            raise ValueError(
                f"LightGBM param '{key}': ожидалось число, получено {value!r}"
            )
        number = float(value)
        if not low <= number <= high:
            raise ValueError(
                f"LightGBM param '{key}'={number} вне bounded диапазона [{low}, {high}]"
            )
        normalized[key] = number
    return normalized


def lgb_feature_specs(n_lags: int) -> dict[str, Any]:
    """Каузальные target-derived спеки адаптера -- общее ядро с префиксом
    ``lgb_`` (нет столкновений с колонками платформенного каталога)."""
    return supervised_feature_specs("lgb", n_lags)


def _make_lgb_params(hyper: Mapping[str, Any], random_state: int, **extra: Any) -> dict[str, Any]:
    """Единая конфигурация бустера: детерминизм (num_threads=1,
    deterministic, force_col_wise) + master-seed (все подчинённые сиды
    LightGBM порождаются из него детерминированно)."""
    return {
        "objective": "regression",
        "num_leaves": hyper["num_leaves"],
        "learning_rate": hyper["learning_rate"],
        "min_data_in_leaf": hyper["min_data_in_leaf"],
        "lambda_l2": hyper["lambda_l2"],
        "feature_fraction": hyper["feature_fraction"],
        "seed": int(random_state),
        "num_threads": 1,
        "deterministic": True,
        "force_col_wise": True,
        "verbosity": -1,
        **extra,
    }


def _normalize_gains(raw_gains: np.ndarray, n_columns: int) -> list[float]:
    """Нормализовать сырые gain-суммы к сумме 1.0 (контракт платформы).

    Нативный feature_importance("gain") LightGBM возвращает сырые величины;
    при вырожденном нуле суммарного гейна (константный target: бустинг не
    делает ни одного сплита) -- равномерное распределение, детерминированный
    документированный fallback, чтобы fold-артефакт всегда был привязываем.
    """
    total = float(np.asarray(raw_gains, dtype=float).sum())
    if total > 0.0:
        return [float(value) / total for value in raw_gains]
    return [1.0 / n_columns] * n_columns


def _lgb_fit_predict(
    y_train: Sequence[float],
    horizon: int,
    *,
    train_features: Optional[Mapping[str, Sequence[float]]] = None,
    future_features: Optional[Mapping[str, Sequence[float]]] = None,
    params: Optional[Mapping[str, Any]] = None,
    random_state: int = 42,
) -> dict[str, Any]:
    """Recursive LightGBM: fit на supervised-матрице train-среза,
    многошаговый прогноз через RecursiveFeatureState (peek_row/push);
    интервалы -- quantile regression (alpha=0.1/0.9) на тех же строках.

    Возвращает dict: forecast/lower/upper (длина == horizon),
    feature_importances (records) и feature_importance_lineage (привязка
    к точной X-матрице для bind_feature_importance в движке бэктеста).
    """
    if int(horizon) < 1:
        raise ValueError(f"LightGBM: horizon должен быть положительным, получен {horizon}")
    y = [float(value) for value in y_train]
    if len(y) == 0:
        raise ValueError("LightGBM requires at least one training observation")
    if not np.isfinite(np.asarray(y, dtype=float)).all():
        raise ValueError("LightGBM: target содержит NaN/Inf (fail-closed)")
    hyper = validate_lgb_params(params)
    regressors = validated_known_features(
        y, int(horizon),
        train_features=train_features, future_features=future_features,
    )
    specs = lgb_feature_specs(hyper["n_lags"])

    columns, x_rows, target_rows, warmup = supervised_matrix(
        y, known={name: channel["train"] for name, channel in regressors.items()},
        specs=specs, model_label="LightGBM",
    )
    design = np.asarray(x_rows, dtype=float)
    labels = np.asarray(target_rows, dtype=float)

    import lightgbm as lgb

    train_set = lgb.Dataset(design, label=labels)
    point_model = lgb.train(
        _make_lgb_params(hyper, random_state), train_set,
        num_boost_round=hyper["n_estimators"],
    )
    lower_model = lgb.train(
        _make_lgb_params(hyper, random_state, objective="quantile", alpha=INTERVAL_LOWER_ALPHA),
        train_set, num_boost_round=hyper["n_estimators"],
    )
    upper_model = lgb.train(
        _make_lgb_params(hyper, random_state, objective="quantile", alpha=INTERVAL_UPPER_ALPHA),
        train_set, num_boost_round=hyper["n_estimators"],
    )

    # -- рекурсивный прогноз: peek -> predict -> push -----------------------
    # Порядок потребителя RecursiveFeatureState (Task 127): peek_row строит
    # строку шага из текущей истории (train-хвост + прогнозы point-модели),
    # затем модель предсказывает по строке, и прогноз кладётся в историю
    # (push).  Никаких фактов теста: единственный источник истории -- train
    # и прогнозы; квантильные модели предсказывают на ТЕХ ЖЕ строках.
    state = RecursiveFeatureState(
        history=y, columns=list(specs), specs=dict(specs),
    )
    known_names = sorted(regressors)
    forecast: list[float] = []
    future_design = np.zeros((int(horizon), len(columns)), dtype=float)
    for step in range(int(horizon)):
        row = state.peek_row() + [regressors[name]["future"][step] for name in known_names]
        future_design[step, :] = row
        point = float(point_model.predict(future_design[step : step + 1])[0])
        if not math.isfinite(point):
            raise ValueError("LightGBM: модель вернула нечисловой прогноз (fail-closed)")
        forecast.append(point)
        state.push(point)

    raw_lower = [float(value) for value in lower_model.predict(future_design)]
    raw_upper = [float(value) for value in upper_model.predict(future_design)]
    if not (np.isfinite(np.asarray(raw_lower)).all() and np.isfinite(np.asarray(raw_upper)).all()):
        raise ValueError("LightGBM: квантильные модели вернули NaN/Inf (fail-closed)")
    lower, upper = widen_intervals(forecast, raw_lower, raw_upper)

    # -- importance, привязанный к ТОЧНОЙ fold-матрице ----------------------
    importances = [
        {"feature_name": name, "importance": float(value)}
        for name, value in zip(
            columns,
            _normalize_gains(point_model.feature_importance(importance_type="gain"), len(columns)),
            strict=True,
        )
    ]
    lineage = {
        "adapter_id": LGB_ADAPTER_ID,
        "columns": list(columns),
        "future_known_columns": list(known_names),
        "matrix_hash": matrix_digest({
            "adapter_id": LGB_ADAPTER_ID,
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


def run_lightgbm_backtest(
    series: Sequence[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """Legacy synthetic-demo эндпоинт (POST /v1/models/backtest), сигнатура
    как у остальных model_impls; seasonal_period не используется (лаги
    задаются n_lags).  Task 129: сознательно БЕЗ safe_backtest/Naive-fallback
    -- для ML-среза ошибку модели нельзя подменять метриками наивного
    прогноза; ошибка поднимается вызывающей стороне как есть."""
    y_train, y_test = train_test_split(list(series), train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)
    payload = _lgb_fit_predict(y_train, len(y_test), random_state=42)
    return compute_metrics(y_test, payload["forecast"], y_train)
