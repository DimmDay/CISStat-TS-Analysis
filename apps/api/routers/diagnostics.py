"""Residual diagnostics for real fitted ETS/ARIMA models (Phase 2)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from scipy.stats import jarque_bera
from statsmodels.stats.diagnostic import acorr_ljungbox, het_arch
from statsmodels.stats.stattools import durbin_watson

from apps.api.auth import require_capability, get_current_principal
from apps.api.model_impls.ets import _ets_fit_predict
from apps.api.model_impls.arima import _arima_fit_predict
from apps.api.plans import AuthenticatedPrincipal

router = APIRouter()


class DiagnosticsRequest(BaseModel):
    model_id: str
    series: List[float] = Field(..., min_length=8)
    params: Dict[str, Any] = Field(default_factory=dict)
    ljung_box_lags: Optional[int] = Field(None, ge=1, le=50)
    arch_lags: Optional[int] = Field(None, ge=1, le=20)
    alpha: float = Field(0.05, gt=0, lt=1)


class DiagnosticResult(BaseModel):
    test: str
    applicable: bool
    applicable_if: str
    statistic: Optional[float] = None
    p_value: Optional[float] = None
    status: str
    reason: Optional[str] = None


class DiagnosticsResponse(BaseModel):
    model_id: str
    n_observations: int
    residuals_count: int
    alpha: float
    diagnostics: List[DiagnosticResult]


def _fit_residuals(model_id: str, series: List[float], params: Dict[str, Any]) -> np.ndarray:
    """Fit the real Phase-6 model and return in-sample residuals."""
    y = np.asarray(series, dtype=np.float64).reshape(-1)
    if y.size < 8:
        raise ValueError("At least 8 observations are required")
    if not np.isfinite(y).all():
        raise ValueError("Series must contain only finite numeric values")

    if model_id in {"ets", "ets_damped"}:
        trend = params.get("trend", "add")
        seasonal = params.get("seasonal")
        seasonal_period = int(params.get("seasonal_periods", 12))
        damped = bool(params.get("damped_trend", model_id == "ets_damped"))
        if trend == "mul" and np.any(y <= 0):
            raise ValueError("multiplicative ETS trend requires strictly positive data")
        if seasonal == "mul" and np.any(y <= 0):
            raise ValueError("multiplicative ETS seasonality requires strictly positive data")

        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        use_seasonal = seasonal is not None and seasonal_period > 1 and y.size >= 2 * seasonal_period
        kwargs: Dict[str, Any] = {
            "trend": trend,
            "damped_trend": damped,
            "seasonal": seasonal if use_seasonal else None,
            "seasonal_periods": seasonal_period if use_seasonal else None,
            "initialization_method": "estimated",
        }
        kwargs = {k: v for k, v in kwargs.items() if v is not None}
        fitted = ExponentialSmoothing(y, **kwargs).fit()
        residuals = np.asarray(fitted.resid, dtype=np.float64).reshape(-1)
    elif model_id == "arima":
        from statsmodels.tsa.arima.model import ARIMA

        order = (int(params.get("p", 1)), int(params.get("d", 1)), int(params.get("q", 1)))
        fitted = ARIMA(y, order=order).fit()
        residuals = np.asarray(fitted.resid, dtype=np.float64).reshape(-1)
    else:
        raise ValueError(f"Residual diagnostics are not implemented for model '{model_id}'")

    residuals = residuals[np.isfinite(residuals)]
    if residuals.size < 8:
        raise ValueError("Fitted model produced fewer than 8 finite residuals")
    return residuals


def _status_from_pvalue(p_value: float, alpha: float) -> str:
    if p_value < alpha / 5:
        return "fail"
    if p_value < alpha:
        return "warning"
    return "pass"


def _diagnose(residuals: np.ndarray, alpha: float, ljung_box_lags: Optional[int], arch_lags: Optional[int]) -> List[DiagnosticResult]:
    n = int(residuals.size)
    lb_lags = ljung_box_lags or min(10, n - 1)
    arch_max = min(10, max(1, n // 5))
    arch_n = arch_lags or arch_max

    results: List[DiagnosticResult] = []

    if n <= lb_lags:
        results.append(DiagnosticResult(
            test="ljung_box", applicable=False,
            applicable_if=f"n_observations > lags ({lb_lags})",
            status="warning", reason="Not enough residuals for the requested lag count",
        ))
    else:
        lb = acorr_ljungbox(residuals, lags=[lb_lags], return_df=True).iloc[-1]
        p = float(lb["lb_pvalue"])
        results.append(DiagnosticResult(
            test="ljung_box", applicable=True,
            applicable_if=f"n_observations > lags ({lb_lags})",
            statistic=float(lb["lb_stat"]), p_value=p,
            status=_status_from_pvalue(p, alpha),
        ))

    if n < 8:
        results.append(DiagnosticResult(
            test="jarque_bera", applicable=False,
            applicable_if="n_observations >= 8",
            status="warning", reason="Not enough residuals",
        ))
    else:
        jb = jarque_bera(residuals)
        p = float(jb.pvalue)
        results.append(DiagnosticResult(
            test="jarque_bera", applicable=True,
            applicable_if="n_observations >= 8",
            statistic=float(jb.statistic), p_value=p,
            status=_status_from_pvalue(p, alpha),
        ))

    if n <= arch_n + 1:
        results.append(DiagnosticResult(
            test="arch_lm", applicable=False,
            applicable_if=f"n_observations > arch_lags + 1 ({arch_n + 1})",
            status="warning", reason="Not enough residuals for ARCH-LM",
        ))
    elif np.std(residuals) <= np.finfo(float).eps:
        results.append(DiagnosticResult(
            test="arch_lm", applicable=False,
            applicable_if="residual variance > 0 and sufficient observations",
            status="warning", reason="Residual variance is effectively zero",
        ))
    else:
        lm_stat, lm_pvalue, _, _ = het_arch(residuals, nlags=arch_n)
        p = float(lm_pvalue)
        results.append(DiagnosticResult(
            test="arch_lm", applicable=True,
            applicable_if=f"n_observations > arch_lags + 1 ({arch_n + 1}) and residual variance > 0",
            statistic=float(lm_stat), p_value=p,
            status=_status_from_pvalue(p, alpha),
        ))

    dw = float(durbin_watson(residuals))
    distance = abs(dw - 2.0)
    status = "pass" if distance <= 0.5 else ("warning" if distance <= 1.0 else "fail")
    results.append(DiagnosticResult(
        test="durbin_watson", applicable=True,
        applicable_if="finite residuals with at least 2 observations",
        statistic=dw, p_value=None, status=status,
    ))
    return results


@router.post(
    "/diagnostics",
    response_model=DiagnosticsResponse,
    dependencies=[Depends(require_capability("can_train_models"))],
)
def run_diagnostics(
    payload: DiagnosticsRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> DiagnosticsResponse:
    try:
        residuals = _fit_residuals(payload.model_id, payload.series, payload.params)
        diagnostics = _diagnose(
            residuals,
            payload.alpha,
            payload.ljung_box_lags,
            payload.arch_lags,
        )
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DiagnosticsResponse(
        model_id=payload.model_id,
        n_observations=len(payload.series),
        residuals_count=int(residuals.size),
        alpha=payload.alpha,
        diagnostics=diagnostics,
    )
