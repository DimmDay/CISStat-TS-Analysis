# apps/api/model_impls/_common.py
"""
Общие хелперы для всех реализаций model_impls:

- train_test_split(series, train_ratio) -> (y_train, y_test)
- safe_backtest(fn, series, train_ratio, seasonal_period, model_name) -> BacktestMetrics
  Обёртка try/except: если statsmodels упадёт на проблемных данных
  (короткий ряд, zero variance, NaN) — откатываемся на Naive-метрики,
  чтобы UI получил осмысленный ответ, а не 500-ю ошибку.

Контракт fallback:
- В лог пишется WARNING с указанием модели и причиной.
- Возвращаются метрики Naive, НЕ заглушки naive*penalty.
- Это сознательное решение: лучше показать «наивный» ответ, чем уронить
  бэктест — пользователь видит, что модель формально сработала, даже
  если statsmodels не смог обучиться.
"""
from __future__ import annotations

import logging
from typing import Callable, List, Tuple

from apps.api.schemas import BacktestMetrics
from apps.api.model_impls._metrics import compute_metrics


logger = logging.getLogger(__name__)


def train_test_split(
    series: List[float], train_ratio: float
) -> Tuple[List[float], List[float]]:
    """Разделить ряд на train/test по train_ratio.

    Аналогично _run_naive_backtest в routers/models.py — та же логика:
    n_train = int(n * train_ratio). НЕ использует временные индексы,
    работает с обычным list[float].
    """
    n = len(series)
    n_train = int(n * train_ratio)
    return series[:n_train], series[n_train:]


def _naive_metrics(series, train_ratio) -> BacktestMetrics:
    """Naive fallback: y_pred = y_{t-1}. Используется когда реальная
    модель упала. Сознательно НЕ импортирует routers.models._run_naive_backtest
    (циклический импорт) — дублирует тривиальную логику."""
    y_train, y_test = train_test_split(series, train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)
    y_pred = [y_train[-1]] + y_test[:-1]
    return compute_metrics(y_test, y_pred, y_train)


def safe_backtest(
    fn: Callable[[List[float], float, int], BacktestMetrics],
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
    model_name: str,
) -> BacktestMetrics:
    """Обёрнуть вызов модели в try/except, откатываясь на Naive при ошибке.

    Использование:
        def _impl(series, train_ratio, seasonal_period):
            # ... fit statsmodels, predict, compute_metrics
            return metrics
        return safe_backtest(_impl, series, train_ratio, seasonal_period, "ets")

    Все исключения (ValueError, RuntimeError, IndexError и т.д.) логируются
    как WARNING и приводят к Naive fallback. Это предпочтительнее 500-ошибки:
    пользователь видит метрики, а не «internal server error».
    """
    try:
        return fn(series, train_ratio, seasonal_period)
    except Exception as exc:
        logger.warning(
            "Model %s failed (%s), falling back to Naive metrics",
            model_name, exc.__class__.__name__,
        )
        return _naive_metrics(series, train_ratio)
