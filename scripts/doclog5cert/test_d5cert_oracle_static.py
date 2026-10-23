# scripts/doclog5cert/test_d5cert_oracle_static.py
"""DOCLOG-5-CERT: статические/PG-parity оракулы (класс d5pgm) -- урок
F-D2C1 (соответствие колонок row-reader'а и INSERT) и аддитивность
миграции 0011. Работают БЕЗ живого PG: сверка исходников и DDL."""
from __future__ import annotations

import inspect
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MIGRATION_0011 = REPO / "apps" / "api" / "migrations" / "0011_doclog5_render_formats.sql"


def _migration_ddl() -> str:
    return MIGRATION_0011.read_text(encoding="utf-8")


def _source(cls_or_func) -> str:
    return inspect.getsource(cls_or_func)


def _flatten(source: str) -> str:
    """Флэттенинг исходника: снять кавычки строковых литералов и
    переводы строк -- SQL становится однострочным для надёжного
    статического разбора."""
    return " ".join(source.replace('"', " ").split())


def _insert_columns(flat: str, table: str) -> list[str]:
    """Колонки первого INSERT INTO <table> (...) во флэттенинге."""
    match = re.search(
        rf"INSERT INTO {table}\s*\((.*?)\) VALUES", flat, re.I
    )
    assert match is not None, f"INSERT INTO {table} не найден"
    return [col.strip() for col in match.group(1).split(",")]


def _select_columns(flat: str, class_attr: str) -> list[str]:
    """Колонки SELECT-константы класса (_JOB_SELECT/_RENDITION_SELECT)."""
    match = re.search(
        rf"{class_attr}\s*=\s*\(? SELECT (.*?) FROM",
        flat,
        re.I,
    )
    if match is None:
        return []
    return [col.strip() for col in match.group(1).split(",")]


# ══════════════════════════════════════════════════════════════════════
# Миграция 0011: аддитивность и каталог
# ══════════════════════════════════════════════════════════════════════


class TestMigration0011Static:
    def test_d5pgm01_additive_only(self):
        """§19 «миграции аддитивные»: только ADD COLUMN IF NOT EXISTS и
        CREATE INDEX IF NOT EXISTS; никакого UPDATE/DELETE/DROP/ALTER
        TYPE."""
        raw = _migration_ddl()
        # убираем комментарии перед разбором statement'ов
        no_comments = "\n".join(
            line for line in raw.splitlines()
            if not line.strip().startswith("--")
        )
        statements = [
            s.strip() for s in no_comments.split(";") if s.strip()
        ]
        assert statements, "миграция пуста"
        for stmt in statements:
            low = " ".join(stmt.lower().split())
            assert (
                low.startswith("alter table")
                and "add column if not exists" in low
            ) or low.startswith("create index if not exists"), stmt[:80]
        low_all = " ".join(no_comments.lower().split())
        assert "update " not in low_all.replace("updated_at", "")
        assert "delete from" not in low_all
        assert "drop " not in low_all

    def test_d5pgm02_catalog_contains_0011(self):
        from apps.api.research_runs import MIGRATION_FILES

        names = [name for name, _ in MIGRATION_FILES]
        assert "0011_doclog5_render_formats.sql" in names
        assert len(MIGRATION_FILES) == 11

    def test_d5pgm03_new_columns_present_in_ddl(self):
        ddl = " ".join(_migration_ddl().lower().split())
        assert "snapshot_payload_sha256 text not null default ''" in ddl
        assert "add column if not exists tenant_id text" in ddl
        assert "add column if not exists claimed_at timestamptz" in ddl
        assert "add column if not exists lease_expires_at timestamptz" in ddl
        assert "idx_document_jobs_state" in ddl

    def test_d5pgm04_catalog_parity_with_file(self):
        """Каталог MIGRATION_STATEMENTS_0011 == statement'ы файла
        (паритет файл-каталог)."""
        from apps.api.research_runs import MIGRATION_STATEMENTS_0011

        ddl = _migration_ddl()
        # грубый паритет: каждый catalog-statement встречается в файле
        for statement in MIGRATION_STATEMENTS_0011:
            normalized = " ".join(statement.split()).lower()
            file_normalized = " ".join(ddl.split()).lower()
            assert normalized in file_normalized, statement[:60]
        assert len(MIGRATION_STATEMENTS_0011) == 5


# ══════════════════════════════════════════════════════════════════════
# Урок F-D2C1: row-reader читает ТОЛЬКО колонки, которые пишет INSERT
# ══════════════════════════════════════════════════════════════════════


class TestPgMirrorColumnParity:
    def test_d5pgm05_job_reader_insert_parity(self):
        """document_jobs: каждая колонка _JOB_SELECT входит в INSERT
        (позиционное чтение строк psycopg честно -- урок F-D2C1)."""
        from apps.api.document_jobs import PostgresDocumentRegistry

        flat = _flatten(_source(PostgresDocumentRegistry))
        insert_cols = _insert_columns(flat, "document_jobs")
        select_cols = _select_columns(flat, "_JOB_SELECT")
        assert select_cols, "_JOB_SELECT не разобран"
        for col in select_cols:
            assert col in insert_cols, (
                f"колонка {col!r} читается, но не пишется INSERT'ом "
                "(класс F-D2C1)"
            )
        for col in ("tenant_id", "claimed_at", "lease_expires_at"):
            assert col in insert_cols, col
            assert col in select_cols, col

    def test_d5pgm06_rendition_reader_insert_parity(self):
        """document_renditions: ридер включает snapshot_payload_sha256,
        и эта колонка есть в INSERT/UPDATE (§19 единый hash)."""
        from apps.api.document_jobs import PostgresDocumentRegistry

        flat = _flatten(_source(PostgresDocumentRegistry))
        insert_cols = _insert_columns(flat, "document_renditions")
        select_cols = _select_columns(flat, "_RENDITION_SELECT")
        assert select_cols, "_RENDITION_SELECT не разобран"
        assert "snapshot_payload_sha256" in select_cols
        for col in select_cols:
            assert col in insert_cols, (
                f"колонка {col!r} читается, но не пишется INSERT'ом "
                "(класс F-D2C1)"
            )

    def test_d5pgm07_rendition_upsert_assigns_snapshot_hash(self):
        """UPSERT rendition (ON CONFLICT DO UPDATE) переносит
        snapshot_payload_sha256 при retry."""
        from apps.api.document_jobs import PostgresDocumentRegistry

        flat = _flatten(_source(PostgresDocumentRegistry))
        assert "on conflict" in flat.lower()
        match = re.search(
            r"DO UPDATE SET (.*?)(?:, \( | RETURNING|$)", flat, re.I
        )
        assert match is not None, "DO UPDATE SET не найден"
        assert (
            "snapshot_payload_sha256 = EXCLUDED.snapshot_payload_sha256"
            in match.group(1)
        )

    def test_d5pgm08_job_upsert_writes_lease_and_tenant(self):
        """INSERT document_jobs включает tenant_id/claimed_at/
        lease_expires_at (lease-контракт worker'а в durable-слое)."""
        from apps.api.document_jobs import PostgresDocumentRegistry

        flat = _flatten(_source(PostgresDocumentRegistry))
        insert_cols = _insert_columns(flat, "document_jobs")
        for col in ("tenant_id", "claimed_at", "lease_expires_at"):
            assert col in insert_cols, col

    def test_d5pgm09_list_open_jobs_filters_open_states(self):
        """list_open_jobs (ABC/Memory/Postgres) возвращает ТОЛЬКО
        queued/rendering -- фундамент реклейма и квот."""
        from apps.api.document_jobs import (
            JOB_QUEUED,
            JOB_RENDERING,
            MemoryDocumentRegistry,
            PostgresDocumentRegistry,
        )

        mem_source = _source(MemoryDocumentRegistry.list_open_jobs)
        assert "open_states" in mem_source
        pg_source = _source(PostgresDocumentRegistry.list_open_jobs)
        low = " ".join(pg_source.lower().split())
        assert "queued" in low and "rendering" in low

    def test_d5pgm10_worker_reads_registry_hash_source(self):
        """load_snapshot_system переносит payload_sha256 из
        registry-метаданных (источник единого hash §19)."""
        from apps.api.document_render_worker import load_snapshot_system

        source = _source(load_snapshot_system)
        assert "payload_sha256" in source
        assert "SnapshotIntegrityError" in source
