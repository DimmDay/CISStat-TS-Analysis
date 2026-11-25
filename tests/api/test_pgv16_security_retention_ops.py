# tests/api/test_pgv16_security_retention_ops.py
"""TDD-корпус PGV-16 (spec_passport_graphics_visual.md §11–§13,
строка PGV-16): Security/retention/ops/coverage -- точки изменения
identity/audit/pins/health/registry.

Постановка (§13): «Foreign refs/SSRF denied, permission/holds/TTL/
dependency failure честны».

Пять честных разрывов (docs/pgv16_security_retention_ops_coverage.md §1):

  SEC-1  -- выдача контента: тройка download_requested/
            response_stream_started/finished -- mandatory (AC11,
            fail-closed) с ЧЕСТНЫМ решением (allowed/denied/aborted);
            чужой не получает «allowed»-записи перед uniform 404;
  SEC-2  -- SSRF-префлайт API-слоя: внешние ресурсы screen_svg
            (http/file/javascript/blob href/src) -- 422
            invalid_screen_svg (AC19); внутренние якоря/data: легальны;
  RET-1  -- retention печатных renditions (V01/P01/P02): свой TTL,
            hold защищает, basis-артефакты/пины не трогаются (§12
            «источники и PNG могут иметь разные сроки»);
  OPS-1  -- /health/ops классифицирует print-PNG отдельно (секция
            print_renderer, facts-only, peek: сбой probe не роняет
            health, URL/секретов в payload нет);
  COV-1  -- registry coverage gate (scripts/pgv16/coverage_gate.py,
            см. tests/unit/test_pgv16_coverage_gate.py).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# ── Изоляция КАЖДОГО теста (паттерн test_pgv10) ──────────────────────


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
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
        "CISSTAT_PNG_RENDERER_URL",
        "CISSTAT_PNG_RENDERER_ENABLED",
        "CISSTAT_PNG_RENDERER_IPC",
        "CISSTAT_DOCUMENT_RETENTION_DRAFT_DAYS",
        "CISSTAT_DOCUMENT_RETENTION_PRINT_DAYS",
    ):
        monkeypatch.delenv(name, raising=False)
    from apps.api import research_runs

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    from apps.api import artifact_store, document_jobs, document_render_worker
    from apps.api import report_snapshot, visual_producers
    from apps.api.routers import documentation as documentation_router
    from apps.api.session_store import reset_session_store_for_testing
    from apps.api.security_audit import reset_audit_for_testing
    from apps.api.telemetry import reset_telemetry_for_testing

    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    document_render_worker.reset_document_render_worker_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()
    visual_producers.reset_visual_response_cache_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    document_render_worker.reset_document_render_worker_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()
    visual_producers.reset_visual_response_cache_for_testing()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


# ── Сид-хелперы на СВОИХ данных (корпус pgv16) ───────────────────────

RUN_ID = "RUN-PGV16A01"
SESSION_ID = "pgv16-seed-session"
FOREIGN_SESSION_ID = "pgv16-foreign-session"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso_at(days_ago: float) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(days=days_ago)
    ).isoformat()


def _seed_d_revision(client) -> str:
    """D-документ (предыдущий контур DOCLOG) через штатный сборщик
    снимка (паттерн doclog4) + POST documents; возвращает revision_id."""
    from tests.api.test_doclog4_document_delivery import _seed_snapshot

    _seed_snapshot(RUN_ID, SESSION_ID)
    _cookie(client)
    response = client.post(
        f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D01"}
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["revision"]["revision_id"]


def _cookie(client, session_id: str = SESSION_ID) -> None:
    from apps.api.session_store import SESSION_COOKIE_NAME

    client.cookies.set(SESSION_COOKIE_NAME, session_id)


def _owner_cookie(client) -> str:
    """Текущая cookie-сессия владельца (создана upload-потоком);
    cookie НЕ перезаписывается -- run принадлежит ЕЙ (R09
    creator-continuity), а не константе SESSION_ID."""
    from apps.api.session_store import SESSION_COOKIE_NAME

    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    assert session_id, "upload-поток не создал cookie-сессию"
    return session_id


def _seed_foreign_session() -> None:
    """Чужая сессия СВОИХ данных (uniform-404 оракулы)."""
    from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
    from apps.api.session_store import AnalysisSession, get_session_store

    session = AnalysisSession(session_id=FOREIGN_SESSION_ID)
    session.owner_subject = SubjectRef.from_session(FOREIGN_SESSION_ID).subject_id
    session.tenant_id = DEFAULT_TENANT_ID
    get_session_store().save(session)


def _create_print_document(client):
    """Печатный документ P01 через штатный POST passport-documents
    (fixation без рендера; полная траектория чекпоинтов -- паттерн
    seeded PGV-15). Возвращает (run_id, document_id, print_revision_id)."""
    from tests.api.test_pgv15_print_documents_ui import (
        _capture_full_trajectory,
        _durable_checkpoint_id,
        _run_id_of,
        _select_series,
        _upload,
    )

    _upload(client)
    _select_series(client)
    capture = _capture_full_trajectory(client)
    run_id = _run_id_of(client)
    checkpoint_id = _durable_checkpoint_id(run_id, capture["checkpoint_id"])
    created = client.post(
        f"/v1/documentation/runs/{run_id}/passport-documents",
        json={"mode": "set", "checkpoint_id": checkpoint_id},
    )
    assert created.status_code == 202, created.text
    body = created.json()
    return run_id, body["document_id"], body["print_revision_id"]


def _register_ready_print_rendition(
    print_revision_id: str,
    run_id: str = RUN_ID,
    *,
    fmt: str = "png",
    created_at: str | None = None,
    content: bytes | None = None,
    content_sha256: str | None = None,
    media_type: str = "image/png",
):
    """Ready печатная rendition (реальная форма publish-пути PGV-09/14)."""
    from apps.api.document_jobs import (
        DocumentDeliveryService,
        DocumentRenditionRecord,
        RENDITION_READY,
        new_rendition_id,
    )

    from apps.api.artifact_store import artifact_content_sha256

    service = DocumentDeliveryService.create_default()
    content = content if content is not None else b"\x89PNG\r\n\x1a\npgv16-bytes"
    rendition = service.registry.register_rendition(
        DocumentRenditionRecord(
            rendition_id=new_rendition_id(),
            revision_id="",
            snapshot_id="",
            run_id=run_id,
            format=fmt,
            state=RENDITION_READY,
            media_type=media_type,
            size_bytes=len(content),
            content_sha256=content_sha256 or artifact_content_sha256(content),
            storage_key=f"objects/pgv16-{fmt}",
            content_bytes=content,
            created_at=created_at or _now(),
            print_revision_id=print_revision_id,
        )
    )
    return service, rendition


def _audit_records(action: str | None = None) -> list[dict]:
    from apps.api.security_audit import get_audit_sink

    records = get_audit_sink().list_recent(limit=1000)
    if action is None:
        return [record for record in records]
    return [record for record in records if record.get("action") == action]


def _decisions_for(action: str, resource_id: str) -> list[str]:
    return [
        str(record.get("decision"))
        for record in _audit_records(action)
        if record.get("resource_id") == resource_id
    ]


# ══════════════════════════════════════════════════════════════════════
# SEC-1: честная mandatory-аудит-тройка выдачи (AC11, spec §11)
# ══════════════════════════════════════════════════════════════════════


class TestContentDeliveryAuditHonesty:
    def _seed_ready(self, client):
        run_id, _document_id, print_revision_id = _create_print_document(client)
        _service, rendition = _register_ready_print_rendition(
            print_revision_id, run_id
        )
        return rendition

    def test_owner_content_delivery_records_allowed_mandatory_triple(
        self, client
    ):
        """Успешная выдача: тройка allowed-записей в порядке
        download_requested -> stream_started -> stream_finished (§14.1)."""
        rendition = self._seed_ready(client)
        response = client.get(
            f"/v1/documentation/renditions/{rendition.rendition_id}/content"
        )
        assert response.status_code == 200, response.text
        assert response.content.startswith(b"\x89PNG")
        decisions = _decisions_for(
            "download_requested", rendition.rendition_id
        )
        assert decisions == ["allowed"], decisions
        actions = [record.get("action") for record in _audit_records()]
        i_req = actions.index("download_requested")
        i_started = actions.index(
            "response_stream_started", i_req
        )
        i_finished = actions.index(
            "response_stream_finished", i_started
        )
        assert i_req < i_started < i_finished
        started = [
            record
            for record in _audit_records("response_stream_started")
            if record.get("resource_id") == rendition.rendition_id
        ]
        assert started[0].get("decision") == "allowed"

    def test_foreign_content_uniform_404_without_allowed_record(self, client):
        """AC18/§11: чужой не получает ни байтов, ни «allowed»-записи:
        download_requested=denied (mandatory), stream-записей нет."""
        rendition = self._seed_ready(client)
        _seed_foreign_session()
        _cookie(client, FOREIGN_SESSION_ID)
        response = client.get(
            f"/v1/documentation/renditions/{rendition.rendition_id}/content"
        )
        assert response.status_code == 404, response.text
        decisions = _decisions_for(
            "download_requested", rendition.rendition_id
        )
        assert decisions == ["denied"], decisions
        assert _audit_records("response_stream_started") == []
        assert _audit_records("response_stream_finished") == []

    def test_audit_sink_failure_blocks_delivery_fail_closed(self, client):
        """AC11 fail-closed: sink недоступен -> 503
        mandatory_audit_unavailable, байты НЕ покидают сервис."""
        from apps.api.security_audit import set_audit_sink_for_testing

        rendition = self._seed_ready(client)

        class _DeadSink:
            def append(self, record):
                raise RuntimeError("sink down")

        set_audit_sink_for_testing(_DeadSink())
        response = client.get(
            f"/v1/documentation/renditions/{rendition.rendition_id}/content"
        )
        assert response.status_code == 503, response.text
        body = response.json()
        assert body["detail"]["code"] == "mandatory_audit_unavailable"
        assert b"\x89PNG" not in response.content

    def test_purged_print_rendition_410_with_denied_request(self, client):
        """§16.1/§17: purged rendition -- честный 410 владельцу; решение
        выдачи -- denied (не allowed)."""
        from apps.api.document_jobs import RENDITION_PURGED
        from apps.api.document_lifecycle import replace_record

        _run_id, _document_id, print_revision_id = _create_print_document(client)
        _service, rendition = _register_ready_print_rendition(
            print_revision_id, _run_id
        )
        purged = replace_record(rendition, state=RENDITION_PURGED)
        _service.registry.update_rendition(purged)
        response = client.get(
            f"/v1/documentation/renditions/{rendition.rendition_id}/content"
        )
        assert response.status_code == 410, response.text
        assert (
            response.json()["detail"]["code"] == "purged_artifact"
        )
        decisions = _decisions_for(
            "download_requested", rendition.rendition_id
        )
        assert decisions == ["denied"], decisions

    def test_integrity_mismatch_records_aborted(self, client):
        """Hash mismatch -- failed integrity_error, решение aborted
        (§11: выдача прервана, байты не выданы)."""
        _run_id, _document_id, print_revision_id = _create_print_document(client)
        _service, rendition = _register_ready_print_rendition(
            print_revision_id,
            _run_id,
            content=b"\x89PNG\r\n\x1a\nbad-bytes",
            content_sha256="b" * 64,
        )
        response = client.get(
            f"/v1/documentation/renditions/{rendition.rendition_id}/content"
        )
        assert response.status_code == 500, response.text
        assert (
            response.json()["detail"]["code"] == "integrity_mismatch"
        )
        decisions = _decisions_for(
            "download_requested", rendition.rendition_id
        )
        assert decisions == ["aborted"], decisions

    def test_preview_foreign_records_denied_uniform_404(self, client):
        """Preview (§17): чужой revision -- uniform 404 + честная
        protected_document_viewed=denied запись (не «allowed»)."""
        rev_id = _seed_d_revision(client)
        _seed_foreign_session()
        _cookie(client, FOREIGN_SESSION_ID)
        response = client.get(
            f"/v1/documentation/revisions/{rev_id}/preview"
        )
        assert response.status_code == 404, response.text
        decisions = _decisions_for("protected_document_viewed", rev_id)
        assert decisions == ["denied"], decisions

    def test_preview_owner_viewed_recorded_allowed(self, client):
        """Успешный preview -- protected_document_viewed=allowed
        (порядок: после решающей таблицы, до HTML)."""
        rev_id = _seed_d_revision(client)
        response = client.get(
            f"/v1/documentation/revisions/{rev_id}/preview"
        )
        assert response.status_code == 200, response.text
        decisions = _decisions_for("protected_document_viewed", rev_id)
        assert decisions == ["allowed"], decisions


# ══════════════════════════════════════════════════════════════════════
# SEC-2: SSRF/external-resource префлайт screen_svg (AC19)
# ══════════════════════════════════════════════════════════════════════


class TestScreenSvgSsrfPreflight:
    def test_external_http_image_href_rejected(self):
        from apps.api.visual_exports import InvalidScreenSvg, validate_screen_svg

        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg'>"
            "<image href='http://attacker.example/exfil.png'/></svg>"
        )
        with pytest.raises(InvalidScreenSvg):
            validate_screen_svg(svg)

    def test_https_and_file_and_blob_and_ftp_rejected(self):
        from apps.api.visual_exports import InvalidScreenSvg, validate_screen_svg

        for uri in (
            "https://attacker.example/x.png",
            "file:///etc/passwd",
            "blob:https://app.example/9f",
            "ftp://attacker.example/x",
            "javascript:alert(1)",
            "chrome://settings",
        ):
            svg = (
                "<svg xmlns='http://www.w3.org/2000/svg'>"
                f"<image xlink:href='{uri}'/></svg>"
            )
            with pytest.raises(InvalidScreenSvg):
                validate_screen_svg(svg)

    def test_remote_src_attribute_rejected(self):
        from apps.api.visual_exports import InvalidScreenSvg, validate_screen_svg

        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg'>"
            "<image src='http://attacker.example/track.gif'/></svg>"
        )
        with pytest.raises(InvalidScreenSvg):
            validate_screen_svg(svg)

    def test_internal_anchor_and_data_uri_are_legal(self):
        """Регресс-гвард: легальная frozen-сериализация Recharts
        (внутренние якоря clip-path/filter, data:-изображения) проходит."""
        from apps.api.visual_exports import validate_screen_svg

        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' "
            "xmlns:xlink='http://www.w3.org/1999/xlink'>"
            "<defs><clipPath id='cp'/></defs>"
            "<g clip-path='url(#cp)'>"
            "<use xlink:href='#cp'/>"
            "<image href='data:image/png;base64,iVBORw0KGgo='/>"
            "</g></svg>"
        )
        validate_screen_svg(svg)

    def test_http_post_visuals_mutant_killer_422(self, client):
        """HTTP-оракул мутанта: ослабление validate_screen_svg убивается
        контрактом маршрута -- POST /visuals с внешним ресурсом ->
        422 invalid_screen_svg (AC19 на API-границе)."""
        from tests.api.test_pgv10_visual_exports import (
            RUN_ID as P10_RUN_ID,
            SESSION_ID as P10_SESSION_ID,
            _freeze_visual_result,
        )

        _freeze_visual_result(
            "upload.chart.series",
            data={"series": [{"x": "2025-01-01", "y": 1.0}]},
            kind="recharts_svg",
            result_ref="vr-pgv16-ssrf-1",
        )
        _cookie(client, P10_SESSION_ID)
        response = client.post(
            f"/v1/documentation/runs/{P10_RUN_ID}/visuals",
            json={
                "view_id": "upload.chart.series",
                "screen_svg": (
                    "<svg xmlns='http://www.w3.org/2000/svg'>"
                    "<image href='http://attacker.example/exfil.png'/>"
                    "</svg>"
                ),
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["code"] == "invalid_screen_svg"


# ══════════════════════════════════════════════════════════════════════
# RET-1: retention печатных renditions (pins/holds/TTL, spec §12/§16.1)
# ══════════════════════════════════════════════════════════════════════


class TestPrintRetentionSweep:
    def _seed_print_with_rendition(self, client, *, days_ago: float | None):
        run_id, document_id, print_revision_id = _create_print_document(client)
        created_at = _iso_at(days_ago) if days_ago is not None else None
        _service, rendition = _register_ready_print_rendition(
            print_revision_id, run_id, created_at=created_at
        )
        return run_id, document_id, print_revision_id, _service, rendition

    def _sweep(self, client, run_id: str) -> dict:
        response = client.post(f"/v1/documentation/runs/{run_id}/retention/sweep")
        assert response.status_code == 200, response.text
        return response.json()["report"]

    def test_expired_print_rendition_purged_with_report(
        self, client, monkeypatch
    ):
        """TTL печатных PNG: старее cutoff -> purge (tombstone),
        чтение -> 410, отчёт честен."""
        monkeypatch.setenv("CISSTAT_DOCUMENT_RETENTION_PRINT_DAYS", "0")
        run_id, _doc, print_revision_id, _service, rendition = (
            self._seed_print_with_rendition(client, days_ago=45.0)
        )
        report = self._sweep(client, run_id)
        assert report["purged_print_renditions"] == 1, report
        assert report["scanned_print_documents"] >= 1, report
        response = client.get(
            f"/v1/documentation/renditions/{rendition.rendition_id}/content"
        )
        assert response.status_code == 410, response.text

    def test_fresh_print_rendition_kept(self, client):
        run_id, _doc, _print_revision_id, _service, rendition = (
            self._seed_print_with_rendition(client, days_ago=None)
        )
        report = self._sweep(client, run_id)
        assert report["purged_print_renditions"] == 0, report
        response = client.get(
            f"/v1/documentation/renditions/{rendition.rendition_id}/content"
        )
        assert response.status_code == 200, response.text

    def test_print_hold_protects_rendition(self, client):
        """Hold на печатном документе защищает renditions от purge
        (§12 «Cleanup не ломает ... holds»)."""
        run_id, document_id, _print_revision_id, _service, rendition = (
            self._seed_print_with_rendition(client, days_ago=45.0)
        )
        from apps.api.document_lifecycle import DocumentLifecycleService
        from apps.api.identity import SubjectRef

        lifecycle = DocumentLifecycleService.create_default()
        owner_session_id = _owner_cookie(client)
        owner = SubjectRef.from_session(owner_session_id)
        lifecycle.set_retention(
            document_id, owner, session_id=owner_session_id, action="hold",
            reason="pgv16-hold",
        )
        report = self._sweep(client, run_id)
        assert report["skipped_hold_print_documents"] == 1, report
        assert report["purged_print_renditions"] == 0, report
        response = client.get(
            f"/v1/documentation/renditions/{rendition.rendition_id}/content"
        )
        assert response.status_code == 200, response.text

    def test_basis_artifacts_and_pins_not_touched_by_sweep(self, client):
        """§12: источники и PNG имеют разные сроки -- basis-артефакты
        и пины печатной ревизии переживают purge renditions."""
        run_id, _doc, print_revision_id, service, rendition = (
            self._seed_print_with_rendition(client, days_ago=45.0)
        )
        revision = service.registry.get_print_revision(print_revision_id)
        assert revision is not None
        basis_ids = list(revision.basis_artifact_ids or [])
        assert basis_ids, "печатная ревизия без basis-артефактов"
        from apps.api.artifact_store import (
            get_artifact_object_store,
            get_artifact_registry,
        )

        report = self._sweep(client, run_id)
        assert report["purged_print_renditions"] == 1, report
        registry = get_artifact_registry()
        for artifact_id in basis_ids:
            artifact = registry.get_artifact(artifact_id)
            assert artifact is not None, artifact_id
            get_artifact_object_store().read_bytes(artifact.storage_key)
        pins = registry.list_pins(run_id, ref_kind="artifact")
        pinned_ids = {pin.ref_id for pin in pins}
        assert set(basis_ids) <= pinned_ids

    def test_d_document_sweep_regression_unchanged(self, client):
        """Регресс: D01-D12 sweep прежний (md-рендер, purge старья)."""
        rev_id = _seed_d_revision(client)
        job = client.post(
            f"/v1/documentation/revisions/{rev_id}/renditions",
            json={"format": "md"},
        ).json()["job"]
        rendition_id = job["rendition"]["rendition_id"]
        response = client.post(
            f"/v1/documentation/runs/{RUN_ID}/retention/sweep"
        )
        assert response.status_code == 200
        report = response.json()["report"]
        assert "purged_renditions" in report
        assert report["purged_print_renditions"] == 0
        fresh = client.get(
            f"/v1/documentation/renditions/{rendition_id}/content"
        )
        assert fresh.status_code == 200

    def test_list_print_renditions_memory_registry_scoped(self, client):
        """Новый метод реестра: только renditions СВОЕГО print_revision."""
        _run_id, _doc, print_revision_id = _create_print_document(client)
        _service, rendition = _register_ready_print_rendition(
            print_revision_id, RUN_ID
        )
        listed = _service.registry.list_print_renditions(print_revision_id)
        assert [r.rendition_id for r in listed] == [rendition.rendition_id]
        assert _service.registry.list_print_renditions("prn-nope") == []


# ══════════════════════════════════════════════════════════════════════
# OPS-1: /health/ops классифицирует print-PNG отдельно (spec §12)
# ══════════════════════════════════════════════════════════════════════


class TestPrintRendererOps:
    def _ops_snapshot(self, client) -> dict:
        response = client.get("/health/ops")
        assert response.status_code == 200, response.text
        return response.json()

    def test_section_disabled_reports_honest_reason(self, client):
        from apps.api.png_renderer_client import ENV_RENDERER_ENABLED

        import os

        os.environ[ENV_RENDERER_ENABLED] = "0"
        try:
            snapshot = self._ops_snapshot(client)
        finally:
            os.environ.pop(ENV_RENDERER_ENABLED, None)
        section = snapshot["print_renderer"]
        assert section["enabled"] is False
        assert section["readiness"]["ok"] is False
        assert section["readiness"]["reason"] == "renderer_disabled"
        assert section["classification"].startswith("png_print")

    def test_section_probe_ok_facts_only(self, client, monkeypatch):
        monkeypatch.setenv("CISSTAT_PNG_RENDERER_ENABLED", "1")
        from apps.api import print_renderer_ops
        from apps.api.png_renderer_client import PngRendererClient

        def _fake_readiness(self):
            return {"status": "ready", "checks": {"browser": "ok"}}

        monkeypatch.setattr(PngRendererClient, "readiness", _fake_readiness)
        snapshot = self._ops_snapshot(client)
        section = snapshot["print_renderer"]
        assert section["enabled"] is True
        assert section["readiness"]["ok"] is True
        assert section["readiness"]["status"] == "ready"
        assert "probe_ms" in section
        # Facts-only: ни URL, ни пути сокета, ни секретов в payload.
        text = json.dumps(section)
        assert "http://" not in text and "https://" not in text
        assert "sock" not in text.lower()

    def test_probe_failure_does_not_break_health(self, client, monkeypatch):
        monkeypatch.setenv("CISSTAT_PNG_RENDERER_ENABLED", "1")
        from apps.api.png_renderer_client import (
            PngRendererClient,
            RendererUnavailable,
        )

        def _dead(self):
            raise RendererUnavailable("renderer_unavailable: down")

        monkeypatch.setattr(PngRendererClient, "readiness", _dead)
        snapshot = self._ops_snapshot(client)
        section = snapshot["print_renderer"]
        assert section["readiness"]["ok"] is False
        assert section["readiness"]["reason"] == "renderer_unreachable"

    def test_readiness_tcp_parsing_real_socket(self):
        """Штатный readiness() контейнера: 200-JSON парсится; отказ --
        честные коды (RendererUnavailable/RendererClientError)."""
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        from apps.api.png_renderer_client import (
            PngRendererClient,
            RendererClientError,
            RendererUnavailable,
        )

        class _Ready(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 -- API http.server
                body = json.dumps({"status": "ready"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET_503(self):  # noqa: N802 -- не используется
                raise AssertionError

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), _Ready)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            probe = PngRendererClient(
                base_url=f"http://127.0.0.1:{server.server_port}",
                enabled=True,
                timeout_s=2.0,
            )
            assert probe.readiness() == {"status": "ready"}
        finally:
            server.shutdown()

        class _Fail(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 -- API http.server
                self.send_response(503)
                self.end_headers()

            def log_message(self, *args):
                pass

        dead = HTTPServer(("127.0.0.1", 0), _Fail)
        thread2 = threading.Thread(target=dead.serve_forever, daemon=True)
        thread2.start()
        try:
            probe = PngRendererClient(
                base_url=f"http://127.0.0.1:{dead.server_port}",
                enabled=True,
                timeout_s=2.0,
            )
            with pytest.raises(RendererClientError):
                probe.readiness()
        finally:
            dead.shutdown()
        # Рефакшн -- контейнер не поднят.
        probe = PngRendererClient(
            base_url="http://127.0.0.1:1", enabled=True, timeout_s=0.5
        )
        with pytest.raises(RendererUnavailable):
            probe.readiness()
