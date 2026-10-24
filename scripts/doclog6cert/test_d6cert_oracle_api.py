# scripts/doclog6cert/test_d6cert_oracle_api.py
"""DOCLOG-6-CERT: API-оракулы на СВОИХ данных (a01–a38).

Поверхность DOCLOG-6 через HTTP на собственном корпусе (RUN-D6C*,
d6cert-*): полный поток согласования с точным bound-hash (AC07),
manifest только из ready-форм, разделение прав с гранулярностью scopes
(свой run, принадлежащий key-субъекту), two_person на ключевых
субъектах (requester≠approver по scopes, reject-ветка), mandatory
audit fail-closed на publish c восстановлением, publish-policy на СВОИХ
снимках (пустые секции/partial D10/D11), retention tombstone с честной
проверкой УДАЛЕНИЯ БАЙТОВ, archive-пакет на run с двумя документами и
drill с ref_errors (ссылочная целостность при ВАЛИДНЫХ checksums),
diff ревизий с validity_changed/added на собственных снимках, AC05
tripwire неизменности науки.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from apps.api.document_jobs import replace_dataclass

from .conftest import (
    CERT_ADMIN_KEY,
    CERT_APPROVER_KEY,
    CERT_APPROVER_SUBJ,
    CERT_RUN_ID,
    CERT_RUN_ID_B,
    CERT_RUN_ID_C,
    CERT_WRITER_KEY,
    CERT_WRITER_SUBJ,
    OWN_SECTIONS_A,
    OWN_SECTIONS_B,
    api_key,
    approve_route,
    archive_dir,
    build_own_snapshot,
    cert_subject,
    cookie,
    ensure_own_revision,
    full_publish_flow,
    register_failed_rendition,
    scoped_keys_env,
    seed_cert_run,
)

# ── сиды ─────────────────────────────────────────────────────────────


def _seed_own_revision(kind_code="D02", **snapshot_kwargs):
    snapshot = build_own_snapshot(kinds=[kind_code], **snapshot_kwargs)
    document, revision = ensure_own_revision(snapshot, kind_code)
    return snapshot, document, revision


def _publish_two_revisions(client):
    """Свой документ с двумя опубликованными ревизиями (supersede)."""
    snapshot1, document, revision1 = _seed_own_revision()
    full_publish_flow(client, document, revision1)
    snapshot2 = build_own_snapshot(
        snapshot_key="snap-b",
        kinds=["D02"],
        sections=OWN_SECTIONS_B,
        context_id="ctx-d6cert-2",
        data_revision=8,
        captured_at="2026-10-23T13:45:00+00:00",
        event_count=62,
        last_sequence=2062,
    )
    _document, revision2 = ensure_own_revision(snapshot2, "D02")
    assert revision2.revision_id != revision1.revision_id
    full_publish_flow(client, document, revision2)
    return document, revision1, revision2, snapshot1, snapshot2


# ══ 1. Полный поток на своих данных (§11) ════════════════════════════


def test_a01_initial_state_draft(cert_client):
    seed_cert_run()
    _snapshot, _document, revision = _seed_own_revision()
    cookie(cert_client)
    resp = cert_client.get(
        f"/v1/documentation/revisions/{revision.revision_id}"
    )
    assert resp.status_code == 200
    assert resp.json()["revision"]["lifecycle_state"] == "draft"


def test_a02_repeat_request_422(cert_client):
    seed_cert_run()
    _snapshot, _document, revision = _seed_own_revision()
    cookie(cert_client)
    r1 = cert_client.post(approve_route(revision.revision_id), json={"action": "request"})
    assert r1.status_code == 200
    r2 = cert_client.post(approve_route(revision.revision_id), json={"action": "request"})
    assert r2.status_code == 422
    assert r2.json()["detail"]["code"] == "invalid_transition"


def test_a03_approve_with_correct_expected_hash(cert_client):
    seed_cert_run()
    snapshot, _document, revision = _seed_own_revision()
    cookie(cert_client)
    cert_client.post(approve_route(revision.revision_id), json={"action": "request"})
    resp = cert_client.post(
        approve_route(revision.revision_id),
        json={
            "decision": "approve",
            "reason": "d6cert-bound",
            "expected_snapshot_sha256": snapshot.payload_sha256,
        },
    )
    assert resp.status_code == 200, resp.text
    approval = resp.json()["approval"]
    assert approval["snapshot_payload_sha256"] == snapshot.payload_sha256
    assert approval["revision_id"] == revision.revision_id
    assert approval["decision"] == "approve"
    assert approval["actor_subject"]
    assert approval["policy"] == "single"
    assert approval["policy_version"]


def test_a04_approve_without_request_422(cert_client):
    seed_cert_run()
    _snapshot, _document, revision = _seed_own_revision()
    cookie(cert_client)
    resp = cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_transition"


def test_a05_publish_record_honest_details(cert_client):
    seed_cert_run()
    snapshot, document, revision = _seed_own_revision()
    cookie(cert_client)
    cert_client.post(approve_route(revision.revision_id), json={"action": "request"})
    approved = cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve", "reason": "ok"},
    ).json()
    approval_id = approved["approval"]["approval_id"]
    resp = cert_client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/publish"
    )
    assert resp.status_code == 200
    record = resp.json()["record"]
    assert record["event"] == "published"
    assert record["details"]["approval_id"] == approval_id
    assert record["details"]["snapshot_payload_sha256"] == snapshot.payload_sha256
    # Первая публикация документа: supersede-ссылки нет (честный null).
    assert record["details"]["supersedes_revision_id"] is None


def test_a06_pin_exact_reason_and_creator(cert_client):
    seed_cert_run()
    _snapshot, document, revision = _seed_own_revision()
    full_publish_flow(cert_client, document, revision)
    from apps.api.artifact_store import get_artifact_registry

    pins = get_artifact_registry().list_pins(CERT_RUN_ID)
    matched = [
        pin
        for pin in pins
        if pin.reason
        == f"document:{document.document_id}:published:{revision.version_no}"
    ]
    assert matched, [pin.reason for pin in pins]
    assert matched[0].ref_kind == "snapshot"
    assert matched[0].ref_id == revision.snapshot_id


def test_a07_publish_after_retract_422(cert_client):
    seed_cert_run()
    _snapshot, document, revision = _seed_own_revision()
    full_publish_flow(cert_client, document, revision)
    cookie(cert_client)
    resp = cert_client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/retract",
        json={"reason": "d6cert-retract"},
    )
    assert resp.status_code == 200
    resp = cert_client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/publish"
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_transition"


def test_a08_supersede_both_sides_honest(cert_client):
    seed_cert_run()
    document, revision1, revision2, _s1, _s2 = _publish_two_revisions(cert_client)
    cookie(cert_client)
    # Сторона старой ревизии: superseded + superseded_by.
    resp = cert_client.get(
        f"/v1/documentation/revisions/{revision1.revision_id}/lifecycle"
    )
    records = resp.json()["records"]
    assert records[-1]["event"] == "superseded"
    assert records[-1]["details"]["superseded_by"] == revision2.revision_id
    # Сторона новой ревизии: publish-запись несёт supersedes_revision_id.
    resp = cert_client.get(
        f"/v1/documentation/revisions/{revision2.revision_id}/lifecycle"
    )
    records = resp.json()["records"]
    published = next(r for r in records if r["event"] == "published")
    assert published["details"]["supersedes_revision_id"] == revision1.revision_id
    # Состояния читаются вычислением из append-only.
    resp1 = cert_client.get(
        f"/v1/documentation/revisions/{revision1.revision_id}"
    )
    resp2 = cert_client.get(
        f"/v1/documentation/revisions/{revision2.revision_id}"
    )
    assert resp1.json()["revision"]["lifecycle_state"] == "superseded"
    assert resp2.json()["revision"]["lifecycle_state"] == "published"


def test_a09_republish_superseded_422(cert_client):
    seed_cert_run()
    document, revision1, _revision2, _s1, _s2 = _publish_two_revisions(cert_client)
    cookie(cert_client)
    resp = cert_client.post(
        f"/v1/documentation/revisions/{revision1.revision_id}/publish"
    )
    assert resp.status_code == 422


# ══ 2. Approval bound hash (AC07) на своих данных ════════════════════


def test_a10_manifest_excludes_not_ready_renditions(cert_client):
    """Собственный негативный контроль канала согласования: failed-форма
    НЕ попадает в approval manifest (только ready)."""
    seed_cert_run()
    snapshot, _document, revision = _seed_own_revision()
    cookie(cert_client)
    resp = cert_client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/renditions",
        json={"format": "md"},
    )
    assert resp.status_code == 202
    register_failed_rendition(revision, snapshot)
    cert_client.post(approve_route(revision.revision_id), json={"action": "request"})
    resp = cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve", "reason": "manifest"},
    )
    assert resp.status_code == 200
    manifest = resp.json()["approval"]["approval_manifest"]
    assert len(manifest) == 1, manifest
    assert manifest[0]["format"] == "md"


def test_a11_publish_409_on_tampered_rendition_hash(cert_client):
    seed_cert_run()
    snapshot, document, revision = _seed_own_revision()
    cookie(cert_client)
    cert_client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/renditions",
        json={"format": "md"},
    )
    cert_client.post(approve_route(revision.revision_id), json={"action": "request"})
    cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve", "reason": "ok"},
    )
    from apps.api.document_jobs import DocumentDeliveryService

    registry = DocumentDeliveryService.create_default().registry
    rendition = registry.list_renditions(snapshot.snapshot_id)[0]
    registry.update_rendition(
        replace_dataclass(rendition, content_sha256="f" * 64)
    )
    resp = cert_client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/publish"
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "approval_not_applicable"
    state = cert_client.get(
        f"/v1/documentation/revisions/{revision.revision_id}"
    ).json()["revision"]["lifecycle_state"]
    assert state == "approved"  # publish не выполнен


def test_a12_approval_not_transferred_to_new_revision(cert_client):
    seed_cert_run()
    snapshot1, document, revision1 = _seed_own_revision()
    full_publish_flow(cert_client, document, revision1)
    snapshot2 = build_own_snapshot(
        snapshot_key="snap-transfer",
        kinds=["D02"],
        context_id="ctx-d6cert-2",
        data_revision=9,
    )
    _document, revision2 = ensure_own_revision(snapshot2, "D02")
    cookie(cert_client)
    resp = cert_client.post(
        f"/v1/documentation/revisions/{revision2.revision_id}/publish"
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "publish_requires_approval"


# ══ 3. Разделение прав: 9 маршрутов + гранулярность scopes ═══════════


def test_a13_foreign_uniform_404_on_all_nine_routes(cert_client):
    seed_cert_run()
    snapshot, document, revision = _seed_own_revision()
    full_publish_flow(cert_client, document, revision)
    seed_cert_run("RUN-D6C00009", "d6c-cert-foreign-session")
    cookie(cert_client, "d6c-cert-foreign-session")
    matrix = [
        ("post", approve_route(revision.revision_id), {"action": "request"}),
        ("post", approve_route(revision.revision_id), {"decision": "approve"}),
        ("post", f"/v1/documentation/revisions/{revision.revision_id}/publish", None),
        ("post", f"/v1/documentation/revisions/{revision.revision_id}/retract", {"reason": "x"}),
        ("get", f"/v1/documentation/revisions/{revision.revision_id}/lifecycle", None),
        ("get", f"/v1/documentation/revisions/{revision.revision_id}/diff?against={revision.revision_id}", None),
        ("post", f"/v1/documentation/documents/{document.document_id}/retention", {"action": "hold"}),
        ("post", f"/v1/documentation/runs/{CERT_RUN_ID}/retention/sweep", None),
        ("post", f"/v1/documentation/runs/{CERT_RUN_ID}/archive", None),
        ("post", f"/v1/documentation/runs/{CERT_RUN_ID}/archive/verify", {"bundle_id": "d6arch-x"}),
    ]
    for method, url, payload in matrix:
        if method == "post":
            resp = cert_client.post(url, json=payload or {})
        else:
            resp = cert_client.get(url)
        assert resp.status_code == 404, (url, resp.status_code)


def test_a14_anonymous_404(cert_client):
    seed_cert_run()
    _snapshot, _document, revision = _seed_own_revision()
    resp = cert_client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/publish"
    )
    assert resp.status_code == 404


def test_a15_scoped_mode_cookie_owner_403(cert_client, monkeypatch):
    monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "scoped")
    seed_cert_run()
    _snapshot, _document, revision = _seed_own_revision()
    cookie(cert_client)
    resp = cert_client.post(approve_route(revision.revision_id), json={"action": "request"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "insufficient_scope"


def test_a16_scope_granularity_on_key_owned_run(cert_client, monkeypatch):
    """Свой run, владелец -- key-субъект с documentation.write: запрос
    согласования доступен, решение -- 403 (права нет, ресурс свой)."""
    monkeypatch.setenv("CISSTAT_API_KEYS", scoped_keys_env())
    seed_cert_run(
        CERT_RUN_ID_B,
        "d6cert-session-b",
        owner_subject_id=CERT_WRITER_SUBJ,
    )
    snapshot = build_own_snapshot(
        snapshot_key="snap-key", run_id=CERT_RUN_ID_B, kinds=["D02"]
    )
    _document, revision = ensure_own_revision(
        snapshot, "D02", session_id="d6cert-session-b"
    )
    api_key(cert_client, CERT_WRITER_KEY)
    r1 = cert_client.post(approve_route(revision.revision_id), json={"action": "request"})
    assert r1.status_code == 200, r1.text
    r2 = cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve", "reason": "write-only"},
    )
    assert r2.status_code == 403
    assert r2.json()["detail"]["code"] == "insufficient_scope"
    # publish -- тоже не по write-scope.
    r3 = cert_client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/publish"
    )
    assert r3.status_code == 403


def test_a17_admin_second_person_on_key_owned_run(cert_client, monkeypatch):
    """Разделение прав на своих субъектах: writer (documentation.write)
    запрашивает, ADMIN-key утверждает -- второе лицо по решающей таблице
    DOCLOG-0 (не-admin ключ на чужой run не проходит run-уровень: честно
    404 -- проверено калибровкой)."""
    monkeypatch.setenv("CISSTAT_API_KEYS", scoped_keys_env())
    seed_cert_run(
        CERT_RUN_ID_B,
        "d6cert-session-b",
        owner_subject_id=CERT_WRITER_SUBJ,
    )
    snapshot = build_own_snapshot(
        snapshot_key="snap-approve", run_id=CERT_RUN_ID_B, kinds=["D02"]
    )
    _document, revision = ensure_own_revision(
        snapshot, "D02", session_id="d6cert-session-b"
    )
    api_key(cert_client, CERT_WRITER_KEY)
    assert cert_client.post(
        approve_route(revision.revision_id), json={"action": "request"}
    ).status_code == 200
    api_key(cert_client, CERT_ADMIN_KEY)
    resp = cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve", "reason": "scope-approve"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["approval"]["actor_via"] == "api_key"
    assert resp.json()["approval"]["actor_subject"] != CERT_WRITER_SUBJ
    # Не-admin ключ на чужой run -- uniform 404 (решающая таблица R09).
    api_key(cert_client, CERT_APPROVER_KEY)
    denied = cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve"},
    )
    assert denied.status_code == 404


def test_a18_two_person_self_approval_by_owner(cert_client, monkeypatch):
    """two_person: утверждающий == запросивший == создатель (владелец-
    суррогат имеет полные пилотные права) -- 422 self_approval_forbidden;
    второе лицо (ADMIN-key) утверждает -- 200. Калибровка: субъект БЕЗ
    approve-scope получает 403 ДО two_person-проверки (порядок
    fail-closed: резолв -> права -> policy), поэтому сцена самосогласования
    -- владелец-суррогат."""
    monkeypatch.setenv("CISSTAT_API_KEYS", scoped_keys_env())
    monkeypatch.setenv("CISSTAT_DOCLOG_APPROVAL_POLICY", "two_person")
    seed_cert_run()
    snapshot = build_own_snapshot(kinds=["D02"])
    _document, revision = ensure_own_revision(snapshot, "D02")
    cookie(cert_client)  # владелец: создатель + запросивший + утверждающий
    assert cert_client.post(
        approve_route(revision.revision_id), json={"action": "request"}
    ).status_code == 200
    resp = cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve", "reason": "сам запросил"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "self_approval_forbidden"
    state = cert_client.get(
        f"/v1/documentation/revisions/{revision.revision_id}"
    ).json()["revision"]["lifecycle_state"]
    assert state == "ready_for_review"  # состояние не изменилось
    api_key(cert_client, CERT_ADMIN_KEY)
    ok = cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve", "reason": "второе лицо"},
    )
    assert ok.status_code == 200


def test_a19_two_person_reject_path(cert_client, monkeypatch):
    monkeypatch.setenv("CISSTAT_API_KEYS", scoped_keys_env())
    monkeypatch.setenv("CISSTAT_DOCLOG_APPROVAL_POLICY", "two_person")
    seed_cert_run(
        CERT_RUN_ID_B,
        "d6cert-session-b",
        owner_subject_id=CERT_WRITER_SUBJ,
    )
    snapshot = build_own_snapshot(
        snapshot_key="snap-rej", run_id=CERT_RUN_ID_B, kinds=["D02"]
    )
    _document, revision = ensure_own_revision(
        snapshot, "D02", session_id="d6cert-session-b"
    )
    api_key(cert_client, CERT_WRITER_KEY)
    cert_client.post(approve_route(revision.revision_id), json={"action": "request"})
    api_key(cert_client, CERT_ADMIN_KEY)
    resp = cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "reject", "reason": "не хватает оснований"},
    )
    assert resp.status_code == 200
    assert resp.json()["revision"]["lifecycle_state"] == "rejected"
    assert resp.json()["approval"]["decision"] == "reject"
    api_key(cert_client, CERT_WRITER_KEY)
    history = cert_client.get(
        f"/v1/documentation/revisions/{revision.revision_id}/lifecycle"
    ).json()["records"]
    assert [r["event"] for r in history] == ["approval_requested", "rejected"]


# ══ 4. Mandatory audit fail-closed на publish + восстановление ═══════


def _break_audit_sink(monkeypatch):
    from apps.api import security_audit

    class _BrokenSink:
        def append(self, record: dict) -> bool:
            raise RuntimeError("audit sink down (d6cert)")

    _original = security_audit.get_audit_sink
    monkeypatch.setattr(security_audit, "get_audit_sink", lambda: _BrokenSink())
    return _original


def test_a20_publish_fails_closed_503(cert_client, monkeypatch):
    seed_cert_run()
    _snapshot, document, revision = _seed_own_revision()
    cookie(cert_client)
    cert_client.post(approve_route(revision.revision_id), json={"action": "request"})
    cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve", "reason": "ok"},
    )
    _break_audit_sink(monkeypatch)
    resp = cert_client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/publish"
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "mandatory_audit_unavailable"
    state = cert_client.get(
        f"/v1/documentation/revisions/{revision.revision_id}"
    ).json()["revision"]["lifecycle_state"]
    assert state == "approved"  # состояние НЕ изменилось


def test_a21_audit_recovery_after_failure(cert_client, monkeypatch):
    """После отказа sink'а и его ВОССТАНОВЛЕНИЯ (свой restore, не
    teardown monkeypatch) операция выполняется: fail-closed не портит
    состояние и не «сжигает» согласование."""
    from apps.api import security_audit

    seed_cert_run()
    _snapshot, document, revision = _seed_own_revision()
    cookie(cert_client)
    cert_client.post(approve_route(revision.revision_id), json={"action": "request"})
    original_sink = _break_audit_sink(monkeypatch)
    denied = cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve"},
    )
    assert denied.status_code == 503
    # СВОЁ восстановление sink'а ДО повторной попытки.
    monkeypatch.setattr(security_audit, "get_audit_sink", lambda: original_sink())
    recovered = cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve", "reason": "после восстановления"},
    )
    assert recovered.status_code == 200, recovered.text
    # Согласование уже выдано: публикация напрямую (request -> 422
    # вернул бы invalid_transition -- ревизия уже approved).
    published = cert_client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/publish"
    )
    assert published.status_code == 200


# ══ 5. Publish-policy на СВОИХ снимках (§11) ═════════════════════════


def test_a22_empty_sections_block_publish(cert_client):
    """СВОЙ снимок без секций: публикация заблокирована (§11 «наличие
    обязательных разделов»); repo-корпус этого класса не достигает
    (сборщик всегда строит секции)."""
    seed_cert_run()
    snapshot = build_own_snapshot(
        snapshot_key="snap-empty",
        kinds=["D02"],
        sections=[],
    )
    _document, revision = ensure_own_revision(snapshot, "D02")
    cookie(cert_client)
    cert_client.post(approve_route(revision.revision_id), json={"action": "request"})
    cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve"},
    )
    resp = cert_client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/publish"
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "publish_blocked_gaps"


def test_a23_d10_partial_publishes(cert_client):
    """D10 с честным partial -- gaps НЕ блокируют (policy v1 блокирует
    только итоговый D11)."""
    seed_cert_run()
    snapshot = build_own_snapshot(
        snapshot_key="snap-d10",
        kinds=["D10"],
        completeness={"status": "partial", "missing_refs": ["res-d6c-x"]},
    )
    _document, revision = ensure_own_revision(snapshot, "D10")
    full_publish_flow(cert_client, _document, revision)


def test_a24_d11_partial_blocks_own_data(cert_client):
    seed_cert_run()
    snapshot = build_own_snapshot(
        snapshot_key="snap-d11",
        kinds=["D11"],
        completeness={"status": "partial", "missing_refs": ["res-d6c-dangling"]},
    )
    _document, revision = ensure_own_revision(snapshot, "D11")
    cookie(cert_client)
    cert_client.post(approve_route(revision.revision_id), json={"action": "request"})
    cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve"},
    )
    resp = cert_client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/publish"
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "publish_blocked_gaps"


# ══ 6. Retention: tombstone и байты (§16.1) ══════════════════════════


def _aged_rendition(client, snapshot, revision, days: int):
    resp = client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/renditions",
        json={"format": "md"},
    )
    assert resp.status_code == 202
    from apps.api.document_jobs import DocumentDeliveryService

    registry = DocumentDeliveryService.create_default().registry
    rendition = next(
        item
        for item in registry.list_renditions(snapshot.snapshot_id)
        if item.format == "md"
    )
    old = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    registry.update_rendition(replace_dataclass(rendition, created_at=old))
    return rendition


def test_a25_retention_hold_release_roundtrip(cert_client):
    seed_cert_run()
    _snapshot, document, _revision = _seed_own_revision()
    cookie(cert_client)
    resp = cert_client.post(
        f"/v1/documentation/documents/{document.document_id}/retention",
        json={"action": "hold", "reason": "d6cert-юридический hold"},
    )
    assert resp.status_code == 200
    body = resp.json()["retention"]
    assert body["hold"] is True
    assert body["hold_reason"] == "d6cert-юридический hold"
    assert body["updated_by"]
    resp = cert_client.post(
        f"/v1/documentation/documents/{document.document_id}/retention",
        json={"action": "release"},
    )
    assert resp.status_code == 200
    body = resp.json()["retention"]
    assert body["hold"] is False
    assert body["hold_reason"] == ""  # release очищает причину


def test_a26_retention_invalid_action_422(cert_client):
    seed_cert_run()
    _snapshot, document, _revision = _seed_own_revision()
    cookie(cert_client)
    resp = cert_client.post(
        f"/v1/documentation/documents/{document.document_id}/retention",
        json={"action": "purge"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_transition"


def test_a27_sweep_own_env_value_and_no_double_purge(cert_client, monkeypatch):
    monkeypatch.setenv("CISSTAT_DOCUMENT_RETENTION_DRAFT_DAYS", "1")
    seed_cert_run()
    snapshot, _document, revision = _seed_own_revision()
    cookie(cert_client)
    rendition = _aged_rendition(cert_client, snapshot, revision, days=2)
    resp = cert_client.post(
        f"/v1/documentation/runs/{CERT_RUN_ID}/retention/sweep"
    )
    assert resp.status_code == 200
    report = resp.json()["report"]
    assert report["purged_renditions"] == 1
    assert report["draft_days"] == 1  # своё значение env отражено честно
    # Повторный sweep: tombstone не считается повторно.
    resp = cert_client.post(
        f"/v1/documentation/runs/{CERT_RUN_ID}/retention/sweep"
    )
    assert resp.json()["report"]["purged_renditions"] == 0


def test_a28_purge_removes_object_bytes_tombstone_kept(cert_client, monkeypatch):
    monkeypatch.setenv("CISSTAT_DOCUMENT_RETENTION_DRAFT_DAYS", "0")
    seed_cert_run()
    snapshot, _document, revision = _seed_own_revision()
    cookie(cert_client)
    rendition = _aged_rendition(cert_client, snapshot, revision, days=0)
    from apps.api.document_jobs import DocumentDeliveryService

    delivery = DocumentDeliveryService.create_default()
    object_path = delivery.objects.path_for_key(rendition.storage_key)
    assert object_path.exists()
    resp = cert_client.post(
        f"/v1/documentation/runs/{CERT_RUN_ID}/retention/sweep"
    )
    assert resp.json()["report"]["purged_renditions"] == 1
    # БАЙТЫ удалены с диска (не только флаг).
    assert not object_path.exists()
    # Tombstone: запись жива, state=purged, чтение -- честный 410.
    after = delivery.registry.get_rendition(rendition.rendition_id)
    assert after.state == "purged"
    assert after.content_bytes is None
    resp = cert_client.get(
        f"/v1/documentation/renditions/{rendition.rendition_id}/content"
    )
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "purged_artifact"


def test_a29_sweep_empty_run_zeros(cert_client):
    seed_cert_run(CERT_RUN_ID_C, "d6cert-session-a")
    cookie(cert_client)
    resp = cert_client.post(
        f"/v1/documentation/runs/{CERT_RUN_ID_C}/retention/sweep"
    )
    assert resp.status_code == 200
    report = resp.json()["report"]
    assert report["scanned_documents"] == 0
    assert report["purged_renditions"] == 0


# ══ 7. Archive/restore drill на своих данных (§16/AC18) ══════════════


def _archive_own_run(client):
    """Свой run с ДВУМЯ документами, retention-записью и failed-формой."""
    seed_cert_run()
    snapshot_a, document_a, revision_a = _seed_own_revision("D02")
    snapshot_b, document_b, revision_b = _seed_own_revision("D01")
    cookie(client)
    full_publish_flow(client, document_a, revision_a)
    register_failed_rendition(revision_b, snapshot_b)
    client.post(
        f"/v1/documentation/documents/{document_b.document_id}/retention",
        json={"action": "hold", "reason": "d6cert-hold"},
    )
    created = client.post(
        f"/v1/documentation/runs/{CERT_RUN_ID}/archive"
    )
    assert created.status_code == 200
    return created.json(), document_a, document_b, snapshot_a, snapshot_b


def test_a30_archive_bundle_covers_all_entities(cert_client):
    body, document_a, document_b, snapshot_a, _snapshot_b = _archive_own_run(cert_client)
    assert body["run_id"] == CERT_RUN_ID
    assert body["bundle_id"].startswith("d6arch-")
    assert body["manifest_sha256"]
    bundle_dir = archive_dir(CERT_RUN_ID, body["bundle_id"])
    manifest = json.loads((bundle_dir / "manifest.json").read_text("utf-8"))
    # §13.3: самохеша в манифесте нет.
    member_paths = {member["path"] for member in manifest["members"]}
    assert "manifest.json" not in member_paths
    assert "metadata.jsonl" in member_paths
    # Члены -- честные sha256 своих байтов.
    for member in manifest["members"]:
        target = bundle_dir / member["path"]
        assert hashlib.sha256(target.read_bytes()).hexdigest() == member["sha256"]
    lines = [
        json.loads(line)
        for line in (bundle_dir / "metadata.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    ]
    entities = [line["entity"] for line in lines]
    for expected in (
        "document", "revision", "rendition", "approval",
        "lifecycle", "retention", "snapshot", "pin",
    ):
        assert expected in entities, expected
    # Оба документа (D01+D02) присутствуют.
    doc_ids = {line["document_id"] for line in lines if line["entity"] == "document"}
    assert {document_a.document_id, document_b.document_id} <= doc_ids
    # Мой снимок -- в entity-линии с МОИМ hash и в objects/.
    snap_lines = [line for line in lines if line["entity"] == "snapshot"]
    assert any(
        line["payload_sha256"] == snapshot_a.payload_sha256 for line in snap_lines
    )
    assert f"objects/{snapshot_a.storage_key.replace('/', '_')}" in member_paths
    # Ответ без путей ФС (§16: только bundle_id/manifest_sha256).
    assert "/" not in json.dumps(body)
    # Failed-форма -- тоже в пакете (честный состав, не маскировка).
    rend_lines = [line for line in lines if line["entity"] == "rendition"]
    assert any(line.get("state") == "failed" for line in rend_lines)


def test_a31_drill_ref_errors_on_valid_checksums(cert_client):
    """Ссылочная целостность НЕ маскируется даже при ВАЛИДНЫХ sha256:
    вычёркивание document-линии metadata.jsonl (с пересчётом member-hash
    в манифесте) даёт ref_errors -- checksums в порядке, refs сломаны."""
    body, _document_a, _document_b, _s1, _s2 = _archive_own_run(cert_client)
    bundle_dir = archive_dir(CERT_RUN_ID, body["bundle_id"])
    metadata_path = bundle_dir / "metadata.jsonl"
    lines = [
        line
        for line in metadata_path.read_text("utf-8").splitlines()
        if line.strip()
    ]
    kept = [
        line for line in lines
        if json.loads(line).get("entity") != "document"
    ]
    metadata_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    # Пересчёт sha256 члена metadata.jsonl в манифесте -- checksums
    # становятся консистентными, ломается только ссылочность.
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    for member in manifest["members"]:
        if member["path"] == "metadata.jsonl":
            member["sha256"] = hashlib.sha256(
                metadata_path.read_bytes()
            ).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    cookie(cert_client)
    resp = cert_client.post(
        f"/v1/documentation/runs/{CERT_RUN_ID}/archive/verify",
        json={"bundle_id": body["bundle_id"]},
    )
    assert resp.status_code == 200
    report = resp.json()
    assert report["ok"] is False
    assert report["missing"] == []
    assert report["mismatched"] == []
    assert report["ref_errors"], "ссылочные ошибки обязаны быть явными"
    assert any(
        error.endswith(":document_missing") for error in report["ref_errors"]
    )


def test_a32_drill_approval_bound_hash_ref_error(cert_client):
    """Подмена bound-hash согласования в metadata (с валидным checksum)
    -- drill фиксирует approval:...:hash_mismatch (AC18/AC07-дух)."""
    body, _document_a, _document_b, _s1, _s2 = _archive_own_run(cert_client)
    bundle_dir = archive_dir(CERT_RUN_ID, body["bundle_id"])
    metadata_path = bundle_dir / "metadata.jsonl"
    raw_lines = metadata_path.read_text("utf-8").splitlines()
    out = []
    for line in raw_lines:
        if not line.strip():
            continue
        entity = json.loads(line)
        if entity.get("entity") == "approval":
            entity["snapshot_payload_sha256"] = "0" * 64
            out.append(json.dumps(entity, ensure_ascii=False, separators=(",", ":")))
        else:
            out.append(line)
    metadata_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    for member in manifest["members"]:
        if member["path"] == "metadata.jsonl":
            member["sha256"] = hashlib.sha256(
                metadata_path.read_bytes()
            ).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    cookie(cert_client)
    resp = cert_client.post(
        f"/v1/documentation/runs/{CERT_RUN_ID}/archive/verify",
        json={"bundle_id": body["bundle_id"]},
    )
    report = resp.json()
    assert report["ok"] is False
    assert any(
        error.endswith(":hash_mismatch") for error in report["ref_errors"]
    ), report["ref_errors"]


def test_a33_verify_unknown_bundle_404(cert_client):
    seed_cert_run()
    _snapshot, document, revision = _seed_own_revision()
    full_publish_flow(cert_client, document, revision)
    cookie(cert_client)
    resp = cert_client.post(
        f"/v1/documentation/runs/{CERT_RUN_ID}/archive/verify",
        json={"bundle_id": "not-a-bundle"},
    )
    assert resp.status_code == 404


def test_a34_drill_ok_on_own_bundle(cert_client):
    body, *_rest = _archive_own_run(cert_client)
    cookie(cert_client)
    resp = cert_client.post(
        f"/v1/documentation/runs/{CERT_RUN_ID}/archive/verify",
        json={"bundle_id": body["bundle_id"]},
    )
    assert resp.status_code == 200
    report = resp.json()
    assert report["ok"] is True
    assert report["missing"] == []
    assert report["mismatched"] == []
    assert report["ref_errors"] == []
    assert report["checked_refs"] > 0
    assert report["duration_ms"] >= 0


# ══ 8. Diff ревизий на своих снимках (§17) ═══════════════════════════


def test_a35_diff_direction_contract_and_validity(cert_client):
    """Контракт направления (естественное чтение; эволюция пина после
    исправления F-D6C1 в DOCLOG-6-CERT-FIX): diff(rev, against=prev) =
    изменения ОТ against К rev. metadata from = against, to = URL-ревизия;
    claims.added = есть в URL-ревизии, нет в against; claims.removed =
    есть в against, нет в URL; validity_changed: from = against,
    to = URL. Пересчётов нет."""
    seed_cert_run()
    document, revision1, revision2, _s1, _s2 = _publish_two_revisions(cert_client)
    cookie(cert_client)
    resp = cert_client.get(
        f"/v1/documentation/revisions/{revision2.revision_id}/diff",
        params={"against": revision1.revision_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["recalculated"] is False
    # from = against (1: ctx-d6cert-1/rev 7), to = URL-ревизия (2).
    assert body["metadata"]["context_id"]["from"] == "ctx-d6cert-1"
    assert body["metadata"]["context_id"]["to"] == "ctx-d6cert-2"
    assert body["metadata"]["data_revision"]["from"] == 7
    assert body["metadata"]["data_revision"]["to"] == 8
    added_texts = [claim["text"] for claim in body["claims"]["added"]]
    removed_texts = [claim["text"] for claim in body["claims"]["removed"]]
    # added = есть в URL (rev2, секция B), нет в against (rev1):
    # новое утверждение B.
    assert any("добавлена проверка остатков" in text for text in added_texts)
    # removed = есть в against (rev1, секции A), нет в URL (rev2):
    # методика D02 и гипотеза-unknown.
    assert any("скользящее окно 12" in text for text in removed_texts)
    # validity_changed: тот же текст, from=against(current) -> to=URL(stale).
    changed = {
        item["text"]: (item["from"], item["to"])
        for item in body["claims"]["validity_changed"]
    }
    assert any(
        "коэффициент детерминации 0.83" in text and pair == ("current", "stale")
        for text, pair in changed.items()
    )


def test_a36_diff_cross_document_honest_code(cert_client):
    seed_cert_run()
    _s1, _doc1, revision1 = _seed_own_revision("D01")
    _s2, _doc2, revision2 = _seed_own_revision("D02")
    cookie(cert_client)
    resp = cert_client.get(
        f"/v1/documentation/revisions/{revision2.revision_id}/diff",
        params={"against": revision1.revision_id},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "diff_across_documents"


def test_a37_diff_against_missing_revision_404(cert_client):
    seed_cert_run()
    _snapshot, _document, revision = _seed_own_revision()
    cookie(cert_client)
    resp = cert_client.get(
        f"/v1/documentation/revisions/{revision.revision_id}/diff",
        params={"against": "rev-d6c-missing"},
    )
    assert resp.status_code == 404


# ══ 9. AC05 tripwire: содержание не меняет науку ═════════════════════


def test_a38_lifecycle_actions_leave_science_state_untouched(cert_client):
    seed_cert_run()
    snapshot, document, revision = _seed_own_revision()
    cookie(cert_client)
    from apps.api.report_snapshot import peek_snapshot_registry
    from apps.api.research_runs import get_research_run_store

    snapshots_before = [
        s.snapshot_id for s in peek_snapshot_registry().list_records(CERT_RUN_ID)
    ]
    payload_before = snapshot.payload_sha256
    events_before = len(
        get_research_run_store().list_events(CERT_RUN_ID)
    )
    full_publish_flow(cert_client, document, revision)
    cert_client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/retract",
        json={"reason": "d6cert-ac05"},
    )
    cert_client.get(
        f"/v1/documentation/revisions/{revision.revision_id}/lifecycle"
    )
    cert_client.get(
        f"/v1/documentation/revisions/{revision.revision_id}/diff",
        params={"against": revision.revision_id},
    )
    snapshots_after = [
        s.snapshot_id for s in peek_snapshot_registry().list_records(CERT_RUN_ID)
    ]
    assert snapshots_after == snapshots_before
    assert snapshot.payload_sha256 == payload_before  # байты не тронуты
    events_after = len(get_research_run_store().list_events(CERT_RUN_ID))
    assert events_after == events_before  # наука не пишет событий


# ══ 10. Дозадачные негативные оракула (заморозка корпуса) ════════════


def test_a39_garbage_decision_422(cert_client):
    """Решение вне approve|reject -- честный 422 invalid_transition
    (валидация тела ПОСЛЕ резолва/прав, но ДО записи)."""
    seed_cert_run()
    _snapshot, _document, revision = _seed_own_revision()
    cookie(cert_client)
    cert_client.post(approve_route(revision.revision_id), json={"action": "request"})
    resp = cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "maybe"},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "invalid_transition"
    state = cert_client.get(
        f"/v1/documentation/revisions/{revision.revision_id}"
    ).json()["revision"]["lifecycle_state"]
    assert state == "ready_for_review"  # мусор не изменил состояние


def test_a40_publish_409_on_tampered_snapshot_hash(cert_client):
    """AC07 (снимок): подмена payload_sha256 снимка ПОСЛЕ согласования
    -- publish 409 approval_not_applicable, состояние не меняется."""
    from apps.api.report_snapshot import peek_snapshot_registry

    seed_cert_run()
    snapshot, _document, revision = _seed_own_revision()
    cookie(cert_client)
    cert_client.post(approve_route(revision.revision_id), json={"action": "request"})
    cert_client.post(
        approve_route(revision.revision_id),
        json={"decision": "approve", "reason": "ok"},
    )
    # Fault-injection: снимок ПЕРЕМОРОЖЕН под тем же id (§11: «старое
    # approval не переносится на новый hash»). Байты и record-hash
    # консистентны (loader T8 проходит), но approval связан СТАРЫЙ hash
    # -- publish обязан ответить approval_not_applicable.
    from apps.api.artifact_store import (
        canonical_json_bytes,
        get_artifact_object_store,
    )

    payload_dict = snapshot.to_dict()
    payload_dict["captured_at"] = "2026-10-23T23:59:00+00:00"
    new_bytes = canonical_json_bytes(payload_dict)
    new_key = get_artifact_object_store().commit_staged(
        get_artifact_object_store().stage_bytes(new_bytes, "application/json")
    )
    registry = peek_snapshot_registry()
    stored = registry._snapshots[snapshot.snapshot_id]
    stored.payload_sha256 = hashlib.sha256(new_bytes).hexdigest()
    stored.size_bytes = len(new_bytes)
    stored.storage_key = new_key
    resp = cert_client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/publish"
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "approval_not_applicable"
    state = cert_client.get(
        f"/v1/documentation/revisions/{revision.revision_id}"
    ).json()["revision"]["lifecycle_state"]
    assert state == "approved"


def test_a41_sweep_purges_exactly_aged_rendition(cert_client, monkeypatch):
    """СВОИ две формы: свежая остаётся ready, состаренная -- purged
    (идентичность purged-цели, не только счётчик)."""
    monkeypatch.setenv("CISSTAT_DOCUMENT_RETENTION_DRAFT_DAYS", "7")
    seed_cert_run()
    snapshot, _document, revision = _seed_own_revision()
    cookie(cert_client)
    from apps.api.document_jobs import DocumentDeliveryService

    registry = DocumentDeliveryService.create_default().registry
    # Свежая (json, готова сразу при постановке) + состаренная (md).
    resp = cert_client.post(
        f"/v1/documentation/revisions/{revision.revision_id}/renditions",
        json={"format": "json"},
    )
    assert resp.status_code == 202
    aged = _aged_rendition(cert_client, snapshot, revision, days=14)
    fresh = next(
        item
        for item in registry.list_renditions(snapshot.snapshot_id)
        if item.format == "json"
    )
    resp = cert_client.post(
        f"/v1/documentation/runs/{CERT_RUN_ID}/retention/sweep"
    )
    assert resp.status_code == 200
    assert resp.json()["report"]["purged_renditions"] == 1
    assert registry.get_rendition(aged.rendition_id).state == "purged"
    assert registry.get_rendition(fresh.rendition_id).state == "ready"


def test_a42_admin_request_basis_full_catalog(cert_client, monkeypatch):
    """ADMIN-key запрашивает согласование: lifecycle-запись несёт честный
    basis=admin_full_catalog (§15.1 -- полный каталог, не scope-вывод)."""
    monkeypatch.setenv(
        "CISSTAT_API_KEYS",
        f"{CERT_ADMIN_KEY}:admin:demo:d6cert-admin-subj:{CERT_ADMIN_KEY}-tenant:",
    )
    seed_cert_run()
    _snapshot, _document, revision = _seed_own_revision()
    cookie(cert_client)
    api_key(cert_client, CERT_ADMIN_KEY)
    resp = cert_client.post(
        approve_route(revision.revision_id), json={"action": "request"}
    )
    assert resp.status_code == 200, resp.text
    history = cert_client.get(
        f"/v1/documentation/revisions/{revision.revision_id}/lifecycle"
    ).json()["records"]
    request_record = next(r for r in history if r["event"] == "approval_requested")
    assert request_record["details"]["basis"] == "admin_full_catalog"
