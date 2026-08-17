# apps/api/model_impls/theta.py
"""
Theta-метод — формальная модель из Forecasting with Theta Method (Assimakopoulos & Nikolopoulos 2000).

Использует statsmodels.tsa.forecasting.theta.ThetaModel (доступен с statsmodels 0.12+).
Это полноценная реализация: декомпозиция ряда на тренд и сезонность,
линейная экстраполяция тренда + second-order differencing для theta=2.

Контракт: на входе list[float], на выходе BacktestMetrics.
"""
from __future__ import annotations

import logging
from typing import List

import pandas as pd

from apps.api.schemas import BacktestMetrics
from apps.api.model_impls._common import safe_backtest, train_test_split
from apps.api.model_impls._metrics import compute_metrics


logger = logging.getLogger(__name__)


def _theta_fit_predict(
    y_train: List[float],
    n_test: int,
    seasonal_period: int,
) -> List[float]:
    """Обучить ThetaModel на y_train, предсказать n_test точек.

    ThetaModel требует:
    - не менее 2 наблюдений (для лин. регрессии на тренд)
    - период сезонности, если она есть (period >= 2)
    - ряд НЕ должен быть константой (variance > 0) — иначе падает на
      линейной регрессии и возвращает NaN forecast (численная нестабильность).

    Для константного ряда возвращаем [y_train[-1]] * n_test (Naive forecast
    на константе = сама константа = 0 ошибок). Это согласовано с поведением
    других моделей на константных рядах.

    Возвращает list[float] длины n_test.
    """
    from statsmodels.tsa.forecasting.theta import ThetaModel

    # Edge case: константный ряд. ThetaModel пытается обучить линейную
    # регрессию на тренд, что для константы даёт NaN (variance=0).
    # Возвращаем Naive forecast = y_train[-1] (для константного ряда
    # это сама константа).
    if len(set(y_train)) == 1:
        return [y_train[-1]] * n_test

    # ThetaModel требует PeriodIndex или DatetimeIndex с частотой.
    # Создаём RangeIndex с фиксированной частотой через период.
    idx = pd.RangeIndex(start=0, stop=len(y_train))
    train = pd.Series(y_train, index=idx)

    # ThetaModel требует period при deseasonalize=True (дефолт).
    # Если сезонности нет (seasonal_period<=1) или ряд слишком короткий
    # для определения сезонности — отключаем deseasonalize.
    use_seasonal = (
        seasonal_period > 1
        and len(y_train) >= 2 * seasonal_period
    )

    kwargs = dict(
        period=seasonal_period if use_seasonal else None,
        deseasonalize=use_seasonal,
    )
    kwargs = {k: v for k, v in kwargs.items() if v is not None}

    model = ThetaModel(train, method="auto", **kwargs)
    fitted = model.fit()
    forecast = fitted.forecast(steps=n_test)
    return list(forecast)


def _theta_backtest_impl(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """Чистая реализация (без safe_backtest)."""
    y_train, y_test = train_test_split(series, train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)

    y_pred = _theta_fit_predict(
        y_train=y_train,
        n_test=len(y_test),
        seasonal_period=seasonal_period,
    )
    return compute_metrics(y_test, y_pred, y_train)


def run_theta_backtest(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """Theta: формальная Theta-модель (Assimakopoulos & Nikolopoulos 2000).

    Реализует: ряд = тренд + второй-difference компонент. Forecast = лин.
    экстраполяция тренда + 0.5 * (forecast from theta=2). Часто побеждает
    на ежемесячных данных с трендом и слабой сезонностью.

    Edge cases, обрабатываемые safe_backtest:
    - Константный ряд → ValueError в линейной регрессии → Naive fallback.
    - Слишком короткий ряд (<4 точек) → ValueError → Naive fallback.
    """
    return safe_backtest(
        _theta_backtest_impl,
        series, train_ratio, seasonal_period, "theta",
    )
