"""AUTH-25 reconciliation/restore/launch CLI. Operator-facing; no HTTP
surface. Read-only modes never mutate; the two mutating modes (restore
comparison, finance-hold quarantine) write the mandatory audit intent in the
same transaction and never re-apply money automatically.

Examples:
  python scripts/auth25/reconcile.py --report
  python scripts/auth25/reconcile.py --export-watermark /var/lib/cisstat-ops/financial-watermark.json
  python scripts/auth25/reconcile.py --reconcile-watermark --watermark /var/lib/cisstat-ops/financial-watermark.json --reason "restore-2026-11-12"
  python scripts/auth25/reconcile.py --lock-flagged --reason "uncertain state before manual review"
  python scripts/auth25/reconcile.py --launch-check
  python scripts/auth25/reconcile.py --launch-check --allow-empty-catalog
DSN comes from CISSTAT_AUTH_DATABASE_URL / DATABASE_URL (libpq format).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--report", action="store_true", help="read-only consistency report")
    mode.add_argument(
        "--export-watermark",
        metavar="PATH",
        help="write the out-of-pgdata financial watermark (run BEFORE every backup)",
    )
    mode.add_argument(
        "--reconcile-watermark",
        action="store_true",
        help="compare a watermark with the live DB after a backup restore",
    )
    mode.add_argument(
        "--lock-flagged",
        action="store_true",
        help="finance hold on wallets of accounts with blocking findings",
    )
    mode.add_argument(
        "--launch-check",
        action="store_true",
        help="pre-launch gate: terms/catalog/provider/report readiness facts",
    )
    parser.add_argument("--watermark", metavar="PATH", help="watermark file for --reconcile-watermark")
    parser.add_argument(
        "--reason",
        default="",
        help="operator reason (mandatory for --reconcile-watermark/--lock-flagged, recorded in audit)",
    )
    parser.add_argument(
        "--allow-empty-catalog",
        action="store_true",
        help="treat the empty catalog as an intentional off state, not a blocker",
    )
    args = parser.parse_args()

    try:
        from apps.api.authentication.storage import PostgresAccessStore
        from apps.api.billing.reconciliation import FinancialReconciliationService

        if (args.reconcile_watermark or args.lock_flagged) and not args.reason.strip():
            parser.error("--reason is mandatory for mutating modes")

        service = FinancialReconciliationService(store=PostgresAccessStore.from_env())
        if args.report:
            result = service.report()
        elif args.export_watermark:
            result = service.export_watermark(args.export_watermark)
        elif args.reconcile_watermark:
            if not args.watermark:
                parser.error("--reconcile-watermark requires --watermark PATH")
            raw = Path(args.watermark).read_text(encoding="utf-8")
            result = service.reconcile_watermark(
                json.loads(raw), reason=args.reason.strip()
            )
        elif args.lock_flagged:
            result = service.lock_flagged(reason=args.reason.strip())
        else:  # --launch-check
            result = service.launch_check(environ=None, allow_empty_catalog=args.allow_empty_catalog)
        print(json.dumps({"ok": True, "result": result}, default=str))
        if args.launch_check:
            return 0 if result["ok"] else 1
        if args.report:
            return 0 if result["ok"] else 1
        if args.reconcile_watermark:
            return 0 if result["ok"] else 1
        return 0
    except Exception as exc:  # noqa: BLE001 — bounded CLI boundary; no secrets
        detail = getattr(exc, "code", "") or type(exc).__name__
        print(
            json.dumps(
                {"ok": False, "code": "reconciliation_rejected", "detail": str(detail)}
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
