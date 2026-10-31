#!/usr/bin/env python3
"""Check negative oracles by removing constraints ONLY in fresh test schemas."""

import importlib.util
import io
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    if not os.environ.get("CISSTAT_AUTH_TEST_DSN"):
        raise SystemExit("disposable CISSTAT_AUTH_TEST_DSN required")
    spec = importlib.util.spec_from_file_location(
        "auth02_pg_mutants", ROOT / "tests/integration/test_auth02_postgres.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cases = [
        (
            "issuer-sub unique",
            "test_issuer_sub_unique_and_conflict_rolls_back_whole_transaction",
            "ALTER TABLE auth_external_identities DROP CONSTRAINT auth_external_identities_pkey",
        ),
        (
            "MONO and last owner",
            "test_mono_exactly_one_owner_and_no_empty_account_commit",
            "DROP TRIGGER auth02_account_membership_check ON auth_accounts; DROP TRIGGER auth02_member_account_check ON auth_memberships",
        ),
        (
            "immutable tenant",
            "test_immutable_ids_and_tenant_binding",
            "DROP TRIGGER auth02_account_update ON auth_accounts",
        ),
        (
            "unique membership",
            "test_unique_subject_membership_and_foreign_keys_on_server",
            "ALTER TABLE auth_memberships DROP CONSTRAINT auth_memberships_pkey",
        ),
    ]
    for name, method, sql in cases:

        class Mutant(module.PostgresTests):
            def setUp(self):
                super().setUp()
                with self.store.transaction() as tx:
                    tx.connection.execute(sql, prepare=False)

        output = io.StringIO()
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(
            unittest.TestSuite([Mutant(method)])
        )
        print(
            name,
            (
                "DETECTED"
                if len(result.failures) == 1 and not result.errors
                else "UNEXPECTED"
            ),
            flush=True,
        )
        print(output.getvalue(), flush=True)
        if len(result.failures) != 1 or result.errors:
            return 1
    print(
        "4/4 constraint mutants detected by assertion failures, no infrastructure errors"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
