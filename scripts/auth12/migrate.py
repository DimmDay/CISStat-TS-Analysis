"""Explicit AUTH-12 authority migration/readiness; no request-time DDL."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        from apps.api.authentication.storage import PostgresAccessStore
        from apps.api.billing.coordinator import ReservationCoordinator
        from apps.api.billing.migrations import apply_migration

        store = PostgresAccessStore.from_env()
        if args.apply:
            with store.transaction() as tx:
                applied = apply_migration(tx.connection)
            print(json.dumps({"applied": applied}))
        print(json.dumps(ReservationCoordinator(store).readiness()))
        return 0
    except Exception:  # noqa: BLE001 -- safe operator boundary; no DSNs/driver messages
        print(json.dumps({"ok": False, "code": "auth_authority_unavailable"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
