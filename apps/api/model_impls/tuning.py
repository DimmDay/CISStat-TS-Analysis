"""Shared real-model prediction adapters used by hyperparameter tuning."""
from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

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
    # statsmodels ARIMA is sensitive to the representation of very small
    # pandas inputs on some Windows/Python combinations. Normalize once at
    # the adapter boundary to a 1-D numeric array.
    train = np.asarray(y_train, dtype=np.float64).reshape(-1)
    if train.size == 0:
        raise ValueError("ARIMA requires at least one training observation")
    return _arima_fit_predict(train.tolist(), n_test, order)