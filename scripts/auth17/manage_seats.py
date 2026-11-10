"""Trusted interactive entitlement confirmation. Never a browser/provider verifier."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("account_id", type=UUID)
    p.add_argument("request_id", type=UUID)
    p.add_argument("--expected-version", type=int, required=True)
    p.add_argument("--confirmation-ref", required=True)
    p.add_argument("--reason", required=True)
    args = p.parse_args()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        p.error("interactive operator terminal required")
    print(
        "Confirm only after verifying external paid entitlement or an explicitly authorized manual allocation. No CU credit is issued."
    )
    if input("Type account UUID to apply: ").strip() != str(args.account_id):
        return 2
    try:
        from apps.api.accounts.team import TeamService

        print(
            json.dumps(
                TeamService().confirm_capacity(
                    args.account_id,
                    args.request_id,
                    expected_version=args.expected_version,
                    confirmation_ref=args.confirmation_ref,
                    reason=args.reason,
                )
            )
        )
        return 0
    except Exception:  # noqa: BLE001 -- safe operator boundary, no driver/secret output
        print(json.dumps({"ok": False, "code": "seat_confirmation_failed"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
