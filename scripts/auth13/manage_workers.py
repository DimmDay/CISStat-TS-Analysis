"""Trusted operator service credentials and bounded reconciliation; no force refund."""

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=("issue-service", "revoke-service", "inspect", "reconcile")
    )
    parser.add_argument(
        "--kinds", nargs="+", choices=("modeling", "render", "delivery")
    )
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--service-id", type=UUID)
    parser.add_argument("--reason")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.limit <= 200:
        parser.error("--limit must be 1..200")
    if args.operation in ("issue-service", "revoke-service"):
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            parser.error("interactive operator terminal required")
        if not args.reason:
            parser.error("--reason required")
    if args.operation == "issue-service" and not args.kinds:
        parser.error("--kinds required")
    if args.operation == "revoke-service" and not args.service_id:
        parser.error("--service-id required")
    try:
        from apps.api.authentication.storage import PostgresAccessStore
        from apps.api.workers.services import WorkerServices
        from apps.api.workers.authority import WorkerAuthority
        from apps.api.workers.migrations import check_schema

        store = PostgresAccessStore.from_env()
        if args.operation == "issue-service":
            result = {
                "secret": WorkerServices(store).issue(
                    kinds=args.kinds, days=args.days, reason=args.reason
                )
            }
        elif args.operation == "revoke-service":
            WorkerServices(store).revoke(args.service_id, reason=args.reason)
            result = {"ok": True}
        elif args.operation == "reconcile":
            result = WorkerAuthority(store).reconcile(limit=args.limit)
        else:
            with store.transaction(readonly=True) as tx:
                check_schema(tx.connection)
                jobs = tx.connection.execute(
                    "SELECT worker_id,kind,external_id,state,fence,phase,deadline,lease_until,error_code FROM auth_worker_jobs ORDER BY created_at,worker_id LIMIT %s",
                    (args.limit,),
                ).fetchall()
                services = tx.connection.execute(
                    "SELECT service_id,kinds,expires_at,revoked_at FROM auth_worker_services ORDER BY created_at LIMIT %s",
                    (args.limit,),
                ).fetchall()
            result = {"jobs": jobs, "services": services}
        print(json.dumps(result, default=str, ensure_ascii=False))
        return 0
    except Exception:
        print(json.dumps({"ok": False, "code": "worker_operator_failed"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
