# apps/api/model_impls/catboost.py
"""
CatBoost -- четвёртый ML-адаптер платформы (Task 130, family=tree_ml).

Recursive supervised-стратегия на общей рекурсивной базе
``_supervised_recursion`` (извлечено из Task 127, сертифицировано в
Task 127/128/129): каузальные target-derived historic-признаки (лаги
1..n_lags, rolling mean/std, diff_1) через ``RecursiveFeatureState``
(peek_row/push) -- train/serve skew устранён по построению;
платформенные future_known/static регрессоры от fold-local FeaturePlan
(granted-канал Task 126/124), fail-closed валидация.  Никакой
oracle-утечки: на шаге h признаки зависят только от train-хвоста и
прогнозов модели.

Prediction intervals -- ЧЕРЕЗ QUANTILE REGRESSION (как декларировано в
rules/modeling.yaml::catboost.supports_prediction_intervals): три
CatBoostRegressor на одной supervised-матрице -- point
(loss_function="RMSE") и две квантильные (loss_function=
"Quantile:alpha=0.1"/"Quantile:alpha=0.9", fixed 80% -- тот же
bounded-scope подход, что reg:quantileerror у XGBoost и objective=
"quantile" у LightGBM).  Рекурсию ведёт point-модель (её прогнозы
питают историю), квантильные предсказывают на ТЕХ ЖЕ future-строках.
Границы расширяются до point-прогноза -- инвариант реестра
lower <= point <= upper обязан держаться при любом распределении.

Feature importance: нативный ``get_feature_importance()`` CatBoost
возвращает PredictionValuesChange в ПРОЦЕНТАХ с суммой 100 (в отличие от
нормализованного ``feature_importances_`` XGBoost и сырых гейнов
LightGBM) -- адаптер НОРМАЛИЗУЕТ их к сумме 1.0 (контракт платформы; при
вырожденном нуле суммарной важности используется равномерное
распределение, документированный детерминированный fallback).
Деградированные данные закрываются САМОЙ БИБЛИОТЕКОЙ: CatBoost
отказывается обучаться на константном target / константных признаках
(CatBoostError; через этот адаптер константный target обязан давать
константные target-derived признаки, поэтому первым срабатывает отказ
квантизации "All features are either constant or ignored") -- ошибка
поднимается вызывающей стороне как есть, синтетические fallback-метрики
запрещены.
Привязка к ТОЧНОЙ fold-матрице через ``bind_feature_importance``:
адаптер считает matrix_hash своей X-матрицы (та же схема canonical-JSON
sha256) и возвращает lineage в metadata; движок бэктеста связывает его в
fold["feature_importance"] (oracle-защита: чужие колонки отклоняются).

Bounded params (fail-closed, см. PARAM_BOUNDS и rules/modeling.yaml):
iterations, depth, learning_rate, l2_leaf_reg, bagging_temperature,
random_strength, n_lags.  CatBoost -- бустинг на симметричных
(oblivious) деревьях, сложность дерева идиоматично ограничивает depth,
как max_depth у XGBoost.  Детерминизм: thread_count=1 (детерминированный
порядок float-суммирования на CPU) + master-seed ``random_seed`` через
ModelExecutionRequest; байесовский бутстрап строк выключен дефолтом
адаптера (bagging_temperature=0.0 -- отклонение от официального 1.0
документировано: на коротких platform-fold'ах ресемплинг строк с температурой
1.0 избыточно шумит), score-шум random_strength остаётся на официальном
дефолте 1.0 -- поэтому дефолтные запуски seed-зависимы (проводка seed
до бустера доказана тестом), а при random_strength=0 бустер
детерминирован независимо от seed -- скрытой стохастичности нет
(двустороннее доказательство покрыто тестами, как в Task 128/129).
allow_writing_files=False -- CatBoost по умолчанию пишет служебный
каталог catboost_info/ рядом с процессом; в production/тестах это
загрязнение запрещено.  Никаких Naive-fallback: ошибка fit/predict --
ошибка fold'а, синтетические метрики запрещены.
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


CB_ADAPTER_ID = "catboost-native"

# Fixed 80%: quantile alpha нижней/верхней моделей (bounded scope, не тюнится).
INTERVAL_LOWER_ALPHA = 0.1
INTERVAL_UPPER_ALPHA = 0.9

DEFAULT_N_LAGS = 7

# Нормализованные дефолты + строгие границы (bounded param_space вне
# тюнинга тоже не может выйти за границы -- fail-closed).  iterations=200
# -- платформенный бюджет (как n_estimators=200 у RF/XGB/LGBM); depth=6 и
# l2_leaf_reg=3.0 -- официальные дефолты CatBoost; learning_rate=0.1 --
# нормализация платформы (как у XGBoost/LightGBM адаптеров);
# bagging_temperature=0.0 -- документированное отклонение от официального
# 1.0 (см. докстринг модуля); random_strength=1.0 -- официальный дефолт.
DEFAULT_PARAMS: dict[str, Any] = {
    "iterations": 200,
    "depth": 6,
    "learning_rate": 0.1,
    "l2_leaf_reg": 3.0,
    "bagging_temperature": 0.0,
    "random_strength": 1.0,
    "n_lags": DEFAULT_N_LAGS,
}
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "iterations": (10, 2000),
    "depth": (1, 16),
    "learning_rate": (0.001, 1.0),
    "l2_leaf_reg": (0.0, 1000.0),
    "bagging_temperature": (0.0, 100.0),
    "random_strength": (0.0, 100.0),
    "n_lags": (1, 32),
}

_INT_KEYS = ("iterations", "depth", "n_lags")
_FLOAT_KEYS = ("learning_rate", "l2_leaf_reg", "bagging_temperature", "random_strength")
_PARAM_KEYS = (*_INT_KEYS, *_FLOAT_KEYS)


def validate_cb_params(params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
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
                f"CatBoost param '{key}': ожидался целочисленный аргумент, "
                f"получено {value!r}"
            )
        number = int(value)
        if not low <= number <= high:
            raise ValueError(
                f"CatBoost param '{key}'={number} вне bounded диапазона [{low}, {high}]"
            )
        normalized[key] = number
    for key in _FLOAT_KEYS:
        value = merged[key]
        low, high = PARAM_BOUNDS[key]
        if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
            raise ValueError(
                f"CatBoost param '{key}': ожидалось число, получено {value!r}"
            )
        number = float(value)
        if not low <= number <= high:
            raise ValueError(
                f"CatBoost param '{key}'={number} вне bounded диапазона [{low}, {high}]"
            )
        normalized[key] = number
    return normalized


def cb_feature_specs(n_lags: int) -> dict[str, Any]:
    """Каузальные target-derived спеки адаптера -- общее ядро с префиксом
    ``cb_`` (нет столкновений с колонками платформенного каталога)."""
    return supervised_feature_specs("cb", n_lags)


def _make_catboost_params(
    hyper: Mapping[str, Any], random_state: int, *, quantile_alpha: Optional[float] = None,
) -> dict[str, Any]:
    """Единая конфигурация CatBoostRegressor: детерминизм (thread_count=1)
    + master-seed (random_seed) + fail-safe вывода (verbose=False,
    allow_writing_files=False -- без служебного каталога catboost_info/).
    quantile_alpha переключает loss_function на квантильную."""
    loss = (
        "RMSE" if quantile_alpha is None else f"Quantile:alpha={quantile_alpha}"
    )
    return {
        "loss_function": loss,
        "iterations": hyper["iterations"],
        "depth": hyper["depth"],
        "learning_rate": hyper["learning_rate"],
        "l2_leaf_reg": hyper["l2_leaf_reg"],
        "bagging_temperature": hyper["bagging_temperature"],
        "random_strength": hyper["random_strength"],
        "random_seed": int(random_state),
        "thread_count": 1,
        "allow_writing_files": False,
        "verbose": False,
    }


def _normalize_importances(raw_importances: np.ndarray, n_columns: int) -> list[float]:
    """Нормализовать проценты PredictionValuesChange к сумме 1.0 (контракт
    платформы).

    Нативный get_feature_importance() CatBoost возвращает проценты с суммой
    100; нормализация делением на фактическую сумму даёт точную 1.0.
    При вырожденном нуле суммарной важности (ни одного сплита) --
    равномерное распределение, детерминированный документированный
    fallback, чтобы fold-артефакт всегда был привязываем.  СТАТУС
    DEFENSIVE-ONLY (зафиксирован сертификацией Task 130, замечание 1):
    ветка недостижима через публичную поверхность адаптера -- zero-сумма
    важности требует отсутствия сплитов, т.е. константных признаков, что
    CatBoost отклоняет library-native (CatBoostError стадии квантизации);
    поведение хелпера на нулевой сумме тем не менее привязано тестом
    напрямую (TestNormalizeImportancesHelper, закрывает gap
    mutation-проверки 4).  Константный target -- другая деградация:
    CatBoost отказывается обучаться (CatBoostError), она fail-closed на
    уровне библиотеки (см. докстринг модуля).
    """
    total = float(np.asarray(raw_importances, dtype=float).sum())
    if total > 0.0:
        return [float(value) / total for value in raw_importances]
    return [1.0 / n_columns] * n_columns


def _cb_fit_predict(
    y_train: Sequence[float],
    horizon: int,
    *,
    train_features: Optional[Mapping[str, Sequence[float]]] = None,
    future_features: Optional[Mapping[str, Sequence[float]]] = None,
    params: Optional[Mapping[str, Any]] = None,
    random_state: int = 42,
) -> dict[str, Any]:
    """Recursive CatBoost: fit на supervised-матрице train-среза,
    многошаговый прогноз через RecursiveFeatureState (peek_row/push);
    интервалы -- quantile regression (Quantile:alpha=0.1/0.9) на тех же
    строках.

    Возвращает dict: forecast/lower/upper (длина == horizon),
    feature_importances (records) и feature_importance_lineage (привязка
    к точной X-матрице для bind_feature_importance в движке бэктеста).
    """
    if int(horizon) < 1:
        raise ValueError(f"CatBoost: horizon должен быть положительным, получен {horizon}")
    y = [float(value) for value in y_train]
    if len(y) == 0:
        raise ValueError("CatBoost requires at least one training observation")
    if not np.isfinite(np.asarray(y, dtype=float)).all():
        raise ValueError("CatBoost: target содержит NaN/Inf (fail-closed)")
    hyper = validate_cb_params(params)
    regressors = validated_known_features(
        y, int(horizon),
        train_features=train_features, future_features=future_features,
    )
    specs = cb_feature_specs(hyper["n_lags"])

    columns, x_rows, target_rows, warmup = supervised_matrix(
        y, known={name: channel["train"] for name, channel in regressors.items()},
        specs=specs, model_label="CatBoost",
    )
    design = np.asarray(x_rows, dtype=float)
    labels = np.asarray(target_rows, dtype=float)

    from catboost import CatBoostRegressor

    # Три модели на ОДНОЙ supervised-матрице: point ведёт рекурсию,
    # квантильные предсказывают на тех же future-строках.  Один и тот же
    # random_state у всех трёх -- детерминизм пары (данные, seed).
    point_model = CatBoostRegressor(
        **_make_catboost_params(hyper, random_state),
    )
    lower_model = CatBoostRegressor(
        **_make_catboost_params(hyper, random_state, quantile_alpha=INTERVAL_LOWER_ALPHA),
    )
    upper_model = CatBoostRegressor(
        **_make_catboost_params(hyper, random_state, quantile_alpha=INTERVAL_UPPER_ALPHA),
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
            raise ValueError("CatBoost: модель вернула нечисловой прогноз (fail-closed)")
        forecast.append(point)
        state.push(point)

    raw_lower = [float(value) for value in lower_model.predict(future_design)]
    raw_upper = [float(value) for value in upper_model.predict(future_design)]
    if not (np.isfinite(np.asarray(raw_lower)).all() and np.isfinite(np.asarray(raw_upper)).all()):
        raise ValueError("CatBoost: квантильные модели вернули NaN/Inf (fail-closed)")
    lower, upper = widen_intervals(forecast, raw_lower, raw_upper)

    # -- importance, привязанный к ТОЧНОЙ fold-матрице ----------------------
    importances = [
        {"feature_name": name, "importance": float(value)}
        for name, value in zip(
            columns,
            _normalize_importances(
                np.asarray(point_model.get_feature_importance(), dtype=float), len(columns),
            ),
            strict=True,
        )
    ]
    lineage = {
        "adapter_id": CB_ADAPTER_ID,
        "columns": list(columns),
        "future_known_columns": list(known_names),
        "matrix_hash": matrix_digest({
            "adapter_id": CB_ADAPTER_ID,
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


def run_catboost_backtest(
    series: Sequence[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """Legacy synthetic-demo эндпоинт (POST /v1/models/backtest), сигнатура
    как у остальных model_impls; seasonal_period не используется (лаги
    задаются n_lags).  Task 130: сознательно БЕЗ safe_backtest/Naive-fallback
    -- для ML-среза ошибку модели нельзя подменять метриками наивного
    прогноза; ошибка поднимается вызывающей стороне как есть."""
    y_train, y_test = train_test_split(list(series), train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)
    payload = _cb_fit_predict(y_train, len(y_test), random_state=42)
    return compute_metrics(y_test, payload["forecast"], y_train)
