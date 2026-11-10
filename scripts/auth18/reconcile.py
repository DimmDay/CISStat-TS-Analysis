"""Queue an existing order for authenticated provider recovery, never mark it paid manually."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("order_id", type=UUID)
    p.add_argument("payment_id")
    p.add_argument("--reason", required=True)
    args = p.parse_args()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        p.error("interactive operator terminal required")
    if input("Type order UUID: ").strip() != str(args.order_id):
        return 2
    try:
        from apps.api.billing.subscriptions import SubscriptionService

        print(
            json.dumps(
                SubscriptionService().reconcile(
                    args.order_id, args.payment_id, reason=args.reason
                )
            )
        )
        return 0
    except Exception:  # noqa: BLE001 -- safe operator boundary
        print('{"ok":false,"code":"billing_reconcile_rejected"}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
