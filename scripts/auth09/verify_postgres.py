#!/usr/bin/env python3
"""Mandatory native PostgreSQL gate: missing DSN or skips is not a PASS."""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    if not os.environ.get("CISSTAT_AUTH_TEST_DSN"):
        print(
            "Set CISSTAT_AUTH_TEST_DSN to a disposable PostgreSQL database. No tests ran.",
            file=sys.stderr,
        )
        return 2
    suite = unittest.defaultTestLoader.discover(
        str(ROOT / "tests/integration"), pattern="test_auth09*.py"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return (
        0
        if result.wasSuccessful() and result.testsRun > 0 and not result.skipped
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
