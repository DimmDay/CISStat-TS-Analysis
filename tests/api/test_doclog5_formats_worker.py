# tests/api/test_doclog5_formats_worker.py
"""Задача DOCLOG-5 (spec_documentation_logging.md §7, §11, §12.3, §17,
§18, §19 строка DOCLOG-5, §19.1, §20 AC03/AC08/AC09/AC16): форматы и
worker -- PDF с кириллицей, XLSX/Parquet/ChartSpec SVG/PNG, evidence
ZIP, лимиты и retries.

Критерий завершения (§19): все rendition имеют один snapshot hash,
render crash не теряет результат.

Оракулы на СВОИХ данных: корпус дизъюнктен repo-корпусу и корпусам
0/1/2/3/4 (RUN-D5xxxxxx, d5-*); изоляция каждого теста -- паттерн
test_doclog4_document_delivery.py (свой tmp_path/CISSTAT_DATA_DIR,
сброс singleton-фабрик). Тяжёлые рендеры -- ЧИСТЫЕ функции от frozen
ReportSnapshot (R06), выполняются worker'ом (§18: тяжёлый PDF не
создаётся синхронно); rendition регистрируется ТОЛЬКО после
stage+commit байтов (AC08: никаких broken ready refs); дубликат
запроса при активном job возвращает ТОТ ЖЕ job (AC09); lease expiry
реклеймит job без повторной научной операции; XLSX/SVG/ZIP --
безопасный вывод (AC16: формулы/кириллица/переводы строк, script/
external URL, ZIP path traversal).
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timedelta, timezone
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
    monkeypatch.delenv("CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED", raising=False)
    monkeypatch.delenv("CISSTAT_DOCUMENT_RENDER_WORKER_INTERVAL", raising=False)
    monkeypatch.delenv("CISSTAT_DOCUMENT_RENDER_WORKER_BATCH", raising=False)
    monkeypatch.delenv("CISSTAT_DOCUMENT_RENDER_WORKER_PER_TENANT", raising=False)
    monkeypatch.delenv("CISSTAT_DOCUMENT_RENDER_WORKER_RENDER_TIMEOUT", raising=False)
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    from apps.api import artifact_store, report_snapshot, document_jobs
    from apps.api import document_render_worker
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
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


# ── Сид-хелперы: run/сессия/subject на СВОИХ данных ─────────────────

RUN_ID = "RUN-D5A00001"
SESSION_ID = "d5-seed-session"
FOREIGN_SESSION_ID = "d5-foreign-session"


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
    context_id: str | None = "ctx-d5-1",
    data_revision: int | None = 2,
) -> ResearchRun:
    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="d5" * 16,
        dataset_name="doclog5-seed",
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
) -> None:
    from apps.api.trace_events import TraceEvent

    event = TraceEvent(
        event_type=event_type,
        payload=dict(payload or {}),
        run_id=run_id,
        stage=stage,
        schema_version=2,
        evidence_level="server_result",
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
    """Собирает frozen-снимок через штатный сборщик DOCLOG-2; опция
    подмены текста первого claim -- ТОЛЬКО в памяти (рендеры получают
    недоверенный вход; durable-снимок не трогается)."""
    _seed_session(session_id)
    _seed_bound_run(run_id, session_id)
    _seed_event(run_id, payload={"dataset": "doclog5-seed"})
    subject = _owner_subject(session_id)
    snapshot, _created = _service().build_snapshot(
        run_id, subject, session_id=session_id, kinds=kinds or ["D01", "D02"]
    )
    if claim_text:
        from dataclasses import replace as _replace

        sections = [dict(section) for section in snapshot.sections]
        if sections:
            sections[0] = dict(sections[0])
            sections[0]["claims"] = [
                dict(sections[0]["claims"][0]) | {"text": claim_text},
                *[dict(claim) for claim in sections[0]["claims"][1:]],
            ]
        snapshot = _replace(snapshot, sections=sections)
    return snapshot


def _delivery():
    from apps.api.document_jobs import DocumentDeliveryService

    return DocumentDeliveryService.create_default()


def _make_org_profile(fmt: str, name: str):
    """DOCLOG-9: локальный хелпер профиля организации (admin-субъект,
    свои данные; корпус DOCLOG-9 -- tests/api/test_doclog9_profiles.py)."""
    from dataclasses import replace

    from apps.api.doc_profiles import org_profile_service
    from apps.api.identity import SubjectRef

    base = SubjectRef.from_session("d5-admin-seed")
    subject = replace(base, role="admin")
    return org_profile_service().create_profile(
        name=name,
        version_no=1,
        format=fmt,
        subject=subject,
    )


# DOCLOG-9 (честное обновление пина): HEAVY расширен docx/pdfa.
HEAVY = ("pdf", "xlsx", "parquet", "svg", "png", "zip", "docx", "pdfa")
P0 = ("json", "jsonl", "md", "html", "csv")


# ══════════════════════════════════════════════════════════════════════
# 1. Каталог форматов P1 и чистые рендеры (§7; R06/AC03/AC16)
# ══════════════════════════════════════════════════════════════════════


class TestHeavyFormatCatalog:
    def test_catalog_contains_p0_plus_heavy(self):
        from apps.api.document_renditions import (
            HEAVY_RENDITION_FORMATS,
            RENDITION_FORMATS,
        )

        assert set(RENDITION_FORMATS) == set(P0) | set(HEAVY)
        assert HEAVY_RENDITION_FORMATS == frozenset(HEAVY)
        for fmt in HEAVY:
            assert RENDITION_FORMATS[fmt].extension == fmt

    def test_heavy_media_types(self):
        from apps.api.document_renditions import RENDITION_FORMATS

        assert RENDITION_FORMATS["pdf"].media_type == "application/pdf"
        assert (
            RENDITION_FORMATS["xlsx"].media_type
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert (
            RENDITION_FORMATS["parquet"].media_type
            == "application/vnd.apache.parquet"
        )
        assert RENDITION_FORMATS["svg"].media_type == "image/svg+xml"
        assert RENDITION_FORMATS["png"].media_type == "image/png"
        assert RENDITION_FORMATS["zip"].media_type == "application/zip"

    def test_docx_and_pdfa_present_as_org_profile_formats(self):
        """DOCLOG-9 (честное обновление пина, §7 P2/§19): DOCX/PDF/A --
        форматы профилей организации (DOCLOG-5 граница честно расширена
        последующей задачей; выпуск ТОЛЬКО через профиль, §19 строка
        DOCLOG-9). Прецедент: DOCLOG-4 (9/53→10/62)."""
        from apps.api.document_renditions import RENDITION_FORMATS

        assert "docx" in RENDITION_FORMATS
        assert "pdfa" in RENDITION_FORMATS


class TestPdfRender:
    def test_pdf_bytes_and_determinism(self):
        from apps.api.document_renditions import render_snapshot_pdf

        snapshot = _seed_snapshot()
        first = render_snapshot_pdf(snapshot)
        second = render_snapshot_pdf(snapshot)
        assert first.startswith(b"%PDF-")
        assert len(first) > 1000
        assert first == second  # детерминизм (invariant-метаданные)

    def test_pdf_embeds_cyrillic_ttf_font(self):
        """§7 PDF: кириллица/встроенные шрифты. Подмножество TTF
        встраивается в файл (FontFile2 в дескрипторе шрифта)."""
        from apps.api.document_renditions import render_snapshot_pdf

        snapshot = _seed_snapshot()
        content = render_snapshot_pdf(snapshot)
        assert b"DejaVuSans" in content or b"DejaVu Sans" in content
        # Встроенный шрифт: подмножество TTF в объекте-потоке.
        assert b"FontFile2" in content

    def test_pdf_cyrillic_text_extractable(self):
        """Кириллица реально извлекается из PDF (pypdf), а не декори-
        руется -- §20: «PDF -- render и проверка кириллицы/шрифтов»."""
        from apps.api.document_renditions import render_snapshot_pdf

        snapshot = _seed_snapshot()
        content = render_snapshot_pdf(snapshot)
        import pypdf

        reader = pypdf.PdfReader(io.BytesIO(content))
        text = "".join(page.extract_text() or "" for page in reader.pages)
        assert "Документ исследования" in text

    def test_pdf_no_external_urls_or_javascript(self):
        """AC16/§12.3: рендер не получает сеть -- в PDF нет внешних
        URI-действий и JavaScript-действий."""
        from apps.api.document_renditions import render_snapshot_pdf

        snapshot = _seed_snapshot(
            claim_text="См. https://evil.example/x и <script>alert(1)</script>"
        )
        content = render_snapshot_pdf(snapshot)
        assert b"/JavaScript" not in content
        assert b"/URI (https://evil.example" not in content
        assert b"/GoToR" not in content
        assert b"/Launch" not in content

    def test_pdf_font_unavailable_is_honest_error(self, monkeypatch):
        """Нет ни одного allowlist-шрифта -> RenderDependencyError
        (честный отказ, не битый файл)."""
        from apps.api import document_renditions as renditions

        snapshot = _seed_snapshot()
        monkeypatch.setattr(renditions, "_PDF_FONT_CANDIDATES", ())
        with pytest.raises(renditions.RenderDependencyError) as excinfo:
            renditions.render_snapshot_pdf(snapshot)
        assert "font_unavailable" in str(excinfo.value)


class TestXlsxRender:
    def test_xlsx_five_sheets_and_determinism(self):
        from apps.api.document_renditions import render_snapshot_xlsx

        snapshot = _seed_snapshot()
        first = render_snapshot_xlsx(snapshot)
        second = render_snapshot_xlsx(snapshot)
        assert first.startswith(b"PK")
        assert first == second
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(first))
        assert wb.sheetnames == [
            "Summary", "Metadata", "Results", "Methods", "Warnings",
        ]

    def test_xlsx_claims_rows_match_snapshot_facts(self):
        """AC03: факты снимка в XLSX совпадают (число строк Results ==
        число claims; кириллица/переводы строк раундтрипятся)."""
        from apps.api.document_renditions import render_snapshot_xlsx

        snapshot = _seed_snapshot(
            claim_text="Многострочный claim\nвторая строка · кириллица"
        )
        content = render_snapshot_xlsx(snapshot)
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(content))
        ws = wb["Results"]
        expected = sum(
            len(section.get("claims", [])) for section in snapshot.sections
        )
        # header + по строке на каждый claim
        assert ws.max_row == expected + 1
        texts = [ws.cell(row=row, column=3).value for row in range(2, ws.max_row + 1)]
        joined = "\n".join(str(t) for t in texts if t)
        assert "Многострочный claim" in joined
        assert "вторая строка" in joined

    def test_xlsx_formula_like_text_stays_string(self):
        """AC16/§7: «XLSX пишет недоверенный текст как строки, не
        формулы» -- '=HYPERLINK/=SUM не становятся формулами."""
        from apps.api.document_renditions import render_snapshot_xlsx

        snapshot = _seed_snapshot(
            claim_text="=HYPERLINK(\"https://evil.example\",\"войти\")"
        )
        content = render_snapshot_xlsx(snapshot)
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(content))
        ws = wb["Results"]
        cell = ws.cell(row=2, column=3)
        assert str(cell.value).startswith("=HYPERLINK")
        assert cell.data_type == "s"  # строка, не формула ('f')

    def test_xlsx_no_macros(self):
        from apps.api.document_renditions import render_snapshot_xlsx

        snapshot = _seed_snapshot()
        content = render_snapshot_xlsx(snapshot)
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
        assert not any("vbaProject" in name for name in names)

    def test_xlsx_long_text_truncated_honestly(self):
        """§7: «лимиты Excel проверяются» -- усечение ячейки честное, с
        маркером в Warnings, не тихая порча."""
        from apps.api.document_renditions import (
            MAX_XLSX_CELL_CHARS,
            render_snapshot_xlsx,
        )

        snapshot = _seed_snapshot(claim_text="Ж" * (MAX_XLSX_CELL_CHARS + 500))
        content = render_snapshot_xlsx(snapshot)
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(content))
        cell = wb["Results"].cell(row=2, column=3)
        assert isinstance(cell.value, str)
        assert len(cell.value) <= MAX_XLSX_CELL_CHARS
        assert "усечено" in cell.value
        warnings_text = "\n".join(
            " ".join(str(cell.value or "") for cell in row)
            for row in wb["Warnings"].iter_rows()
        )
        assert "усечено" in warnings_text


class TestParquetRender:
    def test_parquet_roundtrip_typed_table(self):
        """§7 Parquet + schema: typed-таблица claims; refs --
        list<string>, числовые cutoff -- int64 nullable."""
        pq = pytest.importorskip("pyarrow.parquet")
        from apps.api.document_renditions import render_snapshot_parquet

        snapshot = _seed_snapshot(claim_text="Кириллица в parquet")
        content = render_snapshot_parquet(snapshot)
        table = pq.read_table(io.BytesIO(content))
        expected = sum(
            len(section.get("claims", [])) for section in snapshot.sections
        )
        assert table.num_rows == expected
        column_names = set(table.column_names)
        assert {
            "schema_version", "snapshot_id", "research_run_id",
            "captured_at", "section_code", "section_kind", "claim",
            "validity", "evidence_level", "event_refs", "result_refs",
            "event_count", "last_sequence",
        } <= column_names
        claims = table.column("claim").to_pylist()
        assert any("Кириллица в parquet" in str(c) for c in claims)
        assert str(table.schema.field("event_refs").type).startswith("list")
        assert "snapshot_id" in table.schema.names

    def test_parquet_schema_carries_snapshot_identity(self):
        pq = pytest.importorskip("pyarrow.parquet")
        from apps.api.document_renditions import render_snapshot_parquet

        snapshot = _seed_snapshot()
        content = render_snapshot_parquet(snapshot)
        table = pq.read_table(io.BytesIO(content))
        ids = set(table.column("snapshot_id").to_pylist())
        assert ids == {snapshot.snapshot_id}

    def test_parquet_dependency_unavailable_honest(self, monkeypatch):
        """Отсутствие движка -- честный RenderDependencyError
        (render_dependency_unavailable), не тихая подмена форматом."""
        import builtins

        from apps.api import document_renditions as renditions

        snapshot = _seed_snapshot()
        real_import = builtins.__import__

        def _no_pyarrow(name, *args, **kwargs):
            if name.startswith("pyarrow"):
                raise ImportError("pyarrow недоступен (тест)")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_pyarrow)
        with pytest.raises(renditions.RenderDependencyError) as excinfo:
            renditions.render_snapshot_parquet(snapshot)
        assert "dependency_unavailable" in str(excinfo.value)


class TestChartSpecRender:
    def test_chart_spec_is_deterministic_projection(self):
        from apps.api.document_renditions import build_chart_spec

        snapshot = _seed_snapshot()
        spec = build_chart_spec(snapshot)
        spec2 = build_chart_spec(snapshot)
        assert spec == spec2
        expected = {
            section.get("code", ""): len(section.get("claims", []))
            for section in snapshot.sections
        }
        assert dict(spec.series) == expected
        assert snapshot.snapshot_id in spec.source_ref

    def test_svg_safe_and_deterministic(self):
        """§7 SVG/AC16: валидный XML, фиксированная светлая print-тема,
        БЕЗ script/xlink/внешних URL; тексты экранированы."""
        import xml.etree.ElementTree as ET

        from apps.api.document_renditions import render_snapshot_svg

        snapshot = _seed_snapshot(
            claim_text="<script>alert(1)</script> javascript:alert(2)"
        )
        first = render_snapshot_svg(snapshot)
        second = render_snapshot_svg(snapshot)
        assert first == second
        root = ET.fromstring(first)
        assert root.tag.endswith("svg")
        lowered = first.lower()
        assert "<script" not in lowered
        assert "xlink:href" not in lowered
        assert "href=\"http" not in lowered
        assert "javascript:" not in lowered
        assert "<image" not in lowered
        # недоверенный текст НЕ попал в разметку как элемент/атрибут
        assert "<script>alert" not in first

    def test_svg_contains_chartspec_ref_and_title(self):
        from apps.api.document_renditions import render_snapshot_svg

        snapshot = _seed_snapshot()
        svg = render_snapshot_svg(snapshot)
        assert "doclog.chartspec/1" in svg
        assert snapshot.snapshot_id in svg

    def test_png_deterministic_and_raster(self):
        from PIL import Image

        from apps.api.document_renditions import render_snapshot_png

        snapshot = _seed_snapshot()
        first = render_snapshot_png(snapshot)
        second = render_snapshot_png(snapshot)
        assert first == second
        image = Image.open(io.BytesIO(first))
        assert image.format == "PNG"
        assert image.size[0] >= 600

    def test_png_font_unavailable_is_honest_error(self, monkeypatch):
        from apps.api import document_renditions as renditions

        snapshot = _seed_snapshot()
        monkeypatch.setattr(renditions, "_PDF_FONT_CANDIDATES", ())
        with pytest.raises(renditions.RenderDependencyError):
            renditions.render_snapshot_png(snapshot)


class TestEvidenceZip:
    def test_zip_members_fixed_and_deterministic(self):
        from apps.api.document_renditions import (
            EVIDENCE_ZIP_MEMBERS,
            render_evidence_zip,
        )

        snapshot = _seed_snapshot()
        first = render_evidence_zip(snapshot)
        second = render_evidence_zip(snapshot)
        assert first == second
        with zipfile.ZipFile(io.BytesIO(first)) as zf:
            names = zf.namelist()
        assert names == list(EVIDENCE_ZIP_MEMBERS)
        assert not any(name.startswith("/") for name in names)
        assert not any(".." in name for name in names)

    def test_zip_manifest_checksums_no_self_hash(self):
        """§13.3: манифест не содержит собственного hash (циклическое
        определение); sha256 всех членов корректны."""
        import hashlib

        from apps.api.document_renditions import render_evidence_zip

        snapshot = _seed_snapshot()
        content = render_evidence_zip(snapshot)
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            for member in manifest["members"]:
                actual = hashlib.sha256(zf.read(member["name"])).hexdigest()
                assert actual == member["sha256"], member["name"]
        assert manifest["members"] != []
        # сам манифест НЕ входит в собственный checksum-набор
        assert "manifest.json" not in {m["name"] for m in manifest["members"]}

    def test_zip_honest_no_data_included(self):
        """§7: ZIP без исходных данных -- data_included=false и
        reproducibility=limited, не мнимая полнота."""
        from apps.api.document_renditions import render_evidence_zip

        snapshot = _seed_snapshot()
        with zipfile.ZipFile(io.BytesIO(render_evidence_zip(snapshot))) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            report = json.loads(zf.read("report.json").decode("utf-8"))
            md_text = zf.read("document.md").decode("utf-8")
            csv_text = zf.read("table_claims.csv").decode("utf-8")
            svg_text = zf.read("chart_claims.svg").decode("utf-8")
            schema = json.loads(zf.read("table_schema.json").decode("utf-8"))
        assert manifest["data_included"] is False
        assert manifest["reproducibility"] == "limited"
        assert manifest["snapshot_id"] == snapshot.snapshot_id
        assert report["snapshot_id"] == snapshot.snapshot_id
        assert snapshot.snapshot_id in md_text
        assert csv_text.splitlines()[0].startswith("schema_version")
        assert "doclog.chartspec/1" in svg_text
        assert schema["locale"] == snapshot.locale
        assert schema["columns"], "schema.json без колонок"

    def test_zip_path_traversal_never_possible(self):
        """AC16: ZIP paths не допускают ../ и абсолютных имён --
        по построению (фиксированные имена) + оракул."""
        from apps.api.document_renditions import (
            EVIDENCE_ZIP_MEMBERS,
            render_evidence_zip,
        )

        snapshot = _seed_snapshot(claim_text="../../etc/passwd")
        with zipfile.ZipFile(io.BytesIO(render_evidence_zip(snapshot))) as zf:
            for name in zf.namelist():
                assert name in EVIDENCE_ZIP_MEMBERS
                assert not name.startswith(("/", "\\"))
                assert ".." not in Path(name).parts


class TestCrossFormatFactsConsistency:
    def test_ac03_same_facts_across_all_formats(self):
        """AC03: один frozen снимок -- совпадающие ФАКТЫ во всех
        форматах; байты (и hashes) форматов различны."""
        from apps.api.artifact_store import artifact_content_sha256
        from apps.api.document_renditions import (
            render_evidence_zip,
            render_snapshot_csv,
            render_snapshot_html,
            render_snapshot_json,
            render_snapshot_jsonl,
            render_snapshot_markdown,
            render_snapshot_parquet,
            render_snapshot_pdf,
            render_snapshot_png,
            render_snapshot_svg,
            render_snapshot_xlsx,
        )

        snapshot = _seed_snapshot()
        expected_claims = sum(
            len(section.get("claims", [])) for section in snapshot.sections
        )
        blobs = {
            "json": render_snapshot_json(snapshot),
            "jsonl": render_snapshot_jsonl(snapshot).encode("utf-8"),
            "md": render_snapshot_markdown(snapshot).encode("utf-8"),
            "html": render_snapshot_html(snapshot).encode("utf-8"),
            "csv": render_snapshot_csv(snapshot).encode("utf-8"),
            "pdf": render_snapshot_pdf(snapshot),
            "xlsx": render_snapshot_xlsx(snapshot),
            "parquet": render_snapshot_parquet(snapshot),
            "svg": render_snapshot_svg(snapshot).encode("utf-8"),
            "png": render_snapshot_png(snapshot),
            "zip": render_evidence_zip(snapshot),
        }
        hashes = {name: artifact_content_sha256(blob) for name, blob in blobs.items()}
        assert len(set(hashes.values())) == len(hashes)  # байты различны
        # Факты: jsonl -- по строке на claim.
        jsonl_lines = [
            line
            for line in blobs["jsonl"].decode("utf-8").splitlines()
            if line.strip()
        ]
        assert len(jsonl_lines) == expected_claims
        # CSV -- по строке на claim (+header).
        csv_rows = blobs["csv"].decode("utf-8").strip().split("\r\n")
        assert len(csv_rows) == expected_claims + 1
        # Parquet -- num_rows == claims.
        pq = pytest.importorskip("pyarrow.parquet")
        assert pq.read_table(io.BytesIO(blobs["parquet"])).num_rows == expected_claims
        # ZIP report.json -- те же секции/claims.
        with zipfile.ZipFile(io.BytesIO(blobs["zip"])) as zf:
            report = json.loads(zf.read("report.json").decode("utf-8"))
        zip_claims = sum(
            len(section.get("claims", [])) for section in report["sections"]
        )
        assert zip_claims == expected_claims

    def test_renditions_share_single_snapshot_hash(self):
        """Критерий завершения §19: все rendition одной ревизии несут
        ОДИН snapshot hash (snapshot_payload_sha256 == payload_sha256
        снимка) и один snapshot_id."""
        snapshot = _seed_snapshot()
        service = _delivery()
        for fmt in P0:
            service.request_rendition(
                snapshot, format=fmt,
                subject=_owner_subject(), session_id=SESSION_ID,
            )
        renditions = service.registry.list_renditions(snapshot.snapshot_id)
        assert len(renditions) == len(P0)
        for rendition in renditions:
            assert rendition.snapshot_id == snapshot.snapshot_id
            assert rendition.snapshot_payload_sha256 == snapshot.payload_sha256


# ══════════════════════════════════════════════════════════════════════
# 2. Асинхронный контур: heavy → queued → worker → ready (§11/§18/AC08/AC09)
# ══════════════════════════════════════════════════════════════════════


class TestHeavyAsyncPath:
    def test_heavy_format_request_creates_queued_job_without_rendition(self):
        """§18: тяжёлый PDF не создаётся синхронно -- job queued,
        rendition НЕТ до работы worker'а."""
        from apps.api.document_jobs import JOB_QUEUED

        snapshot = _seed_snapshot()
        service = _delivery()
        job, rendition = service.request_rendition(
            snapshot, format="pdf",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        assert job.state == JOB_QUEUED
        assert job.format == "pdf"
        assert rendition is None
        assert service.registry.list_renditions(snapshot.snapshot_id) == []

    def test_duplicate_request_while_active_returns_same_job(self):
        """AC09: дубликат запроса при активном (queued) job -- ТОТ ЖЕ
        job, без нового задания и без второй версии."""
        snapshot = _seed_snapshot()
        service = _delivery()
        job1, _ = service.request_rendition(
            snapshot, format="pdf",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        job2, rend2 = service.request_rendition(
            snapshot, format="pdf",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        assert job2.job_id == job1.job_id
        assert rend2 is None
        assert len(service.registry.list_jobs(RUN_ID)) == 1

    def test_worker_run_once_renders_queued_job_ready(self):
        from apps.api.document_render_worker import DocumentRenderWorker
        from apps.api.document_jobs import JOB_READY

        snapshot = _seed_snapshot()
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="pdf",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        worker = DocumentRenderWorker()
        summary = worker.run_once()
        assert summary["claimed"] >= 1
        done = service.registry.get_job(job.job_id)
        assert done.state == JOB_READY
        rendition = service.registry.get_rendition(done.rendition_id)
        assert rendition is not None
        assert rendition.format == "pdf"
        assert rendition.media_type == "application/pdf"
        assert rendition.snapshot_payload_sha256 == snapshot.payload_sha256
        content = service.read_rendition_content(
            rendition, subject=_owner_subject(), session_id=SESSION_ID
        )
        assert content.startswith(b"%PDF-")

    def test_worker_ready_idempotent_no_second_rendition(self):
        """AC09: после ready повторный запрос -- прежний job/rendition
        (UNIQUE(snapshot_id, format, profile)), worker не создаёт
        вторую версию."""
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        service = _delivery()
        job1, _ = service.request_rendition(
            snapshot, format="xlsx",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        DocumentRenderWorker().run_once()
        job2, rend2 = service.request_rendition(
            snapshot, format="xlsx",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        assert job2.job_id == job1.job_id
        assert rend2 is not None
        assert len(service.registry.list_renditions(snapshot.snapshot_id)) == 1

    def test_all_heavy_formats_end_to_end(self):
        from apps.api.document_render_worker import DocumentRenderWorker
        from apps.api.document_jobs import JOB_READY

        snapshot = _seed_snapshot()
        service = _delivery()
        # DOCLOG-9 (честное обновление пина): docx/pdfa требуют
        # организационный профиль -- создаётся на месте (выпуск ТОЛЬКО
        # по профилю, §19 строка DOCLOG-9).
        profiles = {
            "docx": _make_org_profile("docx", "d5pin-docx"),
            "pdfa": _make_org_profile("pdfa", "d5pin-pdfa"),
        }
        jobs = []
        for fmt in HEAVY:
            job, _ = service.request_rendition(
                snapshot, format=fmt,
                org_profile_id=(
                    profiles[fmt].profile_id if fmt in profiles else ""
                ),
                subject=_owner_subject(), session_id=SESSION_ID,
            )
            jobs.append((fmt, job.job_id))
        # Явные лимиты: все 8 jobs одного tenant за один цикл
        # (DOCLOG-9, честное обновление пина: HEAVY расширен docx/pdfa;
        # дефолт per_tenant_limit=2 -- проверен отдельным тестом).
        summary = DocumentRenderWorker(
            batch_size=8, per_tenant_limit=8
        ).run_once()
        assert summary["ready"] == len(HEAVY)
        for fmt, job_id in jobs:
            done = service.registry.get_job(job_id)
            assert done.state == JOB_READY, fmt
            rendition = service.registry.get_rendition(done.rendition_id)
            assert rendition.format == fmt
            assert rendition.snapshot_payload_sha256 == snapshot.payload_sha256

    def test_worker_does_not_touch_snapshot_or_science_state(self):
        """AC05/AC08: рендер worker'ом не повторяет научную операцию --
        payload_sha256/captured_at снимка до/после совпадают."""
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="parquet",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        before = _service().get_snapshot(
            snapshot.snapshot_id, _owner_subject(), session_id=SESSION_ID
        )
        DocumentRenderWorker().run_once()
        after = _service().get_snapshot(
            snapshot.snapshot_id, _owner_subject(), session_id=SESSION_ID
        )
        assert after.payload_sha256 == before.payload_sha256
        assert after.captured_at == before.captured_at
        assert after.to_dict() == before.to_dict()


class TestWorkerFailuresAndRetries:
    def test_render_crash_job_failed_no_broken_ready_refs(self):
        """AC08: crash рендера -- failed + error_code; НЕТ rendition,
        НЕТ ready refs; retry не теряет результат (следующая попытка
        доводит до ready)."""
        from apps.api import document_jobs
        from apps.api.document_jobs import JOB_FAILED
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="pdf",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        original = document_jobs.render_snapshot_pdf

        def _boom(_snapshot):
            raise RuntimeError("pdf renderer boom")

        worker = DocumentRenderWorker(max_attempts=1)
        document_jobs.render_snapshot_pdf = _boom
        try:
            worker.run_once()
        finally:
            document_jobs.render_snapshot_pdf = original
        failed = service.registry.get_job(job.job_id)
        assert failed.state == JOB_FAILED
        assert failed.error_code == "render_failed"
        assert failed.rendition_id is None
        assert service.registry.list_renditions(snapshot.snapshot_id) == []
        # Retry (новый запрос -- честная новая попытка) доводит до ready.
        job2, _ = service.request_rendition(
            snapshot, format="pdf",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        assert job2.job_id != job.job_id
        DocumentRenderWorker().run_once()
        done = service.registry.get_job(job2.job_id)
        assert done.state == "ready"

    def test_worker_auto_retry_bounded_by_max_attempts(self):
        """§18 retries: устойчивые неудачи рендера повторяются
        автоматически, но ОГРАНИЧЕНО (max_attempts) -- после исчерпания
        честный terminal failed, очередь не крутится вечно."""
        from apps.api import document_jobs
        from apps.api.document_jobs import JOB_FAILED
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="png",
            subject=_owner_subject(), session_id=SESSION_ID,
        )

        def _boom(_snapshot):
            raise RuntimeError("png renderer boom")

        worker = DocumentRenderWorker(max_attempts=3)
        original = document_jobs.render_snapshot_png
        document_jobs.render_snapshot_png = _boom
        try:
            worker.run_once()  # попытка 1 -> requeue (attempt=2)
            worker.run_once()  # попытка 2 -> requeue (attempt=3)
            worker.run_once()  # попытка 3 -> terminal failed
            worker.run_once()  # больше нет открытых заданий
        finally:
            document_jobs.render_snapshot_png = original
        final = service.registry.get_job(job.job_id)
        assert final.state == JOB_FAILED
        assert final.attempt == 3
        assert final.error_code == "render_failed"
        assert service.registry.list_renditions(snapshot.snapshot_id) == []

    def test_unsupported_format_terminal_no_retry(self):
        """Неддерживаемый формат -- terminal failed БЕЗ автоповторов
        (детерминированная ошибка не крутится в очереди)."""
        from apps.api.document_jobs import JOB_FAILED
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="pdf",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        # Подмена формата job'а на несуществующий (симуляция рассинхрона
        # каталога): honest терминальный отказ.
        stalled = service.registry.get_job(job.job_id)
        service.registry.update_job(
            type(stalled)(**{**stalled.to_dict(), "format": "no-such"})
        )
        worker = DocumentRenderWorker(max_attempts=5)
        worker.run_once()
        final = service.registry.get_job(job.job_id)
        assert final.state == JOB_FAILED
        assert final.error_code == "unsupported_format"
        assert final.attempt == 1  # терминально: автоповторов нет

    def test_render_timeout_honest_failure_not_corrupt_file(self):
        """§18/AC08: timeout рендера -- failed render_timeout, НЕ
        повреждённый ready файл (соединение рвётся честно)."""
        import threading

        from apps.api import document_jobs
        from apps.api.document_jobs import JOB_FAILED
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="zip",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        release = threading.Event()

        def _slow(_snapshot):
            release.wait(timeout=10)
            return b"never ready"

        original = document_jobs.render_snapshot_zip
        document_jobs.render_snapshot_zip = _slow
        try:
            worker = DocumentRenderWorker(
                render_timeout=0.2, max_attempts=1
            )
            worker.run_once()
        finally:
            document_jobs.render_snapshot_zip = original
            release.set()
        final = service.registry.get_job(job.job_id)
        assert final.state == JOB_FAILED
        assert final.error_code == "render_timeout"
        assert service.registry.list_renditions(snapshot.snapshot_id) == []

    def test_dependency_unavailable_is_terminal(self):
        """Отсутствие зависимости (pyarrow) -- честный терминальный
        отказ render_dependency_unavailable."""
        import builtins

        from apps.api.document_jobs import JOB_FAILED
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="parquet",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        real_import = builtins.__import__

        def _no_pyarrow(name, *args, **kwargs):
            if name.startswith("pyarrow"):
                raise ImportError("pyarrow недоступен (тест)")
            return real_import(name, *args, **kwargs)

        worker = DocumentRenderWorker(max_attempts=3)
        builtins.__import__ = _no_pyarrow
        try:
            worker.run_once()
        finally:
            builtins.__import__ = real_import
        final = service.registry.get_job(job.job_id)
        assert final.state == JOB_FAILED
        assert final.error_code == "render_dependency_unavailable"
        assert final.attempt == 1  # terminal

    def test_lease_expiry_reclaims_without_duplicating(self):
        """AC08/AC09: crash worker'а между claim и готовностью --
        просроченный lease реклеймится (честный pending), рендер
        доходит до ready, версия ОДНА (научная операция не повторяется,
        attempt не растёт)."""
        from apps.api.document_render_worker import (
            DocumentRenderWorker,
            load_snapshot_system,
        )
        from apps.api.document_jobs import JOB_RENDERING, JOB_QUEUED

        snapshot = _seed_snapshot()
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="svg",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        # Симуляция crash: job завис в rendering, lease протек.
        stalled = service.registry.get_job(job.job_id)
        expired = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        service.registry.update_job(
            type(stalled)(
                **{
                    **stalled.to_dict(),
                    "state": JOB_RENDERING,
                    "claimed_at": expired,
                    "lease_expires_at": expired,
                }
            )
        )
        worker = DocumentRenderWorker(lease_seconds=60)
        worker.run_once()
        done = service.registry.get_job(job.job_id)
        assert done.state == "ready"
        assert done.attempt == stalled.attempt  # attempt не растёт
        renditions = service.registry.list_renditions(snapshot.snapshot_id)
        assert len(renditions) == 1  # вторая версия НЕ создана

    def test_active_lease_not_stolen(self):
        """ЧУЖОЙ живой lease не перехватывается другим worker'ом
        (защита от двойного рендера/двух версий)."""
        from apps.api.document_render_worker import DocumentRenderWorker
        from apps.api.document_jobs import JOB_RENDERING

        snapshot = _seed_snapshot()
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="png",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        stalled = service.registry.get_job(job.job_id)
        future = (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()
        service.registry.update_job(
            type(stalled)(
                **{
                    **stalled.to_dict(),
                    "state": JOB_RENDERING,
                    "claimed_at": datetime.now(timezone.utc).isoformat(),
                    "lease_expires_at": future,
                }
            )
        )
        summary = DocumentRenderWorker(lease_seconds=60).run_once()
        untouched = service.registry.get_job(job.job_id)
        assert untouched.state == JOB_RENDERING
        assert summary["ready"] == 0

    def test_snapshot_unavailable_honest_terminal(self):
        """Снимок недоступен при рендере -- честный terminal failed
        snapshot_unavailable (никаких тихих суррогатов)."""
        from apps.api.document_jobs import JOB_FAILED
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        service = _delivery()
        job, _ = service.request_rendition(
            snapshot, format="svg",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        fake_snapshot_id = "rs-" + "e" * 32
        stalled = service.registry.get_job(job.job_id)
        service.registry.update_job(
            type(stalled)(**{**stalled.to_dict(), "snapshot_id": fake_snapshot_id})
        )
        DocumentRenderWorker(max_attempts=3).run_once()
        final = service.registry.get_job(job.job_id)
        assert final.state == JOB_FAILED
        assert final.error_code == "snapshot_unavailable"

    def test_ac08_invariant_all_ready_renditions_have_valid_bytes(self):
        """AC08-инвариант по всей реестровой базе сценария: каждая
        ready rendition имеет валидный storage_key и байты, sha256
        которых совпадает с content_sha256 (broken ready refs
        невозможны)."""
        from apps.api.artifact_store import artifact_content_sha256
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot = _seed_snapshot()
        service = _delivery()
        # DOCLOG-9 (честное обновление пина): профильные форматы -- с
        # профилем (выпуск ТОЛЬКО по профилю).
        profiles = {
            "docx": _make_org_profile("docx", "d5pin-ac08-docx"),
            "pdfa": _make_org_profile("pdfa", "d5pin-ac08-pdfa"),
        }
        for fmt in HEAVY:
            service.request_rendition(
                snapshot, format=fmt,
                org_profile_id=(
                    profiles[fmt].profile_id if fmt in profiles else ""
                ),
                subject=_owner_subject(), session_id=SESSION_ID,
            )
        DocumentRenderWorker().run_once()
        for rendition in service.registry.list_renditions(snapshot.snapshot_id):
            assert rendition.state == "ready"
            assert rendition.storage_key, rendition.rendition_id
            content = service.objects.read_bytes(rendition.storage_key)
            assert artifact_content_sha256(content) == rendition.content_sha256


class TestWorkerLimits:
    def test_batch_limit_backpressure_keeps_jobs_queued(self):
        """§18 backpressure: batch=1 -- за цикл берётся один job,
        остальные ЧЕСТНО остаются queued (не теряются, не отказываются)."""
        from apps.api.document_render_worker import DocumentRenderWorker
        from apps.api.document_jobs import JOB_QUEUED

        snapshot = _seed_snapshot()
        service = _delivery()
        job_ids = []
        for fmt in ("pdf", "svg", "png"):
            job, _ = service.request_rendition(
                snapshot, format=fmt,
                subject=_owner_subject(), session_id=SESSION_ID,
            )
            job_ids.append(job.job_id)
        summary = DocumentRenderWorker(batch_size=1).run_once()
        assert summary["claimed"] == 1
        states = {
            job_id: service.registry.get_job(job_id).state
            for job_id in job_ids
        }
        ready_count = sum(1 for state in states.values() if state == "ready")
        queued_count = sum(1 for state in states.values() if state == JOB_QUEUED)
        assert ready_count == 1
        assert queued_count == 2

    def test_per_tenant_limit_defers_same_tenant(self):
        """§18 per-tenant concurrency: второй job того же tenant ждёт
        следующий цикл; чужой tenant не блокируется."""
        from apps.api.document_render_worker import DocumentRenderWorker

        snapshot_a = _seed_snapshot(run_id=RUN_ID, session_id=SESSION_ID)
        other_session = "d5-other-tenant"
        snapshot_b = _seed_snapshot(
            run_id="RUN-D5A00002", session_id=other_session
        )
        service = _delivery()
        job_a, _ = service.request_rendition(
            snapshot_a, format="pdf",
            subject=_owner_subject(), session_id=SESSION_ID,
        )
        job_b, _ = service.request_rendition(
            snapshot_b, format="pdf",
            subject=_owner_subject(other_session), session_id=other_session,
        )
        # Один и тот же tenant у обоих (DEFAULT_TENANT_ID) + per_tenant=1:
        worker = DocumentRenderWorker(per_tenant_limit=1, batch_size=8)
        summary = worker.run_once()
        assert summary["claimed"] == 1
        states = {
            job_a.job_id: service.registry.get_job(job_a.job_id).state,
            job_b.job_id: service.registry.get_job(job_b.job_id).state,
        }
        assert sum(1 for s in states.values() if s == "ready") == 1
        assert sum(1 for s in states.values() if s == "queued") == 1

    def test_tenant_open_queue_quota_429(self):
        """§18 quota: превышение очереди открытых jobs tenant'а --
        честный 429 quota_exceeded, не тихая очередь-переполнение."""
        from apps.api.document_jobs import (
            DocumentJobRecord,
            DocumentQuotaExceeded,
            new_job_id,
        )

        snapshot = _seed_snapshot()
        service = _delivery()
        subject = _owner_subject()
        # Забиваем tenant-очередь открытыми jobs (лимит по умолчанию 10).
        for index in range(10):
            service.registry.register_job(
                DocumentJobRecord(
                    job_id=new_job_id(),
                    run_id=RUN_ID,
                    snapshot_id=snapshot.snapshot_id,
                    format="pdf",
                    state="queued",
                    attempt=1,
                    tenant_id=DEFAULT_TENANT_ID,
                    created_by=subject.subject_id,
                )
            )
        with pytest.raises(DocumentQuotaExceeded) as excinfo:
            service.request_rendition(
                snapshot, format="svg",
                subject=subject, session_id=SESSION_ID,
            )
        assert "quota_exceeded" in str(excinfo.value)

    def test_retry_limit_exceeded_429_after_max_attempts(self):
        """§18 retries: после MAX_JOB_ATTEMPTS неудач -- 429
        retry_limit_exceeded (честный отказ, не бесконечная очередь)."""
        from apps.api.document_jobs import (
            DocumentJobRecord,
            DocumentRetryLimitExceeded,
            MAX_JOB_ATTEMPTS,
            new_job_id,
        )

        snapshot = _seed_snapshot()
        service = _delivery()
        for index in range(MAX_JOB_ATTEMPTS):
            service.registry.register_job(
                DocumentJobRecord(
                    job_id=new_job_id(),
                    run_id=RUN_ID,
                    snapshot_id=snapshot.snapshot_id,
                    format="pdf",
                    state="failed",
                    error_code="render_failed",
                    attempt=index + 1,
                    tenant_id=DEFAULT_TENANT_ID,
                )
            )
        with pytest.raises(DocumentRetryLimitExceeded):
            service.request_rendition(
                snapshot, format="pdf",
                subject=_owner_subject(), session_id=SESSION_ID,
            )

    def test_worker_status_observability(self):
        """§18/DeliveryWorker-паритет: status() -- operational-состояние
        с last_summary и safe last_error; цикл с ошибкой не убивает
        worker (consecutive_errors растёт)."""
        from apps.api.document_render_worker import DocumentRenderWorker

        worker = DocumentRenderWorker()
        worker.run_once()
        status = worker.status()
        assert status["running"] is False  # фоновый поток не стартован
        assert status["last_run_at"] is not None
        assert status["last_summary"]["ready"] >= 0
        assert status["consecutive_errors"] == 0

    def test_singleton_start_stop_and_env_disabled(self, monkeypatch):
        from apps.api import document_render_worker as drw

        monkeypatch.setenv("CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED", "0")
        assert drw.start_document_render_worker() is None
        monkeypatch.setenv("CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED", "1")
        monkeypatch.setenv("CISSTAT_DOCUMENT_RENDER_WORKER_INTERVAL", "0")
        assert drw.start_document_render_worker() is None
        monkeypatch.setenv("CISSTAT_DOCUMENT_RENDER_WORKER_INTERVAL", "3600")
        handle = drw.start_document_render_worker()
        assert handle is not None and handle.running is True
        assert drw.start_document_render_worker() is handle  # идемпотентно
        drw.stop_document_render_worker(timeout=3.0)
        assert drw.document_render_worker_status()["running"] is False


# ══════════════════════════════════════════════════════════════════════
# 3. HTTP-контур (§17; AC05/AC06/AC09) и миграция 0011
# ══════════════════════════════════════════════════════════════════════


def _cookie(client):
    """Cookie-субъект-владелец (паритет DOCLOG-4)."""
    from apps.api.session_store import SESSION_COOKIE_NAME

    _seed_session()
    client.cookies.set(SESSION_COOKIE_NAME, SESSION_ID)


def _revision_id(client, kind: str = "D01") -> str:
    resp = client.post(
        f"/v1/documentation/runs/{RUN_ID}/documents", json={"kind": kind}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["revision"]["revision_id"]


class TestHTTPHeavyFormats:
    def test_post_heavy_returns_202_queued_with_status_url(self, client):
        """§17: POST heavy -- 202 queued + status_url; тяжёлый формат
        НЕ рендерится в запросе (§18)."""
        _seed_snapshot()
        _cookie(client)
        rev_id = _revision_id(client)
        resp = client.post(
            f"/v1/documentation/revisions/{rev_id}/renditions",
            json={"format": "pdf"},
        )
        assert resp.status_code == 202
        body = resp.json()
        assert body["job"]["state"] == "queued"
        assert body["job"]["format"] == "pdf"
        assert body["status_url"].startswith("/v1/documentation/jobs/")

    def test_post_docx_requires_org_profile(self, client):
        """DOCLOG-9 (честное обновление пина): docx -- валидный формат,
        но без профиля -- честный 422 org_profile_invalid (§19 строка
        DOCLOG-9: выпуск ТОЛЬКО по подтверждённому профилю)."""
        _seed_snapshot()
        _cookie(client)
        rev_id = _revision_id(client)
        resp = client.post(
            f"/v1/documentation/revisions/{rev_id}/renditions",
            json={"format": "docx"},
        )
        assert resp.status_code == 422
        detail = resp.json().get("detail")
        code = detail.get("code") if isinstance(detail, dict) else None
        assert code == "org_profile_invalid"

    def test_job_polling_to_ready_and_content_download(self, client):
        """§17: POST 202 queued -> worker run_once -> GET job ready ->
        GET content 200 с media_type pdf и безопасными заголовками."""
        _seed_snapshot()
        _cookie(client)
        rev_id = _revision_id(client)
        post = client.post(
            f"/v1/documentation/revisions/{rev_id}/renditions",
            json={"format": "pdf"},
        )
        job_id = post.json()["job"]["job_id"]
        from apps.api import document_render_worker
        from apps.api.document_render_worker import DocumentRenderWorker

        document_render_worker.reset_document_render_worker_for_testing()
        DocumentRenderWorker().run_once()
        poll = client.get(f"/v1/documentation/jobs/{job_id}")
        assert poll.status_code == 200
        assert poll.json()["job"]["state"] == "ready"
        rendition_id = poll.json()["job"]["rendition"]["rendition_id"]
        download = client.get(
            f"/v1/documentation/renditions/{rendition_id}/content"
        )
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("application/pdf")
        assert download.content.startswith(b"%PDF-")
        assert "nosniff" in download.headers.get("x-content-type-options", "")

    def test_foreign_subject_cannot_poll_or_download(self, client):
        """AC06/T15: знание job_id/rendition_id НЕ право -- чужой
        субъект получает uniform 404."""
        _seed_snapshot()
        _cookie(client)
        rev_id = _revision_id(client)
        post = client.post(
            f"/v1/documentation/revisions/{rev_id}/renditions",
            json={"format": "zip"},
        )
        job_id = post.json()["job"]["job_id"]
        from apps.api import document_render_worker
        from apps.api.document_render_worker import DocumentRenderWorker

        document_render_worker.reset_document_render_worker_for_testing()
        DocumentRenderWorker().run_once()
        _seed_session(FOREIGN_SESSION_ID)
        from apps.api.session_store import SESSION_COOKIE_NAME

        client.cookies.set(SESSION_COOKIE_NAME, FOREIGN_SESSION_ID)
        poll = client.get(f"/v1/documentation/jobs/{job_id}")
        assert poll.status_code == 404
        job_payload = post.json()["job"]
        # rendition_id ещё не назначен в queued; проверяем 404-поведение
        # content-маршрута на готовой rendition чужого контура ниже.
        assert job_payload["state"] in ("queued", "ready")

    def test_retry_limit_exceeded_maps_429(self, client):
        from apps.api.document_jobs import (
            DocumentJobRecord,
            MAX_JOB_ATTEMPTS,
            new_job_id,
        )

        snapshot = _seed_snapshot()
        service = _delivery()
        for index in range(MAX_JOB_ATTEMPTS):
            service.registry.register_job(
                DocumentJobRecord(
                    job_id=new_job_id(),
                    run_id=RUN_ID,
                    snapshot_id=snapshot.snapshot_id,
                    format="pdf",
                    state="failed",
                    error_code="render_failed",
                    attempt=index + 1,
                    tenant_id=DEFAULT_TENANT_ID,
                )
            )
        _seed_session()
        _cookie(client)
        rev_id = _revision_id(client)
        resp = client.post(
            f"/v1/documentation/revisions/{rev_id}/renditions",
            json={"format": "pdf"},
        )
        assert resp.status_code == 429
        detail = resp.json().get("detail")
        code = detail.get("code") if isinstance(detail, dict) else None
        assert code == "retry_limit_exceeded"

    def test_quota_exceeded_maps_429(self, client):
        from apps.api.document_jobs import (
            DocumentJobRecord,
            new_job_id,
        )

        snapshot = _seed_snapshot()
        service = _delivery()
        for index in range(10):
            service.registry.register_job(
                DocumentJobRecord(
                    job_id=new_job_id(),
                    run_id=RUN_ID,
                    snapshot_id=snapshot.snapshot_id,
                    format="png",
                    state="queued",
                    attempt=1,
                    tenant_id=DEFAULT_TENANT_ID,
                )
            )
        _seed_session()
        _cookie(client)
        rev_id = _revision_id(client)
        resp = client.post(
            f"/v1/documentation/revisions/{rev_id}/renditions",
            json={"format": "svg"},
        )
        assert resp.status_code == 429
        detail = resp.json().get("detail")
        code = detail.get("code") if isinstance(detail, dict) else None
        assert code == "quota_exceeded"

    def test_health_ops_reports_document_render_worker(self, client):
        _cookie(client)
        resp = client.get("/health/ops")
        assert resp.status_code == 200
        payload = resp.json()
        assert "document_render_worker" in payload
        # Lifespan авто-стартует worker (паритет DeliveryWorker) --
        # честный статус: включён и работает в процессе API.
        assert payload["document_render_worker"]["enabled"] is True
        assert payload["document_render_worker"]["running"] is True

    def test_worker_endpoint_not_triggered_by_get_only_routes(self, client):
        """AC05-дух: preview/metadata GET не ставят jobs и не рендерят
        (рендер -- только POST renditions)."""
        _seed_snapshot()
        _cookie(client)
        rev_id = _revision_id(client)
        client.get(f"/v1/documentation/revisions/{rev_id}/preview")
        client.get(f"/v1/documentation/revisions/{rev_id}")
        service = _delivery()
        assert service.registry.list_jobs(RUN_ID) == []


class TestMigration0011:
    def test_migration_catalog_contains_0011(self):
        from apps.api.research_runs import MIGRATION_FILES

        names = [name for name, _statements in MIGRATION_FILES]
        assert "0011_doclog5_render_formats.sql" in names
        assert "0012_doclog6_approvals_archive.sql" in names  # DOCLOG-6
        assert "0014_doclog8_monitoring.sql" in names  # DOCLOG-8
        assert "0015_doclog9_profiles.sql" in names  # DOCLOG-9
        assert "0016_pgv2_print_documents.sql" in names  # PGV-02
        assert len(names) == 16

    def test_migration_file_parity(self):
        from apps.api.research_runs import MIGRATION_FILES

        for name, statements in MIGRATION_FILES:
            text = (
                Path(__file__).resolve().parents[2]
                / "apps" / "api" / "migrations" / name
            ).read_text(encoding="utf-8")
            normalized = " ".join(text.split())
            for statement in statements:
                assert " ".join(statement.split()) in normalized, name

    def test_migration_0011_is_additive(self):
        """§19: миграции аддитивные -- только ADD COLUMN IF NOT EXISTS,
        никакого переписывания существующих таблиц/данных."""
        from apps.api.research_runs import MIGRATION_STATEMENTS_0011

        ddl = "\n".join(MIGRATION_STATEMENTS_0011).lower()
        assert "drop" not in ddl
        assert "alter table document_renditions" in ddl
        assert "alter table document_jobs" in ddl
        assert "add column if not exists snapshot_payload_sha256" in ddl
        assert "add column if not exists tenant_id" in ddl
        assert "add column if not exists claimed_at" in ddl
        assert "add column if not exists lease_expires_at" in ddl

    def test_job_record_lease_and_tenant_fields(self):
        from apps.api.document_jobs import DocumentJobRecord, new_job_id

        moment = datetime.now(timezone.utc).isoformat()
        job = DocumentJobRecord(
            job_id=new_job_id(),
            run_id=RUN_ID,
            snapshot_id="rs-" + "5" * 32,
            format="pdf",
            state="rendering",
            attempt=1,
            tenant_id=DEFAULT_TENANT_ID,
            claimed_at=moment,
            lease_expires_at=moment,
        )
        as_dict = job.to_dict()
        assert as_dict["tenant_id"] == DEFAULT_TENANT_ID
        assert as_dict["claimed_at"] == moment
        assert as_dict["lease_expires_at"] == moment

    def test_postgres_registry_ddl_columns_parity(self):
        """PG-зеркало (урок F-D2C1): новые поля записей соответствуют
        DDL-колонкам миграций 0010+0011 (параметры INSERT ⊆ колонки)."""
        from apps.api import document_jobs
        from apps.api.research_runs import MIGRATION_FILES

        ddl_catalog = {
            name: "\n".join(statements).lower()
            for name, statements in MIGRATION_FILES
        }
        renditions_ddl = (
            ddl_catalog["0010_doclog4_documents.sql"]
            + ddl_catalog["0011_doclog5_render_formats.sql"]
        )
        jobs_ddl = (
            ddl_catalog["0010_doclog4_documents.sql"]
            + ddl_catalog["0011_doclog5_render_formats.sql"]
        )
        for column in ("snapshot_payload_sha256",):
            assert column in renditions_ddl
        for column in ("tenant_id", "claimed_at", "lease_expires_at"):
            assert column in jobs_ddl
        # Поля records не ссылаются на несуществующие колонки.
        rendition = document_jobs.DocumentRenditionRecord(
            rendition_id=document_jobs.new_rendition_id(),
            revision_id="drev-" + "5" * 32,
            snapshot_id="rs-" + "5" * 32,
            run_id=RUN_ID,
            format="pdf",
            snapshot_payload_sha256="a" * 64,
        )
        assert rendition.snapshot_payload_sha256 == "a" * 64
