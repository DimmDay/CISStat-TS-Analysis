"""AUTH-05 explicit migration; previous version/checksum contracts are preserved."""

import hashlib
from pathlib import Path

from .errors import AuthSchemaNotReady
from .session_migrations import apply_migration as apply_identity

VERSION = "0021_auth05_mfa"
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
    from .session_migrations import check_schema as check_sessions

    check_sessions(conn)
    row = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
    ).fetchone()
    if not row or row["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    for table in (
        "auth_mfa_factors",
        "auth_session_mfa",
        "auth_challenges",
        "auth_recovery_codes",
        "auth_bootstrap",
    ):
        conn.execute("SELECT 1 FROM " + table + " LIMIT 0")
