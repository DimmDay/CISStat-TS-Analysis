"""AUTH-CERT browser-layer gate: static oracles on both shells (no DSN needed)."""

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    suite = unittest.defaultTestLoader.discover(
        str(ROOT / "tests/integration"), pattern="test_authcert_browser.py"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return (
        0
        if result.wasSuccessful() and result.testsRun > 0 and not result.skipped
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
