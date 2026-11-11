"""AUTH-21 explicit migration; previous version/checksum contracts preserved."""

import hashlib
from pathlib import Path

from apps.api.authentication.auth20_migrations import (
    apply_migration as apply_auth20,
)
from apps.api.authentication.auth20_migrations import check_schema as check_auth20
from apps.api.authentication.errors import AuthSchemaNotReady

VERSION = "0033_auth21_wallet"
SQL_TEXT = (
    (Path(__file__).resolve().parents[1] / "migrations" / f"{VERSION}.sql")
    .read_text(encoding="utf-8-sig")
    .replace("\r\n", "\n")
)
CHECKSUM = hashlib.sha256(SQL_TEXT.encode()).hexdigest()


def apply_migration(conn):
    with conn.transaction():
        # 0033 references auth_billing_cycles (0030) and auth_reservations
        # (0025); the chain guarantees every parent table before 0033.
        apply_auth20(conn)
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
    check_auth20(conn)
    row = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
    ).fetchone()
    if not row or row["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    columns = {
        "auth_wallets": "wallet_id,account_id,status,locked_reason,version,created_at",
        "auth_wallet_lots": (
            "lot_id,wallet_id,account_id,source,issued,available,reserved,spent,"
            "expired,refund_pending,refunded,expires_at,origin_cycle,origin_order,"
            "origin_ref,version,created_at"
        ),
        "auth_wallet_postings": (
            "posting_id,lot_id,reservation_id,event,issued_delta,available_delta,"
            "reserved_delta,spent_delta,expired_delta,refund_pending_delta,"
            "refunded_delta,created_at"
        ),
        "auth_reservation_lot_allocations": "reservation_id,lot_id,units",
    }
    for table, names in columns.items():
        conn.execute("SELECT " + names + " FROM " + table + " LIMIT 0")
    count = conn.execute(
        "SELECT count(*) AS n FROM pg_trigger WHERE tgname IN ("
        "'auth21_wallet_guard','auth21_lot_guard','auth21_posting_guard',"
        "'auth21_posting_projection','auth21_lot_allocation_guard') "
        "AND tgrelid IN ('auth_wallets'::regclass,'auth_wallet_lots'::regclass,"
        "'auth_wallet_postings'::regclass,'auth_reservation_lot_allocations'::regclass) "
        "AND tgenabled IN ('O','A')"
    ).fetchone()["n"]
    if count != 5:
        raise AuthSchemaNotReady()
