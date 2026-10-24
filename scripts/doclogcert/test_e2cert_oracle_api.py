# scripts/doclogcert/test_e2cert_oracle_api.py
"""DOCLOG-CERT: API-оракулы сквозной приёмки (TestClient, полный
apps.api.main, свои данные). Покрывают §20: AC01 (пайплайн -> документы,
честные unknown), AC02/AC09 (идемпотентность через HTTP), AC03 (паритет
форматов), AC04 (публикация переживает утрату TTL-сессии), AC05
(read-only tripwire + download-тройка), AC06 (uniform-404 матрица,
scoped-права), AC07 (bound-hash/два лица), AC08 (worker/crash),
AC10 (безопасные ошибки, отсутствие секретов), AC12/AC15 (мониторинг
через HTTP), AC17-дух (состояния queued/ready/failed/403/404/409/410/422),
AC18 (archive/restore drill), §15.1 (журналы/гранты/поддержка)."""
from __future__ import annotations

import io
import json
import zipfile

import pytest

@pytest.fixture(autouse=True)
def _api_keys_env(monkeypatch):
    """Реестр ключей для API-оракулов (конфорт-изоляция удаляет env)."""
    monkeypatch.setenv("CISSTAT_API_KEYS", ADMIN_KEYS_ENV)


from .conftest import (
    ADMIN_KEY,
    ADMIN_KEYS_ENV,
    NOSCOPE_KEY,
    LOGS_KEY,
    RUN_A,
    RUN_B,
    SESSION_A,
    SESSION_B,
    SUBJECT_ADMIN,
    SUBJECT_LOGS,
    SUBJECT_NOSCOPE,
    TENANT_2,
    api_key,
    approval_route,
    build_comparison,
    clear_api_key,
    cookie,
    register_batch,
    run_worker_once,
    science_fingerprint,
    seed_event,
    seed_forecast,
    seed_run,
    subject_of,
)


# ══════════════════════════════════════════════════════════════════════
# AC01: один run -> документы; честные unknown
# ══════════════════════════════════════════════════════════════════════


class TestFullPipelineToDocuments:
    def test_documents_created_for_three_kinds(self, client):
        seed_run()
        seed_event()
        seed_forecast()
        cookie(client, SESSION_A)
        for kind, expected_status in (
            ("D02", 201),
            ("D08", 201),
            ("D12", 201),
        ):
            resp = client.post(
                f"/v1/documentation/runs/{RUN_A}/documents",
                json={"kind": kind},
            )
            assert resp.status_code == expected_status, resp.text
        listed = client.get(f"/v1/documentation/runs/{RUN_A}/documents")
        assert listed.status_code == 200
        documents = listed.json()["documents"]
        kinds = {d["kind_code"] for d in documents}
        assert {"D02", "D08", "D12"} <= kinds

    def test_d12_empty_honest_unknown_claim(self, client):
        seed_run()
        seed_event()
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D12"},
        )
        assert resp.status_code == 201, resp.text
        revision_id = resp.json()["revision"]["revision_id"]
        detail = client.get(f"/v1/documentation/revisions/{revision_id}")
        snapshot_id = detail.json()["revision"]["snapshot_id"]
        from apps.api.snapshot_builder import SnapshotService

        snapshot = SnapshotService.create_default().get_snapshot(
            snapshot_id, subject_of(SESSION_A), session_id=SESSION_A
        )
        section = next(s for s in snapshot.sections if s["code"] == "D12")
        assert section["claims"], "пустая D12 без claims недопустима"
        assert all(
            c["validity"] == "unknown" for c in section["claims"]
        ), "пустая сверка обязана быть честным unknown, не fabricated 0"

    def test_dangling_ref_honest_gap_via_api(self, client):
        seed_run()
        seed_event(result_ref={"artifact_id": "art-e2c-missing-api"})
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        assert resp.status_code == 201
        revision_id = resp.json()["revision"]["revision_id"]
        detail = client.get(f"/v1/documentation/revisions/{revision_id}")
        snapshot_id = detail.json()["revision"]["snapshot_id"]
        from apps.api.snapshot_builder import SnapshotService

        snapshot = SnapshotService.create_default().get_snapshot(
            snapshot_id, subject_of(SESSION_A), session_id=SESSION_A
        )
        section = next(s for s in snapshot.sections if s["code"] == "D02")
        assert any(c["validity"] == "unknown" for c in section["claims"])


# ══════════════════════════════════════════════════════════════════════
# AC09: идемпотентность через HTTP
# ══════════════════════════════════════════════════════════════════════


class TestApiIdempotency:
    def test_same_body_same_key_same_revision(self, client):
        seed_run()
        seed_event()
        cookie(client, SESSION_A)
        body = {"kind": "D02", "idempotency_key": "e2c-doc-key-1"}
        r1 = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents", json=body
        )
        assert r1.status_code == 201
        r2 = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents", json=body
        )
        assert r2.status_code == 200, "повтор -- переиспользование, не 201"
        assert (
            r1.json()["revision"]["revision_id"]
            == r2.json()["revision"]["revision_id"]
        )

    def test_same_key_different_body_409(self, client):
        seed_run()
        seed_event()
        cookie(client, SESSION_A)
        r1 = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02", "idempotency_key": "e2c-doc-key-2"},
        )
        assert r1.status_code == 201
        r2 = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D08", "idempotency_key": "e2c-doc-key-2"},
        )
        assert r2.status_code == 409
        assert r2.json()["detail"]["code"] == "idempotency_conflict"


# ══════════════════════════════════════════════════════════════════════
# AC03: паритет форматов через выдачу
# ══════════════════════════════════════════════════════════════════════


class TestApiCrossFormatParity:
    def test_json_and_md_share_facts_bytes_differ(self, client):
        seed_run()
        seed_event(payload={"name": "e2c-паритет"})
        seed_forecast()
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        revision_id = resp.json()["revision"]["revision_id"]
        contents = {}
        for fmt in ("json", "md"):
            r = client.post(
                f"/v1/documentation/revisions/{revision_id}/renditions",
                json={"format": fmt},
            )
            assert r.status_code == 202, r.text
            rendition_id = r.json()["job"]["rendition"]["rendition_id"]
            got = client.get(
                f"/v1/documentation/renditions/{rendition_id}/content"
            )
            assert got.status_code == 200
            contents[fmt] = got.content
        parsed = json.loads(contents["json"].decode("utf-8"))
        safe = next(
            c["text"]
            for c in parsed["sections"][0]["claims"]
            if "Загружен датасет" in c["text"]
        )
        assert safe in contents["md"].decode("utf-8")
        assert contents["json"] != contents["md"]


# ══════════════════════════════════════════════════════════════════════
# AC05: чтение не меняет науку; download-тройка в audit
# ══════════════════════════════════════════════════════════════════════


class TestReadOnlyScienceTripwire:
    def test_gets_do_not_change_science_state(self, client):
        seed_run()
        seed_event()
        seed_forecast()
        register_batch()
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        revision_id = resp.json()["revision"]["revision_id"]
        rend = client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={"format": "md"},
        ).json()["job"]["rendition"]["rendition_id"]

        before = science_fingerprint(RUN_A)
        assert (
            client.get(f"/v1/documentation/runs/{RUN_A}/documents").status_code
            == 200
        )
        assert (
            client.get(
                f"/v1/documentation/revisions/{revision_id}"
            ).status_code
            == 200
        )
        assert (
            client.get(
                f"/v1/documentation/revisions/{revision_id}/preview"
            ).status_code
            == 200
        )
        assert (
            client.get(
                f"/v1/documentation/renditions/{rend}/content"
            ).status_code
            == 200
        )
        after = science_fingerprint(RUN_A)
        assert before == after, "GET-выдача изменила научное состояние (AC05)"

    def test_download_triple_in_audit(self, client):
        from apps.api.security_audit import audit_records

        seed_run()
        seed_event()
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        revision_id = resp.json()["revision"]["revision_id"]
        rend = client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={"format": "md"},
        ).json()["job"]["rendition"]["rendition_id"]
        client.get(f"/v1/documentation/renditions/{rend}/content")
        actions = [r.get("action") for r in audit_records()]
        assert "download_requested" in actions
        assert "response_stream_started" in actions
        assert "response_stream_finished" in actions


# ══════════════════════════════════════════════════════════════════════
# AC06: uniform-404 матрица + права
# ══════════════════════════════════════════════════════════════════════


class TestUniform404Matrix:
    def _seed_targets(self, client):
        seed_run()
        seed_event()
        artifact = seed_forecast()
        register_batch()
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        assert resp.status_code == 201, resp.text
        document_id = resp.json()["document"]["document_id"]
        revision_id = resp.json()["revision"]["revision_id"]
        rend = client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={"format": "md"},
        ).json()["job"]["rendition"]["rendition_id"]
        cookie(client, SESSION_A)
        client.post(approval_route(revision_id), json={"action": "request"})
        api_key(client, ADMIN_KEY)
        client.post(
            approval_route(revision_id),
            json={"decision": "approve", "reason": "e2c"},
        )
        client.post(
            f"/v1/documentation/revisions/{revision_id}/publish"
        )
        clear_api_key(client)
        batch = register_batch(idempotency_key="e2c-404-batch")
        record = build_comparison(artifact=artifact, batch=batch)
        monitoring_cmp = record.comparison_id
        return document_id, revision_id, rend, monitoring_cmp

    def test_foreign_and_anonymous_get_uniform_404(self, client):
        document_id, revision_id, rend, monitoring_cmp = self._seed_targets(
            client
        )

        paths = [
            ("GET", f"/v1/documentation/runs/{RUN_A}/documents", None),
            ("GET", f"/v1/documentation/documents/{document_id}/revisions", None),
            ("GET", f"/v1/documentation/revisions/{revision_id}", None),
            ("GET", f"/v1/documentation/revisions/{revision_id}/preview", None),
            ("GET", f"/v1/documentation/renditions/{rend}/content", None),
            ("POST", f"/v1/documentation/revisions/{revision_id}/renditions",
             {"format": "md"}),
            ("POST", approval_route(revision_id), {"action": "request"}),
            ("POST", f"/v1/documentation/revisions/{revision_id}/publish", None),
            ("POST", f"/v1/documentation/revisions/{revision_id}/retract",
             {"reason": "e2c"}),
            ("GET", f"/v1/documentation/revisions/{revision_id}/lifecycle", None),
            ("GET", f"/v1/documentation/revisions/{revision_id}/diff?against=drev-e2c-other", None),
            ("POST", f"/v1/documentation/documents/{document_id}/retention",
             {"action": "hold"}),
            ("POST", f"/v1/documentation/runs/{RUN_A}/retention/sweep", None),
            ("POST", f"/v1/documentation/runs/{RUN_A}/archive", None),
            ("GET", f"/v1/documentation/runs/{RUN_A}/monitoring/actuals", None),
            ("GET", f"/v1/documentation/runs/{RUN_A}/monitoring/comparisons", None),
            ("GET",
             f"/v1/documentation/runs/{RUN_A}/monitoring/comparisons/"
             f"{monitoring_cmp}", None),
        ]
        for who, setup in (
            ("foreign", lambda: (clear_api_key(client),
                                 cookie(client, SESSION_B))),
            ("anonymous", lambda: _be_anonymous(client)),
        ):
            setup()
            for method, path, body in paths:
                if method == "GET":
                    resp = client.get(path)
                else:
                    resp = client.post(path, json=body)
                assert resp.status_code == 404, (
                    f"{who} {method} {path}: {resp.status_code} "
                    f"(существование дисклоужается)"
                )

    def test_owner_still_sees_resources(self, client):
        _document_id, revision_id, rend, _cmp = self._seed_targets(client)
        cookie(client, SESSION_A)
        assert (
            client.get(f"/v1/documentation/revisions/{revision_id}").status_code
            == 200
        )
        assert (
            client.get(
                f"/v1/documentation/renditions/{rend}/content"
            ).status_code
            == 200
        )

    def test_scoped_mode_no_pilot_lifecycle_rights(self, client, monkeypatch):
        """§15/D5: в scoped-режиме cookie-суррогат прав согласования
        НЕ получает (права не фантазируются), даже если он владелец."""
        from .conftest import build_snapshot, ensure_revision

        monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "scoped")
        seed_run()
        seed_event()
        snapshot = build_snapshot(kinds=["D02"])
        _document, revision = ensure_revision(snapshot)
        cookie(client, SESSION_A)
        resp = client.post(
            approval_route(revision.revision_id), json={"action": "request"}
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["code"] == "insufficient_scope"


# ══════════════════════════════════════════════════════════════════════
# AC07: согласование, два лица, bound hash
# ══════════════════════════════════════════════════════════════════════


class TestApprovalFlowApi:
    def _revision(self, client):
        seed_run()
        seed_event()
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        return resp.json()["revision"]["revision_id"]

    def test_publish_without_approval_422(self, client):
        revision_id = self._revision(client)
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/revisions/{revision_id}/publish"
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "publish_requires_approval"

    def test_two_person_self_approval_422(self, client, monkeypatch):
        monkeypatch.setenv("CISSTAT_DOCLOG_APPROVAL_POLICY", "two_person")
        revision_id = self._revision(client)
        cookie(client, SESSION_A)
        client.post(approval_route(revision_id), json={"action": "request"})
        resp = client.post(
            approval_route(revision_id),
            json={"decision": "approve", "reason": "сам себя"},
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "self_approval_forbidden"
        state = client.get(
            f"/v1/documentation/revisions/{revision_id}"
        ).json()["revision"]["lifecycle_state"]
        assert state == "ready_for_review"

    def test_second_person_admin_approves_and_publish(self, client):
        revision_id = self._revision(client)
        cookie(client, SESSION_A)
        client.post(approval_route(revision_id), json={"action": "request"})
        api_key(client, ADMIN_KEY)
        resp = client.post(
            approval_route(revision_id),
            json={"decision": "approve", "reason": "второе лицо"},
        )
        assert resp.status_code == 200
        published = client.post(
            f"/v1/documentation/revisions/{revision_id}/publish"
        )
        assert published.status_code == 200
        assert (
            published.json()["revision"]["lifecycle_state"] == "published"
        )

    def test_wrong_expected_hash_409(self, client):
        revision_id = self._revision(client)
        cookie(client, SESSION_A)
        client.post(approval_route(revision_id), json={"action": "request"})
        resp = client.post(
            approval_route(revision_id),
            json={
                "decision": "approve",
                "reason": "e2c",
                "expected_snapshot_sha256": "0" * 64,
            },
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "approval_hash_mismatch"


# ══════════════════════════════════════════════════════════════════════
# AC04: публикация переживает утрату TTL-сессии (через HTTP)
# ══════════════════════════════════════════════════════════════════════


class TestPublishedSurvivesSessionLossApi:
    def test_content_bytes_identical_after_session_reset(self, client):
        from apps.api.session_store import reset_session_store_for_testing

        seed_run()
        seed_event()
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        document_id = resp.json()["document"]["document_id"]
        revision_id = resp.json()["revision"]["revision_id"]
        rend = client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={"format": "md"},
        ).json()["job"]["rendition"]["rendition_id"]
        cookie(client, SESSION_A)
        client.post(approval_route(revision_id), json={"action": "request"})
        api_key(client, ADMIN_KEY)
        client.post(
            approval_route(revision_id),
            json={"decision": "approve", "reason": "e2c"},
        )
        client.post(f"/v1/documentation/revisions/{revision_id}/publish")
        cookie(client, SESSION_A)
        before = client.get(
            f"/v1/documentation/renditions/{rend}/content"
        )
        assert before.status_code == 200
        # TTL-потеря + восстановление той же сессии (детерминированный
        # псевдоним -- restore-континуитет §15.1).
        reset_session_store_for_testing()
        from .conftest import seed_session

        seed_session(SESSION_A)
        cookie(client, SESSION_A)
        after = client.get(f"/v1/documentation/renditions/{rend}/content")
        assert after.status_code == 200
        assert after.content == before.content
        state = client.get(
            f"/v1/documentation/revisions/{revision_id}"
        ).json()["revision"]["lifecycle_state"]
        assert state == "published"
        listed = client.get(
            f"/v1/documentation/documents/{document_id}/revisions"
        )
        assert listed.status_code == 200


# ══════════════════════════════════════════════════════════════════════
# AC08/AC09: очередь тяжёлых форматов, worker, crash
# ══════════════════════════════════════════════════════════════════════


class TestHeavyQueueApi:
    def test_xlsx_queue_worker_ready_idempotent(self, client):
        seed_run()
        seed_event()
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        revision_id = resp.json()["revision"]["revision_id"]
        queued = client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={"format": "xlsx"},
        )
        assert queued.status_code == 202
        job_id = queued.json()["job"]["job_id"]
        assert queued.json()["job"]["state"] == "queued"
        report = run_worker_once()
        assert report["ready"] >= 1
        job = client.get(f"/v1/documentation/jobs/{job_id}").json()["job"]
        assert job["state"] == "ready"
        rendition_id = job["rendition_id"]
        content = client.get(
            f"/v1/documentation/renditions/{rendition_id}/content"
        )
        assert content.status_code == 200
        assert content.content[:2] == b"PK", "XLSX обязан быть OOXML-zip"
        # AC09: повторный клик -- прежний job, без нового задания.
        again = client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={"format": "xlsx"},
        )
        assert again.status_code == 202
        assert again.json()["job"]["job_id"] == job_id

    def test_crash_render_honest_failed_via_api(self, client, monkeypatch):
        from apps.api import document_jobs

        seed_run()
        seed_event()
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        revision_id = resp.json()["revision"]["revision_id"]
        queued = client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={"format": "xlsx"},
        )
        job_id = queued.json()["job"]["job_id"]

        def _boom(*args, **kwargs):
            raise RuntimeError("e2c api crash")

        monkeypatch.setattr(document_jobs, "render_snapshot_xlsx", _boom)
        # attempt постановки = 1; max_attempts=1 -> первая неудача
        # terminal failed (без broken ready refs, AC08).
        from apps.api.document_render_worker import DocumentRenderWorker

        report = DocumentRenderWorker(interval=None, max_attempts=1).run_once()
        assert report["failed"] >= 1
        job = client.get(f"/v1/documentation/jobs/{job_id}").json()["job"]
        assert job["state"] == "failed"
        # Битых ready-refs нет: rendition_id отсутствует/не ready.
        assert not job.get("rendition_id")
        # Повторная постановка разрешена (retry честный), 202.
        retry = client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={"format": "xlsx"},
        )
        assert retry.status_code == 202

    def test_cancel_queued_job_honest(self, client):
        seed_run()
        seed_event()
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        revision_id = resp.json()["revision"]["revision_id"]
        queued = client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={"format": "parquet"},
        )
        assert queued.status_code == 202
        job_id = queued.json()["job"]["job_id"]
        cancelled = client.post(f"/v1/documentation/jobs/{job_id}/cancel")
        assert cancelled.status_code == 200
        job = client.get(f"/v1/documentation/jobs/{job_id}").json()["job"]
        assert job["state"] == "cancelled"


# ══════════════════════════════════════════════════════════════════════
# AC12/AC15: мониторинг через HTTP
# ══════════════════════════════════════════════════════════════════════


class TestMonitoringApi:
    def _setup(self, client):
        seed_run()
        seed_event()
        artifact = seed_forecast()
        cookie(client, SESSION_A)
        return artifact

    def test_actuals_and_comparison_flow(self, client):
        artifact = self._setup(client)
        r1 = client.post(
            f"/v1/documentation/runs/{RUN_A}/monitoring/actuals",
            json={
                "target_name": "e2c_gdp",
                "units": "percent",
                "as_of": "2026-10-15T00:00:00+00:00",
                "source_kind": "manual",
                "values": [
                    {"period": "2026-09-01", "value": 4.8},
                    {"period": "2026-10-01", "value": 6.1},
                ],
            },
        )
        assert r1.status_code == 201, r1.text
        batch_id = r1.json()["batch"]["batch_id"]
        r2 = client.post(
            f"/v1/documentation/runs/{RUN_A}/monitoring/comparisons",
            json={
                "forecast_artifact_id": artifact.artifact_id,
                "actual_batch_id": batch_id,
            },
        )
        assert r2.status_code == 201, r2.text
        comparison = r2.json()["comparison"]
        assert comparison["result"]["alignment"]["excluded_labels"] == [
            "2026-11-01", "2026-12-01"
        ]

    def test_units_mismatch_422_with_own_code(self, client):
        artifact = self._setup(client)
        client.post(
            f"/v1/documentation/runs/{RUN_A}/monitoring/actuals",
            json={
                "target_name": "e2c_gdp",
                "units": "tons",
                "as_of": "2026-10-15T00:00:00+00:00",
                "source_kind": "manual",
                "values": [{"period": "2026-09-01", "value": 1.0}],
            },
        )
        batches = client.get(
            f"/v1/documentation/runs/{RUN_A}/monitoring/actuals"
        ).json()["items"]
        r = client.post(
            f"/v1/documentation/runs/{RUN_A}/monitoring/comparisons",
            json={
                "forecast_artifact_id": artifact.artifact_id,
                "actual_batch_id": batches[0]["batch_id"],
                "forecast_units": "percent",
            },
        )
        assert r.status_code == 422
        assert r.json()["code"] == "monitoring_units_mismatch"

    def test_zero_actual_honest_nulls_via_api(self, client):
        artifact = self._setup(client)
        client.post(
            f"/v1/documentation/runs/{RUN_A}/monitoring/actuals",
            json={
                "target_name": "e2c_gdp",
                "units": "percent",
                "as_of": "2026-10-15T00:00:00+00:00",
                "source_kind": "manual",
                "values": [
                    {"period": "2026-09-01", "value": 0.0},
                    {"period": "2026-10-01", "value": 6.1},
                ],
            },
        )
        batches = client.get(
            f"/v1/documentation/runs/{RUN_A}/monitoring/actuals"
        ).json()["items"]
        r = client.post(
            f"/v1/documentation/runs/{RUN_A}/monitoring/comparisons",
            json={
                "forecast_artifact_id": artifact.artifact_id,
                "actual_batch_id": batches[0]["batch_id"],
            },
        )
        assert r.status_code == 201
        result = r.json()["comparison"]["result"]
        zero = next(
            p for p in result["pairs"] if p["date"] == "2026-09-01"
        )
        assert zero["ape"] is None
        assert zero["ape_undefined_reason"] == "actual_zero"
        assert result["aggregates"]["mape"] is None

    def test_threshold_fact_and_decision_separate(self, client):
        artifact = self._setup(client)
        client.post(
            f"/v1/documentation/runs/{RUN_A}/monitoring/actuals",
            json={
                "target_name": "e2c_gdp",
                "units": "percent",
                "as_of": "2026-10-15T00:00:00+00:00",
                "source_kind": "manual",
                "values": [
                    {"period": "2026-09-01", "value": 9.9},
                    {"period": "2026-10-01", "value": 9.9},
                ],
            },
        )
        batches = client.get(
            f"/v1/documentation/runs/{RUN_A}/monitoring/actuals"
        ).json()["items"]
        r = client.post(
            f"/v1/documentation/runs/{RUN_A}/monitoring/comparisons",
            json={
                "forecast_artifact_id": artifact.artifact_id,
                "actual_batch_id": batches[0]["batch_id"],
                "threshold": {"metric": "mae", "operator": ">", "value": 0.1},
            },
        )
        comparison_id = r.json()["comparison"]["comparison_id"]
        assert (
            r.json()["comparison"]["result"]["threshold"]["status"]
            == "exceeded"
        )
        assert r.json()["comparison"]["result"]["decision_action"] is None
        no_rationale = client.post(
            f"/v1/documentation/runs/{RUN_A}/monitoring/comparisons/"
            f"{comparison_id}/decisions",
            json={"action": "investigate"},
        )
        assert no_rationale.status_code == 422
        decision = client.post(
            f"/v1/documentation/runs/{RUN_A}/monitoring/comparisons/"
            f"{comparison_id}/decisions",
            json={
                "action": "investigate",
                "rationale": "e2c: порог превышен, изучаем",
            },
        )
        assert decision.status_code == 201

    def test_late_actual_new_comparison_old_frozen(self, client):
        artifact = self._setup(client)
        b1 = client.post(
            f"/v1/documentation/runs/{RUN_A}/monitoring/actuals",
            json={
                "target_name": "e2c_gdp",
                "units": "percent",
                "as_of": "2026-10-15T00:00:00+00:00",
                "source_kind": "manual",
                "idempotency_key": "e2c-api-b1",
                "values": [{"period": "2026-09-01", "value": 4.8}],
            },
        ).json()["batch"]["batch_id"]
        c1 = client.post(
            f"/v1/documentation/runs/{RUN_A}/monitoring/comparisons",
            json={
                "forecast_artifact_id": artifact.artifact_id,
                "actual_batch_id": b1,
                "idempotency_key": "e2c-api-c1",
            },
        ).json()["comparison"]
        client.post(
            f"/v1/documentation/runs/{RUN_A}/monitoring/actuals",
            json={
                "target_name": "e2c_gdp",
                "units": "percent",
                "as_of": "2026-11-15T00:00:00+00:00",
                "source_kind": "manual",
                "idempotency_key": "e2c-api-b2",
                "values": [{"period": "2026-09-01", "value": 9.9}],
            },
        )
        batches = client.get(
            f"/v1/documentation/runs/{RUN_A}/monitoring/actuals"
        ).json()["items"]
        b2 = next(
            b["batch_id"] for b in batches if b["batch_id"] != b1
        )
        client.post(
            f"/v1/documentation/runs/{RUN_A}/monitoring/comparisons",
            json={
                "forecast_artifact_id": artifact.artifact_id,
                "actual_batch_id": b2,
                "idempotency_key": "e2c-api-c2",
            },
        )
        reread = client.get(
            f"/v1/documentation/runs/{RUN_A}/monitoring/comparisons/{c1['comparison_id']}"
        ).json()
        assert reread["result"]["pairs"] == c1["result"]["pairs"]


# ══════════════════════════════════════════════════════════════════════
# §15.1/AC06/AC10: журналы, гранты, диагностический пакет
# ══════════════════════════════════════════════════════════════════════


class TestLogsApiMatrix:
    def test_admin_reads_all_streams_and_self_journaling(self, client):
        api_key(client, ADMIN_KEY)
        from apps.api.security_audit import audit_records

        assert client.get("/v1/logs/audit").status_code == 200
        assert client.get("/v1/logs/delivery").status_code == 200
        accessed_before = len(
            [
                a
                for a in audit_records()
                if a.get("action") == "audit_log_accessed"
            ]
        )
        assert client.get("/v1/logs/telemetry").status_code == 200
        accessed_after = [
            a
            for a in audit_records()
            if a.get("action") == "audit_log_accessed"
        ]
        # Саможурналирование: РОВНО одна запись на операцию (§14.1),
        # без рекурсии.
        assert len(accessed_after) - accessed_before == 1

    def test_scope_key_narrowing_and_403(self, client):
        seed_run()
        seed_event()
        # Свои записи телеметрии, чтобы поток был непустым.
        from apps.api.telemetry import emit

        emit("e2cert.stream_probe", "info", message_template="e2c probe")
        api_key(client, LOGS_KEY)
        r_telemetry = client.get("/v1/logs/telemetry")
        assert r_telemetry.status_code == 200
        meta = r_telemetry.json().get("meta", {})
        scope_meta = meta.get("effective_scope")
        # Скоуп-ключ без грантов -- unrestricted-поток (границы задают
        # гранты, не скоупы -- §15.1); сужение проверяется run-грантом.
        assert scope_meta == "unrestricted"
        r_audit = client.get("/v1/logs/audit")
        assert r_audit.status_code == 200  # audit.read тоже выдан
        # Ключ вообще без scopes -- 403 (uniform, дисклоужения нет).
        api_key(client, NOSCOPE_KEY)
        denied = client.get("/v1/logs/telemetry")
        assert denied.status_code == 403
        assert denied.json()["code"] == "logs_access_denied"

    def test_run_scoped_grant_403_outside_boundary(self, client):
        """DOCLOG-7 (§14.2): явный фильтр ВНЕ границы run-гранта --
        403 (не пустой список); внутри границы -- честное сужение."""
        seed_run()
        seed_run(RUN_B, SESSION_B)
        seed_event(RUN_B)
        api_key(client, ADMIN_KEY)
        created = client.post(
            "/v1/logs/grants",
            json={
                "ticket": "E2C-SCOPED-TICKET",
                "purpose": "run-scoped поддержка",
                "subject_id": SUBJECT_NOSCOPE,
                "tenant_id": TENANT_2,
                "run_id": RUN_B,
                "scopes": ["logs.read"],
                "ttl_hours": 2.0,
            },
        )
        assert created.status_code == 201, created.text
        api_key(client, NOSCOPE_KEY)
        inside = client.get(
            "/v1/logs/telemetry", params={"run_id": RUN_B}
        )
        assert inside.status_code == 200
        outside = client.get(
            "/v1/logs/telemetry", params={"run_id": RUN_A}
        )
        assert outside.status_code == 403

    def test_grant_flow_via_api(self, client):
        api_key(client, ADMIN_KEY)
        created = client.post(
            "/v1/logs/grants",
            json={
                "ticket": "E2C-API-TICKET",
                "purpose": "поддержка: сквозная приёмка",
                "subject_id": SUBJECT_NOSCOPE,
                "tenant_id": TENANT_2,
                "scopes": ["logs.read", "audit.read", "logs.export"],
                "ttl_hours": 4.0,
            },
        )
        assert created.status_code == 201, created.text
        grant_id = created.json()["grant_id"]
        # Субъект гранта получает доступ.
        api_key(client, NOSCOPE_KEY)
        assert client.get("/v1/logs/telemetry").status_code == 200
        # Отзыв закрывает доступ.
        api_key(client, ADMIN_KEY)
        revoked = client.post(
            f"/v1/logs/grants/{grant_id}/revoke",
            json={"reason": "e2c: инцидент закрыт"},
        )
        assert revoked.status_code == 200
        api_key(client, NOSCOPE_KEY)
        assert client.get("/v1/logs/telemetry").status_code == 403

    def test_diagnostic_bundle_independent_reader_no_secrets(
        self, client, monkeypatch
    ):
        from apps.api.security_audit import audit_records

        seed_run()
        seed_event()
        api_key(client, ADMIN_KEY)
        client.get("/v1/logs/telemetry")  # свои записи audit_log_accessed
        r = client.post(
            "/v1/logs/export", json={"streams": ["telemetry", "audit"]}
        )
        assert r.status_code == 200, r.text
        raw = r.content
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = archive.namelist()
            assert "manifest.json" in names
            manifest = json.loads(archive.read("manifest.json"))
            excluded = " ".join(
                str(item) for item in manifest.get("excluded", [])
            )
            assert "env" in excluded.lower()
            assert "cookie" in excluded.lower()
            for name in names:
                if name.endswith(".jsonl"):
                    text = archive.read(name).decode("utf-8")
                    assert "e2cert-SENTINEL" not in text
                    assert SESSION_A not in text
                    assert ADMIN_KEY not in text
        # Независимый процесс чтения: пакет не требует текущей сессии
        # (никаких cookie в запросе -- только админ-ключ, AC19).

    def test_bundle_export_denied_without_scope(self, client):
        api_key(client, NOSCOPE_KEY)
        r = client.post("/v1/logs/export", json={})
        assert r.status_code == 403
        assert r.json()["code"] == "logs_access_denied"

    def test_bundle_export_requires_export_scope_despite_read(self, client):
        """§15.1: logs.read/audit.read дают ЧТЕНИЕ потоков, но экспорт
        пакета требует logs.export (гвард сборки, не только пер-стрим)."""
        from .conftest import NOEXPORT_KEY

        api_key(client, NOEXPORT_KEY)
        assert client.get("/v1/logs/telemetry").status_code == 200
        assert client.get("/v1/logs/audit").status_code == 200
        r = client.post("/v1/logs/export", json={"streams": ["telemetry"]})
        assert r.status_code == 403
        assert r.json()["code"] == "logs_access_denied"


def _be_anonymous(client) -> None:
    """Аноним: ни ключа, ни cookie."""
    clear_api_key(client)
    client.cookies.clear()


# ══════════════════════════════════════════════════════════════════════
# DOCLOG-9: профили организации через HTTP
# ══════════════════════════════════════════════════════════════════════


class TestOrgProfilesApi:
    def test_create_requires_policy_admin(self, client):
        seed_run()
        api_key(client, NOSCOPE_KEY)
        denied = client.post(
            "/v1/documentation/org-profiles",
            json={
                "name": "e2c-без-прав",
                "version_no": 1,
                "format": "pdfa",
            },
        )
        assert denied.status_code == 403
        api_key(client, ADMIN_KEY)
        ok = client.post(
            "/v1/documentation/org-profiles",
            json={
                "name": "e2c-корпоративный-api",
                "version_no": 1,
                "format": "pdfa",
                "title_prefix": "[E2C]",
                "footer_text": "Служебный документ",
                "organization": "E2C Org",
            },
        )
        assert ok.status_code == 201, ok.text
        profile_id = ok.json()["profile"]["profile_id"]
        # Идемпотентный retire.
        r1 = client.post(
            f"/v1/documentation/org-profiles/{profile_id}/retire"
        )
        assert r1.status_code == 200
        r2 = client.post(
            f"/v1/documentation/org-profiles/{profile_id}/retire"
        )
        assert r2.status_code == 200

    def test_pdfa_rendition_requires_profile(self, client):
        seed_run()
        seed_event()
        seed_forecast()
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        revision_id = resp.json()["revision"]["revision_id"]
        no_profile = client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={"format": "pdfa"},
        )
        assert no_profile.status_code == 422
        assert no_profile.json()["detail"]["code"] == "org_profile_invalid"

    def test_profile_confirmed_by_validator_not_filename(self, client):
        """Критерий §19: выпуск по профилю проходит структурный
        валидатор; запись валидации пишется; имя файла ничего не
        подтверждает."""
        seed_run()
        seed_event()
        seed_forecast()
        api_key(client, ADMIN_KEY)
        profile = client.post(
            "/v1/documentation/org-profiles",
            json={
                "name": "e2c-валидатор-api",
                "version_no": 1,
                "format": "pdfa",
            },
        ).json()["profile"]["profile_id"]
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        revision_id = resp.json()["revision"]["revision_id"]
        queued = client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={
                "format": "pdfa",
                "org_profile_id": profile,
            },
        )
        assert queued.status_code == 202, queued.text
        job_id = queued.json()["job"]["job_id"]
        run_worker_once()
        job = client.get(f"/v1/documentation/jobs/{job_id}").json()["job"]
        assert job["state"] == "ready", job
        validations = client.get(
            f"/v1/documentation/renditions/{job['rendition_id']}/validations"
        )
        assert validations.status_code == 200
        records = validations.json().get("validations", [])
        assert any(
            rec.get("validator") == "pdfa-structural/1"
            and rec.get("result") == "passed"
            for rec in records
        ), "валидатор обязан подтвердить выпуск (не имя файла)"
        # Чужой rendition -- uniform 404.
        clear_api_key(client)
        api_key(client, ADMIN_KEY)
        foreign = client.get(
            "/v1/documentation/renditions/org-e2c-foreign/validations"
        )
        assert foreign.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# AC18: архив и restore drill
# ══════════════════════════════════════════════════════════════════════


class TestArchiveRestoreDrill:
    def test_archive_and_verify_ok(self, client):
        seed_run()
        seed_event()
        seed_forecast()
        cookie(client, SESSION_A)
        client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        archive = client.post(f"/v1/documentation/runs/{RUN_A}/archive")
        assert archive.status_code == 200, archive.text
        bundle_id = archive.json()["bundle_id"]
        verify = client.post(
            f"/v1/documentation/runs/{RUN_A}/archive/verify",
            json={"bundle_id": bundle_id},
        )
        assert verify.status_code == 200, verify.text
        report = verify.json()
        assert report.get("ok") is True
        assert not report.get("missing")
        assert not report.get("mismatched")

    def test_missing_member_not_masked(self, client):
        from apps.api.document_lifecycle import _data_root

        seed_run()
        seed_event()
        seed_forecast()
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        revision_id = resp.json()["revision"]["revision_id"]
        client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={"format": "md"},
        )
        archive = client.post(f"/v1/documentation/runs/{RUN_A}/archive")
        bundle_id = archive.json()["bundle_id"]
        bundle_dir = _data_root() / "archive" / RUN_A / bundle_id
        manifest = json.loads((bundle_dir / "manifest.json").read_bytes())
        members = manifest.get("members", [])
        assert members, "пустой манифест архива"
        # Честная симуляция утраты объекта: удаляем член пакета с диска.
        victim = bundle_dir / members[0]["path"]
        if victim.exists():
            victim.unlink()
        verify = client.post(
            f"/v1/documentation/runs/{RUN_A}/archive/verify",
            json={"bundle_id": bundle_id},
        )
        report = verify.json()
        assert report.get("ok") is False or report.get("missing"), report


# ══════════════════════════════════════════════════════════════════════
# AC10: безопасные ошибки, health без секретов; §16: retention через HTTP
# ══════════════════════════════════════════════════════════════════════


class TestSafeErrorsAndRetention:
    def test_error_bodies_flat_no_secrets(self, client):
        seed_run()
        seed_event()
        cookie(client, SESSION_B)  # чужой субъект
        r404 = client.get(f"/v1/documentation/revisions/rs-e2c-missing")
        assert r404.status_code == 404
        body = json.dumps(r404.json(), ensure_ascii=False)
        assert "Traceback" not in body
        assert "e2cert-SENTINEL" not in body
        api_key(client, NOSCOPE_KEY)
        r403 = client.get("/v1/logs/telemetry")
        assert r403.status_code == 403
        payload = r403.json()
        assert set(payload) >= {"code", "message"}
        assert "Traceback" not in json.dumps(payload)

    def test_health_ops_no_sentinel(self, client, monkeypatch):
        r = client.get("/health/ops")
        assert r.status_code == 200
        body = json.dumps(r.json(), ensure_ascii=False, default=str)
        assert "e2cert-SENTINEL" not in body
        assert SESSION_A not in body

    def test_retention_hold_and_sweep_via_api(self, client):
        seed_run()
        seed_event()
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        document_id = resp.json()["document"]["document_id"]
        revision_id = resp.json()["revision"]["revision_id"]
        client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={"format": "md"},
        )
        hold = client.post(
            f"/v1/documentation/documents/{document_id}/retention",
            json={"action": "hold", "reason": "e2c hold"},
        )
        assert hold.status_code == 200
        sweep = client.post(
            f"/v1/documentation/runs/{RUN_A}/retention/sweep"
        )
        assert sweep.status_code == 200
        report = sweep.json()["report"]
        assert report["skipped_hold_documents"] >= 1
        assert report["purged_renditions"] == 0

    def test_purged_content_410_via_api(self, client):
        from dataclasses import replace as dc_replace
        from datetime import datetime, timedelta, timezone

        from apps.api.document_jobs import DocumentDeliveryService

        seed_run()
        seed_event()
        cookie(client, SESSION_A)
        resp = client.post(
            f"/v1/documentation/runs/{RUN_A}/documents",
            json={"kind": "D02"},
        )
        revision_id = resp.json()["revision"]["revision_id"]
        rend = client.post(
            f"/v1/documentation/revisions/{revision_id}/renditions",
            json={"format": "md"},
        ).json()["job"]["rendition"]["rendition_id"]
        # renditions P0 синхронны: rendition уже ready; состарим её и
        # снимем hold (его нет) -> sweep очищает устаревший draft.
        delivery = DocumentDeliveryService.create_default()
        record = delivery.registry.get_rendition(rend)
        past = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).isoformat()
        delivery.registry.update_rendition(dc_replace(record, created_at=past))
        sweep = client.post(
            f"/v1/documentation/runs/{RUN_A}/retention/sweep"
        )
        assert sweep.status_code == 200
        assert sweep.json()["report"]["purged_renditions"] >= 1
        content = client.get(
            f"/v1/documentation/renditions/{rend}/content"
        )
        assert content.status_code == 410
        assert content.json()["detail"]["code"] == "purged_artifact"
