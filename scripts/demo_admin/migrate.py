"""Explicit additive 0037 admin-notice migration, never on HTTP admission."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--check", action="store_true")
    a = p.parse_args()
    try:
        from apps.api.authentication.demo_admin_migrations import (
            VERSION,
            apply_migration,
            check_schema,
        )
        from apps.api.authentication.storage import PostgresAccessStore

        with PostgresAccessStore.from_env().transaction() as tx:
            applied = apply_migration(tx.connection) if a.apply else False
            check_schema(tx.connection)
        print(json.dumps({"ok": True, "applied": applied, "version": VERSION}))
        return 0
    except Exception:  # noqa: BLE001 -- safe operator boundary
        print('{"ok":false,"code":"demo_admin_schema_unavailable"}')
        return 1


if __name__ == "__main__":
    sys.exit(main())
