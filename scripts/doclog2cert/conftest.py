# scripts/doclog2cert/conftest.py
# DOCLOG-2-CERT: оракулы сертификатора на СВОИХ данных.
# Корпус ДИЗЪЮНКТЕН repo-корпусу (tests/api/test_doclog2_snapshots.py:
# RUN-D2A*, d2-seed-session, d2-admin-test-key) и корпусам прошлых
# сертификаций (D0C*, D1C*): RUN-D2C*, d2cert-*, d2c-cert-admin-key-91.
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ── Корпус сертификатора (свои данные, дизъюнктные repo) ────────────

RUN_ID = "RUN-D2C00001"              # основной запуск корпуса
RUN_ID_B = "RUN-D2C00002"            # второй запуск (scope-тесты)
RUN_ID_LEGACY = "RUN-D2C00003"       # unresolved legacy
RUN_FOREIGN = "RUN-D2C00009"         # запуск чужой сессии
RUN_MISSING = "RUN-D2C00404"         # несуществующий (uniform-отказ)

SESSION_ID = "d2cert-alpha-session"
SESSION_B = "d2cert-beta-session"
SESSION_FOREIGN = "d2cert-omega-session"

ADMIN_KEY = "d2c-cert-admin-key-91"
CTX_ALPHA = "ctx-d2c-alpha"
CTX_BETA = "ctx-d2c-beta"
REV_ALPHA = 4
FP = "d2c" * 16                       # dataset_fingerprint корпуса

UNIFORM_DENIAL_TEXT = "Снимок недоступен"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def orc_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Изоляция контура сертификатора: свой data-root, чистые фабрики."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "d2c-data"))
    for var in (
        "DATABASE_URL", "CISSTAT_RUNS_BACKEND", "CISSTAT_IDENTITY_MODE",
        "CISSTAT_API_KEYS", "CISSTAT_IDENTITY_SALT",
        "CISSTAT_ARTIFACTS_BACKEND", "CISSTAT_SNAPSHOTS_BACKEND",
        "CISSTAT_STORAGE_MODE",
    ):
        monkeypatch.delenv(var, raising=False)
    from apps.api import artifact_store, report_snapshot, research_runs
    from apps.api.session_store import reset_session_store_for_testing

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    reset_session_store_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    reset_session_store_for_testing()


# ── Сид-хелперы корпуса (собственные, на своих данных) ──────────────


def seed_session(session_id: str = SESSION_ID, *, target: str | None = "revenue"):
    from apps.api.identity import SubjectRef
    from apps.api.session_store import AnalysisSession, get_session_store

    store = get_session_store()
    existing = store.get(session_id)
    if existing is not None:
        return existing
    session = AnalysisSession(session_id=session_id)
    session.owner_subject = SubjectRef.from_session(session_id).subject_id
    from apps.api.identity import DEFAULT_TENANT_ID

    session.tenant_id = DEFAULT_TENANT_ID
    session.target_column = target
    session.date_column = "dt"
    store.save(session)
    return session


def seed_bound_run(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    context_id: str | None = CTX_ALPHA,
    data_revision: int | None = REV_ALPHA,
    target: str | None = "revenue",
):
    from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
    from apps.api.research_runs import ResearchRun, get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint=FP,
        dataset_name="d2cert-corpus",
        target_column=target,
        target_column_source="user",
        created_at=_now_iso(),
        last_active_at=_now_iso(),
        status="active",
        context_id=context_id,
        data_revision=data_revision,
        owner_subject=SubjectRef.from_session(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)
    return run


def owner_subject(session_id: str = SESSION_ID):
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(session_id)


def foreign_subject():
    return owner_subject(SESSION_FOREIGN)


def admin_subject():
    from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef

    return SubjectRef(
        subject_id="subj-d2c-cert-admin",
        tenant_id=DEFAULT_TENANT_ID,
        via="api_key",
        role="admin",
    )


def append_event(
    run_id: str = RUN_ID,
    event_type: str = "upload_completed",
    stage: str = "upload",
    *,
    node_id: str | None = None,
    payload: dict | None = None,
    evidence_level: str | None = "server_result",
    result_ref: dict | None = None,
    context_id: str | None = None,
    sequence: int | None = None,
):
    """Событие корпуса: sequence задаётся явно ТОЛЬКО когда нужен
    частичный корпус (legacy-сценарии) -- честный контроль корпуса."""
    from apps.api.research_runs import get_research_run_store
    from apps.api.trace_events import TraceEvent

    event = TraceEvent(
        event_type=event_type,
        payload=dict(payload or {}),
        run_id=run_id,
        stage=stage,
        node_id=node_id,
        schema_version=2,
        evidence_level=evidence_level,
        result_ref=result_ref,
        context_id=context_id,
    )
    stored = get_research_run_store().append_event(run_id, event)
    return stored if stored is not None else event


def make_artifact(
    kind: str,
    producer_key: str,
    payload,
    *,
    run_id: str = RUN_ID,
    context_id: str | None = None,
    data_revision: int | None = None,
    input_kind: str | None = None,
    panel: dict | None = None,
    dependencies: list[str] | None = None,
    refs: dict | None = None,
    media_type: str = "application/json",
):
    """Артефакт корпуса через реальный staging→commit протокол."""
    from apps.api.artifact_store import (
        ResultArtifact,
        artifact_content_sha256,
        canonical_json_bytes,
        data_digest as compute_data_digest,
        get_artifact_object_store,
        get_artifact_registry,
        new_artifact_id,
    )

    if media_type == "application/json":
        content = canonical_json_bytes(payload)
        digest_value = None
    else:
        content = payload
        digest_value = compute_data_digest(content)
    objects = get_artifact_object_store()
    staged = objects.stage_bytes(content, media_type)
    storage_key = objects.commit_staged(staged)
    artifact = ResultArtifact(
        artifact_id=new_artifact_id(),
        run_id=run_id,
        kind=kind,
        producer_key=producer_key,
        media_type=media_type,
        size_bytes=len(content),
        payload_sha256=artifact_content_sha256(content),
        data_digest=digest_value,
        storage_key=storage_key,
        context_id=context_id,
        data_revision=data_revision,
        input_kind=input_kind,
        panel=panel,
        dependencies=list(dependencies or []),
        refs=dict(refs or {}),
    )
    stored, _created = get_artifact_registry().register_artifact(artifact)
    return stored


def service():
    from apps.api.snapshot_builder import SnapshotService

    return SnapshotService.create_default()


def section(snapshot, code: str) -> dict:
    for item in snapshot.sections:
        if item.get("code") == code:
            return item
    raise AssertionError(f"Секция {code} отсутствует")
