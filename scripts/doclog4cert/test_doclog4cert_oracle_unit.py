# scripts/doclog4cert/test_doclog4cert_oracle_unit.py
# DOCLOG-4-CERT: юнит-оракулы сертификатора (чистые функции рендеров,
# каталог P0, filename-гигиена, миграционная статика 0010).
# Все данные корпуса -- свои (RUN-D4C*); ожидания выводятся из СПЕКИ
# (§7, §12.3, §15.2, AC03/AC05/AC16), а не из docstring реализации.
from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

import pytest

from conftest import (
    CTX_ALPHA, REV_ALPHA, RUN_ID, SENTINEL_IMG_ONERROR, SENTINEL_JS_SCHEME,
    SENTINEL_PLAIN, SENTINEL_SCRIPT, SESSION_ID, seed_snapshot,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

P0_FORMATS = {"json", "jsonl", "md", "html", "csv"}
HEAVY_FORMATS = {"pdf", "xlsx", "parquet", "svg", "png", "zip", "docx"}


# ══════════════════════════════════════════════════════════════════════
# 1. Каталог форматов P0 (§7)
# ══════════════════════════════════════════════════════════════════════


class TestOrcFormatsCatalog:
    def test_p0_set_matches_spec(self):
        from apps.api.document_renditions import RENDITION_FORMATS

        assert set(RENDITION_FORMATS) == P0_FORMATS

    def test_heavy_formats_absent_doclog5(self):
        from apps.api.document_renditions import RENDITION_FORMATS

        assert not (set(RENDITION_FORMATS) & HEAVY_FORMATS)

    def test_media_types_honest(self):
        from apps.api.document_renditions import RENDITION_FORMATS

        assert RENDITION_FORMATS["json"].media_type == "application/json"
        assert RENDITION_FORMATS["jsonl"].media_type == "application/x-ndjson"
        assert RENDITION_FORMATS["html"].media_type == "text/html"
        assert RENDITION_FORMATS["csv"].media_type == "text/csv"
        assert RENDITION_FORMATS["md"].media_type == "text/markdown"
        for spec in RENDITION_FORMATS.values():
            assert spec.extension == spec.format

    def test_schema_version_constants_exist(self):
        from apps.api import document_renditions as dr

        # §7: JSONL/CSV экспорт обязан нести schema_version (значение --
        # решение реализации; константа должна существовать и быть
        # непустой строкой вида ".../N").
        assert re.fullmatch(r"[a-z0-9.]+/[0-9]+", dr.JSONL_SCHEMA_VERSION)
        assert re.fullmatch(r"[a-z0-9.]+/[0-9]+", dr.CSV_SCHEMA_VERSION)


# ══════════════════════════════════════════════════════════════════════
# 2. JSON-рендер: канон снимка (R06/AC03)
# ══════════════════════════════════════════════════════════════════════


class TestOrcRenderJson:
    def test_json_is_canonical_snapshot_dict(self, orc_env):
        snapshot = seed_snapshot()
        from apps.api.artifact_store import canonical_json_bytes
        from apps.api.document_renditions import render_snapshot_json

        raw = render_snapshot_json(snapshot)
        assert isinstance(raw, bytes)
        assert json.loads(raw.decode("utf-8")) == snapshot.to_dict()
        # Канон DOCLOG-1/2: та же сериализация (sort_keys/compact/no-NaN).
        assert raw == canonical_json_bytes(snapshot.to_dict())

    def test_json_deterministic_bytes(self, orc_env):
        snapshot = seed_snapshot()
        from apps.api.document_renditions import render_snapshot_json

        assert render_snapshot_json(snapshot) == render_snapshot_json(snapshot)

    def test_json_pure_function_no_state(self, orc_env):
        # AC05 (юнит-уровень): рендер не мутирует снимок.
        snapshot = seed_snapshot()
        before = snapshot.to_dict()
        from apps.api.document_renditions import (
            render_snapshot_csv, render_snapshot_html, render_snapshot_json,
            render_snapshot_jsonl, render_snapshot_markdown,
        )

        render_snapshot_json(snapshot)
        render_snapshot_jsonl(snapshot)
        render_snapshot_markdown(snapshot)
        render_snapshot_html(snapshot)
        render_snapshot_csv(snapshot)
        assert snapshot.to_dict() == before


# ══════════════════════════════════════════════════════════════════════
# 3. JSONL-рендер: envelope, одна claim на строку (§7)
# ══════════════════════════════════════════════════════════════════════


class TestOrcRenderJsonl:
    def test_one_claim_per_line_envelope_fields(self, orc_env):
        snapshot = seed_snapshot(kinds=["D01"])
        from apps.api.document_renditions import render_snapshot_jsonl

        raw = render_snapshot_jsonl(snapshot)
        lines = raw.splitlines()
        expected_claims = sum(
            len(section.get("claims", [])) for section in snapshot.sections
        )
        assert len(lines) == expected_claims
        assert raw.endswith("\n")
        for line in lines:
            envelope = json.loads(line)
            assert set(envelope) >= {
                "schema_version", "snapshot_id", "research_run_id",
                "section_code", "text", "event_refs", "result_refs",
                "validity", "captured_at",
            }
            assert envelope["snapshot_id"] == snapshot.snapshot_id
            assert envelope["research_run_id"] == snapshot.research_run_id
            # Формат schema_version пинится паттерном (не любая строка).
            assert re.fullmatch(r"[a-z0-9.]+/[0-9]+", envelope["schema_version"])
            assert isinstance(envelope["event_refs"], list)
            assert isinstance(envelope["result_refs"], list)

    def test_order_and_text_match_snapshot(self, orc_env):
        # Мульти-вид данные: минимум две секции с claims -- иначе
        # инверсия порядка НЕ различима (урок мутанта M06).
        snapshot = seed_snapshot(
            kinds=["D01", "D02"], claim_text=SENTINEL_PLAIN
        )
        from apps.api.document_renditions import render_snapshot_jsonl

        envelopes = [
            json.loads(line)
            for line in render_snapshot_jsonl(snapshot).splitlines()
        ]
        flat_claims = [
            claim
            for section in snapshot.sections
            for claim in section.get("claims", [])
        ]
        assert [e["text"] for e in envelopes] == [
            c.get("text", "") for c in flat_claims
        ]
        assert [e["validity"] for e in envelopes] == [
            c.get("validity", "unknown") for c in flat_claims
        ]
        assert [e["section_code"] for e in envelopes] == [
            section.get("code")
            for section in snapshot.sections
            for _claim in section.get("claims", [])
        ]
        # Порядок строго соответствует frozen-порядку секций снимка
        # (мульти-секционные данные: инверсия/перемешивание ломает).
        codes_in_order = [e["section_code"] for e in envelopes]
        first_positions = [
            codes_in_order.index(code) for code in dict.fromkeys(codes_in_order)
        ]
        assert first_positions == sorted(first_positions)

    def test_empty_snapshot_yields_empty_export(self, orc_env):
        snapshot = seed_snapshot(kinds=["D01"])
        import dataclasses

        empty = dataclasses.replace(
            snapshot,
            sections=[dict(section, claims=[]) for section in snapshot.sections],
        )
        from apps.api.document_renditions import render_snapshot_jsonl

        assert render_snapshot_jsonl(empty) == ""


# ══════════════════════════════════════════════════════════════════════
# 4. Markdown-рендер: честность unknown/partial/gaps (R07/§12.2)
# ══════════════════════════════════════════════════════════════════════


class TestOrcRenderMarkdown:
    def test_complete_snapshot_marked_complete(self, orc_env):
        snapshot = seed_snapshot(kinds=["D01"])
        from apps.api.document_renditions import render_snapshot_markdown

        md = render_snapshot_markdown(snapshot)
        assert snapshot.snapshot_id in md
        assert snapshot.research_run_id in md
        assert "Полнота: complete" in md

    def test_missing_refs_listed_honestly(self, orc_env):
        snapshot = seed_snapshot(kinds=["D01"])
        import dataclasses

        patched = dataclasses.replace(
            snapshot,
            completeness={
                "status": "partial",
                "missing_refs": ["d4c-missing-ref-1", "d4c-missing-ref-2"],
            },
        )
        from apps.api.document_renditions import render_snapshot_markdown

        md = render_snapshot_markdown(patched)
        assert "partial" in md
        assert "d4c-missing-ref-1" in md
        assert "d4c-missing-ref-2" in md

    def test_validity_labels_and_basis(self, orc_env):
        snapshot = seed_snapshot(kinds=["D01"], claim_text=SENTINEL_PLAIN)
        from apps.api.document_renditions import render_snapshot_markdown

        md = render_snapshot_markdown(snapshot)
        # Утверждение и метка валидности присутствуют; основание -- ровно
        # тогда, когда у claim есть evidence/refs (честность R07).
        assert SENTINEL_PLAIN in md
        assert "[актуально]" in md or "[unknown]" in md or "[неизвестно]" in md
        first_claim = snapshot.sections[0]["claims"][0]
        has_basis = bool(
            first_claim.get("evidence_level")
            or first_claim.get("event_refs")
            or first_claim.get("result_refs")
        )
        assert ("Основание:" in md) == has_basis

    def test_approval_honest_null_doclog6(self, orc_env):
        snapshot = seed_snapshot(kinds=["D01"])
        from apps.api.document_renditions import render_snapshot_markdown

        md = render_snapshot_markdown(snapshot)
        # R07: согласование не выдумывается (DOCLOG-6) -- честная пустота.
        assert "Согласование" in md and "—" in md


# ══════════════════════════════════════════════════════════════════════
# 5. HTML-рендер: безопасность по построению (§12.3/AC16)
# ══════════════════════════════════════════════════════════════════════


class TestOrcRenderHtml:
    def test_script_sentinel_never_executable(self, orc_env):
        snapshot = seed_snapshot(kinds=["D01"], claim_text=SENTINEL_SCRIPT)
        from apps.api.document_renditions import render_snapshot_html

        html = render_snapshot_html(snapshot)
        body = html.lower()
        assert "<script" not in body
        assert "d4c-xss-77" in html  # текст виден (экранированным)
        assert "&lt;script&gt;" in html

    def test_event_handler_and_scheme_neutralized(self, orc_env):
        snapshot = seed_snapshot(
            kinds=["D01"], claim_text=SENTINEL_IMG_ONERROR + SENTINEL_JS_SCHEME
        )
        from apps.api.document_renditions import render_snapshot_html

        html = render_snapshot_html(snapshot)
        # Структура: теги/атрибуты не инжектируются (§12.3 «не исполняются");
        # слова sentinel'а видны только как ЭКРАНИРОВАННЫЙ текст.
        for tag in ("<img", "<script", "<iframe", "<object", "<embed", "<svg"):
            assert tag not in html.lower(), tag
        # Атрибутивная форма onerror=" (с сырой кавычкой) невозможна:
        # quote=True переводит кавычки в &quot;.
        assert 'onerror="' not in html
        assert "javascript:" not in html.lower()

    def test_no_external_refs_by_construction(self, orc_env):
        snapshot = seed_snapshot(
            kinds=["D01"],
            claim_text=SENTINEL_PLAIN + " https://d4c-evil.example/x",
        )
        from apps.api.document_renditions import render_snapshot_html

        html = render_snapshot_html(snapshot)
        # Нет <a href, нет <link, нет <iframe, нет src=.
        assert "<a " not in html.lower()
        assert "href=" not in html.lower()
        assert "<link" not in html.lower()
        assert "<iframe" not in html.lower()
        assert "src=" not in html.lower()

    def test_structure_and_gaps_block(self, orc_env):
        snapshot = seed_snapshot(kinds=["D01"])
        import dataclasses

        patched = dataclasses.replace(
            snapshot,
            completeness={
                "status": "partial",
                "missing_refs": ["d4c-gap-A"],
            },
        )
        from apps.api.document_renditions import render_snapshot_html

        html = render_snapshot_html(patched)
        assert html.startswith("<!doctype html>")
        assert 'lang="ru"' in html
        assert 'charset="utf-8"' in html
        assert "<style>" in html
        assert "d4c-gap-A" in html
        assert "gaps" in html

    def test_html_pure_deterministic(self, orc_env):
        snapshot = seed_snapshot(kinds=["D01"])
        from apps.api.document_renditions import render_snapshot_html

        assert render_snapshot_html(snapshot) == render_snapshot_html(snapshot)


# ══════════════════════════════════════════════════════════════════════
# 6. CSV-рендер: spreadsheet-safe профиль §7
# ══════════════════════════════════════════════════════════════════════


class TestOrcRenderCsv:
    def _rows(self, snapshot):
        from apps.api.document_renditions import render_snapshot_csv

        raw = render_snapshot_csv(snapshot)
        reader = csv.reader(io.StringIO(raw, newline=""))
        return raw, list(reader)

    def test_header_and_row_per_claim(self, orc_env):
        snapshot = seed_snapshot(kinds=["D01"])
        raw, rows = self._rows(snapshot)
        expected_claims = sum(
            len(section.get("claims", [])) for section in snapshot.sections
        )
        assert len(rows) == expected_claims + 1
        header = rows[0]
        for column in ("schema_version", "snapshot_id", "research_run_id",
                       "captured_at", "section_code", "claim", "validity",
                       "event_refs", "result_refs"):
            assert column in header
        assert snapshot.snapshot_id in raw

    def test_formula_prefixes_neutralized_text_only(self, orc_env):
        snapshot = seed_snapshot(
            kinds=["D01"], claim_text="=1+1.cmd|' +C:\\x"
        )
        _raw, rows = self._rows(snapshot)
        claims = [row for row in rows[1:] if row]
        # Каждая текстовая claim-ячейка с опасным префиксом нейтрализована.
        for row in claims:
            claim_cell = row[6] if len(row) > 6 else ""
            if claim_cell:
                assert claim_cell.startswith("'") or not claim_cell[0] in "=+-@"

    def test_negative_numbers_not_neutralized(self, orc_env):
        # §7: «не превращая числовые отрицательные значения в текст» --
        # event_count/last_sequence пишутся как числа.
        snapshot = seed_snapshot(kinds=["D01"])
        import dataclasses

        patched = dataclasses.replace(
            snapshot,
            source_cutoff={"event_count": -12, "last_sequence": -3},
        )
        from apps.api.document_renditions import render_snapshot_csv

        raw = render_snapshot_csv(patched)
        assert "-12" in raw
        assert "'-12" not in raw
        assert "'-3" not in raw

    def test_control_chars_stripped_and_iso_date(self, orc_env):
        snapshot = seed_snapshot(
            kinds=["D01"], claim_text="a\x00b\x01c\r\nd4c-tail"
        )
        from apps.api.document_renditions import render_snapshot_csv

        raw = render_snapshot_csv(snapshot)
        for control in ("\x00", "\x01"):
            assert control not in raw
        if snapshot.captured_at:
            assert snapshot.captured_at[:10] in raw  # ISO-дата присутствует

    def test_csv_pure_deterministic(self, orc_env):
        snapshot = seed_snapshot(kinds=["D01"])
        from apps.api.document_renditions import render_snapshot_csv

        assert render_snapshot_csv(snapshot) == render_snapshot_csv(snapshot)


# ══════════════════════════════════════════════════════════════════════
# 7. filename_for: гигиена Content-Disposition (§15.2)
# ══════════════════════════════════════════════════════════════════════


class TestOrcFilenameFor:
    def test_traversal_and_garbage_sanitized(self):
        from apps.api.document_renditions import filename_for

        for evil in (
            "../../etc/passwd", "/abs/path", "a\\b", "drev-../..",
            "drev\x00null", "drev-юникод", "", None,
        ):
            name = filename_for(evil, "md")
            assert "/" not in name
            assert "\\" not in name
            assert ".." not in name
            assert "\x00" not in name
            assert re.fullmatch(r"document-[A-Za-z0-9_-]*\.md", name), name

    def test_unknown_format_falls_back_to_bin(self):
        from apps.api.document_renditions import filename_for

        assert filename_for("drev-" + "a" * 32, "pdf").endswith(".bin")


# ══════════════════════════════════════════════════════════════════════
# 8. Миграция 0010: статические факты (каталог/DDL/паритет)
# ══════════════════════════════════════════════════════════════════════


class TestOrcMigrationStatics:
    def test_catalog_ten_files_0010_present(self):
        from apps.api.research_runs import MIGRATION_FILES

        names = [name for name, _statements in MIGRATION_FILES]
        assert len(names) == 10
        assert "0010_doclog4_documents.sql" in names
        # Порядок-нумерация без дыр.
        assert names == sorted(names)

    def test_statements_catalog_total_62(self):
        from apps.api.research_runs import MIGRATION_FILES

        total = sum(len(statements) for _name, statements in MIGRATION_FILES)
        assert total == 62

    def test_file_catalog_parity_independent_norm(self):
        from apps.api.research_runs import MIGRATION_FILES

        names = [name for name, _statements in MIGRATION_FILES]
        # DOCLOG-4-чувствительность: паритет проверяется ВМЕСТЕ с фактом
        # регистрации 0010 (иначе оракул проходил бы и на родителе).
        assert "0010_doclog4_documents.sql" in names

        def _norm(value: str) -> str:
            return " ".join(value.split())

        for name, statements in MIGRATION_FILES:
            text = (
                REPO_ROOT / "apps" / "api" / "migrations" / name
            ).read_text(encoding="utf-8")
            normalized = _norm(text)
            for statement in statements:
                assert _norm(statement) in normalized, (name, statement[:50])

    def test_documents_ddl_idempotency_uniques(self):
        from apps.api.research_runs import MIGRATION_STATEMENTS_0010

        ddl = " ".join(MIGRATION_STATEMENTS_0010).lower()
        # AC09: идемпотентность выдачи на уровне схемы.
        assert "unique (snapshot_id, format, redaction_profile)" in ddl
        # Ревизия 1:1 снимок (адаптер, не дубли).
        assert "unique (document_id, snapshot_id)" in ddl
        # Монотонные версии документа.
        assert "unique (document_id, version_no)" in ddl
        # Документ уникален в паре (run, kind).
        assert "unique (run_id, kind_code)" in ddl
        # Документный слой не переживает научный (CASCADE).
        assert "on delete cascade" in ddl
        assert "references report_snapshots(snapshot_id)" in ddl

    def test_no_drop_or_alter_of_science_tables(self):
        from apps.api.research_runs import MIGRATION_STATEMENTS_0010

        ddl = " ".join(MIGRATION_STATEMENTS_0010).lower()
        # Аддитивность (reader раньше writer): миграция ничего не ломает.
        assert "drop " not in ddl
        assert "alter table report_snapshots" not in ddl
        assert "alter table artifacts" not in ddl
