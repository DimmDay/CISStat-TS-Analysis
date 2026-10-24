# scripts/doclog9cert/conftest.py
"""DOCLOG-9-CERT (2026-10-24): фикстуры корпуса сертификатора
независимой сертификации DOCLOG-9 «Профили организации».

Методология «оракулы на своих данных, мутанты на своих мутантах»
(прецедент DOCLOG-3..8-CERT). Namespace дизъюнктен repo-корпусам
DOCLOG-0..9 (RUN-D9A*, d9-*, d9prof-*) и корпусам предыдущих
сертификаторов (d6cert-*, d7c-*, d8cert-*): **RUN-D9C*, d9cert-*,
ctx-d9cert-*, subj-d9cert*, d9cert-session-***, свой AC-сентинел env
CISSTAT_D9C_SECRET_SENTINEL, свои ключи d9cert-key-* (в т.ч. субъект
с ПРАВОМ policy.admin БЕЗ роли admin -- §15: право через scopes).

СВОИ данные: собственные sessions/bound-runs/снимки (штатный
SnapshotService), собственные документы/ревизии (штатный
ensure_document_revision), собственные профили организации (штатный
OrgProfileService), свои ключи подписи (CISSTAT_DOC_SIGN_KEY).

Изоляция каждого теста -- паттерн tests/api/test_doclog9_profiles.py +
DOCLOG-8-CERT: свой tmp_path/CISSTAT_DATA_DIR, memory-бекенды, сброс
всех singleton-фабрик (включая org-profile registry+СЕРВИС парой --
урок worklog11: сброс реестра без сброса сервиса оставлял бы старый
Memory-реестр).
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ── СВОЙ namespace (дизъюнктен repo и предыдущим сертификаторам) ─────

RUN_A = "RUN-D9CA0001"          # свой run владельца session-a
RUN_B = "RUN-D9CB0002"          # свой второй run (чужой для session-a)
SESSION_A = "d9cert-session-a"  # владелец RUN_A
SESSION_B = "d9cert-session-b"  # владелец RUN_B (uniform-404 кейсы)
SESSION_C = "d9cert-session-c"  # третий субъект (посторонний)
CTX_A = "ctx-d9cert-1"

D9C_SENTINEL = "d9cert-SENTINEL-секрет-не-попадает-в-ошибки"

# Свои ключи X-API-Key (формат auth.py: key:role:plan:subject:tenant:scopes)
API_KEYS_ENV = (
    "d9cert-key-adm:admin::subj-d9certadm00000001:tenant-d9cert:,"
    "d9cert-key-pol:external_user:starter:subj-d9certpol0000002:tenant-d9cert:policy.admin+documentation.write,"
    "d9cert-key-wrt:external_user:starter:subj-d9certwrt0000003:tenant-d9cert:documentation.write,"
    "d9cert-key-oth:external_user:starter:subj-d9certoth0000004:tenant-d9other:"
)
ADMIN_KEY = "d9cert-key-adm"
POLICY_KEY = "d9cert-key-pol"    # policy.admin БЕЗ роли admin (§15 scopes)
WRITER_KEY = "d9cert-key-wrt"
OTHER_KEY = "d9cert-key-oth"

SIGN_KEY_VALUE = "d9cert-sign-secret-7777"


def subject_of(session_id: str = SESSION_A, *, role: str | None = None,
               scopes: frozenset[str] | None = None):
    """Свой субъект (SubjectRef immutable -- собирается через replace)."""
    from apps.api.identity import SubjectRef

    base = SubjectRef.from_session(session_id)
    if role is None and scopes is None:
        return base
    return replace(
        base,
        **({"role": role} if role is not None else {}),
        **({"scopes": frozenset(scopes)} if scopes is not None else {}),
    )


def admin_subject():
    return subject_of(SESSION_A, role="admin",
                      scopes=frozenset({"policy.admin", "documentation.write",
                                        "documentation.read"}))


def policy_subject():
    """§15: право policy.admin через SCOPES, не через роль."""
    return subject_of(SESSION_B, role="external_user",
                      scopes=frozenset({"policy.admin"}))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Изоляция КАЖДОГО теста корпуса сертификатора."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CISSTAT_D9C_SECRET_SENTINEL", D9C_SENTINEL)
    for var in (
        "DATABASE_URL",
        "CISSTAT_RUNS_BACKEND",
        "CISSTAT_IDENTITY_MODE",
        "CISSTAT_IDENTITY_SALT",
        "CISSTAT_ARTIFACTS_BACKEND",
        "CISSTAT_SNAPSHOTS_BACKEND",
        "CISSTAT_DOCUMENTS_BACKEND",
        "CISSTAT_DOC_PROFILES_BACKEND",
        "CISSTAT_DOC_SIGN_KEY",
        "CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED",
        "CISSTAT_DOCUMENT_RENDER_WORKER_INTERVAL",
        "CISSTAT_DOCUMENT_RENDER_WORKER_BATCH",
        "CISSTAT_DOCUMENT_RENDER_WORKER_PER_TENANT",
        "CISSTAT_DOCUMENT_RENDER_WORKER_RENDER_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CISSTAT_API_KEYS", API_KEYS_ENV)
    _reset_all()
    yield
    _reset_all()


def _reset_all() -> None:
    from apps.api import artifact_store, doc_profiles, report_snapshot
    from apps.api import document_jobs, document_render_worker, research_runs
    from apps.api.routers import documentation as documentation_router
    from apps.api.security_audit import reset_audit_for_testing
    from apps.api.session_store import reset_session_store_for_testing
    from apps.api.telemetry import reset_telemetry_for_testing

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    document_render_worker.reset_document_render_worker_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    # Пара registry+service -- ОДНИМ reset'ом (урок worklog11).
    doc_profiles.reset_org_profile_registry_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()


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


def seed_run(run_id: str = RUN_A, session_id: str = SESSION_A):
    from apps.api.identity import DEFAULT_TENANT_ID
    from apps.api.research_runs import ResearchRun, get_research_run_store

    seed_session(session_id)
    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="d9c" + "0" * 29,
        dataset_name="d9cert-seed",
        target_column="value",
        target_column_source="user",
        created_at=now_iso(),
        last_active_at=now_iso(),
        status="active",
        context_id=CTX_A,
        data_revision=3,
        owner_subject=subject_of(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)
    return run


def seed_event(run_id: str = RUN_A) -> None:
    from apps.api.trace_events import TraceEvent

    event = TraceEvent(
        event_type="upload_completed",
        payload={"dataset": "d9cert-seed"},
        run_id=run_id,
        stage="upload",
        schema_version=2,
        evidence_level="server_result",
    )
    from apps.api.research_runs import get_research_run_store

    get_research_run_store().append_event(run_id, event)


def seed_snapshot(run_id: str = RUN_A, session_id: str = SESSION_A):
    """Свой frozen-снимок через штатный SnapshotService."""
    seed_session(session_id)
    seed_run(run_id, session_id)
    seed_event(run_id)
    from apps.api.snapshot_builder import SnapshotService

    snapshot, _created = SnapshotService.create_default().build_snapshot(
        run_id,
        subject_of(session_id),
        session_id=session_id,
        kinds=["D01", "D02"],
    )
    return snapshot


def profile_service():
    from apps.api.doc_profiles import org_profile_service

    return org_profile_service()


def make_profile(
    *,
    name: str = "d9cert-gost",
    fmt: str = "pdfa",
    version_no: int = 1,
    sign_contents: bool = False,
    anchor_registry: bool = False,
    worm_lock: bool = False,
    validate_conformance: bool = True,
    title_prefix: str = "d9cert · организация",
    footer_text: str = "Подготовлено d9cert-профилью",
    organization: str = "Организация d9cert",
    subject=None,
):
    """Свой профиль через штатный сервис (policy.admin-субъект)."""
    return profile_service().create_profile(
        name=name,
        version_no=version_no,
        format=fmt,
        subject=subject if subject is not None else admin_subject(),
        validate_conformance=validate_conformance,
        title_prefix=title_prefix,
        footer_text=footer_text,
        organization=organization,
        sign_contents=sign_contents,
        anchor_registry=anchor_registry,
        worm_lock=worm_lock,
    )


def delivery():
    from apps.api.document_jobs import DocumentDeliveryService

    return DocumentDeliveryService.create_default()


def run_worker_once() -> None:
    from apps.api.document_render_worker import DocumentRenderWorker

    DocumentRenderWorker().run_once()


def render_with_profile(
    snapshot,
    fmt: str,
    profile,
    *,
    revision_id: str | None = None,
    subject=None,
    session_id: str = SESSION_A,
):
    """Свой полный цикл: заказ рендера с профилем + один проход worker."""
    job, _rendition = delivery().request_rendition(
        snapshot,
        format=fmt,
        org_profile_id=profile.profile_id,
        revision_id=revision_id,
        subject=subject if subject is not None else subject_of(session_id),
        session_id=session_id,
    )
    run_worker_once()
    done = delivery().registry.get_job(job.job_id)
    rendition = (
        delivery().registry.get_rendition(done.rendition_id)
        if done.rendition_id
        else None
    )
    return done, rendition


def seed_document_revision(snapshot):
    """Свой документ+ревизия (держатель WORM-hold'а)."""
    document, revision, _created = delivery().ensure_document_revision(
        snapshot, subject_of(SESSION_A), session_id=SESSION_A
    )
    return document, revision


def cookie(client: TestClient, session_id: str = SESSION_A) -> None:
    from apps.api.session_store import SESSION_COOKIE_NAME

    client.cookies.set(SESSION_COOKIE_NAME, session_id)


def audit_records():
    from apps.api.security_audit import audit_records as impl

    return impl()


def audit_count(action: str) -> int:
    return sum(1 for r in audit_records() if r.get("action") == action)


class BrokenAuditSink:
    """Ломучий sink (паритет repo-паттерна test_doclog3)."""

    def append(self, record):
        raise RuntimeError(f"audit sink down {D9C_SENTINEL}")

    def list_records(self, **kwargs):
        return []
