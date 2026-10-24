# tests/api/test_doclog6_approvals_archive.py
"""Task DOCLOG-6 (spec_documentation_logging.md §11, §14.1, §15, §16,
§17, §19 строка DOCLOG-6, §20 AC04-дух/AC05/AC06/AC07/AC11/AC17/AC18):
согласование и архив.

Критерии завершения (§19): approval bound hash, разделение прав,
deletion/hold и restore drill.

Оракулы на СВОИХ данных: корпус дизъюнктен repo-корпусу и корпусам
0/1/2/3/4/5 (RUN-D6xxxxxx, d6-*); изоляция каждого теста -- паттерн
test_doclog5_formats_worker.py (свой tmp_path/CISSTAT_DATA_DIR, сброс
singleton-фабрик). Согласование связывает ТОЧНУЮ ревизию + snapshot
payload hash + renditions manifest (AC07); publish перепроверяет хэши
и требует права/documentation.publish; два лица -- по выбранной policy
(§11: права reviewer НЕ возникают автоматически у ADMIN). Approve/
publish/retract -- mandatory audit fail-closed (§14.1/AC11). Retention
-- независимо от checkpoint keeper'а (§16.1): hold приоритетен,
published не очищается, purged -- честный tombstone с 410 владельцу.
Archive/restore drill: manifest без self-hash (§13.3), missing/
mismatched НЕ маскируются (AC18). Diff -- по замороженным данным,
без пересчётов (§17).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api import research_runs
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
from apps.api.research_runs import ResearchRun
from apps.api.session_store import AnalysisSession

# ── Изоляция КАЖДОГО теста (паттерн test_doclog5_formats_worker.py) ───


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_SALT", raising=False)
    monkeypatch.delenv("CISSTAT_ARTIFACTS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_SNAPSHOTS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_DOCUMENTS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_DOCLOG_APPROVAL_POLICY", raising=False)
    monkeypatch.delenv("CISSTAT_DOCUMENT_RETENTION_DRAFT_DAYS", raising=False)
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    from apps.api import artifact_store, report_snapshot, document_jobs
    from apps.api import document_lifecycle, document_render_worker
    from apps.api.routers import documentation as documentation_router
    from apps.api.session_store import reset_session_store_for_testing
    from apps.api.security_audit import reset_audit_for_testing
    from apps.api.telemetry import reset_telemetry_for_testing

    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    document_lifecycle.reset_document_lifecycle_registry_for_testing()
    document_render_worker.reset_document_render_worker_for_testing()
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
    document_lifecycle.reset_document_lifecycle_registry_for_testing()
    document_render_worker.reset_document_render_worker_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()


@pytest.fixture()
def client():
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


# ── Сид-хелперы: run/сессия/subject на СВОИХ данных ──────────────────

RUN_ID = "RUN-D6A00001"
SESSION_ID = "d6-seed-session"
FOREIGN_SESSION_ID = "d6-foreign-session"
ADMIN_KEY = "d6-admin-key-7f31"
REVIEWER_KEY = "d6-reviewer-key-42ab"  # documentation.approve, свой субъект

RUNS = "RUN-D6A00001"
RUNS_TWO = "RUN-D6B00002"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_session(session_id: str = SESSION_ID) -> AnalysisSession:
    from apps.api.session_store import get_session_store

    store = get_session_store()
    session = store.get(session_id)
    if session is not None:
        return session
    session = AnalysisSession(session_id=session_id)
    session.owner_subject = SubjectRef.from_session(session_id).subject_id
    session.tenant_id = DEFAULT_TENANT_ID
    session.target_column = "value"
    session.date_column = "date"
    store.save(session)
    return session


def _seed_bound_run(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    context_id: str | None = "ctx-d6-1",
    data_revision: int | None = 2,
) -> ResearchRun:
    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="d6" * 16,
        dataset_name="doclog6-seed",
        target_column="value",
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


def _seed_event(
    run_id: str = RUN_ID,
    event_type: str = "upload_completed",
    stage: str = "upload",
    *,
    payload: dict | None = None,
    evidence_level: str = "server_result",
) -> None:
    from apps.api.trace_events import TraceEvent

    event = TraceEvent(
        event_type=event_type,
        payload=dict(payload or {}),
        run_id=run_id,
        stage=stage,
        schema_version=2,
        evidence_level=evidence_level,
    )
    research_runs.get_research_run_store().append_event(run_id, event)


def _owner_subject(session_id: str = SESSION_ID) -> SubjectRef:
    return SubjectRef.from_session(session_id)


def _service():
    from apps.api.snapshot_builder import SnapshotService

    return SnapshotService.create_default()


def _seed_run(run_id: str = RUN_ID, session_id: str = SESSION_ID) -> None:
    _seed_session(session_id)
    _seed_bound_run(run_id, session_id)
    _seed_event(run_id, payload={"dataset": "doclog6-seed"})


def _seed_snapshot(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    kinds: list[str] | None = None,
    user_decision_event: bool = False,
    dangling_artifact_ref: bool = False,
):
    """Frozen-снимок штатным сборщиком DOCLOG-2. Опции:
    user_decision_event -- событие с evidence_level=user_decision (для
    D10); dangling_artifact_ref -- событие с несуществующим result_ref
    (честный partial для publish-policy D11)."""
    _seed_run(run_id, session_id)
    if user_decision_event:
        _seed_event(
            run_id,
            event_type="model_selected",
            stage="modeling",
            payload={"model_id": "prophet"},
            evidence_level="user_decision",
        )
    if dangling_artifact_ref:
        # Dangling result_ref на upload-событии: D02/D11 ссылаются на
        # него _event_claim'ом -> честный missing_ref -> partial (AC01).
        from apps.api.trace_events import TraceEvent

        store = research_runs.get_research_run_store()
        event = TraceEvent(
            event_type="upload_completed",
            payload={"dataset": "d6-dangling"},
            run_id=run_id,
            stage="upload",
            schema_version=2,
            evidence_level="server_result",
            result_ref={"artifact_id": "art-d6-nonexistent-0001"},
        )
        store.append_event(run_id, event)
    subject = _owner_subject(session_id)
    snapshot, _created = _service().build_snapshot(
        run_id, subject, session_id=session_id, kinds=kinds or ["D01", "D02"]
    )
    return snapshot


def _seed_revision(
    snapshot=None,
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    kind_code: str = "D02",
):
    """Документ+ревизия поверх снимка (адаптер DOCLOG-4)."""
    if snapshot is None:
        snapshot = _seed_snapshot(run_id=run_id, session_id=session_id, kinds=[kind_code])
    from apps.api.document_jobs import DocumentDeliveryService

    service = DocumentDeliveryService.create_default()
    document, revision, _created = service.ensure_document_revision(
        snapshot,
        _owner_subject(session_id),
        session_id=session_id,
        kind_code=kind_code,
    )
    return document, revision


def _delivery():
    from apps.api.document_jobs import DocumentDeliveryService

    return DocumentDeliveryService.create_default()


def _lifecycle():
    from apps.api.document_lifecycle import DocumentLifecycleService

    return DocumentLifecycleService.create_default()


def _cookie(client: TestClient, session_id: str = SESSION_ID) -> None:
    from apps.api.session_store import SESSION_COOKIE_NAME

    client.cookies.set(SESSION_COOKIE_NAME, session_id)


def _api_key(client: TestClient, key: str) -> None:
    client.headers["x-api-key"] = key


def _approval_route(revision_id: str) -> str:
    return f"/v1/documentation/revisions/{revision_id}/approvals"


def _publish_flow(
    client: TestClient,
    document,
    revision,
    *,
    session_id: str = SESSION_ID,
    expect_status: int = 200,
):
    """Полный поток: запрос согласования -> approve -> publish."""
    _cookie(client, session_id)
    r1 = client.post(_approval_route(revision.revision_id), json={"action": "request"})
    assert r1.status_code == 200, r1.text
    r2 = client.post(
        _approval_route(revision.revision_id),
        json={"decision": "approve", "reason": "d6-test"},
    )
    assert r2.status_code == 200, r2.text
    r3 = client.post(f"/v1/documentation/revisions/{revision.revision_id}/publish")
    assert r3.status_code == expect_status, r3.text
    return r3


# ══════════════════════════════════════════════════════════════════════
# 1. Каталог видов D10/D11 (§6/§19; D1)
# ══════════════════════════════════════════════════════════════════════


class TestKindCatalogD10D11:
    def test_catalog_contains_d10_d11(self):
        from apps.api.report_snapshot import DOCUMENT_KINDS

        assert "D10" in DOCUMENT_KINDS
        assert "D11" in DOCUMENT_KINDS
        assert DOCUMENT_KINDS["D10"][0] == "recommendations_limits"
        assert DOCUMENT_KINDS["D11"][0] == "final_report"
        assert DOCUMENT_KINDS["D10"][1] == "Рекомендации и ограничения"
        assert DOCUMENT_KINDS["D11"][1] == "Итоговый отчёт"

    def test_resolve_kinds_accepts_d10_d11(self):
        from apps.api.report_snapshot import resolve_kinds

        assert resolve_kinds(["D10", "recommendations_limits"]) == ["D10"]
        assert resolve_kinds(["D11"]) == ["D11"]

    def test_unknown_kind_still_rejected(self):
        from apps.api.report_snapshot import resolve_kinds

        with pytest.raises(ValueError):
            resolve_kinds(["D99"])

    def test_build_snapshot_d10_honest_claims(self):
        snapshot = _seed_snapshot(kinds=["D10"], user_decision_event=True)
        codes = [section["code"] for section in snapshot.sections]
        assert codes == ["D10"]
        claims = snapshot.sections[0]["claims"]
        # Факт решения аналитика из ledger -- с event_ref (refs честны).
        decision_claims = [
            claim
            for claim in claims
            if claim["text"].startswith("Решение аналитика:")
            and claim.get("event_refs")
        ]
        assert decision_claims, "решение аналитика должно попасть в D10 с ref"
        # Честное not_computed для редактируемого текста (R03).
        assert any("not_computed" in claim["text"] for claim in claims)

    def test_build_snapshot_d10_without_decisions_is_honest(self):
        snapshot = _seed_snapshot(kinds=["D10"])
        claims = snapshot.sections[0]["claims"]
        assert claims, "пустая секция не честна -- нужен not_computed-claim"
        assert all(
            claim["evidence_level"] in (None, "user_decision") for claim in claims
        )
        assert any("not_computed" in claim["text"] for claim in claims)

    def test_build_snapshot_d11_summary(self):
        snapshot = _seed_snapshot(kinds=["D11"])
        codes = [section["code"] for section in snapshot.sections]
        assert codes == ["D11"]
        claims = snapshot.sections[0]["claims"]
        assert claims
        # Честная сводка: cutoff/состояние запуска.
        joined = " ".join(claim["text"] for claim in claims)
        assert "cutoff" in joined.lower()


# ══════════════════════════════════════════════════════════════════════
# 2. Полный поток согласования и публикация (§11; D3/D5)
# ══════════════════════════════════════════════════════════════════════


class TestApprovalFlow:
    def test_full_flow_request_approve_publish(self, client):
        snapshot = _seed_snapshot(kinds=["D02"])
        document, revision = _seed_revision(snapshot)
        _cookie(client)

        resp = client.get(f"/v1/documentation/revisions/{revision.revision_id}")
        assert resp.status_code == 200
        # Начальное состояние -- draft (аддитивное поле lifecycle_state).
        assert resp.json()["revision"]["lifecycle_state"] == "draft"

        resp = client.post(_approval_route(revision.revision_id), json={"action": "request"})
        assert resp.status_code == 200
        assert resp.json()["revision"]["lifecycle_state"] == "ready_for_review"

        resp = client.post(
            _approval_route(revision.revision_id),
            json={"decision": "approve", "reason": "методология проверена"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["revision"]["lifecycle_state"] == "approved"
        approval = body["approval"]
        assert approval["decision"] == "approve"
        # AC07: approval связан точным revision_id и snapshot hash.
        assert approval["revision_id"] == revision.revision_id
        assert approval["snapshot_payload_sha256"] == snapshot.payload_sha256

        resp = client.post(f"/v1/documentation/revisions/{revision.revision_id}/publish")
        assert resp.status_code == 200
        body = resp.json()
        assert body["revision"]["lifecycle_state"] == "published"
        # Publish пинирует снимок (§16/AC04-дух: deletion-защита).
        from apps.api.artifact_store import get_artifact_registry

        pins = get_artifact_registry().list_pins(RUN_ID)
        pin_reasons = [pin.reason for pin in pins]
        assert any(
            f"document:{document.document_id}:published:" in reason
            for reason in pin_reasons
        ), pin_reasons

    def test_approve_without_request_is_honest_422(self, client):
        _document, revision = _seed_revision()
        _cookie(client)
        resp = client.post(
            _approval_route(revision.revision_id),
            json={"decision": "approve", "reason": "сразу"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "invalid_transition"

    def test_reject_returns_revision_to_rejected_state(self, client):
        _document, revision = _seed_revision()
        _cookie(client)
        client.post(_approval_route(revision.revision_id), json={"action": "request"})
        resp = client.post(
            _approval_route(revision.revision_id),
            json={"decision": "reject", "reason": "нужны доп. проверки"},
        )
        assert resp.status_code == 200
        assert resp.json()["revision"]["lifecycle_state"] == "rejected"
        # Отклонение -- конец для ревизии; повторный approve -- 422.
        resp = client.post(
            _approval_route(revision.revision_id),
            json={"decision": "approve"},
        )
        assert resp.status_code == 422

    def test_publish_without_approval_422(self, client):
        _document, revision = _seed_revision()
        _cookie(client)
        resp = client.post(f"/v1/documentation/revisions/{revision.revision_id}/publish")
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "publish_requires_approval"

    def test_repeat_publish_422(self, client):
        snapshot = _seed_snapshot(kinds=["D02"])
        document, revision = _seed_revision(snapshot)
        _publish_flow(client, document, revision)
        _cookie(client)
        resp = client.post(f"/v1/documentation/revisions/{revision.revision_id}/publish")
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "invalid_transition"

    def test_lifecycle_history_append_only(self, client):
        snapshot = _seed_snapshot(kinds=["D02"])
        document, revision = _seed_revision(snapshot)
        _publish_flow(client, document, revision)
        _cookie(client)
        resp = client.get(
            f"/v1/documentation/revisions/{revision.revision_id}/lifecycle"
        )
        assert resp.status_code == 200
        events = [record["event"] for record in resp.json()["records"]]
        assert events == [
            "approval_requested",
            "approved",
            "published",
        ]
        # Append-only: записи несут время и субъекта (§9.1).
        for record in resp.json()["records"]:
            assert record["created_at"]
            assert record["actor_subject"]


# ══════════════════════════════════════════════════════════════════════
# 3. Approval bound hash (AC07; D4)
# ══════════════════════════════════════════════════════════════════════


class TestApprovalBoundHash:
    def test_approval_binds_renditions_manifest(self, client):
        snapshot = _seed_snapshot(kinds=["D02"])
        document, revision = _seed_revision(snapshot)
        _cookie(client)
        # Готовая rendition до согласования -- попадает в manifest.
        resp = client.post(
            f"/v1/documentation/revisions/{revision.revision_id}/renditions",
            json={"format": "md"},
        )
        assert resp.status_code == 202
        resp = client.post(_approval_route(revision.revision_id), json={"action": "request"})
        resp = client.post(
            _approval_route(revision.revision_id),
            json={"decision": "approve", "reason": "ok"},
        )
        assert resp.status_code == 200
        manifest = resp.json()["approval"]["approval_manifest"]
        assert len(manifest) == 1
        assert manifest[0]["format"] == "md"
        assert manifest[0]["content_sha256"]
        assert manifest[0]["rendition_id"]

    def test_expected_snapshot_hash_mismatch_409(self, client):
        _document, revision = _seed_revision()
        _cookie(client)
        client.post(_approval_route(revision.revision_id), json={"action": "request"})
        resp = client.post(
            _approval_route(revision.revision_id),
            json={
                "decision": "approve",
                "expected_snapshot_sha256": "0" * 64,
            },
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "approval_hash_mismatch"

    def test_publish_fails_when_rendition_changed_after_approval(self, client):
        from apps.api.document_jobs import replace_dataclass

        snapshot = _seed_snapshot(kinds=["D02"])
        document, revision = _seed_revision(snapshot)
        _cookie(client)
        client.post(
            f"/v1/documentation/revisions/{revision.revision_id}/renditions",
            json={"format": "md"},
        )
        client.post(_approval_route(revision.revision_id), json={"action": "request"})
        client.post(
            _approval_route(revision.revision_id),
            json={"decision": "approve", "reason": "ok"},
        )
        # Подмена content_sha256 готовой rendition (симуляция смены
        # утверждённой визуальной формы -- «старое approval не
        # переносится на новый hash», §11).
        registry = _delivery().registry
        renditions = registry.list_renditions(snapshot.snapshot_id)
        mutated = replace_dataclass(
            renditions[0], content_sha256="f" * 64
        )
        registry.update_rendition(mutated)
        resp = client.post(f"/v1/documentation/revisions/{revision.revision_id}/publish")
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "approval_not_applicable"
        # Состояние НЕ изменилось (publish не выполнен).
        resp = client.get(f"/v1/documentation/revisions/{revision.revision_id}")
        assert resp.json()["revision"]["lifecycle_state"] == "approved"

    def test_approval_does_not_transfer_to_other_revision(self, client):
        # Согласование ревизии 1 не переносится на ревизию 2 того же
        # документа (AC07: «approval точной ревизии не переносится»).
        snapshot1 = _seed_snapshot(kinds=["D02"])
        document, revision1 = _seed_revision(snapshot1)
        _cookie(client)
        _publish_flow(client, document, revision1)
        # Новая заморозка состояния -> новая ревизия того же документа.
        _seed_event(RUN_ID, event_type="mode_changed", payload={"mode": "eda"})
        snapshot2 = _seed_snapshot(kinds=["D02"])
        _document, revision2 = _seed_revision(snapshot2)
        assert revision2.revision_id != revision1.revision_id
        # Ревизия 2 -- draft, у неё НЕТ своего approval.
        resp = client.get(f"/v1/documentation/revisions/{revision2.revision_id}")
        assert resp.json()["revision"]["lifecycle_state"] == "draft"
        resp = client.post(
            f"/v1/documentation/revisions/{revision2.revision_id}/publish"
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# 4. Разделение прав (§15; D5) и policy двух лиц (§11; D6)
# ══════════════════════════════════════════════════════════════════════


class TestRightsSeparation:
    def test_anonymous_404(self, client):
        _document, revision = _seed_revision()
        resp = client.post(_approval_route(revision.revision_id), json={"action": "request"})
        assert resp.status_code == 404

    def test_foreign_session_uniform_404_on_all_routes(self, client):
        snapshot = _seed_snapshot(kinds=["D02"])
        document, revision = _seed_revision(snapshot)
        _cookie(client)
        _publish_flow(client, document, revision)
        _seed_session(FOREIGN_SESSION_ID)
        _cookie(client, FOREIGN_SESSION_ID)
        for method, url in (
            ("post", _approval_route(revision.revision_id)),
            ("post", f"/v1/documentation/revisions/{revision.revision_id}/publish"),
            ("post", f"/v1/documentation/revisions/{revision.revision_id}/retract"),
            ("get", f"/v1/documentation/revisions/{revision.revision_id}/lifecycle"),
            ("post", f"/v1/documentation/documents/{document.document_id}/retention"),
            ("post", f"/v1/documentation/runs/{RUN_ID}/retention/sweep"),
            ("post", f"/v1/documentation/runs/{RUN_ID}/archive"),
        ):
            if method == "post":
                resp = client.post(url, json={})
            else:
                resp = client.get(url)
            assert resp.status_code == 404, url

    def test_scoped_mode_session_surrogate_has_no_rights(self, client, monkeypatch):
        monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "scoped")
        _document, revision = _seed_revision()
        _cookie(client)
        resp = client.post(_approval_route(revision.revision_id), json={"action": "request"})
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "insufficient_scope"

    def test_admin_key_has_full_catalog(self, client, monkeypatch):
        monkeypatch.setenv(
            "CISSTAT_API_KEYS",
            f"{ADMIN_KEY}:admin:demo:d6-admin-subj:{DEFAULT_TENANT_ID}",
        )
        _document, revision = _seed_revision()
        _cookie(client)  # владелец запрашивает согласование
        client.post(_approval_route(revision.revision_id), json={"action": "request"})
        _api_key(client, ADMIN_KEY)
        resp = client.post(
            _approval_route(revision.revision_id),
            json={"decision": "approve", "reason": "админ-согласование"},
        )
        assert resp.status_code == 200
        assert resp.json()["revision"]["lifecycle_state"] == "approved"


class TestTwoPersonPolicy:
    def test_self_approval_forbidden_under_two_person(self, client, monkeypatch):
        monkeypatch.setenv("CISSTAT_DOCLOG_APPROVAL_POLICY", "two_person")
        _document, revision = _seed_revision()
        _cookie(client)
        client.post(_approval_route(revision.revision_id), json={"action": "request"})
        resp = client.post(
            _approval_route(revision.revision_id),
            json={"decision": "approve", "reason": "сам себя"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "self_approval_forbidden"
        # Состояние не изменилось.
        resp = client.get(f"/v1/documentation/revisions/{revision.revision_id}")
        assert resp.json()["revision"]["lifecycle_state"] == "ready_for_review"

    def test_second_person_admin_can_approve(self, client, monkeypatch):
        monkeypatch.setenv("CISSTAT_DOCLOG_APPROVAL_POLICY", "two_person")
        monkeypatch.setenv(
            "CISSTAT_API_KEYS",
            f"{ADMIN_KEY}:admin:demo:d6-admin-subj:{DEFAULT_TENANT_ID}",
        )
        _document, revision = _seed_revision()
        _cookie(client)  # владелец создаёт/запрашивает
        client.post(_approval_route(revision.revision_id), json={"action": "request"})
        _api_key(client, ADMIN_KEY)
        resp = client.post(
            _approval_route(revision.revision_id),
            json={"decision": "approve", "reason": "второе лицо"},
        )
        assert resp.status_code == 200

    def test_single_policy_allows_owner_approval(self, client):
        _document, revision = _seed_revision()
        _cookie(client)
        client.post(_approval_route(revision.revision_id), json={"action": "request"})
        resp = client.post(
            _approval_route(revision.revision_id),
            json={"decision": "approve", "reason": "пилот single"},
        )
        assert resp.status_code == 200

    def test_unknown_policy_fails_closed_to_single_with_warning(self, client, monkeypatch):
        monkeypatch.setenv("CISSTAT_DOCLOG_APPROVAL_POLICY", "nonsense")
        from apps.api.document_lifecycle import approval_policy

        assert approval_policy() == "single"


# ══════════════════════════════════════════════════════════════════════
# 5. Mandatory audit fail-closed (§14.1/AC11; D7)
# ══════════════════════════════════════════════════════════════════════


class TestMandatoryAuditFailClosed:
    def _break_audit_sink(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.api import security_audit

        class _BrokenSink:
            def append(self, record: dict) -> bool:  # pragma: no cover
                raise RuntimeError("audit sink down")

        monkeypatch.setattr(security_audit, "get_audit_sink", lambda: _BrokenSink())

    def test_approve_fails_closed(self, client, monkeypatch):
        _document, revision = _seed_revision()
        _cookie(client)
        client.post(_approval_route(revision.revision_id), json={"action": "request"})
        self._break_audit_sink(monkeypatch)
        resp = client.post(
            _approval_route(revision.revision_id),
            json={"decision": "approve"},
        )
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "mandatory_audit_unavailable"
        # Состояние не изменилось.
        resp = client.get(f"/v1/documentation/revisions/{revision.revision_id}")
        assert resp.json()["revision"]["lifecycle_state"] == "ready_for_review"

    def test_publish_fails_closed(self, client, monkeypatch):
        snapshot = _seed_snapshot(kinds=["D02"])
        document, revision = _seed_revision(snapshot)
        _cookie(client)
        _publish_flow(client, document, revision)
        # Retract -- тоже mandatory: ломаем аудит -> retract не выполняется.
        self._break_audit_sink(monkeypatch)
        resp = client.post(
            f"/v1/documentation/revisions/{revision.revision_id}/retract",
            json={"reason": "ошибка данных"},
        )
        assert resp.status_code == 503
        resp = client.get(f"/v1/documentation/revisions/{revision.revision_id}")
        assert resp.json()["revision"]["lifecycle_state"] == "published"

    def test_lifecycle_read_does_not_change_science_state(self, client):
        snapshot = _seed_snapshot(kinds=["D02"])
        document, revision = _seed_revision(snapshot)
        _cookie(client)
        from apps.api.report_snapshot import peek_snapshot_registry

        before = peek_snapshot_registry().list_records(RUN_ID)
        resp = client.get(
            f"/v1/documentation/revisions/{revision.revision_id}/lifecycle"
        )
        assert resp.status_code == 200
        resp = client.get(
            f"/v1/documentation/revisions/{revision.revision_id}"
        )
        assert resp.status_code == 200
        after = peek_snapshot_registry().list_records(RUN_ID)
        assert [s.snapshot_id for s in before] == [s.snapshot_id for s in after]


# ══════════════════════════════════════════════════════════════════════
# 6. Publish policy: обязательные разделы/полнота (§11)
# ══════════════════════════════════════════════════════════════════════


class TestPublishPolicy:
    def _approve(self, client: TestClient, revision) -> None:
        client.post(_approval_route(revision.revision_id), json={"action": "request"})
        resp = client.post(
            _approval_route(revision.revision_id),
            json={"decision": "approve", "reason": "ok"},
        )
        assert resp.status_code == 200

    def test_d11_partial_completeness_blocks_publish(self, client):
        # D11 с dangling result_ref -> partial; gaps блокируют публикацию
        # итогового отчёта (§11: «для итогового D11 policy определяет,
        # какие gaps блокируют публикацию»).
        snapshot = _seed_snapshot(kinds=["D11"], dangling_artifact_ref=True)
        assert snapshot.completeness["status"] == "partial"
        _document, revision = _seed_revision(snapshot, kind_code="D11")
        _cookie(client)
        self._approve(client, revision)
        resp = client.post(f"/v1/documentation/revisions/{revision.revision_id}/publish")
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "publish_blocked_gaps"

    def test_d11_complete_publishes(self, client):
        snapshot = _seed_snapshot(kinds=["D11"])
        _document, revision = _seed_revision(snapshot, kind_code="D11")
        _cookie(client)
        self._approve(client, revision)
        resp = client.post(f"/v1/documentation/revisions/{revision.revision_id}/publish")
        assert resp.status_code == 200

    def test_partial_d02_publishes_with_honest_partial(self, client):
        # Для D01-D10 partial допустим (политика v1: gaps блокируют
        # только итоговый D11).
        snapshot = _seed_snapshot(kinds=["D02"], dangling_artifact_ref=True)
        assert snapshot.completeness["status"] == "partial"
        _document, revision = _seed_revision(snapshot, kind_code="D02")
        _cookie(client)
        self._approve(client, revision)
        resp = client.post(f"/v1/documentation/revisions/{revision.revision_id}/publish")
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════
# 7. Retract и supersede (§11; D3)
# ══════════════════════════════════════════════════════════════════════


class TestRetractSupersede:
    def test_retract_with_reason_append_only(self, client):
        snapshot = _seed_snapshot(kinds=["D02"])
        document, revision = _seed_revision(snapshot)
        _publish_flow(client, document, revision)
        _cookie(client)
        resp = client.post(
            f"/v1/documentation/revisions/{revision.revision_id}/retract",
            json={"reason": "обнаружена ошибка входных данных"},
        )
        assert resp.status_code == 200
        assert resp.json()["revision"]["lifecycle_state"] == "retracted"
        resp = client.get(
            f"/v1/documentation/revisions/{revision.revision_id}/lifecycle"
        )
        events = [record["event"] for record in resp.json()["records"]]
        assert events == ["approval_requested", "approved", "published", "retracted"]
        retracted = resp.json()["records"][-1]
        assert retracted["reason"] == "обнаружена ошибка входных данных"
        # Повторный retract -- 422 (терминальное состояние попытки).
        resp = client.post(
            f"/v1/documentation/revisions/{revision.revision_id}/retract",
            json={"reason": "ещё раз"},
        )
        assert resp.status_code == 422

    def test_new_publication_supersedes_previous(self, client):
        snapshot1 = _seed_snapshot(kinds=["D02"])
        document, revision1 = _seed_revision(snapshot1)
        _publish_flow(client, document, revision1)
        # Новая заморозка -> ревизия 2 -> публикация -> rev1 superseded.
        _seed_event(RUN_ID, event_type="mode_changed", payload={"mode": "eda"})
        snapshot2 = _seed_snapshot(kinds=["D02"])
        _document, revision2 = _seed_revision(snapshot2)
        _publish_flow(client, document, revision2)
        _cookie(client)
        resp = client.get(f"/v1/documentation/revisions/{revision1.revision_id}")
        assert resp.json()["revision"]["lifecycle_state"] == "superseded"
        resp = client.get(
            f"/v1/documentation/revisions/{revision1.revision_id}/lifecycle"
        )
        events = [record["event"] for record in resp.json()["records"]]
        assert events[-1] == "superseded"
        assert (
            resp.json()["records"][-1]["details"].get("superseded_by")
            == revision2.revision_id
        )


# ══════════════════════════════════════════════════════════════════════
# 8. Diff ревизий (§17; D10-решение)
# ══════════════════════════════════════════════════════════════════════


class TestRevisionDiff:
    def test_diff_between_revisions_of_same_document(self, client):
        snapshot1 = _seed_snapshot(kinds=["D02"])
        document, revision1 = _seed_revision(snapshot1)
        _cookie(client)
        _seed_event(RUN_ID, event_type="mode_changed", payload={"mode": "eda"})
        snapshot2 = _seed_snapshot(kinds=["D02"])
        _document, revision2 = _seed_revision(snapshot2)
        resp = client.get(
            f"/v1/documentation/revisions/{revision2.revision_id}/diff",
            params={"against": revision1.revision_id},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["revision_id"] == revision2.revision_id
        assert body["against_revision_id"] == revision1.revision_id
        # Metadata-различия честны (captured_at различается всегда).
        assert "captured_at" in body["metadata"]
        # Никакого пересчёта: diff построен из замороженных снимков.
        assert body["recalculated"] is False

    def test_diff_direction_natural_semantics(self, client):
        """Пин направления diff (F-D6C1; DOCLOG-6-CERT-FIX): diff(rev,
        against=prev) читается как изменения ОТ against К rev --
        естественному чтению подписей панели doclog6-diff
        («Добавлено утверждений» / «Убрано утверждений»).
        claims.added = утверждения, появившиеся в rev относительно
        against; claims.removed = существовавшие в against и
        отсутствующие в rev; metadata.from = значение against,
        metadata.to = значение rev."""
        snapshot1 = _seed_snapshot(kinds=["D02"])
        document, revision1 = _seed_revision(snapshot1)
        _cookie(client)
        # Дополнительное upload-событие того же run: уникальный claim
        # появляется ТОЛЬКО в rev2 (D02-адаптер: «Загружен датасет…»).
        _seed_event(
            RUN_ID,
            event_type="upload_completed",
            payload={"name": "d6-fix-extra", "rows": 3, "columns": 2},
        )
        snapshot2 = _seed_snapshot(kinds=["D02"])
        _document, revision2 = _seed_revision(snapshot2)
        resp = client.get(
            f"/v1/documentation/revisions/{revision2.revision_id}/diff",
            params={"against": revision1.revision_id},
        )
        assert resp.status_code == 200
        body = resp.json()
        added_texts = [claim["text"] for claim in body["claims"]["added"]]
        removed_texts = [claim["text"] for claim in body["claims"]["removed"]]
        # NEW-claim rev2 попадает в added, не в removed.
        assert any("d6-fix-extra" in text for text in added_texts)
        assert not any("d6-fix-extra" in text for text in removed_texts)
        # Metadata: from = значение AGAINST (rev1), to = значение rev.
        assert body["metadata"]["captured_at"]["from"] == snapshot1.captured_at
        assert body["metadata"]["captured_at"]["to"] == snapshot2.captured_at

    def test_diff_across_documents_422(self, client):
        snapshot1 = _seed_snapshot(kinds=["D01"])
        _document1, revision1 = _seed_revision(snapshot1, kind_code="D01")
        _cookie(client)
        snapshot2 = _seed_snapshot(kinds=["D02"])
        _document2, revision2 = _seed_revision(snapshot2, kind_code="D02")
        resp = client.get(
            f"/v1/documentation/revisions/{revision2.revision_id}/diff",
            params={"against": revision1.revision_id},
        )
        assert resp.status_code == 422

    def test_diff_foreign_revision_404(self, client):
        snapshot1 = _seed_snapshot(kinds=["D02"])
        _document, revision1 = _seed_revision(snapshot1)
        _cookie(client)
        _seed_session(FOREIGN_SESSION_ID)
        _cookie(client, FOREIGN_SESSION_ID)
        resp = client.get(
            f"/v1/documentation/revisions/{revision1.revision_id}/diff",
            params={"against": revision1.revision_id},
        )
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# 9. Retention: hold/release и sweep (§16.1; D8)
# ══════════════════════════════════════════════════════════════════════


class TestRetention:
    def test_hold_release_audit(self, client):
        snapshot = _seed_snapshot(kinds=["D02"])
        document, _revision = _seed_revision(snapshot)
        _cookie(client)
        resp = client.post(
            f"/v1/documentation/documents/{document.document_id}/retention",
            json={"action": "hold", "reason": "юридический hold"},
        )
        assert resp.status_code == 200
        assert resp.json()["retention"]["hold"] is True
        assert resp.json()["retention"]["hold_reason"] == "юридический hold"
        resp = client.post(
            f"/v1/documentation/documents/{document.document_id}/retention",
            json={"action": "release"},
        )
        assert resp.status_code == 200
        assert resp.json()["retention"]["hold"] is False

    def test_sweep_purges_stale_draft_rendition(self, client, monkeypatch):
        from apps.api.document_jobs import replace_dataclass

        monkeypatch.setenv("CISSTAT_DOCUMENT_RETENTION_DRAFT_DAYS", "30")
        snapshot = _seed_snapshot(kinds=["D02"])
        document, revision = _seed_revision(snapshot)
        _cookie(client)
        resp = client.post(
            f"/v1/documentation/revisions/{revision.revision_id}/renditions",
            json={"format": "md"},
        )
        assert resp.status_code == 202
        job = resp.json()["job"]
        # P0-рендер синхронный: rendition готова сразу.
        registry = _delivery().registry
        renditions = registry.list_renditions(snapshot.snapshot_id)
        assert renditions and renditions[0].state == "ready"
        rendition = renditions[0]
        # Состаривание: created_at 40 дней назад (запись в Memory-реестре).
        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        registry.update_rendition(replace_dataclass(rendition, created_at=old))
        resp = client.post(f"/v1/documentation/runs/{RUN_ID}/retention/sweep")
        assert resp.status_code == 200
        body = resp.json()
        assert body["report"]["purged_renditions"] == 1
        # Tombstone: запись жива, байтов нет (честный purged).
        after = registry.get_rendition(rendition.rendition_id)
        assert after.state == "purged"
        # Чтение контента purged -- честный 410 владельцу (§17).
        _cookie(client)
        resp = client.get(
            f"/v1/documentation/renditions/{rendition.rendition_id}/content"
        )
        assert resp.status_code == 410
        assert resp.json()["detail"]["code"] == "purged_artifact"

    def test_sweep_never_purges_published_document(self, client):
        from apps.api.document_jobs import replace_dataclass

        snapshot = _seed_snapshot(kinds=["D02"])
        document, revision = _seed_revision(snapshot)
        _cookie(client)
        client.post(
            f"/v1/documentation/revisions/{revision.revision_id}/renditions",
            json={"format": "md"},
        )
        _publish_flow(client, document, revision)
        registry = _delivery().registry
        renditions = registry.list_renditions(snapshot.snapshot_id)
        for rendition in renditions:
            old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
            registry.update_rendition(
                replace_dataclass(rendition, created_at=old)
            )
        resp = client.post(f"/v1/documentation/runs/{RUN_ID}/retention/sweep")
        assert resp.status_code == 200
        assert resp.json()["report"]["purged_renditions"] == 0
        assert resp.json()["report"]["kept_published_documents"] == 1
        after = registry.get_rendition(renditions[0].rendition_id)
        assert after.state == "ready"

    def test_sweep_respects_hold(self, client):
        from apps.api.document_jobs import replace_dataclass

        snapshot = _seed_snapshot(kinds=["D02"])
        document, revision = _seed_revision(snapshot)
        _cookie(client)
        client.post(
            f"/v1/documentation/revisions/{revision.revision_id}/renditions",
            json={"format": "md"},
        )
        client.post(
            f"/v1/documentation/documents/{document.document_id}/retention",
            json={"action": "hold", "reason": "hold"},
        )
        registry = _delivery().registry
        rendition = registry.list_renditions(snapshot.snapshot_id)[0]
        old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        registry.update_rendition(replace_dataclass(rendition, created_at=old))
        resp = client.post(f"/v1/documentation/runs/{RUN_ID}/retention/sweep")
        assert resp.status_code == 200
        assert resp.json()["report"]["skipped_hold_documents"] == 1
        assert resp.json()["report"]["purged_renditions"] == 0


# ══════════════════════════════════════════════════════════════════════
# 10. Archive и restore drill (§16/AC18; D9)
# ══════════════════════════════════════════════════════════════════════


class TestArchiveRestoreDrill:
    def _prepare(self, client: TestClient):
        snapshot = _seed_snapshot(kinds=["D02"])
        document, revision = _seed_revision(snapshot)
        _cookie(client)
        _publish_flow(client, document, revision)
        return document, revision, snapshot

    def test_archive_bundle_structure(self, client):
        _document, _revision, snapshot = self._prepare(client)
        resp = client.post(f"/v1/documentation/runs/{RUN_ID}/archive")
        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == RUN_ID
        assert body["bundle_id"]
        assert body["member_count"] > 0
        assert body["manifest_sha256"]
        # Пакет на диске: manifest + metadata + objects (без путей в ответе).
        data_dir = Path(_delivery().objects._root).parent
        bundle_dir = data_dir / "archive" / RUN_ID / body["bundle_id"]
        manifest_path = bundle_dir / "manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text("utf-8"))
        # §13.3: manifest не содержит собственного hash (циклическое
        # определение запрещено).
        member_paths = {member["path"] for member in manifest["members"]}
        assert "manifest.json" not in member_paths
        assert "metadata.jsonl" in member_paths
        for member in manifest["members"]:
            target = bundle_dir / member["path"]
            assert target.exists(), member["path"]
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            assert digest == member["sha256"]

    def test_verify_drill_ok(self, client):
        self._prepare(client)
        created = client.post(f"/v1/documentation/runs/{RUN_ID}/archive").json()
        resp = client.post(
            f"/v1/documentation/runs/{RUN_ID}/archive/verify",
            json={"bundle_id": created["bundle_id"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["missing"] == []
        assert body["mismatched"] == []
        assert body["checked_refs"] > 0
        assert body["duration_ms"] >= 0

    def test_verify_missing_object_not_masked(self, client):
        _document, _revision, _snapshot = self._prepare(client)
        created = client.post(f"/v1/documentation/runs/{RUN_ID}/archive").json()
        data_dir = Path(_delivery().objects._root).parent
        bundle_dir = data_dir / "archive" / RUN_ID / created["bundle_id"]
        # Удаляем один объектный член -- restore drill НЕ маскирует.
        members = json.loads(
            (bundle_dir / "manifest.json").read_text("utf-8")
        )["members"]
        object_member = next(
            m for m in members if m["path"].startswith("objects/")
        )
        (bundle_dir / object_member["path"]).unlink()
        resp = client.post(
            f"/v1/documentation/runs/{RUN_ID}/archive/verify",
            json={"bundle_id": created["bundle_id"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert object_member["path"] in body["missing"]

    def test_verify_tampered_member_reported(self, client):
        _document, _revision, _snapshot = self._prepare(client)
        created = client.post(f"/v1/documentation/runs/{RUN_ID}/archive").json()
        data_dir = Path(_delivery().objects._root).parent
        bundle_dir = data_dir / "archive" / RUN_ID / created["bundle_id"]
        members = json.loads(
            (bundle_dir / "manifest.json").read_text("utf-8")
        )["members"]
        target = bundle_dir / members[0]["path"]
        target.write_bytes(target.read_bytes() + b"tampered")
        resp = client.post(
            f"/v1/documentation/runs/{RUN_ID}/archive/verify",
            json={"bundle_id": created["bundle_id"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert members[0]["path"] in body["mismatched"]


# ══════════════════════════════════════════════════════════════════════
# 11. Миграция 0012 и паритет файл↔каталог
# ══════════════════════════════════════════════════════════════════════


class TestMigration0012:
    def test_catalog_counts(self):
        from apps.api.research_runs import MIGRATION_FILES, MIGRATION_STATEMENTS

        assert len(MIGRATION_FILES) == 14
        # DOCLOG-8 (честное обновление пина): последний файл каталога --
        # 0014; сами миграции 0012/0013 -- предпоследние (пин по имени).
        assert "0012_doclog6_approvals_archive.sql" in [n for n, _ in MIGRATION_FILES]
        # 78 (0013) + 7 statement 0014 (3 таблицы + 4 индекса).
        assert len(MIGRATION_STATEMENTS) == 85

    def test_file_parity(self):
        from apps.api.research_runs import MIGRATION_FILES

        name, statements = MIGRATION_FILES[-1]
        path = Path("apps/api/migrations") / name
        sql = path.read_text("utf-8")
        for statement in statements:
            compact = " ".join(statement.split())
            assert compact in " ".join(sql.split()), statement[:80]

    def test_new_tables_present_in_ddl(self):
        path = Path("apps/api/migrations/0012_doclog6_approvals_archive.sql")
        sql = path.read_text("utf-8")
        for table in (
            "document_approvals",
            "document_lifecycle",
            "document_retention",
        ):
            assert f"CREATE TABLE IF NOT EXISTS {table}" in sql


# ══════════════════════════════════════════════════════════════════════
# 12. Audit-реестр: новое действие
# ══════════════════════════════════════════════════════════════════════


class TestAuditActions:
    def test_archive_bundle_created_action_registered(self):
        from apps.api import security_audit

        assert "archive_bundle_created" in security_audit.AUDIT_ACTIONS

    def test_human_read_confirmed_still_absent(self):
        from apps.api import security_audit

        assert "human_read_confirmed" not in security_audit.AUDIT_ACTIONS
