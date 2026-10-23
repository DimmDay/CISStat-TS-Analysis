# scripts/doclog5cert/conftest.py
"""DOCLOG-5-CERT (независимая сертификация DOCLOG-5 на базе ebbfa87):
фикстуры оракулов на СВОИХ данных.

Корпус сертификатора дизъюнктен repo-корпусу (RUN-D5A*/d5-*), корпусам
DOCLOG-3-CERT (RUN-D3C*) и DOCLOG-4-CERT (RUN-D4C*/d4cert-*):
namespace -- RUN-D5C*, d5cert-*, d5c-cert-*.

Единица данных -- СВЯСТРОЕННЫЙ frozen-снимок (прямая конструкция
ReportSnapshot: полный контроль недоверенного входа -- формулоподобные
тексты, управляющие символы, кириллица, текст 40k символов, честные
gaps). Для API-оракулов снимок дополнительно регистрируется в штатном
SnapshotRegistry (свой ObjectStore в tmp_path) -- worker читает его
системным загрузчиком с проверкой payload_sha256.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# ── Пространство имён сертификатора (дизъюнкт) ───────────────────────

CERT_RUN_ID = "RUN-D5C00001"
CERT_RUN_ID_B = "RUN-D5C00002"
CERT_SESSION = "d5cert-session-a"
CERT_SESSION_B = "d5cert-session-b"
CERT_FOREIGN_SESSION = "d5c-cert-foreign-session"
CERT_TENANT_B = "tenant-d5cert-b"


@pytest.fixture(autouse=True)
def _cert_isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Изоляция КАЖДОГО оракула: свой data-dir, без PG, сброс всех
    singleton-фабрик (паритет repo-паттерна, но СВОЙ tmp_path)."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "d5cert-data"))
    for name in (
        "DATABASE_URL",
        "CISSTAT_RUNS_BACKEND",
        "CISSTAT_IDENTITY_MODE",
        "CISSTAT_API_KEYS",
        "CISSTAT_IDENTITY_SALT",
        "CISSTAT_ARTIFACTS_BACKEND",
        "CISSTAT_SNAPSHOTS_BACKEND",
        "CISSTAT_DOCUMENTS_BACKEND",
        "CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED",
        "CISSTAT_DOCUMENT_RENDER_WORKER_INTERVAL",
        "CISSTAT_DOCUMENT_RENDER_WORKER_BATCH",
        "CISSTAT_DOCUMENT_RENDER_WORKER_PER_TENANT",
        "CISSTAT_DOCUMENT_RENDER_WORKER_RENDER_TIMEOUT",
    ):
        monkeypatch.delenv(name, raising=False)
    _reset_all()
    yield
    _reset_all()


def _reset_all() -> None:
    from apps.api import (
        artifact_store,
        document_jobs,
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


# ── СВОЙ конструктор снимка (полный контроль недоверенного входа) ────

LONG_TEXT = "П" + "о" * 39998 + "н"  # 40000 символов -- усечение Excel

HOSTILE_SECTIONS = [
    {
        "code": "D01",
        "title": "Сводка сертификации",
        "kind": "summary",
        "methodology_stage": "S1",
        "claims": [
            {
                "text": "Кириллическое утверждение: ARIMA(1,0,1) стабильна на окне 24",
                "validity": "supported",
                "evidence_level": "server_result",
                "event_refs": ["evt-d5c-1", "evt-d5c-2"],
                "result_refs": ["res-d5c-1"],
            },
            {
                # формулоподобный текст (XLSX обязан оставить строкой)
                "text": '=1+2; =HYPERLINK("http://evil.example")',
                "validity": "unknown",
                "evidence_level": None,
                "event_refs": [],
                "result_refs": [],
            },
            {
                # управляющие символы (IllegalCharacterError openpyxl)
                "text": "плох\x00ой\x07текст\x0b ok",
                "validity": "supported",
                "evidence_level": "server_result",
                "event_refs": ["evt-d5c-3"],
                "result_refs": [],
            },
        ],
    },
    {
        "code": "D02",
        "title": "Метод <script>alert('svg')</script> сертификации",
        "kind": "methods",
        "methodology_stage": "S2",
        "claims": [
            {
                "text": LONG_TEXT,
                "validity": "supported",
                "evidence_level": "server_result",
                "event_refs": ["evt-d5c-4"],
                "result_refs": ["res-d5c-2"],
            },
        ],
    },
    {
        # пустая секция (честный ноль утверждений)
        "code": "D03",
        "title": "Пустая секция",
        "kind": "results",
        "methodology_stage": None,
        "claims": [],
    },
]


def build_own_snapshot(
    snapshot_id: str = "snap-d5cert-0001",
    run_id: str = "RUN-D5C00001",
) -> object:
    """СВОЙ frozen-снимок: 3 секции, 4 утверждения, кириллица,
    формулоподобный/управляющий/длинный текст, честные gaps."""
    from apps.api.report_snapshot import ReportSnapshot

    return ReportSnapshot(
        snapshot_id=snapshot_id,
        research_run_id=run_id,
        context_id="ctx-d5cert-1",
        data_revision=7,
        source_cutoff={"event_count": 42, "last_sequence": 1042},
        captured_at="2026-10-23T08:00:00+00:00",
        template={"id": "tpl-d5cert", "version": 3},
        knowledge_version="kv-d5cert-1",
        classification="internal",
        redaction_profile="standard",
        completeness={"status": "partial", "missing_refs": ["ref-x-d5c"]},
        reproducibility={
            "status": "limited",
            "reasons": ["данные не включены"],
        },
        sections=json.loads(json.dumps(HOSTILE_SECTIONS)),  # глубокая копия
        dependencies=["dep-d5c-1"],
    )


def register_own_snapshot(snapshot, tmp_path: Path) -> str:
    """Регистрация СВОЕГО снимка в штатном реестре (worker читает
    системным загрузчиком; payload_sha256 -- единый hash §19)."""
    from apps.api.artifact_store import (
        canonical_json_bytes,
        get_artifact_object_store,
    )
    from apps.api.report_snapshot import get_snapshot_registry

    payload = canonical_json_bytes(snapshot.to_dict())
    storage_key = get_artifact_object_store().commit_staged(
        get_artifact_object_store().stage_bytes(
            payload, "application/json"
        )
    )
    snapshot.payload_sha256 = hashlib.sha256(payload).hexdigest()
    snapshot.size_bytes = len(payload)
    snapshot.storage_key = storage_key
    registry = get_snapshot_registry()
    registry.register_snapshot(snapshot, [{"ref": "dep-d5c-1"}])
    return snapshot.payload_sha256


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_cert_run(
    run_id: str = CERT_RUN_ID,
    session_id: str = CERT_SESSION,
    *,
    tenant_id: str | None = None,
) -> None:
    """Свой bound-run (штатная механика ownership DOCLOG-0)."""
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
            dataset_fingerprint="d5c" * 10 + "1",
            dataset_name="d5cert-seed",
            target_column="value",
            target_column_source="user",
            created_at=_now_iso(),
            last_active_at=_now_iso(),
            status="active",
            context_id=f"ctx-{run_id.lower()}",
            data_revision=7,
            owner_subject=SubjectRef.from_session(session_id).subject_id,
            tenant_id=tenant_id or DEFAULT_TENANT_ID,
            ownership="bound",
        )
    )


def cert_subject(session_id: str = CERT_SESSION, tenant_id: str | None = None):
    from apps.api.identity import SubjectRef

    if tenant_id is None:
        return SubjectRef.from_session(session_id)
    return SubjectRef(
        subject_id=f"subject-{session_id}",
        tenant_id=tenant_id,
        via="session_surrogate",
    )


def lease(
    seconds: float,
) -> tuple[str, str]:
    """(claimed_at, lease_expires_at) ISO-пара для сид-джобов."""
    now = datetime.now(timezone.utc)
    return (
        now.isoformat(),
        (now + timedelta(seconds=seconds)).isoformat(),
    )
