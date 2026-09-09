# apps/api/model_impls/var.py
"""
VAR -- нативная векторная авторегрессия statsmodels (Task 132, family=multivariate).

Первый исполнитель многомерного контракта Task 131.  Постановка
docs/modeling_task_list.md::Task 132 (общая нота серии VAR/VECM):

1. **Порядок лага выбирается fold-local**: адаптер получает ТОЛЬКО train-срез
   системы; select_order (AIC/BIC/HQIC/FPE) или фиксированный p исполняются
   на нём.  Полная история в адаптер недостижима по построению.
2. **Нативный многомерный прогноз с интервалами** -- VARResults.forecast
   и VARResults.forecast_interval statsmodels.  Это НЕ цикл одномерных
   ARIMA: перекрёстные связи между уравнениями работают в обе стороны
   (привязано тестом на связанных системах).
3. **Fail-closed**: никаких Naive-fallback и синтетических метрик.  Ошибка
   fit/predict (короткая история, вырожденная ковариация, нечисловой вход)
   -- ошибка fold'а (BacktestExecutionError на движке).

Контракт данных: target-ряд -- первая колонка системы, related_series --
остальные колонки в порядке объявления (EndogenousSystem, Task 131).
Общая регулярная сетка и валидация системы -- ответственность движка
(run_vector_backtest_plan); адаптер повторно валидирует длины/finite.

Bounded params (fail-closed, см. PARAM_BOUNDS и rules/modeling.yaml):
maxlags (1..12), ic (aic/bic/hqic/fpe/None), trend (c/ct/n/ctt),
alpha (0.01/0.05/0.10 -- ширина нативных интервалов).  ic=None означает
фиксированный порядок p=maxlags (без информационного критерия).

Детерминизм: statsmodels VAR -- OLS по последнему квадрату, случайность
отсутствует; параметр random_state принимается по контракту реестра и
не влияет на результат (задокументировано).
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import numpy as np

from apps.api.model_impls._metrics import compute_metrics
from apps.api.schemas import BacktestMetrics


VAR_ADAPTER_ID = "statsmodels-var"

#: Имя target-колонки внутри адаптера (движок подставляет реальные имена
#: системы; адаптер фиксирует только ПОРЯДОК: target -- первая колонка).
TARGET_PLACEHOLDER = "__target__"

#: Минимальная длина train-среза системы (согласовано с
#: MIN_SYSTEM_OBSERVATIONS контракта Task 131).
VAR_MIN_TRAIN = 20

#: Нормализованные дефолты + строгие границы (bounded param_space вне
#: тюнинга тоже не может выйти за границы -- fail-closed).
DEFAULT_PARAMS: dict[str, Any] = {
    "maxlags": 8,
    "ic": "aic",
    "trend": "c",
    "alpha": 0.05,
}
PARAM_BOUNDS: dict[str, tuple[int, int]] = {
    "maxlags": (1, 12),
}
IC_OPTIONS = {"aic", "bic", "hqic", "fpe"}
TREND_OPTIONS = {"c", "ct", "n", "ctt"}
ALPHA_OPTIONS = {0.01, 0.05, 0.10}

_PARAM_KEYS = ("maxlags", "ic", "trend", "alpha")


def validate_var_params(params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Нормализовать и провалидировать гиперпараметры VAR (fail-closed).

    Неизвестные ключи игнорируются -- соглашение платформы (в params всегда
    приходят чужие ключи вроде tbats_seasonal_periods, см.
    backtesting.py::run_backtest_plan).  ic=None -- допустимая конвенция
    «фиксированный порядок p=maxlags».
    """
    merged = {
        **DEFAULT_PARAMS,
        **{k: v for k, v in dict(params or {}).items() if k in _PARAM_KEYS},
    }
    normalized: dict[str, Any] = {}
    low, high = PARAM_BOUNDS["maxlags"]
    value = merged["maxlags"]
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(
            f"VAR param 'maxlags': ожидался целочисленный аргумент, получено {value!r}"
        )
    number = int(value)
    if not low <= number <= high:
        raise ValueError(
            f"VAR param 'maxlags'={number} вне bounded диапазона [{low}, {high}]"
        )
    normalized["maxlags"] = number
    ic = merged["ic"]
    if ic is not None and ic not in IC_OPTIONS:
        raise ValueError(
            f"VAR param 'ic'={ic!r} вне допустимого набора {sorted(IC_OPTIONS)} или None"
        )
    normalized["ic"] = None if ic is None else str(ic)
    trend = merged["trend"]
    if trend not in TREND_OPTIONS:
        raise ValueError(
            f"VAR param 'trend'={trend!r} вне допустимого набора {sorted(TREND_OPTIONS)}"
        )
    normalized["trend"] = str(trend)
    alpha = merged["alpha"]
    try:
        alpha_value = float(alpha)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"VAR param 'alpha'={alpha!r} не числовой") from exc
    if alpha_value not in ALPHA_OPTIONS:
        raise ValueError(
            f"VAR param 'alpha'={alpha_value} вне допустимого набора {sorted(ALPHA_OPTIONS)}"
        )
    normalized["alpha"] = alpha_value
    return normalized


def _validated_matrix(
    target: Sequence[float],
    related_series: Optional[Mapping[str, Sequence[float]]],
) -> tuple[np.ndarray, tuple[str, ...]]:
    """Система [target | related]: finite, равные длины, K >= 2 (fail-closed)."""
    target_vector = np.asarray([float(value) for value in target], dtype=float)
    if target_vector.size == 0:
        raise ValueError("VAR: target train fold пуст")
    if not np.isfinite(target_vector).all():
        raise ValueError("VAR: target содержит NaN/Inf")
    names: list[str] = [TARGET_PLACEHOLDER]
    columns: list[np.ndarray] = [target_vector]
    for name, column in dict(related_series or {}).items():
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("VAR: имена related_series не могут быть пустыми")
        try:
            vector = np.asarray([float(value) for value in column], dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"VAR: related_series '{clean_name}' должен быть числовым"
            ) from exc
        if vector.size != target_vector.size:
            raise ValueError(
                f"VAR: related_series '{clean_name}': длина {vector.size} не равна "
                f"длине target {target_vector.size}"
            )
        if not np.isfinite(vector).all():
            raise ValueError("VAR: related_series содержит NaN/Inf")
        names.append(clean_name)
        columns.append(vector)
    if len(columns) < 2:
        raise ValueError(
            "VAR требует не менее 2 endogenous-рядов (target + related_series); "
            f"получено {len(columns)}"
        )
    return np.column_stack(columns), tuple(names)


def _search_bound_ok(nobs: int, k: int, maxlags: int, ic: Optional[str]) -> bool:
    """Детерминированная проверка достаточности истории.

    Фиксированный p=maxlags: нужно nobs - p > K*p + K(trend) параметров
    на уравнение.  Поиск по ic до maxlags: тот же критерий для ВЕРХНЕЙ
    границы поиска (поиск по слишком короткой выборке даёт вырожденные
    критерии, а не честный отказ).
    """
    rows_needed = (k + 1) * maxlags + k
    return nobs > rows_needed


def _var_fit_predict(
    target: Sequence[float],
    horizon: int,
    *,
    related_series: Optional[Mapping[str, Sequence[float]]] = None,
    params: Optional[Mapping[str, Any]] = None,
    random_state: int = 42,
) -> dict[str, Any]:
    """Нативный VAR fit/forecast/forecast_interval на переданном train-срезе.

    Возвращает векторный payload: forecast/lower/upper -- матрицы
    (horizon x K) в порядке колонок [target | related...]; metadata-поля
    lag_order/lag_selection/coefficient_matrices/in_sample_residuals --
    вход диагностики companion_stability/system_white_noise_diagnostics
    (Task 131) на движке.  random_state принят по контракту реестра:
    VAR -- детерминированный OLS, случайности нет.
    """
    if int(horizon) < 1:
        raise ValueError("VAR: horizon должен быть положительным")
    normalized = validate_var_params(params)
    matrix, series_names = _validated_matrix(target, related_series)
    nobs, k = matrix.shape
    if nobs < VAR_MIN_TRAIN:
        raise ValueError(
            f"VAR: история слишком короткая ({nobs} наблюдений); минимум "
            f"{VAR_MIN_TRAIN} (MIN_SYSTEM_OBSERVATIONS контракта Task 131)"
        )
    if not _search_bound_ok(nobs, k, normalized["maxlags"], normalized["ic"]):
        raise ValueError(
            f"VAR: история слишком короткая ({nobs} наблюдений) для поиска "
            f"порядка лага до {normalized['maxlags']} при K={k}; уменьшите "
            "maxlags или увеличьте train-срез"
        )

    from statsmodels.tsa.vector_ar.var_model import VAR as _StatsmodelsVAR

    try:
        model = _StatsmodelsVAR(matrix)
        if normalized["ic"] is None:
            fitted = model.fit(
                maxlags=normalized["maxlags"], trend=normalized["trend"],
            )
            selection: dict[str, Any] = {
                "ic": None, "selected_order": int(fitted.k_ar),
                "criteria": {},
                "searched_up_to": normalized["maxlags"],
            }
        else:
            order_table = model.select_order(
                maxlags=normalized["maxlags"], trend=normalized["trend"],
            )
            fitted = model.fit(
                maxlags=normalized["maxlags"], ic=normalized["ic"],
                trend=normalized["trend"],
            )
            selection = {
                "ic": normalized["ic"],
                "selected_order": int(fitted.k_ar),
                "criteria": {
                    name: int(value)
                    for name, value in order_table.selected_orders.items()
                },
                "searched_up_to": normalized["maxlags"],
            }
        point, lower, upper = fitted.forecast_interval(
            matrix[-fitted.k_ar:], steps=int(horizon),
            alpha=normalized["alpha"],
        )
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 -- library-native отказ = ошибка fold'а
        raise ValueError(
            f"VAR: fit/forecast недоступен на переданном train-срезе: {exc}"
        ) from exc

    forecast = np.asarray(point, dtype=float)
    lower_matrix = np.asarray(lower, dtype=float)
    upper_matrix = np.asarray(upper, dtype=float)
    if forecast.shape != (int(horizon), k):
        raise ValueError(
            f"VAR: statsmodels вернул прогноз формы {forecast.shape}, ожидалось "
            f"({int(horizon)}, {k})"
        )
    # Инвариант реестра lower <= point <= upper обязан держаться нативно;
    # численная защита от вырожденного квантиля (не меняет честный прогноз).
    lower_matrix = np.minimum(lower_matrix, forecast)
    upper_matrix = np.maximum(upper_matrix, forecast)
    coefficient_matrices = [
        np.asarray(block, dtype=float) for block in fitted.coefs
    ]
    return {
        "series_names": series_names,
        "forecast": forecast,
        "lower": lower_matrix,
        "upper": upper_matrix,
        "lag_order": int(fitted.k_ar),
        "lag_selection": selection,
        "trend": normalized["trend"],
        "alpha": normalized["alpha"],
        "nobs": int(fitted.nobs),
        "coefficient_matrices": coefficient_matrices,
        "in_sample_residuals": np.asarray(fitted.resid, dtype=float),
        "random_state": int(random_state),
        "deterministic": True,
    }


def run_var_backtest(
    series: Sequence[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """Legacy synthetic-demo эндпоинт (POST /v1/models/backtest), сигнатура
    как у остальных model_impls.  Task 132: VAR требует систему K>=2 --
    на одиночном синтетическом ряде исполнение НЕВОЗМОЖНО без подмены.
    Никаких синтетических многомерных демо и Naive-fallback: честный отказ
    (ValueError), как и у ML-адаптеров Tasks 127-130."""
    raise ValueError(
        "VAR требует не менее 2 endogenous-рядов (target + related_series); "
        "однорядный synthetic-эндпоинт не применим -- исполняйте VAR через "
        "многомерный session backtest (run_vector_backtest_plan)"
    )


__all__ = [
    "ALPHA_OPTIONS",
    "DEFAULT_PARAMS",
    "IC_OPTIONS",
    "PARAM_BOUNDS",
    "TARGET_PLACEHOLDER",
    "TREND_OPTIONS",
    "VAR_ADAPTER_ID",
    "VAR_MIN_TRAIN",
    "_var_fit_predict",
    "run_var_backtest",
    "validate_var_params",
]
