"""AUTH-22 explicit migration; previous version/checksum contracts preserved."""

import hashlib
from pathlib import Path

from apps.api.billing.wallet_migrations import (
    apply_migration as apply_wallet,
)
from apps.api.billing.wallet_migrations import check_schema as check_wallet
from apps.api.authentication.errors import AuthSchemaNotReady

VERSION = "0034_auth22_topups"
SQL_TEXT = (
    (Path(__file__).resolve().parents[1] / "migrations" / f"{VERSION}.sql")
    .read_text(encoding="utf-8-sig")
    .replace("\r\n", "\n")
)
CHECKSUM = hashlib.sha256(SQL_TEXT.encode()).hexdigest()


def apply_migration(conn):
    with conn.transaction():
        # 0034 credits into AUTH-21 wallets; the chain guarantees 0019…0033.
        apply_wallet(conn)
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
    check_wallet(conn)
    row = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
    ).fetchone()
    if not row or row["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    columns = {
        "auth_topup_packages": (
            "package_id,title,units,price_minor,currency,price_version,"
            "terms_version,enabled,created_at"
        ),
        "auth_topup_quotes": (
            "quote_id,account_id,owner_id,package_id,snapshot,digest,"
            "created_at,expires_at"
        ),
        "auth_topup_orders": (
            "order_id,quote_id,account_id,units,state,payment_id,candidate_id,"
            "checkout_url,first_attempt_at,next_attempt_at,lease_until,"
            "last_observed_at,fence,attempts,created_at,paid_at,credited_at"
        ),
        "auth_topup_inbox": "order_id,payment_id,event,received_at",
    }
    for table, names in columns.items():
        conn.execute("SELECT " + names + " FROM " + table + " LIMIT 0")
    count = conn.execute(
        "SELECT count(*) AS n FROM pg_trigger WHERE tgname IN ("
        "'auth22_package_guard','auth22_quote_guard','auth22_order_guard',"
        "'auth22_inbox_guard') "
        "AND tgrelid IN ('auth_topup_packages'::regclass,"
        "'auth_topup_quotes'::regclass,'auth_topup_orders'::regclass,"
        "'auth_topup_inbox'::regclass) AND tgenabled IN ('O','A')"
    ).fetchone()["n"]
    if count != 4:
        raise AuthSchemaNotReady()
