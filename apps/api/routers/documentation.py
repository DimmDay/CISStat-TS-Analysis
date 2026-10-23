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
    DocumentDeliveryService,
    UnsupportedFormatError,
)
from apps.api.document_renditions import (
    RENDITION_FORMATS,
    filename_for,
    render_snapshot_html,
)
from apps.api.identity import resolve_request_subject
from apps.api.report_snapshot import (
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
    record_standard,
)
from apps.api.session_store import SESSION_COOKIE_NAME

router = APIRouter()

# Uniform-404 (§15/AC06): одинаковые код/тело для «нет» и «чужой».
_RUN_NOT_FOUND_DETAIL = "Запуск не найден"
_DOCUMENT_NOT_FOUND_DETAIL = "Документ не найден"

_SERVICE: Optional[DocumentDeliveryService] = None


def _delivery_service() -> DocumentDeliveryService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = DocumentDeliveryService.create_default()
    return _SERVICE


def reset_documentation_service_for_testing() -> None:
    global _SERVICE
    _SERVICE = None


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
    """§17: 400 unsupported_format; 409 конфликт; 404 uniform; 503."""
    if isinstance(exc, UnsupportedFormatError):
        return HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_format",
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
    if isinstance(exc, DocumentAccessDenied):
        return HTTPException(status_code=404, detail=_DOCUMENT_NOT_FOUND_DETAIL)
    if isinstance(exc, DocumentIntegrityError):
        return HTTPException(
            status_code=500,
            detail={
                "code": "integrity_mismatch",
                "message": "Файл повреждён; обратитесь в поддержку",
            },
        )
    return HTTPException(
        status_code=500,
        detail={"code": "internal_error", "message": "Внутренняя ошибка"},
    )


# ── Сериализация ─────────────────────────────────────────────────────


def _revision_json(revision: Any, snapshot_record: Any) -> dict[str, Any]:
    """Версия документа + метаданные снимка (captured_at/полнота) +
    готовые renditions (§12.2 таблица: «доступные форматы и размер»)."""
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
    (AC09). Тяжёлые форматы -- 400 unsupported_format (DOCLOG-5)."""
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
    Content-Disposition/media_type/nosniff/private,no-store (§15.2)."""
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
    except DocumentAccessDenied as exc:
        raise _map_service_errors(exc) from None
    except DocumentIntegrityError as exc:
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
            "Content-Disposition": (
                f'inline; filename="{filename_for(rendition_id, rendition.format)}"'
            ),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )
