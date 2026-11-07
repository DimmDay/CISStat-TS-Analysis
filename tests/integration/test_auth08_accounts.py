"""AUTH-08 live PostgreSQL: lifecycle/CAS/audit/HTTP; no memory authority."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from tests.integration import test_auth04_sessions as previous

ORIGIN = previous.ORIGIN
from apps.api.authentication.context import resolve_verified_context
from apps.api.authentication.errors import RepositoryConflict, VersionConflict

DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")


@unittest.skipUnless(DSN, "Mandatory runner requires CISSTAT_AUTH_TEST_DSN")
class AccountSQLTests(unittest.TestCase):
    setUp = previous.SessionSQLTests.setUp
    cleanup = previous.SessionSQLTests.cleanup
    login = previous.SessionSQLTests.login
    error = previous.SessionSQLTests.error
    rows = previous.SessionSQLTests.rows

    def lifecycle(self):
        from apps.api.accounts.lifecycle import AccountLifecycle

        return AccountLifecycle(store=self.store, clock=lambda: self.now)

    def current(self):
        with self.store.transaction(readonly=True) as tx:
            return tx.accounts.get(self.account.account_id)

    def change(self, **values):
        from apps.api.accounts.lifecycle import AccountChange

        return self.lifecycle().change(
            self.account.account_id,
            expected_version=self.current().entitlement_version,
            change=AccountChange(**values),
            reason="AUTH-08 test",
        )

    def member_status(self, subject, status):
        return self.lifecycle().membership(
            self.account.account_id,
            subject,
            expected_version=self.current().entitlement_version,
            status=status,
            reason="AUTH-08 test",
        )

    def context(self, token):
        return resolve_verified_context(
            self.service.verify(token, origin=ORIGIN), store=self.store
        )

    def add_member(self):
        # Trusted fixture only. Invitation/seat purchase is AUTH-17/18.
        with self.store.transaction() as tx:
            account = tx.accounts.get(self.account.account_id)
            account = tx.accounts.update(
                account.account_id,
                expected_version=account.entitlement_version,
                account_type="multi",
                seats=2,
            )
            member = tx.identities.create()
            tx.accounts.add_member(
                account.account_id,
                member.subject_id,
                expected_version=account.entitlement_version,
            )
        return member

    def test_plan_change_visible_with_original_sid_and_no_relogin(self):
        token = self.login().token
        self.change(plan="professional")
        self.assertTrue(self.context(token).as_principal().capabilities.can_tune_models)
        first = self.context(token)
        self.change(plan="starter")
        second = self.context(token)
        self.assertFalse(second.as_principal().capabilities.can_tune_models)
        self.assertEqual(first.auth_session_id, second.auth_session_id)
        self.assertGreater(second.entitlement_version, first.entitlement_version)

    def test_actual_me_same_cookie_projects_downgrade(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from apps.api.routers.authentication import router

        app = FastAPI()
        app.state.auth_access_store = self.store
        app.state.auth_session_service = self.service
        app.include_router(router, prefix="/v1/auth")
        token = self.login().token
        client = TestClient(app, base_url=ORIGIN)
        client.cookies.set(
            "__Host-cisstat_auth", token, domain="standalone.example", path="/"
        )
        self.change(plan="professional")
        first = client.get("/v1/auth/me")
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()["capabilities"]["can_tune_models"])
        self.change(plan="demo")
        second = client.get("/v1/auth/me")
        self.assertEqual(second.status_code, 200, second.text)
        self.assertFalse(second.json()["capabilities"]["can_tune_models"])
        self.assertEqual(
            second.json()["auth_session_id"], first.json()["auth_session_id"]
        )
        self.assertGreater(
            second.json()["entitlement_version"], first.json()["entitlement_version"]
        )
        self.assertIn("no-store", second.headers["cache-control"])

    def test_capability_dependency_reads_downgrade_on_next_http_request(self):
        from types import SimpleNamespace

        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from apps.api.auth import require_capability
        from apps.api.authentication.context import VerifiedCredential

        app = FastAPI()
        app.state.auth_access_store = self.store
        evidence = VerifiedCredential(
            subject_id=str(self.owner.subject_id),
            account_id=str(self.account.account_id),
            credential_id="verified-stable-key",
            auth_method="api_key",
        )
        app.state.auth_credential_verifier = SimpleNamespace(
            api_key=lambda key: evidence if key == "test08" else None,
            session=lambda request: None,
        )

        @app.get(
            "/advanced", dependencies=[Depends(require_capability("can_tune_models"))]
        )
        def advanced():
            return {"allowed": True}

        client = TestClient(app)
        self.change(plan="professional")
        self.assertEqual(
            client.get("/advanced", headers={"X-API-Key": "test08"}).status_code, 200
        )
        self.change(plan="starter")
        self.assertEqual(
            client.get(
                "/advanced", headers={"X-API-Key": "test08", "X-Role": "admin"}
            ).status_code,
            403,
        )

    def test_exact_expiry_blocks_session_and_password_login(self):
        token = self.login().token
        self.change(plan_expires_at=self.now + timedelta(seconds=1))
        self.service.verify(token)
        self.now += timedelta(seconds=1)
        self.error(lambda: self.service.verify(token), 403, "account_expired")
        self.error(self.login, 403)

    def test_expired_account_not_in_multi_account_choices(self):
        with self.store.transaction() as tx:
            live = tx.accounts.create(self.owner.subject_id, plan="starter")
        self.change(plan_expires_at=self.now)
        from tests.integration.test_auth04_sessions import PASS

        result = self.service.login("alice04", PASS, origin=ORIGIN)
        self.assertEqual(result.session["account_id"], str(live.account_id))

    def test_expiry_can_be_cleared_explicitly_and_not_reset_by_login(self):
        deadline = self.now + timedelta(days=1)
        self.change(plan_expires_at=deadline)
        self.login()
        self.assertEqual(self.current().plan_expires_at, deadline)
        self.change(plan_expires_at=None)
        self.assertIsNone(self.current().plan_expires_at)

    def test_suspend_resume_does_not_resurrect_old_sid(self):
        token = self.login().token
        self.change(status="suspended")
        self.error(lambda: self.service.verify(token), 401)
        self.change(status="active")
        self.error(lambda: self.service.verify(token), 401)
        self.login()

    def test_closed_terminal_and_no_delete_of_history_or_credentials(self):
        token = self.login().token
        self.change(status="closed")
        with self.assertRaises(RepositoryConflict):
            self.change(status="active")
        self.assertEqual(self.current().status, "closed")
        self.assertEqual(len(self.rows("auth_password_credentials")), 1)
        self.error(lambda: self.service.verify(token), 401)

    def test_mono_to_multi_keeps_ids_and_capacity(self):
        before = self.current()
        after = self.change(account_type="multi")
        self.assertEqual(after.account_type, "multi")
        self.assertEqual(
            (after.account_id, after.tenant_id, after.seats),
            (before.account_id, before.tenant_id, 1),
        )
        self.assertGreater(after.entitlement_version, before.entitlement_version)

    def test_last_owner_cannot_be_revoked_even_when_suspended(self):
        for state in ("active", "suspended"):
            self.change(status=state)
            before = self.current()
            with self.assertRaises(RepositoryConflict):
                self.member_status(self.owner.subject_id, "revoked")
            self.assertEqual(self.current(), before)

    def test_revoke_is_account_scoped_and_restore_does_not_revive_sid(self):
        member = self.add_member()
        from tests.integration.test_auth04_sessions import PASS

        self.service.set_password(member.subject_id, "member08", PASS)
        with self.store.transaction() as tx:
            other = tx.accounts.create(member.subject_id, plan="starter")
        a = self.service.login("member08", PASS, self.account.account_id, origin=ORIGIN)
        b = self.service.login("member08", PASS, other.account_id, origin=ORIGIN)
        self.member_status(member.subject_id, "revoked")
        self.error(lambda: self.service.verify(a.token), 401)
        self.service.verify(b.token)
        self.member_status(member.subject_id, "active")
        self.error(lambda: self.service.verify(a.token), 401)
        self.service.verify(b.token)
        self.service.login("member08", PASS, self.account.account_id, origin=ORIGIN)

    def test_restore_must_respect_seat_capacity(self):
        member = self.add_member()
        self.member_status(member.subject_id, "revoked")
        with self.store.transaction() as tx:
            a = tx.accounts.get(self.account.account_id)
            tx.accounts.update(
                a.account_id, expected_version=a.entitlement_version, seats=1
            )
        with self.assertRaises(RepositoryConflict):
            self.member_status(member.subject_id, "active")

    def test_restore_also_fences_sessions_from_low_level_legacy_revoke(self):
        member = self.add_member()
        self.service.set_password(member.subject_id, "member08", previous.PASS)
        token = self.service.login(
            "member08", previous.PASS, self.account.account_id, origin=ORIGIN
        ).token
        # Prior trusted repository writers did not invalidate auth sessions.
        with self.store.transaction() as tx:
            a = tx.accounts.get(self.account.account_id)
            tx.accounts.update_member(
                a.account_id,
                member.subject_id,
                expected_version=a.entitlement_version,
                status="revoked",
            )
        self.error(lambda: self.service.verify(token), 401)
        self.member_status(member.subject_id, "active")
        self.error(lambda: self.service.verify(token), 401)

    def test_restore_into_mono_cannot_add_second_member(self):
        member = self.add_member()
        self.member_status(member.subject_id, "revoked")
        with self.store.transaction() as tx:
            a = tx.accounts.get(self.account.account_id)
            tx.accounts.update(
                a.account_id,
                expected_version=a.entitlement_version,
                seats=1,
                account_type="mono",
            )
        with self.assertRaises(RepositoryConflict):
            self.member_status(member.subject_id, "active")

    def test_stale_expected_version_rejects_and_leaves_no_intent(self):
        from apps.api.accounts.lifecycle import AccountChange

        before = self.current()
        self.change(plan="starter")
        count = len(self.rows("auth_audit_outbox"))
        with self.assertRaises(VersionConflict):
            self.lifecycle().change(
                before.account_id,
                expected_version=before.entitlement_version,
                change=AccountChange(plan="enterprise"),
                reason="stale",
            )
        self.assertEqual(self.current().plan, "starter")
        self.assertEqual(len(self.rows("auth_audit_outbox")), count)

    def test_two_writers_one_wins_cas(self):
        from threading import Barrier

        from apps.api.accounts.lifecycle import AccountChange

        start = Barrier(2)
        version = self.current().entitlement_version

        def work(plan):
            start.wait(timeout=10)
            try:
                self.lifecycle().change(
                    self.account.account_id,
                    expected_version=version,
                    change=AccountChange(plan=plan),
                    reason="race",
                )
                return "changed"
            except VersionConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(
                list(pool.map(work, ("starter", "professional"))),
                ["changed", "conflict"],
            )

    def test_actual_sql_audit_insert_failure_rolls_back_everything(self):
        token = self.login().token
        before = self.current()
        with self.store.transaction() as tx:
            tx.connection.execute("""CREATE FUNCTION auth08_fault() RETURNS trigger
                LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test audit fault' USING ERRCODE='23514'; END $$""")
            tx.connection.execute("""CREATE TRIGGER auth08_fault BEFORE INSERT ON auth_audit_outbox
                FOR EACH ROW EXECUTE FUNCTION auth08_fault()""")
        with self.assertRaises(RepositoryConflict):
            self.change(status="suspended")
        self.assertEqual(self.current(), before)
        self.service.verify(token)

    def test_expiry_blocks_inflight_mfa_challenge_and_resume_consumes_it(self):
        from apps.api.authentication.mfa import MfaService

        # Existing trusted bootstrap pattern: ADMIN has enrollment permission.
        with self.store.transaction() as tx:
            tx.connection.execute(
                """UPDATE auth_identities SET platform_role='admin',
                subject_version=subject_version+1 WHERE subject_id=%s""",
                (self.owner.subject_id,),
            )
            tx.connection.execute(
                "UPDATE auth_subject_security SET enrollment_allowed=true WHERE subject_id=%s",
                (self.owner.subject_id,),
            )
        challenge = self.login()
        self.change(plan_expires_at=self.now + timedelta(seconds=1))
        self.now += timedelta(seconds=1)
        mfa = MfaService(self.store, clock=lambda: self.now)
        # Must refuse before generating/encrypting a factor (no keyring needed).
        self.error(
            lambda: mfa.begin_enrollment(challenge.token, origin=ORIGIN),
            403,
            "account_expired",
        )
        self.change(plan_expires_at=None)
        self.error(lambda: mfa.begin_enrollment(challenge.token, origin=ORIGIN), 401)

    def test_bound_admin_in_low_plan_has_admin_permission_but_no_tuning(self):
        from apps.api.authentication.context import VerifiedCredential

        with self.store.transaction() as tx:
            tx.connection.execute(
                """UPDATE auth_identities SET platform_role='admin',
                subject_version=subject_version+1 WHERE subject_id=%s""",
                (self.owner.subject_id,),
            )
        self.change(plan="starter")
        ctx = resolve_verified_context(
            VerifiedCredential(
                subject_id=str(self.owner.subject_id),
                account_id=str(self.account.account_id),
                credential_id="server-verified",
                auth_method="api_key",
            ),
            store=self.store,
        )
        self.assertIn("platform.admin", ctx.platform_permissions)
        self.assertFalse(ctx.as_principal().capabilities.can_tune_models)

    def test_suspended_or_expired_account_cannot_restore_membership(self):
        member = self.add_member()
        self.member_status(member.subject_id, "revoked")
        self.change(status="suspended")
        with self.assertRaises(RepositoryConflict):
            self.member_status(member.subject_id, "active")
        self.change(status="active", plan_expires_at=self.now)
        with self.assertRaises(RepositoryConflict):
            self.member_status(member.subject_id, "active")

    def test_audit_failure_rolls_back_account_and_session_revoke(self):
        token = self.login().token
        before = self.current()
        with (
            patch(
                "apps.api.accounts.lifecycle.enqueue_audit",
                side_effect=RuntimeError("fault"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.change(status="suspended")
        self.assertEqual(self.current(), before)
        self.service.verify(token)

    def test_audit_failure_rolls_back_membership_and_sid(self):
        member = self.add_member()
        from tests.integration.test_auth04_sessions import PASS

        self.service.set_password(member.subject_id, "member08", PASS)
        token = self.service.login(
            "member08", PASS, self.account.account_id, origin=ORIGIN
        ).token
        with (
            patch(
                "apps.api.accounts.lifecycle.enqueue_audit",
                side_effect=RuntimeError("fault"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.member_status(member.subject_id, "revoked")
        self.service.verify(token)

    def test_intent_existing_schema_and_noop_does_not_advance_or_audit(self):
        result = self.change(plan="starter")
        intent = self.rows("auth_audit_outbox")[-1]["payload"]
        self.assertEqual(intent["action"], "auth_account_changed")
        self.assertEqual(intent["actor_via"], "operator_cli")
        self.assertEqual(intent["tenant_id"], str(result.tenant_id))
        count = len(self.rows("auth_audit_outbox"))
        self.assertEqual(self.change(plan="starter"), result)
        self.assertEqual(len(self.rows("auth_audit_outbox")), count)

    def test_context_reloaded_in_fresh_process(self):
        import json
        import subprocess
        import sys

        self.change(plan="starter")
        code = """import json,os
from apps.api.authentication.context import VerifiedCredential,resolve_verified_context
from apps.api.authentication.storage import PostgresAccessStore
ctx=resolve_verified_context(VerifiedCredential(subject_id=os.environ['A08_SUBJECT'],account_id=os.environ['A08_ACCOUNT'],credential_id='verified-test',auth_method='api_key'),store=PostgresAccessStore(os.environ['CISSTAT_AUTH_TEST_DSN'],schema=os.environ['A08_SCHEMA']))
print(json.dumps(ctx.as_principal().capabilities.model_dump(mode='json')))
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=False,
            env={
                **os.environ,
                "A08_SUBJECT": str(self.owner.subject_id),
                "A08_ACCOUNT": str(self.account.account_id),
                "A08_SCHEMA": self.schema,
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["can_tune_models"])


if __name__ == "__main__":
    unittest.main()
