"""Local trusted resource-ceiling operator. No money/payment/plan grant or HTTP API."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    scope = sub.add_parser("scope-create")
    scope.add_argument("kind", choices=["sponsor", "campaign", "account", "grant"])
    scope.add_argument("--account-id")
    scope.add_argument("--parent-id")
    scope.add_argument("--ends-at")
    budget = sub.add_parser("budget-set")
    budget.add_argument("scope_id")
    budget.add_argument("metric", choices=["cu", "api", "analysis", "concurrency"])
    budget.add_argument("--limit-units", type=int, required=True)
    budget.add_argument("--period", default="lifetime")
    budget.add_argument("--expected-version", type=int, required=True)
    status = sub.add_parser("scope-status")
    status.add_argument("scope_id")
    status.add_argument("status", choices=["active", "paused", "closed"])
    status.add_argument("--expected-version", type=int, required=True)
    for p in (scope, budget, status):
        p.add_argument("--reason", required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        print("Interactive trusted operator terminal required.", file=sys.stderr)
        return 2
    try:
        from apps.api.billing.policy import BudgetPolicy

        policy = BudgetPolicy()
        if args.command == "scope-create":
            from datetime import datetime

            result = policy.create_scope(
                args.kind,
                account_id=args.account_id,
                parent_id=args.parent_id,
                ends_at=datetime.fromisoformat(args.ends_at) if args.ends_at else None,
                reason=args.reason,
            )
        elif args.command == "scope-status":
            result = policy.set_status(
                args.scope_id,
                expected_version=args.expected_version,
                status=args.status,
                reason=args.reason,
            )
        else:
            result = policy.set_budget(
                args.scope_id,
                args.metric,
                limit_units=args.limit_units,
                period=args.period,
                expected_version=args.expected_version,
                reason=args.reason,
            )
        print(json.dumps(result, default=str))
        return 0
    except Exception:  # noqa: BLE001 -- safe operator boundary; no DSNs/driver messages
        print(json.dumps({"ok": False, "code": "budget_operator_command_failed"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
