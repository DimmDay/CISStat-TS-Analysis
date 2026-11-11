"""Trusted AUTH-22 top-up operator. Not a public writer; every command carries
a reason and a mandatory audit in the same transaction.

Catalog follows spec_billing_accounts.md §13.4: prices/units come from the
operator only, packages are immutable once created (disable instead of edit),
and the recovery path credit-paid requires an existing purchased lot for the
order (the AUTH-21 unique basis makes a double credit impossible).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add-package", help="catalog a top-up package (immutable)")
    add.add_argument("--title", required=True)
    add.add_argument("--units", type=int, required=True, help="micro-CU")
    add.add_argument("--price-minor", type=int, required=True, help="minor units")
    add.add_argument("--currency", default="RUB")
    add.add_argument("--price-version", required=True)
    add.add_argument("--terms-version", required=True)
    add.add_argument("--reason", required=True)

    disable = sub.add_parser("disable-package", help="disable without rewriting history")
    disable.add_argument("--package-id", required=True)
    disable.add_argument("--reason", required=True)

    packages = sub.add_parser("packages", help="list catalog")

    status = sub.add_parser("status", help="orders of one account")
    status.add_argument("--account-id", required=True)

    reconcile = sub.add_parser(
        "reconcile", help="queue an unknown-outcome order for API-proofed retry"
    )
    reconcile.add_argument("--order-id", required=True)
    reconcile.add_argument("--payment-id", required=True)
    reconcile.add_argument("--reason", required=True)

    credit = sub.add_parser(
        "credit-paid", help="paid_review -> credited after the manual wallet credit"
    )
    credit.add_argument("--order-id", required=True)
    credit.add_argument("--reason", required=True)

    args = parser.parse_args()
    from apps.api.billing.topups import TopupService

    service = TopupService()
    try:
        if args.command == "add-package":
            out = service.provision_package(
                title=args.title,
                units=args.units,
                price_minor=args.price_minor,
                currency=args.currency,
                price_version=args.price_version,
                terms_version=args.terms_version,
                reason=args.reason,
            )
        elif args.command == "disable-package":
            out = service.disable_package(args.package_id, reason=args.reason)
        elif args.command == "packages":
            with service._tx() as tx:
                rows = tx.connection.execute(
                    "SELECT package_id,title,units,price_minor,currency,price_version,"
                    "terms_version,enabled FROM auth_topup_packages ORDER BY created_at"
                ).fetchall()
                out = {"packages": [TopupService.package_view(r) | {"enabled": r["enabled"]} for r in rows]}
        elif args.command == "status":
            with service._tx() as tx:
                rows = tx.connection.execute(
                    "SELECT order_id,state,units,payment_id,credited_at,created_at "
                    "FROM auth_topup_orders WHERE account_id=%s ORDER BY created_at DESC LIMIT 50",
                    (args.account_id,),
                ).fetchall()
                out = {
                    "orders": [
                        {
                            "order_id": str(r["order_id"]),
                            "state": r["state"],
                            "units": int(r["units"]),
                            "payment_id": r["payment_id"],
                            "credited_at": r["credited_at"].isoformat() if r["credited_at"] else None,
                            "created_at": r["created_at"].isoformat(),
                        }
                        for r in rows
                    ]
                }
        elif args.command == "reconcile":
            out = service.reconcile(
                args.order_id, args.payment_id, reason=args.reason
            )
        elif args.command == "credit-paid":
            out = service.credit_paid(args.order_id, reason=args.reason)
        else:  # pragma: no cover - argparse guards this
            raise ValueError("unknown command")
        print(json.dumps({"ok": True, **out}, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001 — bounded CLI boundary
        detail = getattr(exc, "code", "") or type(exc).__name__
        print(json.dumps({"ok": False, "code": "topup_operator_rejected", "detail": str(detail)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
