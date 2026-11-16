"""PERSONAL-DEMO explicit migration; previous version/checksum contracts preserved."""

import hashlib
from pathlib import Path

from apps.api.authentication.errors import AuthSchemaNotReady
from apps.api.billing.refund_migrations import (
    apply_migration as apply_previous,
)
from apps.api.billing.refund_migrations import check_schema as check_previous

VERSION = "0036_personal_demo"
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
        from apps.api.billing.coordinator import audit

        audit(
            conn,
            "auth_budget_changed",
            "00000000-0000-4000-8000-000000000136",
            details={"command": "personal_demo_pool_provisioned", "max_trials": 100},
        )
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
    for table in ("auth_personal_demo_pool", "auth_personal_trials"):
        conn.execute("SELECT 1 FROM " + table + " LIMIT 0")
    for table, name in (
        ("auth_personal_demo_pool", "personal_pool_guard"),
        ("auth_personal_trials", "personal_trials_guard"),
    ):
        if not conn.execute(
            "SELECT 1 FROM pg_trigger WHERE tgname=%s AND tgrelid=%s::regclass AND tgenabled IN ('O','A')",
            (name, table),
        ).fetchone():
            raise AuthSchemaNotReady()
