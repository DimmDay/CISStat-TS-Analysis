# scripts/doclog8cert/conftest.py
"""DOCLOG-8-CERT (2026-10-24): фикстуры корпуса сертификатора
независимой сертификации DOCLOG-8 «Мониторинг» (D12 «Сверка прогноза
с фактом»).

Методология «оракулы на своих данных, мутанты на своих мутантах»
(прецедент DOCLOG-3/4/5/6/7-CERT). Namespace дизъюнктен repo-корпусам
DOCLOG-0..8 (RUN-D8A*, d8-*, ctx-d8-*, fc-d8-*) и корпусам предыдущих
сертификаторов (d6cert-*, d7c-*, RUN-D7C*): **RUN-D8C*, d8cert-*,
ctx-d8cert-*, fc-d8cert-*, subj-d8cert-***.

СВОИ данные: собственные research runs (bound к своим сессиям),
собственные артефакты прогноза kind="forecast" (штатный
artifact_store: stage/commit/register), собственные actual vintages и
сверки через штатный MonitoringService, свои сессии для cookie-доступа
к /v1/documentation (паритет repo-паттерна DOCLOG-8).

Изоляция каждого теста -- паттерн tests/api/test_doclog8_monitoring.py:
свой tmp_path/CISSTAT_DATA_DIR, сброс singleton-фабрик ВКЛЮЧАЯ monitoring
registry/artifacts/snapshots/session, memory-бекенды (DATABASE_URL
удалён).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ── СВОЙ namespace (дизъюнктен repo и предыдущим сертификаторам) ─────

RUN_A = "RUN-D8CA0001"          # свой run владельца session-a
RUN_B = "RUN-D8CB0002"          # свой второй run (чужой для session-a)
SESSION_A = "d8cert-session-a"  # владелец RUN_A
SESSION_B = "d8cert-session-b"  # владелец RUN_B (для uniform-404)
SESSION_C = "d8cert-session-c"  # третий субъект (посторонний)
CTX_A = "ctx-d8cert-1"
FORECAST_ID_1 = "fc-d8cert-1"
FORECAST_ID_2 = "fc-d8cert-2"
TARGET_NAME = "d8cert_gdp_growth"

D8C_SENTINEL = "d8cert-SENTINEL-секрет-не-попадает-в-ошибки"


def subject_of(session_id: str):
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(session_id)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Изоляция КАЖДОГО теста корпуса сертификатора."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CISSTAT_D8C_SECRET_SENTINEL", D8C_SENTINEL)
    for var in (
        "DATABASE_URL",
        "CISSTAT_RUNS_BACKEND",
        "CISSTAT_IDENTITY_MODE",
        "CISSTAT_IDENTITY_SALT",
        "CISSTAT_ARTIFACTS_BACKEND",
        "CISSTAT_SNAPSHOTS_BACKEND",
        "CISSTAT_MONITORING_BACKEND",
        "CISSTAT_API_KEYS",
    ):
        monkeypatch.delenv(var, raising=False)
    _reset_all()
    yield
    _reset_all()


def _reset_all() -> None:
    from apps.api import artifact_store, monitoring, research_runs
    from apps.api import report_snapshot
    from apps.api.security_audit import reset_audit_for_testing
    from apps.api.session_store import reset_session_store_for_testing

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    monitoring.reset_monitoring_registry_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()


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
    """Свой bound research run (паритет repo-паттерна DOCLOG-8)."""
    from apps.api.identity import DEFAULT_TENANT_ID
    from apps.api.research_runs import ResearchRun, get_research_run_store

    seed_session(session_id)
    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="d8c" + "0" * 29,
        dataset_name="d8cert-seed",
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
):
    chosen = points if points is not None else FORECAST_POINTS
    return make_artifact(
        "forecast",
        f"forecast:{forecast_id}",
        {
            "forecast_id": forecast_id,
            "model_card_id": "card-d8cert-1",
            "generated_at": now_iso(),
            "horizon": len(chosen),
            "alpha": 0.05,
            "points": chosen,
        },
        run_id=run_id,
    )


def service():
    from apps.api.monitoring import MonitoringService

    return MonitoringService.create_default()


def register_batch(
    run_id: str = RUN_A,
    *,
    subject=None,
    periods: list[tuple[str, float]] | None = None,
    target_name: str = TARGET_NAME,
    entity_id=None,
    units: str = "percent",
    as_of: str = "2026-12-01T00:00:00+00:00",
    source_kind: str = "manual",
    source_ref=None,
    notes: str = "",
    idempotency_key: str = "",
):
    values = [
        {"period": period, "value": value}
        for period, value in (
            periods or [("2026-09-01", 4.8), ("2026-10-01", 6.1)]
        )
    ]
    batch, _created = service().register_actual_batch(
        run_id,
        subject if subject is not None else subject_of(SESSION_A),
        target_name=target_name,
        entity_id=entity_id,
        units=units,
        as_of=as_of,
        values=values,
        source_kind=source_kind,
        source_ref=source_ref,
        notes=notes,
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
    record, _created = service().build_comparison(
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


def audit_records():
    from apps.api.security_audit import audit_records as impl

    return impl()


def audit_count(action: str) -> int:
    return sum(1 for r in audit_records() if r.get("action") == action)
