"""Native PostgreSQL refund/dispute saga: hold exclusivity (E4), unknown
outcome keeps the hold, provider spoof/review, chargeback after spend, debt
exposure without negative available, single resolution, audit rollback. No
simulated SQL, no real merchant/network (MockTransport parity with the
inherited AUTH-18/AUTH-22 fixture)."""

import os
import unittest
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException
from psycopg import errors as pg_errors

from apps.api.billing.refund_contract import RefundRequest
from apps.api.billing.refund_migrations import (
    VERSION as REFUND_VERSION,
    apply_migration as apply_refund,
    check_schema,
)
from apps.api.billing.refunds import RefundService
from apps.api.billing.topup_contract import TopupOrder, TopupQuote
from apps.api.billing.topup_migrations import (
    apply_migration as apply_topup,
)
from apps.api.billing.topups import TopupService
from apps.api.billing.wallet import WalletError
from tests.integration import test_auth17_team as team_previous
from tests.integration import test_auth18_saga as previous
from tests.integration import test_auth21_wallet as wallet_previous
from tests.integration.test_auth04_sessions import ORIGIN, PASS

DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")


@unittest.skipUnless(DSN, "Mandatory runner requires disposable PostgreSQL DSN")
class RefundSQLTests(wallet_previous.WalletFixture):
    """Wallet fixture (paid MULTI, budgets) + topup/refund schema and saga."""

    http = previous.SagaSQLTests.http
    invite = team_previous.TeamSQLTests.invite
    accept = team_previous.TeamSQLTests.accept

    def due(self, minutes=2):
        self.now += timedelta(minutes=minutes)

    def setUp(self):
        self.refund_id = "refund-23"
        self.refund_status = "pending"
        self.refund_payment_id = None
        self.refund_calls = []
        super().setUp()
        self.payment_id = "payment-22"
        with self.store.transaction() as tx:
            apply_topup(tx.connection)
            apply_refund(tx.connection)
        self.topups = TopupService(self.store, lambda: self.now, self.gateway)
        self.refunds = RefundService(self.store, lambda: self.now, self.gateway)
        self.wallet.create_wallet(self.account.account_id, reason="native AUTH23 wallet")
        self.package = self.topups.provision_package(
            title="100 CU",
            units=100_000_000,
            price_minor=4900,
            currency="RUB",
            price_version="fixture-price",
            terms_version="fixture-terms",
            reason="native AUTH23 catalog",
        )["package_id"]

    def http(self, r):
        print("HTTP", r.method, r.url.path, file=__import__("sys").stderr)
        if r.url.path.startswith("/v3/refunds"):
            self.refund_calls.append(r)
            if self.outage:
                return httpx.Response(500)
            import json

            if r.method == "POST":
                self.refund_created = json.loads(r.content)
                self.refund_key = r.headers["Idempotence-Key"]
            return httpx.Response(
                200,
                json={
                    "id": self.refund_id,
                    "payment_id": self.refund_payment_id or self.payment_id,
                    "status": self.refund_status,
                    "amount": self.refund_created["amount"],
                    "test": True,
                },
            )
        return previous.SagaSQLTests.http(self, r)

    def tbody(self, cls, **kw):
        base = {
            "expected_version": self.current().entitlement_version,
            "reason": "native AUTH23",
            "idempotency_key": uuid4().hex,
        }
        base.update(kw)
        return cls(**base)

    def credited_order(self):
        q = self.topups.quote(
            self.token,
            ORIGIN,
            self.account.account_id,
            self.tbody(TopupQuote, package_id=UUID(self.package)),
        )
        o = self.topups.confirm(
            self.token,
            ORIGIN,
            self.account.account_id,
            self.tbody(
                TopupOrder,
                quote_id=UUID(q["quote_id"]),
                quote_digest=q["digest"],
            ),
        )
        self.assertTrue(self.topups.step())  # create payment
        self.due()
        self.status = "succeeded"
        self.assertTrue(self.topups.step())  # GET-confirmed proof -> credited
        self.assertEqual(self.order_row(o["order_id"])["state"], "credited")
        self.status = "pending"
        return o

    def order_row(self, order_id):
        with self.store.transaction(readonly=True) as tx:
            return tx.connection.execute(
                "SELECT * FROM auth_topup_orders WHERE order_id=%s",
                (UUID(order_id) if isinstance(order_id, str) else order_id,),
            ).fetchone()

    def refund_row(self, refund_id):
        with self.store.transaction(readonly=True) as tx:
            return tx.connection.execute(
                "SELECT * FROM auth_refund_orders WHERE refund_id=%s",
                (UUID(refund_id) if isinstance(refund_id, str) else refund_id,),
            ).fetchone()

    def dispute_row(self, dispute_id):
        with self.store.transaction(readonly=True) as tx:
            return tx.connection.execute(
                "SELECT * FROM auth_disputes WHERE dispute_id=%s",
                (UUID(dispute_id) if isinstance(dispute_id, str) else dispute_id,),
            ).fetchone()

    def lot(self):
        with self.store.transaction(readonly=True) as tx:
            return tx.connection.execute(
                "SELECT * FROM auth_wallet_lots WHERE account_id=%s AND source='purchased' ORDER BY lot_id LIMIT 1",
                (self.account.account_id,),
            ).fetchone()

    def wallet_row(self):
        with self.store.transaction(readonly=True) as tx:
            return tx.connection.execute(
                "SELECT wallet_id,version,status FROM auth_wallets WHERE account_id=%s",
                (self.account.account_id,),
            ).fetchone()

    def request_refund(self, o, **kw):
        return self.refunds.request(
            self.token,
            ORIGIN,
            self.account.account_id,
            UUID(o["order_id"]),
            self.tbody(RefundRequest, order_id=UUID(o["order_id"]), **kw),
        )

    def raw(self):
        import psycopg

        return psycopg.connect(
            DSN, options="-c search_path=" + self.store.schema + ",pg_catalog"
        )

    # ------------------------------------------------------------- migration

    def test_migration_repeat_check_and_guards(self):
        with self.store.transaction() as tx:
            self.assertFalse(apply_refund(tx.connection))
            check_schema(tx.connection)
        o = self.credited_order()
        r = self.request_refund(o)
        with self.raw() as conn:
            with self.assertRaises(pg_errors.CheckViolation):
                with conn.transaction():
                    conn.execute(
                        "DELETE FROM auth_refund_orders WHERE refund_id=%s",
                        (UUID(r["refund_id"]),),
                    )
            conn.rollback()
            with self.assertRaises(pg_errors.CheckViolation):
                with conn.transaction():
                    conn.execute(
                        "UPDATE auth_refund_orders SET units=5 WHERE refund_id=%s",
                        (UUID(r["refund_id"]),),
                    )
            conn.rollback()
        self.assertEqual(REFUND_VERSION, "0035_auth23_refunds")

    # --------------------------------------------------------------- happy path

    def test_owner_refund_extinguishes_whole_unused_lot(self):
        o = self.credited_order()
        r = self.request_refund(o)
        self.assertEqual(r["state"], "pending")
        lot = self.lot()
        self.assertEqual(int(lot["available"]), 0)
        self.assertEqual(int(lot["refund_pending"]), 100_000_000)
        again = self.request_refund(o, reason="repeated click")
        self.assertEqual(again["refund_id"], r["refund_id"])
        with self.store.transaction(readonly=True) as tx:
            self.assertEqual(
                tx.connection.execute(
                    "SELECT count(*) AS n FROM auth_refund_orders"
                ).fetchone()["n"],
                1,
            )
        self.assertTrue(self.refunds.step())  # create refund (Idempotence-Key=refund_id)
        self.assertEqual(self.refund_key, r["refund_id"])
        self.assertEqual(self.refund_row(r["refund_id"])["provider_refund_id"], "refund-23")
        self.refund_status = "succeeded"
        self.due(minutes=2)
        self.assertTrue(self.refunds.step())  # GET-confirmed proof -> refunded
        row = self.refund_row(r["refund_id"])
        self.assertEqual(row["state"], "refunded")
        self.assertIsNotNone(row["decided_at"])
        lot = self.lot()
        self.assertEqual(int(lot["refund_pending"]), 0)
        self.assertEqual(int(lot["refunded"]), 100_000_000)
        self.assertEqual(int(lot["available"]), 0)
        self.assertFalse(self.refunds.step())

    def test_spoofed_refund_payment_parks_review_and_hold_survives(self):
        o = self.credited_order()
        r = self.request_refund(o)
        self.refund_payment_id = "payment-OTHER"
        self.assertTrue(self.refunds.step())
        self.assertEqual(self.refund_row(r["refund_id"])["state"], "review_required")
        lot = self.lot()
        self.assertEqual(int(lot["refund_pending"]), 100_000_000)
        with self.assertRaises(ValueError):
            self.refunds.reconcile(UUID(r["order_id"]), reason="wrong id")
        self.refunds.reconcile(r["refund_id"], reason="native AUTH23 reconcile")
        self.assertEqual(self.refund_row(r["refund_id"])["state"], "pending")
        self.refund_payment_id = None
        self.refund_status = "succeeded"
        self.assertTrue(self.refunds.step())
        self.assertEqual(self.refund_row(r["refund_id"])["state"], "refunded")

    def test_unknown_outcome_keeps_hold_and_backs_off(self):
        o = self.credited_order()
        r = self.request_refund(o)
        self.outage = True
        self.assertTrue(self.refunds.step())
        row = self.refund_row(r["refund_id"])
        self.assertEqual(row["state"], "pending")
        self.assertIsNone(row["provider_refund_id"])
        self.assertGreater(row["next_attempt_at"], self.now)
        lot = self.lot()
        self.assertEqual(int(lot["refund_pending"]), 100_000_000)
        self.outage = False
        self.refund_status = "succeeded"
        self.due(minutes=16)
        self.assertTrue(self.refunds.step())
        self.assertEqual(self.refund_row(r["refund_id"])["state"], "refunded")

    def test_canceled_refund_unlocks_lot_exactly_once(self):
        o = self.credited_order()
        r = self.request_refund(o)
        self.refund_status = "canceled"
        self.assertTrue(self.refunds.step())
        self.assertEqual(self.refund_row(r["refund_id"])["state"], "failed")
        lot = self.lot()
        self.assertEqual(int(lot["available"]), 100_000_000)
        self.assertEqual(int(lot["refund_pending"]), 0)
        self.due()
        self.assertFalse(self.refunds.step())
        self.assertEqual(int(self.lot()["available"]), 100_000_000)

    def test_spend_after_hold_is_refused(self):
        o = self.credited_order()
        self.request_refund(o)
        with self.assertRaises(HTTPException) as ctx:
            self.ledger.reserve(self.api, self.req(cu=10))
        self.assertEqual(ctx.exception.status_code, 402)

    # ------------------------------------------------------------- eligibility

    def test_window_and_state_gates(self):
        o = self.credited_order()
        with patch.dict(os.environ, {"CISSTAT_TOPUP_REFUND_DAYS": "0"}):
            self.now += timedelta(seconds=1)
            with self.assertRaises(HTTPException) as ctx:
                self.request_refund(o)
            self.assertEqual(ctx.exception.detail["code"], "refund_window")
        # A pending (not credited) order is never refundable; the 0034 guard
        # forbids flipping credited back, so a fresh unstepped order is used.
        q = self.topups.quote(
            self.token,
            ORIGIN,
            self.account.account_id,
            self.tbody(TopupQuote, package_id=UUID(self.package)),
        )
        o2 = self.topups.confirm(
            self.token,
            ORIGIN,
            self.account.account_id,
            self.tbody(
                TopupOrder,
                quote_id=UUID(q["quote_id"]),
                quote_digest=q["digest"],
            ),
        )
        with self.assertRaises(HTTPException) as ctx:
            self.request_refund(o2)
        self.assertEqual(ctx.exception.detail["code"], "refund_not_eligible")

    def test_member_and_foreign_account_denied(self):
        o = self.credited_order()
        inv = self.invite()
        self.accept(inv)
        issued = self.team.select(self.other_token, ORIGIN, self.account.account_id)
        with self.assertRaises(HTTPException) as ctx:
            self.refunds.request(
                issued.token,
                ORIGIN,
                self.account.account_id,
                UUID(o["order_id"]),
                self.tbody(RefundRequest, order_id=UUID(o["order_id"])),
            )
        self.assertEqual(ctx.exception.detail["code"], "owner_required")
        with self.assertRaises(HTTPException) as ctx:
            self.refunds.refund_get(
                self.token, ORIGIN, self.account.account_id, uuid4()
            )
        self.assertEqual(ctx.exception.detail["code"], "refund_not_found")

    def test_audit_fault_rolls_back_hold(self):
        from apps.api.authentication.context import AuthHTTPException

        o = self.credited_order()
        with patch(
            "apps.api.billing.refunds.audit",
            side_effect=RuntimeError("audit unavailable"),
        ):
            # The HTTP boundary converts the fault into a safe 503; the
            # transaction still rolls back completely (hold included).
            with self.assertRaises(AuthHTTPException):
                self.request_refund(o)
        lot = self.lot()
        self.assertEqual(int(lot["available"]), 100_000_000)
        self.assertEqual(int(lot["refund_pending"]), 0)
        with self.store.transaction(readonly=True) as tx:
            self.assertEqual(
                tx.connection.execute(
                    "SELECT count(*) AS n FROM auth_refund_orders"
                ).fetchone()["n"],
                0,
            )
        r = self.request_refund(o)
        self.assertEqual(r["state"], "pending")

    # ---------------------------------------------------------------- disputes

    def spend_part(self, cu, actual):
        """FEFO spend through the AUTH-12 coordinator (real reservations).

        The reservation pins exactly what settles, so spent>0 and the
        unreserved remainder stays available for the dispute hold."""
        receipt = self.ledger.reserve(self.api, self.req(cu=cu))
        run = self.ledger.start(
            self.api, receipt.reservation_id, expected_version=receipt.version
        )
        self.ledger.settle(
            receipt.reservation_id,
            expected_version=run.version,
            actual_cu=actual,
        )

    def test_chargeback_after_spend_lost_extinguishes_and_keeps_lock(self):
        o = self.credited_order()
        self.spend_part(30_000_000, 30_000_000)
        lot = self.lot()
        self.assertEqual(int(lot["spent"]), 30_000_000)
        self.assertEqual(int(lot["available"]), 70_000_000)
        d = self.refunds.dispute_open(o["order_id"], reason="native AUTH23 chargeback")
        self.assertEqual(d["spent_units"], 30_000_000)
        self.assertEqual(d["disputed_units"], 70_000_000)
        self.assertEqual(self.wallet_row()["status"], "locked")
        lot = self.lot()
        self.assertEqual(int(lot["refund_pending"]), 70_000_000)
        self.assertEqual(int(lot["available"]), 0)
        with self.assertRaises(HTTPException) as ctx:
            self.request_refund(o)
        self.assertEqual(ctx.exception.detail["code"], "refund_not_eligible")
        with self.assertRaises(ValueError):
            self.refunds.dispute_open(o["order_id"], reason="double dispute")
        with self.assertRaises(HTTPException) as ctx:
            self.spend_part(10, 10)
        self.assertIn(ctx.exception.status_code, (402, 403))
        self.refunds.dispute_resolve(d["dispute_id"], "lost", reason="bank ruled")
        lot = self.lot()
        self.assertEqual(int(lot["refunded"]), 70_000_000)
        self.assertEqual(int(lot["refund_pending"]), 0)
        self.assertEqual(int(lot["available"]), 0)
        self.assertEqual(self.dispute_row(d["dispute_id"])["state"], "lost")
        self.assertEqual(self.wallet_row()["status"], "locked")
        with self.raw() as conn:
            with self.assertRaises(pg_errors.CheckViolation):
                with conn.transaction():
                    conn.execute("DELETE FROM auth_disputes")
            conn.rollback()
        with self.assertRaises(ValueError):
            self.refunds.dispute_resolve(d["dispute_id"], "won", reason="flip")

    def test_chargeback_won_unlocks_exactly_once(self):
        o = self.credited_order()
        self.spend_part(30_000_000, 30_000_000)
        d = self.refunds.dispute_open(o["order_id"], reason="native AUTH23 chargeback")
        self.refunds.dispute_resolve(d["dispute_id"], "won", reason="bank reversed")
        lot = self.lot()
        self.assertEqual(int(lot["available"]), 70_000_000)
        self.assertEqual(int(lot["refund_pending"]), 0)
        self.assertEqual(self.wallet_row()["status"], "active")
        self.assertEqual(self.dispute_row(d["dispute_id"])["state"], "won")
        with self.assertRaises(ValueError):
            self.refunds.dispute_resolve(d["dispute_id"], "lost", reason="flip")
        self.assertEqual(int(self.lot()["available"]), 70_000_000)

    def test_refund_and_dispute_are_mutually_exclusive(self):
        o = self.credited_order()
        r = self.request_refund(o)
        with self.assertRaises(ValueError):
            self.refunds.dispute_open(o["order_id"], reason="after refund request")
        self.refund_status = "canceled"
        self.assertTrue(self.refunds.step())
        self.assertEqual(self.refund_row(r["refund_id"])["state"], "failed")
        d = self.refunds.dispute_open(o["order_id"], reason="dispute after failed refund")
        self.assertEqual(d["disputed_units"], 100_000_000)
        with self.store.transaction(readonly=True) as tx:
            self.assertEqual(
                tx.connection.execute(
                    "SELECT count(*) AS n FROM auth_disputes"
                ).fetchone()["n"],
                1,
            )
