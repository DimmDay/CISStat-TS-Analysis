"""AUTH-04 explicit migration; AUTH-02's version/checksum contract is preserved."""

import hashlib
from pathlib import Path
from .errors import AuthSchemaNotReady
from .migrations import apply_migration as apply_identity

VERSION = "0020_auth04_sessions"
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
    from .migrations import VERSION as IDENTITY_VERSION, CHECKSUM as IDENTITY_CHECKSUM

    identity = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s",
        (IDENTITY_VERSION,),
    ).fetchone()
    if not identity or identity["checksum"] != IDENTITY_CHECKSUM:
        raise AuthSchemaNotReady()
    row = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
    ).fetchone()
    if not row or row["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    for table in (
        "auth_password_credentials",
        "auth_subject_security",
        "auth_sessions",
        "auth_login_limits",
        "auth_audit_outbox",
    ):
        conn.execute("SELECT 1 FROM " + table + " LIMIT 0")
