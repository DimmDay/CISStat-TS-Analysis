"""Native demo/transport regression. Missing DSN or skips never count as PASS."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    if not os.environ.get("CISSTAT_AUTH_TEST_DSN"):
        print(
            "Disposable CISSTAT_AUTH_TEST_DSN required; no tests ran.", file=sys.stderr
        )
        return 2
    suite = unittest.TestSuite(
        unittest.defaultTestLoader.loadTestsFromName(name)
        for name in (
            "tests.integration.test_auth06_transport",
            "tests.integration.test_auth15_demo",
            "tests.integration.test_auth16_lifecycle",
        )
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() and result.testsRun and not result.skipped else 1


if __name__ == "__main__":
    sys.exit(main())
