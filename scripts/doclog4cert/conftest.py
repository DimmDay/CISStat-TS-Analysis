# scripts/doclog4cert/conftest.py
# DOCLOG-4-CERT: оракулы сертификатора на СВОИХ данных.
# Корпус ДИЗЪЮНКТЕН repo-корпусу (tests/api/test_doclog4_document_delivery.py:
# RUN-D4A*, d4-seed-session, d4-admin-test-key) и корпусам прошлых
# сертификаций (D0C*/D1C*/D2C*/D3C*): RUN-D4C*, d4cert-*, d4c-cert-admin-key-04.
# Методология: оракулы на своих данных; RED-оракулы находок F-D4C2/F-D4C3
# кодируют ПРАВИЛЬНОЕ поведение по спеке (§14.1/AC11) и обязаны падать
# на дереве с дефектом.
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── Корпус сертификатора (свои данные, дизъюнктные repo) ────────────

RUN_ID = "RUN-D4C00001"              # основной запуск корпуса
RUN_ID_B = "RUN-D4C00002"            # второй запуск (context-фильтр)
RUN_FOREIGN = "RUN-D4C00009"         # чужой запуск (не используется владельцем)
RUN_MISSING = "RUN-D4C00404"         # несуществующий (uniform-отказ)

SESSION_ID = "d4cert-alpha-session"
SESSION_B = "d4cert-beta-session"
SESSION_FOREIGN = "d4cert-omega-session"

ADMIN_KEY = "d4c-cert-admin-key-04"
CTX_ALPHA = "ctx-d4c-alpha"
CTX_BETA = "ctx-d4c-beta"
REV_ALPHA = 7
FP = "d4c" * 16                       # dataset_fingerprint корпуса

# Сентинелы недоверенного контента (свои, не из repo-корпуса).
SENTINEL_SCRIPT = '<script>d4c-xss-77</script>'
SENTINEL_IMG_ONERROR = '<img src=x onerror="d4c-alert-77">'
SENTINEL_JS_SCHEME = 'javascript:d4c-scheme-77'
SENTINEL_PLAIN = "Утверждение корпуса D4C с <тегом> и \"кавычками\""

UNIFORM_RUN_DETAIL = "Запуск не найден"
UNIFORM_DOC_DETAIL = "Документ не найден"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def orc_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Изоляция контура сертификатора: свой data-root, чистые фабрики."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "d4c-data"))
    for var in (
        "DATABASE_URL", "CISSTAT_RUNS_BACKEND", "CISSTAT_IDENTITY_MODE",
        "CISSTAT_API_KEYS", "CISSTAT_IDENTITY_SALT",
        "CISSTAT_ARTIFACTS_BACKEND", "CISSTAT_SNAPSHOTS_BACKEND",
        "CISSTAT_DOCUMENTS_BACKEND", "CISSTAT_STORAGE_MODE",
    ):
        monkeypatch.delenv(var, raising=False)
    from apps.api import artifact_store, report_snapshot, research_runs
    from apps.api import document_jobs
    from apps.api.routers import documentation as documentation_router
    from apps.api.session_store import reset_session_store_for_testing
    from apps.api.security_audit import reset_audit_for_testing
    from apps.api.telemetry import reset_telemetry_for_testing

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()


@pytest.fixture()
def orc_client(orc_env):
    from fastapi.testclient import TestClient

    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def orc_admin_client(orc_client, monkeypatch):
    monkeypatch.setenv("CISSTAT_API_KEYS", f"{ADMIN_KEY}:admin:pro")
    return orc_client


# ── Сид-хелперы корпуса ─────────────────────────────────────────────


def owner_subject(session_id: str = SESSION_ID):
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(session_id)


def foreign_subject():
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(SESSION_FOREIGN)


def seed_session(session_id: str = SESSION_ID):
    from apps.api.identity import DEFAULT_TENANT_ID
    from apps.api.session_store import AnalysisSession, get_session_store

    store = get_session_store()
    session = store.get(session_id)
    if session is not None:
        return session
    session = AnalysisSession(session_id=session_id)
    session.owner_subject = owner_subject(session_id).subject_id
    session.tenant_id = DEFAULT_TENANT_ID
    session.target_column = "value"
    session.date_column = "date"
    store.save(session)
    return session


def seed_bound_run(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    context_id: str | None = CTX_ALPHA,
    data_revision: int | None = REV_ALPHA,
):
    from apps.api.identity import DEFAULT_TENANT_ID
    from apps.api.research_runs import ResearchRun, get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint=FP,
        dataset_name="doclog4cert-seed",
        target_column="value",
        target_column_source="user",
        created_at=_now_iso(),
        last_active_at=_now_iso(),
        status="active",
        context_id=context_id,
        data_revision=data_revision,
        owner_subject=owner_subject(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)
    return run


def append_event(
    run_id: str = RUN_ID,
    event_type: str = "upload_completed",
    stage: str = "upload",
    *,
    payload: dict | None = None,
    evidence_level: str | None = "server_result",
):
    from apps.api import research_runs
    from apps.api.trace_events import TraceEvent

    event = TraceEvent(
        event_type=event_type,
        payload=dict(payload or {"dataset": "doclog4cert-seed"}),
        run_id=run_id,
        stage=stage,
        schema_version=2,
        evidence_level=evidence_level,
    )
    research_runs.get_research_run_store().append_event(run_id, event)
    return event


def snapshot_service():
    from apps.api.snapshot_builder import SnapshotService

    return SnapshotService.create_default()


def seed_snapshot(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    kinds: list[str] | None = None,
    claim_text: str | None = None,
    context_id: str | None = CTX_ALPHA,
):
    """Frozen-снимок через штатный сборщик DOCLOG-2; при claim_text --
    подмена текста ТОЛЬКО в памяти (рендеры получают недоверенный вход)."""
    seed_session(session_id)
    seed_bound_run(run_id, session_id, context_id=context_id)
    append_event(run_id)
    snapshot, _created = snapshot_service().build_snapshot(
        run_id,
        owner_subject(session_id),
        session_id=session_id,
        kinds=kinds or ["D01", "D02"],
    )
    if claim_text is not None:
        import dataclasses

        sections = [dict(section) for section in snapshot.sections]
        if sections:
            sections[0] = dict(sections[0])
            sections[0]["claims"] = [
                dict(sections[0]["claims"][0]) | {"text": claim_text},
                *[dict(claim) for claim in sections[0]["claims"][1:]],
            ]
        snapshot = dataclasses.replace(snapshot, sections=sections)
    return snapshot


def cookie_for(client, session_id: str = SESSION_ID):
    """Ставит cookie-сессию владельца/чужого на TestClient."""
    from apps.api.session_store import SESSION_COOKIE_NAME

    seed_session(session_id)
    client.cookies.set(SESSION_COOKIE_NAME, session_id)
    return client


def audit_records():
    from apps.api.security_audit import get_audit_sink

    return get_audit_sink().list_recent(limit=1000)


def science_state(run_id: str = RUN_ID) -> dict:
    """Независимый фингерпринт научного состояния корпуса (AC05)."""
    from apps.api import artifact_store, report_snapshot, research_runs

    run_store = research_runs.get_research_run_store()
    run = run_store.get_run(run_id)
    events = run_store.list_events(run_id)
    pins = artifact_store.get_artifact_registry().list_pins(run_id)
    return {
        "run": run.to_dict() if run is not None else None,
        "event_ids": [event.event_id for event in events],
        "event_types": [event.event_type for event in events],
        "snapshots": [
            record.snapshot_id
            for record in report_snapshot.get_snapshot_registry().list_records(run_id)
        ],
        "pins": sorted((p.ref_kind, p.ref_id) for p in pins),
    }
