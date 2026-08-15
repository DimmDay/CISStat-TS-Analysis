"""Shared real-model prediction adapters used by hyperparameter tuning."""
from __future__ import annotations

from typing import Any, Dict, List

from apps.api.model_impls.arima import _arima_fit_predict
from apps.api.model_impls.ets import _ets_fit_predict


def tune_ets_predict(
    y_train: List[float],
    n_test: int,
    params: Dict[str, Any],
) -> List[float]:
    """Fit/forecast ETS using the exact parameters from one grid trial."""
    trend = params.get("trend", "add")
    seasonal = params.get("seasonal")
    seasonal_period = int(params.get("seasonal_periods", 12))
    damped = bool(params.get("damped_trend", False))

    if trend == "mul" and any(value <= 0 for value in y_train):
        raise ValueError("multiplicative ETS trend requires strictly positive data")
    if seasonal == "mul" and any(value <= 0 for value in y_train):
        raise ValueError(
            "multiplicative ETS seasonality requires strictly positive data"
        )

    return _ets_fit_predict(
        y_train=y_train,
        n_test=n_test,
        seasonal_period=seasonal_period,
        damped=damped,
        trend=trend,
        seasonal=seasonal,
    )


def tune_arima_predict(
    y_train: List[float],
    n_test: int,
    params: Dict[str, Any],
) -> List[float]:
    """Fit/forecast ARIMA using the exact (p,d,q) grid-trial parameters."""
    order = (
        int(params["p"]),
        int(params["d"]),
        int(params["q"]),
    )
    return _arima_fit_predict(y_train, n_test, order)
