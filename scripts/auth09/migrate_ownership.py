#!/usr/bin/env python3
"""Interactive trusted operator legacy migration. DSN only from environment."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def nullable(value):
    return None if value == "null" else value


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("operation", choices=("inspect", "apply"))
    p.add_argument("run_id")
    p.add_argument("--account-id", required=True, type=UUID)
    p.add_argument("--expected-version", type=int)
    p.add_argument("--expected-account-version", type=int)
    p.add_argument("--expected-owner-subject", type=nullable, default=argparse.SUPPRESS)
    p.add_argument("--expected-tenant-id", type=nullable, default=argparse.SUPPRESS)
    p.add_argument("--evidence")
    p.add_argument("--reason")
    args = p.parse_args(argv)
    if args.operation == "apply":
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            p.error("interactive operator terminal required")
        if (
            args.expected_version is None
            or args.expected_account_version is None
            or not hasattr(args, "expected_owner_subject")
            or not hasattr(args, "expected_tenant_id")
            or not args.evidence
            or not args.reason
        ):
            p.error(
                "explicit source/version/evidence/reason required; use null for unknown provenance"
            )
    try:
        from apps.api.accounts.ownership_migration import migrate_legacy_run
        from apps.api.authentication.storage import PostgresAccessStore

        store = PostgresAccessStore.from_env()
        if args.operation == "inspect":
            with store.transaction(readonly=True) as tx:
                run = tx.connection.execute(
                    "SELECT run_id,owner_account_id,owner_subject,tenant_id,ownership,ownership_version FROM research_runs WHERE run_id=%s",
                    (args.run_id,),
                ).fetchone()
                account = tx.accounts.get(args.account_id)
                if run is None or account is None:
                    raise ValueError("not found")
                result = {"run": run, "target_account": account.model_dump(mode="json")}
        else:
            if (
                input("Type run ID to confirm reviewed migration: ").strip()
                != args.run_id
            ):
                return 2
            result = migrate_legacy_run(
                store=store,
                run_id=args.run_id,
                account_id=args.account_id,
                expected_version=args.expected_version,
                expected_account_version=args.expected_account_version,
                expected_owner_subject=args.expected_owner_subject,
                expected_tenant_id=args.expected_tenant_id,
                evidence=args.evidence,
                reason=args.reason,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001 -- operator boundary redacts authority errors
        from apps.api.authentication.errors import (
            RecordNotFound,
            RepositoryConflict,
            VersionConflict,
        )

        code = {
            VersionConflict: "ownership_version_conflict",
            RepositoryConflict: "ownership_constraint_violation",
            RecordNotFound: "run_not_found",
        }.get(type(exc), "ownership_authority_unavailable")
        print(code, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
