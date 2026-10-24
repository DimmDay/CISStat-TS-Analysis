# scripts/doclog7cert/conftest.py
"""DOCLOG-7-CERT (2026-10-24): фикстуры корпуса сертификатора.

Методология «оракулы на своих данных, мутанты на своих мутантах»
(прецедент DOCLOG-3/4/5/6-CERT). Namespace дизъюнктен repo-корпусам
DOCLOG-0..7 (RUN-D7xxxxxx, d7-*, tenant-d7*, subj-d7*) и корпусам
предыдущих сертификаторов (d6cert-*, doclog3cert-*, ...): **d7c-*,
RUN-D7C*, tenant-d7cert-*, subj-d7c***.

СВОИ данные: собственные telemetry/audit/delivery-записи ПРЯМОЙ
посадки (через штатные emit/build_audit_record/DocumentRegistry),
собственные support grants, свои API-ключи 6-сегментного формата
реестра (включая scoped-ключи и support.grant-ключ НЕ-админа), свой
sentinel-секрет в env для AC10-оракула пакета.

Изоляция каждого теста -- паттерн tests/api/test_doclog7_logs_support.py:
свой tmp_path/CISSTAT_DATA_DIR, сброс singleton-фабрик, memory-бекенды
по умолчанию (DATABASE_URL удалён).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ── СВОЙ namespace (дизъюнктен repo и предыдущим сертификаторам) ─────

API_KEYS_ENV = (
    "d7c-admin-key-1111:admin::subj-d7caaaaaaaaaaaaa:tenant-d7cert-core:,"
    "d7c-support-key-2222:external_user:starter:subj-d7cbbbbbbbbbbbbb:tenant-d7cert-other:,"
    "d7c-scoped-key-3333:external_user:starter:subj-d7cccccccccccccc:tenant-d7cert-other:logs.read+audit.read+logs.export,"
    "d7c-ro-key-4444:external_user:starter:subj-d7cddddddddddddd:tenant-d7cert-other:logs.read,"
    "d7c-mgr-key-5555:external_user:starter:subj-d7ceeeeeeeeeeeee:tenant-d7cert-other:support.grant,"
    "d7c-zeta-key-6666:external_user:starter:subj-d7cfffffffffffff:tenant-d7cert-zeta:"
)

ADMIN_KEY = "d7c-admin-key-1111"
SUPPORT_KEY = "d7c-support-key-2222"        # scopes нет -- только через grants
SCOPED_KEY = "d7c-scoped-key-3333"          # logs.read+audit.read+logs.export (реестр)
RO_KEY = "d7c-ro-key-4444"                  # только logs.read
MGR_KEY = "d7c-mgr-key-5555"                # только support.grant (НЕ админ)
ZETA_KEY = "d7c-zeta-key-6666"              # scopes нет, чужой tenant

ADMIN_SUBJECT = "subj-d7caaaaaaaaaaaaa"
SUPPORT_SUBJECT = "subj-d7cbbbbbbbbbbbbb"
SCOPED_SUBJECT = "subj-d7cccccccccccccc"
RO_SUBJECT = "subj-d7cddddddddddddd"
MGR_SUBJECT = "subj-d7ceeeeeeeeeeeee"
ZETA_SUBJECT = "subj-d7cfffffffffffff"

TENANT_CORE = "tenant-d7cert-core"
TENANT_OTHER = "tenant-d7cert-other"
TENANT_ZETA = "tenant-d7cert-zeta"
RUN_A = "RUN-D7CA0001"
RUN_B = "RUN-D7CB0002"

# AC10-сентинел: значение env, которое НИКОГДА не должно попасть
# ни в пакет, ни в ответы ошибок.
SECRET_SENTINEL = "d7c-SENTINEL-env-секрет-AC10-молния"

# СВОИ snapshot_id (валидный шаблон rs-<hex32>, алфавит hex).
SNAPSHOT_A = "rs-" + ("d7c" * 11)[:32]

# База сидов относительно РЕАЛЬНЫХ часов среды (дефолтное окно запроса
# [now-24h, now]; более старые сиды -- честная невидимость по умолчанию).
_T0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=2)


def iso(dt: datetime) -> str:
    return dt.isoformat()


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Изоляция КАЖДОГО теста корпуса сертификатора."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CISSTAT_API_KEYS", API_KEYS_ENV)
    monkeypatch.setenv("CISSTAT_D7C_SECRET_SENTINEL", SECRET_SENTINEL)
    for var in (
        "DATABASE_URL",
        "CISSTAT_RUNS_BACKEND",
        "CISSTAT_IDENTITY_MODE",
        "CISSTAT_IDENTITY_SALT",
        "CISSTAT_TELEMETRY_BACKEND",
        "CISSTAT_AUDIT_BACKEND",
        "CISSTAT_DOCUMENTS_BACKEND",
        "CISSTAT_GRANTS_BACKEND",
    ):
        monkeypatch.delenv(var, raising=False)
    _reset_all()
    yield
    _reset_all()


def _reset_all() -> None:
    from apps.api import admin_logs, document_jobs, research_runs
    from apps.api.routers import logs as logs_router
    from apps.api.security_audit import reset_audit_for_testing
    from apps.api.session_store import reset_session_store_for_testing
    from apps.api.telemetry import reset_telemetry_for_testing

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    document_jobs.reset_document_registry_for_testing()
    admin_logs.reset_support_grant_registry_for_testing()
    logs_router.reset_logs_service_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()


@pytest.fixture()
def client():
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def admin_client(client: TestClient) -> TestClient:
    client.headers.update({"X-API-Key": ADMIN_KEY})
    return client


# ── Сид-хелперы (СВОИ данные, свой namespace) ─────────────────────────


def seed_telemetry(
    count: int = 3,
    *,
    event_name: str = "d7c.seed.event",
    severity: str = "info",
    outcome: str = "success",
    request_id: str = "req-d7c-0001",
    run_id: str | None = RUN_A,
    tenant_id: str | None = TENANT_CORE,
    start: datetime = _T0,
    message_prefix: str = "событие d7c",
) -> None:
    """Свои telemetry-записи через штатный emit (occurred_at от T0)."""
    from apps.api import telemetry

    for i in range(count):
        telemetry.emit(
            event_name,
            severity,
            message_template=f"{message_prefix} #{i}",
            attributes={"component": f"d7c-seed-{i}"},
            outcome=outcome,
            request_id=request_id,
            research_run_id=run_id,
            tenant_id=tenant_id,
            occurred_at=iso(start + timedelta(seconds=i)),
            essential=True,
        )


def seed_audit(
    action: str = "run_access_allowed",
    decision: str = "allowed",
    *,
    actor_subject: str = SUPPORT_SUBJECT,
    tenant_id: str | None = TENANT_CORE,
    run_id: str | None = RUN_A,
    occurred_at: datetime = _T0,
    resource_id: str | None = None,
) -> str:
    """Свои audit-записи через штатные build_audit_record + sink.append."""
    from apps.api import security_audit

    record = security_audit.build_audit_record(
        action,
        decision,
        actor_subject=actor_subject,
        actor_via="api_key",
        tenant_id=tenant_id,
        resource_kind="research_run",
        resource_id=resource_id or run_id or "res-d7c",
        run_id=run_id,
        policy_basis="d7ceeeeeeeeeeeeert membership",
        occurred_at=iso(occurred_at),
        details={"note": "d7c audit seed"},
    )
    security_audit.get_audit_sink().append(record)
    return record["audit_id"]


def seed_delivery(
    *,
    state: str = "ready",
    tenant_id: str = TENANT_CORE,
    run_id: str = RUN_A,
    format_: str = "pdf",
    attempt: int = 1,
) -> str:
    """Своя цепочка document -> revision -> rendition -> job (D02)."""
    from apps.api.document_jobs import (
        DocumentJobRecord,
        DocumentRecord,
        DocumentRenditionRecord,
        DocumentRevisionRecord,
        get_document_registry,
        new_document_id,
        new_job_id,
        new_rendition_id,
        new_revision_id,
    )

    registry = get_document_registry()
    document = registry.register_document(
        DocumentRecord(document_id=new_document_id(), run_id=run_id, kind_code="D02")
    )
    revision = registry.register_revision(
        DocumentRevisionRecord(
            revision_id=new_revision_id(),
            document_id=document.document_id,
            snapshot_id=SNAPSHOT_A,
            run_id=run_id,
            version_no=1,
        )
    )
    rendition = registry.register_rendition(
        DocumentRenditionRecord(
            rendition_id=new_rendition_id(),
            revision_id=revision.revision_id,
            snapshot_id=revision.snapshot_id,
            run_id=run_id,
            format=format_,
            state="ready" if state == "failed" else state,
        )
    )
    job = registry.register_job(
        DocumentJobRecord(
            job_id=new_job_id(),
            run_id=run_id,
            snapshot_id=revision.snapshot_id,
            format=format_,
            revision_id=revision.revision_id,
            rendition_id=rendition.rendition_id,
            state=state,
            error_code="render_error" if state == "failed" else None,
            attempt=2 if state == "failed" else attempt,
            tenant_id=tenant_id,
        )
    )
    return job.job_id


def seed_delivery_chain(
    *, tenant_id: str = TENANT_CORE, run_id: str = RUN_A, state: str = "ready"
) -> dict:
    """Своя цепочка с возвратом всех идентификаторов (пин join'а)."""
    from apps.api.document_jobs import (
        DocumentJobRecord,
        DocumentRecord,
        DocumentRenditionRecord,
        DocumentRevisionRecord,
        get_document_registry,
        new_document_id,
        new_job_id,
        new_rendition_id,
        new_revision_id,
    )

    registry = get_document_registry()
    document = registry.register_document(
        DocumentRecord(document_id=new_document_id(), run_id=run_id, kind_code="D02")
    )
    revision = registry.register_revision(
        DocumentRevisionRecord(
            revision_id=new_revision_id(),
            document_id=document.document_id,
            snapshot_id=SNAPSHOT_A,
            run_id=run_id,
            version_no=1,
        )
    )
    rendition = registry.register_rendition(
        DocumentRenditionRecord(
            rendition_id=new_rendition_id(),
            revision_id=revision.revision_id,
            snapshot_id=revision.snapshot_id,
            run_id=run_id,
            format="pdf",
            state="ready",
        )
    )
    job = registry.register_job(
        DocumentJobRecord(
            job_id=new_job_id(),
            run_id=run_id,
            snapshot_id=revision.snapshot_id,
            format="pdf",
            revision_id=revision.revision_id,
            rendition_id=rendition.rendition_id,
            state=state,
            tenant_id=tenant_id,
        )
    )
    return {
        "document_id": document.document_id,
        "revision_id": revision.revision_id,
        "rendition_id": rendition.rendition_id,
        "job_id": job.job_id,
    }


def make_grant_record(
    *,
    grant_id: str = "d7grant-d7ceeeeeeeeeeeeert-unit-0001",
    subject_id: str = SUPPORT_SUBJECT,
    tenant_id: str = TENANT_CORE,
    run_id: str | None = None,
    scopes: tuple[str, ...] = ("logs.read",),
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
    revoked_at: str | None = None,
):
    """Прямая (без audit-зависимости) запись гранта."""
    from apps.api.admin_logs import SupportGrantRecord

    now = created_at or datetime.now(timezone.utc)
    return SupportGrantRecord(
        grant_id=grant_id,
        ticket="d7c-ticket-unit",
        purpose="d7c unit grant",
        subject_id=subject_id,
        tenant_id=tenant_id,
        run_id=run_id,
        scopes=scopes,
        created_by=ADMIN_SUBJECT,
        created_at=now.isoformat(),
        expires_at=(expires_at or (now + timedelta(hours=24))).isoformat(),
        revoked_at=revoked_at,
    )


def create_grant_via_api(
    admin: TestClient,
    *,
    subject_id: str = SUPPORT_SUBJECT,
    tenant_id: str = TENANT_CORE,
    run_id: str | None = None,
    scopes: list[str] | None = None,
    ttl_hours: float = 24.0,
    ticket: str = "d7c-ticket-42",
    purpose: str = "разбор инцидента d7c",
) -> dict:
    body = {
        "ticket": ticket,
        "purpose": purpose,
        "subject_id": subject_id,
        "tenant_id": tenant_id,
        "scopes": scopes if scopes is not None else ["logs.read"],
        "ttl_hours": ttl_hours,
    }
    if run_id is not None:
        body["run_id"] = run_id
    response = admin.post("/v1/logs/grants", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def audit_count(action: str, resource_id: str | None = None) -> int:
    from apps.api.security_audit import audit_records

    return sum(
        1
        for r in audit_records()
        if r.get("action") == action
        and (resource_id is None or r.get("resource_id") == resource_id)
    )


class FailingAuditSink:
    """Свой ломучий sink (проба AC11 mandatory fail-closed)."""

    def __init__(self) -> None:
        self.calls = 0

    def append(self, record):
        self.calls += 1
        raise RuntimeError("d7c audit outage")

    def readiness_probe(self):
        return {"ok": False, "backend": "memory", "note": "d7c failing sink"}
