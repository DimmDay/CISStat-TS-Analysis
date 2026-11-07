#!/usr/bin/env python3
"""Explicit AUTH-10 migration/readiness; DSN only from environment."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--check", action="store_true")
    args = p.parse_args()
    try:
        from apps.api.authentication.api_key_migrations import apply_migration
        from apps.api.authentication.api_keys import APIKeyService
        from apps.api.authentication.storage import PostgresAccessStore

        store = PostgresAccessStore.from_env()
        if args.apply:
            with store.transaction() as tx:
                applied = apply_migration(tx.connection)
            print(json.dumps({"applied": applied}))
        print(json.dumps(APIKeyService(store).readiness()))
        return 0
    except Exception:  # noqa: BLE001 -- safe operator boundary
        print(json.dumps({"ok": False, "code": "auth_authority_unavailable"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
