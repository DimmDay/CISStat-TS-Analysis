#!/usr/bin/env python3
"""Explicit auth migration/readiness CLI. Credentials stay in environment."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apps.api.authentication.storage import PostgresAccessStore
from apps.api.authentication.errors import (
    AuthSchemaNotReady,
    AuthStoreUnavailable,
    RepositoryConflict,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--apply", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        store = PostgresAccessStore.from_env()
        if args.apply:
            print(json.dumps({"applied": store.migrate()}))
        state = store.readiness()
        print(json.dumps(state))
        return 0 if state["ok"] else 1
    except (AuthSchemaNotReady, AuthStoreUnavailable, RepositoryConflict) as exc:
        print(json.dumps({"ok": False, "code": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
