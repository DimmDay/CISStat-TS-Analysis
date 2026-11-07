"""AUTH-10 explicit migration; previous version/checksum contracts are preserved."""

import hashlib
from pathlib import Path

from .errors import AuthSchemaNotReady
from .mfa_migrations import apply_migration as apply_identity

VERSION = "0024_auth10_api_keys"
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
    from .mfa_migrations import check_schema as check_sessions

    check_sessions(conn)
    row = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s",
        (VERSION,),
    ).fetchone()
    if not row or row["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    conn.execute("SELECT key_id FROM auth_api_keys LIMIT 0")
    row = conn.execute("""SELECT count(*) AS n FROM pg_trigger WHERE NOT tgisinternal
        AND tgname IN ('auth10_key_guard','auth10_identity_keys','auth10_account_keys','auth10_membership_keys')
        AND tgrelid IN ('auth_api_keys'::regclass,'auth_identities'::regclass,'auth_accounts'::regclass,'auth_memberships'::regclass)
        AND tgenabled IN ('O','A')""").fetchone()
    if row["n"] != 4:
        raise AuthSchemaNotReady()
