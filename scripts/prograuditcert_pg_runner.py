"""Start an owned disposable PostgreSQL; never accept an external DSN.

Usage: python scripts/prograuditcert_pg_runner.py [pytest arguments]
Existing audit suites can use CISSTAT_TEST_PG_DSN from this runner too.
"""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise SystemExit("Local PostgreSQL unavailable: run this runner as a non-root user with access to the workspace. It does not create OS accounts or alter ancestor permissions.")
    import pgserver
    import psycopg
    import pytest
    from apps.api.research_runs import run_migrations
    os.environ.pop("DATABASE_URL", None)
    os.environ.pop("REDIS_URL", None)
    with tempfile.TemporaryDirectory(prefix="auditcert-pg-", dir=ROOT.parent) as directory:
        server = pgserver.get_server(Path(directory) / "database", cleanup_mode="delete")
        try:
            dsn = server.get_uri()
            os.environ["CISSTAT_CERT_LOCAL_PG_DSN"] = dsn
            os.environ["CISSTAT_TEST_PG_DSN"] = dsn
            with psycopg.connect(dsn) as conn:
                run_migrations(conn)
            # Do not print credentials/DSN: protocol records the backend/version.
            with psycopg.connect(dsn) as conn:
                version = conn.execute("SHOW server_version").fetchone()[0]
            print(f"Owned temporary PostgreSQL {version}; migrations applied", flush=True)
            return pytest.main(sys.argv[1:] or ["tests/api/test_progress_audit_cert_store.py", "-q"])
        finally:
            # Stop the owned server before deleting its data directory.
            server.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
