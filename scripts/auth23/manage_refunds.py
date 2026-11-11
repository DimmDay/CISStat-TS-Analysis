"""Trusted AUTH-23 refund/dispute operator. Not a public writer; every command
carries a reason and a mandatory audit in the same transaction.

Spec: spec_billing_accounts.md §13.7 — self-service refund is only the whole
unused purchased lot of a credited order; chargeback/dispute opening and
resolution are trusted procedures (the bank/provider initiates them, never the
browser), the exposure stays in auth_disputes and never becomes a negative
available balance.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    reconcile = sub.add_parser(
        "refund-reconcile", help="requeue a review_required refund for API-proofed retry"
    )
    reconcile.add_argument("--refund-id", required=True)
    reconcile.add_argument("--reason", required=True)

    open_d = sub.add_parser(
        "dispute-open", help="open a chargeback dispute for a credited order"
    )
    open_d.add_argument("--order-id", required=True)
    open_d.add_argument("--reason", required=True)

    resolve = sub.add_parser(
        "dispute-resolve", help="resolve an open dispute exactly once (lost|won)"
    )
    resolve.add_argument("--dispute-id", required=True)
    resolve.add_argument("--outcome", choices=("lost", "won"), required=True)
    resolve.add_argument("--reason", required=True)

    refunds = sub.add_parser("refunds", help="refunds of one account")
    refunds.add_argument("--account-id", required=True)

    disputes = sub.add_parser("disputes", help="disputes of one account")
    disputes.add_argument("--account-id", required=True)

    args = parser.parse_args()
    from apps.api.billing.refunds import RefundService

    service = RefundService()
    try:
        if args.command == "refund-reconcile":
            out = service.reconcile(args.refund_id, reason=args.reason)
        elif args.command == "dispute-open":
            out = service.dispute_open(args.order_id, reason=args.reason)
        elif args.command == "dispute-resolve":
            out = service.dispute_resolve(
                args.dispute_id, args.outcome, reason=args.reason
            )
        elif args.command == "refunds":
            out = service.refunds_of(args.account_id)
        elif args.command == "disputes":
            out = service.disputes_of(args.account_id)
        else:  # pragma: no cover - argparse guards this
            raise ValueError("unknown command")
        print(json.dumps({"ok": True, **out}, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001 — bounded CLI boundary
        detail = getattr(exc, "code", "") or type(exc).__name__
        print(json.dumps({"ok": False, "code": "refund_operator_rejected", "detail": str(detail)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
