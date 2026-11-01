#!/usr/bin/env python3
"""Generate/check proxy method/path allowlist from reviewed AUTH-00 discovery."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.auth00.inventory import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", action="store_true")
    group.add_argument("--check", action="store_true")
    args = parser.parse_args()
    values = [
        {"method": e["method"], "path": e["path"]}
        for e in build()["entries"]
        if e["kind"] == "api"
    ]
    text = json.dumps(values, indent=2) + "\n"
    path = ROOT / "packages/ui/server/proxy-routes.generated.json"
    if args.write:
        path.write_text(text, encoding="utf-8", newline="\n")
    elif path.read_text(encoding="utf-8") != text:
        raise ValueError("Proxy allowlist drift; review AUTH-00 first")
    print(json.dumps({"status": "ok", "api_routes": len(values)}))


if __name__ == "__main__":
    main()
