#!/usr/bin/env python3
"""Independent actual ASGI OpenAPI vs reviewed AUTH-00 source inventory."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from apps.api.access_registry import REGISTRY
from apps.api.main import app
from scripts.auth00.inventory import check


def main():
    report = check()
    expected = {e["id"][4:] for e in report["entries"] if e["kind"] == "api"}
    actual = {
        method.upper() + ":" + path
        for path, ops in app.openapi()["paths"].items()
        for method in ops
        if method
        in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
    }
    assert actual == expected, {
        "added": sorted(actual - expected),
        "missing": sorted(expected - actual),
    }
    assert {"api:" + entry for entry in actual} <= set(REGISTRY.bindings)
    print(
        json.dumps(
            {
                "status": "ok",
                "actual_api": len(actual),
                "inventory_api": len(expected),
                "registry_bindings": len(REGISTRY.bindings),
                "inventory_entries": len(report["entries"]),
                "added": [],
                "missing": [],
            }
        )
    )


if __name__ == "__main__":
    main()
