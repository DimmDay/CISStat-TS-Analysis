"""AUTH-09 account boundary and compatibility; no DB required."""

import os
import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from apps.api.identity import SubjectRef, authorize_run_access
from apps.api.research_runs import MemoryResearchRunStore, ResearchRun
from apps.api.session_store import AnalysisSession, session_from_dict, session_to_dict


class AccountObjectTests(unittest.TestCase):
    def setUp(self):
        self.account, self.tenant, self.owner = map(str, (uuid4(), uuid4(), uuid4()))
        self.run = ResearchRun(
            run_id="RUN-A0900001",
            session_id="old-pointer",
            owner_subject=self.owner,
            tenant_id=self.tenant,
            ownership="bound",
            owner_account_id=self.account,
            ownership_version=1,
        )
        self.actor = SubjectRef(
            subject_id=str(uuid4()),
            tenant_id=self.tenant,
            account_id=self.account,
            via="auth_session",
            auth_method="auth_session",
            is_authenticated=True,
        )

    def allowed(self, subject=None, **kwargs):
        return authorize_run_access(self.run, subject or self.actor, **kwargs).allowed

    def test_member_not_author(self):
        self.assertNotEqual(self.actor.subject_id, self.run.owner_subject)
        self.assertTrue(self.allowed())
        self.assertTrue(self.allowed(action="write"))

    def test_admin_dev_cannot_bypass(self):
        for actor in (
            replace(self.actor, role="admin", account_id=str(uuid4())),
            replace(self.actor, role="admin", tenant_id=str(uuid4())),
        ):
            with patch(
                "apps.api.identity.get_identity_mode", return_value="dev_single_user"
            ):
                self.assertFalse(self.allowed(actor, session_id="old-pointer"))

    def test_same_person_other_account_cannot_use_creator_cookie(self):
        self.assertFalse(
            self.allowed(
                replace(self.actor, subject_id=self.owner, account_id=str(uuid4())),
                session_id="old-pointer",
            )
        )

    def test_surrogate_unknown_action_and_unauthenticated_deny(self):
        self.assertFalse(
            self.allowed(
                SubjectRef.from_session("old-pointer"), session_id="old-pointer"
            )
        )
        self.assertFalse(self.allowed(action="other"))
        self.assertFalse(self.allowed(replace(self.actor, is_authenticated=False)))

    def test_roundtrip(self):
        self.assertEqual(
            ResearchRun.from_dict(self.run.to_dict()).owner_account_id, self.account
        )
        s = AnalysisSession(
            "pointer",
            owner_subject=self.owner,
            tenant_id=self.tenant,
            owner_account_id=self.account,
        )
        self.assertEqual(
            session_from_dict(session_to_dict(s)).owner_account_id, self.account
        )

    def test_legacy_json_and_malformed_binding(self):
        self.assertIsNone(
            session_from_dict(
                {"session_id": "old", "session_schema_version": 4}
            ).owner_account_id
        )
        for value in ("bad", False, 0):
            r = ResearchRun.from_dict({**self.run.to_dict(), "owner_account_id": value})
            self.assertFalse(
                authorize_run_access(r, self.actor, session_id="old-pointer").allowed
            )

    def test_memory_immutable(self):
        store = MemoryResearchRunStore()
        store.upsert_run(self.run)
        for changes in (
            {"owner_account_id": str(uuid4())},
            {"owner_subject": "rewritten"},
            {"tenant_id": str(uuid4())},
            {"ownership": "unresolved"},
            {"ownership_version": 2},
        ):
            with self.assertRaises(ValueError):
                store.upsert_run(replace(self.run, **changes))

    def test_memory_no_claim(self):
        store = MemoryResearchRunStore()
        store.upsert_run(replace(self.run, owner_account_id=None, ownership_version=0))
        with self.assertRaises(ValueError):
            store.upsert_run(self.run)

    def test_foreign_tenant_legacy_admin_deny(self):
        r = replace(self.run, owner_account_id=None, ownership_version=0)
        self.assertFalse(
            authorize_run_access(
                r, replace(self.actor, role="admin", tenant_id=str(uuid4()))
            ).allowed
        )

    def test_private_legacy_named_read_only(self):
        self.run = replace(self.run, owner_account_id=None, ownership_version=0)
        self.assertFalse(self.allowed())
        self.assertTrue(self.allowed(replace(self.actor, subject_id=self.owner)))
        self.assertFalse(
            self.allowed(replace(self.actor, subject_id=self.owner), action="write")
        )

    def test_operator_and_native_runner_fail_closed(self):
        env = dict(os.environ)
        env.pop("CISSTAT_AUTH_TEST_DSN", None)
        r = subprocess.run(
            [sys.executable, "scripts/auth09/verify_postgres.py"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("disposable", r.stderr)
        r = subprocess.run(
            [
                sys.executable,
                "scripts/auth09/migrate_ownership.py",
                "apply",
                self.run.run_id,
                "--account-id",
                self.account,
            ],
            input="",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("interactive", r.stderr)

    def test_migration_parity_no_mass_backfill(self):
        from apps.api.research_runs import MIGRATION_STATEMENTS_0023

        sql = Path("apps/api/migrations/0023_auth09_account_ownership.sql").read_text()
        for s in MIGRATION_STATEMENTS_0023:
            self.assertIn(" ".join(s.split()), " ".join(sql.split()))
        self.assertEqual(len(MIGRATION_STATEMENTS_0023), 9)
        self.assertNotIn("UPDATE research_runs SET owner_account_id", sql)


if __name__ == "__main__":
    unittest.main()
