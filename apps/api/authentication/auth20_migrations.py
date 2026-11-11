"""AUTH-20 explicit migration; previous version/checksum contracts preserved."""

import hashlib
from pathlib import Path

from .auth19_migrations import apply_migration as apply_auth19
from .auth19_migrations import check_schema as check_auth19
from .errors import AuthSchemaNotReady

VERSION = "0032_auth20_audit_ops"
SQL_TEXT = (
    (Path(__file__).resolve().parents[1] / "migrations" / f"{VERSION}.sql")
    .read_text(encoding="utf-8-sig")
    .replace("\r\n", "\n")
)
CHECKSUM = hashlib.sha256(SQL_TEXT.encode()).hexdigest()


def apply_migration(conn):
    with conn.transaction():
        # 0032 adds capture triggers on auth_billing_orders (0030), so the
        # chain guarantees the AUTH-17/AUTH-18 tables exist before 0031/0032.
        from apps.api.billing.subscription_migrations import apply_migration as apply_provider

        apply_provider(conn)
        apply_auth19(conn)
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
    from apps.api.billing.subscription_migrations import check_schema as check_provider

    check_provider(conn)
    check_auth19(conn)
    row = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
    ).fetchone()
    if not row or row["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    conn.execute(
        "SELECT entry_id,table_name,row_id,event,row_image,occurred_at FROM auth_ops_ledger LIMIT 0"
    )
    count = conn.execute(
        "SELECT count(*) AS n FROM pg_trigger WHERE tgname IN ("
        "'auth20_ledger_guard','auth20_capture_password','auth20_capture_sessions',"
        "'auth20_capture_api_keys','auth20_capture_worker_services',"
        "'auth20_capture_demo_grants','auth20_capture_demo_admissions',"
        "'auth20_capture_reservations','auth20_capture_billing_orders') "
        "AND tgenabled IN ('O','A')"
    ).fetchone()["n"]
    if count != 9:
        raise AuthSchemaNotReady()
