"""Phase 2 integration tests: diagnostics over real ETS/ARIMA residuals."""
from __future__ import annotations

import math

import numpy as np

from apps.api.routers.diagnostics import _diagnose, _fit_residuals


def _seasonal_series(n: int = 72) -> list[float]:
    return [
        100.0 + 0.35 * t + 7.0 * math.sin(2.0 * math.pi * t / 12.0) + 1.5 * math.sin(t)
        for t in range(n)
    ]


def _arima_series(n: int = 80) -> list[float]:
    values = [100.0]
    for t in range(1, n):
        values.append(values[-1] + 0.25 + 0.8 * math.sin(t / 5.0))
    return values


def test_ets_diagnostics_use_real_statsmodels_residuals() -> None:
    residuals = _fit_residuals(
        "ets",
        _seasonal_series(),
        {"trend": "add", "seasonal": "add", "seasonal_periods": 12},
    )
    assert residuals.ndim == 1
    assert len(residuals) >= 72
    assert np.isfinite(residuals).all()

    results = _diagnose(residuals, alpha=0.05, ljung_box_lags=10, arch_lags=5)
    assert {item.test for item in results} == {
        "ljung_box", "jarque_bera", "arch_lm", "durbin_watson"
    }
    assert all(item.applicable for item in results)
    assert all(item.statistic is not None for item in results)
    assert all(item.p_value is not None for item in results if item.test != "durbin_watson")


def test_arima_diagnostics_use_real_statsmodels_residuals() -> None:
    residuals = _fit_residuals(
        "arima",
        _arima_series(),
        {"p": 1, "d": 1, "q": 1},
    )
    assert residuals.ndim == 1
    assert len(residuals) >= 80
    assert np.isfinite(residuals).all()

    results = _diagnose(residuals, alpha=0.05, ljung_box_lags=10, arch_lags=5)
    assert len(results) == 4
    assert all(item.applicable for item in results)


def test_ljung_box_is_marked_not_applicable_when_requested_lag_exceeds_sample() -> None:
    residuals = np.arange(8, dtype=float)
    results = _diagnose(residuals, alpha=0.05, ljung_box_lags=10, arch_lags=2)
    ljung_box = next(item for item in results if item.test == "ljung_box")
    assert ljung_box.applicable is False
    assert ljung_box.p_value is None
    assert "n_observations" in ljung_box.applicable_if


def test_arch_lm_is_not_applicable_for_constant_residuals() -> None:
    residuals = np.ones(20, dtype=float)
    results = _diagnose(residuals, alpha=0.05, ljung_box_lags=5, arch_lags=5)
    arch = next(item for item in results if item.test == "arch_lm")
    assert arch.applicable is False
    assert arch.p_value is None
    assert arch.reason


def test_diagnostic_statuses_are_bounded_to_ui_contract() -> None:
    residuals = _fit_residuals("arima", _arima_series(), {"p": 1, "d": 1, "q": 1})
    results = _diagnose(residuals, alpha=0.05, ljung_box_lags=5, arch_lags=5)
    assert all(item.status in {"pass", "warning", "fail"} for item in results)