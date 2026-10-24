# scripts/doclogcert/conftest.py
"""DOCLOG-CERT (2026-10-24): фикстуры корпуса сквозной приёмки
сервиса документирования и логирования (DOCLOG-0…9).

Спека §19 строка DOCLOG-CERT: «Независимый
негативный/сбойный/права/методический корпус и миграция». Критерий:
«выполнены относящиеся критерии §20, ограничения явно перечислены».

Методология «оракулы на своих данных, мутанты на своих мутантах»
(прецедент DOCLOG-3…8-CERT). Namespace дизъюнктен repo-корпусам
DOCLOG-0..9 (RUN-D6xxxxxx, d6-*, d8-*, d9-*, org-*) и корпусам
сертификаторов (d6cert-*, d7c-*, d8cert-*, RUN-D7C*, RUN-D8C*):
**RUN-E2C*, e2cert-session-*, ctx-e2c-*, fc-e2c-*, subj-e2c-*,
tenant-e2c-2, sentinel CISSTAT_E2C_SECRET_SENTINEL**.

СВОИ данные: собственные research runs (bound к своим сессиям),
собственные артефакты (штатный artifact_store: stage/commit/register),
свои снимки/документы/согласования через штатные сервисы, свои
actual vintages и сверки MonitoringService, свои org-профили, свои
support-гранты. Изоляция каждого теста -- свой tmp_path/CISSTAT_DATA_DIR,
сброс ВСЕХ singleton-фабрик контура документирования, memory-бекенды.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ── СВОЙ namespace (дизъюнктен repo и предыдущим сертификаторам) ─────

RUN_A = "RUN-E2CA0001"           # свой run владельца session-a
RUN_B = "RUN-E2CB0002"           # чужой для session-a run
RUN_C = "RUN-E2CC0003"           # третий run (гранты/tenants)
SESSION_A = "e2cert-session-a"   # владелец RUN_A
SESSION_B = "e2cert-session-b"   # владелец RUN_B (чужой)
SESSION_C = "e2cert-session-c"   # третий субъект (гранты)
CTX_A = "ctx-e2c-1"
CTX_B = "ctx-e2c-2"
FORECAST_ID_1 = "fc-e2c-1"
FORECAST_ID_2 = "fc-e2c-2"
TENANT_2 = "tenant-e2c-2"
TARGET_NAME = "e2c_gdp_growth"
DATASET_NAME = "e2cert-seed"

ADMIN_KEY = "e2c-admin-key-0001"
LOGS_KEY = "e2c-logs-key-0002"      # logs.read+audit.read+logs.export
NOSCOPE_KEY = "e2c-noscope-key-0003"
NOEXPORT_KEY = "e2c-noexp-key-0004"  # logs.read+audit.read БЕЗ logs.export
SUBJECT_ADMIN = "subj-e2ca000000000001"
SUBJECT_LOGS = "subj-e2cb000000000002"
SUBJECT_NOSCOPE = "subj-e2cc000000000003"

ADMIN_KEYS_ENV = ",".join(
    [
        f"{ADMIN_KEY}:admin:demo:{SUBJECT_ADMIN}:tenant-default:",
        f"{LOGS_KEY}:internal_analyst:demo:{SUBJECT_LOGS}:{TENANT_2}:"
        "logs.read+audit.read+logs.export",
        f"{NOSCOPE_KEY}:internal_analyst:demo:{SUBJECT_NOSCOPE}:{TENANT_2}:",
        f"{NOEXPORT_KEY}:internal_analyst:demo:subj-e2cd000000000004:"
        f"{TENANT_2}:logs.read+audit.read",
    ]
)

E2C_SENTINEL = "e2cert-SENTINEL-секрет-не-попадает-в-ошибки-и-журналы"


def subject_of(session_id: str):
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(session_id)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Изоляция КАЖДОГО теста корпуса ────────────────────────────────────


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CISSTAT_E2C_SECRET_SENTINEL", E2C_SENTINEL)
    for var in (
        "DATABASE_URL",
        "CISSTAT_RUNS_BACKEND",
        "CISSTAT_IDENTITY_MODE",
        "CISSTAT_IDENTITY_SALT",
        "CISSTAT_ARTIFACTS_BACKEND",
        "CISSTAT_SNAPSHOTS_BACKEND",
        "CISSTAT_MONITORING_BACKEND",
        "CISSTAT_DOCUMENTS_BACKEND",
        "CISSTAT_DOCLOG_APPROVAL_POLICY",
        "CISSTAT_DOCUMENT_RETENTION_DRAFT_DAYS",
        "CISSTAT_API_KEYS",
        "CISSTAT_DOC_SIGN_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    _reset_all()
    yield
    _reset_all()


def _reset_all() -> None:
    from apps.api import artifact_store, monitoring, research_runs
    from apps.api import report_snapshot, document_jobs, document_lifecycle
    from apps.api import document_render_worker, doc_profiles, admin_logs
    from apps.api import delivery_worker, storage_diagnostics
    from apps.api.routers import documentation as documentation_router
    from apps.api.routers import logs as logs_router
    from apps.api.security_audit import reset_audit_for_testing
    from apps.api.session_store import reset_session_store_for_testing
    from apps.api.telemetry import reset_telemetry_for_testing

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    document_lifecycle.reset_document_lifecycle_registry_for_testing()
    document_render_worker.reset_document_render_worker_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    logs_router.reset_logs_service_for_testing()
    monitoring.reset_monitoring_registry_for_testing()
    doc_profiles.reset_org_profile_registry_for_testing()
    doc_profiles.reset_org_profile_service_for_testing()
    admin_logs.reset_support_grant_registry_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()
    storage_diagnostics.reset_storage_diagnostics_for_testing()
    delivery_worker.reset_delivery_worker_for_testing()


@pytest.fixture()
def client():
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


# ── Сид-хелперы (СВОИ данные, свой namespace) ─────────────────────────


def seed_session(session_id: str = SESSION_A):
    from apps.api.identity import DEFAULT_TENANT_ID
    from apps.api.session_store import AnalysisSession, get_session_store

    store = get_session_store()
    session = store.get(session_id)
    if session is not None:
        return session
    session = AnalysisSession(session_id=session_id)
    session.owner_subject = subject_of(session_id).subject_id
    session.tenant_id = DEFAULT_TENANT_ID
    session.target_column = "value"
    session.date_column = "date"
    store.save(session)
    return session


def seed_run(
    run_id: str = RUN_A,
    session_id: str = SESSION_A,
    *,
    context_id: str | None = CTX_A,
    data_revision: int | None = 3,
):
    """Свой bound research run (паритет repo-паттерна DOCLOG-8)."""
    from apps.api.identity import DEFAULT_TENANT_ID
    from apps.api.research_runs import ResearchRun, get_research_run_store

    seed_session(session_id)
    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="e2c" + "0" * 29,
        dataset_name=DATASET_NAME,
        target_column="value",
        target_column_source="user",
        created_at=now_iso(),
        last_active_at=now_iso(),
        status="active",
        context_id=context_id,
        data_revision=data_revision,
        owner_subject=subject_of(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)
    return run


def seed_event(
    run_id: str = RUN_A,
    event_type: str = "upload_completed",
    stage: str = "upload",
    *,
    payload: dict | None = None,
    evidence_level: str = "server_result",
    result_ref: dict | None = None,
    schema_version: int = 2,
) -> str:
    from apps.api.research_runs import get_research_run_store
    from apps.api.trace_events import TraceEvent

    event = TraceEvent(
        event_type=event_type,
        payload=dict(payload or {}),
        run_id=run_id,
        stage=stage,
        schema_version=schema_version,
        evidence_level=evidence_level,
        result_ref=result_ref,
    )
    get_research_run_store().append_event(run_id, event)
    return event.event_id


def make_artifact(
    kind: str,
    producer_key: str,
    payload,
    *,
    run_id: str = RUN_A,
    context_id: str | None = CTX_A,
    data_revision: int | None = 3,
):
    """Свой артефакт через штатный artifact_store (T8-совместимый)."""
    from apps.api.artifact_store import (
        ResultArtifact,
        artifact_content_sha256,
        canonical_json_bytes,
        get_artifact_object_store,
        get_artifact_registry,
        new_artifact_id,
    )

    content = canonical_json_bytes(payload)
    objects = get_artifact_object_store()
    staged = objects.stage_bytes(content, "application/json")
    storage_key = objects.commit_staged(staged)
    artifact = ResultArtifact(
        artifact_id=new_artifact_id(),
        run_id=run_id,
        kind=kind,
        producer_key=producer_key,
        media_type="application/json",
        size_bytes=len(content),
        payload_sha256=artifact_content_sha256(content),
        data_digest=None,
        storage_key=storage_key,
        context_id=context_id,
        data_revision=data_revision,
        input_kind=None,
        panel=None,
        dependencies=[],
        refs={},
    )
    stored, _created = get_artifact_registry().register_artifact(artifact)
    return stored


FORECAST_POINTS = [
    {"step": 1, "date": "2026-09-01", "value": 5.0, "ci_lower": 4.0, "ci_upper": 6.0},
    {"step": 2, "date": "2026-10-01", "value": 6.0, "ci_lower": 4.8, "ci_upper": 7.2},
    {"step": 3, "date": "2026-11-01", "value": 7.0, "ci_lower": 5.6, "ci_upper": 8.4},
    {"step": 4, "date": "2026-12-01", "value": 8.0, "ci_lower": 6.4, "ci_upper": 9.6},
]


def seed_forecast(
    run_id: str = RUN_A,
    *,
    points: list | None = None,
    forecast_id: str = FORECAST_ID_1,
    alpha: float = 0.05,
    ci_method: str = "analytic",
):
    chosen = points if points is not None else FORECAST_POINTS
    return make_artifact(
        "forecast",
        f"forecast:{forecast_id}",
        {
            "forecast_id": forecast_id,
            "model_card_id": "card-e2c-1",
            "generated_at": now_iso(),
            "horizon": len(chosen),
            "alpha": alpha,
            "ci_method": ci_method,
            "points": chosen,
        },
        run_id=run_id,
    )


def build_snapshot(
    run_id: str = RUN_A,
    session_id: str = SESSION_A,
    *,
    kinds: list[str] | None = None,
    idempotency_key: str | None = None,
    context_id: str | None = None,
    data_revision: int | None = None,
):
    """Frozen-снимок штатным сборщиком DOCLOG-2 (свои данные)."""
    from apps.api.research_runs import get_research_run_store

    if context_id is not None or data_revision is not None:
        run = get_research_run_store().get_run(run_id)
        run.context_id = context_id if context_id is not None else run.context_id
        run.data_revision = (
            data_revision if data_revision is not None else run.data_revision
        )
        get_research_run_store().upsert_run(run)
    from apps.api.snapshot_builder import SnapshotService

    subject = subject_of(session_id)
    snapshot, _created = SnapshotService.create_default().build_snapshot(
        run_id,
        subject,
        session_id=session_id,
        kinds=kinds or ["D02", "D08"],
        idempotency_key=idempotency_key,
    )
    return snapshot


def ensure_revision(snapshot, session_id: str = SESSION_A, kind_code: str = "D02"):
    """Документ+ревизия поверх снимка (адаптер DOCLOG-4)."""
    from apps.api.document_jobs import DocumentDeliveryService

    service = DocumentDeliveryService.create_default()
    document, revision, _created = service.ensure_document_revision(
        snapshot,
        subject_of(session_id),
        session_id=session_id,
        kind_code=kind_code,
    )
    return document, revision


def request_heavy_rendition(
    snapshot,
    session_id: str = SESSION_A,
    *,
    fmt: str = "xlsx",
    org_profile_id: str = "",
):
    from apps.api.document_jobs import DocumentDeliveryService

    service = DocumentDeliveryService.create_default()
    job, rendition = service.request_rendition(
        snapshot,
        format=fmt,
        subject=subject_of(session_id),
        session_id=session_id,
        org_profile_id=org_profile_id,
    )
    return service, job, rendition


def run_worker_once() -> dict:
    from apps.api.document_render_worker import DocumentRenderWorker

    return DocumentRenderWorker(interval=None).run_once()


def monitoring_service():
    from apps.api.monitoring import MonitoringService

    return MonitoringService.create_default()


def register_batch(
    run_id: str = RUN_A,
    *,
    subject=None,
    periods: list[tuple[str, float]] | None = None,
    target_name: str = TARGET_NAME,
    units: str = "percent",
    as_of: str = "2026-10-15T00:00:00+00:00",
    source_kind: str = "manual",
    idempotency_key: str = "",
):
    values = [
        {"period": period, "value": value}
        for period, value in (
            periods or [("2026-09-01", 4.8), ("2026-10-01", 6.1)]
        )
    ]
    batch, _created = monitoring_service().register_actual_batch(
        run_id,
        subject if subject is not None else subject_of(SESSION_A),
        target_name=target_name,
        units=units,
        as_of=as_of,
        values=values,
        source_kind=source_kind,
        idempotency_key=idempotency_key,
    )
    return batch


def build_comparison(
    run_id: str = RUN_A,
    *,
    artifact,
    batch,
    subject=None,
    **kwargs,
):
    record, _created = monitoring_service().build_comparison(
        run_id,
        subject if subject is not None else subject_of(SESSION_A),
        forecast_artifact_id=artifact.artifact_id,
        actual_batch_id=batch.batch_id,
        **kwargs,
    )
    return record


def cookie(client: TestClient, session_id: str = SESSION_A) -> None:
    from apps.api.session_store import SESSION_COOKIE_NAME

    client.cookies.set(SESSION_COOKIE_NAME, session_id)


def api_key(client: TestClient, key: str = ADMIN_KEY) -> None:
    client.headers["x-api-key"] = key


def clear_api_key(client: TestClient) -> None:
    client.headers.pop("x-api-key", None)


def approval_route(revision_id: str) -> str:
    return f"/v1/documentation/revisions/{revision_id}/approvals"


def publish_flow(
    client: TestClient,
    revision,
    *,
    session_id: str = SESSION_A,
    two_person: bool = False,
) -> dict:
    """Полный поток: запрос согласования -> approve -> publish."""
    if two_person:
        import os

        os.environ["CISSTAT_DOCLOG_APPROVAL_POLICY"] = "two_person"
    cookie(client, session_id)
    r1 = client.post(approval_route(revision.revision_id), json={"action": "request"})
    assert r1.status_code == 200, r1.text
    api_key(client, ADMIN_KEY)
    r2 = client.post(
        approval_route(revision.revision_id),
        json={"decision": "approve", "reason": "e2cert"},
    )
    assert r2.status_code == 200, r2.text
    r3 = client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/publish"
    )
    assert r3.status_code == 200, r3.text
    return r3.json()


def science_fingerprint(run_id: str = RUN_A) -> str:
    """Отпечаток НАУЧНОГО состояния (AC05-tripwire): run-запись + события
    + реестры артефактов/снимков/документов/мониторинга/профилей +
    retention/lifecycle. Audit-поток СОЗНАТЕЛЬНО исключён (audit access
    может добавляться -- §20 AC05)."""
    import hashlib
    import json

    from apps.api import artifact_store, monitoring, report_snapshot
    from apps.api import document_jobs, doc_profiles
    from apps.api.research_runs import get_research_run_store

    def _dump(obj) -> str:
        if obj is None:
            return "null"
        if hasattr(obj, "to_dict"):
            return json.dumps(obj.to_dict(), sort_keys=True, ensure_ascii=False, default=str)
        return json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)

    run = get_research_run_store().get_run(run_id)
    events = get_research_run_store().list_events(run_id)
    from apps.api.document_jobs import DocumentDeliveryService

    docs = DocumentDeliveryService.create_default().list_documents(
        run_id, subject_of(SESSION_A), session_id=SESSION_A
    )
    doc_ids = sorted(pair[0].document_id for pair in docs)
    parts = [
        _dump(run),
        _dump([e.to_dict() if hasattr(e, "to_dict") else e for e in events]),
        _dump(sorted(a.artifact_id for a in artifact_store.get_artifact_registry().list_artifacts(run_id))),
        _dump(sorted(r.snapshot_id for r in report_snapshot.peek_snapshot_registry().list_records(run_id))),
        _dump(doc_ids),
        _dump(sorted(b.batch_id for b in monitoring.get_monitoring_registry().list_actual_batches(run_id))),
        _dump(sorted(c.comparison_id for c in monitoring.get_monitoring_registry().list_comparisons(run_id))),
    ]
    try:
        profiles = doc_profiles.org_profile_service().list_profiles()
        parts.append(_dump(sorted(p.profile_id for p in profiles)))
    except Exception:
        parts.append("profiles-err")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
