# scripts/prograudit6acert_pg_run.py
# Сертификация AUDIT-6A: запуск pytest-сюит на живом PostgreSQL (pgserver).
# DSN выставляется в CISSTAT_TEST_PG_DSN (затвор test_research_runs_postgres.py).
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    import pgserver

    d = tempfile.mkdtemp(prefix="cisstat6acert-pg-")
    srv = pgserver.get_server(d, cleanup_mode="delete")
    uri = srv.get_uri()
    print("PG URI:", uri)

    suite = sys.argv[1:] or ["tests/api/test_research_runs_postgres.py", "tests/api/test_progress_audit_6a.py"]
    env = dict(os.environ, CISSTAT_TEST_PG_DSN=uri)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *suite, "-q", "--no-header"],
        cwd=REPO,
        env=env,
    )
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
