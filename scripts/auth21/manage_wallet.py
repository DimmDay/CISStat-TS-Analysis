"""Trusted AUTH-21 wallet operator. Not a public writer; every command carries
a reason and a mandatory auth_wallet_changed audit in the same transaction.

Issuance follows spec_billing_accounts.md §13: included lots derive their
amount and expiry from the AUTH-18 cycle row (never client-supplied), purchased
lots are permanent in v1 and unique per origin order, promotional lots carry an
explicit basis and optional bounded expiry. No pricing, no provider, no HTTP.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _parse_expiry(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("aware ISO-8601 expiry required")
    return parsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-wallet", help="provision one wallet per Account")
    create.add_argument("--account-id", required=True)
    create.add_argument("--reason", required=True)

    included = sub.add_parser(
        "issue-included", help="issue the cycle's included lot (formula-pinned)"
    )
    included.add_argument("--account-id", required=True)
    included.add_argument("--cycle-id", required=True)
    included.add_argument("--ref", default="base", help="issuance basis (base|proration:<order>)")
    included.add_argument("--reason", required=True)

    purchased = sub.add_parser("issue-purchased", help="issue a permanent purchased lot")
    purchased.add_argument("--account-id", required=True)
    purchased.add_argument("--units", type=int, required=True, help="micro-CU")
    purchased.add_argument("--origin-order", required=True)
    purchased.add_argument("--reason", required=True)

    promo = sub.add_parser("issue-promotional", help="issue an explicit promotional lot")
    promo.add_argument("--account-id", required=True)
    promo.add_argument("--units", type=int, required=True, help="micro-CU")
    promo.add_argument("--origin-ref", required=True)
    promo.add_argument("--expires-at", default=None, help="optional aware ISO-8601")
    promo.add_argument("--reason", required=True)

    lock = sub.add_parser("lock", help="finance hold: block new CU reservations")
    lock.add_argument("--wallet-id", required=True)
    lock.add_argument("--expected-version", type=int, required=True)
    lock.add_argument("--reason", required=True)

    unlock = sub.add_parser("unlock", help="explicit audited recovery")
    unlock.add_argument("--wallet-id", required=True)
    unlock.add_argument("--expected-version", type=int, required=True)
    unlock.add_argument("--reason", required=True)

    sweep = sub.add_parser("sweep", help="bounded available->expired transition")
    sweep.add_argument("--limit", type=int, default=100)
    sweep.add_argument("--reason", required=True)

    status = sub.add_parser("status", help="read-only wallet summary")
    status.add_argument("--account-id", required=True)

    args = parser.parse_args()
    try:
        from apps.api.authentication.storage import PostgresAccessStore
        from apps.api.billing.wallet import WalletService

        service = WalletService(PostgresAccessStore.from_env())
        if args.command == "create-wallet":
            result = service.create_wallet(args.account_id, reason=args.reason)
        elif args.command == "issue-included":
            result = service.issue_included_for_cycle(
                args.account_id, args.cycle_id, ref=args.ref, reason=args.reason
            )
        elif args.command == "issue-purchased":
            result = service.issue_purchased(
                args.account_id,
                args.units,
                origin_order=args.origin_order,
                reason=args.reason,
            )
        elif args.command == "issue-promotional":
            result = service.issue_promotional(
                args.account_id,
                args.units,
                origin_ref=args.origin_ref,
                expires_at=_parse_expiry(args.expires_at),
                reason=args.reason,
            )
        elif args.command == "lock":
            result = service.set_status(
                args.wallet_id,
                expected_version=args.expected_version,
                status="locked",
                reason=args.reason,
            )
        elif args.command == "unlock":
            result = service.set_status(
                args.wallet_id,
                expected_version=args.expected_version,
                status="active",
                reason=args.reason,
            )
        elif args.command == "sweep":
            result = service.sweep_expiry(limit=args.limit, reason=args.reason)
        else:
            result = service.summary(UUID(args.account_id))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
        return 0
    except Exception as exc:  # noqa: BLE001 — bounded CLI boundary; secrets never printed
        message = getattr(getattr(exc, "detail", None), "get", lambda *_: None)("code")
        print(
            json.dumps(
                {
                    "ok": False,
                    "code": message or type(exc).__name__,
                }
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
