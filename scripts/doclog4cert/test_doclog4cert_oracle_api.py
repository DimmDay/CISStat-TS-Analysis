# scripts/doclog4cert/test_doclog4cert_oracle_api.py
# DOCLOG-4-CERT: HTTP-оракулы сертификатора на СВОИХ данных.
# Матрица авторизации (AC06/R09) на ВСЕХ маршрутах; N3-гейт (dependency
# manifest только в авторизованном GET /revisions); AC05 (наука не
# трогается, независимый фингерпринт); AC09 (идемпотентность/409);
# job-контракт §11; аудит §14.1. РАЗДЕЛ RED -- оракулы-ДОКАЗАТЕЛЬСТВА
# находок F-D4C2/F-D4C3: кодируют спеку (AC11 fail-closed; факт решения
# в §14.1) и ОБЯЗАНЫ падать на дереве с дефектом.
from __future__ import annotations

import json

import pytest

from conftest import (
    ADMIN_KEY, CTX_ALPHA, CTX_BETA, RUN_ID, RUN_ID_B, RUN_MISSING,
    SENTINEL_PLAIN, SESSION_B, SESSION_FOREIGN, SESSION_ID,
    audit_records, cookie_for, foreign_subject, science_state,
    seed_snapshot, owner_subject,
)

BASE = "/v1/documentation"


# ── Хелперы корпуса ──────────────────────────────────────────────────


def _make_document(client, run_id: str = RUN_ID, kind: str = "D01"):
    resp = client.post(f"{BASE}/runs/{run_id}/documents", json={"kind": kind})
    assert resp.status_code in (200, 201), resp.text
    payload = resp.json()
    return payload["document"], payload["revision"]


def _make_rendition(client, revision_id: str, fmt: str = "md"):
    resp = client.post(
        f"{BASE}/revisions/{revision_id}/renditions", json={"format": fmt}
    )
    assert resp.status_code == 202, resp.text
    payload = resp.json()
    return payload["job"], payload["job"]["rendition"]


def _full_setup(client, run_id: str = RUN_ID):
    """Снимок -> документ -> рендиция на СВОИХ данных; возвращает ID."""
    seed_snapshot(run_id=run_id)
    cookie_for(client, SESSION_ID)
    document, revision = _make_document(client, run_id)
    job, rendition = _make_rendition(client, revision["revision_id"])
    return document["document_id"], revision["revision_id"], job, rendition


# ══════════════════════════════════════════════════════════════════════
# 1. Матрица авторизации (AC06/R09) -- все маршруты
# ══════════════════════════════════════════════════════════════════════


class TestOrcAuthMatrix:
    def test_owner_full_path_green(self, orc_client):
        doc_id, rev_id, job, rendition = _full_setup(orc_client)
        assert (
            orc_client.get(f"{BASE}/runs/{RUN_ID}/documents").status_code == 200
        )
        assert (
            orc_client.get(f"{BASE}/documents/{doc_id}/revisions").status_code
            == 200
        )
        assert orc_client.get(f"{BASE}/revisions/{rev_id}").status_code == 200
        assert (
            orc_client.get(f"{BASE}/revisions/{rev_id}/preview").status_code == 200
        )
        assert (
            orc_client.get(
                f"{BASE}/renditions/{rendition['rendition_id']}/content"
            ).status_code
            == 200
        )
        assert orc_client.get(f"{BASE}/jobs/{job['job_id']}").status_code == 200

    def test_foreign_uniform_404_on_every_route(self, orc_client):
        doc_id, rev_id, job, rendition = _full_setup(orc_client)
        # Чужая сессия: знание ID не даёт права (R09/T15).
        cookie_for(orc_client, SESSION_FOREIGN)
        foreign_responses = {
            "list": orc_client.get(f"{BASE}/runs/{RUN_ID}/documents"),
            "create": orc_client.post(
                f"{BASE}/runs/{RUN_ID}/documents", json={"kind": "D01"}
            ),
            "revisions": orc_client.get(
                f"{BASE}/documents/{doc_id}/revisions"
            ),
            "revision": orc_client.get(f"{BASE}/revisions/{rev_id}"),
            "preview": orc_client.get(f"{BASE}/revisions/{rev_id}/preview"),
            "renditions": orc_client.post(
                f"{BASE}/revisions/{rev_id}/renditions", json={"format": "md"}
            ),
            "job": orc_client.get(f"{BASE}/jobs/{job['job_id']}"),
            "cancel": orc_client.post(f"{BASE}/jobs/{job['job_id']}/cancel"),
            "content": orc_client.get(
                f"{BASE}/renditions/{rendition['rendition_id']}/content"
            ),
        }
        for name, resp in foreign_responses.items():
            assert resp.status_code == 404, (name, resp.status_code, resp.text)

    def test_anonymous_uniform_404_on_every_route(self, orc_client):
        _doc_id, rev_id, job, rendition = _full_setup(orc_client)
        orc_client.cookies.delete("cisstat_session_id")
        anonymous_responses = {
            "list": orc_client.get(f"{BASE}/runs/{RUN_ID}/documents"),
            "revision": orc_client.get(f"{BASE}/revisions/{rev_id}"),
            "preview": orc_client.get(f"{BASE}/revisions/{rev_id}/preview"),
            "content": orc_client.get(
                f"{BASE}/renditions/{rendition['rendition_id']}/content"
            ),
            "job": orc_client.get(f"{BASE}/jobs/{job['job_id']}"),
        }
        for name, resp in anonymous_responses.items():
            assert resp.status_code == 404, (name, resp.status_code)

    def test_admin_allowed_read_path(self, orc_admin_client):
        _doc_id, _rev_id, _job, _rendition = _full_setup(orc_admin_client)
        resp = orc_admin_client.get(f"{BASE}/runs/{RUN_ID}/documents")
        assert resp.status_code == 200
        assert resp.json()["documents"]

    def test_missing_ids_uniform_404(self, orc_client):
        cookie_for(orc_client, SESSION_ID)
        ghost = "drev-" + "0" * 32
        ghost_doc = "doc-" + "0" * 32
        ghost_job = "djob-" + "0" * 32
        ghost_rend = "drend-" + "0" * 32
        assert (
            orc_client.get(f"{BASE}/revisions/{ghost}").status_code == 404
        )
        assert (
            orc_client.get(f"{BASE}/documents/{ghost_doc}/revisions").status_code
            == 404
        )
        assert orc_client.get(f"{BASE}/jobs/{ghost_job}").status_code == 404
        assert (
            orc_client.get(f"{BASE}/renditions/{ghost_rend}/content").status_code
            == 404
        )
        assert (
            orc_client.get(f"{BASE}/runs/{RUN_MISSING}/documents").status_code
            == 404
        )

    def test_uniform_body_shape_no_existence_leak(self, orc_client):
        # 404 «нет» и 404 «чужой» -- одинаковое тело (существование не
        # дисклоужается, §15/R09).
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        rev_id = revision["revision_id"]
        foreign_body_probe = "d4cert-uniform-probe"
        cookie_for(orc_client, foreign_body_probe)
        foreign_body = orc_client.get(f"{BASE}/revisions/{rev_id}").json()
        missing_body = orc_client.get(
            f"{BASE}/revisions/drev-{'f' * 32}"
        ).json()
        assert foreign_body == missing_body


# ══════════════════════════════════════════════════════════════════════
# 2. N3-гейт: dependency manifest только в авторизованном GET /revisions
# ══════════════════════════════════════════════════════════════════════


class TestOrcN3Gate:
    def test_dependencies_only_in_authorized_revision_get(self, orc_client):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        rev_id = revision["revision_id"]

        # 1. Авторизованный GET /revisions/{id} содержит snapshot-манифест.
        detail = orc_client.get(f"{BASE}/revisions/{rev_id}").json()
        assert "snapshot" in detail
        snapshot_payload = detail["snapshot"]
        assert "dependencies" in snapshot_payload

        # 2. Остальные маршруты не отдают dependency-манифест.
        list_payload = orc_client.get(f"{BASE}/runs/{RUN_ID}/documents").json()
        assert "dependencies" not in json.dumps(list_payload)
        revs_payload = orc_client.get(
            f"{BASE}/documents/{detail['document']['document_id']}/revisions"
        ).json()
        assert "dependencies" not in json.dumps(revs_payload)

        # 3. Чужому GET /revisions/{id} не отдаёт ничего (uniform 404).
        cookie_for(orc_client, SESSION_FOREIGN)
        resp = orc_client.get(f"{BASE}/revisions/{rev_id}")
        assert resp.status_code == 404
        assert "dependencies" not in resp.text


# ══════════════════════════════════════════════════════════════════════
# 3. AC05: чтение не меняет научное состояние (свой фингерпринт)
# ══════════════════════════════════════════════════════════════════════


class TestOrcNoScienceMutation:
    def test_reads_keep_science_state_frozen(self, orc_client):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        before = science_state(RUN_ID)
        _document, revision = _make_document(orc_client)
        rev_id = revision["revision_id"]

        orc_client.get(f"{BASE}/runs/{RUN_ID}/documents")
        orc_client.get(f"{BASE}/revisions/{rev_id}")
        orc_client.get(f"{BASE}/revisions/{rev_id}/preview")
        job, rendition = _make_rendition(orc_client, rev_id, "md")
        orc_client.get(
            f"{BASE}/renditions/{rendition['rendition_id']}/content"
        )
        orc_client.get(f"{BASE}/jobs/{job['job_id']}")

        after = science_state(RUN_ID)
        # POST создал ТОЛЬКО документный адаптер поверх существующего
        # снимка: научные поверхности (run/события/снимки/пины) байт-в-байт.
        assert after["run"] == before["run"]
        assert after["event_ids"] == before["event_ids"]
        assert after["event_types"] == before["event_types"]
        assert after["snapshots"] == before["snapshots"]
        assert after["pins"] == before["pins"]

    def test_list_does_not_create_documents_or_snapshots(self, orc_client):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        before = science_state(RUN_ID)
        for _ in range(3):
            resp = orc_client.get(f"{BASE}/runs/{RUN_ID}/documents")
            assert resp.status_code == 200
        assert science_state(RUN_ID) == before

    def test_denied_reads_change_nothing(self, orc_client):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        before = science_state(RUN_ID)
        cookie_for(orc_client, SESSION_FOREIGN)
        orc_client.get(f"{BASE}/revisions/{revision['revision_id']}")
        orc_client.get(f"{BASE}/revisions/{revision['revision_id']}/preview")
        orc_client.post(
            f"{BASE}/revisions/{revision['revision_id']}/renditions",
            json={"format": "md"},
        )
        assert science_state(RUN_ID) == before


# ══════════════════════════════════════════════════════════════════════
# 4. AC09/§10.3: идемпотентность выдачи и черновика; 409-семантика
# ══════════════════════════════════════════════════════════════════════


class TestOrcIdempotency:
    def test_same_format_returns_same_job_and_rendition(self, orc_client):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        rev_id = revision["revision_id"]
        job1, rend1 = _make_rendition(orc_client, rev_id, "md")
        job2, rend2 = _make_rendition(orc_client, rev_id, "md")
        assert job1["job_id"] == job2["job_id"]
        assert rend1["rendition_id"] == rend2["rendition_id"]
        assert rend1["content_sha256"] == rend2["content_sha256"]

    def test_different_format_separate_rendition(self, orc_client):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        rev_id = revision["revision_id"]
        job_md, rend_md = _make_rendition(orc_client, rev_id, "md")
        job_csv, rend_csv = _make_rendition(orc_client, rev_id, "csv")
        assert rend_md["rendition_id"] != rend_csv["rendition_id"]
        assert job_md["job_id"] != job_csv["job_id"]

    def test_draft_post_without_refresh_reuses_revision(self, orc_client):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision1 = _make_document(orc_client, RUN_ID)
        _document2, revision2 = _make_document(orc_client, RUN_ID)
        assert revision1["revision_id"] == revision2["revision_id"]

    def test_refresh_same_state_idempotent_snapshot(self, orc_client):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        resp1 = orc_client.post(
            f"{BASE}/runs/{RUN_ID}/documents",
            json={"kind": "D01", "refresh": True},
        )
        resp2 = orc_client.post(
            f"{BASE}/runs/{RUN_ID}/documents",
            json={"kind": "D01", "refresh": True},
        )
        assert resp1.status_code in (200, 201)
        assert resp2.status_code in (200, 201)
        # Сборщик DOCLOG-2: неизменное состояние + auto-ключ => тот же
        # снимок (честная идемпотентность «Создать черновик»).
        assert (
            resp1.json()["revision"]["snapshot_id"]
            == resp2.json()["revision"]["snapshot_id"]
        )

    def test_idempotency_key_other_body_conflict_409_builder_path(
        self, orc_client
    ):
        # AC09 («другое тело -> 409») в builder-пути (refresh=true:
        # ключ регистрируется сборщиком DOCLOG-2).
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        first = orc_client.post(
            f"{BASE}/runs/{RUN_ID}/documents",
            json={"kind": "D01", "refresh": True,
                  "idempotency_key": "d4c-key-88"},
        )
        assert first.status_code in (200, 201)
        second = orc_client.post(
            f"{BASE}/runs/{RUN_ID}/documents",
            json={"kind": "D02", "refresh": True,
                  "idempotency_key": "d4c-key-88"},
        )
        assert second.status_code == 409

    def test_cancel_idempotent_terminal_states_respected(self, orc_client):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        job, _rendition = _make_rendition(orc_client, revision["revision_id"])
        # Job уже ready (P0 инлайн): cancel -- no-op, результат жив.
        first = orc_client.post(f"{BASE}/jobs/{job['job_id']}/cancel")
        second = orc_client.post(f"{BASE}/jobs/{job['job_id']}/cancel")
        assert first.status_code == 200
        assert second.status_code == 200
        state = orc_client.get(f"{BASE}/jobs/{job['job_id']}").json()["job"]["state"]
        assert state == "ready"


# ══════════════════════════════════════════════════════════════════════
# 5. Job-контракт §11: состояния/отказы/негативные форматы
# ══════════════════════════════════════════════════════════════════════


class TestOrcJobContract:
    def test_p0_job_renders_ready_with_integrity(self, orc_client):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        job, rendition = _make_rendition(orc_client, revision["revision_id"], "json")
        assert job["state"] == "ready"
        assert rendition["state"] == "ready"
        assert rendition["size_bytes"] > 0
        assert rendition["content_sha256"]
        assert rendition["media_type"] == "application/json"

    def test_unsupported_format_400_no_job(self, orc_client):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        rev_id = revision["revision_id"]
        from apps.api.document_jobs import get_document_registry

        jobs_before = len(get_document_registry().list_jobs(RUN_ID))
        for fmt in ("pdf", "xlsx", "parquet", "zip", "svg"):
            resp = orc_client.post(
                f"{BASE}/revisions/{rev_id}/renditions", json={"format": fmt}
            )
            assert resp.status_code == 400, (fmt, resp.status_code)
            assert resp.json()["detail"]["code"] == "unsupported_format"
        assert len(get_document_registry().list_jobs(RUN_ID)) == jobs_before

    def test_renderer_failure_job_failed_science_untouched(
        self, orc_client, monkeypatch
    ):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        rev_id = revision["revision_id"]
        before = science_state(RUN_ID)

        from apps.api import document_jobs

        def _boom(_snapshot):
            raise RuntimeError("d4c-render-boom")

        monkeypatch.setattr(document_jobs, "render_snapshot_html", _boom)
        resp = orc_client.post(
            f"{BASE}/revisions/{rev_id}/renditions", json={"format": "html"}
        )
        assert resp.status_code == 202
        job = resp.json()["job"]
        assert job["state"] == "failed"
        assert job["error_code"] == "render_failed"
        # Ровно одна попытка -- отказ рендера НЕ повторяет науку.
        assert science_state(RUN_ID) == before

    def test_content_integrity_guard(self, orc_client):
        # T8-дух: расхождение байтов с content_sha256 не выдаётся.
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        job, rendition = _make_rendition(
            orc_client, revision["revision_id"], "md"
        )
        from apps.api import document_jobs

        registry = document_jobs.get_document_registry()
        record = registry.get_rendition(rendition["rendition_id"])
        assert record is not None
        tampered = document_jobs.replace_dataclass(
            record, content_bytes=b"d4c-tampered-bytes"
        )
        registry.update_rendition(tampered)
        resp = orc_client.get(
            f"{BASE}/renditions/{rendition['rendition_id']}/content"
        )
        assert resp.status_code == 500
        assert resp.json()["detail"]["code"] == "integrity_mismatch"


# ══════════════════════════════════════════════════════════════════════
# 6. Аудит выдачи §14.1: тройка/preview/human_read_confirmed
# ══════════════════════════════════════════════════════════════════════


class TestOrcAuditTriple:
    def test_preview_records_protected_view(self, orc_client):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        orc_client.get(f"{BASE}/revisions/{revision['revision_id']}/preview")
        actions = [r["action"] for r in audit_records()]
        assert "protected_document_viewed" in actions

    def test_triple_distinct_ordered_owner_allowed(self, orc_client):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        job, rendition = _make_rendition(orc_client, revision["revision_id"])
        rid = rendition["rendition_id"]
        orc_client.get(f"{BASE}/renditions/{rid}/content")
        records = [
            r
            for r in audit_records()
            if r.get("resource_id") == rid
            or r.get("action") == "download_requested"
            and r.get("details", {}).get("snapshot_id")
        ]
        triple = [
            r["action"]
            for r in audit_records()
            if r["action"]
            in (
                "download_requested",
                "response_stream_started",
                "response_stream_finished",
            )
        ]
        assert "download_requested" in triple
        assert "response_stream_started" in triple
        assert "response_stream_finished" in triple
        i_req = triple.index("download_requested")
        i_started = triple.index("response_stream_started", i_req)
        i_finished = triple.index("response_stream_finished", i_started)
        assert i_req < i_started < i_finished
        # Для владельца решение запроса выгрузки -- allowed.
        requested = [
            r
            for r in audit_records()
            if r["action"] == "download_requested"
        ]
        assert requested and requested[-1]["decision"] == "allowed"

    def test_human_read_confirmed_absent(self, orc_client):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        job, rendition = _make_rendition(orc_client, revision["revision_id"])
        orc_client.get(
            f"{BASE}/renditions/{rendition['rendition_id']}/content"
        )
        actions = {r["action"] for r in audit_records()}
        assert "human_read_confirmed" not in actions


# ══════════════════════════════════════════════════════════════════════
# 7. RED-оракулы находок (ДОКАЗАТЕЛЬСТВА; обязаны падать на дефекте)
# ══════════════════════════════════════════════════════════════════════


class _BrokenAuditSink:
    """Sink-отказ для fault-injection (свой класс корпуса)."""

    def append(self, record) -> bool:
        raise RuntimeError("d4c-broken-audit-sink")

    def list_recent(self, limit: int = 100):
        return []


class TestOrcRedDefectProofs:
    """Оракулы кодируют ПРАВИЛЬНОЕ поведение по спеке:
    F-D4C2 -- AC11/§14.1: обязательный audit защищённой выдачи
    fail-closed ДО раскрытия (класс mandatory закреплён
    AUDIT_REQUIREMENTS и repo-тестом test_mandatory_classes_catalog
    сертифицированного DOCLOG-3);
    F-D4C3 -- §14.1: запись фиксирует ФАКТИЧЕСКОЕ решение
    (разрешено/отказано/прервано); «allowed» до проверки прав --
    ложный audit-факт."""

    def test_red_fd4c2_content_fail_closed_on_sink_failure(
        self, orc_client, monkeypatch
    ):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        _job, rendition = _make_rendition(
            orc_client, revision["revision_id"]
        )
        from apps.api import security_audit

        monkeypatch.setattr(
            security_audit, "get_audit_sink", lambda: _BrokenAuditSink()
        )
        resp = orc_client.get(
            f"{BASE}/renditions/{rendition['rendition_id']}/content"
        )
        # Спека: защищённая выдача НЕ раскрывает байты без обязательного
        # audit -- отказ до выполнения (не 200).
        assert resp.status_code != 200, (
            "F-D4C2: защищённая выдача fail-open -- байты отдаются при "
            "сломанном обязательном audit (AC11/§14.1 нарушен)"
        )

    def test_red_fd4c2_preview_fail_closed_on_sink_failure(
        self, orc_client, monkeypatch
    ):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        from apps.api import security_audit

        monkeypatch.setattr(
            security_audit, "get_audit_sink", lambda: _BrokenAuditSink()
        )
        resp = orc_client.get(
            f"{BASE}/revisions/{revision['revision_id']}/preview"
        )
        assert resp.status_code != 200, (
            "F-D4C2: preview защищённого документа fail-open при сломанном "
            "обязательном audit (AC11/§14.1 нарушен)"
        )

    def test_red_fd4c3_no_false_allowed_on_denied_download(
        self, orc_client
    ):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        _document, revision = _make_document(orc_client)
        _job, rendition = _make_rendition(
            orc_client, revision["revision_id"]
        )
        rid = rendition["rendition_id"]
        # Чужой запрашивает готовый файл: отказ обязателен...
        cookie_for(orc_client, SESSION_FOREIGN)
        resp = orc_client.get(f"{BASE}/renditions/{rid}/content")
        assert resp.status_code == 404
        # ...и в durable audit НЕ появляется ложный факт
        # download_requested/allowed для этого ресурса (§14.1: решение
        # записи отражает фактический исход).
        false_records = [
            r
            for r in audit_records()
            if r["action"] == "download_requested"
            and r.get("resource_id") == rid
            and r.get("decision") == "allowed"
        ]
        assert not false_records, (
            "F-D4C3: download_requested/allowed записан ДО авторизации -- "
            "ложный audit-факт при отказе (§14.1)"
        )

    def test_red_fd4c5_idempotency_other_body_409_on_reuse_path(
        self, orc_client
    ):
        """AC09 («Дубликат idempotency key/body не создаёт новые
        jobs/версии; другое тело -> 409»): на reuse-пути черновика
        (refresh=false) ключ МОЛЧА игнорируется -- тот же ключ с другим
        телом даёт 201 и НОВУЮ версию документа вместо 409."""
        seed_snapshot(kinds=["D01", "D02"])
        cookie_for(orc_client, SESSION_ID)
        first = orc_client.post(
            f"{BASE}/runs/{RUN_ID}/documents",
            json={"kind": "D01", "idempotency_key": "d4c-key-77"},
        )
        assert first.status_code in (200, 201)
        second = orc_client.post(
            f"{BASE}/runs/{RUN_ID}/documents",
            json={"kind": "D02", "idempotency_key": "d4c-key-77"},
        )
        assert second.status_code == 409, (
            "F-D4C5: reuse-путь черновика игнорирует idempotency_key -- "
            "другое тело с тем же ключом создаёт новую версию (AC09)"
        )


# ══════════════════════════════════════════════════════════════════════
# 8. Wiring/health: маршруты в app, facts-only /health/ops.documents
# ══════════════════════════════════════════════════════════════════════


class TestOrcWiringHealth:
    def test_documentation_routes_mounted(self, orc_client):
        resp = orc_client.get("/openapi.json")
        paths = resp.json()["paths"]
        for fragment in (
            f"{BASE}/runs/{{run_id}}/documents",
            f"{BASE}/documents/{{document_id}}/revisions",
            f"{BASE}/revisions/{{revision_id}}",
            f"{BASE}/revisions/{{revision_id}}/preview",
            f"{BASE}/revisions/{{revision_id}}/renditions",
            f"{BASE}/jobs/{{job_id}}",
            f"{BASE}/jobs/{{job_id}}/cancel",
            f"{BASE}/renditions/{{rendition_id}}/content",
        ):
            assert fragment in paths, fragment

    def test_health_documents_block_facts_only(self, orc_client):
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        resp = orc_client.get("/health/ops")
        assert resp.status_code == 200
        documents = resp.json().get("documents")
        assert documents is not None
        assert "registry_backend" in documents
        blob = json.dumps(documents)
        # T6/T10: без путей/DSN/содержимого.
        assert "d4c-data" not in blob          # мой tmp data-root не течёт
        assert "postgres://" not in blob
        assert "postgresql://" not in blob

    def test_existing_report_route_untouched(self, orc_client):
        # §17.1: существующие поверхности не переписываются новой выдачей.
        seed_snapshot()
        cookie_for(orc_client, SESSION_ID)
        resp = orc_client.get(f"/v1/progress/runs/{RUN_ID}/report?format=md")
        assert resp.status_code in (200, 404)  # маршрут жив (не 405/410)
