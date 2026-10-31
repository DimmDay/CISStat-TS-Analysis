# apps/api/routers/logs.py
"""
DOCLOG-7 (spec_documentation_logging.md §14.2, §15, §15.1, §19 строка
DOCLOG-7): маршруты журналов и поддержки под /v1/logs.

АВТОРИЗАЦИЯ (§15.1 дословно): «Новые admin endpoints сохраняют текущую
ADMIN-проверку и дополнительно применяют scopes/tenant grants». Порядок
каждого маршрута: аутентификация (get_current_principal, 401) ->
эффективный доступ (ADMIN-роль + scopes реестра + активные support
grants субъекта, admin_logs.resolve_effective_log_access) -> операция.
Отказ -- uniform 403 {code: logs_access_denied}; отказ сам пишется в
durable audit (authz_denied, standard) с псевдонимом субъекта, БЕЗ
значения ключа.

САМОЖУРНАЛИРОВАНИЕ (§14.2): успешное чтение потока -- РОВНО одна
audit-запись audit_log_accessed (standard, AC11-инвариант: сбой записи
не ломает чтение); экспорт пакета -- mandatory fail-closed (раскрытие
журналов) + тройка download_requested/response_stream_started/finished;
создание/отзыв гранта -- mandatory fail-closed (§14.1 «создание/
изменение прав и support grants»).

ОШИБКИ (§17-дух): 401 нет/неверный ключ; 403 logs_access_denied
(uniform body с code/request_id); 404 грант не найден; 422
logs_validation_error (whitelist-фильтры, окно <= 31 день, TTL, cursor);
503 logs_backend_unavailable / audit_unavailable. НИКАКИХ traceback/
SQL/DSN в ответах.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Header, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from apps.api.admin_logs import (
    EffectiveLogAccess,
    GrantNotFoundError,
    GrantValidationError,
    LogsAccessDenied,
    LogsBackendError,
    LogsValidationError,
    SupportGrantService,
    build_diagnostic_bundle,
    parse_query,
    query_audit,
    query_delivery,
    query_telemetry,
    resolve_effective_log_access,
)
from apps.api.auth import get_current_principal
from apps.api.plans import AuthenticatedPrincipal
from apps.api.security_audit import (
    ACTION_DOWNLOAD_REQUESTED,
    ACTION_RESPONSE_STREAM_FINISHED,
    ACTION_RESPONSE_STREAM_STARTED,
    MandatoryAuditFailure,
    record_standard,
)
from apps.api.telemetry import current_request_id

router = APIRouter()

_SERVICE: Optional[SupportGrantService] = None


def get_grant_service() -> SupportGrantService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = SupportGrantService()
    return _SERVICE


def reset_logs_service_for_testing() -> None:
    global _SERVICE
    _SERVICE = None


# ── Единый отказ/ошибка (uniform body §15) ───────────────────────────


def _denied(request: Request, principal: Any, reason: str) -> JSONResponse:
    """403 uniform + durable audit (псевдоним субъекта, НЕ ключ)."""
    from apps.api.identity import subject_pseudonym

    record_standard(
        "authz_denied",
        "denied",
        actor_subject=(
            getattr(principal, "subject_id", None)
            or subject_pseudonym(getattr(principal, "principal_id", ""))
        ),
        actor_via="api_key",
        resource_kind="admin_logs",
        policy_basis="logs access policy",
        details={"reason": reason},
    )
    return JSONResponse(
        status_code=403,
        content={
            "code": "logs_access_denied",
            "message": "Доступ к журналам не выдан (§15)",
            "request_id": current_request_id(),
        },
    )


def _validation_error(exc: LogsValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "logs_validation_error",
            "message": str(exc),
            "request_id": current_request_id(),
        },
    )


def _backend_error(message: str = "durable-слой журналов недоступен") -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "code": "logs_backend_unavailable",
            "message": message,
            "request_id": current_request_id(),
        },
    )


def _resolve_access(principal: Any) -> EffectiveLogAccess:
    return resolve_effective_log_access(
        principal, registry=get_grant_service().registry
    )


# ── GET /v1/logs/access ──────────────────────────────────────────────


def _principal_or_401(
    x_api_key: Optional[str], request: Request,
) -> Any:
    """401 на отсутствующий/неверный ключ (§15.1: вход -- действующий
    API-key adapter; Header(...) FastAPI вернул бы 422 на отсутствие --
    для админ-области честнее различимый 401)."""
    return get_current_principal(request=request, x_api_key=x_api_key)


@router.get("/access")
def get_log_access(
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
):
    principal = _principal_or_401(x_api_key, request)
    """Эффективный доступ текущего субъекта (§15 таблица прав) --
    без чтения журналов, поэтому audit_log_accessed не пишется."""
    access = _resolve_access(principal)
    return {
        "principal": {
            "subject_id": getattr(principal, "subject_id", None),
            "role": getattr(getattr(principal, "role", None), "value", None),
        },
        "access": {
            "telemetry": access.telemetry,
            "audit": access.audit,
            "delivery": access.delivery,
            "export": access.export,
            "grants_management": access.grants_management,
            "scope": access.scope_meta(),
        },
    }


# ── Потоки журналов ──────────────────────────────────────────────────


def _stream_params(
    request: Request,
) -> dict[str, Any]:
    query = request.query_params
    return {
        "from_raw": query.get("from"),
        "to_raw": query.get("to"),
        "limit_raw": query.get("limit"),
        "cursor_raw": query.get("cursor"),
    }


def _stream_filters(request: Request, names: tuple[str, ...]) -> dict[str, Any]:
    return {name: request.query_params.get(name) for name in names}


@router.get("/telemetry")
def get_telemetry_logs(
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
):
    principal = _principal_or_401(x_api_key, request)
    try:
        access = _resolve_access(principal)
        parsed = parse_query(
            "telemetry",
            **_stream_params(request),
            filters=_stream_filters(
                request,
                ("severity", "outcome", "event_name", "request_id",
                 "run_id", "tenant_id"),
            ),
        )
        payload = query_telemetry(parsed, access)
    except LogsAccessDenied:
        return _denied(request, principal, "telemetry: logs.read отсутствует")
    except LogsValidationError as exc:
        return _validation_error(exc)
    except LogsBackendError:
        return _backend_error()
    record_standard(
        "audit_log_accessed",
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="log_stream",
        resource_id="telemetry",
        policy_basis="logs access policy",
        details={
            "stream": "telemetry",
            "operation": "query",
            "rows_returned": payload["meta"]["count"],
            "filters": dict(parsed.filters),
        },
    )
    return payload


@router.get("/audit")
def get_audit_logs(
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
):
    principal = _principal_or_401(x_api_key, request)
    try:
        access = _resolve_access(principal)
        parsed = parse_query(
            "audit",
            **_stream_params(request),
            filters=_stream_filters(
                request,
                ("action", "decision", "actor_subject", "request_id",
                 "run_id", "tenant_id"),
            ),
        )
        payload = query_audit(parsed, access)
    except LogsAccessDenied:
        return _denied(request, principal, "audit: audit.read отсутствует")
    except LogsValidationError as exc:
        return _validation_error(exc)
    except LogsBackendError:
        return _backend_error()
    record_standard(
        "audit_log_accessed",
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="log_stream",
        resource_id="audit",
        policy_basis="logs access policy",
        details={
            "stream": "audit",
            "operation": "query",
            "rows_returned": payload["meta"]["count"],
            "filters": dict(parsed.filters),
        },
    )
    return payload


@router.get("/delivery")
def get_delivery_logs(
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
):
    principal = _principal_or_401(x_api_key, request)
    try:
        access = _resolve_access(principal)
        parsed = parse_query(
            "delivery",
            **_stream_params(request),
            filters=_stream_filters(
                request,
                ("state", "format", "run_id", "tenant_id"),
            ),
        )
        payload = query_delivery(parsed, access)
    except LogsAccessDenied:
        return _denied(request, principal, "delivery: logs.read отсутствует")
    except LogsValidationError as exc:
        return _validation_error(exc)
    except LogsBackendError:
        return _backend_error()
    record_standard(
        "audit_log_accessed",
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="log_stream",
        resource_id="delivery",
        policy_basis="logs access policy",
        details={
            "stream": "delivery",
            "operation": "query",
            "rows_returned": payload["meta"]["count"],
            "filters": dict(parsed.filters),
        },
    )
    return payload


# ── POST /v1/logs/export -- диагностический пакет (§14.2) ────────────


@router.post("/export")
def export_logs_bundle(
    request: Request,
    body: Optional[dict] = Body(default=None),
    x_api_key: Optional[str] = Header(default=None),
):
    principal = _principal_or_401(x_api_key, request)
    body = dict(body or {})
    streams_raw = body.get("streams")
    streams = tuple(streams_raw) if isinstance(streams_raw, list) else None
    try:
        access = _resolve_access(principal)
        parsed = parse_query(
            "telemetry",  # валидация окна/лимитов; потоки -- отдельно
            from_raw=body.get("from"),
            to_raw=body.get("to"),
            limit_raw=None,
            cursor_raw=None,
            filters={},
        )
        # Mandatory fail-closed (AC11): экспорт журналов -- раскрытие;
        # невозможность зафиксировать -- отказ ДО построения пакета.
        from apps.api.security_audit import record_mandatory

        bundle_id = record_mandatory(
            "audit_log_accessed",
            "allowed",
            actor_subject=getattr(principal, "subject_id", "") or "",
            actor_via="api_key",
            resource_kind="log_stream",
            resource_id="diagnostic_bundle",
            policy_basis="logs export policy",
            details={
                "stream": "bundle",
                "operation": "diagnostic_bundle",
                "streams": list(streams or []),
            },
        )
        zip_bytes, bundle_id, filename = build_diagnostic_bundle(
            parsed, access, streams=streams
        )
    except LogsAccessDenied:
        return _denied(request, principal, "export: logs.export отсутствует")
    except LogsValidationError as exc:
        return _validation_error(exc)
    except MandatoryAuditFailure:
        return JSONResponse(
            status_code=503,
            content={
                "code": "audit_unavailable",
                "message": "Обязательный audit недоступен -- экспорт отклонён (AC11)",
                "request_id": current_request_id(),
            },
        )
    except LogsBackendError:
        return _backend_error()

    record_standard(
        ACTION_DOWNLOAD_REQUESTED,
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="diagnostic_bundle",
        resource_id=bundle_id,
        policy_basis="logs export policy",
    )
    record_standard(
        ACTION_RESPONSE_STREAM_STARTED,
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="diagnostic_bundle",
        resource_id=bundle_id,
        policy_basis="logs export policy",
    )
    record_standard(
        ACTION_RESPONSE_STREAM_FINISHED,
        "allowed",
        actor_subject=getattr(principal, "subject_id", "") or "",
        actor_via="api_key",
        resource_kind="diagnostic_bundle",
        resource_id=bundle_id,
        policy_basis="details",
    )
    import io

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


# ── Гранты поддержки (§14.2/§15) ─────────────────────────────────────


@router.get("/grants")
def list_grants(
    request: Request,
    x_api_key: Optional[str] = Header(default=None),
):
    principal = _principal_or_401(x_api_key, request)
    access = _resolve_access(principal)
    if not access.grants_management:
        return _denied(request, principal, "grants: support.grant отсутствует")
    include_revoked = request.query_params.get("include_revoked") in (
        "1", "true", "yes",
    )
    grants = get_grant_service().list_grants(include_revoked=include_revoked)
    return {"grants": [g.to_dict() for g in grants]}


@router.post("/grants")
def create_grant(
    request: Request,
    body: Optional[dict] = Body(default=None),
    x_api_key: Optional[str] = Header(default=None),
):
    principal = _principal_or_401(x_api_key, request)
    access = _resolve_access(principal)
    if not access.grants_management:
        return _denied(request, principal, "grants: support.grant отсутствует")
    if body is None:
        return _validation_error(LogsValidationError("тело запроса не JSON"))
    body = dict(body)
    try:
        grant = get_grant_service().create_grant(
            ticket=body.get("ticket"),
            purpose=body.get("purpose") or "",
            subject_id=body.get("subject_id"),
            tenant_id=body.get("tenant_id"),
            run_id=body.get("run_id"),
            scopes=tuple(body.get("scopes") or ()),
            ttl_hours=body.get("ttl_hours"),
            created_by=getattr(principal, "subject_id", "") or "",
        )
    except GrantValidationError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "code": "logs_validation_error",
                "message": str(exc),
                "request_id": current_request_id(),
            },
        )
    except MandatoryAuditFailure:
        return JSONResponse(
            status_code=503,
            content={
                "code": "audit_unavailable",
                "message": "Обязательный audit недоступен -- грант не создан (AC11)",
                "request_id": current_request_id(),
            },
        )
    return JSONResponse(status_code=201, content=grant.to_dict())


@router.post("/grants/{grant_id}/revoke")
def revoke_grant(
    grant_id: str,
    request: Request,
    body: Optional[dict] = Body(default=None),
    x_api_key: Optional[str] = Header(default=None),
):
    principal = _principal_or_401(x_api_key, request)
    access = _resolve_access(principal)
    if not access.grants_management:
        return _denied(request, principal, "grants: support.grant отсутствует")
    body = dict(body or {})
    try:
        grant = get_grant_service().revoke_grant(
            grant_id,
            revoked_by=getattr(principal, "subject_id", "") or "",
            reason=str(body.get("reason") or ""),
        )
    except GrantNotFoundError:
        return JSONResponse(
            status_code=404,
            content={
                "code": "grant_not_found",
                "message": "Грант не найден",
                "request_id": current_request_id(),
            },
        )
    except MandatoryAuditFailure:
        return JSONResponse(
            status_code=503,
            content={
                "code": "audit_unavailable",
                "message": "Обязательный audit недоступен -- отзыв отклонён (AC11)",
                "request_id": current_request_id(),
            },
        )
    return grant.to_dict()
