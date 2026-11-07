#!/usr/bin/env python3
"""Trusted local operator CLI. Never mounted in HTTP; DSN comes from environment."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("show", "apply", "membership"))
    parser.add_argument("account_id", type=UUID)
    parser.add_argument("--expected-version", type=int)
    parser.add_argument("--change", help='JSON patch, e.g. {"plan":"starter"}')
    parser.add_argument("--subject-id", type=UUID)
    parser.add_argument("--status", choices=("active", "revoked"))
    parser.add_argument("--reason")
    args = parser.parse_args(argv)
    if args.operation != "show":
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            parser.error("interactive operator terminal required")
        if args.expected_version is None or not args.reason:
            parser.error("--expected-version and --reason required")
    try:
        from apps.api.accounts.lifecycle import AccountChange, AccountLifecycle
        from apps.api.authentication.storage import PostgresAccessStore

        store = PostgresAccessStore.from_env()
        if args.operation == "show":
            with store.transaction(readonly=True) as tx:
                account = tx.accounts.get(args.account_id)
                if account is None:
                    print("account_not_found", file=sys.stderr)
                    return 1
                result = {
                    "account": account.model_dump(mode="json"),
                    "memberships": [
                        m.model_dump(mode="json")
                        for m in tx.accounts.memberships(
                            args.account_id, include_revoked=True
                        )
                    ],
                }
        else:
            if args.operation == "apply":
                if not args.change:
                    parser.error("--change required")

                # JSON-mode accepts an explicit ISO timestamp; naive times are
                # rejected by AwareDatetime. Duplicate patch keys are refused.
                def unique(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError("duplicate patch key")
                        result[key] = value
                    return result

                raw = json.loads(args.change, object_pairs_hook=unique)
                change = AccountChange.model_validate_json(json.dumps(raw))
            elif args.subject_id is None or args.status is None:
                parser.error("--subject-id and --status required")
            if input("Type account UUID to apply: ").strip() != str(args.account_id):
                print("cancelled", file=sys.stderr)
                return 2
            service = AccountLifecycle(store=store)
            common = {"expected_version": args.expected_version, "reason": args.reason}
            result = (
                service.change(args.account_id, change=change, **common)
                if args.operation == "apply"
                else service.membership(
                    args.account_id, args.subject_id, status=args.status, **common
                )
            )
            result = result.model_dump(mode="json")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001 -- hide driver/validation inputs at operator boundary
        from apps.api.authentication.errors import (
            AuthSchemaNotReady,
            AuthStoreUnavailable,
            RecordNotFound,
            RepositoryConflict,
            VersionConflict,
        )

        code = {
            VersionConflict: "auth_version_conflict",
            RepositoryConflict: "account_constraint_violation",
            RecordNotFound: "account_not_found",
            AuthStoreUnavailable: "auth_store_unavailable",
            AuthSchemaNotReady: "auth_schema_not_ready",
        }.get(type(exc), "account_command_failed")
        # Never render ValidationError inputs, driver exceptions or the DSN.
        print(code, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
