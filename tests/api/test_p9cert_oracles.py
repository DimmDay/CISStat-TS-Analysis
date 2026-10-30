# tests/api/test_p9cert_oracles.py
"""PGV-09-CERT: оракулы сертификатора на СВОИХ данных (дизъюнктный
корпус: RUN-P9CERTxxxx, session p9cert-*, view
preprocessing.missing.coverage_matrix / upload.overview.preview).

Назначение -- независимая проверка поставки PGV-09 (09c79aa) и
добивание мутантов, ВЫЖИВШИХ в авторском корпусе (кампания
scripts/p9cert/mutation_campaign.py):
  O1  -- добивает M4 (print-квота tenant снята);
  O2  -- добивает M6 (канонизация NaN/inf/None/bool ячейки снята);
  O3  -- добивает M7 (preflight schema_version снят);
  O4  -- добивает M11 (готовая ветка идемпотентности снята);
  O5  -- добивает M12 (контракт payload'а опустошён);
  O6a/b -- целостность basis (T8): порча байтов объекта и расхождение
           payload_sha256 -- честный render_basis_unavailable;
  O7  -- реальный TCP-путь worker'а: 200 без PNG -- terminal
           renderer_bad_output без rendition (глубина гейта);
  O8  -- сквозной ready на реальном TCP с МОЕЙ теплокартой известных
           сумм: payload несёт МОИ данные, ЕДИНЫЙ hash basis-артефакта;
  O9  -- malformed print_revision_id -- uniform 404 (AC18);
  O10 -- basis вне каталога (P01) -- честный 422 print_basis_unsupported;
  O11 -- proof-оракул дефекта Postgres write-path (находка F-P9C1):
           мини-модель ограничений 0010/0016/0017 в SQLite; точные
           INSERT'ы Postgres-адаптера для печатной job/rendition с
           snapshot_id='' нарушают FK; снятие FK вскрывает
           cross-revision коллизию UNIQUE и перехват строки через
           ON CONFLICT DO UPDATE.

Границы: контейнер PGV-08/Chromium недоступны в среде (унаследовано);
HTTP-контракт -- реальный TCP на локальном http.server с МОИМИ данными.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from apps.api import research_runs
from apps.api.document_jobs import (
    DocumentAccessDenied,
    DocumentQuotaExceeded,
    PrintRenderBasisUnsupported,
)
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
from apps.api.research_runs import ResearchRun

# ── Изоляция каждого теста (дизъюнкт с корпусом автора) ───────────────


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
        "CISSTAT_PNG_RENDERER_TIMEOUT_S",
        "CISSTAT_PNG_RENDERER_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    from apps.api import artifact_store, document_jobs, document_render_worker
    from apps.api import report_snapshot
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


# ── Сид на СВОИХ данных (корпус p9cert) ───────────────────────────────

RUN_ID = "RUN-P9CERT01"
SESSION_ID = "p9cert-session-a"
VIEW_HEATMAP = "preprocessing.missing.coverage_matrix"
VIEW_TABLE = "upload.overview.preview"

_PNG_CERT = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _subject(session_id: str = SESSION_ID) -> SubjectRef:
    return SubjectRef.from_session(session_id)


def _seed_run() -> ResearchRun:
    from dataclasses import replace as dc_replace

    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        dataset_fingerprint="p9cert" * 4,
        dataset_name="p9cert-oracle-seed",
        target_column="Оборот",
        created_at=_now(),
        last_active_at=_now(),
        status="active",
        owner_subject=_subject().subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    run = dc_replace(run, context_id="ctx-p9cert-1", data_revision=11)
    get_research_run_store().upsert_run(run)
    return run


def _site_of(view_id: str) -> dict:
    from apps.api.print_schema import load_visual_registry

    return next(
        s for s in load_visual_registry()["sites"] if s["view_id"] == view_id
    )


def _heatmap_result() -> dict:
    """МОЯ теплокарта пропусков с ИЗВЕСТНЫМИ суммами: 3 колонки x 4
    строки, всего 12 ячеек, пропусков 3 (доля 3/12=25%, сумма
    известных значений 7 -- знаменатели известны). digest -- от реального канон-байта."""
    from apps.api.artifact_store import (
        artifact_content_sha256,
        canonical_json_bytes,
    )
    from apps.api.print_schema import PRINT_RESULT_SCHEMA_VERSION

    data = {
        "columns": ["2024-Q1", "2024-Q2", "2024-Q3"],
        "matrix": [
            [0, 2, None],
            [1, 0, 0],
            [None, 3, 1],
            [0, 0, None],
        ],
    }
    return {
        "schema_version": PRINT_RESULT_SCHEMA_VERSION,
        "view_id": VIEW_HEATMAP,
        "payload": {
            "kind": "html_heatmap",
            "series_cap": None,
            "digest": artifact_content_sha256(canonical_json_bytes(data)),
            "digest_reason": None,
            "data": data,
        },
        "parameters": {
            "origin": "producer_freeze",
            "method": "missing_coverage",
            "parameters": {"bins": 4, "row_window": 100},
        },
        "units": [{"value": "ячеек", "reason": None}],
        "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
        "warnings": [],
        "execution": {
            "execution_ref": "exec-p9cert-1",
            "result_ref": "session:preprocessing.missing:v11",
            "computed_at": "2026-10-30T12:00:00Z",
            "computed_at_reason": None,
        },
    }


def _heatmap_snapshot(result_digest: str) -> dict:
    from apps.api.print_schema import (
        PRINT_SNAPSHOT_SCHEMA_VERSION,
        resolve_scope,
    )

    site = _site_of(VIEW_HEATMAP)
    scope = resolve_scope(site)
    refs = {ref: f"p9cert:{ref}" for ref in site["required_refs"]}
    refs.setdefault("context_id", "ctx-p9cert-1")
    refs.setdefault("data_revision", "11")
    section = {
        "section_id": "cert-heat-1",
        "renderer_kind": "html_heatmap",
        "title": "Матрица пропусков (cert)",
        "axes": [],
        "legend_ordering": [],
        "table_headings": None,
        "heatmap_scale": {"domain": [0, 5], "units": {"value": "ячеек", "reason": None}},
        "units": [{"value": "ячеек", "reason": None}],
    }
    return {
        "schema_version": PRINT_SNAPSHOT_SCHEMA_VERSION,
        "view_id": VIEW_HEATMAP,
        "scope": scope,
        "refs": refs,
        "result": {
            "result_ref": "artifact:visual_result:p9cert",
            "result_schema_version": "pgv.visual_result/1",
            "result_digest": result_digest,
            "result_digest_reason": None,
        },
        "data_artifact": {
            "artifact_id": "artifact:p9cert-data",
            "artifact_version": "v11",
            "source_hash": "d" * 64,
            "hash_algorithm": "sha256",
            "hash_reason": None,
        },
        "expected_context": {
            "context_id": "ctx-p9cert-1",
            "data_revision": "11",
            "expected_data_digest": None,
        },
        "dimensions": {
            "target_column": refs.get("target_column"),
            "date_column": refs.get("date_column"),
            "entity_column": refs.get("entity_column"),
            "entity_id": refs.get("entity"),
            "mode": "univariate",
        },
        "times": {
            "computed_at": "2026-10-30T12:00:00Z",
            "computed_at_reason": None,
            "captured_at": "2026-10-30T12:00:01Z",
            "captured_at_reason": None,
            "checkpoint_confirmed_at": None,
            "render_requested_at": "2026-10-30T12:00:02Z",
            "timezone": "UTC",
            "locale": "ru-RU",
        },
        "checkpoint": None,
        "display": {
            "title": "Матрица пропусков (cert)",
            "subtitle": None,
            "detail_level": "compact",
            "sections": [section],
        },
        "method": {
            "origin": "producer_freeze",
            "method": "missing_coverage",
            "parameters": {},
        },
        "selection": {
            "allowlist": list(site["view_params"]),
            "values": {"bins": 4, "row_window": 100},
        },
        "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
        "annotations": {"revision": 0, "author": "cert-analyst", "text": None},
        "print": {"profile_id": "figure-landscape", "page_count": 1, "theme": "light-print"},
        "renderer_env": {
            "renderer_version": "print-renderer/1",
            "font_profile": "print-fonts-dejavu/1",
            "dependency_status": "available",
            "unavailable_reason": None,
        },
        "data_flow": {"before_revision": None, "after_revision": None},
        "sensitive": {"raw_data_included": False, "sensitive_fields_policy": "metadata_only"},
        "warnings": [],
    }


def _freeze_heatmap_pair():
    from apps.api.visual_artifacts import (
        freeze_visual_print_snapshot,
        freeze_visual_result,
    )

    result_payload = _heatmap_result()
    result = freeze_visual_result(RUN_ID, _subject(), payload=result_payload)
    snapshot = freeze_visual_print_snapshot(
        RUN_ID,
        _subject(),
        payload=_heatmap_snapshot(result_payload["payload"]["digest"]),
        result_artifact_id=result.artifact_id,
    )
    return result, snapshot


def _heatmap_print_revision():
    from apps.api.document_jobs import DocumentDeliveryService

    result, snapshot = _freeze_heatmap_pair()
    service = DocumentDeliveryService.create_default()
    document, revision, _created = service.ensure_print_document_revision(
        RUN_ID,
        _subject(),
        session_id=SESSION_ID,
        print_kind="V01",
        basis_kind="visual_print_snapshot",
        basis_artifact_ids=[snapshot.artifact_id],
        profile_id="figure-landscape",
    )
    return service, revision, snapshot


def _request_print(service, revision):
    return service.request_print_rendition(
        revision.print_revision_id,
        format="png",
        subject=_subject(),
        session_id=SESSION_ID,
    )


class _CapturingHandler(BaseHTTPRequestHandler):
    """МОЙ программируемый контейнер: фиксирует ТЕЛА запросов (контракт
    payload'а пинится на МОИХ данных) и отдаёт заданный ответ."""

    behavior: dict = {}
    captured: list = []

    def log_message(self, *args):  # pragma: no cover
        return

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        _CapturingHandler.captured.append(json.loads(body.decode("utf-8")))
        mode = _CapturingHandler.behavior.get("mode", "png")
        if mode == "png":
            out, status, ctype = _PNG_CERT, 200, "image/png"
        else:
            out = b"<html>cert stub error page</html>"
            status, ctype = 200, "image/png"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


@pytest.fixture()
def cert_container():
    server = HTTPServer(("127.0.0.1", 0), _CapturingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _CapturingHandler.behavior = {"mode": "png"}
    _CapturingHandler.captured = []
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


# ══════════════════════════════════════════════════════════════════════
# O1 -- добивание M4: print-квота tenant
# ══════════════════════════════════════════════════════════════════════


class TestO1PrintQuota:
    def test_tenant_queue_full_is_quota_exceeded(self):
        from apps.api.document_jobs import (
            DocumentJobRecord,
            MAX_OPEN_JOBS_PER_TENANT,
            new_job_id,
        )

        _seed_run()
        service, revision, _snapshot = _heatmap_print_revision()
        for i in range(MAX_OPEN_JOBS_PER_TENANT):
            service.registry.register_job(
                DocumentJobRecord(
                    job_id=new_job_id(),
                    run_id=RUN_ID,
                    snapshot_id="",
                    format="png",
                    redaction_profile="owner-v1",
                    state="queued",
                    attempt=1,
                    created_by=_subject().subject_id,
                    tenant_id=DEFAULT_TENANT_ID,
                    print_revision_id="",
                    basis_artifact_id="",
                )
            )
        with pytest.raises(DocumentQuotaExceeded):
            _request_print(service, revision)


# ══════════════════════════════════════════════════════════════════════
# O2 -- добивание M6: канонизация ячеек на МОИХ значениях
# ══════════════════════════════════════════════════════════════════════


class TestO2CellCanonicalization:
    def test_nan_inf_none_bool_canonicalized_honestly(self):
        from apps.api.print_render_payload import section_content_from_visual_result

        snapshot_payload = _heatmap_snapshot("a" * 64)
        snapshot_payload["display"]["sections"][0]["section_id"] = "cert-table"
        snapshot_payload["display"]["sections"][0]["renderer_kind"] = "html_table"
        snapshot_payload["display"]["sections"][0]["table_headings"] = {
            "row": ["Строка"],
            "column": ["Значение"],
        }
        data = {
            "columns": ["value"],
            "rows": [
                {"value": float("nan")},
                {"value": float("inf")},
                {"value": float("-inf")},
                {"value": None},
                {"value": True},
                {"value": False},
                {"value": 12.5},
            ],
        }
        result_payload = {"payload": {"kind": "html_table", "data": data}}
        content = section_content_from_visual_result(
            snapshot_payload, result_payload
        )
        column = [row[0] for row in content["cert-table"]["rows"]]
        # §3.6: отсутствие значения -- пустая ячейка, не ноль и не 'nan'.
        assert column == ["", "", "", "", "true", "false", "12.5"]


# ══════════════════════════════════════════════════════════════════════
# O3 -- добивание M7: preflight schema_version
# ══════════════════════════════════════════════════════════════════════


class TestO3SchemaPreflight:
    def test_wrong_snapshot_schema_is_invalid_payload(self):
        from apps.api.print_render_payload import (
            PrintRenderPayloadInvalid,
            build_render_payload,
            section_content_from_visual_result,
        )

        snapshot_payload = _heatmap_snapshot("b" * 64)
        snapshot_payload["schema_version"] = "pgv.visual_print_snapshot/2"
        content = section_content_from_visual_result(
            snapshot_payload, {"payload": {"kind": "html_heatmap", "data": {"columns": ["c"], "matrix": [[1]]}}}
        )
        # Содержимое секции собрано, но снапшот чужой схемы -- отказ.
        with pytest.raises(PrintRenderPayloadInvalid):
            build_render_payload(snapshot_payload, content, request_id="cert-o3")


# ══════════════════════════════════════════════════════════════════════
# O4 -- добивание M11: готовая ветка идемпотентности
# ══════════════════════════════════════════════════════════════════════


class TestO4ReadyIdempotency:
    def test_repeat_after_ready_returns_same_job(self):
        _seed_run()
        service, revision, _snapshot = _heatmap_print_revision()
        job, _ = _request_print(service, revision)
        from apps.api.document_render_worker import DocumentRenderWorker

        worker = DocumentRenderWorker(
            render_timeout=5.0, interval=None, png_renderer=None
        )
        worker._png_renderer = _FakeCertRenderer()
        assert worker.run_once()["ready"] == 1
        ready = service.registry.get_job(job.job_id)
        assert ready.state == "ready"
        # Повтор после готовности -- ТОТ ЖЕ job (готовая ветка, AC09).
        job2, rendition2 = _request_print(service, revision)
        assert job2.job_id == job.job_id
        assert rendition2 is not None and rendition2.state == "ready"


class _FakeCertRenderer:
    def __init__(self, png: bytes = _PNG_CERT, error: Exception | None = None):
        self.png = png
        self.error = error
        self.payloads: list[dict] = []

    def render_page(self, payload: dict, *, timeout_s: float | None = None) -> bytes:
        self.payloads.append(payload)
        if self.error is not None:
            raise self.error
        return self.png


# ══════════════════════════════════════════════════════════════════════
# O5 -- добивание M12: контракт payload'а пинится на МОИХ данных
# ══════════════════════════════════════════════════════════════════════


class TestO5PayloadContract:
    def test_worker_payload_carries_my_frozen_content(self):
        _seed_run()
        service, revision, snapshot = _heatmap_print_revision()
        job, _ = _request_print(service, revision)
        renderer = _FakeCertRenderer()
        from apps.api.document_render_worker import DocumentRenderWorker

        worker = DocumentRenderWorker(
            render_timeout=5.0, interval=None, png_renderer=renderer
        )
        assert worker.run_once()["ready"] == 1
        assert len(renderer.payloads) == 1
        payload = renderer.payloads[0]
        assert payload["schema_version"] == "pgv.render_payload/1"
        assert payload["request_id"] == f"pgv:{job.job_id}"
        assert payload["snapshot"]["view_id"] == VIEW_HEATMAP
        assert payload["snapshot"]["print"]["profile_id"] == "figure-landscape"
        assert len(payload["sections"]) == 1
        section = payload["sections"][0]
        assert section["section_id"] == "cert-heat-1"
        assert section["kind"] == "html_heatmap"
        # МОИ известные данные дошли до renderer'а без искажений:
        # 3 колонки, 4 строки, сумма известных значений 7, пропусков 3.
        assert section["row_headings"] == ["2024-Q1", "2024-Q2", "2024-Q3"]
        assert len(section["cells"]) == 4
        flat = [c for row in section["cells"] for c in row]
        assert sum(c for c in flat if c is not None) == 7
        assert sum(1 for c in flat if c is None) == 3
        # ЕДИНЫЙ hash -- digest basis-артефакта (§19).
        rendition = service.registry.get_rendition(
            service.registry.get_job(job.job_id).rendition_id
        )
        assert rendition.snapshot_payload_sha256 == snapshot.payload_sha256


# ══════════════════════════════════════════════════════════════════════
# O6 -- целостность basis (T8): порча объекта / расхождение payload_sha256
# ══════════════════════════════════════════════════════════════════════


class TestO6BasisIntegrity:
    def test_tampered_object_bytes_fail_closed(self):
        _seed_run()
        service, revision, snapshot = _heatmap_print_revision()
        job, _ = _request_print(service, revision)
        from apps.api.artifact_store import (
            get_artifact_object_store,
            get_artifact_registry,
        )

        artifact = get_artifact_registry().get_artifact(snapshot.artifact_id)
        assert artifact is not None
        # Порча байтов ПОД content-key (T8): расхождение хэша.
        object_path = get_artifact_object_store().path_for_key(
            artifact.storage_key
        )
        object_path.write_bytes(b'{"tampered": true}')
        from apps.api.document_render_worker import DocumentRenderWorker

        worker = DocumentRenderWorker(
            render_timeout=5.0, interval=None, png_renderer=_FakeCertRenderer()
        )
        assert worker.run_once()["failed"] == 1
        failed = service.registry.get_job(job.job_id)
        assert failed.state == "failed"
        assert failed.error_code == "render_basis_unavailable"
        assert service.registry.find_print_rendition(
            revision.print_revision_id, "png", "owner-v1"
        ) is None

    def test_payload_sha256_mismatch_fail_closed(self, monkeypatch):
        import dataclasses

        _seed_run()
        service, revision, snapshot = _heatmap_print_revision()
        job, _ = _request_print(service, revision)
        from apps.api import artifact_store

        registry = artifact_store.get_artifact_registry()
        original_get = registry.get_artifact

        def tampered_get(artifact_id: str):
            artifact = original_get(artifact_id)
            if artifact is not None and artifact.artifact_id == snapshot.artifact_id:
                return dataclasses.replace(artifact, payload_sha256="e" * 64)
            return artifact

        monkeypatch.setattr(registry, "get_artifact", tampered_get)
        from apps.api.document_render_worker import DocumentRenderWorker

        worker = DocumentRenderWorker(
            render_timeout=5.0, interval=None, png_renderer=_FakeCertRenderer()
        )
        assert worker.run_once()["failed"] == 1
        failed = service.registry.get_job(job.job_id)
        assert failed.error_code == "render_basis_unavailable"


# ══════════════════════════════════════════════════════════════════════
# O7 -- реальный TCP-путь worker'а: 200 без PNG -- terminal, без rendition
# ══════════════════════════════════════════════════════════════════════


class TestO7RealTcpBadOutput:
    def test_worker_real_client_html_200_is_terminal(self, cert_container, monkeypatch):
        monkeypatch.setenv("CISSTAT_PNG_RENDERER_URL", cert_container)
        _CapturingHandler.behavior = {"mode": "html"}
        _seed_run()
        service, revision, _snapshot = _heatmap_print_revision()
        job, _ = _request_print(service, revision)
        from apps.api.document_render_worker import DocumentRenderWorker

        worker = DocumentRenderWorker(
            render_timeout=5.0, interval=None, png_renderer=None
        )
        assert worker.run_once()["failed"] == 1
        failed = service.registry.get_job(job.job_id)
        assert failed.state == "failed"
        assert failed.error_code == "renderer_bad_output"
        assert service.registry.find_print_rendition(
            revision.print_revision_id, "png", "owner-v1"
        ) is None


# ══════════════════════════════════════════════════════════════════════
# O8 -- сквозной ready на реальном TCP: МОЯ теплокарта доходит до контейнера
# ══════════════════════════════════════════════════════════════════════


class TestO8RealTcpReady:
    def test_end_to_end_ready_real_tcp(self, cert_container, monkeypatch):
        monkeypatch.setenv("CISSTAT_PNG_RENDERER_URL", cert_container)
        _CapturingHandler.behavior = {"mode": "png"}
        _seed_run()
        service, revision, snapshot = _heatmap_print_revision()
        job, _ = _request_print(service, revision)
        from apps.api.document_render_worker import DocumentRenderWorker

        worker = DocumentRenderWorker(
            render_timeout=5.0, interval=None, png_renderer=None
        )
        report = worker.run_once()
        assert report["ready"] == 1
        ready = service.registry.get_job(job.job_id)
        assert ready.state == "ready"
        rendition = service.registry.get_rendition(ready.rendition_id)
        assert rendition.state == "ready"
        assert rendition.print_revision_id == revision.print_revision_id
        content = service.read_rendition_content(
            rendition, _subject(), session_id=SESSION_ID
        )
        assert content == _PNG_CERT
        # Payload дошёл по реальному TCP с МОИМИ данными и МОИМ request_id.
        assert len(_CapturingHandler.captured) == 1
        sent = _CapturingHandler.captured[0]
        assert sent["request_id"] == f"pgv:{job.job_id}"
        assert sent["snapshot"]["view_id"] == VIEW_HEATMAP
        assert sent["sections"][0]["section_id"] == "cert-heat-1"
        assert rendition.snapshot_payload_sha256 == snapshot.payload_sha256


# ══════════════════════════════════════════════════════════════════════
# O9/O10 -- uniform 404 на malformed id; basis вне каталога
# ══════════════════════════════════════════════════════════════════════


class TestO9O10AccessAndCatalog:
    def test_malformed_print_revision_id_uniform_404(self):
        _seed_run()
        service, _revision, _snapshot = _heatmap_print_revision()
        with pytest.raises(DocumentAccessDenied):
            service.request_print_rendition(
                "dprint-not-a-real-id",
                format="png",
                subject=_subject(),
                session_id=SESSION_ID,
            )

    def test_p01_basis_is_print_basis_unsupported(self):
        _seed_run()
        from apps.api.document_jobs import DocumentDeliveryService

        service = DocumentDeliveryService.create_default()
        _document, revision, _created = service.ensure_print_document_revision(
            RUN_ID,
            _subject(),
            session_id=SESSION_ID,
            print_kind="P01",
            basis_kind="passport_checkpoint",
            basis_artifact_ids=[],
        )
        with pytest.raises(PrintRenderBasisUnsupported):
            _request_print(service, revision)


# ══════════════════════════════════════════════════════════════════════
# O11 -- proof-оракул дефекта Postgres write-path (F-P9C1)
# ══════════════════════════════════════════════════════════════════════


class TestO11PostgresWritePathProof:
    """Мини-модель ограничений 0010/0016/0017 (SQLite): точные INSERT'ы
    Postgres-адаптера document_jobs.register_job / register_rendition
    для печатных записей (snapshot_id='', revision_id=dprint-...)
    нарушают FK document_jobs.snapshot_id -> report_snapshots и
    document_renditions.revision_id -> document_revisions; снятие FK
    вскрывает коллизию UNIQUE(snapshot_id, format, redaction_profile)
    между печатными ревизиями и перехват чужой строки ON CONFLICT."""

    DDL = """
    CREATE TABLE report_snapshots (snapshot_id TEXT PRIMARY KEY);
    CREATE TABLE document_revisions (revision_id TEXT PRIMARY KEY);
    CREATE TABLE document_print_revisions (print_revision_id TEXT PRIMARY KEY);
    CREATE TABLE document_jobs (
        job_id TEXT PRIMARY KEY,
        snapshot_id TEXT REFERENCES report_snapshots(snapshot_id) ON DELETE CASCADE,
        format TEXT NOT NULL,
        redaction_profile TEXT NOT NULL DEFAULT 'owner-v1',
        revision_id TEXT,
        print_revision_id TEXT REFERENCES document_print_revisions(print_revision_id) ON DELETE CASCADE,
        basis_artifact_id TEXT
    );
    CREATE TABLE document_renditions (
        rendition_id TEXT PRIMARY KEY,
        revision_id TEXT NOT NULL REFERENCES document_revisions(revision_id) ON DELETE CASCADE,
        snapshot_id TEXT REFERENCES report_snapshots(snapshot_id) ON DELETE CASCADE,
        format TEXT NOT NULL,
        redaction_profile TEXT NOT NULL DEFAULT 'owner-v1',
        state TEXT NOT NULL DEFAULT 'ready',
        print_revision_id TEXT REFERENCES document_print_revisions(print_revision_id) ON DELETE CASCADE,
        UNIQUE (snapshot_id, format, redaction_profile)
    );
    CREATE UNIQUE INDEX uq_document_renditions_print
    ON document_renditions (print_revision_id, format, redaction_profile)
    WHERE print_revision_id IS NOT NULL;
    INSERT INTO report_snapshots VALUES ('rs-legacy-1');
    INSERT INTO document_revisions VALUES ('drev-legacy-1');
    INSERT INTO document_print_revisions VALUES ('dprint-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa');
    INSERT INTO document_print_revisions VALUES ('dprint-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb');
    """

    @staticmethod
    def _connect(*, foreign_keys: bool) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = %s" % ("ON" if foreign_keys else "OFF"))
        conn.executescript(TestO11PostgresWritePathProof.DDL)
        return conn

    @staticmethod
    def _print_job_insert(conn: sqlite3.Connection) -> None:
        # Точная форма register_job для печатной job'а (job.snapshot_id == "")
        conn.execute(
            "INSERT INTO document_jobs (job_id, snapshot_id, format, "
            "redaction_profile, revision_id, print_revision_id, basis_artifact_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("djob-cert-1", "", "png", "owner-v1",
             "dprint-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
             "dprint-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "art-cert-basis"),
        )

    @staticmethod
    def _print_rendition_insert(
        conn: sqlite3.Connection,
        *,
        rendition_id: str,
        print_revision_id: str,
    ) -> None:
        # Точная форма register_rendition для печатной rendition
        # (job.snapshot_id == "", job.revision_id == print_revision_id),
        # включая ON CONFLICT-клаузу Postgres-адаптера.
        conn.execute(
            "INSERT INTO document_renditions (rendition_id, revision_id, "
            "snapshot_id, format, redaction_profile, print_revision_id) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (snapshot_id, format, redaction_profile) DO UPDATE SET "
            "state = EXCLUDED.state, print_revision_id = EXCLUDED.print_revision_id",
            (rendition_id, print_revision_id, "", "png", "owner-v1", print_revision_id),
        )

    def test_print_job_insert_violates_snapshot_fk(self):
        conn = self._connect(foreign_keys=True)
        with pytest.raises(sqlite3.IntegrityError):
            self._print_job_insert(conn)

    def test_print_rendition_insert_violates_revision_fk(self):
        conn = self._connect(foreign_keys=True)
        with pytest.raises(sqlite3.IntegrityError):
            self._print_rendition_insert(
                conn,
                rendition_id="drend-cert-1",
                print_revision_id="dprint-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )

    def test_without_fk_unique_collision_hijacks_foreign_row(self):
        # FK снят (гипотетический修复): всплывает следующая линия защиты --
        # UNIQUE('','png','owner-v1') из 0010 ОБЩАЯ для всех печатных
        # ревизий; ON CONFLICT DO UPDATE ПЕРЕПИСЫВАЕТ чужую строку.
        conn = self._connect(foreign_keys=False)
        a = "dprint-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        b = "dprint-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        self._print_rendition_insert(
            conn, rendition_id="drend-cert-a", print_revision_id=a
        )
        self._print_rendition_insert(
            conn, rendition_id="drend-cert-b", print_revision_id=b
        )
        row = conn.execute(
            "SELECT rendition_id, print_revision_id FROM document_renditions"
        ).fetchall()
        # Вставка ревизии B НЕ создала свою строку: UNIQUE('','png',
        # 'owner-v1') из 0010 общий на все печатные ревизии, ON CONFLICT
        # DO UPDATE ПЕРЕПИСАЛ строку ревизии A (rendition_id A, теперь
        # print_revision_id B) -- тихий перехват чужой строки.
        assert len(row) == 1, row
        assert row == [("drend-cert-a", b)], row
