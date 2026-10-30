#!/usr/bin/env python3
# scripts/pgv09/verify_local.py
"""PGV-09 (Jobs/PNG renderer integration) -- локальная верификация
поставки. Прогоняет адресные и затронутые наборы, проверяет
миграцию/паритет и пишет честные протоколы (реальные exit codes) в
scripts/pgv09/protocols/.

Без commit/push (AGENTS.md). Запуск из корня репозитория:
    python3 scripts/pgv09/verify_local.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOCOLS = Path(__file__).resolve().parent / "protocols"

PGV09_SUITE = [
    "tests/api/test_pgv09_jobs_renderer_integration.py",
]
AFFECTED_SUITES = [
    "tests/api/test_doclog4_document_delivery.py",
    "tests/api/test_doclog5_formats_worker.py",
    "tests/api/test_doclog9_profiles.py",
    "tests/api/test_doclog3_telemetry_audit.py",
    "tests/api/test_doclog6_approvals_archive.py",
    "tests/api/test_doclog7_logs_support.py",
    "tests/api/test_doclog8_monitoring.py",
    "tests/api/test_pgv02_durable_inputs.py",
    "tests/api/test_pgv03_producer_adapters.py",
    "tests/api/test_research_runs.py",
]

MIGRATION_SQL = REPO_ROOT / "apps/api/migrations/0017_pgv9_print_renditions.sql"
NEW_MODULES = [
    REPO_ROOT / "apps/api/png_renderer_client.py",
    REPO_ROOT / "apps/api/print_render_payload.py",
]


def _run(name: str, argv: list[str], *, cwd: Path = REPO_ROOT) -> dict:
    started = time.monotonic()
    proc = subprocess.run(
        argv, cwd=str(cwd), capture_output=True, text=True, timeout=1800
    )
    duration = round(time.monotonic() - started, 3)
    (PROTOCOLS / f"{name}.txt").write_text(
        proc.stdout[-20000:] + ("\n[stderr]\n" + proc.stderr[-8000:] if proc.stderr else ""),
        encoding="utf-8",
    )
    return {
        "name": name,
        "argv": argv,
        "exit_code": proc.returncode,
        "duration_s": duration,
    }


def check_migration_parity() -> dict:
    """Паритет MIGRATION_STATEMENTS_0017 и SQL-файла (PROGR-5.1) +
    аддитивные формы (никаких DROP TABLE/COLUMN)."""
    sys.path.insert(0, str(REPO_ROOT))
    from apps.api.research_runs import (
        MIGRATION_FILES,
        MIGRATION_STATEMENTS,
        MIGRATION_STATEMENTS_0017,
    )

    sql = MIGRATION_SQL.read_text("utf-8")
    joined = "\n".join(MIGRATION_STATEMENTS_0017)
    missing = []
    for line in sql.splitlines():
        stripped = line.strip().rstrip(";")
        if not stripped or stripped.startswith("--"):
            continue
        if stripped not in joined:
            missing.append(stripped)
    for statement in MIGRATION_STATEMENTS_0017:
        compact = " ".join(statement.split())
        if compact not in " ".join(sql.split()):
            missing.append("statement: " + statement[:80])
    checks = {
        "file_lines_in_catalog": not missing,
        "missing": missing,
        "catalog_files": len(MIGRATION_FILES),
        "catalog_statements": len(MIGRATION_STATEMENTS),
        "last_file": MIGRATION_FILES[-1][0],
        "additive_only": "DROP TABLE" not in sql and "DROP COLUMN" not in sql,
        "partial_unique_index": "uq_document_renditions_print" in sql,
        "fk_do_blocks": sum(
            1 for line in sql.splitlines() if line.strip().startswith("DO $$")
        ) == 2,
    }
    return checks


def check_no_git_writes() -> dict:
    """AGENTS.md: commit/push запрещены -- локальная история не уходит
    с базы 962ccda (git log -1)."""
    proc = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    head = proc.stdout.strip()
    return {"head": head, "is_base_962ccda": head.startswith("962ccda")}


def main() -> int:
    PROTOCOLS.mkdir(parents=True, exist_ok=True)
    results: dict = {"task": "PGV-09", "base": "962ccda", "steps": []}

    # 0. Компиляция новых/изменённых модулей (синтаксический гейт).
    compile_argv = [
        sys.executable, "-m", "py_compile",
        *[str(p) for p in NEW_MODULES],
        str(REPO_ROOT / "apps/api/document_jobs.py"),
        str(REPO_ROOT / "apps/api/document_render_worker.py"),
        str(REPO_ROOT / "apps/api/research_runs.py"),
        str(REPO_ROOT / "apps/api/routers/documentation.py"),
        str(REPO_ROOT / "tests/api/test_pgv09_jobs_renderer_integration.py"),
    ]
    results["steps"].append(_run("compile", compile_argv))

    # 1. Адресная suite PGV-09 (RED->GREEN оракулы).
    results["steps"].append(
        _run("pgv09_suite", [sys.executable, "-m", "pytest", *PGV09_SUITE, "-q"])
    )

    # 2. Затронутые наборы (регресс документов/артефактов/миграций).
    results["steps"].append(
        _run("affected_suites", [sys.executable, "-m", "pytest", *AFFECTED_SUITES, "-q"])
    )

    # 3. Миграция/паритет.
    migration = check_migration_parity()
    (PROTOCOLS / "migration_parity.json").write_text(
        json.dumps(migration, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    results["migration_parity"] = migration

    # 4. AGENTS.md: без commit/push.
    git_state = check_no_git_writes()
    (PROTOCOLS / "git_state.json").write_text(
        json.dumps(git_state, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    results["git_state"] = git_state

    all_ok = (
        all(step["exit_code"] == 0 for step in results["steps"])
        and migration["file_lines_in_catalog"]
        and migration["additive_only"]
        and migration["partial_unique_index"]
        and migration["fk_do_blocks"]
        and git_state["is_base_962ccda"]
    )
    results["verdict"] = "PASS" if all_ok else "FAIL"
    (PROTOCOLS / "summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps({
        "verdict": results["verdict"],
        "steps": [
            {"name": s["name"], "exit_code": s["exit_code"], "duration_s": s["duration_s"]}
            for s in results["steps"]
        ],
        "migration_files": migration["catalog_files"],
        "migration_statements": migration["catalog_statements"],
    }, ensure_ascii=False, indent=1))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
