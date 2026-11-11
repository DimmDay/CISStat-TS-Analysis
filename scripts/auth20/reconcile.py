"""AUTH-20 operations CLI: marks export, restore reconciliation,
quarantine and audit outbox delivery. Operator-facing; no HTTP surface.

Examples:
  python scripts/auth20/reconcile.py --export /var/lib/cisstat-ops-marks/marks.json
  python scripts/auth20/reconcile.py --reconcile --marks /var/lib/cisstat-ops-marks/marks.json --reason "restore-2026-11-11"
  python scripts/auth20/reconcile.py --quarantine --reason "doubt-before-reconcile"
  python scripts/auth20/reconcile.py --drain-audit --limit 100
  python scripts/auth20/reconcile.py --prune --retention-days 180
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
    mode.add_argument("--export", metavar="PATH", help="write out-of-band marks file (run BEFORE every backup)")
    mode.add_argument("--reconcile", action="store_true", help="replay a marks file after backup restore")
    mode.add_argument("--quarantine", action="store_true", help="close all sessions and pause active campaigns")
    mode.add_argument("--drain-audit", action="store_true", help="deliver one bounded batch of the mandatory audit outbox")
    mode.add_argument("--prune", action="store_true", help="prune the revocation ledger by retention")
    mode.add_argument("--marks", metavar="PATH", help="marks file for --reconcile")
    mode.add_argument("--reason", default="", help="operator reason (mandatory for --quarantine, recorded in audit)")
    mode.add_argument("--limit", type=int, default=100, help="bounded batch limit for --drain-audit")
    mode.add_argument("--retention-days", default=None, help="ledger retention for --prune (minimum 7)")
    args = parser.parse_args()

    try:
        from apps.api.authentication.ops_service import (
            AuthOpsService,
            RECONCILE_MAX_ITEMS,
        )
        from apps.api.authentication.storage import PostgresAccessStore

        service = AuthOpsService(store=PostgresAccessStore.from_env())
        if args.export:
            if args.reason:
                parser.error("--export does not take --reason")
            result = service.export_marks(args.export)
        elif args.reconcile:
            if not args.marks:
                parser.error("--reconcile requires --marks PATH")
            raw = Path(args.marks).read_text(encoding="utf-8")
            document = json.loads(raw)
            result = service.reconcile_marks(document, reason=args.reason)
            result["unrepairable"] = result["unrepairable"][: RECONCILE_MAX_ITEMS]
        elif args.quarantine:
            if not args.reason.strip():
                parser.error("--quarantine requires --reason (recorded in mandatory audit)")
            result = service.quarantine(reason=args.reason)
        elif args.drain_audit:
            from apps.api.security_audit import PostgresAuditSink

            sink = PostgresAuditSink.from_env()
            result = {"delivered": service.drain_audit(limit=args.limit, sink=sink)}
        else:
            result = service.prune_ledger(retention_days=args.retention_days)
        print(json.dumps({"ok": True, **result}, ensure_ascii=False, default=str))
        return 0
    except ValueError as issue:
        print(json.dumps({"ok": False, "code": "invalid_marks", "detail": str(issue)[:300]}))
        return 2
    except Exception:  # noqa: BLE001 — bounded service/CLI boundary; no driver or secret output
        print(json.dumps({"ok": False, "code": "auth_authority_unavailable"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
