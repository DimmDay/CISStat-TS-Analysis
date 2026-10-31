"""AUTH-03 persisted context/currentness. Native PostgreSQL required in CI."""

from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from fastapi import HTTPException
from apps.api.authentication.context import VerifiedCredential, resolve_verified_context
from apps.api.authentication.storage import PostgresAccessStore

DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")


@unittest.skipUnless(DSN, "Mandatory runner requires CISSTAT_AUTH_TEST_DSN")
class ContextPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql

        self.pg, self.sql = psycopg, sql
        self.schema = "auth03_" + uuid4().hex
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(
                sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema))
            )
        self.addCleanup(self.cleanup)
        self.store = PostgresAccessStore(DSN, schema=self.schema)
        self.store.migrate()
        with self.store.transaction() as tx:
            self.owner = tx.identities.create()
            self.account = tx.accounts.create(
                self.owner.subject_id, account_type="multi", seats=2, plan="starter"
            )
            self.member = tx.identities.create()
            tx.accounts.add_member(
                self.account.account_id,
                self.member.subject_id,
                expected_version=self.account.entitlement_version,
            )
        self.evidence = VerifiedCredential(
            subject_id=str(self.member.subject_id),
            account_id=str(self.account.account_id),
            credential_id="cred-sql-auth03",
            auth_method="auth_session",
            auth_session_id="as-sql-auth03",
            scopes=frozenset({"documentation.read"}),
            auth_time=datetime.now(timezone.utc),
        )

    def cleanup(self):
        with self.pg.connect(DSN, autocommit=True) as conn:
            conn.execute(
                self.sql.SQL("DROP SCHEMA {} CASCADE").format(
                    self.sql.Identifier(self.schema)
                )
            )

    def resolve(self, evidence=None):
        return resolve_verified_context(
            evidence or self.evidence, store=self.store, request_id="auth03-sql"
        )

    def deny(self, status, code, evidence=None):
        with self.assertRaises(HTTPException) as result:
            self.resolve(evidence)
        self.assertEqual(result.exception.status_code, status)
        self.assertEqual(result.exception.detail["code"], code)

    def test_reads_persisted_identity_account_member_and_updated_version(self):
        first = self.resolve()
        self.assertEqual(first.tenant_id, str(self.account.tenant_id))
        self.assertEqual(first.membership_role, "member")
        self.assertEqual(first.role.value, "external_user")
        self.assertFalse(first.platform_permissions)
        with self.store.transaction() as tx:
            account = tx.accounts.get(self.account.account_id)
            changed = tx.accounts.update(
                account.account_id,
                expected_version=account.entitlement_version,
                plan="demo",
            )
        second = self.resolve()
        self.assertEqual(second.plan.value, "demo")
        self.assertEqual(second.entitlement_version, changed.entitlement_version)
        self.assertGreater(second.entitlement_version, first.entitlement_version)

    def test_membership_revoke_denied_on_next_resolution(self):
        self.resolve()
        with self.store.transaction() as tx:
            account = tx.accounts.get(self.account.account_id)
            tx.accounts.update_member(
                account.account_id,
                self.member.subject_id,
                expected_version=account.entitlement_version,
                status="revoked",
            )
        self.deny(403, "account_access_denied")

    def test_identity_suspend_denied_on_next_resolution(self):
        self.resolve()
        with self.store.transaction() as tx:
            identity = tx.identities.get(self.member.subject_id)
            tx.identities.set_status(
                identity.subject_id,
                "suspended",
                expected_version=identity.subject_version,
            )
        self.deny(401, "invalid_credential")

    def test_account_suspend_and_closed_denied(self):
        for state in ("suspended", "closed"):
            with self.store.transaction() as tx:
                account = tx.accounts.get(self.account.account_id)
                tx.accounts.update(
                    account.account_id,
                    expected_version=account.entitlement_version,
                    status=state,
                )
            self.deny(403, "account_access_denied")

    def test_foreign_and_absent_account_have_same_error(self):
        from dataclasses import replace

        with self.store.transaction() as tx:
            stranger = tx.identities.create()
            foreign = tx.accounts.create(stranger.subject_id)
        self.deny(
            403,
            "account_access_denied",
            replace(self.evidence, account_id=str(foreign.account_id)),
        )
        self.deny(
            403,
            "account_access_denied",
            replace(self.evidence, account_id=str(uuid4())),
        )

    def test_context_and_subject_keep_stable_ids_and_mfa_evidence(self):
        from dataclasses import replace

        when = datetime.now(timezone.utc)
        ctx = self.resolve(replace(self.evidence, mfa_verified_at=when))
        self.assertEqual(ctx.mfa_verified_at, when)
        self.assertEqual(ctx.auth_session_id, "as-sql-auth03")
        self.assertEqual(ctx.as_principal().principal_id, str(self.member.subject_id))
        self.assertEqual(ctx.as_subject().account_id, str(self.account.account_id))
        self.assertTrue(ctx.as_subject().is_authenticated)


if __name__ == "__main__":
    unittest.main()
