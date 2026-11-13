"""Mandatory native F-CERT-H1 gate: missing DSN or skips is not a PASS.

Оракулы warmup-поставки на реальном disposable PostgreSQL:
deadlock-класс lazy-DDL (механизм), прогрев lifespan (12 слоёв честных
статусов), coexistence (audit-append под незакрытой транзакцией conn A),
идемпотентность, advisory no-op. Паритет scripts/authNN/verify_postgres.py.
"""

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
        str(ROOT / "tests/integration"), pattern="test_warmup*.py"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return (
        0
        if result.wasSuccessful() and result.testsRun > 0 and not result.skipped
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
