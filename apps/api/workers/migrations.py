"""AUTH-13 explicit migration; previous version/checksum contracts are preserved."""

import hashlib
from pathlib import Path

from apps.api.billing.migrations import apply_migration as apply_identity
from apps.api.authentication.errors import AuthSchemaNotReady

VERSION = "0026_auth13_workers"
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
    from apps.api.billing.migrations import check_schema as check_billing

    check_billing(conn)
    row = conn.execute(
        "SELECT checksum FROM auth_schema_versions WHERE version=%s", (VERSION,)
    ).fetchone()
    if not row or row["checksum"] != CHECKSUM:
        raise AuthSchemaNotReady()
    conn.execute(
        "SELECT service_id,key_hash,kinds,expires_at,revoked_at FROM auth_worker_services LIMIT 0"
    )
    conn.execute(
        "SELECT worker_id,reservation_id,delegation,descriptor,input_digest,state,fence,phase,deadline,lease_until,stop_proof FROM auth_worker_jobs LIMIT 0"
    )
    row = conn.execute(
        "SELECT count(*) AS n FROM pg_trigger WHERE NOT tgisinternal AND tgname IN ('auth13_job_guard','auth13_service_guard') AND tgrelid IN ('auth_worker_jobs'::regclass,'auth_worker_services'::regclass) AND tgenabled IN ('O','A')"
    ).fetchone()
    if row["n"] != 2:
        raise AuthSchemaNotReady()
