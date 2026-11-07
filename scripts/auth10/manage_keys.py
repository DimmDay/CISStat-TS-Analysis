#!/usr/bin/env python3
"""Trusted service-key issuance and emergency revoke. Secret shown once to TTY."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "operation", choices=("issue-service", "rotate-service", "inspect", "revoke")
    )
    p.add_argument("--subject-id", required=True, type=UUID)
    p.add_argument("--account-id", required=True, type=UUID)
    p.add_argument("--key-id", type=UUID)
    p.add_argument("--expected-version", type=int)
    p.add_argument("--label")
    p.add_argument("--scopes", nargs="+")
    p.add_argument("--expires-in-days", type=int)
    p.add_argument("--reason")
    args = p.parse_args()
    if args.operation != "inspect":
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            p.error("interactive operator terminal required")
        if not args.reason:
            p.error("bounded reason required")
    if (
        args.operation in ("inspect", "rotate-service", "revoke")
        and args.key_id is None
    ):
        p.error("--key-id required")
    if args.operation in ("revoke", "rotate-service") and args.expected_version is None:
        p.error("--expected-version required")
    try:
        from apps.api.authentication.api_key_contract import IssueKeyBody, RotateKeyBody
        from apps.api.authentication.api_key_migrations import check_schema
        from apps.api.authentication.api_keys import APIKeyService, public_key
        from apps.api.authentication.storage import PostgresAccessStore

        store = PostgresAccessStore.from_env()
        service = APIKeyService(store)
        if args.operation == "inspect":
            with store.transaction(readonly=True) as tx:
                check_schema(tx.connection)
                row = tx.connection.execute(
                    "SELECT * FROM auth_api_keys WHERE key_id=%s AND subject_id=%s AND account_id=%s",
                    (args.key_id, args.subject_id, args.account_id),
                ).fetchone()
                if row is None:
                    raise ValueError("not found")
                result = public_key(row)
        elif args.operation == "issue-service":
            body = IssueKeyBody(
                label=args.label,
                scopes=args.scopes,
                expires_in_days=args.expires_in_days,
            )
            issued = service.operator_issue(
                args.subject_id, args.account_id, body, reason=args.reason
            )
            result = {"secret": issued.secret, "key": issued.key}
        elif args.operation == "rotate-service":
            body = RotateKeyBody(
                expected_version=args.expected_version, scopes=args.scopes
            )
            issued = service.operator_rotate(
                args.subject_id, args.account_id, args.key_id, body, reason=args.reason
            )
            result = {"secret": issued.secret, "key": issued.key}
        else:
            result = service.operator_revoke(
                args.subject_id,
                args.account_id,
                args.key_id,
                args.expected_version,
                reason=args.reason,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception:  # noqa: BLE001 -- never print credentials, DSN or validation input
        print(json.dumps({"ok": False, "code": "api_key_command_failed"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
