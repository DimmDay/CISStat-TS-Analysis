"""The SQL file is the only DDL source; no scientific import/hidden commit."""

import hashlib
from pathlib import Path
from .errors import AuthSchemaNotReady

VERSION = "0019_auth02_identity_accounts"
SQL_PATH = Path(__file__).resolve().parents[1] / "migrations" / f"{VERSION}.sql"
SQL_TEXT = SQL_PATH.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
CHECKSUM = hashlib.sha256(SQL_TEXT.encode("utf-8")).hexdigest()


def apply_migration(conn):
    """Atomic DDL + ledger; nested caller transaction may still roll it all back."""
    with conn.transaction():
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended('cisstat.auth:'||current_schema(),0))"
        )
        conn.execute("""CREATE TABLE IF NOT EXISTS auth_schema_versions (
            version TEXT PRIMARY KEY, checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
        row = conn.execute(
            "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
        ).fetchone()
        if row:
            value = row["checksum"] if isinstance(row, dict) else row[0]
            if value != CHECKSUM:
                raise AuthSchemaNotReady()
            return False
        conn.execute(SQL_TEXT, prepare=False)
        conn.execute(
            "INSERT INTO auth_schema_versions(version,checksum) VALUES (%s,%s)",
            (VERSION, CHECKSUM),
        )
        return True
