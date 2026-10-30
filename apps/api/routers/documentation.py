# apps/api/routers/documentation.py
"""
DOCLOG-4 (spec_documentation_logging.md §12.1-§12.2, §14.1, §15, §17,
§19 строка DOCLOG-4, §20 AC05/AC06/AC09/AC16/AC17): первые HTTP-маршруты
эпика документирования -- MVP выдачи поверх frozen снимков DOCLOG-2 +
audit-потока DOCLOG-3.

КАЖДЫЙ маршрут (R09/§15): резолв ресурса (document/revision/job/
rendition -> run) -> identity.authorize_run_access (одна объектная
авторизация) -> действие. Знание ID НЕ является правом (T15); отказ --
uniform 404 (существование не дисклоужается; причина -- в audit-потоке
DOCLOG-3). N3-ГЕЙТ (акт DOCLOG-2-FIX): dependency manifest выдаётся
ТОЛЬКО внутри авторизованного GET /revisions/{id} -- прямого ungated
доступа к dependency_refs в HTTP-контуре нет.

ЧТЕНИЕ НЕ МЕНЯЕТ НАУКУ (§17/AC05): GET-маршруты -- metadata/preview/
content; «На GET допускается security audit факта доступа, но нет
изменения исследовательского состояния». Аудит выдачи (§14.1): тройка
download_requested -> response_stream_started -> response_stream_finished
РАЗЛИЧАЕТСЯ; protected_document_viewed на preview; классы standard
(AC11-инвариант: сбой аудита не ломает выдачу); human_read_confirmed НЕ
существует (сервер не удостоверяет сохранение файла на диск).

Коды ошибок (§17): 400 unsupported_format; 409 конфликт
идемпотентности/изменившийся контекст; 404 uniform (нет/чужой);
422 некорректный kind; 503 durable-слой недоступен. Безопасная ошибка:
code/message/request_id без traceback/SQL/DSN.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse

from apps.api.document_jobs import (
    DocumentAccessDenied,
    DocumentIntegrityError,
    DocumentQuotaExceeded,
    DocumentRetryLimitExceeded,
    DocumentDeliveryService,
    PrintRenderBasisUnsupported,
    RenditionPurgedError,
    UnsupportedFormatError,
)
from apps.api.document_lifecycle import (
    ApprovalHashMismatchError,
    ApprovalNotApplicableError,
    DiffAcrossDocumentsError,
    DocumentLifecycleService,
    InsufficientScopeError,
    InvalidTransitionError,
    LifecycleAccessDenied,
    PublishBlockedGapsError,
    PublishRequiresApprovalError,
    SelfApprovalForbiddenError,
)
from apps.api.document_renditions import (
    RENDITION_FORMATS,
    filename_for,
    render_snapshot_html,
)
from apps.api.identity import resolve_request_subject
from apps.api.report_snapshot import (
    DEFAULT_REDACTION_PROFILE,
    DOCUMENT_KINDS,
    resolve_kinds,
)
from apps.api.snapshot_builder import (
    SnapshotConflictError,
    SnapshotIdempotencyConflictError,
)
from apps.api.security_audit import (
    ACTION_DOWNLOAD_REQUESTED,
    ACTION_PROTECTED_DOCUMENT_VIEWED,
    ACTION_RESPONSE_STREAM_FINISHED,
    ACTION_RESPONSE_STREAM_STARTED,
    MandatoryAuditFailure,
    record_standard,
)
from apps.api.session_store import SESSION_COOKIE_NAME

router = APIRouter()

# Uniform-404 (§15/AC06): одинаковые код/тело для «нет» и «чужой».
_RUN_NOT_FOUND_DETAIL = "Запуск не найден"
_DOCUMENT_NOT_FOUND_DETAIL = "Документ не найден"

_SERVICE: Optional[DocumentDeliveryService] = None
_LIFECYCLE_SERVICE: Optional[DocumentLifecycleService] = None


def _delivery_service() -> DocumentDeliveryService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = DocumentDeliveryService.create_default()
    return _SERVICE


def _lifecycle_service() -> DocumentLifecycleService:
    global _LIFECYCLE_SERVICE
    if _LIFECYCLE_SERVICE is None:
        _LIFECYCLE_SERVICE = DocumentLifecycleService.create_default()
    return _LIFECYCLE_SERVICE


def reset_documentation_service_for_testing() -> None:
    global _SERVICE, _LIFECYCLE_SERVICE
    _SERVICE = None
    _LIFECYCLE_SERVICE = None


# ── Авторизация и отображение ошибок ─────────────────────────────────


def _subject_and_session(request: Request) -> tuple[Any, str]:
    subject = resolve_request_subject(request)
    session_id = request.cookies.get(SESSION_COOKIE_NAME) or ""
    return subject, session_id


def _authorized_run_or_404(request: Request, run_id: str, *, action: str) -> Any:
    """Единая точка доступа к run-маршрутам (паритет routers/progress).
    Отказ решающей таблицы -- uniform 404; причина -- AccessDecision в
    durable audit-потоке (сам шлюз _audit_access_decision)."""
    from apps.api.research_runs import get_research_run_store

    run = get_research_run_store().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=_RUN_NOT_FOUND_DETAIL)
    subject, session_id = _subject_and_session(request)
    from apps.api.identity import authorize_run_access

    decision = authorize_run_access(
        run, subject, session_id=session_id, action=action
    )
    if not decision.allowed:
        raise HTTPException(status_code=404, detail=_RUN_NOT_FOUND_DETAIL)
    return run


def _map_service_errors(exc: Exception) -> HTTPException:
    """§17: 400 unsupported_format; 409 конфликт; 404 uniform; 429
    пределы очереди/попыток (§18, DOCLOG-5); 503. DOCLOG-6: 403
    insufficient_scope (ресурс свой, права нет); 409
    approval_hash_mismatch/approval_not_applicable (AC07); 422
    invalid_transition/self_approval_forbidden/publish_*; 410
    purged_artifact (§16.1); 503 mandatory_audit_unavailable (AC11).
    DOCLOG-9: 409 org_profile_mismatch/org_profile_retired; 404
    org_profile_not_found; 422 org_profile_invalid (required/format)."""
    from apps.api import doc_profiles as _dp_module  # noqa: F401 -- маппинг ниже
    if isinstance(exc, UnsupportedFormatError):
        return HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_format",
                "message": str(exc),
            },
        )
    if isinstance(exc, DocumentRetryLimitExceeded):
        # §18 retries: исчерпаны попытки рендера -- честный 429.
        return HTTPException(
            status_code=429,
            detail={
                "code": "retry_limit_exceeded",
                "message": str(exc),
            },
        )
    if isinstance(exc, DocumentQuotaExceeded):
        # §18 backpressure: tenant-очередь переполнена -- честный 429.
        return HTTPException(
            status_code=429,
            detail={
                "code": "quota_exceeded",
                "message": str(exc),
            },
        )
    if isinstance(exc, SnapshotIdempotencyConflictError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "idempotency_conflict",
                "message": "Тот же idempotency_key с другим телом запроса",
            },
        )
    if isinstance(exc, SnapshotConflictError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "conflict",
                "message": (
                    "Состояние запуска изменилось; перечитайте и повторите"
                ),
            },
        )
    # ── DOCLOG-9 (§19 строка DOCLOG-9): ошибки организационного профиля ──
    if isinstance(exc, _dp_module.OrgProfileMismatchError):
        # §11/AC09: одна визуальная форма на цель; другой профиль той же
        # цели -- честный 409, не вторая версия.
        return HTTPException(
            status_code=409,
            detail={"code": "org_profile_mismatch", "message": str(exc)},
        )
    if isinstance(exc, _dp_module.OrgProfileRetired):
        return HTTPException(
            status_code=409,
            detail={"code": "org_profile_retired", "message": str(exc)},
        )
    if isinstance(exc, _dp_module.OrgProfileNotFound):
        return HTTPException(
            status_code=404,
            detail={"code": "org_profile_not_found", "message": str(exc)},
        )
    if isinstance(exc, _dp_module.OrgProfileAccessDenied):
        return HTTPException(
            status_code=403,
            detail={"code": "insufficient_scope", "message": str(exc)},
        )
    if isinstance(exc, _dp_module.OrgProfileError):
        # OrgProfileRequired / OrgProfileFormatMismatch -- 422.
        return HTTPException(
            status_code=422,
            detail={"code": "org_profile_invalid", "message": str(exc)},
        )
    if isinstance(exc, PrintRenderBasisUnsupported):
        # PGV-09: basis печатной ревизии вне каталога рендера поставки
        # (P01/P02 -- PGV-13) -- честный 422, не тихий рендер.
        return HTTPException(
            status_code=422,
            detail={"code": "print_basis_unsupported", "message": str(exc)},
        )
    if isinstance(exc, (DocumentAccessDenied, LifecycleAccessDenied)):
        # DOCLOG-6: LifecycleAccessDenied -- тот же uniform-404 контракт
        # (R09/T15): «нет» и «чужой» неразличимы.
        return HTTPException(status_code=404, detail=_DOCUMENT_NOT_FOUND_DETAIL)
    if isinstance(exc, DocumentIntegrityError):
        return HTTPException(
            status_code=500,
            detail={
                "code": "integrity_mismatch",
                "message": "Файл повреждён; обратитесь в поддержку",
            },
        )
    if isinstance(exc, RenditionPurgedError):
        # §17/§16.1: purged artifact -- честный 410 разрешённому владельцу.
        return HTTPException(
            status_code=410,
            detail={
                "code": "purged_artifact",
                "message": str(exc),
            },
        )
    if isinstance(exc, InsufficientScopeError):
        # §15/D5: субъект владеет ресурсом, права на действие нет.
        return HTTPException(
            status_code=403,
            detail={"code": "insufficient_scope", "message": str(exc)},
        )
    if isinstance(exc, ApprovalHashMismatchError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "approval_hash_mismatch",
                "message": str(exc),
            },
        )
    if isinstance(exc, ApprovalNotApplicableError):
        return HTTPException(
            status_code=409,
            detail={
                "code": "approval_not_applicable",
                "message": str(exc),
            },
        )
    if isinstance(exc, PublishRequiresApprovalError):
        return HTTPException(
            status_code=422,
            detail={
                "code": "publish_requires_approval",
                "message": str(exc),
            },
        )
    if isinstance(exc, PublishBlockedGapsError):
        return HTTPException(
            status_code=422,
            detail={
                "code": "publish_blocked_gaps",
                "message": str(exc),
            },
        )
    if isinstance(exc, SelfApprovalForbiddenError):
        return HTTPException(
            status_code=422,
            detail={
                "code": "self_approval_forbidden",
                "message": str(exc),
            },
        )
    if isinstance(exc, DiffAcrossDocumentsError):
        return HTTPException(
            status_code=422,
            detail={
                "code": "diff_across_documents",
                "message": str(exc),
            },
        )
    if isinstance(exc, InvalidTransitionError):
        return HTTPException(
            status_code=422,
            detail={
                "code": "invalid_transition",
                "message": str(exc),
            },
        )
    if isinstance(exc, MandatoryAuditFailure):
        # §14.1/AC11: обязательный audit не зафиксирован -- защищённое
        # действие не выполняется (fail-closed), состояние не меняется.
        return HTTPException(
            status_code=503,
            detail={
                "code": "mandatory_audit_unavailable",
                "message": "Аудит недоступен; действие не выполнено",
            },
        )
    return HTTPException(
        status_code=500,
        detail={"code": "internal_error", "message": "Внутренняя ошибка"},
    )


# ── Сериализация ─────────────────────────────────────────────────────


def _revision_json(revision: Any, snapshot_record: Any) -> dict[str, Any]:
    """Версия документа + метаданные снимка (captured_at/полнота) +
    готовые renditions (§12.2 таблица: «доступные форматы и размер») +
    DOCLOG-6: вычисленное состояние оси содержания (lifecycle_state)."""
    payload = revision.to_dict()
    if snapshot_record is not None:
        payload["captured_at"] = snapshot_record.captured_at
        payload["completeness_status"] = (
            snapshot_record.completeness.get("status", "partial")
            if isinstance(snapshot_record.completeness, dict)
            else "partial"
        )
    else:
        payload["captured_at"] = None
        payload["completeness_status"] = None
    payload["renditions"] = [
        rendition.to_dict()
        for rendition in _delivery_service().registry.list_renditions(
            revision.snapshot_id
        )
    ]
    # DOCLOG-6 (аддитивно): состояние draft/ready_for_review/approved/
    # published/rejected/retracted/superseded -- вычисляется из
    # append-only lifecycle-записей (сбой lookup -- честный draft).
    try:
        payload["lifecycle_state"] = _lifecycle_service().revision_state(
            revision.revision_id
        )
    except Exception:
        payload["lifecycle_state"] = "draft"
    return payload


def _document_json(
    document: Any, revisions: list[Any]
) -> dict[str, Any]:
    from apps.api.snapshot_builder import SnapshotService
    from apps.api.report_snapshot import peek_snapshot_registry

    snapshot_registry = peek_snapshot_registry()
    service = _delivery_service()
    payloads = []
    for revision in revisions:
        snapshot_record = None
        if snapshot_registry is not None:
            snapshot_record = snapshot_registry.get_snapshot_record(
                revision.snapshot_id
            )
        payloads.append(_revision_json(revision, snapshot_record))
    kind_title = DOCUMENT_KINDS.get(document.kind_code, (None, document.kind_code, None))[
        1
    ]
    payload = document.to_dict()
    payload["title"] = kind_title
    payload["revisions"] = payloads
    return payload


def _job_json(job: Any, rendition: Any) -> dict[str, Any]:
    payload = job.to_dict()
    payload["rendition"] = rendition.to_dict() if rendition is not None else None
    return payload


# ── Маршруты (§17) ───────────────────────────────────────────────────


@router.get("/runs/{run_id}/documents")
def list_documents(
    request: Request,
    run_id: str,
    kind: Optional[str] = Query(default=None),
    context_id: Optional[str] = Query(default=None),
) -> dict[str, Any]:
    """§17 GET /runs/{run_id}/documents: разрешённые документы и версии;
    НЕТ scientific/ledger mutation. kind-фильтр -- §12.1 «открыть
    отфильтрованный список по текущим run/context/stage»; открытие не
    создаёт документ фактом открытия."""
    _authorized_run_or_404(request, run_id, action="read")
    subject, session_id = _subject_and_session(request)
    pairs = _delivery_service().list_documents(
        run_id, subject, session_id=session_id, kind=kind
    )
    documents = [
        _document_json(document, revisions) for document, revisions in pairs
    ]
    if context_id is not None:
        # §12.1: фильтр по контексту -- снимки только выбранного контекста
        # (unknown-контекст не смешивается; честный пустой список).
        filtered = []
        for document in documents:
            matching = []
            for revision in document["revisions"]:
                record = peek_snapshot_record(revision["snapshot_id"])
                if record is not None and getattr(
                    record, "context_id", None
                ) == context_id:
                    matching.append(revision)
            document = dict(document)
            document["revisions"] = matching
            filtered.append(document)
        documents = [document for document in filtered if document["revisions"]]
    return {"run_id": run_id, "documents": documents}


def peek_snapshot_record(snapshot_id: str) -> Any:
    from apps.api.report_snapshot import peek_snapshot_registry

    registry = peek_snapshot_registry()
    if registry is None:
        return None
    return registry.get_snapshot_record(snapshot_id)


@router.post("/runs/{run_id}/documents", status_code=201)
def create_document_draft(
    request: Request,
    run_id: str,
    payload: dict[str, Any],
    response: Response,
) -> Response:
    """§17 POST /runs/{run_id}/documents: создать draft/snapshot по
    выбранному kind (snapshot/manifest pins/job/receipt -- внутри
    сборщика DOCLOG-2; idempotency -- его UNIQUE(run_id, key)).

    refresh=false (default): ПОСЛЕДНИЙ существующий снимок с kind
    переиспользуется (повторный клик не плодит версии); refresh=true:
    сборщик DOCLOG-2 замораживает НОВУЮ версию (auto-ключ включает
    cutoff -- на неизменном состоянии возвращается прежний снимок)."""
    from apps.api.snapshot_builder import SnapshotService

    try:
        requested = resolve_kinds([payload.get("kind")])
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_kind", "message": str(exc)},
        ) from None
    kind_code = requested[0]
    _authorized_run_or_404(request, run_id, action="write")
    subject, session_id = _subject_and_session(request)
    refresh = bool(payload.get("refresh", False))
    idempotency_key = payload.get("idempotency_key") or None
    service = _delivery_service()
    try:
        snapshot_record = None
        if not refresh:
            # Последний снимок запуска, содержащий kind (порядок
            # created_at реестра DOCLOG-2).
            records = service_registry_records(run_id)
            for record in reversed(records):
                if kind_code in (record.kinds or []):
                    snapshot_record = record
                    break
        if snapshot_record is None:
            snapshot, _created = SnapshotService.create_default().build_snapshot(
                run_id,
                subject,
                session_id=session_id,
                kinds=[kind_code],
                idempotency_key=idempotency_key,
            )
            snapshot_record = snapshot
        document, revision, created = service.ensure_document_revision(
            snapshot_record, subject, session_id=session_id, kind_code=kind_code
        )
    except HTTPException:
        raise
    except (SnapshotConflictError, SnapshotIdempotencyConflictError, DocumentAccessDenied, UnsupportedFormatError) as exc:
        raise _map_service_errors(exc) from None
    except RuntimeError as exc:
        # Durable-слой недоступен -- честный 503 (§17), не скрытая деградация.
        raise HTTPException(
            status_code=503,
            detail={"code": "storage_unavailable", "message": str(exc)},
        ) from None
    document_payload = _document_json(
        document, service.registry.list_revisions(document.document_id)
    )
    revision_payload = next(
        (
            item
            for item in document_payload["revisions"]
            if item["revision_id"] == revision.revision_id
        ),
        revision.to_dict(),
    )
    status_code = 200 if not created else 201
    return Response(
        content=_json_bytes(
            {
                "document": document_payload,
                "revision": revision_payload,
            }
        ),
        status_code=status_code,
        media_type="application/json",
    )


def service_registry_records(run_id: str) -> list[Any]:
    from apps.api.report_snapshot import peek_snapshot_registry

    registry = peek_snapshot_registry()
    if registry is None:
        return []
    return registry.list_records(run_id)


def _json_bytes(payload: Any) -> bytes:
    from apps.api.artifact_store import canonical_json_bytes

    return canonical_json_bytes(payload)


@router.get("/documents/{document_id}/revisions")
def list_document_revisions(
    request: Request, document_id: str
) -> dict[str, Any]:
    """§17 GET /documents/{document_id}/revisions: история разрешённых
    revisions (только security access audit -- через решающую таблицу)."""
    subject, session_id = _subject_and_session(request)
    try:
        document, revisions = _delivery_service().get_document_with_revisions(
            document_id, subject, session_id=session_id
        )
    except DocumentAccessDenied as exc:
        raise _map_service_errors(exc) from None
    return {
        "document": _document_json(document, revisions),
        "revisions": [
            _revision_json(revision, peek_snapshot_record(revision.snapshot_id))
            for revision in revisions
        ],
    }


@router.get("/revisions/{revision_id}")
def get_revision(request: Request, revision_id: str) -> dict[str, Any]:
    """§17 GET /revisions/{revision_id}: metadata/manifest/completeness/
    refs. N3-ГЕЙТ: dependencies -- ТОЛЬКО здесь, после решающей таблицы
    (знание revision_id не право)."""
    subject, session_id = _subject_and_session(request)
    try:
        revision, document, snapshot = _delivery_service().get_revision(
            revision_id, subject, session_id=session_id
        )
    except DocumentAccessDenied as exc:
        raise _map_service_errors(exc) from None
    renditions = _delivery_service().registry.list_renditions(
        snapshot.snapshot_id
    )
    return {
        "revision": _revision_json(revision, snapshot),
        "document": document.to_dict(),
        "snapshot": snapshot.to_dict(),
        "renditions": [rendition.to_dict() for rendition in renditions],
    }


@router.get("/revisions/{revision_id}/preview", response_class=HTMLResponse)
def get_revision_preview(request: Request, revision_id: str) -> Response:
    """§17 GET /revisions/{revision_id}/preview: существующий безопасный
    HTML; НЕ создаёт документ/рендеринг/научный расчёт. Аудит
    protected_document_viewed (standard, §14.1)."""
    subject, session_id = _subject_and_session(request)
    try:
        _revision, _document, snapshot = _delivery_service().get_revision(
            revision_id, subject, session_id=session_id
        )
    except DocumentAccessDenied as exc:
        raise _map_service_errors(exc) from None
    record_standard(
        ACTION_PROTECTED_DOCUMENT_VIEWED,
        "allowed",
        actor_subject=subject.subject_id,
        actor_via=subject.via,
        tenant_id=subject.tenant_id,
        resource_kind="document_revision",
        resource_id=revision_id,
        resource_version=str(snapshot.snapshot_id),
        policy_basis="R09 object authorization; classification="
        + str(snapshot.classification),
        run_id=snapshot.research_run_id,
        details={"snapshot_id": snapshot.snapshot_id},
    )
    html = render_snapshot_html(snapshot)
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": 'inline; filename="preview.html"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/revisions/{revision_id}/renditions", status_code=202)
def request_rendition(
    request: Request, revision_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """§17 POST /revisions/{revision_id}/renditions: заказать
    format/profile для frozen snapshot -> 202 job/status_url; повтор с
    тем же (snapshot, format, profile) возвращает ПРЕЖНИЙ job/rendition
    (AC09). P0 рендерится синхронно; тяжёлые форматы (§7 P1, DOCLOG-5)
    ставятся в очередь рендера (§18) -- рендер выполняет
    document_render_worker."""
    fmt = str(payload.get("format", "")).strip().lower()
    if not fmt:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_format",
                "message": "Формат не указан",
            },
        )
    # DOCLOG-9 (§19): организационный профиль выпуска (обязателен для
    # docx/pdfa; resolve/ошибки -- в сервисном слое).
    org_profile_id = str(payload.get("org_profile_id", "") or "").strip()
    subject, session_id = _subject_and_session(request)
    service = _delivery_service()
    try:
        revision, _document, snapshot = service.get_revision(
            revision_id, subject, session_id=session_id
        )
        job, rendition = service.request_rendition(
            snapshot,
            format=fmt,
            subject=subject,
            session_id=session_id,
            redaction_profile=str(
                payload.get("redaction_profile")
                or snapshot.redaction_profile
            ),
            revision_id=revision.revision_id,
            org_profile_id=org_profile_id,
        )
    except DocumentAccessDenied as exc:
        raise _map_service_errors(exc) from None
    except UnsupportedFormatError as exc:
        raise _map_service_errors(exc) from None
    except Exception as exc:  # noqa: BLE001 -- безопасная ошибка §17
        raise _map_service_errors(exc) from None
    return {
        "job": _job_json(job, rendition),
        "status_url": f"/v1/documentation/jobs/{job.job_id}",
    }




@router.post("/print-revisions/{print_revision_id}/renditions", status_code=202)
def request_print_rendition(
    request: Request, print_revision_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """PGV-09 (spec_passport_graphics_visual.md §10.2/§11/§13, строка
    PGV-09): заказать PNG печатной ревизии (V01, basis
    visual_print_snapshot) -- 202 + job/status_url; рендер выполняет
    document_render_worker через изолированный renderer-контейнер PGV-08
    (§4: «Python jobs остаются authority... только backend завершает
    staged object/CAS→ready»). Идемпотентность (AC09): повтор той же
    цели -- прежний job. Чужая/несуществующая ревизия -- uniform 404
    (AC18). Форматы печатных renditions PGV-09 -- PNG-only (§1);
    D01-D12/snapshot-поток не задействуется (AC22)."""
    fmt = str(payload.get("format", "")).strip().lower()
    if not fmt:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_format",
                "message": "Формат не указан",
            },
        )
    subject, session_id = _subject_and_session(request)
    service = _delivery_service()
    try:
        job, rendition = service.request_print_rendition(
            print_revision_id,
            format=fmt,
            subject=subject,
            session_id=session_id,
            redaction_profile=str(
                payload.get("redaction_profile")
                or DEFAULT_REDACTION_PROFILE
            ),
        )
    except DocumentAccessDenied as exc:
        raise _map_service_errors(exc) from None
    except UnsupportedFormatError as exc:
        raise _map_service_errors(exc) from None
    except PrintRenderBasisUnsupported as exc:
        raise _map_service_errors(exc) from None
    except DocumentRetryLimitExceeded as exc:
        raise _map_service_errors(exc) from None
    except DocumentQuotaExceeded as exc:
        raise _map_service_errors(exc) from None
    except Exception as exc:  # noqa: BLE001 -- безопасная ошибка §17
        raise _map_service_errors(exc) from None
    return {
        "job": _job_json(job, rendition),
        "status_url": f"/v1/documentation/jobs/{job.job_id}",
    }

@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str) -> dict[str, Any]:
    """§17 GET /jobs/{job_id}: состояние/ошибка/receipt; НЕ повторяет job."""
    subject, session_id = _subject_and_session(request)
    try:
        job, rendition = _delivery_service().get_job(
            job_id, subject, session_id=session_id
        )
    except DocumentAccessDenied as exc:
        raise _map_service_errors(exc) from None
    return {"job": _job_json(job, rendition)}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> dict[str, Any]:
    """§17 POST /jobs/{job_id}/cancel: идемпотентно; scientific results
    остаются (снимок/артефакты не трогаются)."""
    subject, session_id = _subject_and_session(request)
    try:
        job = _delivery_service().cancel_job(
            job_id, subject, session_id=session_id
        )
    except DocumentAccessDenied as exc:
        raise _map_service_errors(exc) from None
    rendition = (
        _delivery_service().registry.get_rendition(job.rendition_id)
        if job.rendition_id
        else None
    )
    return {"job": _job_json(job, rendition)}


@router.get("/renditions/{rendition_id}/content")
def get_rendition_content(request: Request, rendition_id: str) -> Response:
    """§17 GET /renditions/{rendition_id}/content: скачать уже готовый
    файл; только учёт доступа/stream (audit-тройка §14.1 РАЗЛИЧАЕТСЯ),
    без forecast_exported/touch scientific session. Безопасные
    Content-Disposition/media_type/nosniff/private,no-store (§15.2).

    DOCLOG-DL-FIX-1 (2026-10-27): Content-Disposition = `attachment`
    для ВСЕХ форматов -- маршрут обещает «немедленное скачивание»
    (§12.2) и подписан в UI «Скачать X»; прежний inline (решение
    DOCLOG-4) для рендеримых типов заставлял браузер рисовать документ
    в текущей вкладке вместо сохранения файла (расхождение
    контракт↔код↔UI; разбор -- docs/doclog_download_behavior_2026-10-27.md).
    Легитимный inline остаётся ТОЛЬКО у preview-маршрута
    (GET /revisions/{id}/preview -- санитизированный просмотр,
    sandboxed-iframe UI и действие «Открыть в новой вкладке»)."""
    from apps.api.document_jobs import is_valid_rendition_id

    if not is_valid_rendition_id(rendition_id):
        raise HTTPException(status_code=404, detail=_DOCUMENT_NOT_FOUND_DETAIL)
    service = _delivery_service()
    rendition = service.registry.get_rendition(rendition_id)
    if rendition is None:
        raise HTTPException(status_code=404, detail=_DOCUMENT_NOT_FOUND_DETAIL)
    subject, session_id = _subject_and_session(request)
    # 1. download_requested (§14.1: запрос).
    record_standard(
        ACTION_DOWNLOAD_REQUESTED,
        "allowed",
        actor_subject=subject.subject_id,
        actor_via=subject.via,
        tenant_id=subject.tenant_id,
        resource_kind="document_rendition",
        resource_id=rendition_id,
        resource_version=str(rendition.format),
        policy_basis="R09 object authorization",
        run_id=rendition.run_id,
        details={"snapshot_id": rendition.snapshot_id, "format": rendition.format},
    )
    try:
        content = service.read_rendition_content(
            rendition, subject, session_id=session_id
        )
    except (DocumentAccessDenied, DocumentIntegrityError, RenditionPurgedError) as exc:
        # DOCLOG-6: purged rendition -- честный 410 владельцу (§16.1/§17).
        raise _map_service_errors(exc) from None
    spec = RENDITION_FORMATS.get(rendition.format)
    media_type = (
        rendition.media_type or (spec.media_type if spec else "application/octet-stream")
    )
    # 2. response_stream_started (начало отдачи).
    record_standard(
        ACTION_RESPONSE_STREAM_STARTED,
        "allowed",
        actor_subject=subject.subject_id,
        actor_via=subject.via,
        tenant_id=subject.tenant_id,
        resource_kind="document_rendition",
        resource_id=rendition_id,
        resource_version=str(rendition.format),
        policy_basis="R09 object authorization",
        run_id=rendition.run_id,
        details={"bytes": len(content)},
    )
    # 3. response_stream_finished (завершение отдачи).
    record_standard(
        ACTION_RESPONSE_STREAM_FINISHED,
        "allowed",
        actor_subject=subject.subject_id,
        actor_via=subject.via,
        tenant_id=subject.tenant_id,
        resource_kind="document_rendition",
        resource_id=rendition_id,
        resource_version=str(rendition.format),
        policy_basis="R09 object authorization",
        run_id=rendition.run_id,
        details={"bytes": len(content)},
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={
            # DOCLOG-DL-FIX-1 (2026-10-27): attachment для ВСЕХ форматов
            # -- «Скачать X» честно сохраняет файл (§12.2/§17); inline
            # остаётся только у preview-маршрута (просмотр, не выдача).
            "Content-Disposition": (
                f'attachment; filename="{filename_for(rendition_id, rendition.format)}"'
            ),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


# ── DOCLOG-6: согласование и архив (§11, §16, §17) ───────────────────


@router.post("/revisions/{revision_id}/approvals")
def revision_approvals(
    request: Request, revision_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """§17 POST /revisions/{revision_id}/approvals: approve/reject по
    policy и точному hash (§11/AC07). Тело: {action: "request"} --
    запрос согласования (draft -> ready_for_review), либо
    {decision: "approve"|"reject", reason?, expected_snapshot_sha256?}
    -- решение согласующего (ready_for_review -> approved | rejected).
    Approve/publish/retract -- mandatory audit fail-closed (§14.1)."""
    subject, session_id = _subject_and_session(request)
    service = _lifecycle_service()
    try:
        if str(payload.get("action", "")) == "request":
            revision, _state = service.request_approval(
                revision_id, subject, session_id=session_id
            )
            return {
                "revision": _revision_json(
                    revision, peek_snapshot_record(revision.snapshot_id)
                )
            }
        decision = str(payload.get("decision", ""))
        revision, approval, _state = service.decide_approval(
            revision_id,
            subject,
            session_id=session_id,
            decision=decision,
            reason=str(payload.get("reason", "") or ""),
            expected_snapshot_sha256=payload.get("expected_snapshot_sha256"),
        )
        return {
            "revision": _revision_json(
                revision, peek_snapshot_record(revision.snapshot_id)
            ),
            "approval": approval.to_dict(),
        }
    except (
        LifecycleAccessDenied,
        InsufficientScopeError,
        InvalidTransitionError,
        SelfApprovalForbiddenError,
        ApprovalHashMismatchError,
        ApprovalNotApplicableError,
        MandatoryAuditFailure,
    ) as exc:
        raise _map_service_errors(exc) from None
    except Exception as exc:  # noqa: BLE001 -- безопасная ошибка §17
        raise _map_service_errors(exc) from None


@router.post("/revisions/{revision_id}/publish")
def revision_publish(request: Request, revision_id: str) -> dict[str, Any]:
    """§17 POST /revisions/{revision_id}/publish: публикация
    согласованной версии; статус/approval refs, без изменения bytes.
    Перепроверка bound-hash (AC07); D11 gaps блокируют (policy v1);
    предыдущая published ревизия -- append-only superseded; снимок
    пинируется (§16). Mandatory audit fail-closed."""
    subject, session_id = _subject_and_session(request)
    service = _lifecycle_service()
    try:
        revision, record, _state = service.publish(
            revision_id, subject, session_id=session_id
        )
        return {
            "revision": _revision_json(
                revision, peek_snapshot_record(revision.snapshot_id)
            ),
            "record": record.to_dict(),
        }
    except (
        LifecycleAccessDenied,
        InsufficientScopeError,
        InvalidTransitionError,
        PublishRequiresApprovalError,
        PublishBlockedGapsError,
        ApprovalNotApplicableError,
        MandatoryAuditFailure,
    ) as exc:
        raise _map_service_errors(exc) from None
    except Exception as exc:  # noqa: BLE001 -- безопасная ошибка §17
        raise _map_service_errors(exc) from None


@router.post("/revisions/{revision_id}/retract")
def revision_retract(
    request: Request, revision_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """§17 POST /revisions/{revision_id}/retract: отзыв с причиной;
    append-only решение, не удаление истории (§11). Mandatory audit
    fail-closed."""
    subject, session_id = _subject_and_session(request)
    service = _lifecycle_service()
    try:
        revision, _state = service.retract(
            revision_id,
            subject,
            session_id=session_id,
            reason=str(payload.get("reason", "") or ""),
        )
        return {
            "revision": _revision_json(
                revision, peek_snapshot_record(revision.snapshot_id)
            )
        }
    except (
        LifecycleAccessDenied,
        InsufficientScopeError,
        InvalidTransitionError,
        MandatoryAuditFailure,
    ) as exc:
        raise _map_service_errors(exc) from None
    except Exception as exc:  # noqa: BLE001 -- безопасная ошибка §17
        raise _map_service_errors(exc) from None


@router.get("/revisions/{revision_id}/lifecycle")
def revision_lifecycle(request: Request, revision_id: str) -> dict[str, Any]:
    """§17/§12.2 «История»: append-only lifecycle-записи ревизии;
    read-only (AC05: не меняет науку; access-audit через решающую
    таблицу)."""
    subject, session_id = _subject_and_session(request)
    service = _lifecycle_service()
    try:
        records = service.list_lifecycle(
            revision_id, subject, session_id=session_id
        )
    except LifecycleAccessDenied as exc:
        raise _map_service_errors(exc) from None
    return {
        "revision_id": revision_id,
        "records": [record.to_dict() for record in records],
    }


@router.get("/revisions/{revision_id}/diff")
def revision_diff(
    request: Request,
    revision_id: str,
    against: str = Query(...),
) -> dict[str, Any]:
    """§17 GET /revisions/{revision_id}/diff?against=: различия снимков
    ДВУХ ревизий одного документа по замороженным данным; никаких
    пересчётов исследования (§17)."""
    subject, session_id = _subject_and_session(request)
    service = _lifecycle_service()
    try:
        report = service.diff_revisions(
            revision_id,
            subject,
            session_id=session_id,
            against_revision_id=against,
        )
    except (LifecycleAccessDenied, DiffAcrossDocumentsError) as exc:
        raise _map_service_errors(exc) from None
    return report


@router.post("/documents/{document_id}/retention")
def document_retention(
    request: Request, document_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """§16.1: hold/release на документе (hold приоритетен над очисткой);
    audit retention_policy_changed (§14.1)."""
    subject, session_id = _subject_and_session(request)
    service = _lifecycle_service()
    try:
        record = service.set_retention(
            document_id,
            subject,
            session_id=session_id,
            action=str(payload.get("action", "")),
            reason=str(payload.get("reason", "") or ""),
        )
    except (
        LifecycleAccessDenied,
        InsufficientScopeError,
        InvalidTransitionError,
    ) as exc:
        raise _map_service_errors(exc) from None
    return {"retention": record.to_dict()}


@router.post("/runs/{run_id}/retention/sweep")
def retention_sweep(request: Request, run_id: str) -> dict[str, Any]:
    """§16.1: sweep невостребованных draft renditions (hold приоритетен;
    published не очищаются); audit cleanup_started. Наука и pinned
    зависимости не трогаются."""
    subject, session_id = _subject_and_session(request)
    service = _lifecycle_service()
    try:
        report = service.sweep_retention(
            run_id, subject, session_id=session_id
        )
    except (LifecycleAccessDenied, InsufficientScopeError) as exc:
        raise _map_service_errors(exc) from None
    return {"run_id": run_id, "report": report}


@router.post("/runs/{run_id}/archive")
def archive_run(request: Request, run_id: str) -> dict[str, Any]:
    """§16/AC18: создать архивный пакет (metadata.jsonl + objects +
    manifest без self-hash §13.3); в ответе -- bundle_id/manifest_sha256
    БЕЗ путей ФС; audit archive_bundle_created."""
    subject, session_id = _subject_and_session(request)
    service = _lifecycle_service()
    try:
        bundle = service.build_archive_bundle(
            run_id, subject, session_id=session_id
        )
    except (LifecycleAccessDenied, InsufficientScopeError) as exc:
        raise _map_service_errors(exc) from None
    return bundle


@router.post("/runs/{run_id}/archive/verify")
def archive_verify(request: Request, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """§16/AC18: restore drill -- члены пакета, ссылочная целостность,
    bound-hash согласований; missing/mismatched ЯВНО перечислены (не
    маскируются); duration_ms замерен; audit restore_started +
    integrity_verified|failed."""
    subject, session_id = _subject_and_session(request)
    service = _lifecycle_service()
    try:
        report = service.verify_archive_bundle(
            run_id,
            subject,
            session_id=session_id,
            bundle_id=str(payload.get("bundle_id", "") or ""),
        )
    except (LifecycleAccessDenied, InsufficientScopeError) as exc:
        raise _map_service_errors(exc) from None
    return report
