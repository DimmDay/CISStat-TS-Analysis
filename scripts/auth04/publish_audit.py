#!/usr/bin/env python3
"""Bounded AUTH-04 audit replay. Use existing Postgres audit sink configuration."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apps.api.authentication.audit_outbox import publish_pending


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--limit", type=int, default=100)
    args = p.parse_args()
    try:
        print(json.dumps({"published": publish_pending(limit=args.limit)}))
        return 0
    except Exception:
        print(json.dumps({"ok": False, "code": "audit_delivery_unavailable"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
