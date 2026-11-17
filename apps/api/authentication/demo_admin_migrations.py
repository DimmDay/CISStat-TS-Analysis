"""Explicit additive admin notice schema; previous checksums are preserved."""

import hashlib
from pathlib import Path

from apps.api.authentication.errors import AuthSchemaNotReady
from .personal_demo_migrations import apply_migration as apply_previous
from .personal_demo_migrations import check_schema as check_previous

VERSION = "0037_demo_admin_notifications"
SQL_TEXT = (
    (Path(__file__).resolve().parents[1] / "migrations" / f"{VERSION}.sql")
    .read_text(encoding="utf-8-sig")
    .replace("\r\n", "\n")
)
CHECKSUM = hashlib.sha256(SQL_TEXT.encode()).hexdigest()


def apply_migration(conn):
    with conn.transaction():
        # Existing AUTH12/21 authority and all previous migrations first.
        apply_previous(conn)
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
    check_previous(conn)
    row = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
    ).fetchone()
    if not row or row["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    conn.execute("SELECT notification_id,status,claim_id FROM auth_demo_admin_notifications LIMIT 0")
    if not conn.execute(
        "SELECT 1 FROM pg_trigger WHERE tgname='demo_admin_notice_guard' AND tgrelid='auth_demo_admin_notifications'::regclass AND tgenabled IN ('O','A')"
    ).fetchone():
        raise AuthSchemaNotReady()
