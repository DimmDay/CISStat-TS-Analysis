# apps/api/model_impls/__init__.py
"""
Phase 6-P0: реальные реализации 5 моделей прогнозирования.

До Phase 6-P0: только 4 baseline (naive, seasonal_naive, drift, mean).
ETS / ETS Damped / Theta / ARIMA / Auto-ARIMA возвращали «Naive × penalty»
заглушку (см. routers/models.py _run_backtest_with_series, else-ветка).

После Phase 6-P0: каждая из 5 моделей вызывает statsmodels, обучается
на train-части ряда, прогнозирует test-часть и возвращает реальные метрики.

Реализации:
- ets.py — Holt-Winters ExponentialSmoothing (ETS Auto + ETS Damped)
- theta.py — ThetaModel (формальная Theta-модель)
- arima.py — ARIMA(1,1,1) + Auto-ARIMA (grid search по AIC)

Все функции имеют одинаковую сигнатуру, совместимую с
_BACKTEST_IMPLEMENTATIONS в routers/models.py:
    fn(series: list[float], train_ratio: float, seasonal_period: int)
        -> BacktestMetrics

Обёртка safe_backtest (в _common.py) ловит исключения statsmodels
(короткий ряд, константа, NaN) и откатывается на Naive-метрики,
чтобы UI не получал 500-ю ошибку.
"""
from apps.api.model_impls.ets import (
    run_ets_backtest,
    run_ets_damped_backtest,
)
from apps.api.model_impls.theta import run_theta_backtest
from apps.api.model_impls.arima import (
    run_arima_backtest,
    run_auto_arima_backtest,
)


__all__ = [
    "run_ets_backtest",
    "run_ets_damped_backtest",
    "run_theta_backtest",
    "run_arima_backtest",
    "run_auto_arima_backtest",
]
