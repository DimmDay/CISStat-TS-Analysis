# apps/api/routers/monitoring.py
"""
DOCLOG-8 (spec_documentation_logging.md §6 D12, §17, §19 строка
DOCLOG-8): API контура мониторинга /v1/documentation/runs/{run_id}/
monitoring/* -- регистрация actual vintages, frozen сверки, append-only
решения. Семантика §17: 201 создание; uniform 404 для чужого
run/анонима (решающая таблица DOCLOG-0 -- существование не
дисклоужается); 409 идемпотентность; 422 некорректный запрос/отказ с
причиной (units mismatch AC15); тело ошибки -- плоский
{code, message, request_id} БЕЗ traceback/SQL/DSN (паритет
routers/logs.py DOCLOG-7).

GET не меняет исследовательское состояние (§17: только security audit
факта доступа -- стандартные записи решающей таблицы). Построение
сверки НЕ пересчитывает прогноз и НЕ мутирует научный слой (AC05-дух);
решение человека -- append-only запись (§6.1).
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse

router = APIRouter()

_RUN_NOT_FOUND_DETAIL = {
    "code": "run_not_found_or_forbidden",
    "message": "Run не найден или доступ запрещён",
}


# ── Доступ: паритет routers/documentation.py (единая точка §15.1) ────


def _subject_and_session(request: Request) -> tuple[Any, str]:
    from apps.api.routers.documentation import _subject_and_session as impl

    return impl(request)


def _authorized_run_or_404(request: Request, run_id: str, *, action: str) -> Any:
    from apps.api.routers.documentation import (
        _authorized_run_or_404 as impl,
    )

    return impl(request, run_id, action=action)


def _service():
    from apps.api.monitoring import MonitoringService

    return MonitoringService.create_default()


def _error_response(
    exc: Exception, *, fallback_detail: dict[str, str] | None = None
) -> JSONResponse:
    """§17-семантикаMonitoringService -> плоское {code, message} без
    traceback/SQL/DSN (паритет routers/logs.py)."""
    from apps.api.monitoring import (
        MonitoringAccessDenied,
        MonitoringError,
        MonitoringForecastUnavailable,
        MonitoringIdempotencyConflictError,
        MonitoringNotFoundError,
        MonitoringUnitsMismatchError,
        MonitoringValidationError,
    )
    from apps.api.telemetry import current_request_id

    if isinstance(exc, MonitoringValidationError):
        status, code = 422, "monitoring_validation_error"
    elif isinstance(exc, MonitoringUnitsMismatchError):
        status, code = 422, "monitoring_units_mismatch"
    elif isinstance(exc, MonitoringIdempotencyConflictError):
        status, code = 409, "monitoring_idempotency_conflict"
    elif isinstance(exc, MonitoringForecastUnavailable):
        status, code = 404, "monitoring_forecast_unavailable"
    elif isinstance(exc, MonitoringNotFoundError):
        status, code = 404, "monitoring_not_found"
    elif isinstance(exc, MonitoringAccessDenied):
        # Uniform 404: существование чужого не дисклоужается (§17).
        return JSONResponse(
            status_code=404,
            content={
                **_RUN_NOT_FOUND_DETAIL,
                "request_id": current_request_id(),
            },
        )
    elif isinstance(exc, MonitoringError):
        status, code = 500, "monitoring_internal"
    else:
        status, code = 500, "monitoring_internal"
    return JSONResponse(
        status_code=status,
        content={
            "code": code,
            "message": str(exc),
            "request_id": current_request_id(),
        },
    )


def _batch_json(record: Any) -> dict[str, Any]:
    return record.to_dict()


def _comparison_json(record: Any) -> dict[str, Any]:
    return record.to_dict()


# ── Actual vintages (B07: дата поступления/редакция/единицы) ─────────


@router.post("/runs/{run_id}/monitoring/actuals", status_code=201)
def register_actuals(
    request: Request,
    run_id: str,
    payload: Optional[dict[str, Any]] = Body(None),
) -> Any:
    _authorized_run_or_404(request, run_id, action="write")
    subject, session_id = _subject_and_session(request)
    body = dict(payload or {})
    try:
        record, created = _service().register_actual_batch(
            run_id,
            subject,
            target_name=body.get("target_name"),
            entity_id=body.get("entity_id"),
            units=body.get("units"),
            as_of=body.get("as_of"),
            values=body.get("values"),
            source_kind=str(body.get("source_kind") or "manual"),
            source_ref=body.get("source_ref"),
            notes=str(body.get("notes") or ""),
            idempotency_key=str(body.get("idempotency_key") or ""),
            session_id=session_id,
        )
    except Exception as exc:
        return _error_response(exc)
    return {"created": created, "batch": _batch_json(record)}


@router.get("/runs/{run_id}/monitoring/actuals")
def list_actuals(request: Request, run_id: str) -> Any:
    _authorized_run_or_404(request, run_id, action="read")
    subject, _session_id = _subject_and_session(request)
    try:
        items = _service().list_actual_batches(run_id, subject)
    except Exception as exc:
        return _error_response(exc)
    return {
        "items": [_batch_json(item) for item in items],
        "total": len(items),
    }


# ── Frozen сверки (§6 D12) ───────────────────────────────────────────


@router.post("/runs/{run_id}/monitoring/comparisons", status_code=201)
def create_comparison(
    request: Request,
    run_id: str,
    payload: Optional[dict[str, Any]] = Body(None),
) -> Any:
    _authorized_run_or_404(request, run_id, action="write")
    subject, session_id = _subject_and_session(request)
    body = dict(payload or {})
    try:
        record, created = _service().build_comparison(
            run_id,
            subject,
            forecast_artifact_id=body.get("forecast_artifact_id"),
            actual_batch_id=body.get("actual_batch_id"),
            forecast_units=body.get("forecast_units"),
            units_conversion=body.get("units_conversion"),
            threshold=body.get("threshold"),
            mase_scale=body.get("mase_scale"),
            idempotency_key=str(body.get("idempotency_key") or ""),
            session_id=session_id,
        )
    except Exception as exc:
        return _error_response(exc)
    return {"created": created, "comparison": _comparison_json(record)}


@router.get("/runs/{run_id}/monitoring/comparisons")
def list_comparisons(request: Request, run_id: str) -> Any:
    _authorized_run_or_404(request, run_id, action="read")
    subject, _session_id = _subject_and_session(request)
    try:
        items = _service().list_comparisons(run_id, subject)
    except Exception as exc:
        return _error_response(exc)
    return {
        "items": [_comparison_json(item) for item in items],
        "total": len(items),
    }


@router.get("/runs/{run_id}/monitoring/comparisons/{comparison_id}")
def get_comparison(
    request: Request, run_id: str, comparison_id: str
) -> Any:
    _authorized_run_or_404(request, run_id, action="read")
    subject, _session_id = _subject_and_session(request)
    try:
        record = _service().get_comparison(run_id, subject, comparison_id)
    except Exception as exc:
        return _error_response(exc)
    return _comparison_json(record)


# ── Решения человека (append-only; §6.1: без автопереобучения) ───────


@router.post(
    "/runs/{run_id}/monitoring/comparisons/{comparison_id}/decisions",
    status_code=201,
)
def create_decision(
    request: Request,
    run_id: str,
    comparison_id: str,
    payload: Optional[dict[str, Any]] = Body(None),
) -> Any:
    _authorized_run_or_404(request, run_id, action="write")
    subject, session_id = _subject_and_session(request)
    body = dict(payload or {})
    try:
        decision = _service().record_decision(
            run_id,
            subject,
            comparison_id,
            action=body.get("action"),
            rationale=body.get("rationale"),
            session_id=session_id,
        )
    except Exception as exc:
        return _error_response(exc)
    return {"decision": decision.to_dict()}


@router.get(
    "/runs/{run_id}/monitoring/comparisons/{comparison_id}/decisions"
)
def list_decisions(
    request: Request, run_id: str, comparison_id: str
) -> Any:
    _authorized_run_or_404(request, run_id, action="read")
    subject, _session_id = _subject_and_session(request)
    try:
        items = _service().list_decisions(run_id, subject, comparison_id)
    except Exception as exc:
        return _error_response(exc)
    return {
        "items": [item.to_dict() for item in items],
        "total": len(items),
    }
