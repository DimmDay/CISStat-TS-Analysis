"""Real PG email proof -> finite scopes/wallet -> reservation, no real SMTP."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from apps.api.authentication import personal_demo as P
from apps.api.authentication.context import RequestContext
from apps.api.authentication.personal_demo_migrations import (
    apply_migration,
    check_schema,
)
from apps.api.billing.contract import Admission, Cost
from apps.api.billing.coordinator import ReservationCoordinator
from tests.integration import test_auth19_email_oidc as previous


@unittest.skipUnless(os.environ.get("CISSTAT_AUTH_TEST_DSN"), "disposable PG required")
class PersonalDemoSQLTests(unittest.TestCase):
    def setUp(self):
        self.f = previous.Auth19SQLTests(
            "test_trial_consume_creates_identity_mono_starter_owner"
        )
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.store = self.f.store
        with self.store.transaction() as tx:
            apply_migration(tx.connection)
        self.env = patch.dict(os.environ, {"CISSTAT_PERSONAL_DEMO_ENABLED": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def rows(self, table):
        with self.store.transaction() as tx:
            return tx.connection.execute("SELECT * FROM " + table).fetchall()

    def token(self, email):
        self.f.begin_email(email)
        body = [x for x in self.f.delivery.letters if x["to"] == email][-1]["body"]
        self.assertIn("&return_to=/upload", body)
        return body.split("email_challenge=")[1].split("&")[0]

    def consume(self, token):
        return self.f.email.consume(token=token, origin=previous.previous.ORIGIN)

    def signup(self, email="mono@example.test"):
        return self.consume(self.token(email))

    def context(self, issued):
        e = self.f.email.verify(issued.token)
        with self.store.transaction() as tx:
            a = tx.accounts.get(e.account_id)
            u = tx.identities.get(e.subject_id)
        return RequestContext(
            subject_id=e.subject_id,
            account_id=e.account_id,
            tenant_id=str(a.tenant_id),
            auth_method=e.auth_method,
            auth_session_id=e.auth_session_id,
            subject_version=u.subject_version,
            entitlement_version=a.entitlement_version,
            scopes=e.scopes,
        )

    def req(self, key="trial", cost=1000000):
        return Admission(
            entry_id="api:GET:/v1/internal/rules/templates",
            resource_kind="stateless",
            resource_id="probe",
            idempotency_key=key,
            payload={},
            cost=Cost(micro_cu=cost, version="test-only/1"),
            deadline=self.f.now + timedelta(minutes=1),
        )

    def test_migration_and_atomic_new_owner_ready_for_compute(self):
        with self.store.transaction() as tx:
            self.assertFalse(apply_migration(tx.connection))
            check_schema(tx.connection)
        issued = self.signup()
        ctx = self.context(issued)
        receipts = self.rows("auth_personal_trials")
        self.assertEqual(len(receipts), 1)
        self.assertEqual(len(self.rows("auth_wallets")), 1)
        self.assertEqual(self.rows("auth_wallet_lots")[0]["available"], 100000000)
        ledger = ReservationCoordinator(self.store)
        r = ledger.reserve(ctx, self.req())
        self.assertEqual(
            ledger.reserve(ctx, self.req()).reservation_id, r.reservation_id
        )
        self.assertEqual(self.rows("auth_wallet_lots")[0]["reserved"], 1000000)
        self.assertEqual(len(self.rows("auth_demo_grants")), 0)

    def test_repeat_login_preserves_issued_credit_expiry_and_spend(self):
        first = self.signup()
        ctx = self.context(first)
        ReservationCoordinator(self.store).reserve(ctx, self.req())
        before = self.rows("auth_wallet_lots")
        budget = self.rows("auth_resource_budgets")
        receipts = self.rows("auth_personal_trials")
        self.f.now += timedelta(minutes=2)
        second = self.signup()
        self.assertEqual(self.context(second).subject_id, ctx.subject_id)
        self.assertEqual(self.rows("auth_wallet_lots"), before)
        self.assertEqual(self.rows("auth_resource_budgets"), budget)
        self.assertEqual(self.rows("auth_personal_trials"), receipts)

    def test_credit_and_identity_roll_back_on_mandatory_audit_fault(self):
        token = self.token("fault@example.test")
        with (
            patch(
                "apps.api.billing.wallet._wallet_audit",
                side_effect=RuntimeError("audit fault"),
            ),
            self.assertRaises((RuntimeError, HTTPException)),
        ):
            self.consume(token)
        self.assertFalse(self.rows("auth_personal_trials"))
        self.assertFalse(self.rows("auth_wallets"))
        self.consume(token)
        self.assertEqual(len(self.rows("auth_personal_trials")), 1)

    def test_paused_pool_does_not_create_unfunded_identity(self):
        token = self.token("paused@example.test")
        with self.store.transaction() as tx:
            tx.connection.execute("UPDATE auth_personal_demo_pool SET status='paused'")
        with self.assertRaises(HTTPException):
            self.consume(token)
        self.assertFalse(self.rows("auth_personal_trials"))
        self.assertFalse(self.rows("auth_wallets"))
        with self.store.transaction() as tx:
            self.assertIsNone(
                tx.identities.by_external("cisstat.email/1", "paused@example.test")
            )

    def test_two_registrations_race_for_single_pool_slot(self):
        from apps.api.billing.policy import BudgetPolicy

        policy = BudgetPolicy(self.store)
        sponsor = policy.create_scope(
            "sponsor",
            starts_at=self.f.now,
            ends_at=self.f.now + timedelta(days=44),
            reason="test-only finite pool",
        )
        pid = uuid4()
        with self.store.transaction() as tx:
            tx.connection.execute(
                "INSERT INTO auth_personal_demo_pool(pool_id,sponsor_id,signup_ends_at,max_trials,days,micro_cu,analyses) VALUES (%s,%s,%s,1,14,100000000,10)",
                (pid, sponsor["scope_id"], self.f.now + timedelta(days=30)),
            )
        a = self.token("one@example.test")
        b = self.token("two@example.test")

        def consume(token):
            try:
                self.consume(token)
                return "ok"
            except HTTPException:
                return "denied"

        with patch.object(P, "POOL_ID", pid), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(consume, [a, b]))
        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(len(self.rows("auth_personal_trials")), 1)

    def test_expiry_and_insufficient_cu_are_enforced(self):
        issued = self.signup()
        ctx = self.context(issued)
        with self.assertRaises(HTTPException):
            ReservationCoordinator(self.store).reserve(ctx, self.req(cost=100000001))
        self.f.now += timedelta(days=15)
        with self.assertRaises(HTTPException):
            self.f.email.verify(issued.token)
        with self.assertRaises(HTTPException):
            self.signup()
        self.assertEqual(len(self.rows("auth_wallet_lots")), 1)

    def test_previous_empty_single_owner_can_start_once(self):
        with patch.dict(os.environ, {"CISSTAT_PERSONAL_DEMO_ENABLED": "0"}):
            self.f.begin_email("previous@example.test")
            token = (
                self.f.delivery.letters[-1]["body"]
                .split("email_challenge=")[1]
                .split()[0]
            )
            self.consume(token)
        self.assertFalse(self.rows("auth_wallets"))
        self.signup("previous@example.test")
        self.assertEqual(len(self.rows("auth_personal_trials")), 1)
        self.assertEqual(self.rows("auth_wallet_lots")[0]["available"], 100000000)

    def test_existing_funded_account_is_never_reset_or_adopted(self):
        from apps.api.billing.wallet import WalletService

        with patch.dict(os.environ, {"CISSTAT_PERSONAL_DEMO_ENABLED": "0"}):
            self.f.begin_email("funded@example.test")
            token = (
                self.f.delivery.letters[-1]["body"]
                .split("email_challenge=")[1]
                .split()[0]
            )
            issued = self.consume(token)
        ctx = self.context(issued)
        wallet = WalletService(self.store)
        wallet.create_wallet(ctx.account_id, reason="test managed account")
        wallet.issue_promotional(
            ctx.account_id,
            1,
            origin_ref="test-managed",
            expires_at=self.f.now + timedelta(days=3),
            reason="test managed account",
        )
        before = self.rows("auth_wallet_lots")
        self.signup("funded@example.test")
        self.assertEqual(self.rows("auth_wallet_lots"), before)
        self.assertFalse(self.rows("auth_personal_trials"))

    def _environment_entry(self, use_code):
        """Production creates EmailChallengeService() without an injected store."""
        from apps.api.authentication.email_challenges import EmailChallengeService
        from apps.api.authentication.storage import PostgresAccessStore

        email = "environment-entry@example.test"
        token = self.token(email)
        letter = self.f.delivery.letters[-1]["body"]
        code = letter.splitlines()[0].rsplit(" ", 1)[-1]
        service = EmailChallengeService(clock=lambda: self.f.now)
        self.assertIsNone(service.store)
        # Only route the environment factory to this test's isolated real PG
        # schema. The service itself must resolve the store, just as on the VM.
        with patch.object(PostgresAccessStore, "from_env", return_value=self.store):
            issued = service.consume(
                **({"email": email, "code": code} if use_code else {"token": token}),
                origin=previous.previous.ORIGIN,
            )
            service.verify(issued.token)
            receipt = self.rows("auth_personal_trials")
            self.assertEqual(len(receipt), 1)
            self.assertEqual(len(self.rows("auth_wallets")), 1)
            self.assertEqual(self.rows("auth_wallet_lots")[0]["available"], 100000000)
            self.f.error(lambda: service.consume(token=token, origin=previous.previous.ORIGIN), 401)
            second = service.consume(token=self.token(email), origin=previous.previous.ORIGIN)
            service.verify(second.token)
            self.assertEqual(self.rows("auth_personal_trials"), receipt)
            self.assertEqual(len(self.rows("auth_wallet_lots")), 1)

    def test_environment_store_link_provisions_once(self):
        self._environment_entry(False)

    def test_environment_store_code_provisions_once(self):
        self._environment_entry(True)

    def test_http_environment_entry_sets_cookie_and_confirms_session(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from apps.api.routers.authentication import router
        from apps.api.authentication.storage import PostgresAccessStore

        token = self.token("http-environment@example.test")
        origin = previous.previous.ORIGIN
        app = FastAPI()
        app.include_router(router, prefix="/v1/auth")
        # No auth_access_store or auth_email_service override on app.state.
        with (
            patch.dict(os.environ, {
                "CISSTAT_AUTH_ALLOWED_ORIGINS": origin,
                "CISSTAT_AUTH_CSRF_KEY": "test-csrf-" + "z" * 40,
            }),
            patch.object(PostgresAccessStore, "from_env", return_value=self.store),
            TestClient(app, base_url=origin) as client,
        ):
            proof = client.get("/v1/auth/csrf", headers={"Origin": origin})
            self.assertEqual(proof.status_code, 200, proof.text)
            response = client.post(
                "/v1/auth/email/consume", json={"token": token},
                headers={"Origin": origin, "X-CSRF-Token": proof.json()["csrf_token"]},
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "authenticated")
            self.assertNotIn(token, response.text)
            me = client.get("/v1/auth/me", headers={"Origin": origin})
            self.assertEqual(me.status_code, 200, me.text)
            self.assertEqual(me.json()["account_type"], "mono")
            self.assertEqual(len(self.rows("auth_personal_trials")), 1)
