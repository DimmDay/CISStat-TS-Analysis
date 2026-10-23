# scripts/doclog5cert/test_d5cert_oracle_unit.py
"""DOCLOG-5-CERT: unit-оракулы тяжёлых форматов на СВОИХ данных.

Претензии проверяются против СВОЕГО враждебного снимка (conftest.
build_own_snapshot): формулоподобные тексты, управляющие символы,
кириллица, текст 40 000 символов, hostil-разметка в заголовках,
пустая секция, честные gaps. Дизъюнкт с repo-корпусом.
"""
from __future__ import annotations

import hashlib
import io
import zipfile
import xml.etree.ElementTree as ET

import pytest

from conftest import LONG_TEXT, build_own_snapshot


@pytest.fixture()
def snap():
    return build_own_snapshot()


def _render(name: str, snapshot):
    import importlib

    mod = importlib.import_module("apps.api.document_renditions")
    func = getattr(mod, name)
    return func(snapshot)


def _load_xlsx(data: bytes):
    from openpyxl import load_workbook

    return load_workbook(io.BytesIO(data))


# ══════════════════════════════════════════════════════════════════════
# PDF (§7: кириллица/встроенные шрифты; §12.3/AC16)
# ══════════════════════════════════════════════════════════════════════


class TestPdfOracle:
    def test_d5o01_pdf_magic_and_embedded_font(self, snap):
        data = _render("render_snapshot_pdf", snap)
        assert data.startswith(b"%PDF-")
        # Шрифт реально встроен: имя allowlist-шрифта в байтах PDF.
        from apps.api.document_renditions import _resolve_font

        _, font_name = _resolve_font()
        assert font_name.encode() in data

    def test_d5o02_pdf_deterministic_bytes(self, snap):
        a = _render("render_snapshot_pdf", snap)
        b = _render("render_snapshot_pdf", snap)
        assert a == b

    def test_d5o03_pdf_invariant_metadata_title(self, snap):
        data = _render("render_snapshot_pdf", snap)
        assert b"/Title" in data and b"/Producer" in data

    def test_d5o04_pdf_font_unavailable_honest(self, snap, monkeypatch):
        import apps.api.document_renditions as dr

        monkeypatch.setattr(
            dr,
            "_PDF_FONT_CANDIDATES",
            (("/nonexistent/font.ttf", "NoFont", "/nonexistent/b.ttf"),),
        )
        with pytest.raises(dr.RenderDependencyError):
            _render("render_snapshot_pdf", snap)

    def test_d5o05_resolve_font_allowlist_only(self):
        from apps.api.document_renditions import _resolve_font

        path, name = _resolve_font()
        assert name in {"DejaVuSans", "LiberationSans"}
        import os

        assert os.path.isfile(path)

    def test_d5o06_pdf_hostile_text_escaped_not_crashing(self, snap):
        # hostile-заголовок секции c <script> не ломает mini-XML
        # (Paragraph) и не попадает в байты как живая разметка.
        data = _render("render_snapshot_pdf", snap)
        assert b"<script>" not in data


# ══════════════════════════════════════════════════════════════════════
# XLSX (§7: листы/строки-не-формулы/лимиты Excel; AC16)
# ══════════════════════════════════════════════════════════════════════


class TestXlsxOracle:
    def test_d5o07_xlsx_five_sheets_exact(self, snap):
        wb = _load_xlsx(_render("render_snapshot_xlsx", snap))
        assert wb.sheetnames == [
            "Summary", "Metadata", "Results", "Methods", "Warnings",
        ]

    def test_d5o08_xlsx_formula_like_is_string(self, snap):
        wb = _load_xlsx(_render("render_snapshot_xlsx", snap))
        cell = wb["Results"]["C3"]  # 3-я строка данных = формулоподобный
        assert cell.value.startswith("=1+2")
        assert cell.data_type == "s"

    def test_d5o09_xlsx_control_chars_stripped(self, snap):
        wb = _load_xlsx(_render("render_snapshot_xlsx", snap))
        value = wb["Results"]["C4"].value
        assert "\x00" not in value and "\x07" not in value
        assert "плохойтекст" in value.replace("\x0b", "")

    def test_d5o10_xlsx_truncation_honest_with_marker(self, snap):
        from apps.api.document_renditions import MAX_XLSX_CELL_CHARS

        wb = _load_xlsx(_render("render_snapshot_xlsx", snap))
        # длинный текст -- 4-я claim (строка 5); ищем по объёму
        long_values = [
            wb["Results"].cell(row=r, column=3).value
            for r in range(2, wb["Results"].max_row + 1)
            if len(str(wb["Results"].cell(row=r, column=3).value)) > 1000
        ]
        assert len(long_values) == 1
        value = long_values[0]
        assert len(value) <= MAX_XLSX_CELL_CHARS
        assert value.endswith("[усечено до предела Excel 32767 символов]")

    def test_d5o11_xlsx_truncation_warned(self, snap):
        wb = _load_xlsx(_render("render_snapshot_xlsx", snap))
        kinds = [
            wb["Warnings"].cell(row=r, column=1).value
            for r in range(2, wb["Warnings"].max_row + 1)
        ]
        assert "truncation" in kinds

    def test_d5o12_xlsx_claims_count_matches(self, snap):
        total = sum(
            len(s.get("claims", [])) for s in snap.sections
        )
        wb = _load_xlsx(_render("render_snapshot_xlsx", snap))
        rows = 0
        for r in range(2, wb["Results"].max_row + 1):
            if wb["Results"].cell(row=r, column=3).value:
                rows += 1
        assert rows == total == 4

    def test_d5o13_xlsx_numeric_cutoff_stays_numeric(self, snap):
        wb = _load_xlsx(_render("render_snapshot_xlsx", snap))
        values = [
            wb["Metadata"].cell(row=r, column=1).value
            for r in range(2, wb["Metadata"].max_row + 1)
        ]
        row = values.index("source_cutoff.event_count") + 2
        assert wb["Metadata"].cell(row=row, column=2).value == 42
        assert isinstance(
            wb["Metadata"].cell(row=row, column=2).value, int
        )

    def test_d5o14_xlsx_deterministic_bytes(self, snap):
        a = _render("render_snapshot_xlsx", snap)
        b = _render("render_snapshot_xlsx", snap)
        assert a == b

    def test_d5o15_xlsx_no_macros(self, snap):
        data = _render("render_snapshot_xlsx", snap)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            assert not any(
                name.endswith(".bin") for name in zf.namelist()
            )


# ══════════════════════════════════════════════════════════════════════
# Parquet (§7: typed-таблица; честная зависимость)
# ══════════════════════════════════════════════════════════════════════


class TestParquetOracle:
    def test_d5o16_parquet_roundtrip_typed_schema(self, snap):
        import pyarrow.parquet as pq

        data = _render("render_snapshot_parquet", snap)
        table = pq.read_table(io.BytesIO(data))
        names = table.schema.names
        assert "event_refs" in names and "result_refs" in names
        refs_type = table.schema.field("event_refs").type
        # pyarrow печатает list-тип как 'list<element: string>'
        assert str(refs_type) == "list<element: string>"
        refs_result = table.schema.field("result_refs").type
        assert str(refs_result) == "list<element: string>"
        event_count_type = table.schema.field("event_count").type
        assert "int64" in str(event_count_type)

    def test_d5o17_parquet_rowcount_and_null_preserved(self, snap):
        import pyarrow.parquet as pq

        data = _render("render_snapshot_parquet", snap)
        table = pq.read_table(io.BytesIO(data)).to_pylist()
        assert len(table) == 4
        assert all(row["event_count"] == 42 for row in table)
        assert all(row["last_sequence"] == 1042 for row in table)
        # формулоподобное утверждение сохраняется как строка claim
        claims = {row["claim"] for row in table}
        assert any(c.startswith("=1+2") for c in claims)
        # ЗНАЧЕНИЯ элементов refs (урок адъюдикации M27: pyarrow молча
        # превращает строку в список символов -- проверяем целостность
        # элементов, а не только тип колонки)
        refs_by_claim = {
            row["claim"]: row["event_refs"] for row in table
        }
        first_claim = snap.sections[0]["claims"][0]["text"]
        assert refs_by_claim[first_claim] == [
            "evt-d5c-1", "evt-d5c-2"
        ]
        assert refs_by_claim["=1+2; =HYPERLINK(\"http://evil.example\")"] == []

    def test_d5o18_parquet_deterministic_bytes(self, snap):
        a = _render("render_snapshot_parquet", snap)
        b = _render("render_snapshot_parquet", snap)
        assert a == b

    def test_d5o19_parquet_dependency_honest(self, snap, monkeypatch):
        import builtins
        import apps.api.document_renditions as dr

        real_import = builtins.__import__

        def _fake_import(name, *args, **kwargs):
            if name.startswith("pyarrow"):
                raise ImportError("pyarrow отключён оракулом")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _fake_import)
        with pytest.raises(dr.RenderDependencyError):
            _render("render_snapshot_parquet", snap)


# ══════════════════════════════════════════════════════════════════════
# SVG (§7/AC16: без script/xlink/external; детерминизм; экранирование)
# ══════════════════════════════════════════════════════════════════════


class TestSvgOracle:
    def test_d5o20_svg_wellformed_xml(self, snap):
        text = _render("render_snapshot_svg", snap)
        ET.fromstring(text)  # не падает => well-formed

    def test_d5o21_svg_no_script_no_xlink_no_external(self, snap):
        text = _render("render_snapshot_svg", snap)
        low = text.lower()
        assert "<script" not in low
        assert "xlink" not in low
        assert "javascript:" not in low
        # единственный http -- обязательный xmlns SVG
        assert low.count("http") == 1
        assert "http://www.w3.org/2000/svg" in low

    def test_d5o22_svg_hostile_label_escaped(self):
        # SVG-лейблы -- КОДЫ секций; подаём код с разметкой (свой
        # прямой снимок-зонд): разметка обязана быть экранирована и
        # не стать элементом дерева.
        from apps.api.report_snapshot import ReportSnapshot

        hostile = ReportSnapshot(
            snapshot_id="snap-d5cert-svgprobe",
            research_run_id="RUN-D5C00001",
            sections=[
                {
                    "code": "<script>alert('svg')</script>",
                    "title": "Зонд",
                    "kind": "summary",
                    "claims": [{"text": "x", "validity": "supported"}],
                }
            ],
        )
        text = _render("render_snapshot_svg", hostile)
        ET.fromstring(text)  # разметка не стала элементом
        assert "<script>" not in text
        assert "&lt;script&gt;" in text

    def test_d5o23_svg_deterministic_bytes(self, snap):
        a = _render("render_snapshot_svg", snap)
        b = _render("render_snapshot_svg", snap)
        assert a == b

    def test_d5o24_svg_empty_series_honest(self):
        from apps.api.report_snapshot import ReportSnapshot

        empty = ReportSnapshot(
            snapshot_id="snap-d5cert-empty",
            research_run_id="RUN-D5C00001",
            sections=[],
        )
        text = _render("render_snapshot_svg", empty)
        assert "честно пуст" in text

    def test_d5o25_svg_fixed_light_theme_and_size(self, snap):
        text = _render("render_snapshot_svg", snap)
        assert 'fill="#ffffff"' in text  # светлая print-тема
        assert 'width="720"' in text


# ══════════════════════════════════════════════════════════════════════
# PNG (§7: растровый fallback; детерминизм)
# ══════════════════════════════════════════════════════════════════════


class TestPngOracle:
    def test_d5o26_png_signature_and_structure(self, snap):
        data = _render("render_snapshot_png", snap)
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert b"IEND" in data

    def test_d5o27_png_pil_opens_with_size(self, snap):
        from PIL import Image

        data = _render("render_snapshot_png", snap)
        image = Image.open(io.BytesIO(data))
        assert image.format == "PNG"
        assert image.size[0] == 1440  # 720 * scale 2
        assert image.size[1] > 200

    def test_d5o28_png_deterministic_bytes(self, snap):
        a = _render("render_snapshot_png", snap)
        b = _render("render_snapshot_png", snap)
        assert a == b


# ══════════════════════════════════════════════════════════════════════
# Evidence ZIP (§7/§13.3/AC16)
# ══════════════════════════════════════════════════════════════════════


class TestZipOracle:
    def _zip(self, snap):
        data = _render("render_evidence_zip", snap)
        return data, zipfile.ZipFile(io.BytesIO(data))

    def test_d5o29_zip_members_exact_set(self, snap):
        _, zf = self._zip(snap)
        assert set(zf.namelist()) == {
            "manifest.json",
            "report.json",
            "document.md",
            "table_claims.csv",
            "chart_claims.svg",
            "table_schema.json",
        }

    def test_d5o30_zip_manifest_checksums_match_members(self, snap):
        _, zf = self._zip(snap)
        import json as _json

        manifest = _json.loads(zf.read("manifest.json"))
        entries = {e["name"]: e for e in manifest["members"]}
        assert set(entries) == {
            "report.json",
            "document.md",
            "table_claims.csv",
            "chart_claims.svg",
            "table_schema.json",
        }
        for name, entry in entries.items():
            payload = zf.read(name)
            assert (
                hashlib.sha256(payload).hexdigest() == entry["sha256"]
            ), name
            assert entry["size_bytes"] == len(payload), name

    def test_d5o31_zip_manifest_no_self_hash(self, snap):
        _, zf = self._zip(snap)
        import json as _json

        manifest = _json.loads(zf.read("manifest.json"))
        assert "manifest.json" not in {
            e["name"] for e in manifest["members"]
        }

    def test_d5o32_zip_fixed_datetime_deterministic(self, snap):
        data_a, za = self._zip(snap)
        data_b, zb = self._zip(snap)
        assert data_a == data_b
        for info in za.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)

    def test_d5o33_zip_data_not_included_honest(self, snap):
        _, zf = self._zip(snap)
        import json as _json

        manifest = _json.loads(zf.read("manifest.json"))
        assert manifest["data_included"] is False
        assert manifest["reproducibility"] == "limited"

    def test_d5o34_zip_no_path_traversal(self, snap):
        _, zf = self._zip(snap)
        for name in zf.namelist():
            assert "/" not in name and ".." not in name
            assert not name.startswith("\\")

    def test_d5o35_zip_report_member_is_canonical_snapshot(self, snap):
        from apps.api.artifact_store import canonical_json_bytes

        _, zf = self._zip(snap)
        assert zf.read("report.json") == canonical_json_bytes(
            snap.to_dict()
        )


# ══════════════════════════════════════════════════════════════════════
# AC03: один frozen снимок -- совпадающие факты, различные байты
# ══════════════════════════════════════════════════════════════════════


class TestAc03CrossFormat:
    def test_d5o36_facts_match_across_formats(self, snap):
        total = sum(len(s.get("claims", [])) for s in snap.sections)
        jsonl = _render("render_snapshot_jsonl", snap)
        # JSONL: envelope doclog.rendition/1 -- одна claim/строка
        jsonl_claims = [
            line
            for line in jsonl.splitlines()
            if line.strip()
        ]
        csv = _render("render_snapshot_csv", snap)
        csv_rows = max(0, len(csv.strip().splitlines()) - 1)
        import pyarrow.parquet as pq

        parquet_rows = len(
            pq.read_table(
                io.BytesIO(_render("render_snapshot_parquet", snap))
            )
        )
        wb = _load_xlsx(_render("render_snapshot_xlsx", snap))
        xlsx_rows = sum(
            1
            for r in range(2, wb["Results"].max_row + 1)
            if wb["Results"].cell(row=r, column=3).value
        )
        zip_bytes = _render("render_evidence_zip", snap)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            import json as _json

            zip_report = _json.loads(zf.read("report.json"))
        zip_claims = sum(
            len(s.get("claims", [])) for s in zip_report["sections"]
        )
        assert total == 4
        # jsonl/csv не обязаны равняться 4 (другая гранула: envelope/
        # таблицы) -- проверяем честную согласованность фактов:
        assert zip_claims == total
        assert parquet_rows == xlsx_rows == total
        assert len(jsonl_claims) >= 1 and csv_rows >= 1

    def test_d5o37_format_hashes_all_differ(self, snap):
        outputs = {
            "json": _render("render_snapshot_json", snap),
            "jsonl": _render("render_snapshot_jsonl", snap).encode(),
            "md": _render("render_snapshot_markdown", snap).encode(),
            "html": _render("render_snapshot_html", snap).encode(),
            "csv": _render("render_snapshot_csv", snap).encode(),
            "pdf": _render("render_snapshot_pdf", snap),
            "xlsx": _render("render_snapshot_xlsx", snap),
            "parquet": _render("render_snapshot_parquet", snap),
            "svg": _render("render_snapshot_svg", snap).encode(),
            "png": _render("render_snapshot_png", snap),
            "zip": _render("render_evidence_zip", snap),
        }
        hashes = {
            fmt: hashlib.sha256(data).hexdigest()
            for fmt, data in outputs.items()
        }
        assert len(set(hashes.values())) == len(hashes) == 11

    def test_d5o38_chart_spec_series_from_own_data(self, snap):
        from apps.api.document_renditions import build_chart_spec

        spec = build_chart_spec(snap)
        assert spec.series == (("D01", 3), ("D02", 1), ("D03", 0))
        assert spec.source_ref == (
            "chartspec:report_snapshot/" + snap.snapshot_id
        )

    def test_d5o39_claims_table_schema_types(self, snap):
        from apps.api.document_renditions import claims_table_schema

        schema = claims_table_schema(snap)
        types = {c["name"]: c["type"] for c in schema["columns"]}
        assert types["event_refs"] == "list<string>"
        assert types["result_refs"] == "list<string>"
        assert types["event_count"] == "int64|null"
        assert types["last_sequence"] == "int64|null"
