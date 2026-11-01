#!/usr/bin/env python3
"""Explicit AUTH-04 schema apply/readiness; credentials only in environment."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apps.api.authentication.storage import PostgresAccessStore
from apps.api.authentication.session_migrations import apply_migration
from apps.api.authentication.sessions import SessionService


def main():
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true")
    group.add_argument("--check", action="store_true")
    args = p.parse_args()
    try:
        store = PostgresAccessStore.from_env()
        if args.apply:
            with store.transaction() as tx:
                applied = apply_migration(tx.connection)
            print(json.dumps({"applied": applied}))
        print(json.dumps(SessionService(store).readiness()))
        return 0
    except Exception:
        print(json.dumps({"ok": False, "code": "auth_authority_unavailable"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
