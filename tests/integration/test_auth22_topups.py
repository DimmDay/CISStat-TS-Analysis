"""Native PostgreSQL top-up saga: E3 duplicates, callback spoof, currency
tamper, out-of-order events, quote expiry, wallet locked paid_review, audit
rollback. No simulated SQL, no real merchant/network (MockTransport parity
with the inherited AUTH-18 fixture)."""

import os
import unittest
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import HTTPException
from psycopg import errors as pg_errors

from apps.api.billing.topup_contract import TopupOrder, TopupQuote
from apps.api.billing.topup_migrations import (
    VERSION as TOPUP_VERSION,
    apply_migration as apply_topup,
    check_schema,
)
from apps.api.billing.topups import TopupService
from tests.integration import test_auth17_team as team_previous
from tests.integration import test_auth18_saga as previous
from tests.integration import test_auth21_wallet as wallet_previous
from tests.integration.test_auth04_sessions import ORIGIN, PASS

DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")


@unittest.skipUnless(DSN, "Mandatory runner requires disposable PostgreSQL DSN")
class TopupSQLTests(wallet_previous.WalletFixture):
    """Wallet fixture (paid MULTI, budgets) + topup schema, catalog, saga."""

    # The saga needs the amount-echoing provider mock of AUTH-18 (the wallet
    # fixture stubs a fixed amount that validate() would rightly reject).
    http = previous.SagaSQLTests.http
    invite = team_previous.TeamSQLTests.invite
    accept = team_previous.TeamSQLTests.accept

    def due(self, minutes=2):
        self.now += timedelta(minutes=minutes)

    def setUp(self):
        super().setUp()
        self.payment_id = "payment-22"
        self.status = "pending"
        with self.store.transaction() as tx:
            apply_topup(tx.connection)
        self.topups = TopupService(self.store, lambda: self.now, self.gateway)
        self.wallet.create_wallet(self.account.account_id, reason="native AUTH22 wallet")
        self.package = self.topups.provision_package(
            title="100 CU",
            units=100_000_000,
            price_minor=4900,
            currency="RUB",
            price_version="fixture-price",
            terms_version="fixture-terms",
            reason="native AUTH22 catalog",
        )["package_id"]

    def tbody(self, cls, **kw):
        base = {
            "expected_version": self.current().entitlement_version,
            "reason": "native AUTH22",
            "idempotency_key": uuid4().hex,
        }
        base.update(kw)
        return cls(**base)

    def quote(self, **kw):
        return self.topups.quote(
            self.token,
            ORIGIN,
            self.account.account_id,
            self.tbody(TopupQuote, package_id=UUID(self.package), **kw),
        )

    def order(self, q=None):
        q = q or self.quote()
        return self.topups.confirm(
            self.token,
            ORIGIN,
            self.account.account_id,
            self.tbody(TopupOrder, quote_id=UUID(q["quote_id"]), quote_digest=q["digest"]),
        )

    def lots(self):
        with self.store.transaction(readonly=True) as tx:
            return tx.connection.execute(
                "SELECT * FROM auth_wallet_lots WHERE account_id=%s AND source='purchased' ORDER BY lot_id",
                (self.account.account_id,),
            ).fetchall()

    def order_row(self, order_id):
        with self.store.transaction(readonly=True) as tx:
            return tx.connection.execute(
                "SELECT * FROM auth_topup_orders WHERE order_id=%s",
                (UUID(order_id) if isinstance(order_id, str) else order_id,),
            ).fetchone()

    def wallet_row(self):
        with self.store.transaction(readonly=True) as tx:
            return tx.connection.execute(
                "SELECT wallet_id,version,status FROM auth_wallets WHERE account_id=%s",
                (self.account.account_id,),
            ).fetchone()

    # ------------------------------------------------------------- migration

    def raw(self):
        """Direct connection for SQL-guard oracles (no store translation)."""
        import psycopg

        return psycopg.connect(
            DSN, options="-c search_path=" + self.store.schema + ",pg_catalog"
        )

    def test_migration_repeat_check_and_guards(self):
        self.quote()
        with self.store.transaction() as tx:
            self.assertFalse(apply_topup(tx.connection))
            check_schema(tx.connection)
        with self.raw() as conn:
            with self.assertRaises(pg_errors.CheckViolation):
                with conn.transaction():
                    conn.execute("DELETE FROM auth_topup_quotes")
            conn.rollback()
            with self.assertRaises(pg_errors.CheckViolation):
                with conn.transaction():
                    conn.execute(
                        "UPDATE auth_topup_packages SET price_minor=1 WHERE package_id=%s",
                        (UUID(self.package),),
                    )
            conn.rollback()
        # The only allowed package UPDATE is the enable->disable flip.
        self.topups.disable_package(self.package, reason="catalog replaced")
        with self.raw() as conn:
            with self.assertRaises(pg_errors.CheckViolation):
                with conn.transaction():
                    conn.execute(
                        "UPDATE auth_topup_packages SET enabled=true WHERE package_id=%s",
                        (UUID(self.package),),
                    )
            conn.rollback()
        with self.assertRaises(ValueError):
            self.topups.disable_package(
                self.package, reason="second disable must fail"
            )

    # ------------------------------------------------------------ happy path

    def test_confirmed_payment_credits_exactly_once(self):
        q = self.quote()
        o = self.order(q)
        self.assertEqual(o["state"], "pending")
        self.assertIsNone(o["checkout_url"])
        self.assertTrue(self.topups.step())  # create payment (Idempotence-Key=order)
        row = self.order_row(o["order_id"])
        self.assertEqual(row["state"], "pending")
        self.assertTrue(row["checkout_url"])
        self.assertEqual(row["payment_id"], self.payment_id)
        # Repeated worker step before any event: bounded, no duplicate POST proof.
        self.due()
        self.status = "succeeded"
        self.assertTrue(self.topups.step())  # GET-confirmed proof -> credited
        row = self.order_row(o["order_id"])
        self.assertEqual(row["state"], "credited")
        self.assertIsNotNone(row["credited_at"])
        lots = self.lots()
        self.assertEqual(len(lots), 1)
        self.assertEqual(int(lots[0]["issued"]), 100_000_000)
        self.assertEqual(lots[0]["origin_order"], o["order_id"])
        self.assertIsNone(lots[0]["expires_at"])
        # E5: entitlement/membership untouched by the purchase.
        self.assertEqual(self.current().seats, 2)
        # Terminal order is never claimed again; no second lot (E6).
        self.assertFalse(self.topups.step())
        self.assertEqual(len(self.lots()), 1)

    def test_duplicate_events_and_two_event_ids_credit_once(self):
        o = self.order()
        self.topups.step()
        self.due()
        self.status = "succeeded"
        # Same payment, two different event ids (E3): both only wake up.
        for event in ("payment.succeeded", "payment.waiting_for_capture"):
            self.topups.notify(self.payment_id, event, None)
        self.assertTrue(self.topups.step())
        self.assertEqual(len(self.lots()), 1)
        self.assertEqual(self.order_row(o["order_id"])["state"], "credited")
        # Replayed notify after the terminal state changes nothing.
        self.topups.notify(self.payment_id, "payment.succeeded", None)
        self.assertEqual(len(self.lots()), 1)
        self.assertEqual(self.order_row(o["order_id"])["state"], "credited")

    def test_notify_wakeup_alone_never_credits(self):
        o = self.order()
        # Callback spoof: a "succeeded" notification with no API proof at all.
        self.topups.notify(self.payment_id, "payment.succeeded", None)
        self.assertEqual(len(self.lots()), 0)
        self.assertEqual(self.order_row(o["order_id"])["state"], "pending")

    # -------------------------------------------------- tamper / spoof / ooo

    def test_amount_tamper_goes_to_review_without_credit(self):
        o = self.order()
        self.topups.step()  # honest create binds the exact snapshot amount
        self.bad = True  # provider echoes a tampered amount for the next GET
        self.due()
        self.status = "succeeded"
        self.assertTrue(self.topups.step())
        row = self.order_row(o["order_id"])
        self.assertEqual(row["state"], "review_required")
        self.assertEqual(len(self.lots()), 0)

    def test_out_of_order_canceled_after_credited_is_rejected(self):
        o = self.order()
        self.topups.step()
        self.due()
        self.status = "succeeded"
        self.topups.step()
        self.assertEqual(self.order_row(o["order_id"])["state"], "credited")
        with self.raw() as conn:
            with self.assertRaises(pg_errors.CheckViolation):
                with conn.transaction():
                    conn.execute(
                        "UPDATE auth_topup_orders SET state='pending' WHERE order_id=%s",
                        (UUID(o["order_id"]),),
                    )
            conn.rollback()
            with self.assertRaises(pg_errors.CheckViolation):
                with conn.transaction():
                    conn.execute(
                        "DELETE FROM auth_topup_orders WHERE order_id=%s",
                        (UUID(o["order_id"]),),
                    )
            conn.rollback()

    def test_quote_expiry_blocks_new_order_not_the_running_one(self):
        q = self.quote()
        o = self.order(q)
        self.topups.step()
        fresh = self.quote()  # created now; TTL 15 minutes
        self.due(minutes=10)
        self.topups.show(self.token, ORIGIN, self.account.account_id)  # keep idle fresh
        self.due(minutes=6)  # 16 total: the quote is expired, the session is not
        # Fresh login: _fresh() requires recent authentication for confirm.
        self.token = self.login().token
        with self.assertRaises(HTTPException) as ctx:
            self.topups.confirm(
                self.token,
                ORIGIN,
                self.account.account_id,
                self.tbody(
                    TopupOrder,
                    quote_id=UUID(fresh["quote_id"]),
                    quote_digest=fresh["digest"],
                ),
            )
        self.assertEqual(ctx.exception.status_code, 409)
        self.due()
        self.status = "succeeded"
        self.assertTrue(self.topups.step())
        self.assertEqual(self.order_row(o["order_id"])["state"], "credited")

    def test_idempotent_confirm_and_key_conflict(self):
        q1 = self.quote()
        body = self.tbody(
            TopupOrder, quote_id=UUID(q1["quote_id"]), quote_digest=q1["digest"]
        )
        first = self.topups.confirm(self.token, ORIGIN, self.account.account_id, body)
        again = self.topups.confirm(self.token, ORIGIN, self.account.account_id, body)
        self.assertEqual(first["order_id"], again["order_id"])
        # Same idempotency key, different payload on a fresh quote -> 409 (13.4.1).
        q2 = self.quote()
        other = self.tbody(
            TopupOrder,
            quote_id=UUID(q2["quote_id"]),
            quote_digest=q2["digest"],
            reason="a different confirmation reason",
        )
        other.idempotency_key = body.idempotency_key
        with self.assertRaises(HTTPException) as ctx:
            self.topups.confirm(self.token, ORIGIN, self.account.account_id, other)
        self.assertEqual(ctx.exception.status_code, 409)

    # ------------------------------------------------------------- admission

    def test_member_cannot_purchase(self):
        inv = self.invite()
        self.accept(inv)
        # Foreign current account: no cross-account catalog leakage.
        with self.assertRaises(HTTPException) as ctx:
            self.topups.show(self.other_token, ORIGIN, self.account.account_id)
        self.assertEqual(ctx.exception.status_code, 404)
        # Member with the account selected: OWNER-only refusal (13.3).
        issued = self.team.select(self.other_token, ORIGIN, self.account.account_id)
        with self.assertRaises(HTTPException) as ctx:
            self.topups.show(issued.token, ORIGIN, self.account.account_id)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail.get("code"), "owner_required")

    def test_missing_wallet_blocks_checkout_catalog_still_visible(self):
        other, other_account, _ = self.person("no-wallet-22")
        with self.store.transaction() as tx:
            tx.accounts.update(
                other_account.account_id,
                expected_version=other_account.entitlement_version,
                account_type="multi",
                plan="starter",
                seats=1,
            )
        token = self.service.login(
            "no-wallet-22", PASS, other_account.account_id, origin=ORIGIN
        ).token
        view = self.topups.show(token, ORIGIN, other_account.account_id)
        self.assertTrue(view["packages"])
        self.assertEqual(view["orders"], [])
        with self.assertRaises(HTTPException) as ctx:
            self.topups.quote(
                token,
                ORIGIN,
                other_account.account_id,
                self.tbody(TopupQuote, package_id=UUID(self.package)),
            )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail.get("code"), "wallet_required")

    # --------------------------------------------------- wallet locked credit

    def test_locked_wallet_parks_paid_review_then_operator_credit(self):
        o = self.order()
        self.topups.step()
        row = self.wallet_row()
        self.wallet.set_status(
            row["wallet_id"],
            expected_version=row["version"],
            status="locked",
            reason="finance hold before credit",
        )
        self.due()
        self.status = "succeeded"
        self.assertTrue(self.topups.step())
        paid = self.order_row(o["order_id"])
        self.assertEqual(paid["state"], "paid_review")
        self.assertEqual(paid["payment_id"], self.payment_id)
        self.assertEqual(len(self.lots()), 0)
        # Operator resolution: unlock, manual whole-lot credit, CAS transition.
        row = self.wallet_row()
        self.wallet.set_status(
            row["wallet_id"],
            expected_version=row["version"],
            status="active",
            reason="finance hold released",
        )
        self.wallet.issue_purchased(
            self.account.account_id,
            int(paid["units"]),
            origin_order=str(paid["order_id"]),
            reason="manual credit for reviewed top-up",
        )
        out = self.topups.credit_paid(paid["order_id"], reason="operator resolution")
        self.assertEqual(out["state"], "credited")
        self.assertEqual(len(self.lots()), 1)
        # The unique basis rejects a second credit for the same order (E6).
        with self.assertRaises(Exception):
            self.wallet.issue_purchased(
                self.account.account_id,
                int(paid["units"]),
                origin_order=str(paid["order_id"]),
                reason="duplicate basis must fail",
            )
        self.assertEqual(len(self.lots()), 1)

    # -------------------------------------------------------- outage / retry

    def test_outage_retry_keeps_single_payment_and_lot(self):
        self.outage = True
        o = self.order()
        self.assertTrue(self.topups.step())  # outage -> durable retry
        self.assertEqual(self.order_row(o["order_id"])["state"], "pending")
        self.due()
        self.outage = False
        self.topups.step()  # create with the same Idempotence-Key
        self.due()
        self.status = "succeeded"
        self.topups.step()
        self.assertEqual(self.order_row(o["order_id"])["state"], "credited")
        self.assertEqual(len(self.lots()), 1)

    def test_no_candidate_fifteen_minutes_review(self):
        o = self.order()
        self.due(minutes=16)
        self.assertTrue(self.topups.step())
        self.assertEqual(self.order_row(o["order_id"])["state"], "review_required")

    def test_reconcile_requires_bound_payment_and_proof(self):
        o = self.order()
        self.topups.step()  # create -> payment bound to the order
        # A foreign payment reference cannot be attached to a bound order.
        with self.assertRaises(ValueError):
            self.topups.reconcile(
                o["order_id"], "payment-foreign", reason="native AUTH22 reconcile"
            )
        out = self.topups.reconcile(
            o["order_id"], self.payment_id, reason="native AUTH22 reconcile"
        )
        self.assertTrue(out["queued"])
        self.due()
        self.status = "succeeded"
        self.assertTrue(self.topups.step())  # fetch the bound payment
        self.assertEqual(self.order_row(o["order_id"])["state"], "credited")
        self.assertEqual(len(self.lots()), 1)

    # ------------------------------------------------------------ rate limit

    def test_quote_rate_limit(self):
        for _ in range(32):
            self.quote()
        with self.assertRaises(HTTPException) as ctx:
            self.quote()
        self.assertEqual(ctx.exception.status_code, 429)

    # ----------------------------------------------------------- audit fault

    def test_audit_fault_rolls_back_credit(self):
        o = self.order()
        self.topups.step()
        self.due()
        self.status = "succeeded"
        with patch(
            "apps.api.billing.topups.audit",
            side_effect=RuntimeError("audit unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                self.topups.step()
        self.assertEqual(len(self.lots()), 0)
        self.assertEqual(self.order_row(o["order_id"])["state"], "pending")
        # The crashed attempt keeps its lease; the fence expires before retry.
        self.due(minutes=1)
        self.assertTrue(self.topups.step())
        self.assertEqual(self.order_row(o["order_id"])["state"], "credited")
        self.assertEqual(len(self.lots()), 1)

    # ------------------------------------------------------ package disable

    def test_package_disable_does_not_kill_running_orders(self):
        q = self.quote()
        o = self.order(q)
        self.topups.disable_package(self.package, reason="catalog replaced")
        self.topups.step()
        self.due()
        self.status = "succeeded"
        self.topups.step()
        self.assertEqual(self.order_row(o["order_id"])["state"], "credited")
        self.assertEqual(len(self.lots()), 1)
        # Disabled packages no longer quote.
        with self.assertRaises(HTTPException) as ctx:
            self.quote()
        self.assertEqual(ctx.exception.detail.get("code"), "topup_package_not_found")

    def test_schema_version_recorded(self):
        with self.store.transaction(readonly=True) as tx:
            row = tx.connection.execute(
                "SELECT checksum FROM auth_schema_versions WHERE version=%s",
                (TOPUP_VERSION,),
            ).fetchone()
        self.assertTrue(row)
