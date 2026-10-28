#!/usr/bin/env python3
# scripts/pgv02/check_documents.py
"""Doc-contract гвард PGV-02 (паттерн scripts/pgv00/pgv01): документация
== поставка. Проверяет, что spec-маркеры, документ поставки, worklog-запись
и родительская спека согласованы с фактическими файлами поставки.

Запуск: python3 scripts/pgv02/check_documents.py   (exit 0 = GREEN).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

EXPECTED_SITES = 93
EXPECTED_MIGRATION_FILES = 16
EXPECTED_MIGRATION_STATEMENTS = 96

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    CHECKS.append((name, bool(condition), detail))


def main() -> int:
    spec = (REPO / "spec_passport_graphics_visual.md").read_text(encoding="utf-8")
    parent = (REPO / "spec_documentation_logging.md").read_text(encoding="utf-8")
    doc = (REPO / "docs/pgv02_durable_inputs.md").read_text(encoding="utf-8")
    worklog = (REPO / "worklog/worklog11.md").read_text(encoding="utf-8")

    # ── 1. Спецификация: строка задачи и критерий ────────────────────
    check("spec §13: строка PGV-02 с зависимостью PGV-01",
          re.search(r"PGV-02\s*\|\s*PGV-01\s*\|", spec) is not None)
    check("spec §13: точки изменения artifact_store/report_snapshot/SQL/validators",
          re.search(
              r"PGV-02\s*\|\s*PGV-01\s*\|\s*Durable inputs/V01/P01/P02\s*\|"
              r"\s*artifact_store/report_snapshot/SQL/validators", spec) is not None)
    check("spec §13: критерий «Versioned migrations и legacy D01–12/readers работают»",
          "Versioned migrations и legacy D01–12/readers работают" in spec)
    check("spec §6: новый kind visual_result",
          "Новый kind `visual_result` расширяет" in spec)
    check("spec §8: новый artifact kind passport_checkpoint",
          "Новый artifact kind **passport_checkpoint**" in spec)
    check("spec §10.2: аддитивные типы V01/P01/P02",
          "**V01** scientific visual, **P01** saved passport/комплект, **P02** comparison" in spec)
    check("spec §10.2: не переименование D02", "не переименование D02" in spec)

    # ── 2. Родительская спека: аддитивная строка PGV-02 ──────────────
    check("parent §19: строка PGV-02", "| PGV-02 — durable inputs/V01/P01/P02" in parent)
    check("parent §19: строка PGV-01 сохранена",
          "| PGV-01 — print-схемы, metadata и профили" in parent)
    check("parent §19: строка DOCLOG-1 сохранена (legacy)",
          "| DOCLOG-1 — устойчивые артефакты" in parent)

    # ── 3. Документ поставки ─────────────────────────────────────────
    check("doc: заголовок PGV-02", "# PGV-02 — Durable inputs/V01/P01/P02" in doc)
    check("doc: база 7b72636", "main@7b72636" in doc)
    check("doc: критерий спеки процитирован",
          "Versioned migrations и legacy D01–12/readers работают" in doc)
    check("doc: ключевые файлы перечислены",
          all(name in doc for name in (
              "apps/api/visual_artifacts.py",
              "apps/api/artifact_store.py",
              "apps/api/artifact_promotion.py",
              "apps/api/report_snapshot.py",
              "apps/api/document_jobs.py",
              "apps/api/migrations/0016_pgv2_print_documents.sql",
          )))
    check("doc: AC07/AC09/AC11/AC12/AC14/AC22 упомянуты",
          all(ac in doc for ac in (
              "PGV-AC07", "PGV-AC09", "PGV-AC11", "PGV-AC12", "PGV-AC14", "PGV-AC22")))
    check("doc: честные границы (producer/reader/renderer вне скоупа)",
          "PGV-03/04" in doc and "PGV-05" in doc and "PGV-07/08/09" in doc)

    # ── 4. Worklog ───────────────────────────────────────────────────
    check("worklog: запись Task ID: PGV-02", "## Task ID: PGV-02" in worklog)
    check("worklog: фиксация базы 7b72636", "7b72636" in worklog)

    # ── 5. Фактические файлы поставки ────────────────────────────────
    va = REPO / "apps/api/visual_artifacts.py"
    check("visual_artifacts.py существует", va.exists())
    if va.exists():
        va_text = va.read_text(encoding="utf-8")
        check("visual_artifacts: pgv.passport_checkpoint/1",
              'CHECKPOINT_SCHEMA_VERSION = "pgv.passport_checkpoint/1"' in va_text)
        check("visual_artifacts: schema-пины трёх kinds",
              all(k in va_text for k in (
                  "visual_result", "visual_print_snapshot", "passport_checkpoint")))
        check("visual_artifacts: CAS conflict code",
              'self.error_code = "context_changed"' in va_text)
        check("visual_artifacts: producer_key конвенции",
              all(s in va_text for s in (
                  "pgv.visual_result:", "pgv.print_snapshot:", "pgv.checkpoint:")))
        check("visual_artifacts: нет смешанных алфавитов",
              re.search(r"\b(?=\w*[а-яА-ЯёЁ])(?=\w*[a-zA-Z])\w+\b", va_text) is None)

    store = (REPO / "apps/api/artifact_store.py").read_text(encoding="utf-8")
    check("artifact_store: три новых kinds",
          all(k in store for k in (
              '"visual_result",', '"visual_print_snapshot",', '"passport_checkpoint",')))
    check("artifact_store: legacy kinds сохранены",
          all(k in store for k in (
              '"passport",', '"oof_backtest",', '"model_card",', '"forecast",',
              '"data_frame",', '"validation_result",', '"correction_recipe",')))

    rs = (REPO / "apps/api/report_snapshot.py").read_text(encoding="utf-8")
    check("report_snapshot: DOCUMENT_CATALOG_VERSION pgv.document_catalog/2",
          'DOCUMENT_CATALOG_VERSION = "pgv.document_catalog/2"' in rs)
    check("report_snapshot: PRINT_DOCUMENT_KINDS V01/P01/P02",
          all(k in rs for k in (
              '"V01": ("scientific_visual"',
              '"P01": ("passport_print"',
              '"P02": ("passport_comparison"')))
    check("report_snapshot: D02 source_passport не тронут",
          '"D02": ("source_passport", "Паспорт источника", "upload")' in rs)

    jobs = (REPO / "apps/api/document_jobs.py").read_text(encoding="utf-8")
    check("document_jobs: DocumentPrintRevisionRecord",
          "class DocumentPrintRevisionRecord" in jobs)
    check("document_jobs: печатный контракт реестра (4 метода)",
          all(m in jobs for m in (
              "def register_print_revision", "def get_print_revision",
              "def find_print_revision_by_fingerprint", "def list_print_revisions")))
    check("document_jobs: ensure_print_document_revision + list_print_documents",
          "def ensure_print_document_revision" in jobs
          and "def list_print_documents" in jobs)

    # ── 6. Миграция 0016: файл ↔ каталог ↔ пины ──────────────────────
    sql_path = REPO / "apps/api/migrations/0016_pgv2_print_documents.sql"
    check("migration 0016: файл существует", sql_path.exists())
    if sql_path.exists():
        sql = " ".join(sql_path.read_text(encoding="utf-8").split())
        check("migration 0016: таблица document_print_revisions",
              "CREATE TABLE IF NOT EXISTS document_print_revisions" in sql)
        check("migration 0016: UNIQUE(document_id, version_no)",
              "UNIQUE (document_id, version_no)" in sql)
        check("migration 0016: UNIQUE(document_id, basis_fingerprint)",
              "UNIQUE (document_id, basis_fingerprint)" in sql)
        check("migration 0016: snapshot_id опционален (не NOT NULL)",
              "snapshot_id TEXT REFERENCES" in sql
              and "snapshot_id TEXT NOT NULL" not in sql)
    rr = (REPO / "apps/api/research_runs.py").read_text(encoding="utf-8")
    check("research_runs: MIGRATION_STATEMENTS_0016", "MIGRATION_STATEMENTS_0016" in rr)
    check("research_runs: файл в MIGRATION_FILES",
          '("0016_pgv2_print_documents.sql", MIGRATION_STATEMENTS_0016)' in rr)
    check("research_runs: 0016 в конкатенации", "+ MIGRATION_STATEMENTS_0016" in rr)

    # Фактические счётчики каталога (синхронно с честно обновлёнными пинами)
    sys.path.insert(0, str(REPO))
    from apps.api.research_runs import MIGRATION_FILES, MIGRATION_STATEMENTS

    check("каталог: 16 файлов", len(MIGRATION_FILES) == EXPECTED_MIGRATION_FILES,
          f"факт {len(MIGRATION_FILES)}")
    check("каталог: 96 statements",
          len(MIGRATION_STATEMENTS) == EXPECTED_MIGRATION_STATEMENTS,
          f"факт {len(MIGRATION_STATEMENTS)}")
    check("каталог: сумма групп == полный каталог",
          sum(len(s) for _, s in MIGRATION_FILES) == len(MIGRATION_STATEMENTS))

    # ── 7. Реестр PGV-00 не задет (пин 93) ───────────────────────────
    registry = json.loads(
        (REPO / "config/visual_registry.json").read_text(encoding="utf-8"))
    check("реестр PGV-00: 93 sites", len(registry["sites"]) == EXPECTED_SITES,
          f"факт {len(registry['sites'])}")
    check("реестр PGV-00: модулей 8",
          len({s["module_id"] for s in registry["sites"]}) == 8)

    # ── Отчёт ────────────────────────────────────────────────────────
    failed = [(n, d) for n, ok, d in CHECKS if not ok]
    total = len(CHECKS)
    for name, ok, detail in CHECKS:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f" -- {detail}" if detail and not ok else ""))
    print(f"\nPGV-02 doc-contract guard: {total - len(failed)}/{total} "
          + ("GREEN" if not failed else f"RED ({len(failed)} failed)"))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
