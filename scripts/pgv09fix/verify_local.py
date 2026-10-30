#!/usr/bin/env python3
# scripts/pgv09fix/verify_local.py
"""PGV-09-FIX (исправления F-P9C1/N-P9C2) -- локальная верификация.
Прогоняет адресную suite исправления, авторский корпус, корпус
сертификатора, затронутый регресс, проверяет состояние миграционного
каталога (0018, паритет файла и каталога) и пишет честные протоколы
(реальные exit codes) в scripts/pgv09fix/protocols/.

Без commit/push (AGENTS.md). Запуск из корня репозитория:
    python3 scripts/pgv09fix/verify_local.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOCOLS = Path(__file__).resolve().parent / "protocols"

FIX_SUITE = [
    "tests/api/test_pgv09fix_write_path.py",
]
AFFECTED_SUITES = [
    "tests/api/test_pgv09_jobs_renderer_integration.py",
    "tests/api/test_p9cert_oracles.py",
    "tests/api/test_doclog3_telemetry_audit.py",
    "tests/api/test_doclog4_document_delivery.py",
    "tests/api/test_doclog5_formats_worker.py",
    "tests/api/test_doclog6_approvals_archive.py",
    "tests/api/test_doclog7_logs_support.py",
    "tests/api/test_doclog8_monitoring.py",
    "tests/api/test_doclog9_profiles.py",
    "tests/api/test_pgv02_durable_inputs.py",
    "tests/api/test_pgv03_producer_adapters.py",
    "tests/api/test_research_runs.py",
    "tests/api/test_doclog_recheck_fix.py",
]

MIGRATION_0018_SQL = (
    REPO_ROOT / "apps/api/migrations/0018_pgv9fix_print_rendition_keys.sql"
)
FIX_MODULES = [
    REPO_ROOT / "apps/api/document_jobs.py",
    REPO_ROOT / "apps/api/png_renderer_client.py",
    REPO_ROOT / "apps/api/research_runs.py",
]


def _run(label: str, args: list[str]) -> dict:
    started = time.time()
    proc = subprocess.run(
        args, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=1800
    )
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-4:])
    record = {
        "step": label,
        "cmd": " ".join(args),
        "exit_code": proc.returncode,
        "seconds": round(time.time() - started, 1),
        "tail": tail,
    }
    print(
        f"[{label}] exit={proc.returncode} ({record['seconds']}s)\n{tail}\n"
    )
    return record


def main() -> int:
    PROTOCOLS.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []

    # 0. Состояние: файлы исправления на месте, миграция 0018 существует.
    missing = [str(p) for p in FIX_MODULES + [MIGRATION_0018_SQL] if not p.is_file()]
    state = {
        "step": "state",
        "exit_code": 0 if not missing else 1,
        "missing_files": missing,
        "git_head": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        ).stdout.strip(),
        "dirty_product_files": [
            line.strip()
            for line in subprocess.run(
                ["git", "status", "--short"],
                cwd=str(REPO_ROOT), capture_output=True, text=True,
            ).stdout.splitlines()
        ],
    }
    records.append(state)
    print(json.dumps(state, ensure_ascii=False, indent=1))

    # 1. Адресная suite исправления (20 оракулов F-P9C1/N-P9C2).
    records.append(
        _run("fix_suite", [sys.executable, "-m", "pytest", *FIX_SUITE, "-q"])
    )

    # 2. Затронутый регресс (авторский корпус + сертификатор + doclog/pgv).
    records.append(
        _run(
            "affected_regression",
            [sys.executable, "-m", "pytest", *AFFECTED_SUITES, "-q"],
        )
    )

    # 3. Паритет 0018: каждое утверждение каталога в файле-дубле.
    sql = MIGRATION_0018_SQL.read_text("utf-8")
    sys.path.insert(0, str(REPO_ROOT))
    from apps.api.research_runs import MIGRATION_STATEMENTS_0018

    parity_ok = all(
        " ".join(s.split()) in " ".join(sql.split())
        for s in MIGRATION_STATEMENTS_0018
    )
    records.append(
        {
            "step": "migration_0018_parity",
            "exit_code": 0 if parity_ok else 1,
            "statements": len(MIGRATION_STATEMENTS_0018),
        }
    )
    print(f"[migration_0018_parity] exit={0 if parity_ok else 1}")

    out = PROTOCOLS / "verify_local.json"
    out.write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    critical = [r for r in records if r.get("exit_code") not in (0, 5)]
    verdict = "PASS" if not missing and not critical else "FAIL"
    print(f"VERDICT: {verdict} (protocol: {out})")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
