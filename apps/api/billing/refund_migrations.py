"""AUTH-23 explicit migration; previous version/checksum contracts preserved."""

import hashlib
from pathlib import Path

from apps.api.authentication.errors import AuthSchemaNotReady
from apps.api.billing.topup_migrations import (
    apply_migration as apply_topup,
)
from apps.api.billing.topup_migrations import check_schema as check_topup

VERSION = "0035_auth23_refunds"
SQL_TEXT = (
    (Path(__file__).resolve().parents[1] / "migrations" / f"{VERSION}.sql")
    .read_text(encoding="utf-8-sig")
    .replace("\r\n", "\n")
)
CHECKSUM = hashlib.sha256(SQL_TEXT.encode()).hexdigest()


def apply_migration(conn):
    with conn.transaction():
        # 0035 refunds AUTH-22 orders into AUTH-21 wallet buckets; the chain
        # guarantees 0019…0034 before any refund table exists.
        apply_topup(conn)
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
    check_topup(conn)
    row = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
    ).fetchone()
    if not row or row["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    columns = {
        "auth_refund_orders": (
            "refund_id,order_id,account_id,lot_id,owner_id,units,amount_minor,"
            "currency,terms_version,window_days,state,provider_refund_id,"
            "first_attempt_at,next_attempt_at,lease_until,fence,attempts,"
            "created_at,decided_at"
        ),
        "auth_disputes": (
            "dispute_id,order_id,account_id,lot_id,payment_id,spent_units,"
            "disputed_units,amount_minor,currency,wallet_was_locked,state,"
            "opened_reason,resolution_reason,created_at,resolved_at"
        ),
    }
    for table, names in columns.items():
        conn.execute("SELECT " + names + " FROM " + table + " LIMIT 0")
    count = conn.execute(
        "SELECT count(*) AS n FROM pg_trigger WHERE tgname IN ("
        "'auth23_refund_guard','auth23_dispute_guard') "
        "AND tgrelid IN ('auth_refund_orders'::regclass,'auth_disputes'::regclass) "
        "AND tgenabled IN ('O','A')"
    ).fetchone()["n"]
    if count != 2:
        raise AuthSchemaNotReady()
