"""AUTH-16 explicit migration; previous version/checksum contracts are preserved."""

import hashlib
from pathlib import Path

from apps.api.authentication.demo_migrations import apply_migration as apply_identity
from apps.api.authentication.errors import AuthSchemaNotReady

VERSION = "0028_auth16_demo_lifecycle"
SQL_TEXT = (
    (Path(__file__).resolve().parents[1] / "migrations" / f"{VERSION}.sql")
    .read_text(encoding="utf-8-sig")
    .replace("\r\n", "\n")
)
CHECKSUM = hashlib.sha256(SQL_TEXT.encode()).hexdigest()


def apply_migration(conn):
    with conn.transaction():
        apply_identity(conn)
        row = conn.execute(
            "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
        ).fetchone()
        if row:
            if (row["checksum"] if isinstance(row, dict) else row[0]) != CHECKSUM:
                raise AuthSchemaNotReady()
            return False
        conn.execute(SQL_TEXT, prepare=False)
        conn.execute(
            "INSERT INTO auth_schema_versions(version,checksum) VALUES (%s,%s)",
            (VERSION, CHECKSUM),
        )
        return True


def check_schema(conn):
    from apps.api.authentication.demo_migrations import (
        check_schema as check_sessions,
    )

    check_sessions(conn)
    row = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
    ).fetchone()
    if not row or row["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    for table in (
        "auth_demo_admissions",
        "auth_demo_calls",
        "auth_demo_http_usage",
        "auth_demo_cleanup",
        "auth_demo_gc",
        "auth_demo_sweep_attempts",
    ):
        conn.execute("SELECT 1 FROM " + table + " LIMIT 0")
    if not conn.execute(
        "SELECT 1 FROM pg_trigger WHERE tgname='auth16_admission_guard' AND tgrelid='auth_demo_admissions'::regclass AND tgenabled IN ('O','A')"
    ).fetchone():
        raise AuthSchemaNotReady()
