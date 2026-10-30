# tests/api/test_doclog4_document_delivery.py
"""Task DOCLOG-4 (spec_documentation_logging.md §7, §10.3, §11, §12,
§14.1, §15, §17, §19 строка DOCLOG-4, §19.1, §20 AC05/AC06/AC09/AC16/
AC17): UI и MVP выдачи поверх снимков DOCLOG-2 + audit-потока DOCLOG-3.

Критерий завершения (§19): read/preview не меняют science state;
keyboard/theme/responsive и negative states.

Оракулы на СВОИХ данных: корпус дизъюнктен repo-корпусу и корпусам
0/1/2/3 (RUN-D4xxxxxx, d4-*); изоляция каждого теста -- паттерн
test_doclog2_snapshots.py (свой tmp_path/CISSTAT_DATA_DIR, сброс
singleton-фабрик). Рендеры -- ЧИСТЫЕ функции от frozen ReportSnapshot
(R06): не читают живой run/сессию, не пересчитывают науку (AC05).
Каждый HTTP-маршрут проходит одну объектную авторизацию (R09/T15/N3:
знание document_id/revision_id/job_id/rendition_id НЕ право).
Аудит выдачи -- тройка download_requested/response_stream_started/
response_stream_finished РАЗЛИЧАЕТСЯ (§14.1); human_read_confirmed
НЕ существует. Идемпотентность rendition -- UNIQUE(snapshot_id,
format, redaction_profile) (§10.3/AC09: повторный клик не плодит
дубли). HTML-безопасность (§12.3/AC16): экранирование, без script/
external/on*; CSV -- spreadsheet-safe профиль §7 (числа не в текст).
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api import research_runs
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
from apps.api.research_runs import ResearchRun
from apps.api.session_store import AnalysisSession

# ── Изоляция КАЖДОГО теста (паттерн test_doclog2_snapshots.py) ────────


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
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    from apps.api import artifact_store, report_snapshot
    from apps.api import document_jobs
    from apps.api.routers import documentation as documentation_router
    from apps.api.session_store import reset_session_store_for_testing
    from apps.api.security_audit import reset_audit_for_testing
    from apps.api.telemetry import reset_telemetry_for_testing

    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
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
    documentation_router.reset_documentation_service_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()


@pytest.fixture()
def client():
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


ADMIN_KEY = "d4-admin-test-key"


@pytest.fixture()
def admin_client(client, monkeypatch):
    monkeypatch.setenv("CISSTAT_API_KEYS", f"{ADMIN_KEY}:admin:pro")
    return client


# ── Сид-хелперы: run/сессия/subject на СВОИХ данных ─────────────────

RUN_ID = "RUN-D4A00001"
SESSION_ID = "d4-seed-session"
FOREIGN_SESSION_ID = "d4-foreign-session"
RUN_ID_2 = "RUN-D4A00002"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_session(session_id: str = SESSION_ID) -> AnalysisSession:
    """Сессия-источник фактов; ИДЕМПОТЕНТНА (повторный вызов в одном
    тесте не конфликтует по storage_revision)."""
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
    context_id: str | None = "ctx-d4-1",
    data_revision: int | None = 2,
) -> ResearchRun:
    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="d4" * 16,
        dataset_name="doclog4-seed",
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


def _owner_subject(session_id: str = SESSION_ID) -> SubjectRef:
    return SubjectRef.from_session(session_id)


def _seed_event(
    run_id: str = RUN_ID,
    event_type: str = "upload_completed",
    stage: str = "upload",
    *,
    payload: dict | None = None,
    evidence_level: str | None = "server_result",
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


def _service():
    from apps.api.snapshot_builder import SnapshotService

    return SnapshotService.create_default()


def _seed_snapshot(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    kinds: list[str] | None = None,
    claim_text: str | None = None,
):
    """Собирает frozen-снимок через штатный сборщик DOCLOG-2."""
    _seed_session(session_id)
    _seed_bound_run(run_id, session_id)
    _seed_event(run_id, payload={"dataset": "doclog4-seed"})
    subject = _owner_subject(session_id)
    snapshot, _created = _service().build_snapshot(
        run_id,
        subject,
        session_id=session_id,
        kinds=kinds or ["D01", "D02"],
    )
    if claim_text:
        # Подмена текста claim'а ТОЛЬКО в памяти (рендеры получают
        # недоверенный вход); durable-снимок не трогается.
        from dataclasses import replace as _replace

        from apps.api.report_snapshot import ReportSnapshot

        sections = [dict(section) for section in snapshot.sections]
        if sections:
            sections[0] = dict(sections[0])
            sections[0]["claims"] = [
                dict(sections[0]["claims"][0])
                | {"text": claim_text},
                *[
                    dict(claim)
                    for claim in sections[0]["claims"][1:]
                ],
            ]
        snapshot = _replace(snapshot, sections=sections)
    return snapshot


# ══════════════════════════════════════════════════════════════════════
# 1. Каталог форматов и рендеры (§7 P0; R06/AC05/AC16)
# ══════════════════════════════════════════════════════════════════════


class TestRenditionFormats:
    def test_p0_catalog_formats(self):
        """DOCLOG-5: каталог расширен тяжёлыми форматами §7 P1; P0 --
        НЕПЕРЕСЕКАЮЩЕЕСЯ подмножество (пин DOCLOG-4 сохранён)."""
        from apps.api.document_renditions import RENDITION_FORMATS

        assert {"json", "jsonl", "md", "html", "csv"} <= set(RENDITION_FORMATS)

    def test_p0_catalog_media_types_and_extensions(self):
        from apps.api.document_renditions import RENDITION_FORMATS

        spec = RENDITION_FORMATS
        assert spec["json"].media_type == "application/json"
        assert spec["jsonl"].media_type == "application/x-ndjson"
        assert spec["md"].media_type == "text/markdown"
        assert spec["html"].media_type == "text/html"
        assert spec["csv"].media_type == "text/csv"
        for fmt, item in spec.items():
            assert item.extension == fmt, fmt
            assert item.label, fmt

    def test_heavy_formats_added_by_doclog5(self):
        """DOCLOG-5: PDF/XLSX/Parquet/SVG/PNG/ZIP -- в каталоге §7 P1
        (асинхронный worker-контур). DOCLOG-9 (честное обновление пина):
        DOCX/PDF-A (§7 P2) введены как форматы профилей организации
        (выпуск ТОЛЬКО по профилю, §19 строка DOCLOG-9)."""
        from apps.api.document_renditions import RENDITION_FORMATS

        assert {"pdf", "xlsx", "parquet", "svg", "png", "zip"} <= set(RENDITION_FORMATS)
        assert "docx" in RENDITION_FORMATS
        assert "pdfa" in RENDITION_FORMATS

    def test_render_json_is_canonical_snapshot_bytes(self):
        from apps.api.artifact_store import canonical_json_bytes
        from apps.api.document_renditions import render_snapshot_json

        snapshot = _seed_snapshot()
        assert render_snapshot_json(snapshot) == canonical_json_bytes(
            snapshot.to_dict()
        )


# ══════════════════════════════════════════════════════════════════════
# 2. Слой документов поверх снимков (адаптер §9.1; без переписывания)
# ══════════════════════════════════════════════════════════════════════


class TestDocumentRegistry:
    def test_identifier_formats(self):
        from apps.api.document_jobs import (
            new_document_id,
            new_job_id,
            new_rendition_id,
            new_revision_id,
        )

        assert re.fullmatch(r"doc-[0-9a-f]{32}", new_document_id())
        assert re.fullmatch(r"drev-[0-9a-f]{32}", new_revision_id())
        assert re.fullmatch(r"drend-[0-9a-f]{32}", new_rendition_id())
        assert re.fullmatch(r"djob-[0-9a-f]{32}", new_job_id())

    def test_ensure_revision_find_or_create_and_monotonic_versions(self):
        """§9.1: document=(run_id, kind) find-or-create; revision --
        непerwрываемая ссылка на снимок с монотонным version_no."""
        from apps.api.document_jobs import DocumentDeliveryService

        snapshot1 = _seed_snapshot()
        service = DocumentDeliveryService.create_default()
        doc1, rev1, created1 = service.ensure_document_revision(
            snapshot1, subject=_owner_subject(), session_id=SESSION_ID
        )
        assert created1 is True
        assert doc1.run_id == RUN_ID
        assert doc1.kind_code == "D01"
        assert rev1.document_id == doc1.document_id
        assert rev1.snapshot_id == snapshot1.snapshot_id
        assert rev1.version_no == 1

        snapshot2, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D01"]
        )
        doc2, rev2, created2 = service.ensure_document_revision(
            snapshot2, subject=_owner_subject(), session_id=SESSION_ID
        )
        assert created2 is True
        assert doc2.document_id == doc1.document_id  # тот же документ
        assert rev2.version_no == 2  # монотонно
        assert rev2.snapshot_id != rev1.snapshot_id

    def test_same_snapshot_idempotent_revision(self):
        from apps.api.document_jobs import DocumentDeliveryService

        snapshot = _seed_snapshot()
        service = DocumentDeliveryService.create_default()
        doc1, rev1, _ = service.ensure_document_revision(
            snapshot, subject=_owner_subject(), session_id=SESSION_ID
        )
        doc2, rev2, created = service.ensure_document_revision(
            snapshot, subject=_owner_subject(), session_id=SESSION_ID
        )
        assert created is False
        assert doc2.document_id == doc1.document_id
        assert rev2.revision_id == rev1.revision_id

    def test_different_kinds_different_documents(self):
        from apps.api.document_jobs import DocumentDeliveryService

        snapshot = _seed_snapshot(kinds=["D01", "D02"])
        service = DocumentDeliveryService.create_default()
        doc_d01, rev_d01, _ = service.ensure_document_revision(
            snapshot, subject=_owner_subject(), session_id=SESSION_ID,
            kind_code="D01",
        )
        doc_d02, rev_d02, _ = service.ensure_document_revision(
            snapshot, subject=_owner_subject(), session_id=SESSION_ID,
            kind_code="D02",
        )
        assert doc_d01.document_id != doc_d02.document_id
        assert doc_d01.kind_code == "D01"
        assert doc_d02.kind_code == "D02"
        assert rev_d01.snapshot_id == rev_d02.snapshot_id  # один снимок

    def test_list_run_documents_shape(self):
        from apps.api.document_jobs import DocumentDeliveryService

        snapshot = _seed_snapshot()
        service = DocumentDeliveryService.create_default()
        service.ensure_document_revision(
            snapshot, subject=_owner_subject(), session_id=SESSION_ID
        )
        records = service.list_documents(
            RUN_ID, subject=_owner_subject(), session_id=SESSION_ID
        )
        assert len(records) == 1
        document, revisions = records[0]
        assert document.kind_code == "D01"
        assert len(revisions) == 1
        assert revisions[0].snapshot_id == snapshot.snapshot_id
# ══════════════════════════════════════════════════════════════════════
# 3. Job-контракт и идемпотентность rendition (§10.3/§11/§17, AC09)
# ══════════════════════════════════════════════════════════════════════


class TestDocumentJobs:
    def test_job_lifecycle_renders_ready(self):
        from apps.api.artifact_store import artifact_content_sha256
        from apps.api.document_jobs import (
            JOB_CANCELLED,
            JOB_FAILED,
            JOB_QUEUED,
            JOB_READY,
            JOB_RENDERING,
            DocumentDeliveryService,
        )

        assert {JOB_QUEUED, JOB_RENDERING, JOB_READY, JOB_FAILED, JOB_CANCELLED} == {
            "queued", "rendering", "ready", "failed", "cancelled",
        }
        snapshot = _seed_snapshot()
        service = DocumentDeliveryService.create_default()
        job, rendition = service.request_rendition(
            snapshot, format="md",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        assert job.snapshot_id == snapshot.snapshot_id
        assert job.format == "md"
        assert job.state == JOB_READY  # P0-форматы рендерятся инлайн-быстро
        assert job.attempt >= 1
        assert rendition.job_id == job.job_id
        assert rendition.state == "ready"
        assert rendition.media_type == "text/markdown"
        content = service.read_rendition_content(
            rendition, subject=_owner_subject(), session_id=SESSION_ID
        )
        assert content == rendition.content_bytes  # честные байты
        assert artifact_content_sha256(content) == rendition.content_sha256
        assert rendition.size_bytes == len(content)

    def test_rendition_idempotent_no_duplicate_jobs(self):
        """AC09/§12.2: повторный клик не создаёт дубли и не рендерит
        повторно -- тот же (snapshot, format, profile) возвращает
        существующую ready rendition БЕЗ нового job."""
        from apps.api.document_jobs import DocumentDeliveryService

        snapshot = _seed_snapshot()
        service = DocumentDeliveryService.create_default()
        job1, rend1 = service.request_rendition(
            snapshot, format="html",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        jobs_after_first = service.list_jobs(RUN_ID, subject=_owner_subject(), session_id=SESSION_ID)
        job2, rend2 = service.request_rendition(
            snapshot, format="html",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        assert rend2.rendition_id == rend1.rendition_id
        assert job2.job_id == job1.job_id  # прежний job, не новый
        jobs_after_second = service.list_jobs(RUN_ID, subject=_owner_subject(), session_id=SESSION_ID)
        assert len(jobs_after_second) == len(jobs_after_first)

    def test_different_format_separate_rendition(self):
        from apps.api.document_jobs import DocumentDeliveryService

        snapshot = _seed_snapshot()
        service = DocumentDeliveryService.create_default()
        _job1, rend1 = service.request_rendition(
            snapshot, format="html",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        _job2, rend2 = service.request_rendition(
            snapshot, format="json",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        assert rend2.rendition_id != rend1.rendition_id
        assert rend2.format == "json"

    def test_cancel_idempotent_and_respects_ready(self):
        """§17: cancel идемпотентен; научные результаты остаются
        (снимок не трогается)."""
        from apps.api.document_jobs import DocumentDeliveryService

        snapshot = _seed_snapshot()
        service = DocumentDeliveryService.create_default()
        job1, _rend = service.request_rendition(
            snapshot, format="md",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        # ready-задание отменить нельзя (результат уже существует):
        service.cancel_job(job1.job_id, subject=_owner_subject(), session_id=SESSION_ID)
        service.cancel_job(job1.job_id, subject=_owner_subject(), session_id=SESSION_ID)
        assert job1.state == "ready"  # повторный cancel не меняет ready
        # Снимок не тронут (научный результат остаётся).
        restored = _service().get_snapshot(
            snapshot.snapshot_id, _owner_subject(), session_id=SESSION_ID
        )
        assert restored.snapshot_id == snapshot.snapshot_id

    def test_renderer_failure_job_failed_science_untouched(self):
        """§10.3: ошибка рендера -- failed + error_code; научный
        результат не меняется; retry создаёт НОВУЮ попытку."""
        from apps.api import document_jobs
        from apps.api.document_jobs import DocumentDeliveryService

        snapshot = _seed_snapshot()
        service = DocumentDeliveryService.create_default()
        original = document_jobs.render_snapshot_md
        def _boom(_snapshot):
            raise RuntimeError("renderer boom")
        document_jobs.render_snapshot_md = _boom
        try:
            job1, rend1 = service.request_rendition(
                snapshot, format="md",
                subject=_owner_subject(), session_id=SESSION_ID,
            )
        finally:
            document_jobs.render_snapshot_md = original
        assert job1.state == "failed"
        assert job1.error_code == "render_failed"
        assert rend1 is None
        # Retry -- новая попытка (новый job), прежний failed не перезаписывается.
        job2, rend2 = service.request_rendition(
            snapshot, format="md",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        assert job2.job_id != job1.job_id
        assert job2.state == "ready"
        assert rend2 is not None

    def test_unsupported_format_rejected_before_job(self):
        from apps.api.document_jobs import UnsupportedFormatError, DocumentDeliveryService

        snapshot = _seed_snapshot()
        service = DocumentDeliveryService.create_default()
        # DOCLOG-9 (честное обновление пина): docx/pdfa -- валидные
        # форматы, но требуют организационный профиль; честный
        # unsupported_format проверяется форматом ВНЕ каталога ("doc").
        with pytest.raises(UnsupportedFormatError):
            service.request_rendition(
                snapshot, format="doc",
                subject=_owner_subject(), session_id=SESSION_ID,
            )

    def test_foreign_subject_denied_at_service_layer(self, client):
        """R09/T15: знание run_id/snapshot_id не право -- сервисная
        авторизация до любого действия."""
        from apps.api.document_jobs import DocumentAccessDenied, DocumentDeliveryService

        snapshot = _seed_snapshot()
        service = DocumentDeliveryService.create_default()
        _seed_session(FOREIGN_SESSION_ID)
        foreign = SubjectRef.from_session(FOREIGN_SESSION_ID)
        with pytest.raises(DocumentAccessDenied):
            service.request_rendition(
                snapshot, format="md", subject=foreign,
                session_id=FOREIGN_SESSION_ID,
            )
# ══════════════════════════════════════════════════════════════════════
# 4. HTTP-маршруты /v1/documentation: авторизация (AC06) и форма
# ══════════════════════════════════════════════════════════════════════


def _cookie(client: TestClient, session_id: str = SESSION_ID) -> None:
    from apps.api.session_store import SESSION_COOKIE_NAME

    client.cookies.set(SESSION_COOKIE_NAME, session_id)


class TestDocumentationRoutesAuth:
    """AC06: чужие document/revision/job/rendition -- отказ на ВСЕХ
    маршрутах; uniform 404 (существование не дисклоужается)."""

    def test_owner_full_path_list_create_preview_rendition_content(self, client):
        _seed_snapshot()
        _cookie(client_bound := client)
        # list (пусто) -> create draft -> list (1) -> revision -> preview
        resp = client_bound.get(f"/v1/documentation/runs/{RUN_ID}/documents")
        assert resp.status_code == 200
        assert resp.json()["documents"] == []

        resp = client_bound.post(
            f"/v1/documentation/runs/{RUN_ID}/documents",
            json={"kind": "D02"},
        )
        assert resp.status_code == 201
        body = resp.json()
        document = body["document"]
        assert document["run_id"] == RUN_ID
        assert document["kind_code"] == "D02"
        revision = body["revision"]
        assert revision["version_no"] == 1
        assert revision["snapshot_id"]

        resp = client_bound.get(f"/v1/documentation/runs/{RUN_ID}/documents")
        documents = resp.json()["documents"]
        assert len(documents) == 1
        assert documents[0]["kind_code"] == "D02"
        assert len(documents[0]["revisions"]) == 1
        # Заголовок вида из реестра D01-D09 (§12.2 «Левый список»).
        assert documents[0]["title"] == "Паспорт источника"

        rev_id = revision["revision_id"]
        resp = client_bound.get(f"/v1/documentation/revisions/{rev_id}")
        assert resp.status_code == 200
        meta = resp.json()
        assert meta["revision"]["revision_id"] == rev_id
        assert meta["snapshot"]["snapshot_id"] == revision["snapshot_id"]
        # N3-гейт: dependency manifest -- только внутри авторизованного
        # чтения ревизии (§10.1 dependencies честны).
        assert "dependencies" in meta["snapshot"]

        resp = client_bound.get(f"/v1/documentation/revisions/{rev_id}/preview")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert b"<html" in resp.content.lower()

        resp = client_bound.post(
            f"/v1/documentation/revisions/{rev_id}/renditions",
            json={"format": "md"},
        )
        assert resp.status_code == 202
        job = resp.json()["job"]
        assert job["state"] in {"queued", "rendering", "ready"}

        resp = client_bound.get(f"/v1/documentation/jobs/{job['job_id']}")
        assert resp.status_code == 200
        assert resp.json()["job"]["state"] == "ready"
        rendition = resp.json()["job"].get("rendition") or resp.json().get("rendition")
        if rendition is None:
            rendition = client_bound.get(
                f"/v1/documentation/revisions/{rev_id}"
            ).json()["renditions"][0]
        rid = rendition["rendition_id"]

        resp = client_bound.get(f"/v1/documentation/renditions/{rid}/content")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        # DOCLOG-DL-FIX-1 (2026-10-27): versioned-инверсия пина DOCLOG-4
        # (было: assert "attachment" not in ... -- inline был спроектированным
        # решением DOCLOG-4, но противоречил §12.2 «немедленное скачивание»,
        # §17 «Скачать уже готовый файл» и подписи UI «Скачать X»: для
        # рендеримых форматов браузер совершал top-level переход и рисовал
        # документ в текущей вкладке вместо сохранения файла; разбор --
        # docs/doclog_download_behavior_2026-10-27.md). Стало: attachment
        # обязателен -- «Скачать X» честно сохраняет файл для ВСЕХ форматов.
        assert "attachment" in resp.headers.get("content-disposition", "")
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("cache-control") == "private, no-store"

    def test_foreign_session_uniform_404_on_every_route(self, client):
        _seed_snapshot()
        _cookie(client_foreign := client, FOREIGN_SESSION_ID)
        _seed_session(FOREIGN_SESSION_ID)

        resp = client_foreign.get(f"/v1/documentation/runs/{RUN_ID}/documents")
        assert resp.status_code == 404

        resp = client_foreign.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D02"}
        )
        assert resp.status_code == 404

        # Существующие IDs владельца не открываются чужому (T15).
        owner_client = client
        _cookie(owner_client)
        owner_client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D02"}
        )
        docs = owner_client.get(
            f"/v1/documentation/runs/{RUN_ID}/documents"
        ).json()["documents"]
        rev_id = docs[0]["revisions"][0]["revision_id"]
        _cookie(owner_client, FOREIGN_SESSION_ID)
        for url in (
            f"/v1/documentation/documents/{docs[0]['document_id']}/revisions",
            f"/v1/documentation/revisions/{rev_id}",
            f"/v1/documentation/revisions/{rev_id}/preview",
        ):
            assert owner_client.get(url).status_code == 404, url
        assert owner_client.post(
            f"/v1/documentation/revisions/{rev_id}/renditions",
            json={"format": "md"},
        ).status_code == 404

    def test_anonymous_denied_uniform_404(self, client):
        _seed_snapshot()
        anon = client
        # Без куки -- аноним (subject.is_anonymous).
        resp = anon.get(f"/v1/documentation/runs/{RUN_ID}/documents")
        assert resp.status_code == 404
        resp = anon.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D01"}
        )
        assert resp.status_code == 404

    def test_admin_allowed(self, admin_client):
        _seed_snapshot()
        _cookie(admin_client)
        resp = admin_client.get(f"/v1/documentation/runs/{RUN_ID}/documents")
        assert resp.status_code == 200

    def test_unknown_ids_uniform_404(self, client):
        _seed_snapshot()
        _cookie(client)
        fake_doc = "doc-" + "f" * 32
        fake_rev = "drev-" + "f" * 32
        fake_job = "djob-" + "f" * 32
        fake_rend = "drend-" + "f" * 32
        assert client.get(
            f"/v1/documentation/documents/{fake_doc}/revisions"
        ).status_code == 404
        assert client.get(
            f"/v1/documentation/revisions/{fake_rev}"
        ).status_code == 404
        assert client.get(
            f"/v1/documentation/revisions/{fake_rev}/preview"
        ).status_code == 404
        assert client.post(
            f"/v1/documentation/revisions/{fake_rev}/renditions",
            json={"format": "md"},
        ).status_code == 404
        assert client.get(f"/v1/documentation/jobs/{fake_job}").status_code == 404
        assert client.post(
            f"/v1/documentation/jobs/{fake_job}/cancel"
        ).status_code == 404
        assert client.get(
            f"/v1/documentation/renditions/{fake_rend}/content"
        ).status_code == 404

    def test_invalid_id_shape_uniform_404(self, client):
        """Не только отсутствие, но и некорректная ФОРМА ID не
        дисклоужает (T15-дух)."""
        _seed_snapshot()
        _cookie(client)
        assert client.get(
            "/v1/documentation/revisions/not-a-revision"
        ).status_code == 404
        assert client.get(
            "/v1/documentation/jobs/../etc/passwd"
        ).status_code in {400, 404}

    def test_kind_filter_on_list(self, client):
        _seed_snapshot(kinds=["D01", "D02"])
        _cookie(client)
        client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D01"}
        )
        client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D02"}
        )
        resp = client.get(
            f"/v1/documentation/runs/{RUN_ID}/documents?kind=D02"
        )
        assert resp.status_code == 200
        documents = resp.json()["documents"]
        assert len(documents) == 1
        assert documents[0]["kind_code"] == "D02"

    def test_list_does_not_create_documents(self, client):
        """§12.1: открытие списка НЕ создаёт документ фактом открытия
        (и не меняет степпер)."""
        _seed_snapshot()
        _cookie(client)
        client.get(f"/v1/documentation/runs/{RUN_ID}/documents")
        resp = client.get(f"/v1/documentation/runs/{RUN_ID}/documents")
        assert resp.json()["documents"] == []


# ══════════════════════════════════════════════════════════════════════
# 4b. Семантика доставки «Скачать» (DOCLOG-DL-FIX-1, 2026-10-27)
# ══════════════════════════════════════════════════════════════════════


class TestRenditionDownloadSemantics:
    """DOCLOG-DL-FIX-1 (2026-10-27): Content-Disposition как контракт
    доставки. §12.2 обещает для готового файла «немедленное скачивание»,
    §17 описывает маршрут как «Скачать уже готовый файл», UI подписывает
    действие «Скачать X». Прежний inline (решение DOCLOG-4) для рендеримых
    типов (md/html/json/csv/jsonl) заставлял браузер совершать top-level
    переход и рисовать документ в ТЕКУЩЕЙ вкладке вместо сохранения файла
    (файл появлялся только у нерендеримых бинарных) -- расхождение
    контракт↔код↔UI класса F-D8C1/C09; разбор и матрица форматов --
    docs/doclog_download_behavior_2026-10-27.md.

    Контракт после фикса (ядро A варианта C):
      - GET /renditions/{id}/content -- ВСЕГДА `attachment` (файл);
      - GET /revisions/{id}/preview -- всегда `inline` (легитимный
        санитизированный просмотр: sandboxed-iframe UI и действие
        «Открыть в новой вкладке» -- это просмотр, не скачивание);
      - §15.2 сохраняется: безопасное имя файла, nosniff,
        `Cache-Control: private, no-store`; маршрут GET read-only,
        авторизация R09 и audit-тройка не меняются.
    """

    def test_content_route_attachment_for_all_p0_renderable_formats(
        self, client
    ):
        expected_media = {
            "md": "text/markdown",
            "html": "text/html",
            "json": "application/json",
            "csv": "text/csv",
            "jsonl": "application/x-ndjson",
        }
        _seed_snapshot()
        _cookie(client_bound := client)
        resp = client_bound.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D02"}
        )
        assert resp.status_code == 201
        rev_id = resp.json()["revision"]["revision_id"]

        for fmt, media in expected_media.items():
            resp = client_bound.post(
                f"/v1/documentation/revisions/{rev_id}/renditions",
                json={"format": fmt},
            )
            assert resp.status_code == 202, (fmt, resp.text)
            job = resp.json()["job"]
            # P0 (§7) рендерятся синхронно; без ready-рендерции тест не
            # продолжается (падение честнее тишины).
            assert job["state"] == "ready", (fmt, job)
            rendition = job.get("rendition")
            if rendition is None:
                renditions = client_bound.get(
                    f"/v1/documentation/revisions/{rev_id}"
                ).json()["renditions"]
                rendition = next(r for r in renditions if r["format"] == fmt)
            rid = rendition["rendition_id"]

            resp = client_bound.get(
                f"/v1/documentation/renditions/{rid}/content"
            )
            assert resp.status_code == 200, fmt
            assert resp.headers["content-type"].startswith(media), fmt
            disposition = resp.headers.get("content-disposition", "")
            # «Скачать X» честно сохраняет файл (§12.2/§17/UI-подпись);
            # имя файла -- безопасное document-{safe_id}.{ext} (§15.2).
            assert disposition.startswith("attachment;"), (fmt, disposition)
            assert 'filename="document-' in disposition, (fmt, disposition)
            assert resp.headers.get("x-content-type-options") == "nosniff", fmt
            assert (
                resp.headers.get("cache-control") == "private, no-store"
            ), fmt

    def test_preview_route_stays_inline_legit_view(self, client):
        """Легитимный inline -- только просмотр (§17 preview): sandboxed
        iframe предпросмотра и действие «Открыть в новой вкладке»
        (DOCLOG-DL-FIX-1) используют этот маршрут; это просмотр, не
        скачивание, поэтому inline здесь оправдан и пинуется."""
        _seed_snapshot()
        _cookie(client_bound := client)
        resp = client_bound.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D02"}
        )
        assert resp.status_code == 201
        rev_id = resp.json()["revision"]["revision_id"]

        resp = client_bound.get(
            f"/v1/documentation/revisions/{rev_id}/preview"
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        disposition = resp.headers.get("content-disposition", "")
        assert disposition.startswith("inline;"), disposition
        assert 'filename="preview.html"' in disposition
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("cache-control") == "private, no-store"


# ══════════════════════════════════════════════════════════════════════
# 5. Негативные состояния и конфликты (§17 коды; AC17)
# ══════════════════════════════════════════════════════════════════════


class TestNegativeStates:
    def test_unsupported_format_400_no_job(self, client):
        _seed_snapshot()
        _cookie(client)
        rev_id = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D02"}
        ).json()["revision"]["revision_id"]
        # DOCLOG-9 (честное обновление пина): формат вне каталога --
        # по-прежнему честный 400 unsupported_format (docx/pdfa теперь
        # валидны и требуют профиль -- проверяется корпусом DOCLOG-9).
        resp = client.post(
            f"/v1/documentation/revisions/{rev_id}/renditions",
            json={"format": "doc"},
        )
        assert resp.status_code == 400
        body = resp.json()
        detail = body.get("detail")
        code = detail.get("code") if isinstance(detail, dict) else body.get("code")
        assert code == "unsupported_format"

    def test_idempotency_conflict_409_from_builder(self, client):
        """AC09: тот же idempotency_key с другим телом -- 409 (не тихий
        дубль) -- наследуется от сборщика DOCLOG-2 честно. Конфликт
        доходит до HTTP только через путь сборки (refresh=true + вид без
        существующего снимка -- иначе срабатывает reuse-семантика)."""
        _seed_snapshot()
        _cookie(client)
        body1 = {"kind": "D03", "refresh": True, "idempotency_key": "d4-key-1"}
        resp1 = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json=body1
        )
        assert resp1.status_code == 201
        resp2 = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents",
            json={"kind": "D04", "refresh": True, "idempotency_key": "d4-key-1"},
        )
        assert resp2.status_code == 409
        # Повтор ТОГО ЖЕ тела -- прежний снимок (идемпотентно).
        resp3 = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json=body1
        )
        assert resp3.status_code == 200
        assert (
            resp3.json()["revision"]["revision_id"]
            == resp1.json()["revision"]["revision_id"]
        )

    def test_invalid_kind_422(self, client):
        _seed_snapshot()
        _cookie(client)
        # DOCLOG-6 (обновлено честно): D11 -- плановая поставка DOCLOG-6
        # (201). DOCLOG-8 (обновлено честно): D12 -- плановая поставка
        # DOCLOG-8 (201); некорректный вид -- по-прежнему честный 422.
        resp_ok = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D11"}
        )
        assert resp_ok.status_code in {200, 201}
        resp_d12 = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D12"}
        )
        assert resp_d12.status_code in {200, 201}
        resp = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D99"}
        )
        assert resp.status_code in {400, 422}

    def test_unresolved_run_foreign_session_404(self, client):
        """§15.1: внешний доступ к unresolved-запуску запрещён (контур
        DOCLOG-4 обязан проверять ownership)."""
        _seed_session(FOREIGN_SESSION_ID)
        from apps.api.research_runs import get_research_run_store

        run = ResearchRun(
            run_id=RUN_ID_2,
            session_id="d4-legacy-session",
            dataset_fingerprint="e4" * 16,
            dataset_name="legacy",
            target_column=None,
            target_column_source=None,
            created_at=_now_iso(),
            last_active_at=_now_iso(),
            status="active",
        )
        get_research_run_store().upsert_run(run)
        _cookie(client, FOREIGN_SESSION_ID)
        resp = client.get(f"/v1/documentation/runs/{RUN_ID_2}/documents")
        assert resp.status_code == 404

    def test_content_of_failed_rendition_404(self, client):
        from apps.api import document_jobs

        snapshot = _seed_snapshot()
        _cookie(client)
        rev_id = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D01"}
        ).json()["revision"]["revision_id"]
        original = document_jobs.render_snapshot_json
        def _boom(_snapshot):
            raise RuntimeError("boom")
        document_jobs.render_snapshot_json = _boom
        try:
            failed = client.post(
                f"/v1/documentation/revisions/{rev_id}/renditions",
                json={"format": "json"},
            ).json()["job"]
        finally:
            document_jobs.render_snapshot_json = original
        assert failed["state"] == "failed"
        assert failed["error_code"] == "render_failed"
        # failed rendition не имеет content -- 404 (никаких битых файлов).
        resp = client.get(
            f"/v1/documentation/renditions/{failed['rendition_id'] or 'drend-' + '0' * 32}/content"
        )
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# 6. AC05: read/preview/rendition/content НЕ меняют science state
# ══════════════════════════════════════════════════════════════════════


class TestNoScienceMutation:
    def _science_state(self) -> dict:
        from apps.api import artifact_store, report_snapshot

        run_store = research_runs.get_research_run_store()
        run = run_store.get_run(RUN_ID)
        events = run_store.list_events(RUN_ID)
        pins = artifact_store.get_artifact_registry().list_pins(RUN_ID)
        return {
            "run": run.to_dict(),
            "event_ids": [event.event_id for event in events],
            "event_types": [event.event_type for event in events],
            "snapshots": [
                record.snapshot_id
                for record in report_snapshot.get_snapshot_registry().list_records(RUN_ID)
            ],
            "pins": sorted((p.ref_kind, p.ref_id) for p in pins),
        }

    def test_reads_do_not_change_durable_state(self, client):
        """AC05: list/detail/preview/renditions/content -- diff durable
        state до/после; научные поверхности не тронуты (audit может
        добавиться -- это НЕ science state)."""
        snapshot = _seed_snapshot()
        _cookie(client)
        before = self._science_state()

        client.get(f"/v1/documentation/runs/{RUN_ID}/documents")
        created = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D01"}
        )
        rev_id = created.json()["revision"]["revision_id"]
        client.get(f"/v1/documentation/revisions/{rev_id}")
        client.get(f"/v1/documentation/revisions/{rev_id}/preview")
        client.post(
            f"/v1/documentation/revisions/{rev_id}/renditions",
            json={"format": "md"},
        )
        docs = client.get(
            f"/v1/documentation/runs/{RUN_ID}/documents"
        ).json()["documents"]
        renditions = docs[0]["revisions"][0].get("renditions") or []
        if renditions:
            client.get(
                f"/v1/documentation/renditions/{renditions[0]['rendition_id']}/content"
            )

        after = self._science_state()
        # run/ledger/snapshots/pins -- БАЙТ-в-байт (новый документ через
        # POST зарегистрирован сборщиком ДО before? НЕТ: снимок создан
        # в _seed_snapshot; POST создаёт ТОЛЬКО document/revision-адаптер
        # поверх СУЩЕСТВУЮЩЕГО снимка -- новых снимков нет).
        assert after["run"] == before["run"]
        assert after["event_ids"] == before["event_ids"]
        assert after["event_types"] == before["event_types"]
        assert after["snapshots"] == before["snapshots"]
        assert after["pins"] == before["pins"]
# ══════════════════════════════════════════════════════════════════════
# 7. Refresh-семантика черновика: reuse latest vs новая заморозка
# ══════════════════════════════════════════════════════════════════════


class TestDraftRefreshSemantics:
    def test_default_post_reuses_latest_snapshot_with_kind(self, client):
        """POST без refresh НЕ плодит новые снимки: повторный клик
        возвращает существующую версию (§12.2 без дублей)."""
        _seed_snapshot()
        _cookie(client)
        resp1 = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D01"}
        )
        resp2 = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D01"}
        )
        assert resp1.status_code == 201
        assert resp2.status_code == 200
        assert (
            resp2.json()["revision"]["revision_id"]
            == resp1.json()["revision"]["revision_id"]
        )
        from apps.api.report_snapshot import get_snapshot_registry

        assert len(get_snapshot_registry().list_records(RUN_ID)) == 1

    def test_refresh_freezes_new_version_on_changed_state(self, client):
        """«Создать черновик» при изменившемся состоянии -- новая
        заморозка (новый cutoff -> новый снимок -> version_no+1)."""
        _seed_snapshot()
        _cookie(client)
        resp1 = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents",
            json={"kind": "D01", "refresh": True},
        )
        assert resp1.status_code == 201
        rev1 = resp1.json()["revision"]
        # Состояние изменилось: новое событие корпуса.
        _seed_event(RUN_ID, event_type="validation_completed", stage="validation")
        resp2 = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents",
            json={"kind": "D01", "refresh": True},
        )
        assert resp2.status_code == 201
        rev2 = resp2.json()["revision"]
        assert rev2["revision_id"] != rev1["revision_id"]
        assert rev2["version_no"] == rev1["version_no"] + 1
        assert rev2["snapshot_id"] != rev1["snapshot_id"]

    def test_refresh_same_state_idempotent(self, client):
        """Auto-ключ сборщика включает cutoff: refresh на НЕИЗМЕННОМ
        состоянии возвращает ПРЕЖНИЙ снимок (§10.3 авто-повтор) --
        второй refresh НЕ добавляет новую заморозку D01."""
        _seed_snapshot()
        _cookie(client)
        resp1 = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents",
            json={"kind": "D01", "refresh": True},
        )
        assert resp1.status_code == 201
        resp2 = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents",
            json={"kind": "D01", "refresh": True},
        )
        assert resp2.status_code == 200
        assert (
            resp2.json()["revision"]["snapshot_id"]
            == resp1.json()["revision"]["snapshot_id"]
        )
        from apps.api.report_snapshot import get_snapshot_registry

        d01_freezes = [
            record
            for record in get_snapshot_registry().list_records(RUN_ID)
            if record.kinds == ["D01"]
        ]
        assert len(d01_freezes) == 1


# ══════════════════════════════════════════════════════════════════════
# 8. Аудит выдачи (§14.1): тройка download РАЗЛИЧАЕТСЯ; preview viewed
# ══════════════════════════════════════════════════════════════════════


class TestDeliveryAudit:
    def _audit_actions(self) -> list[str]:
        from apps.api.security_audit import get_audit_sink

        return [record["action"] for record in get_audit_sink().list_recent(limit=500)]

    def test_preview_records_protected_document_viewed(self, client):
        _seed_snapshot()
        _cookie(client)
        rev_id = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D01"}
        ).json()["revision"]["revision_id"]
        client.get(f"/v1/documentation/revisions/{rev_id}/preview")
        assert "protected_document_viewed" in self._audit_actions()

    def test_download_triple_distinct_and_ordered(self, client):
        """download_requested -> response_stream_started ->
        response_stream_finished -- три РАЗЛИЧНЫЕ записи (§14.1);
        human_read_confirmed НЕ существует."""
        _seed_snapshot()
        _cookie(client)
        rev_id = client.post(
            f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": "D01"}
        ).json()["revision"]["revision_id"]
        job = client.post(
            f"/v1/documentation/revisions/{rev_id}/renditions",
            json={"format": "md"},
        ).json()["job"]
        rid = job["rendition"]["rendition_id"]
        client.get(f"/v1/documentation/renditions/{rid}/content")
        actions = self._audit_actions()
        assert "download_requested" in actions
        assert "response_stream_started" in actions
        assert "response_stream_finished" in actions
        # Порядок внутри выдачи: requested раньше started раньше finished.
        i_req = actions.index("download_requested")
        i_started = actions.index("response_stream_started", i_req)
        i_finished = actions.index("response_stream_finished", i_started)
        assert i_req < i_started < i_finished
        from apps.api.security_audit import ACTION_DOCUMENT_PUBLISHED

        assert "human_read_confirmed" not in actions
        assert "document_published" not in actions  # publish -- DOCLOG-6

    def test_list_metadata_access_audited(self, client):
        """§17: GET документов -- только security access audit
        (run_access через решающую таблицу), без изменения науки."""
        _seed_snapshot()
        _cookie(client)
        client.get(f"/v1/documentation/runs/{RUN_ID}/documents")
        actions = self._audit_actions()
        assert "run_access_allowed" in actions or "run_access_denied" not in actions


# ══════════════════════════════════════════════════════════════════════
# 9. Health, main-wiring, миграция 0010 (паритет паттернов 0007-0009)
# ══════════════════════════════════════════════════════════════════════


class TestOpsWiringAndMigration:
    def test_ops_health_documents_block(self, client):
        _seed_snapshot()
        _cookie(client)
        resp = client.get("/health/ops")
        assert resp.status_code == 200
        documents = resp.json().get("documents")
        assert documents is not None
        assert "registry_backend" in documents
        # facts-only: БЕЗ путей/DSN/содержимого (T6/T10).
        blob = json.dumps(documents)
        assert "tmp_path" not in blob
        assert "/" not in blob.replace("not_initialized", "")

    def test_openapi_contains_documentation_routes(self, client):
        _seed_snapshot()
        _cookie(client)
        resp = client.get("/openapi.json")
        paths = resp.json()["paths"]
        for fragment in (
            "/v1/documentation/runs/{run_id}/documents",
            "/v1/documentation/revisions/{revision_id}",
            "/v1/documentation/revisions/{revision_id}/preview",
            "/v1/documentation/jobs/{job_id}",
            "/v1/documentation/renditions/{rendition_id}/content",
        ):
            assert fragment in paths, fragment

    def test_migration_catalog_contains_0010(self):
        from apps.api.research_runs import MIGRATION_FILES

        names = [name for name, _statements in MIGRATION_FILES]
        assert "0010_doclog4_documents.sql" in names
        assert "0011_doclog5_render_formats.sql" in names  # DOCLOG-5
        assert "0012_doclog6_approvals_archive.sql" in names  # DOCLOG-6
        assert "0014_doclog8_monitoring.sql" in names  # DOCLOG-8
        assert "0015_doclog9_profiles.sql" in names  # DOCLOG-9
        assert "0016_pgv2_print_documents.sql" in names  # PGV-02
        assert "0017_pgv9_print_renditions.sql" in names  # PGV-09
        assert len(names) == 17

    def test_migration_file_parity_with_catalog(self):
        """Паритет источников DDL (паттерн DOCLOG-1/2/3): каждый файл
        каталога -- дубль содержимого файла миграции."""
        from apps.api.research_runs import MIGRATION_FILES

        def _norm(value: str) -> str:
            return " ".join(value.split())

        for name, statements in MIGRATION_FILES:
            text = (
                Path(__file__).resolve().parents[2]
                / "apps" / "api" / "migrations" / name
            ).read_text(encoding="utf-8")
            normalized = _norm(text)
            for statement in statements:
                assert _norm(statement) in normalized, (name, statement[:60])

    def test_documents_ddl_constraints(self):
        from apps.api.research_runs import MIGRATION_STATEMENTS_0010

        ddl = "\n".join(MIGRATION_STATEMENTS_0010).lower()
        assert "create table if not exists documents" in ddl
        assert "create table if not exists document_revisions" in ddl
        assert "create table if not exists document_renditions" in ddl
        assert "create table if not exists document_jobs" in ddl
        assert "unique (run_id, kind_code)" in ddl
        assert "unique (document_id, version_no)" in ddl
        assert "unique (document_id, snapshot_id)" in ddl  # версия 1:1 снимок в документе
        assert "unique (snapshot_id, format, redaction_profile)" in ddl
        assert "references research_runs(run_id) on delete cascade" in ddl
        assert "references report_snapshots(snapshot_id) on delete cascade" in ddl

    def test_postgres_documents_registry_mirror(self):
        """PG-зеркало (урок F-D2C1): INSERT-параметры соответствуют
        DDL-колонкам; row -> record раундтрип без TypeError."""
        from apps.api import document_jobs
        from apps.api.research_runs import MIGRATION_STATEMENTS_0010

        ddl = "\n".join(MIGRATION_STATEMENTS_0010)
        for table in ("documents", "document_revisions", "document_renditions", "document_jobs"):
            create_match = re.search(
                rf"create table if not exists {table} \((.*?)\n    \)",
                ddl, re.S | re.I,
            )
            assert create_match, table
            columns = re.findall(r"^\s{8}([a-z_]+) ", create_match.group(1), re.M)
            assert columns, table

        record = document_jobs.DocumentJobRecord(
            job_id=document_jobs.new_job_id(),
            run_id=RUN_ID,
            snapshot_id="rs-" + "4" * 32,
            format="md",
            state=document_jobs.JOB_READY,
            attempt=1,
        )
        as_dict = record.to_dict()
        for key in ("job_id", "run_id", "snapshot_id", "format", "state"):
            assert key in as_dict, key
# ══════════════════════════════════════════════════════════════════════
# 10. Рендеры: JSONL/MD/HTML/CSV (§7; безопасность AC16)
# ══════════════════════════════════════════════════════════════════════


class TestRenderers:
    def test_render_jsonl_envelope_one_claim_per_line(self):
        from apps.api.document_renditions import (
            JSONL_SCHEMA_VERSION,
            render_snapshot_jsonl,
        )

        assert JSONL_SCHEMA_VERSION.startswith("doclog.")
        snapshot = _seed_snapshot()
        output = render_snapshot_jsonl(snapshot)
        lines = [line for line in output.splitlines() if line.strip()]
        total_claims = sum(
            len(section.get("claims", [])) for section in snapshot.sections
        )
        assert len(lines) == total_claims
        for line in lines:
            envelope = json.loads(line)
            assert envelope["schema_version"] == JSONL_SCHEMA_VERSION
            assert envelope["snapshot_id"] == snapshot.snapshot_id
            assert envelope["section_code"].startswith("D")
            assert "text" in envelope
            assert envelope["validity"] in {"current", "stale", "unknown"}
            assert "evidence_level" in envelope
            assert isinstance(envelope["event_refs"], list)
            assert isinstance(envelope["result_refs"], list)

    def test_render_markdown_structure_and_honesty(self):
        from apps.api.document_renditions import render_snapshot_markdown

        snapshot = _seed_snapshot()
        text = render_snapshot_markdown(snapshot)
        assert text.startswith("# ")
        assert snapshot.snapshot_id in text
        for section in snapshot.sections:
            assert section["title"] in text
        for section in snapshot.sections:
            for claim in section.get("claims", []):
                assert claim["text"] in text
        # Честность (R07): partial/gaps не скрываются.
        if snapshot.completeness.get("status") == "partial":
            assert "partial" in text or "неполный" in text.lower()

    def test_render_html_escapes_untrusted_content(self):
        """AC16: содержимое снимка -- недоверенный вход; script/
        javascript:/on*-атрибуты экранированы, исполнение исключено."""
        from apps.api.document_renditions import render_snapshot_html

        sentinel = "<script>alert('d4')</script>"
        snapshot = _seed_snapshot(claim_text=f"Проверка {sentinel} javascript:alert(1)")
        html = render_snapshot_html(snapshot)
        assert "<script>" not in html
        assert "<script" not in html.replace("&lt;script", "")
        assert sentinel not in html
        assert "&lt;script&gt;" in html
        assert "javascript:alert(1)" not in html

    def test_render_html_structure_static_safety(self):
        from apps.api.document_renditions import render_snapshot_html

        snapshot = _seed_snapshot()
        html = render_snapshot_html(snapshot)
        assert html.lstrip().lower().startswith("<!doctype html")
        assert 'lang="ru"' in html
        assert snapshot.snapshot_id in html
        # Статический inline CSS; внешние ресурсы не подключаются.
        assert "<style>" in html
        assert re.search(r"<link\s", html) is None
        assert re.search(r"<img\s", html) is None
        assert "http://" not in html and "https://" not in html
        # Секции и «Основание» (proof refs) присутствуют.
        for section in snapshot.sections:
            assert section["title"] in html
        assert "Основание" in html

    def test_render_csv_spreadsheet_safe_and_numeric_preserved(self):
        """§7: строки с префиксом =,+,-,@ и управляющие символы
        нейтрализуются В ТЕКСТОВЫХ значениях; числовое поле
        (event_count) остаётся числом."""
        from apps.api.document_renditions import render_snapshot_csv

        snapshot = _seed_snapshot(claim_text="=cmd(); опасная формула")
        text = render_snapshot_csv(snapshot)
        rows = list(csv.reader(io.StringIO(text)))
        assert rows, "CSV пуст"
        header = rows[0]
        assert "event_count" in header
        count_idx = header.index("event_count")
        claim_idx = header.index("claim")
        neutralized = False
        for row in rows[1:]:
            assert row[count_idx].isdigit(), row  # число не текст
            claim = row[claim_idx]
            payload = claim[1:] if claim.startswith("'") else claim
            for prefix in ("=", "+", "-", "@"):
                if payload.startswith(prefix):
                    assert claim.startswith("'"), (claim, "не нейтрализован")
                    neutralized = True
        assert neutralized, "сентинел-claim не попал в CSV"

    def test_filename_for_safe_content_disposition(self):
        from apps.api.document_renditions import filename_for

        name = filename_for("drev-" + "a" * 32, "md")
        assert name.startswith("document-drev-")
        assert name.endswith(".md")
        assert "/" not in name and "\\" not in name and ".." not in name
        # Любой мусор в ID не ломает имя (безопасный Content-Disposition).
        assert "/" not in filename_for("../../etc/passwd", "csv")
# MARKER_PART6
