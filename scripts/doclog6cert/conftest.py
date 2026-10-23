# scripts/doclog6cert/conftest.py
"""DOCLOG-6-CERT (независимая сертификация DOCLOG-6 на базе 70c9c1a):
фикстуры оракулов на СВОИХ данных.

Корпус сертификатора дизъюнктен repo-корпусу DOCLOG-6 (RUN-D6A*/RUN-D6B*,
d6-*, ключи d6-admin-key-7f31/d6-reviewer-key-42ab) и корпусам
DOCLOG-3/4/5-CERT (RUN-D3C*, RUN-D4C*/d4cert-*, RUN-D5C*/d5cert-*):
namespace -- RUN-D6C*, d6cert-*, d6c-cert-*, tenant tenant-d6cert-b.

Собственные frozen-снимки -- ПРЯМАЯ КОНСТРУКЦИЯ ReportSnapshot (свои
cutoff/captured_at/claims/полнота; валидный id rs-<hex32>, т.к. чтение
через SnapshotService.get_snapshot валидирует формат) с регистрацией в
штатном SnapshotRegistry (свой ObjectStore в tmp_path) -- approval
связывает МОЙ payload_sha256, publish/verify/diff работают с МОИМИ
байтами (§10.2: registry-метаданные не входят в канонические байты).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# ── Пространство имён сертификатора (дизъюнкт) ───────────────────────

CERT_RUN_ID = "RUN-D6C00001"
CERT_RUN_ID_B = "RUN-D6C00002"          # run, принадлежащий key-субъекту
CERT_RUN_ID_C = "RUN-D6C00003"          # пустой run (без документов)
CERT_SESSION = "d6cert-session-a"
CERT_SESSION_B = "d6cert-session-b"
CERT_FOREIGN_SESSION = "d6c-cert-foreign-session"
CERT_TENANT_B = "tenant-d6cert-b"

CERT_ADMIN_KEY = "d6cert-admin-key-91ce"
CERT_WRITER_KEY = "d6cert-writer-key-4a02"    # documentation.write
CERT_APPROVER_KEY = "d6cert-approver-key-77b3"  # documentation.approve
CERT_WRITER_SUBJ = "d6cert-writer-subj"
CERT_APPROVER_SUBJ = "d6cert-approver-subj"


@pytest.fixture(autouse=True)
def _cert_isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Изоляция КАЖДОГО оракула: свой data-dir, без PG, сброс всех
    singleton-фабрик (паритет repo-паттерна, но СВОЙ tmp_path)."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "d6cert-data"))
    for name in (
        "DATABASE_URL",
        "CISSTAT_RUNS_BACKEND",
        "CISSTAT_IDENTITY_MODE",
        "CISSTAT_API_KEYS",
        "CISSTAT_IDENTITY_SALT",
        "CISSTAT_ARTIFACTS_BACKEND",
        "CISSTAT_SNAPSHOTS_BACKEND",
        "CISSTAT_DOCUMENTS_BACKEND",
        "CISSTAT_DOCLOG_APPROVAL_POLICY",
        "CISSTAT_DOCUMENT_RETENTION_DRAFT_DAYS",
        "CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    _reset_all()
    yield
    _reset_all()


def _reset_all() -> None:
    from apps.api import (
        artifact_store,
        document_jobs,
        document_lifecycle,
        document_render_worker,
        research_runs,
    )
    from apps.api.routers import documentation as documentation_router
    from apps.api.report_snapshot import reset_snapshot_registry_for_testing
    from apps.api.security_audit import reset_audit_for_testing
    from apps.api.session_store import reset_session_store_for_testing
    from apps.api.telemetry import reset_telemetry_for_testing

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    document_lifecycle.reset_document_lifecycle_registry_for_testing()
    document_render_worker.reset_document_render_worker_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()


@pytest.fixture()
def cert_client():
    from fastapi.testclient import TestClient

    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


# ── СВОИ снимки: прямая конструкция + регистрация ────────────────────

OWN_SECTIONS_A = [
    {
        "code": "D01",
        "title": "Сводка собственного запуска сертификации",
        "kind": "summary",
        "methodology_stage": "S1",
        "claims": [
            {
                "text": "Утверждение корпуса D6C: коэффициент детерминации 0.83 на окне 36",
                "validity": "current",
                "evidence_level": "server_result",
                "event_refs": ["evt-d6c-1"],
                "result_refs": ["res-d6c-1"],
            },
            {
                "text": "Кириллическая гипотеза о сезонности месяца -- требует проверки",
                "validity": "unknown",
                "evidence_level": None,
                "event_refs": [],
                "result_refs": [],
            },
        ],
    },
    {
        "code": "D02",
        "title": "Методика корпуса D6C",
        "kind": "methods",
        "methodology_stage": "S2",
        "claims": [
            {
                "text": "Методика: скользящее окно 12, шаг 1, holdout 8 точек",
                "validity": "current",
                "evidence_level": "server_result",
                "event_refs": ["evt-d6c-2"],
                "result_refs": [],
            },
        ],
    },
]

OWN_SECTIONS_B = [
    {
        "code": "D01",
        "title": "Сводка собственного запуска сертификации",
        "kind": "summary",
        "methodology_stage": "S1",
        "claims": [
            {
                # тот же текст -- validity изменена (для diff-оракула)
                "text": "Утверждение корпуса D6C: коэффициент детерминации 0.83 на окне 36",
                "validity": "stale",
                "evidence_level": "server_result",
                "event_refs": ["evt-d6c-1"],
                "result_refs": ["res-d6c-1"],
            },
            {
                # новое утверждение (для diff-оракула added)
                "text": "Новое утверждение ревизии B: добавлена проверка остатков",
                "validity": "current",
                "evidence_level": "server_result",
                "event_refs": ["evt-d6c-3"],
                "result_refs": [],
            },
        ],
    },
]


def own_snapshot_id(key: str) -> str:
    """Валидный id (rs-<hex32> -- SNAPSHOT_ID_PATTERN) с детерминизмом
    от собственного namespace."""
    return "rs-" + hashlib.md5(f"d6cert-{key}".encode()).hexdigest()


def build_own_snapshot(
    *,
    snapshot_key: str = "snap-a",
    run_id: str = CERT_RUN_ID,
    kinds: list[str] | None = None,
    sections: list[dict] | None = None,
    completeness: dict | None = None,
    context_id: str = "ctx-d6cert-1",
    data_revision: int = 7,
    captured_at: str = "2026-10-23T12:30:00+00:00",
    event_count: int = 61,
    last_sequence: int = 2061,
):
    """СВОЙ frozen-снимок: свои cutoff/captured_at/claims; регистрация в
    штатном реестре со своим ObjectStore; payload_sha256 -- МОЙ hash,
    с которым связывается approval (AC07)."""
    from apps.api.artifact_store import (
        canonical_json_bytes,
        get_artifact_object_store,
    )
    from apps.api.report_snapshot import ReportSnapshot, get_snapshot_registry

    snapshot = ReportSnapshot(
        snapshot_id=own_snapshot_id(snapshot_key),
        research_run_id=run_id,
        context_id=context_id,
        data_revision=data_revision,
        source_cutoff={
            "event_count": event_count,
            "last_sequence": last_sequence,
            "ordering_quality": "monotonic",
        },
        captured_at=captured_at,
        template={"id": "tpl-d6cert", "version": 4},
        knowledge_version="kv-d6cert-6",
        classification="internal",
        redaction_profile="standard",
        completeness=completeness
        or {"status": "complete", "missing_refs": []},
        reproducibility={
            "status": "limited",
            "reasons": ["данные не включены (d6cert)"],
        },
        sections=sections if sections is not None else OWN_SECTIONS_A,
        dependencies=["dep-d6c-1"],
    )
    snapshot.kinds = list(kinds or ["D01", "D02"])
    # СВОЙ idempotency_key на каждый снимок: реестр обязан хранить
    # несколько собственных снимков одного run (иначе идемпотентность
    # вернёт первый снимок с пустым ключом -- урок калибровки a12).
    snapshot.idempotency_key = f"d6cert-{snapshot_key}"
    snapshot.request_fingerprint = hashlib.sha256(
        f"d6cert-{snapshot_key}".encode()
    ).hexdigest()
    payload = canonical_json_bytes(snapshot.to_dict())
    storage_key = get_artifact_object_store().commit_staged(
        get_artifact_object_store().stage_bytes(payload, "application/json")
    )
    snapshot.payload_sha256 = hashlib.sha256(payload).hexdigest()
    snapshot.size_bytes = len(payload)
    snapshot.storage_key = storage_key
    get_snapshot_registry().register_snapshot(snapshot, [{"ref": "dep-d6c-1"}])
    return snapshot


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_cert_run(
    run_id: str = CERT_RUN_ID,
    session_id: str = CERT_SESSION,
    *,
    owner_subject_id: str | None = None,
    tenant_id: str | None = None,
) -> None:
    """Свой bound-run (штатная механика ownership DOCLOG-0); опционально
    владелец -- key-субъект (для оракулов разделения прав по scopes)."""
    from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
    from apps.api.research_runs import ResearchRun, get_research_run_store
    from apps.api.session_store import AnalysisSession, get_session_store

    store = get_session_store()
    session = store.get(session_id)
    if session is None:
        session = AnalysisSession(session_id=session_id)
        session.owner_subject = SubjectRef.from_session(session_id).subject_id
    session.tenant_id = tenant_id or DEFAULT_TENANT_ID
    session.target_column = "value"
    session.date_column = "date"
    store.save(session)
    get_research_run_store().upsert_run(
        ResearchRun(
            run_id=run_id,
            session_id=session_id,
            dataset_fingerprint="d6c" * 10 + "6",
            dataset_name="d6cert-seed",
            target_column="value",
            target_column_source="user",
            created_at=_now_iso(),
            last_active_at=_now_iso(),
            status="active",
            context_id=f"ctx-{run_id.lower()}-1",
            data_revision=7,
            owner_subject=owner_subject_id
            or SubjectRef.from_session(session_id).subject_id,
            tenant_id=tenant_id or DEFAULT_TENANT_ID,
            ownership="bound",
        )
    )


def cert_subject(session_id: str = CERT_SESSION):
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(session_id)


def ensure_own_revision(snapshot, kind_code: str, session_id: str = CERT_SESSION):
    """Документ+ревизия поверх СВОЕГО снимка (штатный адаптер DOCLOG-4,
    поверхность которого сертифицирована DOCLOG-4-CERT)."""
    from apps.api.document_jobs import DocumentDeliveryService

    service = DocumentDeliveryService.create_default()
    document, revision, _created = service.ensure_document_revision(
        snapshot,
        cert_subject(session_id),
        session_id=session_id,
        kind_code=kind_code,
    )
    return document, revision


def register_failed_rendition(revision, snapshot) -> object:
    """СВОЯ failed-rendition: не-ready форма НЕ попадает в approval
    manifest (собственный негативный контроль канала approval)."""
    from apps.api.document_jobs import (
        DocumentDeliveryService,
        DocumentRenditionRecord,
    )

    delivery = DocumentDeliveryService.create_default()
    return delivery.registry.register_rendition(
        DocumentRenditionRecord(
            rendition_id="rend-d6cert-failed-0001",
            revision_id=revision.revision_id,
            snapshot_id=snapshot.snapshot_id,
            run_id=snapshot.research_run_id,
            format="json",
            state="failed",
            content_sha256="e" * 64,
            created_by="d6cert-seed",
        )
    )


# ── HTTP-хелперы ─────────────────────────────────────────────────────

def cookie(client, session_id: str = CERT_SESSION) -> None:
    from apps.api.session_store import SESSION_COOKIE_NAME

    client.cookies.set(SESSION_COOKIE_NAME, session_id)


def api_key(client, key: str) -> None:
    client.headers["x-api-key"] = key


def scoped_keys_env() -> str:
    from apps.api.identity import DEFAULT_TENANT_ID

    return ",".join(
        [
            f"{CERT_ADMIN_KEY}:admin:demo:{CERT_ADMIN_KEY}-subj:{DEFAULT_TENANT_ID}:",
            f"{CERT_WRITER_KEY}:internal_analyst:demo:{CERT_WRITER_SUBJ}:{DEFAULT_TENANT_ID}:documentation.write",
            f"{CERT_APPROVER_KEY}:internal_analyst:demo:{CERT_APPROVER_SUBJ}:{DEFAULT_TENANT_ID}:documentation.approve",
        ]
    )


def approve_route(revision_id: str) -> str:
    return f"/v1/documentation/revisions/{revision_id}/approvals"


def full_publish_flow(
    client,
    document,
    revision,
    *,
    session_id: str = CERT_SESSION,
    expect: int = 200,
):
    """Полный поток на СВОИХ данных: request -> approve -> publish."""
    cookie(client, session_id)
    r1 = client.post(approve_route(revision.revision_id), json={"action": "request"})
    assert r1.status_code == 200, r1.text
    r2 = client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve", "reason": "d6cert-ok"},
    )
    assert r2.status_code == 200, r2.text
    r3 = client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/publish"
    )
    assert r3.status_code == expect, r3.text
    return r3


def data_root() -> Path:
    import os

    return Path(os.environ["CISSTAT_DATA_DIR"])


def archive_dir(run_id: str, bundle_id: str) -> Path:
    return data_root() / "archive" / run_id / bundle_id
