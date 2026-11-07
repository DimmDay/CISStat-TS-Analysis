"""AUTH-09 trusted single-run operator CAS; never mount as HTTP claim."""

import hashlib
import json
import os
from uuid import UUID

from apps.api.accounts.entitlements import account_is_active
from apps.api.authentication.errors import (
    RecordNotFound,
    RepositoryConflict,
    VersionConflict,
)
from apps.api.authentication.mfa_migrations import check_schema
from apps.api.authentication.storage import PostgresAccessStore


def _shared_relation_ids(store):
    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    # Explicit VM profile. Avoid lazy factory warming/DDL in concurrent commands.
    if (
        os.environ.get("CISSTAT_SESSION_BACKEND", "").strip().lower() != "postgres"
        or os.environ.get("CISSTAT_STORAGE_MODE", "").strip().lower() != "required"
    ):
        raise RepositoryConflict()
    science_dsn = os.environ.get("DATABASE_URL", "")
    if not science_dsn or conninfo_to_dict(science_dsn) != conninfo_to_dict(store._dsn):
        raise RepositoryConflict()
    with psycopg.connect(science_dsn, connect_timeout=3) as c:
        ids = c.execute(
            "SELECT to_regclass('research_runs')::oid,to_regclass('analysis_sessions')::oid"
        ).fetchone()
    if not all(ids):
        raise RepositoryConflict()
    return ids


def migrate_legacy_run(
    *,
    run_id,
    account_id,
    expected_account_version,
    expected_owner_subject,
    expected_tenant_id,
    expected_version,
    evidence,
    reason,
    store=None,
):
    """Account→run→session locks, ownership + immutable receipt + audit one UoW.

    Operator independently reviews evidence; possession of a run ID is no proof.
    Scientific objects and historical audit bytes are not rewritten.
    """
    from apps.api.identity import is_valid_run_id
    from apps.api.telemetry import redact_text

    if (
        not is_valid_run_id(run_id)
        or type(expected_version) is not int
        or expected_version != 0
    ):
        raise VersionConflict()
    account_id = UUID(str(account_id))
    if type(expected_account_version) is not int or expected_account_version < 1:
        raise VersionConflict()
    for value in (evidence, reason):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 256:
            raise ValueError("bounded evidence/reason required")
    evidence, reason = redact_text(evidence, limit=256), redact_text(reason, limit=256)
    store = store if store is not None else PostgresAccessStore.from_env()
    relation_ids = _shared_relation_ids(store)
    with store.transaction() as tx:
        c = tx.connection
        check_schema(c)
        ids = c.execute(
            "SELECT to_regclass('research_runs')::oid AS runs,to_regclass('analysis_sessions')::oid AS sessions"
        ).fetchone()
        if (ids["runs"], ids["sessions"]) != relation_ids:
            raise RepositoryConflict()
        account = tx.accounts._lock(account_id, expected_account_version)
        now = c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        if not account_is_active(account, now=now):
            raise RepositoryConflict()
        run = c.execute(
            "SELECT * FROM research_runs WHERE run_id=%s FOR UPDATE", (run_id,)
        ).fetchone()
        if run is None:
            raise RecordNotFound()
        if (
            run["owner_account_id"] is not None
            or run["ownership_version"] != expected_version
            or run["owner_subject"] != expected_owner_subject
            or run["tenant_id"] != expected_tenant_id
        ):
            raise VersionConflict()
        session = c.execute(
            "SELECT * FROM analysis_sessions WHERE session_id=%s FOR UPDATE",
            (run["session_id"],),
        ).fetchone()
        live = session is not None and session["expires_at"] > now
        if live:
            payload = session["payload"]
            if (
                payload.get("run_id") != run_id
                or payload.get("owner_account_id") is not None
                or payload.get("owner_subject") != expected_owner_subject
                or payload.get("tenant_id") != expected_tenant_id
            ):
                raise VersionConflict()
        c.execute(
            """INSERT INTO run_ownership_migrations(run_id,owner_account_id,tenant_id,
            previous_owner_subject,previous_tenant_id,previous_session_hash,evidence,reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                run_id,
                account_id,
                account["tenant_id"],
                expected_owner_subject,
                expected_tenant_id,
                hashlib.sha256(
                    ("auth09.legacy-pointer/1\0" + (run["session_id"] or "")).encode()
                ).hexdigest(),
                evidence,
                reason,
            ),
        )
        c.execute(
            "UPDATE research_runs SET owner_account_id=%s,tenant_id=%s,ownership='bound',ownership_version=1 WHERE run_id=%s",
            (account_id, str(account["tenant_id"]), run_id),
        )
        if live:
            from apps.api.session_store import SESSION_SCHEMA_VERSION

            payload = dict(session["payload"])
            payload.update(
                owner_account_id=str(account_id),
                tenant_id=str(account["tenant_id"]),
                session_schema_version=SESSION_SCHEMA_VERSION,
                storage_revision=session["storage_revision"] + 1,
            )
            c.execute(
                """UPDATE analysis_sessions SET payload=%s::jsonb,storage_revision=storage_revision+1,
                updated_at=%s WHERE session_id=%s""",
                (json.dumps(payload), now, run["session_id"]),
            )
        from apps.api.security_audit import build_audit_record

        record = build_audit_record(
            "auth_ownership_migrated",
            "allowed",
            actor_subject="operator:local",
            actor_via="operator_cli",
            tenant_id=str(account["tenant_id"]),
            resource_kind="research_run",
            resource_id=run_id,
            resource_version="1",
            run_id=run_id,
            policy_basis="AUTH-09 explicit legacy CAS migration",
            details={
                "owner_account_id": str(account_id),
                "evidence": evidence,
                "reason": reason,
            },
        )
        c.execute(
            "INSERT INTO auth_audit_outbox(audit_id,payload) VALUES (%s,%s::jsonb)",
            (record["audit_id"], json.dumps(record)),
        )
        return {
            "run_id": run_id,
            "owner_account_id": str(account_id),
            "tenant_id": str(account["tenant_id"]),
            "ownership_version": 1,
        }
