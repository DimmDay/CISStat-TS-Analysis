"""AUTH-17 explicit migration; previous version/checksum contracts are preserved."""

import hashlib
from pathlib import Path

from apps.api.authentication.demo_lifecycle_migrations import (
    apply_migration as apply_identity,
)
from apps.api.authentication.errors import AuthSchemaNotReady

VERSION = "0029_auth17_team"
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
    from apps.api.authentication.demo_lifecycle_migrations import (
        check_schema as check_sessions,
    )

    check_sessions(conn)
    row = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
    ).fetchone()
    if not row or row["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    for table in ("auth_team_commands", "auth_invitations", "auth_seat_requests"):
        conn.execute("SELECT 1 FROM " + table + " LIMIT 0")
    for table, name in (
        ("auth_team_commands", "auth17_commands_guard"),
        ("auth_invitations", "auth17_invitation_guard"),
        ("auth_seat_requests", "auth17_request_guard"),
    ):
        if not conn.execute(
            "SELECT 1 FROM pg_trigger WHERE tgname=%s AND tgrelid=%s::regclass AND tgenabled IN ('O','A')",
            (name, table),
        ).fetchone():
            raise AuthSchemaNotReady()
