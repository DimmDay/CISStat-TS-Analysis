"""AUTH-18 explicit migration; previous version/checksum contracts are preserved."""

import hashlib
from pathlib import Path

from apps.api.accounts.team_migrations import (
    apply_migration as apply_identity,
)
from apps.api.authentication.errors import AuthSchemaNotReady

VERSION = "0030_auth18_provider"
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
    from apps.api.accounts.team_migrations import (
        check_schema as check_sessions,
    )

    check_sessions(conn)
    row = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
    ).fetchone()
    if not row or row["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    for table in (
        "auth_billing_cycles",
        "auth_billing_quotes",
        "auth_billing_orders",
        "auth_provider_inbox",
        "auth_billing_adjustments",
    ):
        conn.execute("SELECT 1 FROM " + table + " LIMIT 0")
    for table, name in (
        ("auth_billing_quotes", "auth18_quote_guard"),
        ("auth_billing_cycles", "auth18_cycle_guard"),
        ("auth_provider_inbox", "auth18_inbox_guard"),
        ("auth_billing_orders", "auth18_order_guard"),
        ("auth_billing_adjustments", "auth18_adjustment_guard"),
    ):
        if not conn.execute(
            "SELECT 1 FROM pg_trigger WHERE tgname=%s AND tgrelid=%s::regclass AND tgenabled IN ('O','A')",
            (name, table),
        ).fetchone():
            raise AuthSchemaNotReady()
