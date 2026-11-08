"""Explicit AUTH-13 migration/readiness. Never runs DDL on worker admission."""

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
        from apps.api.workers.migrations import apply_migration, check_schema, VERSION

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
                    "commercial_cu": "AUTH-14",
                }
            )
        )
        return 0
    except Exception:
        print(json.dumps({"ok": False, "code": "auth_authority_unavailable"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
