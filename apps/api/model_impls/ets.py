# apps/api/model_impls/ets.py
"""
ETS (Error, Trend, Seasonality) — экспоненциальное сглаживание.

Две реализации:
- run_ets_backtest: Holt-Winters auto (подбирает trend/seasonal по данным)
- run_ets_damped_backtest: то же, но damped_trend=True (затухающий тренд)

Использует statsmodels.tsa.holtwinters.ExponentialSmoothing. Не путать
с ETS-полным state-space моделью (та в statsmodels.tsa.exponential_smoothing.ets.ETSModel) —
ExponentialSmoothing классическая, быстрее и стабильнее сходится,
что важно для Phase 6-P0 (надёжность > точности).

Контракт: на входе list[float], на выходе BacktestMetrics. Сигнатура
совпадает с другими функциями в _BACKTEST_IMPLEMENTATIONS:
    fn(series, train_ratio, seasonal_period) -> BacktestMetrics
"""
from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np
import pandas as pd

from apps.api.schemas import BacktestMetrics
from apps.api.model_impls._common import safe_backtest, train_test_split
from apps.api.model_impls._metrics import compute_metrics


logger = logging.getLogger(__name__)


def _ets_fit_predict(
    y_train: List[float],
    n_test: int,
    seasonal_period: int,
    damped: bool,
    trend: str = "add",
    seasonal: Optional[str] = "add",
) -> List[float]:
    """Обучить ETS на y_train, предсказать n_test точек.

    ``trend`` и ``seasonal`` опциональны для backward compatibility с
    Phase 6-P0 backtest; tuning передаёт их явно из param_space.
    Мультипликативные варианты требуют строго положительный ряд.
    """
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    if trend not in {"add", "mul", None}:
        raise ValueError(f"Unsupported ETS trend: {trend!r}")
    if seasonal not in {"add", "mul", None}:
        raise ValueError(f"Unsupported ETS seasonal: {seasonal!r}")
    if trend == "mul" and any(value <= 0 for value in y_train):
        raise ValueError("multiplicative ETS trend requires strictly positive data")
    if seasonal == "mul" and any(value <= 0 for value in y_train):
        raise ValueError("multiplicative ETS seasonality requires strictly positive data")

    # Для сезонности нужно >= 2 полных периода. Иначе trial без сезонности
    # выполняется явно, вместо падения statsmodels.
    use_seasonal = (
        seasonal is not None
        and seasonal_period > 1
        and len(y_train) >= 2 * seasonal_period
    )

    train = pd.Series(
        y_train, index=pd.RangeIndex(start=0, stop=len(y_train))
    )

    kwargs = dict(
        trend=trend,
        damped_trend=damped,
        seasonal=seasonal if use_seasonal else None,
        seasonal_periods=seasonal_period if use_seasonal else None,
        initialization_method="estimated",
    )
    kwargs = {k: v for k, v in kwargs.items() if v is not None}

    model = ExponentialSmoothing(train, **kwargs)
    fitted = model.fit()
    forecast = fitted.forecast(steps=n_test)
    return list(forecast)


def _ets_backtest_impl(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
    damped: bool,
) -> BacktestMetrics:
    """Чистая реализация (без safe_backtest-обёртки)."""
    y_train, y_test = train_test_split(series, train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)

    y_pred = _ets_fit_predict(
        y_train=y_train,
        n_test=len(y_test),
        seasonal_period=seasonal_period,
        damped=damped,
    )
    return compute_metrics(y_test, y_pred, y_train)


def run_ets_backtest(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """ETS (Auto): Holt-Winters без затухания тренда.

    Сезонность: аддитивная, если seasonal_period > 1 и данных достаточно
    (>= 2 полных периодов в train). Иначе — без сезонности.
    """
    return safe_backtest(
        lambda s, tr, p: _ets_backtest_impl(s, tr, p, damped=False),
        series, train_ratio, seasonal_period, "ets",
    )


def run_ets_damped_backtest(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """ETS Damped: то же, но damped_trend=True (затухающий тренд)."""
    return safe_backtest(
        lambda s, tr, p: _ets_backtest_impl(s, tr, p, damped=True),
        series, train_ratio, seasonal_period, "ets_damped",
    )
