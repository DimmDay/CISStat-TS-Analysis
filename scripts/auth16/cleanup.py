"""Trusted bounded lifecycle operator. Physical GC requires stopped publishers."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sweep", action="store_true")
    mode.add_argument("--collect-files", action="store_true")
    mode.add_argument("--abandon-calls", action="store_true")
    p.add_argument("--quiesced", action="store_true")
    p.add_argument("--limit", type=int, default=25)
    args = p.parse_args()
    try:
        from apps.api.authentication.demo_cleanup import DemoCleanup

        result = (
            DemoCleanup().sweep(args.limit)
            if args.sweep
            else DemoCleanup().abandon_calls(quiesced=args.quiesced)
            if args.abandon_calls
            else DemoCleanup().collect_files(quiesced=args.quiesced, limit=args.limit)
        )
        print(json.dumps({"ok": True, **result}))
        return 0
    except Exception:  # noqa: BLE001 — bounded service/CLI boundary; no driver or secret output
        print(json.dumps({"ok": False, "code": "demo_cleanup_unavailable"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
