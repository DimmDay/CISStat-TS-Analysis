"""Register an approved existing sandbox subscription; never a public credit endpoint."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("account_id", type=UUID)
    p.add_argument("--starts-at", required=True, type=datetime.fromisoformat)
    p.add_argument("--ends-at", required=True, type=datetime.fromisoformat)
    p.add_argument("--seat-price-minor", required=True, type=int)
    p.add_argument("--included-per-seat", required=True, type=int)
    p.add_argument("--price-version", required=True)
    p.add_argument("--terms-version", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument(
        "--allow-reduction",
        action="store_true",
        help="Approved zero-refund decrease terms required",
    )
    args = p.parse_args()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        p.error("interactive operator terminal required")
    print(
        "Only an isolated sandbox Account. This records existing cycle; no CU or seats are granted."
    )
    if input("Type Account UUID: ").strip() != str(args.account_id):
        return 2
    try:
        from apps.api.billing.subscriptions import SubscriptionService

        print(
            json.dumps(
                {
                    "ok": True,
                    "cycle_id": SubscriptionService().provision_cycle(
                        args.account_id,
                        **{k: v for k, v in vars(args).items() if k != "account_id"},
                    ),
                }
            )
        )
        return 0
    except Exception:  # noqa: BLE001 -- safe operator boundary
        print('{"ok":false,"code":"billing_cycle_rejected"}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
