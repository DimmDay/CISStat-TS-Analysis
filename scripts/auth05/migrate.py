#!/usr/bin/env python3
"""Explicit AUTH-05 schema apply/readiness; credentials only in environment."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apps.api.authentication.mfa_migrations import apply_migration
from apps.api.authentication.sessions import SessionService
from apps.api.authentication.storage import PostgresAccessStore


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
    except Exception:  # noqa: BLE001 — operator boundary must redact all authority errors
        print(json.dumps({"ok": False, "code": "auth_authority_unavailable"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
