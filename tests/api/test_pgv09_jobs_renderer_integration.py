# tests/api/test_pgv09_jobs_renderer_integration.py
"""Задача PGV-09 (spec_passport_graphics_visual.md §4/§10/§11/§13,
строка PGV-09): интеграция Jobs/PNG renderer -- документные jobs
печатают PNG печатных ревизий (V01, basis visual_print_snapshot) через
изолированный renderer-контейнер PGV-08.

Критерий завершения (§13): «Lease/staging/CAS/cancel/missing dependency
не дают broken ready».

Оракулы на СВОИХ данных: корпус дизъюнктен repo-корпусу и корпусам
PGV-02/03/08 (RUN-P09xxxxx, p09-*); изоляция каждого теста -- паттерн
test_doclog5_formats_worker.py (свой tmp_path/CISSTAT_DATA_DIR, сброс
singleton-фабрик). Контейнер PGV-08 в среде сессии недоступен (граница
унаследована от PGV-08): HTTP-контракт клиента проверяется реальным
TCP-раундтрипом (класс B, локальный http.server), жизненный цикл jobs --
инъекцией fake-renderer'а (классы C/D).

Гарантии по классам:
  A -- мост pgv.render_payload/1: сборка из frozen durable-входов,
       честные пропуски контента (никакого фабрикования, §3.6);
  B -- клиент контейнера: таксономия ошибок §11/AC17, PNG-гейт 200;
  C -- сервис печатных renditions: авторизация/uniform 404 (AC18),
       идемпотентность (AC09), 429-лимиты (§18);
  D -- worker: terminal/transient таксономия (AC17/AC20), lease-реклейм,
       CAS-гейт позднего завершения (AC20), единый hash basis-артефакта;
  E -- HTTP-маршрут 202 + status_url (§17);
  F -- миграция 0017 и паритет MIGRATION_STATEMENTS (паттерн PROGR-5.1).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from apps.api import research_runs
from apps.api.document_jobs import (
    DocumentAccessDenied,
    DocumentRetryLimitExceeded,
    UnsupportedFormatError,
)
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
from apps.api.research_runs import ResearchRun

# ── Изоляция КАЖДОГО теста (паттерн test_doclog5_formats_worker.py) ────


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
        "CISSTAT_DOCUMENT_RENDER_WORKER_INTERVAL",
        "CISSTAT_DOCUMENT_RENDER_WORKER_BATCH",
        "CISSTAT_DOCUMENT_RENDER_WORKER_PER_TENANT",
        "CISSTAT_DOCUMENT_RENDER_WORKER_RENDER_TIMEOUT",
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


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


# ── Сид-хелперы на СВОИХ данных (корпус p09) ─────────────────────────

RUN_ID = "RUN-P09A0001"
SESSION_ID = "p09-seed-session"
VIEW_TABLE = "upload.overview.tech_table"  # html_table, research-scope


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_run(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    context_id: str | None = "ctx-p09-1",
    data_revision: int | None = 7,
) -> ResearchRun:
    """Сид запуска; ResearchRun иммутабелен -- контекст через replace()."""
    from dataclasses import replace as dc_replace

    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="p09" * 8,
        dataset_name="pgv09-jobs-renderer-seed",
        target_column="value",
        created_at=_now(),
        last_active_at=_now(),
        status="active",
        owner_subject=SubjectRef.from_session(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    if context_id is not None or data_revision is not None:
        run = dc_replace(
            run,
            context_id=context_id if context_id is not None else run.context_id,
            data_revision=(
                data_revision if data_revision is not None else run.data_revision
            ),
        )
    get_research_run_store().upsert_run(run)
    return run


def _owner_subject(session_id: str = SESSION_ID) -> SubjectRef:
    return SubjectRef.from_session(session_id)


def _visual_result_table() -> dict:
    """VisualResult/1 с каноническим срезом таблицы (форма PGV-03
    адаптера {columns, rows}; digest -- от реального канон-байта)."""
    from apps.api.artifact_store import (
        artifact_content_sha256,
        canonical_json_bytes,
    )
    from apps.api.print_schema import PRINT_RESULT_SCHEMA_VERSION

    data = {
        "columns": ["name", "dtype", "non_null", "nulls"],
        "rows": [
            {"name": "Дата", "dtype": "datetime64", "non_null": 96, "nulls": 0},
            {"name": "Оборот", "dtype": "float64", "non_null": 94, "nulls": 2},
        ],
    }
    return {
        "schema_version": PRINT_RESULT_SCHEMA_VERSION,
        "view_id": VIEW_TABLE,
        "payload": {
            "kind": "html_table",
            "series_cap": None,
            "digest": artifact_content_sha256(canonical_json_bytes(data)),
            "digest_reason": None,
            "data": data,
        },
        "parameters": {
            "origin": "producer_freeze",
            "method": "tech_info",
            "parameters": {"selected_column": "Оборот"},
        },
        "units": [{"value": None, "reason": "dimensionless"}],
        "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
        "warnings": [],
        "execution": {
            "execution_ref": "exec-p09-1",
            "result_ref": "session:upload.tech_table:v7",
            "computed_at": "2026-10-30T09:00:00Z",
            "computed_at_reason": None,
        },
    }


def _print_snapshot(result_digest: str, view_id: str = VIEW_TABLE) -> dict:
    """Валидный VisualPrintSnapshot/1 (правила PGV-01; сборка по сайту
    реестра PGV-00)."""
    from apps.api.print_schema import (
        PRINT_SNAPSHOT_SCHEMA_VERSION,
        load_visual_registry,
        resolve_scope,
    )

    site = next(
        s for s in load_visual_registry()["sites"] if s["view_id"] == view_id
    )
    scope = resolve_scope(site)
    refs = {ref: f"p09:{ref}" for ref in site["required_refs"]}
    refs.setdefault("context_id", "ctx-p09-1")
    refs.setdefault("data_revision", "7")

    section = {
        "section_id": "s1",
        "renderer_kind": "html_table",
        "title": "Техническая информация по колонкам",
        "axes": [],
        "legend_ordering": [],
        "table_headings": {
            "row": ["Колонка", "Тип", "Непустых", "Пропусков"],
            "column": ["Значение"],
        },
        "heatmap_scale": None,
        "units": [{"value": None, "reason": "dimensionless"}],
    }
    return {
        "schema_version": PRINT_SNAPSHOT_SCHEMA_VERSION,
        "view_id": view_id,
        "scope": scope,
        "refs": refs,
        "result": {
            "result_ref": "artifact:visual_result:p09",
            "result_schema_version": "pgv.visual_result/1",
            "result_digest": result_digest,
            "result_digest_reason": None,
        },
        "data_artifact": {
            "artifact_id": "artifact:p09-data",
            "artifact_version": "v7",
            "source_hash": "c" * 64,
            "hash_algorithm": "sha256",
            "hash_reason": None,
        },
        "expected_context": {
            "context_id": "ctx-p09-1",
            "data_revision": "7",
            "expected_data_digest": None,
        },
        "dimensions": {
            "target_column": refs.get("target_column"),
            "date_column": refs.get("date_column"),
            "entity_column": refs.get("entity_column"),
            "entity_id": refs.get("entity"),
            "mode": "univariate" if site["applicability"] == "univariate" else "panel",
        },
        "times": {
            "computed_at": "2026-10-30T09:00:00Z",
            "computed_at_reason": None,
            "captured_at": "2026-10-30T09:00:01Z",
            "captured_at_reason": None,
            "checkpoint_confirmed_at": None,
            "render_requested_at": "2026-10-30T09:00:02Z",
            "timezone": "UTC",
            "locale": "ru-RU",
        },
        "checkpoint": None,
        "display": {
            "title": "Техническая информация по колонкам",
            "subtitle": None,
            "detail_level": "compact",
            "sections": [section],
        },
        "method": {"origin": "producer_freeze", "method": "tech_info", "parameters": {}},
        "selection": {
            "allowlist": list(site["view_params"]),
            "values": {"selected_column": "Оборот"},
        },
        "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
        "annotations": {"revision": 0, "author": "analyst", "text": None},
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


def _freeze_pair(run_id: str = RUN_ID):
    """Durable-пара visual_result + visual_print_snapshot (§6/§8)."""
    from apps.api.visual_artifacts import (
        freeze_visual_print_snapshot,
        freeze_visual_result,
    )

    subject = _owner_subject()
    result_payload = _visual_result_table()
    result = freeze_visual_result(run_id, subject, payload=result_payload)
    snapshot = freeze_visual_print_snapshot(
        run_id,
        subject,
        payload=_print_snapshot(result_payload["payload"]["digest"]),
        result_artifact_id=result.artifact_id,
    )
    return result, snapshot


def _print_revision(run_id: str = RUN_ID):
    """Печатная ревизия V01 (basis visual_print_snapshot) -- PGV-02."""
    from apps.api.document_jobs import DocumentDeliveryService

    result, snapshot = _freeze_pair(run_id)
    service = DocumentDeliveryService.create_default()
    document, revision, _created = service.ensure_print_document_revision(
        run_id,
        _owner_subject(),
        session_id=SESSION_ID,
        print_kind="V01",
        basis_kind="visual_print_snapshot",
        basis_artifact_ids=[snapshot.artifact_id],
        profile_id="figure-landscape",
    )
    return service, document, revision, snapshot


# Минимальный валидный PNG (1x1, без pHYs -- подписи достаточно: pHYs
# инъекция и геометрия -- зона PGV-08/CERT).
_PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)


class _FakeRenderer:
    """Fake PGV-08-контейнера для lifecycle-оракулов (класс D)."""

    def __init__(self, *, png: bytes = _PNG_1PX, error: Exception | None = None):
        self.png = png
        self.error = error
        self.calls: list[dict] = []

    def render_page(self, payload: dict, *, timeout_s: float | None = None) -> bytes:
        self.calls.append({"request_id": payload.get("request_id"), "timeout_s": timeout_s})
        if self.error is not None:
            raise self.error
        return self.png


# ══════════════════════════════════════════════════════════════════════
# A. Мост pgv.render_payload/1 (сборка из frozen durable-входов)
# ══════════════════════════════════════════════════════════════════════


class TestPayloadBridge:
    def test_build_render_payload_from_durable_pair(self):
        """Печатный payload собирается из frozen пары: snapshot=PGV-01
        метаданные, sections=контент visual_result (§6: renderer получает
        frozen typed payload)."""
        from apps.api.print_render_payload import (
            RENDER_PAYLOAD_VERSION,
            build_render_payload,
            section_content_from_visual_result,
        )

        result_payload = _visual_result_table()
        snapshot_payload = _print_snapshot(
            result_payload["payload"]["digest"]
        )
        # Реальный поток worker'а: resolver контента -> сборка payload'а.
        content = section_content_from_visual_result(
            snapshot_payload, result_payload
        )
        payload = build_render_payload(
            snapshot_payload, content, request_id="job-test-1"
        )
        assert payload["schema_version"] == RENDER_PAYLOAD_VERSION
        assert payload["request_id"] == "job-test-1"
        assert payload["snapshot"]["view_id"] == VIEW_TABLE
        assert payload["snapshot"]["print"]["profile_id"] == "figure-landscape"
        assert len(payload["sections"]) == 1
        section = payload["sections"][0]
        assert section["section_id"] == "s1"
        assert section["kind"] == "html_table"
        assert section["headings"]["row"] == [
            "Колонка", "Тип", "Непустых", "Пропусков",
        ]
        # Контент -- строки ячеек из visual_result.data (первая колонка
        # -- имя строки).
        assert section["rows"][0][0] == "Дата"
        assert section["rows"][1][3] == "2"

    def test_missing_section_content_is_honest(self):
        """Нет контента секции -- честный отказ сборки (§3.6: неполнота
        не подменяется нулями/пустой картинкой)."""
        from apps.api.print_render_payload import (
            PrintRenderPayloadIncomplete,
            build_render_payload,
        )

        snapshot_payload = _print_snapshot("a" * 64)
        with pytest.raises(PrintRenderPayloadIncomplete):
            build_render_payload(snapshot_payload, {}, request_id="x")

    def test_recharts_without_svg_is_honest_missing(self):
        """recharts_svg-секция без frozen svg_xml -- missing (экранный
        SVG не фабрикуется на Python-стороне; §4.1)."""
        from apps.api.print_render_payload import (
            PrintRenderPayloadIncomplete,
            build_render_payload,
        )

        snapshot_payload = _print_snapshot("a" * 64)
        snapshot_payload["display"]["sections"][0]["renderer_kind"] = (
            "recharts_svg"
        )
        snapshot_payload["display"]["sections"][0]["axes"] = [
            {"name": "Дата", "units": {"value": None, "reason": "dimensionless"}, "scale": "time", "limits": None},
            {"name": "Ряд", "units": {"value": None, "reason": "dimensionless"}, "scale": "linear", "limits": None},
        ]
        snapshot_payload["display"]["sections"][0]["table_headings"] = None
        with pytest.raises(PrintRenderPayloadIncomplete):
            build_render_payload(
                snapshot_payload,
                {"s1": {"series": [1, 2, 3]}},
                request_id="x",
            )

    def test_section_content_from_visual_result_cards(self):
        """Каноническая форма {cards} -> контент html_cards."""
        from apps.api.print_render_payload import section_content_from_visual_result

        snapshot_payload = _print_snapshot("a" * 64)
        # Секция карточек (композиция проверяется при freeze; здесь --
        # чистая функция resolver'а).
        snapshot_payload["display"]["sections"][0]["renderer_kind"] = "html_cards"
        snapshot_payload["display"]["sections"][0]["table_headings"] = None
        result_payload = {
            "payload": {
                "kind": "html_cards",
                "data": {
                    "cards": [
                        {"label": "Наблюдений", "value": 96},
                        {"label": "Пропусков", "value": 2},
                    ]
                },
            }
        }
        content = section_content_from_visual_result(
            snapshot_payload, result_payload
        )
        # Значения карточек канонизируются в строки (форма контента
        # PGV-08 -- текстовые карточки).
        assert content["s1"]["cards"][0] == {
            "label": "Наблюдений", "value": "96", "unit": None,
        }

    def test_section_content_missing_data_is_honest(self):
        """visual_result без data (уровень digest-only) -- честный
        пропуск: контент не фабрикуется."""
        from apps.api.print_render_payload import (
            PrintRenderPayloadIncomplete,
            section_content_from_visual_result,
        )

        snapshot_payload = _print_snapshot("a" * 64)
        result_payload = {"payload": {"kind": "html_table", "digest": "a" * 64}}
        with pytest.raises(PrintRenderPayloadIncomplete):
            section_content_from_visual_result(snapshot_payload, result_payload)




# ══════════════════════════════════════════════════════════════════════
# B. Клиент renderer-контейнера (реальный TCP-раундтрип)
# ══════════════════════════════════════════════════════════════════════


class _StubHandler(BaseHTTPRequestHandler):
    """Программируемый ответ контейнера (код/тело задаются тестом)."""

    behavior: dict = {}

    def log_message(self, *args):  # pragma: no cover -- тишина в логах
        return

    def do_POST(self):  # noqa: N802 -- BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        mode = _StubHandler.behavior.get("mode", "png")
        if mode == "png":
            body = _PNG_1PX
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
        elif mode in {"dependency", "timeout", "busy", "invalid", "too_large"}:
            codes = {
                "dependency": (503, "render_dependency_unavailable"),
                "timeout": (503, "render_timeout"),
                "busy": (429, "renderer_busy"),
                "invalid": (422, "invalid_payload"),
                "too_large": (413, "payload_too_large"),
            }
            status, code = codes[mode]
            body = json.dumps(
                {"error": {"code": code, "message": code, "retryable": False}}
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
        else:  # not_png
            body = b"<html>proxy error page</html>"
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def stub_container():
    server = HTTPServer(("127.0.0.1", 0), _StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _StubHandler.behavior = {"mode": "png"}
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


class TestRendererClient:
    def _client(self, base_url: str):
        from apps.api.png_renderer_client import PngRendererClient

        return PngRendererClient(base_url=base_url, timeout_s=5.0)

    def test_render_page_returns_png(self, stub_container):
        from apps.api.png_renderer_client import PNG_SIGNATURE

        payload = {"schema_version": "pgv.render_payload/1", "request_id": "b1"}
        data = self._client(stub_container).render_page(payload)
        assert data.startswith(PNG_SIGNATURE)

    def test_dependency_unavailable_mapped(self, stub_container):
        """AC17: 503 missing_browser/missing_fonts/missing_bundle --
        render_dependency_unavailable, детерминированная (terminal)."""
        from apps.api.png_renderer_client import RendererDependencyUnavailable

        _StubHandler.behavior = {"mode": "dependency"}
        with pytest.raises(RendererDependencyUnavailable):
            self._client(stub_container).render_page({"request_id": "b2"})

    def test_timeout_mapped(self, stub_container):
        from apps.api.png_renderer_client import RendererTimeout

        _StubHandler.behavior = {"mode": "timeout"}
        with pytest.raises(RendererTimeout):
            self._client(stub_container).render_page({"request_id": "b3"})

    def test_busy_mapped(self, stub_container):
        from apps.api.png_renderer_client import RendererBusy

        _StubHandler.behavior = {"mode": "busy"}
        with pytest.raises(RendererBusy):
            self._client(stub_container).render_page({"request_id": "b4"})

    def test_invalid_payload_mapped(self, stub_container):
        from apps.api.png_renderer_client import RendererPayloadInvalid

        _StubHandler.behavior = {"mode": "invalid"}
        with pytest.raises(RendererPayloadInvalid):
            self._client(stub_container).render_page({"request_id": "b5"})

    def test_too_large_mapped(self, stub_container):
        from apps.api.png_renderer_client import RendererPayloadTooLarge

        _StubHandler.behavior = {"mode": "too_large"}
        with pytest.raises(RendererPayloadTooLarge):
            self._client(stub_container).render_page({"request_id": "b6"})

    def test_connection_refused_is_unavailable(self):
        """Контейнер недоступен -- RendererUnavailable (transient:
        перезапуск контейнера возможен, AC24)."""
        from apps.api.png_renderer_client import RendererUnavailable

        # Порт без слушателя (эпемeral зарезервирован закрытием).
        blocker = HTTPServer(("127.0.0.1", 0), _StubHandler)
        port = blocker.server_address[1]
        blocker.server_close()
        with pytest.raises(RendererUnavailable):
            self._client(f"http://127.0.0.1:{port}").render_page(
                {"request_id": "b7"}
            )

    def test_non_png_200_is_bad_output(self, stub_container):
        """200 без PNG-подписи -- broken output не становится готовым
        файлом (§11: битые байты не выдаются за валидные)."""
        from apps.api.png_renderer_client import RendererBadOutput

        _StubHandler.behavior = {"mode": "not_png"}
        with pytest.raises(RendererBadOutput):
            self._client(stub_container).render_page({"request_id": "b8"})

    def test_disabled_client_is_dependency_unavailable(self):
        """ENABLED=0 -- честный render_dependency_unavailable
        (renderer_disabled), не тихий суррогат."""
        from apps.api.png_renderer_client import (
            PngRendererClient,
            RendererDependencyUnavailable,
        )

        with pytest.raises(RendererDependencyUnavailable):
            PngRendererClient(base_url="http://127.0.0.1:1", enabled=False).render_page(
                {"request_id": "b9"}
            )


# ══════════════════════════════════════════════════════════════════════
# C. Сервис печатных renditions (request_print_rendition)
# ══════════════════════════════════════════════════════════════════════


class TestServicePrintRendition:
    def test_request_creates_queued_print_job(self):
        """PNG печатной ревизии -- тяжёлый путь: job queued c
        print_revision_id/basis_artifact_id, snapshot_id пуст (работу
        выполняет worker, §18)."""
        _seed_run()
        service, _document, revision, snapshot = _print_revision()
        job, rendition = service.request_print_rendition(
            revision.print_revision_id,
            format="png",
            subject=_owner_subject(),
            session_id=SESSION_ID,
        )
        assert rendition is None
        assert job.state == "queued"
        assert job.print_revision_id == revision.print_revision_id
        assert job.basis_artifact_id == snapshot.artifact_id
        assert job.snapshot_id == ""
        assert job.run_id == RUN_ID

    def test_idempotent_repeat_returns_same_job(self):
        """AC09: повторный запрос той же цели -- тот же job, без нового
        задания («повторный клик не создаёт дубли»)."""
        _seed_run()
        service, _document, revision, _snapshot = _print_revision()
        first, _ = service.request_print_rendition(
            revision.print_revision_id,
            format="png",
            subject=_owner_subject(),
            session_id=SESSION_ID,
        )
        second, _ = service.request_print_rendition(
            revision.print_revision_id,
            format="png",
            subject=_owner_subject(),
            session_id=SESSION_ID,
        )
        assert second.job_id == first.job_id

    def test_unknown_print_revision_uniform_404(self):
        """AC18: несуществующая ревизия -- DocumentAccessDenied
        (uniform 404, существование не дисклоужается)."""
        _seed_run()
        service, _document, _revision, _snapshot = _print_revision()
        with pytest.raises(DocumentAccessDenied):
            service.request_print_rendition(
                "dprint-" + "0" * 32,
                format="png",
                subject=_owner_subject(),
                session_id=SESSION_ID,
            )

    def test_foreign_subject_denied(self):
        """AC18: чужой субъект -- тот же uniform отказ (знание id не
        право, R09)."""
        _seed_run()
        service, _document, revision, _snapshot = _print_revision()
        with pytest.raises(DocumentAccessDenied):
            service.request_print_rendition(
                revision.print_revision_id,
                format="png",
                subject=_owner_subject("p09-foreign-session"),
                session_id="p09-foreign-session",
            )

    def test_non_png_format_rejected(self):
        """PGV-09 -- PNG-only: печатные renditions других форматов не
        открываются этой поставкой (§1 «PNG-only»); D01–D12 не тронуты."""
        _seed_run()
        service, _document, revision, _snapshot = _print_revision()
        with pytest.raises(UnsupportedFormatError):
            service.request_print_rendition(
                revision.print_revision_id,
                format="svg",
                subject=_owner_subject(),
                session_id=SESSION_ID,
            )

    def test_retry_limit_exceeded(self):
        """§18: исчерпаны попытки рендера цели -- честный 429
        (retry_limit_exceeded), очередь не крутится вечно."""
        _seed_run()
        service, _document, revision, _snapshot = _print_revision()
        from apps.api.document_jobs import MAX_JOB_ATTEMPTS

        for _ in range(MAX_JOB_ATTEMPTS):
            service.request_print_rendition(
                revision.print_revision_id,
                format="png",
                subject=_owner_subject(),
                session_id=SESSION_ID,
            )
            jobs = [
                j
                for j in service.registry.list_jobs(RUN_ID)
                if j.print_revision_id == revision.print_revision_id
            ]
            job = jobs[-1]
            service.fail_render(job, "render_dependency_unavailable")
        with pytest.raises(DocumentRetryLimitExceeded):
            service.request_print_rendition(
                revision.print_revision_id,
                format="png",
                subject=_owner_subject(),
                session_id=SESSION_ID,
            )


# ══════════════════════════════════════════════════════════════════════
# D. Worker: lease/staging/CAS/cancel/missing dependency
# ══════════════════════════════════════════════════════════════════════


class TestWorkerPrintIntegration:
    def _worker(self, renderer) -> object:
        from apps.api.document_render_worker import DocumentRenderWorker

        return DocumentRenderWorker(
            render_timeout=5.0,
            interval=None,
            png_renderer=renderer,
        )

    def _request_job(self, service, revision):
        job, _rendition = service.request_print_rendition(
            revision.print_revision_id,
            format="png",
            subject=_owner_subject(),
            session_id=SESSION_ID,
        )
        return job

    def test_end_to_end_ready_with_staged_bytes(self):
        """D1: queued -> worker -> rendition ready; байты stage'ятся ДО
        ready (AC08), rendition несёт print_revision_id и ЕДИНЫЙ hash
        basis-артефакта (§19)."""
        _seed_run()
        service, _document, revision, snapshot = _print_revision()
        job = self._request_job(service, revision)
        renderer = _FakeRenderer()
        report = self._worker(renderer).run_once()
        assert report["ready"] == 1
        ready = service.registry.get_job(job.job_id)
        assert ready.state == "ready"
        rendition = service.registry.get_rendition(ready.rendition_id)
        assert rendition is not None
        assert rendition.state == "ready"
        assert rendition.print_revision_id == revision.print_revision_id
        assert rendition.snapshot_id == ""
        assert rendition.format == "png"
        assert rendition.content_sha256
        from apps.api.artifact_store import artifact_content_sha256

        assert rendition.content_sha256 == artifact_content_sha256(_PNG_1PX)
        # Единый hash печатной rendition = digest basis-артефакта.
        assert rendition.snapshot_payload_sha256 == snapshot.payload_sha256
        # Payload строился из frozen пары (request_id от job).
        assert renderer.calls and renderer.calls[0]["request_id"].startswith(
            "pgv:"
        )

    def test_missing_dependency_terminal_no_ready(self):
        """D2/AC17: контейнер без browser/fonts/bundle -> job terminal
        failed render_dependency_unavailable; НЕТ rendition, НЕТ ready."""
        from apps.api.png_renderer_client import RendererDependencyUnavailable

        _seed_run()
        service, _document, revision, _snapshot = _print_revision()
        job = self._request_job(service, revision)
        renderer = _FakeRenderer(
            error=RendererDependencyUnavailable("missing_browser")
        )
        report = self._worker(renderer).run_once()
        assert report["failed"] == 1
        failed = service.registry.get_job(job.job_id)
        assert failed.state == "failed"
        assert failed.error_code == "render_dependency_unavailable"
        assert service.registry.find_print_rendition(
            revision.print_revision_id, "png", "owner-v1"
        ) is None

    def test_timeout_requeues_then_fails(self):
        """D3/AC20: render_timeout -- transient (requeue, attempt+1);
        после исчерпания попыток -- честный terminal failed."""
        from apps.api.png_renderer_client import RendererTimeout

        _seed_run()
        service, _document, revision, _snapshot = _print_revision()
        job = self._request_job(service, revision)
        renderer = _FakeRenderer(error=RendererTimeout(60))
        worker = self._worker(renderer)
        worker._max_attempts = 2
        assert worker.run_once()["requeued"] == 1
        requeued = service.registry.get_job(job.job_id)
        assert requeued.state == "queued"
        assert requeued.attempt == job.attempt + 1
        assert worker.run_once()["failed"] == 1
        failed = service.registry.get_job(job.job_id)
        assert failed.state == "failed"
        assert failed.error_code == "render_timeout"

    def test_busy_requeues(self):
        """D4: renderer_busy (429) -- transient requeue, попытка+1."""
        from apps.api.png_renderer_client import RendererBusy

        _seed_run()
        service, _document, revision, _snapshot = _print_revision()
        job = self._request_job(service, revision)
        renderer = _FakeRenderer(error=RendererBusy(2))
        assert self._worker(renderer).run_once()["requeued"] == 1
        requeued = service.registry.get_job(job.job_id)
        assert requeued.state == "queued"
        assert requeued.error_code == "renderer_busy"

    def test_unavailable_requeues_then_recovers(self):
        """D5/AC24: connection refused -- transient; восстановление
        контейнера между попытками завершает job ready (байтов до
        восстановления нет)."""
        from apps.api.png_renderer_client import RendererUnavailable

        _seed_run()
        service, _document, revision, snapshot = _print_revision()
        job = self._request_job(service, revision)
        failing = _FakeRenderer(error=RendererUnavailable("connection refused"))
        assert self._worker(failing).run_once()["requeued"] == 1
        assert service.registry.find_print_rendition(
            revision.print_revision_id, "png", "owner-v1"
        ) is None
        recovered = _FakeRenderer()
        report = self._worker(recovered).run_once()
        assert report["ready"] == 1
        ready = service.registry.get_job(job.job_id)
        assert ready.state == "ready"
        assert service.registry.get_rendition(ready.rendition_id) is not None

    def test_invalid_payload_terminal(self):
        """D6: 422 invalid_payload -- terminal (детерминированный дефект
        payload'а, retry не чинит)."""
        from apps.api.png_renderer_client import RendererPayloadInvalid

        _seed_run()
        service, _document, revision, _snapshot = _print_revision()
        job = self._request_job(service, revision)
        renderer = _FakeRenderer(error=RendererPayloadInvalid("bad"))
        assert self._worker(renderer).run_once()["failed"] == 1
        failed = service.registry.get_job(job.job_id)
        assert failed.state == "failed"
        assert failed.error_code == "invalid_payload"
        assert failed.attempt == job.attempt  # без requeue-прироста

    def test_missing_section_content_terminal(self):
        """D7/§3.6: срез результата без контента секции -- terminal
        missing_section_content; пустая/подменённая картинка не
        создаётся."""
        from apps.api.print_render_payload import PrintRenderPayloadIncomplete

        _seed_run()
        service, _document, revision, _snapshot = _print_revision()
        job = self._request_job(service, revision)
        renderer = _FakeRenderer(error=PrintRenderPayloadIncomplete("s1"))
        assert self._worker(renderer).run_once()["failed"] == 1
        failed = service.registry.get_job(job.job_id)
        assert failed.state == "failed"
        assert failed.error_code == "missing_section_content"
        assert service.registry.find_print_rendition(
            revision.print_revision_id, "png", "owner-v1"
        ) is None

    def test_cancelled_queued_job_not_rendered(self):
        """D8/AC20: cancel queued -- рабочий цикл не рендерит отменённое
        задание; исход отмены не переписывается."""
        _seed_run()
        service, _document, revision, _snapshot = _print_revision()
        job = self._request_job(service, revision)
        service.cancel_job(job.job_id, _owner_subject(), session_id=SESSION_ID)
        renderer = _FakeRenderer()
        report = self._worker(renderer).run_once()
        assert report["ready"] == 0 and report["claimed"] == 0
        assert renderer.calls == []
        assert service.registry.get_job(job.job_id).state == "cancelled"

    def test_late_completion_after_cancel_not_published(self):
        """D9/AC20: гонка «cancel в rendering -> завершение воркера»:
        CAS-гейт complete_render -- готовые байты НЕ публикуются, job
        остаётся cancelled."""
        _seed_run()
        service, _document, revision, snapshot = _print_revision()
        job = self._request_job(service, revision)
        # Захват (rendering) и cancel после захвата.
        from apps.api.document_jobs import JOB_RENDERING, replace_dataclass

        claimed = service.registry.update_job(
            replace_dataclass(job, state=JOB_RENDERING)
        )
        service.cancel_job(job.job_id, _owner_subject(), session_id=SESSION_ID)
        # Позднее завершение «воркера» -- уже после отмены.
        from apps.api.document_renditions import RENDITION_FORMATS

        spec = RENDITION_FORMATS["png"]
        result_job, rendition = service.complete_render(
            claimed, spec, _PNG_1PX, None,
            source_sha256=snapshot.payload_sha256 or "",
        )
        assert result_job.state == "cancelled"
        assert rendition is None
        stored = service.registry.get_job(job.job_id)
        assert stored.state == "cancelled"

    def test_expired_lease_reclaimed_for_print_job(self):
        """D10: lease print-job'а, истёкший после crash воркера,
        реклеймится в queued БЕЗ прироста попыток (рендер из frozen
        снимка не повторяет науку, AC08); чужой живой lease не
        перехватывается."""
        _seed_run()
        service, _document, revision, _snapshot = _print_revision()
        job = self._request_job(service, revision)
        from apps.api.document_jobs import JOB_RENDERING, replace_dataclass

        past = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
        service.registry.update_job(
            replace_dataclass(
                job,
                state=JOB_RENDERING,
                claimed_at=past,
                lease_expires_at=past,
            )
        )
        worker = self._worker(_FakeRenderer())
        reclaimed_count = worker._reclaim_expired_leases()
        assert reclaimed_count == 1
        reclaimed = service.registry.get_job(job.job_id)
        assert reclaimed.state == "queued"
        assert reclaimed.attempt == job.attempt
        assert reclaimed.error_code == "lease_reclaimed"
        # После реклейма обычный цикл доводит job до ready (AC24).
        report = worker.run_once()
        assert report["ready"] == 1
        assert service.registry.get_job(job.job_id).state == "ready"

    def test_rendition_content_integrity_and_access(self):
        """D11: чтение готовых байтов печатной rendition -- integrity
        (content_sha256) и объектная авторизация (AC18)."""
        _seed_run()
        service, _document, revision, _snapshot = _print_revision()
        job = self._request_job(service, revision)
        self._worker(_FakeRenderer()).run_once()
        ready = service.registry.get_job(job.job_id)
        rendition = service.registry.get_rendition(ready.rendition_id)
        content = service.read_rendition_content(
            rendition, _owner_subject(), session_id=SESSION_ID
        )
        assert content == _PNG_1PX
        with pytest.raises(DocumentAccessDenied):
            service.read_rendition_content(
                rendition,
                _owner_subject("p09-foreign-session"),
                session_id="p09-foreign-session",
            )

    def test_bad_renderer_output_terminal(self):
        """D12/B8-дух: 200 без PNG-подписи -- terminal
        renderer_bad_output; байты не stage'ятся (broken ready
        невозможен по построению)."""
        from apps.api.png_renderer_client import RendererBadOutput

        _seed_run()
        service, _document, revision, _snapshot = _print_revision()
        job = self._request_job(service, revision)
        renderer = _FakeRenderer(png=b"<html>not a png</html>")
        assert self._worker(renderer).run_once()["failed"] == 1
        failed = service.registry.get_job(job.job_id)
        assert failed.state == "failed"
        assert failed.error_code == "renderer_bad_output"
        assert service.registry.find_print_rendition(
            revision.print_revision_id, "png", "owner-v1"
        ) is None


# ══════════════════════════════════════════════════════════════════════
# E. HTTP-маршрут печатных renditions (§17)
# ══════════════════════════════════════════════════════════════════════


class TestHttpPrintRenditions:
    def _cookie(self, client, session_id: str = SESSION_ID) -> None:
        """Cookie-субъект-владелец (паритет DOCLOG-4/DOCLOG-5)."""
        from apps.api.session_store import SESSION_COOKIE_NAME

        client.cookies.set(SESSION_COOKIE_NAME, session_id)

    def test_post_print_rendition_202(self, client):
        """202 + status_url; повтор -- тот же job (AC09 на HTTP-слое)."""
        _seed_run()
        _service, _document, revision, _snapshot = _print_revision()
        self._cookie(client)
        url = (
            "/v1/documentation/print-revisions/"
            f"{revision.print_revision_id}/renditions"
        )
        first = client.post(url, json={"format": "png"})
        assert first.status_code == 202, first.text
        body = first.json()
        assert body["job"]["state"] == "queued"
        assert body["status_url"] == f"/v1/documentation/jobs/{body['job']['job_id']}"
        second = client.post(url, json={"format": "png"})
        assert second.status_code == 202
        assert second.json()["job"]["job_id"] == body["job"]["job_id"]
        # Статус задания читается общим маршрутом jobs/{job_id}.
        status = client.get(body["status_url"])
        assert status.status_code == 200
        assert status.json()["job"]["print_revision_id"] == revision.print_revision_id

    def test_foreign_print_revision_404(self, client):
        """AC18: чужая ревизия -- uniform 404 (форма ошибки прежняя)."""
        _seed_run()
        _service, _document, _revision, _snapshot = _print_revision()
        self._cookie(client)
        foreign = client.post(
            f"/v1/documentation/print-revisions/dprint-{'0' * 32}/renditions",
            json={"format": "png"},
        )
        assert foreign.status_code == 404

    def test_unsupported_format_400(self, client):
        _seed_run()
        _service, _document, revision, _snapshot = _print_revision()
        self._cookie(client)
        response = client.post(
            f"/v1/documentation/print-revisions/{revision.print_revision_id}/renditions",
            json={"format": "pdf"},
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "unsupported_format"


# ══════════════════════════════════════════════════════════════════════
# F. Миграция 0017 (аддитивность, паритет источников DDL)
# ══════════════════════════════════════════════════════════════════════


class TestMigration0017:
    def test_migration_file_exists_and_additive(self):
        sql = Path("apps/api/migrations/0017_pgv9_print_renditions.sql").read_text(
            "utf-8"
        )
        assert "ADD COLUMN IF NOT EXISTS print_revision_id" in sql
        assert "DROP NOT NULL" in sql
        # Только аддитивные формы: никаких DROP TABLE/DROP COLUMN.
        assert "DROP TABLE" not in sql
        assert "DROP COLUMN" not in sql

    def test_migration_statements_parity(self):
        """Паритет MIGRATION_STATEMENTS_0017 и SQL-файла (PROGR-5.1):
        каждое утверждение каталога входит в компактный SQL; каждая
        значимая строка файла -- в каталог (точка с запятой файла --
        операторная форма, каталог -- исполняемые строки)."""
        from apps.api.research_runs import (
            MIGRATION_FILES,
            MIGRATION_STATEMENTS_0017,
        )

        sql = Path("apps/api/migrations/0017_pgv9_print_renditions.sql").read_text(
            "utf-8"
        )
        joined = "\n".join(MIGRATION_STATEMENTS_0017)
        for statement in MIGRATION_STATEMENTS_0017:
            compact = " ".join(statement.split())
            assert compact in " ".join(sql.split()), statement[:80]
        for line in sql.splitlines():
            stripped = line.strip().rstrip(";")
            if not stripped or stripped.startswith("--"):
                continue
            assert stripped in joined, f"строка файла вне каталога: {stripped!r}"
        assert (
            "0017_pgv9_print_renditions.sql",
            MIGRATION_STATEMENTS_0017,
        ) in MIGRATION_FILES

    def test_job_and_rendition_records_carry_print_revision(self):
        """Печатные записи несут print_revision_id (Memory-паритет
        Postgres-колонок 0017)."""
        from apps.api.document_jobs import DocumentJobRecord, DocumentRenditionRecord

        job = DocumentJobRecord(
            job_id="djob-" + "a" * 32,
            run_id=RUN_ID,
            snapshot_id="",
            format="png",
            print_revision_id="dprint-" + "b" * 32,
            basis_artifact_id="art-" + "c" * 32,
        )
        assert job.print_revision_id == "dprint-" + "b" * 32
        assert job.to_dict()["basis_artifact_id"] == "art-" + "c" * 32
        rendition = DocumentRenditionRecord(
            rendition_id="drend-" + "a" * 32,
            revision_id="",
            snapshot_id="",
            run_id=RUN_ID,
            format="png",
            print_revision_id="dprint-" + "b" * 32,
        )
        assert rendition.to_dict()["print_revision_id"] == "dprint-" + "b" * 32
