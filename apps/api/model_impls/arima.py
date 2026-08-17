"""
ARIMA и Auto-ARIMA — авторегрессия + интеграция + скользящее среднее.

Две реализации:
- run_arima_backtest: фиксированный порядок (1, 1, 1) — стандартный
  «обычный» ARIMA, разумный дефолт для большинства бизнес-рядов.
- run_auto_arima_backtest: grid search по (p, d, q) с AIC-критерием.
  Реализован через statsmodels (НЕ pmdarima) — grid over
  p in {0,1}, d in {0,1}, q in {0,1} = 8 моделей. Выбираем
  модель с минимальным AIC, затем forecast.

Контракт: на входе list[float], на выходе BacktestMetrics.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from apps.api.schemas import BacktestMetrics
from apps.api.model_impls._common import safe_backtest, train_test_split
from apps.api.model_impls._metrics import compute_metrics


logger = logging.getLogger(__name__)


DEFAULT_ARIMA_ORDER: Tuple[int, int, int] = (1, 1, 1)

AUTO_ARIMA_GRID: List[Tuple[int, int, int]] = [
    (p, d, q)
    for p in (0, 1)
    for d in (0, 1)
    for q in (0, 1)
]


def _arima_fit_predict(
    y_train: List[float],
    n_test: int,
    order: Tuple[int, int, int],
) -> List[float]:
    """Обучить ARIMA(y_train, order=order), forecast n_test шагов."""
    from statsmodels.tsa.arima.model import ARIMA

    train = np.asarray(y_train, dtype=np.float64).reshape(-1)
    if train.size == 0:
        raise ValueError("ARIMA requires at least one training observation")
    if not np.isfinite(train).all():
        raise ValueError("ARIMA requires finite numeric observations")

    # Explicit 1-D ndarray avoids a statsmodels 0-D endog edge case seen on
    # Windows/Python 3.13 for short CV folds when a pandas scalar-like input
    # reaches SARIMAX conditional-sum-of-squares initialization.
    model = ARIMA(train, order=order)
    fitted = model.fit()
    forecast = np.asarray(fitted.forecast(steps=n_test), dtype=np.float64).reshape(-1)
    return forecast.tolist()


def _arima_backtest_impl(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
    order: Tuple[int, int, int] = DEFAULT_ARIMA_ORDER,
) -> BacktestMetrics:
    """Чистая реализация ARIMA. seasonal_period игнорируется."""
    y_train, y_test = train_test_split(series, train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)

    y_pred = _arima_fit_predict(
        y_train=y_train,
        n_test=len(y_test),
        order=order,
    )
    return compute_metrics(y_test, y_pred, y_train)


def _auto_arima_select_order(
    y_train: List[float],
) -> Tuple[int, int, int]:
    """Выбрать оптимальный (p, d, q) по AIC."""
    from statsmodels.tsa.arima.model import ARIMA

    best_aic: Optional[float] = None
    best_order: Tuple[int, int, int] = DEFAULT_ARIMA_ORDER
    train = np.asarray(y_train, dtype=np.float64).reshape(-1)

    for order in AUTO_ARIMA_GRID:
        try:
            model = ARIMA(train, order=order)
            fitted = model.fit()
            aic = fitted.aic
            if best_aic is None or aic < best_aic:
                best_aic = aic
                best_order = order
        except Exception as exc:
            logger.debug(
                "ARIMA order %s failed (%s), skipping",
                order,
                exc.__class__.__name__,
            )
            continue

    logger.debug(
        "Auto-ARIMA selected order %s (AIC=%s, train_len=%d)",
        best_order,
        best_aic,
        len(y_train),
    )
    return best_order


def _auto_arima_backtest_impl(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """Чистая реализация Auto-ARIMA: grid search по (p,d,q) с AIC."""
    y_train, y_test = train_test_split(series, train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)

    best_order = _auto_arima_select_order(y_train)
    y_pred = _arima_fit_predict(
        y_train=y_train,
        n_test=len(y_test),
        order=best_order,
    )
    return compute_metrics(y_test, y_pred, y_train)


def run_arima_backtest(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """ARIMA(1,1,1): фиксированный порядок."""
    return safe_backtest(
        _arima_backtest_impl,
        series, train_ratio, seasonal_period, "arima",
    )


def run_auto_arima_backtest(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """Auto-ARIMA: grid search по (p,d,q) ∈ {0,1} × {0,1} × {0,1} = 8 моделей."""
    return safe_backtest(
        _auto_arima_backtest_impl,
        series, train_ratio, seasonal_period, "arima_auto",
    )
