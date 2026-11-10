"""Explicit AUTH-17 migration/readiness. Never runs DDL on worker admission."""

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
        from apps.api.accounts.team_migrations import (
            VERSION,
            apply_migration,
            check_schema,
        )
        from apps.api.authentication.storage import PostgresAccessStore

        store = PostgresAccessStore.from_env()
        with store.transaction() as tx:
            applied = apply_migration(tx.connection) if args.apply else False
            check_schema(tx.connection)
        print(
            json.dumps(
                {
                    "ok": True,
                    "applied": applied,
                    "schema_version": VERSION,
                    "seat_activation": "trusted confirmed entitlement only",
                }
            )
        )
        return 0
    except Exception:  # noqa: BLE001 — bounded service/CLI boundary; no driver or secret output
        print(json.dumps({"ok": False, "code": "auth_authority_unavailable"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
