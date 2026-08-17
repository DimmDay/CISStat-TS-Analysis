"""Session-backed residual diagnostics for standalone/embedded UI (Phase 2)."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from apps.api.routers.diagnostics import _diagnose, _fit_residuals, DiagnosticResult
from apps.api.session_store import get_or_create_session_id, get_session_store

router = APIRouter()


class InternalDiagnosticsRequest(BaseModel):
    model_id: str
    params: Dict[str, Any] = Field(default_factory=dict)
    ljung_box_lags: Optional[int] = Field(None, ge=1, le=50)
    arch_lags: Optional[int] = Field(None, ge=1, le=20)
    alpha: float = Field(0.05, gt=0, lt=1)


class InternalDiagnosticsResponse(BaseModel):
    model_id: str
    target_column: str
    n_observations: int
    residuals_count: int
    alpha: float
    diagnostics: list[DiagnosticResult]


@router.post("/models/diagnostics", response_model=InternalDiagnosticsResponse)
def run_internal_diagnostics(
    payload: InternalDiagnosticsRequest,
    request: Request,
    response: Response,
) -> InternalDiagnosticsResponse:
    """Run diagnostics on the session's selected real target series.

    The browser never sends raw observations back to the API. The endpoint
    resolves the current AnalysisSession by cookie and uses its persisted
    target_column/dataframe. This keeps diagnostics aligned with Backtest and
    avoids a second client-side source of truth for the time series.
    """
    session_id = get_or_create_session_id(request, response)
    session = get_session_store().get_or_create(session_id)

    if session.dataframe is None:
        raise HTTPException(status_code=400, detail="Dataset is not loaded in the current session")
    if not session.target_column:
        raise HTTPException(status_code=400, detail="Target column is not selected")
    if session.target_column not in [str(c) for c in session.dataframe.columns]:
        raise HTTPException(status_code=400, detail="Selected target column is not present in the dataset")

    values = session.dataframe[session.target_column]
    if values.dtype.kind not in "biufc":
        raise HTTPException(status_code=422, detail="Target column must be numeric")

    series = values.dropna().astype(float).tolist()
    try:
        residuals = _fit_residuals(payload.model_id, series, payload.params)
        diagnostics = _diagnose(
            residuals,
            payload.alpha,
            payload.ljung_box_lags,
            payload.arch_lags,
        )
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return InternalDiagnosticsResponse(
        model_id=payload.model_id,
        target_column=session.target_column,
        n_observations=len(series),
        residuals_count=int(residuals.size),
        alpha=payload.alpha,
        diagnostics=diagnostics,
    )
