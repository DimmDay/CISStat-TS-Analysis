"""AUTH-15 explicit migration; previous version/checksum contracts are preserved."""

import hashlib
from pathlib import Path

from apps.api.workers.migrations import apply_migration as apply_identity
from apps.api.authentication.errors import AuthSchemaNotReady

VERSION = "0027_auth15_demo"
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
    from apps.api.workers.migrations import (
        check_schema as check_sessions,
    )

    check_sessions(conn)
    row = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
    ).fetchone()
    if not row or row["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    for table, columns in {
        "auth_demo_campaigns": "campaign_id,alias,status,policy,policy_version,password_hash,credential_version,issued_grants,sponsor_id,activated_at",
        "auth_demo_grants": "grant_id,campaign_id,subject_id,account_id,resume_hash,issued_at,expires_at,status",
        "auth_sessions": "demo_grant_id",
    }.items():
        conn.execute("SELECT " + columns + " FROM " + table + " LIMIT 0")
    count = conn.execute(
        "SELECT count(*) AS n FROM pg_trigger WHERE tgname IN ('auth15_grant_guard','auth15_campaign_guard') AND tgenabled IN ('O','A') AND tgrelid IN ('auth_demo_campaigns'::regclass,'auth_demo_grants'::regclass)"
    ).fetchone()["n"]
    if count != 2:
        raise AuthSchemaNotReady()
