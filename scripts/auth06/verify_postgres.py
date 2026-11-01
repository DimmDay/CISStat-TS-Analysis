#!/usr/bin/env python3
"""Mandatory live-PostgreSQL gate. Missing DSN/skipped tests cannot mean PASS."""

import os
import subprocess
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
        str(ROOT / "tests/integration"), pattern="test_auth06_transport.py"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not (result.wasSuccessful() and result.testsRun > 0 and not result.skipped):
        return 1
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/auth06/wire_e2e.py")],
        cwd=ROOT,
        check=False,
    ).returncode


if __name__ == "__main__":
    sys.exit(main())
