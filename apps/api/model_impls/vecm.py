# apps/api/model_impls/vecm.py
"""
VECM -- нативная векторная модель коррекции ошибками statsmodels (Task 133,
family=multivariate).

Второй исполнитель многомерного контракта Task 131.  Постановка
docs/modeling_task_list.md::Task 133 (общая нота серии VAR/VECM):

1. **Ранг Йохансена определяется ТОЛЬКО на train-fold**: адаптер получает
   ТОЛЬКО train-срез системы; режим ``coint_rank="auto"`` вызывает
   select_coint_rank (trace, signif=0.05) на нём, полная история
   недостижима по построению.  Ранг 0 -- честный отказ (VECM неприменим
   к системе без коинтеграции), БЕЗ тихого VAR-fallback.
2. **Нативный многомерный прогноз с интервалами** -- VECMResults.predict
   (mid/lower/upper при alpha).  Это НЕ цикл одномерных ARIMA:
   краткосрочная динамика gamma и долгосрочная связь beta работают
   совместно (привязано тестом на коинтегрированных системах).
3. **Fail-closed**: никаких Naive-fallback и синтетических метрик.  Ошибка
   fit/predict -- ошибка fold'а (BacktestExecutionError на движке).

Контракт данных: target-ряд -- первая колонка системы, related_series --
остальные колонки в порядке объявления (EndogenousSystem, Task 131).
Общая регулярная сетка и валидация системы -- ответственность движка
(run_vector_backtest_plan); адаптер повторно валидирует длины/finite.

Bounded params (fail-closed, см. PARAM_BOUNDS и rules/modeling.yaml):
k_ar_diff (1..12 -- число лаговых разностей), coint_rank ("auto" | int
1..K-1), deterministic (n/ci/co/li/lo -- детерминированные термы
statsmodels), alpha (0.01/0.05/0.10 -- ширина нативных интервалов).
det_order для ранг-теста выводится из deterministic: n -> -1, ci/co -> 0,
li/lo -> 1.  Exogenous-канал (VARX) -- ТОЛЬКО для VAR (yaml:
supports_exogenous: false у vecm); адаптер exog не принимает.

Детерминизм: statsmodels VECM -- OLS/ML по регрессии разностей, случайность
отсутствует; параметр random_state принимается по контракту реестра и не
влияет на результат (задокументировано).
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import numpy as np

from apps.api.schemas import BacktestMetrics


VECM_ADAPTER_ID = "statsmodels-vecm"

#: Имя target-колонки внутри адаптера (движок подставляет реальные имена
#: системы; адаптер фиксирует только ПОРЯДОК: target -- первая колонка).
TARGET_PLACEHOLDER = "__target__"

#: Минимальная длина train-среза системы (согласовано с
#: MIN_SYSTEM_OBSERVATIONS контракта Task 131).
VECM_MIN_TRAIN = 20

#: Нормализованные дефолты + строгие границы (bounded param_space вне
#: тюнинга тоже не может выйти за границы -- fail-closed).
DEFAULT_PARAMS: dict[str, Any] = {
    "k_ar_diff": 1,
    "coint_rank": "auto",
    "deterministic": "ci",
    "alpha": 0.05,
}
PARAM_BOUNDS: dict[str, tuple[int, int]] = {
    "k_ar_diff": (1, 12),
}
RANK_AUTO = "auto"
DETERMINISTIC_OPTIONS = {"n", "ci", "co", "li", "lo"}
ALPHA_OPTIONS = {0.01, 0.05, 0.10}

#: det_order ранг-теста Йохансена выводится из детерминированных термов
#: спецификации VECM (statsmodels: -1 -- нет, 0 -- константа, 1 -- тренд).
DET_ORDER_BY_DETERMINISTIC: dict[str, int] = {
    "n": -1, "ci": 0, "co": 0, "li": 1, "lo": 1,
}

_PARAM_KEYS = ("k_ar_diff", "coint_rank", "deterministic", "alpha")


def validate_vecm_params(params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Нормализовать и провалидировать гиперпараметры VECM (fail-closed).

    Неизвестные ключи игнорируются -- соглашение платформы (в params всегда
    приходят чужие ключи вроде tbats_seasonal_periods, см.
    backtesting.py::run_backtest_plan).  ``coint_rank="auto"`` -- конвенция
    fold-local ранг-теста Йохансена; целый ранг >= 1 -- фиксированная
    спецификация (пользовательское решение, не тест).
    """
    merged = {
        **DEFAULT_PARAMS,
        **{k: v for k, v in dict(params or {}).items() if k in _PARAM_KEYS},
    }
    normalized: dict[str, Any] = {}
    low, high = PARAM_BOUNDS["k_ar_diff"]
    value = merged["k_ar_diff"]
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ValueError(
            f"VECM param 'k_ar_diff': ожидался целочисленный аргумент, получено {value!r}"
        )
    number = int(value)
    if not low <= number <= high:
        raise ValueError(
            f"VECM param 'k_ar_diff'={number} вне bounded диапазона [{low}, {high}]"
        )
    normalized["k_ar_diff"] = number
    rank = merged["coint_rank"]
    if isinstance(rank, str):
        if rank.strip().lower() != RANK_AUTO:
            raise ValueError(
                f"VECM param 'coint_rank'={rank!r}: допустимо {RANK_AUTO!r} "
                "или целое >= 1"
            )
        normalized["coint_rank"] = RANK_AUTO
    else:
        if isinstance(rank, bool) or not isinstance(rank, (int, np.integer)):
            raise ValueError(
                f"VECM param 'coint_rank'={rank!r}: допустимо {RANK_AUTO!r} "
                "или целое >= 1"
            )
        rank_number = int(rank)
        if rank_number < 1:
            raise ValueError(
                f"VECM param 'coint_rank'={rank_number} вне допустимого "
                f"диапазона [1, K-1] или {RANK_AUTO!r}"
            )
        normalized["coint_rank"] = rank_number
    deterministic = merged["deterministic"]
    if deterministic not in DETERMINISTIC_OPTIONS:
        raise ValueError(
            f"VECM param 'deterministic'={deterministic!r} вне допустимого "
            f"набора {sorted(DETERMINISTIC_OPTIONS)}"
        )
    normalized["deterministic"] = str(deterministic)
    alpha = merged["alpha"]
    try:
        alpha_value = float(alpha)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"VECM param 'alpha'={alpha!r} не числовой") from exc
    if alpha_value not in ALPHA_OPTIONS:
        raise ValueError(
            f"VECM param 'alpha'={alpha_value} вне допустимого набора {sorted(ALPHA_OPTIONS)}"
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
        raise ValueError("VECM: target train fold пуст")
    if not np.isfinite(target_vector).all():
        raise ValueError("VECM: target содержит NaN/Inf")
    names: list[str] = [TARGET_PLACEHOLDER]
    columns: list[np.ndarray] = [target_vector]
    for name, column in dict(related_series or {}).items():
        clean_name = str(name).strip()
        if not clean_name:
            raise ValueError("VECM: имена related_series не могут быть пустыми")
        try:
            vector = np.asarray([float(value) for value in column], dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"VECM: related_series '{clean_name}' должен быть числовым"
            ) from exc
        if vector.size != target_vector.size:
            raise ValueError(
                f"VECM: related_series '{clean_name}': длина {vector.size} не равна "
                f"длине target {target_vector.size}"
            )
        if not np.isfinite(vector).all():
            raise ValueError("VECM: related_series содержит NaN/Inf")
        names.append(clean_name)
        columns.append(vector)
    if len(columns) < 2:
        raise ValueError(
            "VECM требует не менее 2 endogenous-рядов (target + related_series); "
            f"получено {len(columns)}"
        )
    return np.column_stack(columns), tuple(names)


def _search_bound_ok(nobs: int, k: int, k_ar_diff: int) -> bool:
    """Детерминированная проверка достаточности истории.

    VECM(k_ar_diff) эквивалентен VAR(k_ar_diff+1) в уровнях: на уравнение
    нужно K*(k_ar_diff+1) лаговых регрессоров + ранговые/детерминированные
    термы.  Консервативная граница: nobs > (K+1)*(k_ar_diff+1) + K --
    поиск/оценка на слишком короткой выборке даёт вырожденные результаты,
    а не честный отказ.
    """
    rows_needed = (k + 1) * (k_ar_diff + 1) + k
    return nobs > rows_needed


def _select_coint_rank_auto(
    matrix: np.ndarray, *, det_order: int, k_ar_diff: int,
) -> tuple[int, dict[str, Any]]:
    """Fold-local ранг-тест Йохансена (trace, signif=0.05) -- честный отказ при 0."""
    from statsmodels.tsa.vector_ar.vecm import select_coint_rank

    try:
        rank_result = select_coint_rank(
            matrix, det_order=det_order, k_ar_diff=k_ar_diff,
            method="trace", signif=0.05,
        )
    except Exception as exc:  # noqa: BLE001 -- library-native отказ
        raise ValueError(
            f"VECM: ранг-тест Йохансена недоступен на train-срезе: {exc}"
        ) from exc
    rank = int(rank_result.rank)
    selection: dict[str, Any] = {
        "mode": RANK_AUTO,
        "selected_rank": rank,
        "det_order": int(det_order),
        "signif": 0.05,
        "k_ar_diff": int(k_ar_diff),
    }
    if rank < 1:
        raise ValueError(
            "VECM: коинтеграция на train-срезе не подтверждена "
            f"(Johansen trace rank={rank} при signif=0.05) -- модель "
            "неприменима без VAR-fallback; используйте VAR или подтвердите "
            "коинтеграцию"
        )
    return rank, selection


def _vecm_fit_predict(
    target: Sequence[float],
    horizon: int,
    *,
    related_series: Optional[Mapping[str, Sequence[float]]] = None,
    params: Optional[Mapping[str, Any]] = None,
    random_state: int = 42,
) -> dict[str, Any]:
    """Нативный VECM fit/predict на переданном train-срезе.

    Возвращает векторный payload: forecast/lower/upper -- матрицы
    (horizon x K) в порядке колонок [target | related...]; metadata-поля
    k_ar_diff/coint_rank/rank_selection/coefficient_matrices
    (VAR(k_ar_diff+1) в уровнях)/in_sample_residuals -- вход диагностики
    vecm_stability/system_white_noise_diagnostics (Task 131/133) на движке.
    random_state принят по контракту реестра: VECM -- детерминированная
    оценка, случайности нет.
    """
    if int(horizon) < 1:
        raise ValueError("VECM: horizon должен быть положительным")
    normalized = validate_vecm_params(params)
    matrix, series_names = _validated_matrix(target, related_series)
    nobs, k = matrix.shape
    if nobs < VECM_MIN_TRAIN:
        raise ValueError(
            f"VECM: история слишком короткая ({nobs} наблюдений); минимум "
            f"{VECM_MIN_TRAIN} (MIN_SYSTEM_OBSERVATIONS контракта Task 131)"
        )
    k_ar_diff = normalized["k_ar_diff"]
    if not _search_bound_ok(nobs, k, k_ar_diff):
        raise ValueError(
            f"VECM: история слишком короткая ({nobs} наблюдений) для "
            f"k_ar_diff={k_ar_diff} при K={k}; уменьшите k_ar_diff или "
            "увеличьте train-срез"
        )
    rank = normalized["coint_rank"]
    rank_selection: dict[str, Any]
    if rank == RANK_AUTO:
        rank, rank_selection = _select_coint_rank_auto(
            matrix, det_order=DET_ORDER_BY_DETERMINISTIC[normalized["deterministic"]],
            k_ar_diff=k_ar_diff,
        )
    else:
        if rank > k - 1:
            raise ValueError(
                f"VECM: coint_rank={rank} превышает K-1={k - 1} "
                f"(ранг Йохансена строго меньше числа рядов)"
            )
        rank_selection = {
            "mode": "fixed", "selected_rank": int(rank),
            "det_order": DET_ORDER_BY_DETERMINISTIC[normalized["deterministic"]],
            "signif": None, "k_ar_diff": k_ar_diff,
        }

    from statsmodels.tsa.vector_ar.vecm import VECM as _StatsmodelsVECM

    try:
        model = _StatsmodelsVECM(
            matrix, k_ar_diff=k_ar_diff, coint_rank=rank,
            deterministic=normalized["deterministic"],
        )
        fitted = model.fit()
        point, lower, upper = fitted.predict(
            steps=int(horizon), alpha=normalized["alpha"],
        )
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 -- library-native отказ = ошибка fold'а
        raise ValueError(
            f"VECM: fit/predict недоступен на переданном train-срезе: {exc}"
        ) from exc

    forecast = np.asarray(point, dtype=float)
    lower_matrix = np.asarray(lower, dtype=float)
    upper_matrix = np.asarray(upper, dtype=float)
    if forecast.shape != (int(horizon), k):
        raise ValueError(
            f"VECM: statsmodels вернул прогноз формы {forecast.shape}, ожидалось "
            f"({int(horizon)}, {k})"
        )
    # Инвариант реестра lower <= point <= upper обязан держаться нативно;
    # численная защита от вырожденного квантиля (не меняет честный прогноз).
    lower_matrix = np.minimum(lower_matrix, forecast)
    upper_matrix = np.maximum(upper_matrix, forecast)
    coefficient_matrices = [
        np.asarray(block, dtype=float) for block in fitted.var_rep
    ]
    return {
        "series_names": series_names,
        "forecast": forecast,
        "lower": lower_matrix,
        "upper": upper_matrix,
        "k_ar_diff": k_ar_diff,
        "coint_rank": int(rank),
        "rank_selection": rank_selection,
        "deterministic_terms": normalized["deterministic"],
        "alpha": normalized["alpha"],
        "nobs": int(fitted.nobs),
        "coefficient_matrices": coefficient_matrices,
        "in_sample_residuals": np.asarray(fitted.resid, dtype=float),
        "random_state": int(random_state),
        "deterministic": True,
    }


def run_vecm_backtest(
    series: Sequence[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """Legacy synthetic-demo эндпоинт (POST /v1/models/backtest), сигнатура
    как у остальных model_impls.  Task 133: VECM требует систему K>=2 --
    на одиночном синтетическом ряде исполнение НЕВОЗМОЖНО без подмены.
    Никаких синтетических многомерных демо и Naive-fallback: честный отказ
    (ValueError), как и у VAR (Task 132)."""
    raise ValueError(
        "VECM требует не менее 2 endogenous-рядов (target + related_series); "
        "однорядный synthetic-эндпоинт не применим -- исполняйте VECM через "
        "многомерный session backtest (run_vector_backtest_plan)"
    )


__all__ = [
    "ALPHA_OPTIONS",
    "DEFAULT_PARAMS",
    "DET_ORDER_BY_DETERMINISTIC",
    "DETERMINISTIC_OPTIONS",
    "PARAM_BOUNDS",
    "RANK_AUTO",
    "TARGET_PLACEHOLDER",
    "VECM_ADAPTER_ID",
    "VECM_MIN_TRAIN",
    "_vecm_fit_predict",
    "run_vecm_backtest",
    "validate_vecm_params",
]
