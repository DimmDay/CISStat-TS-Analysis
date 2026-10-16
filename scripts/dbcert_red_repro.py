#!/usr/bin/env python3
"""
СЕРТИФИКАЦИЯ UPLOAD-DB-3 — RED-воспроизведение (оракул сертификации).

Два независимых RED-доказательства на коде ДО фазы A (68fd65d):
1. Все новые файлы фазы A отсутствуют → collection = честный RED
   (проверяется git cat-file, вне Python).
2. D1-дефект живьём: legacy file_loader@68fd65d исполняет контрольный
   запрос СЫРОЙ СТРОКОЙ ("SELECT 1") — под SQLAlchemy>=2.0 это
   StatementError. Legacy-файл извлекается в изолированную песочницу
   (git show), рабочее дерево НЕ трогается.

Протокол: scripts/dbcert_red_repro.txt
"""
import os
import subprocess
import sys
import tempfile
import traceback

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BASE = "68fd65d"

lines = []


def log(msg):
    print(msg)
    lines.append(msg)


def step2_d1_live_probe():
    log("")
    log("=== RED-2: D1-дефект живьём (legacy file_loader@68fd65d, sqlalchemy>=2.0) ===")
    sandbox = tempfile.mkdtemp(prefix="dbcert_red_")
    legacy = os.path.join(sandbox, "legacy_file_loader.py")
    raw = subprocess.run(
        ["git", "-C", REPO, "show", f"{BASE}:app/data/file_loader.py"],
        capture_output=True, text=True, check=True,
    ).stdout
    # Изоляция: убираем относительный импорт реестра (его тогда не было)
    raw = raw.replace(
        "from app.data import db_connectors",
        "db_connectors = None  # (68fd65d: реестра ещё нет — изоляция песочницы)",
    )
    with open(legacy, "w") as fh:
        fh.write(raw)
    # Прячем текущее app/ из пути — legacy-модуль должен импортироваться сам
    script = os.path.join(sandbox, "probe_d1.py")
    with open(script, "w") as fh:
        fh.write(
            "import sys, os, logging\n"
            f"sys.path.insert(0, {sandbox!r})\n"
            "os.chdir(sys.path[0])\n"
            "logging.disable(logging.CRITICAL)\n"
            "import legacy_file_loader as lf\n"
            "from sqlalchemy import create_engine\n"
            "# Legacy PG-ветка (68fd65d) исполняет conn.execute(\"SELECT 1\") СЫРОЙ СТРОКОЙ.\n"
            "# Демонстрация D1 живьём: подставляем РЕАЛЬНЫЙ sqlite-движок (драйвер всегда есть),\n"
            "# строка контрольного запроса остаётся байт-в-байт legacy-строкой 68fd65d.\n"
            "lf.create_engine = lambda *a, **k: create_engine('sqlite:///:memory:')\n"
            "try:\n"
            "    lf.init_db_connection('PostgreSQL', 'ignored', 5432, 'u', 'p', 'd')\n"
            "    print('PROBE-RESULT: connected (unexpected)')\n"
            "except Exception as exc:\n"
            "    print('PROBE-RESULT: %s: %s' % (type(exc).__name__, str(exc)[:120]))\n"
            "    cause = exc.__cause__ or exc.__context__\n"
            "    while cause is not None:\n"
            "        print('  CAUSE: %s: %s' % (type(cause).__name__, str(cause)[:200]))\n"
            "        cause = cause.__cause__\n"
        )
    env = dict(os.environ, DATABASE_URL="sqlite://")
    proc = subprocess.run(
        [sys.executable, script], capture_output=True, text=True, env=env
    )
    for ln in (proc.stdout + proc.stderr).strip().splitlines():
        log("  " + ln)
    ok = ("ObjectNotExecutableError" in proc.stdout
          or "StatementError" in proc.stdout
          or "Textual SQL expression" in proc.stdout
          or "textual sql" in proc.stdout.lower())
    log("  Побочно (подтверждено чтением legacy-кода): 'SQLite'/'DuckDB' на 68fd65d —")
    log("  ветка else → logger.warning('Unsupported database type') → return None:")
    log("  embedded-СУБД legacy НЕ поддерживались вовсе (RED-композиция полная).")
    log(f"  RED-2 VERDICT: {'CONFIRMED (D1 жив: сырая строка отклонена SQLAlchemy 2.0)' if ok else 'NOT REPRODUCED'}")
    return ok


def main():
    log("СЕРТИФИКАЦИЯ UPLOAD-DB-3 (2026-10-16) — RED-воспроизведение на коде ДО фазы A")
    log(f"База RED: {BASE} (до коммита фазы A 88a5459); HEAD аудита: 6cff336")
    log("")
    log("=== RED-1: файлы фазы A отсутствуют на 68fd65d (collection RED) ===")
    files = [
        "app/data/db_connectors.py",
        "app/data/db_guard.py",
        "tests/unit/test_db_embedded.py",
        "tests/unit/test_db_connectors.py",
        "tests/unit/test_db_guard.py",
    ]
    all_absent = True
    for f in files:
        r = subprocess.run(["git", "-C", REPO, "cat-file", "-e", f"{BASE}:{f}"])
        absent = r.returncode != 0
        all_absent &= absent
        log(f"  {'ABSENT' if absent else 'EXISTS?!'} at {BASE}: {f}")
    log(f"  RED-1 VERDICT: {'CONFIRMED (все 5 файлов новые — collection падает: честный RED)' if all_absent else 'FAILED'}")

    ok2 = step2_d1_live_probe()

    log("")
    log(f"ИТОГ RED: {'CONFIRMED' if (all_absent and ok2) else 'PARTIAL/FAILED'} "
        "(RED-1 collection + RED-2 живой D1-дефект на реальном соединении)")
    with open(os.path.join(REPO, "scripts", "dbcert_red_repro.txt"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return 0 if (all_absent and ok2) else 1


if __name__ == "__main__":
    sys.exit(main())
