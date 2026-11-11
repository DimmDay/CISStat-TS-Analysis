"""Native PostgreSQL wallet flows: FEFO, expiry, pinned allocations, races,
refund transitions, duplicate-credit guards, audit rollback. No simulated SQL.

The inherited AUTH-18 fixture already provisions a cycle
(included_per_seat=1_000_000, seats=2), so the formula-pinned included lot of
these tests is exactly 2_000_000 micro-CU — the amount is never client-supplied.
"""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from psycopg import errors as pg_errors

from apps.api.authentication.api_key_contract import IssueKeyBody
from apps.api.authentication.api_keys import APIKeyService
from apps.api.authentication.context import RequestContext
from apps.api.billing.contract import Admission, Cost
from apps.api.billing.coordinator import ReservationCoordinator
from apps.api.billing.policy import BudgetPolicy
from apps.api.billing.wallet import WalletService
from apps.api.billing.wallet_migrations import (
    VERSION as WALLET_VERSION,
    apply_migration as apply_wallet,
    check_schema,
)
from tests.integration import test_auth18_saga as previous

DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")
INCLUDED = 2_000_000


@unittest.skipUnless(DSN, "Mandatory runner requires disposable PostgreSQL DSN")
class WalletFixture(unittest.TestCase):
    """Shared fixture: paid MULTI account, budgets, API key; wallet optional."""

    cleanup = previous.SagaSQLTests.cleanup
    login = previous.SagaSQLTests.login
    error = previous.SagaSQLTests.error
    rows = previous.SagaSQLTests.rows
    person = previous.SagaSQLTests.person
    current = previous.SagaSQLTests.current
    body = previous.SagaSQLTests.body
    command = previous.SagaSQLTests.command

    def setUp(self):
        self.calls = []
        self.status = "pending"
        self.payment_id = "payment-21"
        previous.SagaSQLTests.setUp(self)
        with self.store.transaction() as tx:
            # Deployment-order parity: applying 0033 chains 0019…0032 first.
            apply_wallet(tx.connection)
        self.ledger = ReservationCoordinator(self.store)
        self.wallet = WalletService(self.store)
        self.policy = BudgetPolicy(self.store)
        self.keys = APIKeyService(self.store)
        issued = self.keys.issue(
            self.token,
            IssueKeyBody(
                label="wallet test",
                scopes=["api.read", "api.compute", "api.write", "api.database"],
                expires_in_days=1,
            ),
            origin=previous.ORIGIN,
        )
        self.api = self.context(self.keys.verify(issued.secret))
        self.policy.create_scope(
            "account", account_id=self.account.account_id, reason="native AUTH21"
        )
        self.policy.set_budget(
            self.account.account_id, "cu", limit_units=2**40, reason="native AUTH21"
        )
        self.policy.set_budget(
            self.account.account_id,
            "concurrency",
            limit_units=4,
            reason="native AUTH21",
        )

    def http(self, r):
        # The wallet tests never drive the provider saga; a bounded stub keeps
        # the inherited fixture's MockTransport contract satisfied.
        import httpx

        self.calls.append(r)
        if r.url.path == "/v3/me":
            return httpx.Response(
                200,
                json={"account_id": "test-shop", "test": True, "status": "enabled"},
            )
        payload = {
            "id": self.payment_id,
            "status": self.status,
            "paid": self.status == "succeeded",
            "test": True,
            "recipient": {"account_id": "test-shop"},
            "amount": {"value": "1.00", "currency": "RUB"},
            "metadata": {"order_id": str(uuid4())},
            "confirmation": {
                "type": "redirect",
                "confirmation_url": "https://yoomoney.ru/checkout/payments/v2/contract",
            },
        }
        return httpx.Response(200, json=payload)

    def context(self, e):
        with self.store.transaction(readonly=True) as tx:
            a = tx.accounts.get(e.account_id)
            u = tx.identities.get(e.subject_id)
        return RequestContext(
            subject_id=e.subject_id,
            account_id=e.account_id,
            tenant_id=str(a.tenant_id),
            auth_method=e.auth_method,
            credential_id=e.credential_id,
            auth_session_id=e.auth_session_id,
            subject_version=u.subject_version,
            entitlement_version=a.entitlement_version,
            scopes=e.scopes,
            request_id="native21",
        )

    def req(self, key=None, *, cu=0, entry="api:GET:/v1/public/rules/templates"):
        return Admission(
            entry_id=entry,
            idempotency_key=key or str(uuid4()),
            resource_kind="stateless",
            resource_id="wallet-input",
            payload={"n": 80},
            cost=Cost(micro_cu=cu, version="test-only/1"),
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            slots=1 if cu else 0,
        )

    def cycle_id(self):
        return self.rows("auth_billing_cycles")[0]["cycle_id"]

    def issue_included(self, *, ref="base"):
        return self.wallet.issue_included_for_cycle(
            self.account.account_id, self.cycle_id(), ref=ref, reason="native AUTH21"
        )

    def issue_purchased(self, units, order=None):
        return self.wallet.issue_purchased(
            self.account.account_id,
            units,
            origin_order=order or ("order-" + uuid4().hex[:8]),
            reason="native AUTH21",
        )

    def lots(self):
        return self.rows("auth_wallet_lots")

    def lot(self, lot_id):
        for row in self.lots():
            if str(row["lot_id"]) == str(lot_id):
                return row
        raise AssertionError("lot not found")

    def summary(self):
        return self.wallet.summary(self.account.account_id)

    def wallet_row(self):
        return self.rows("auth_wallets")[0]

    def reserve_start(self, admission):
        receipt = self.ledger.reserve(self.api, admission)
        run = self.ledger.start(
            self.api, receipt.reservation_id, expected_version=receipt.version
        )
        return receipt, run


@unittest.skipUnless(DSN, "Mandatory runner requires disposable PostgreSQL DSN")
class WalletSQLTests(WalletFixture):
    """Wallet-provisioned flows (operator provisioning happened in setUp)."""

    def setUp(self):
        super().setUp()
        self.wallet.create_wallet(self.account.account_id, reason="native AUTH21")

    def test_migration_apply_repeat_checksum_and_guards(self):
        with self.store.transaction() as tx:
            self.assertFalse(apply_wallet(tx.connection))
            check_schema(tx.connection)
        self.assertEqual(self.issue_included()["units"], INCLUDED)
        # Unique issuance basis: a second 'base' lot for the same cycle is refused.
        with self.assertRaises(Exception):
            self.issue_included()
        with self.store.transaction() as tx:
            c = tx.connection
            with self.assertRaises(pg_errors.UniqueViolation):
                c.execute(
                    "INSERT INTO auth_wallet_lots(lot_id,wallet_id,account_id,source,issued,available,expires_at,origin_cycle,origin_ref,created_at) "
                    "SELECT %s,wallet_id,account_id,'included',10,10,expires_at,origin_cycle,origin_ref,created_at FROM auth_wallet_lots LIMIT 1",
                    (uuid4(),),
                )
        lot_id = self.issue_purchased(50)["lot_id"]
        with self.store.transaction() as tx:
            with self.assertRaises(Exception):
                tx.connection.execute(
                    "UPDATE auth_wallet_lots SET available=available+1 WHERE lot_id=%s",
                    (lot_id,),
                )
            with self.assertRaises(Exception):
                tx.connection.execute(
                    "DELETE FROM auth_wallet_lots WHERE lot_id=%s", (lot_id,)
                )
            with self.assertRaises(Exception):
                tx.connection.execute(
                    "UPDATE auth_wallet_postings SET spent_delta=0 WHERE lot_id=%s",
                    (lot_id,),
                )

    def test_e1_fefo_included_before_purchased(self):
        self.issue_included()
        self.issue_purchased(200_000)
        receipt, run = self.reserve_start(self.req(cu=2_050_000))
        self.ledger.settle(
            receipt.reservation_id,
            expected_version=run.version,
            actual_cu=2_050_000,
        )
        s = self.summary()
        self.assertEqual(s["sources"]["included"]["available"], 0)
        self.assertEqual(s["sources"]["included"]["spent"], INCLUDED)
        self.assertEqual(s["sources"]["purchased"]["available"], 150_000)
        self.assertEqual(s["sources"]["purchased"]["spent"], 50_000)
        self.assertEqual(s["reserved"], 0)

    def test_fefo_order_included_promotional_purchased(self):
        self.issue_purchased(100, order="order-endless")
        self.wallet.issue_promotional(
            self.account.account_id,
            100,
            origin_ref="promo-tie",
            expires_at=None,
            reason="native AUTH21",
        )
        self.issue_included()
        receipt, run = self.reserve_start(self.req(cu=INCLUDED + 200))
        self.ledger.settle(
            receipt.reservation_id,
            expected_version=run.version,
            actual_cu=INCLUDED + 200,
        )
        s = self.summary()
        self.assertEqual(s["sources"]["included"]["spent"], INCLUDED)
        self.assertEqual(s["sources"]["promotional"]["spent"], 100)
        self.assertEqual(s["sources"]["purchased"]["spent"], 100)
        self.assertEqual(s["sources"]["purchased"]["available"], 0)

    def test_insufficient_and_concurrent_race_for_last_units(self):
        self.issue_included()
        with self.assertRaises(HTTPException) as ctx:
            self.ledger.reserve(self.api, self.req(cu=INCLUDED + 1))
        self.assertEqual(ctx.exception.status_code, 402)
        self.assertEqual(ctx.exception.detail["code"], "cu_insufficient")
        self.assertEqual(ctx.exception.detail["required"], INCLUDED + 1)
        self.assertEqual(ctx.exception.detail["available"], INCLUDED)
        first, first_run = self.reserve_start(self.req(cu=INCLUDED - 10))
        barrier = Barrier(2)

        def call(_):
            barrier.wait()
            try:
                self.ledger.reserve(self.api, self.req(cu=10))
                return "reserved"
            except HTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(call, range(2)))
        self.assertEqual(outcomes.count("reserved"), 1)
        self.assertIn(402, outcomes)
        self.ledger.settle(
            first.reservation_id,
            expected_version=first_run.version,
            actual_cu=INCLUDED - 10,
        )

    def test_release_after_sweep_never_revives(self):
        issued = self.issue_included()
        receipt = self.ledger.reserve(self.api, self.req(cu=30))
        # Operator drill: the cycle ends today for the unreserved remainder.
        self.wallet.sweep_expiry(
            reason="cycle ended drill", now=self.now + timedelta(days=16)
        )
        row = self.lot(issued["lot_id"])
        self.assertEqual(row["available"], 0)
        self.assertEqual(row["expired"], INCLUDED - 30)
        self.assertEqual(row["reserved"], 30)
        self.ledger.release(
            receipt.reservation_id, expected_version=receipt.version
        )
        row = self.lot(issued["lot_id"])
        self.assertEqual(row["available"], 0)
        self.assertEqual(row["expired"], INCLUDED)
        self.assertEqual(row["reserved"], 0)
        self.assertEqual(self.summary()["reserved"], 0)

    def test_settle_into_swept_lot_uses_pinned(self):
        issued = self.issue_included()
        receipt, run = self.reserve_start(self.req(cu=40))
        self.wallet.sweep_expiry(
            reason="cycle ended drill", now=self.now + timedelta(days=16)
        )
        # Settle spends the pinned allocation even after the sweep (design D6).
        self.ledger.settle(
            receipt.reservation_id,
            expected_version=run.version,
            actual_cu=40,
        )
        row = self.lot(issued["lot_id"])
        self.assertEqual(row["spent"], 40)
        self.assertEqual(row["expired"], INCLUDED - 40)
        self.assertEqual(row["reserved"], 0)

    def test_extend_pins_delta_and_settles(self):
        self.issue_included()
        receipt, run = self.reserve_start(self.req(cu=40))
        extended = self.ledger.extend(
            self.api,
            receipt.reservation_id,
            expected_version=run.version,
            additional_cu=30,
        )
        allocations = self.rows("auth_reservation_lot_allocations")
        self.assertEqual(sum(row["units"] for row in allocations), 70)
        self.ledger.settle(
            receipt.reservation_id,
            expected_version=extended.version,
            actual_cu=70,
        )
        self.assertEqual(self.summary()["reserved"], 0)

    def test_locked_wallet_blocks_new_reservations(self):
        self.issue_included()
        wallet_row = self.wallet_row()
        self.wallet.set_status(
            wallet_row["wallet_id"],
            expected_version=wallet_row["version"],
            status="locked",
            reason="dispute drill",
        )
        with self.assertRaises(HTTPException) as ctx:
            self.ledger.reserve(self.api, self.req(cu=10))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail["code"], "wallet_locked")
        self.wallet.set_status(
            wallet_row["wallet_id"],
            expected_version=wallet_row["version"] + 1,
            status="active",
            reason="resolved",
        )
        receipt = self.ledger.reserve(self.api, self.req(cu=10))
        self.ledger.release(receipt.reservation_id, expected_version=receipt.version)

    def test_refund_hold_excludes_from_fefo_and_races(self):
        purchased = self.issue_purchased(100)
        lot_id = purchased["lot_id"]
        self.wallet.refund_hold(lot_id, reason="whole unused lot")
        row = self.lot(lot_id)
        self.assertEqual(row["refund_pending"], 100)
        self.assertEqual(row["available"], 0)
        # refund_pending units cannot be reserved (E4); the included lot backs
        # a smaller reservation instead.
        self.issue_included()
        receipt = self.ledger.reserve(self.api, self.req(cu=10))
        self.ledger.release(receipt.reservation_id, expected_version=receipt.version)
        # Exhaust the included lot, so the next reservation pins the purchased
        # lot and the refund race becomes exclusive (E4).
        receipt, run = self.reserve_start(self.req(cu=INCLUDED))
        self.ledger.settle(
            receipt.reservation_id,
            expected_version=run.version,
            actual_cu=INCLUDED,
        )
        other = self.issue_purchased(50)
        receipt = self.ledger.reserve(self.api, self.req(cu=50))
        with self.assertRaises(HTTPException) as ctx:
            self.wallet.refund_hold(other["lot_id"], reason="too late")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "refund_not_eligible")
        self.ledger.release(receipt.reservation_id, expected_version=receipt.version)
        # Provider refused: the hold releases back to available.
        self.wallet.refund_failed(lot_id, reason="provider refused")
        self.assertEqual(self.lot(lot_id)["available"], 100)
        self.wallet.refund_hold(lot_id, reason="retry")
        self.wallet.refund_confirmed(lot_id, reason="provider refund done")
        row = self.lot(lot_id)
        self.assertEqual(row["refunded"], 100)
        self.assertEqual(row["available"], 0)
        self.assertEqual(row["refund_pending"], 0)

    def test_duplicate_credit_guards(self):
        order = "order-dup"
        self.issue_purchased(100, order=order)
        with self.assertRaises(Exception):
            self.issue_purchased(100, order=order)
        self.issue_included()
        with self.assertRaises(Exception):
            self.issue_included()
        result = self.wallet.sweep_expiry(reason="nothing to sweep")
        self.assertEqual(result["lots"], 0)

    def test_sweep_expires_only_available_and_is_idempotent(self):
        issued = self.issue_included()
        receipt, run = self.reserve_start(self.req(cu=INCLUDED - 70))
        result = self.wallet.sweep_expiry(
            reason="cycle ended drill", now=self.now + timedelta(days=16)
        )
        self.assertEqual(result["lots"], 1)
        row = self.lot(issued["lot_id"])
        self.assertEqual(row["available"], 0)
        self.assertEqual(row["expired"], 70)
        self.assertEqual(row["reserved"], INCLUDED - 70)
        self.assertEqual(self.wallet.sweep_expiry(reason="repeat")["lots"], 0)
        self.ledger.settle(
            receipt.reservation_id,
            expected_version=run.version,
            actual_cu=INCLUDED - 70,
        )

    def test_zero_cost_reservations_touch_no_lots(self):
        self.issue_included()
        receipt = self.ledger.reserve(self.api, self.req(cu=0))
        rows = [
            row
            for row in self.rows("auth_wallet_postings")
            if row["reservation_id"] == receipt.reservation_id
        ]
        self.assertEqual(rows, [])

    def test_audit_fault_rolls_back_issuance(self):
        from apps.api.billing import wallet as wallet_module

        def broken(*a, **k):
            raise RuntimeError("audit outage drill")

        with patch.object(wallet_module, "audit", broken):
            with self.assertRaises(RuntimeError):
                self.issue_purchased(100)
        self.assertEqual(
            [row for row in self.lots() if row["source"] == "purchased"], []
        )

    def test_wallet_create_refuses_duplicates_and_demo_plan(self):
        with self.assertRaises(Exception):
            self.wallet.create_wallet(self.account.account_id, reason="duplicate")
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_accounts SET plan='demo',entitlement_version=entitlement_version+1 WHERE account_id=%s",
                (self.account.account_id,),
            )
        fresh = WalletService(self.store)
        with self.assertRaises(Exception):
            fresh.create_wallet(self.account.account_id, reason="demo refused")

    def test_summary_shape_and_version(self):
        self.issue_included()
        self.issue_purchased(50)
        s = self.summary()
        self.assertEqual(s["status"], "active")
        self.assertEqual(s["schema_version"], WALLET_VERSION)
        self.assertEqual(s["sources"]["included"]["issued"], INCLUDED)
        self.assertEqual(s["sources"]["purchased"]["issued"], 50)
        self.assertIsNotNone(s["next_expiry"])
        self.assertEqual(s["reserved"], 0)


@unittest.skipUnless(DSN, "Mandatory runner requires disposable PostgreSQL DSN")
class NoWalletSQLTests(WalletFixture):
    """Additive boundary D1: without provisioning, nothing changes for an Account."""

    def test_no_wallet_account_is_untouched(self):
        receipt = self.ledger.reserve(self.api, self.req(cu=500))
        self.assertEqual(self.rows("auth_wallet_lots"), [])
        self.assertEqual(self.rows("auth_reservation_lot_allocations"), [])
        self.assertIsNone(self.summary())
        run = self.ledger.start(
            self.api, receipt.reservation_id, expected_version=receipt.version
        )
        self.ledger.settle(
            receipt.reservation_id,
            expected_version=run.version,
            actual_cu=500,
        )

    def test_extend_pins_whole_hold_after_late_provisioning(self):
        receipt = self.ledger.reserve(self.api, self.req(cu=40))
        self.assertEqual(self.rows("auth_reservation_lot_allocations"), [])
        self.wallet.create_wallet(self.account.account_id, reason="late provisioning")
        self.issue_included()
        run = self.ledger.start(
            self.api, receipt.reservation_id, expected_version=receipt.version
        )
        extended = self.ledger.extend(
            self.api,
            receipt.reservation_id,
            expected_version=run.version,
            additional_cu=30,
        )
        self.ledger.settle(
            receipt.reservation_id,
            expected_version=extended.version,
            actual_cu=70,
        )
        allocations = self.rows("auth_reservation_lot_allocations")
        self.assertEqual(sum(row["units"] for row in allocations), 70)


if __name__ == "__main__":
    unittest.main()
