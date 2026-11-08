"""AUTH-12 explicit migration; previous version/checksum contracts are preserved."""

import hashlib
from pathlib import Path

from apps.api.authentication.api_key_migrations import apply_migration as apply_identity
from apps.api.authentication.errors import AuthSchemaNotReady

VERSION = "0025_auth12_reservations"
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
    from apps.api.authentication.api_key_migrations import (
        check_schema as check_sessions,
    )

    check_sessions(conn)
    row = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
    ).fetchone()
    if not row or row["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    columns = {
        "auth_budget_scopes": "scope_id,kind,parent_id,account_id,status,starts_at,ends_at,version",
        "auth_resource_budgets": "budget_id,scope_id,metric,period,limit_units,reserved,spent,version",
        "auth_reservations": "reservation_id,account_id,subject_id,tenant_id,canonical_operation,key_digest,payload_digest,admission,quote_version,held_cu,actual_cu,state,version,created_at,deadline,lease_until,result_ref",
        "auth_reservation_allocations": "reservation_id,budget_id,units,metric",
        "auth_usage_postings": "reservation_id,event_no,budget_id,available_delta,reserved_delta,spent_delta",
        "auth_analysis_claims": "account_id,run_id,reservation_id",
        "auth_job_outbox": "reservation_id,payload,created_at,delivered_at",
    }
    for table, names in columns.items():
        conn.execute("SELECT " + names + " FROM " + table + " LIMIT 0")
    row = conn.execute(
        "SELECT count(*) AS n FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'auth12_%' AND tgrelid IN ('auth_budget_scopes'::regclass,'auth_resource_budgets'::regclass,'auth_reservations'::regclass,'auth_reservation_allocations'::regclass,'auth_usage_postings'::regclass,'auth_analysis_claims'::regclass,'auth_job_outbox'::regclass) AND tgenabled IN ('O','A')"
    ).fetchone()
    if row["n"] != 8:
        raise AuthSchemaNotReady()
