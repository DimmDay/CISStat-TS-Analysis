"""AUTH-19 explicit migration; previous version/checksum contracts preserved."""

import hashlib
from pathlib import Path

from .demo_lifecycle_migrations import apply_migration as apply_lifecycle
from .errors import AuthSchemaNotReady

VERSION = "0031_auth19_email_oidc"
SQL_TEXT = (
    (Path(__file__).resolve().parents[1] / "migrations" / f"{VERSION}.sql")
    .read_text(encoding="utf-8-sig")
    .replace("\r\n", "\n")
)
CHECKSUM = hashlib.sha256(SQL_TEXT.encode()).hexdigest()


def apply_migration(conn):
    with conn.transaction():
        apply_lifecycle(conn)
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
    from .demo_lifecycle_migrations import check_schema as check_demo

    check_demo(conn)
    row = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
    ).fetchone()
    if not row or row["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    for table, columns in {
        "auth_email_challenges": "challenge_id,purpose,email,token_hash,code_hash,subject_id,origin,issued_at,expires_at,attempts,delivered_at,delivery_code,consumed_at",
        "auth_login_states": "state_id,purpose,state_hash,nonce,pkce_verifier,subject_id,origin,issued_at,expires_at,consumed_at",
        "auth_sessions": "credential_id,credential_version",
    }.items():
        conn.execute("SELECT " + columns + " FROM " + table + " LIMIT 0")
    count = conn.execute(
        "SELECT count(*) AS n FROM pg_trigger WHERE tgname IN ('auth19_email_challenge_guard','auth19_login_state_guard') AND tgenabled IN ('O','A') AND tgrelid IN ('auth_email_challenges'::regclass,'auth_login_states'::regclass)"
    ).fetchone()["n"]
    if count != 2:
        raise AuthSchemaNotReady()
