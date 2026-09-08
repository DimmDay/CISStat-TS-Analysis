# apps/api/model_impls/xgboost.py
"""
XGBoost -- второй ML-адаптер платформы (Task 128, family=tree_ml).

Recursive supervised-стратегия на общей рекурсивной базе
``_supervised_recursion`` (извлечено из Task 127 и сертифицировано):
каузальные target-derived historic-признаки (лаги 1..n_lags, rolling
mean/std, diff_1) через ``RecursiveFeatureState`` (peek_row/push) --
train/serve skew устранён по построению; платформенные future_known/static
регрессоры от fold-local FeaturePlan (granted-канал Task 126/124),
fail-closed валидация.  Никакой oracle-утечки: на шаге h признаки зависят
только от train-хвоста и прогнозов модели.

Prediction intervals -- ЧЕРЕЗ QUANTILE REGRESSION (как декларировано в
rules/modeling.yaml::xgboost.supports_prediction_intervals): три модели на
одной supervised-матрице -- point (reg:squarederror) и две квантильные
(reg:quantileerror, alpha=0.1/0.9, fixed 80% -- тот же bounded-scope
подход, что interval_width у Prophet).  Рекурсию ведёт point-модель
(её прогнозы питают историю), квантильные предсказывают на ТЕХ ЖЕ
future-строках.  Границы расширяются до point-прогноза -- инвариант
реестра lower <= point <= upper обязан держаться при любом распределении.

Feature importance: gain-importances бустинга (importance_type="gain"),
привязанные к ТОЧНОЙ fold-матрице через ``bind_feature_importance`` --
адаптер считает matrix_hash своей X-матрицы (та же схема canonical-JSON
sha256) и возвращает lineage в metadata; движок бэктеста связывает его в
fold["feature_importance"] (oracle-защита: чужие колонки отклоняются).

Bounded params (fail-closed, см. PARAM_BOUNDS и rules/modeling.yaml):
n_estimators, max_depth, learning_rate, min_child_weight, reg_lambda,
colsample_bytree, n_lags.  Детерминизм: n_jobs=1, tree_method="hist",
random_state через ModelExecutionRequest; при полном сэмплировании
(colsample_bytree=1.0) бустер детерминирован независимо от seed --
скрытой стохастичности нет (покрыто тестом).  Никаких Naive-fallback:
ошибка fit/predict -- ошибка fold'а, синтетические метрики запрещены.
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


XGB_ADAPTER_ID = "xgboost-native"

# Fixed 80%: quantile_alpha нижней/верхней моделей (bounded scope, не тюнится).
INTERVAL_LOWER_ALPHA = 0.1
INTERVAL_UPPER_ALPHA = 0.9

DEFAULT_N_LAGS = 7

# Нормализованные дефолты + строгие границы (bounded param_space вне
# тюнинга тоже не может выйти за границы -- fail-closed).
DEFAULT_PARAMS: dict[str, Any] = {
    "n_estimators": 200,
    "max_depth": 6,
    "learning_rate": 0.1,
    "min_child_weight": 1,
    "reg_lambda": 1.0,
    "colsample_bytree": 1.0,
    "n_lags": DEFAULT_N_LAGS,
}
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "n_estimators": (10, 1000),
    "max_depth": (1, 20),
    "learning_rate": (0.001, 1.0),
    "min_child_weight": (1, 100),
    "reg_lambda": (0.0, 1000.0),
    "colsample_bytree": (0.1, 1.0),
    "n_lags": (1, 32),
}

_INT_KEYS = ("n_estimators", "max_depth", "min_child_weight", "n_lags")
_FLOAT_KEYS = ("learning_rate", "reg_lambda", "colsample_bytree")
_PARAM_KEYS = (*_INT_KEYS, *_FLOAT_KEYS)


def validate_xgb_params(params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
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
                f"XGBoost param '{key}': ожидался целочисленный аргумент, "
                f"получено {value!r}"
            )
        number = int(value)
        if not low <= number <= high:
            raise ValueError(
                f"XGBoost param '{key}'={number} вне bounded диапазона [{low}, {high}]"
            )
        normalized[key] = number
    for key in _FLOAT_KEYS:
        value = merged[key]
        low, high = PARAM_BOUNDS[key]
        if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
            raise ValueError(
                f"XGBoost param '{key}': ожидалось число, получено {value!r}"
            )
        number = float(value)
        if not low <= number <= high:
            raise ValueError(
                f"XGBoost param '{key}'={number} вне bounded диапазона [{low}, {high}]"
            )
        normalized[key] = number
    return normalized


def xgb_feature_specs(n_lags: int) -> dict[str, Any]:
    """Каузальные target-derived спеки адаптера -- общее ядро с префиксом
    ``xgb_`` (нет столкновений с колонками платформенного каталога)."""
    return supervised_feature_specs("xgb", n_lags)


def _make_booster(hyper: Mapping[str, Any], random_state: int, **extra: Any) -> Any:
    """Единая конфигурация бустера: детерминизм (n_jobs=1, hist) + seed."""
    from xgboost import XGBRegressor

    return XGBRegressor(
        n_estimators=hyper["n_estimators"],
        max_depth=hyper["max_depth"],
        learning_rate=hyper["learning_rate"],
        min_child_weight=hyper["min_child_weight"],
        reg_lambda=hyper["reg_lambda"],
        colsample_bytree=hyper["colsample_bytree"],
        random_state=int(random_state),
        n_jobs=1,
        tree_method="hist",
        importance_type="gain",
        **extra,
    )


def _xgb_fit_predict(
    y_train: Sequence[float],
    horizon: int,
    *,
    train_features: Optional[Mapping[str, Sequence[float]]] = None,
    future_features: Optional[Mapping[str, Sequence[float]]] = None,
    params: Optional[Mapping[str, Any]] = None,
    random_state: int = 42,
) -> dict[str, Any]:
    """Recursive XGBoost: fit на supervised-матрице train-среза,
    многошаговый прогноз через RecursiveFeatureState (peek_row/push);
    интервалы -- quantile regression (alpha=0.1/0.9) на тех же строках.

    Возвращает dict: forecast/lower/upper (длина == horizon),
    feature_importances (records) и feature_importance_lineage (привязка
    к точной X-матрице для bind_feature_importance в движке бэктеста).
    """
    if int(horizon) < 1:
        raise ValueError(f"XGBoost: horizon должен быть положительным, получен {horizon}")
    y = [float(value) for value in y_train]
    if len(y) == 0:
        raise ValueError("XGBoost requires at least one training observation")
    if not np.isfinite(np.asarray(y, dtype=float)).all():
        raise ValueError("XGBoost: target содержит NaN/Inf (fail-closed)")
    hyper = validate_xgb_params(params)
    regressors = validated_known_features(
        y, int(horizon),
        train_features=train_features, future_features=future_features,
    )
    specs = xgb_feature_specs(hyper["n_lags"])

    columns, x_rows, target_rows, warmup = supervised_matrix(
        y, known={name: channel["train"] for name, channel in regressors.items()},
        specs=specs, model_label="XGBoost",
    )
    design = np.asarray(x_rows, dtype=float)
    labels = np.asarray(target_rows, dtype=float)

    point_model = _make_booster(hyper, random_state, objective="reg:squarederror")
    lower_model = _make_booster(
        hyper, random_state,
        objective="reg:quantileerror", quantile_alpha=INTERVAL_LOWER_ALPHA,
    )
    upper_model = _make_booster(
        hyper, random_state,
        objective="reg:quantileerror", quantile_alpha=INTERVAL_UPPER_ALPHA,
    )
    point_model.fit(design, labels)
    lower_model.fit(design, labels)
    upper_model.fit(design, labels)

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
            raise ValueError("XGBoost: модель вернула нечисловой прогноз (fail-closed)")
        forecast.append(point)
        state.push(point)

    raw_lower = [float(value) for value in lower_model.predict(future_design)]
    raw_upper = [float(value) for value in upper_model.predict(future_design)]
    if not (np.isfinite(np.asarray(raw_lower)).all() and np.isfinite(np.asarray(raw_upper)).all()):
        raise ValueError("XGBoost: квантильные модели вернули NaN/Inf (fail-closed)")
    lower, upper = widen_intervals(forecast, raw_lower, raw_upper)

    # -- importance, привязанный к ТОЧНОЙ fold-матрице ----------------------
    importances = [
        {"feature_name": name, "importance": float(value)}
        for name, value in zip(columns, point_model.feature_importances_, strict=True)
    ]
    lineage = {
        "adapter_id": XGB_ADAPTER_ID,
        "columns": list(columns),
        "future_known_columns": list(known_names),
        "matrix_hash": matrix_digest({
            "adapter_id": XGB_ADAPTER_ID,
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


def run_xgboost_backtest(
    series: Sequence[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """Legacy synthetic-demo эндпоинт (POST /v1/models/backtest), сигнатура
    как у остальных model_impls; seasonal_period не используется (лаги
    задаются n_lags).  Task 128: сознательно БЕЗ safe_backtest/Naive-fallback
    -- для ML-среза ошибку модели нельзя подменять метриками наивного
    прогноза; ошибка поднимается вызывающей стороне как есть."""
    y_train, y_test = train_test_split(list(series), train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)
    payload = _xgb_fit_predict(y_train, len(y_test), random_state=42)
    return compute_metrics(y_test, payload["forecast"], y_train)
