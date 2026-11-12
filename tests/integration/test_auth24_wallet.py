"""Native PostgreSQL AUTH-24 wallet READ surface and lifecycle invariants.

Acceptance criterion (spec_auth_architecture.md AUTH-24): OWNER buys, MEMBER
only permittedly spends; expiry/seat/owner change preserve purchased. The
top-up/refund sagas themselves are certified by AUTH-22/23 native suites; the
ledger projection test seeds refund/dispute rows on a real credited order.
"""

import os
import unittest
from datetime import timedelta
from uuid import UUID, uuid4

from apps.api.accounts.team_contract import Convert, SeatRequest, Transfer
from apps.api.billing.refund_migrations import apply_migration as apply_refund
from apps.api.billing.wallet_views import WalletReadService
from tests.integration import test_auth22_topups as topup_previous
from tests.integration import test_auth21_wallet as wallet_module
from tests.integration.test_auth04_sessions import ORIGIN, PASS

DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")
INCLUDED = wallet_module.INCLUDED


@unittest.skipUnless(DSN, "Mandatory runner requires disposable PostgreSQL DSN")
class WalletReadFixture(topup_previous.TopupSQLTests):
    """Wallet fixture + top-up schema + the AUTH-24 read service under test."""

    def setUp(self):
        super().setUp()
        self.reads = WalletReadService(self.store, clock=lambda: self.now)
        # A second personal login of the same OWNER identity (re-login oracle).
        self.owner_token_2 = self.login().token

    def make_member(self):
        """self.other becomes an active MEMBER with an account-bound session."""
        self.accept(self.invite(), token=self.other_token)
        switched = self.team.select(self.other_token, ORIGIN, self.account.account_id)
        return switched.token

    def owner_read(self, token=None):
        return self.reads.wallet(token or self.token, ORIGIN, self.account.account_id)

    def member_read(self, token):
        return self.reads.wallet(token, ORIGIN, self.account.account_id)

    def lots_snapshot(self):
        return [
            {k: v for k, v in row.items()}
            for row in sorted(self.lots(), key=lambda r: str(r["lot_id"]))
        ]

    def set_plan_expiry(self, *, days):
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_accounts SET plan_expires_at=%s,"
                "entitlement_version=entitlement_version+1 WHERE account_id=%s",
                (self.now + timedelta(days=days), self.account.account_id),
            )

    def credited_order(self):
        """Honest saga path: quote -> order -> create payment -> GET-confirmed
        credit (one whole purchased lot bound to the order id)."""
        q = self.quote()
        o = self.order(q)
        self.assertTrue(self.topups.step())
        self.due()
        self.status = "succeeded"
        self.assertTrue(self.topups.step())
        row = self.order_row(o["order_id"])
        self.assertEqual(row["state"], "credited")
        return o


class WalletReadTests(WalletReadFixture):
    # ------------------------------------------------------------- admission

    def test_owner_read_full_member_usage_only(self):
        member_token = self.make_member()
        self.issue_included()
        self.issue_purchased(200_000)
        owner = self.owner_read()
        self.assertIn("sources", owner)
        self.assertIn("locked_reason", owner)
        self.assertEqual(owner["sources"]["included"]["available"], INCLUDED)
        self.assertEqual(owner["sources"]["purchased"]["available"], 200_000)
        self.assertTrue(owner["can_purchase_cu"])
        self.assertTrue(owner["can_spend_cu"])
        member = self.member_read(member_token)
        # §13.8/§12.5 financial privacy: usage facts only, no money.
        for key in ("sources", "locked_reason", "issued", "spent", "expired",
                    "refund_pending", "refunded", "amount_minor", "currency",
                    "price_version", "terms_version", "origin_order"):
            self.assertNotIn(key, member)
        self.assertEqual(member["available"], owner["available"])
        self.assertEqual(member["reserved"], owner["reserved"])
        self.assertEqual(member["next_expiry"], owner["next_expiry"])
        self.assertFalse(member["can_purchase_cu"])
        self.assertTrue(member["can_spend_cu"])

    def test_wallet_summary_parity_with_wallet_service(self):
        self.issue_included()
        self.issue_purchased(150_000)
        self.wallet.refund_hold(
            self.issue_purchased(50_000)["lot_id"], reason="native AUTH24 hold"
        )
        owner = self.owner_read()
        summary = self.wallet.summary(self.account.account_id)
        self.assertEqual(owner["sources"], summary["sources"])
        self.assertEqual(owner["reserved"], summary["reserved"])
        self.assertEqual(owner["next_expiry"], summary["next_expiry"])
        self.assertEqual(owner["status"], summary["status"])

    def test_foreign_identity_and_missing_wallet_refusals(self):
        # self.third has an own starter account without a wallet: reading the
        # shared account is a foreign-object 404, reading the own account is
        # an honest wallet_required (the wallet is operator-provisioned).
        self.error(
            lambda: self.reads.wallet(self.third_token, ORIGIN, self.account.account_id),
            404,
        )
        self.error(
            lambda: self.reads.wallet(
                self.third_token, ORIGIN, self.third_account.account_id
            ),
            403,
            code="wallet_required",
        )

    def test_ledger_is_owner_only_and_safe(self):
        member_token = self.make_member()
        self.issue_included()
        credited = self.credited_order()
        self.error(
            lambda: self.reads.ledger(member_token, ORIGIN, self.account.account_id),
            403,
            code="owner_required",
        )
        lot_id = self.lots()[0]["lot_id"]
        # A real hold movement (the only posting producer in this scenario:
        # lot issuance itself writes no posting row by design).
        self.wallet.refund_hold(lot_id, reason="native AUTH24 owner refund")
        owner_subject = next(
            m["subject_id"]
            for m in self.rows("auth_memberships")
            if str(m["account_id"]) == str(self.account.account_id)
            and m["account_role"] == "owner"
            and m["status"] == "active"
        )
        credited_id = UUID(credited["order_id"])
        with self.store.transaction() as tx:
            c = tx.connection
            # 0035 chains 0019…0035; the AUTH-22 fixture applies only through 0034.
            apply_refund(c)
            c.execute(
                "INSERT INTO auth_refund_orders(refund_id,order_id,account_id,lot_id,"
                "owner_id,units,amount_minor,currency,terms_version,window_days,state,"
                "next_attempt_at,created_at,lease_until,fence) "
                "VALUES (%s,%s,%s,%s,%s,100000000,4900,'RUB','t1',14,'pending',%s,%s,%s,3)",
                (uuid4(), credited_id, self.account.account_id, lot_id, owner_subject,
                 self.now, self.now, self.now),
            )
            c.execute(
                "INSERT INTO auth_disputes(dispute_id,order_id,account_id,lot_id,"
                "spent_units,disputed_units,amount_minor,currency,wallet_was_locked,"
                "state,opened_reason,created_at) "
                "VALUES (%s,%s,%s,%s,45000,55000000,4900,'RUB',true,'open','chargeback',%s)",
                (uuid4(), credited_id, self.account.account_id, lot_id, self.now),
            )
        ledger = self.reads.ledger(self.token, ORIGIN, self.account.account_id)
        self.assertEqual(len(ledger["postings"]), 1)
        self.assertEqual(ledger["postings"][0]["event"], "refund_hold")
        purchased = next(
            row for row in ledger["lots"] if row["source"] == "purchased"
        )
        self.assertEqual(purchased["origin_order"], credited["order_id"])
        self.assertEqual(ledger["orders"][0]["state"], "credited")
        self.assertEqual(ledger["refunds"][0]["amount_minor"], 4900)
        self.assertEqual(ledger["disputes"][0]["disputed_units"], 55000000)
        for row in ledger["refunds"] + ledger["disputes"]:
            for leaked in ("lease_until", "fence", "owner_id"):
                self.assertNotIn(leaked, row)

    # ------------------------------------------------------ lifecycle (§12.5)

    def test_seat_churn_preserves_wallet(self):
        self.issue_included()
        self.issue_purchased(300_000)
        before_read = self.owner_read()
        before_lots = self.lots_snapshot()
        member_token = self.make_member()
        self.command("remove", target=self.other.subject_id)
        self.assertEqual(self.owner_read(), before_read)
        self.assertEqual(self.lots_snapshot(), before_lots)
        # Removal closes the member's account-bound session immediately.
        self.error(lambda: self.member_read(member_token), 401)

    def test_owner_transfer_preserves_wallet_and_switches_projection(self):
        member_token = self.make_member()
        self.issue_purchased(400_000)
        before_read = self.owner_read()
        before_lots = self.lots_snapshot()
        # Transfer invalidates both account-bound sessions (AUTH-17 contract).
        self.command(
            "transfer", self.body(Transfer, target_subject_id=self.other.subject_id)
        )
        self.error(lambda: self.owner_read(), 401)
        # Previous OWNER re-enters and is downgraded to the usage projection.
        owner_token_2 = self.login().token
        old_owner = self.owner_read(token=owner_token_2)
        self.assertNotIn("sources", old_owner)
        self.assertFalse(old_owner["can_purchase_cu"])
        self.assertTrue(old_owner["can_spend_cu"])
        # New OWNER needs a fresh account-bound session; the wallet is intact.
        new_owner_token = self.team.select(
            self.service.login(
                "bob17", PASS, self.other_account.account_id, origin=ORIGIN
            ).token,
            ORIGIN,
            self.account.account_id,
        ).token
        new_owner = self.reads.wallet(new_owner_token, ORIGIN, self.account.account_id)
        self.assertEqual(new_owner["wallet_id"], before_read["wallet_id"])
        self.assertEqual(new_owner["sources"], before_read["sources"])
        self.assertTrue(new_owner["can_purchase_cu"])
        self.assertEqual(self.lots_snapshot(), before_lots)
        self.error(lambda: self.member_read(member_token), 401)

    def test_mono_multi_conversion_preserves_wallet(self):
        req = self.command("seat-request", self.body(SeatRequest, seats=1))
        self.team.confirm_capacity(
            self.account.account_id,
            req["request_id"],
            expected_version=self.current().entitlement_version,
            confirmation_ref="manual:one",
            reason="verified",
        )
        self.issue_purchased(250_000)
        before_read = self.owner_read()
        before_lots = self.lots_snapshot()
        self.command("convert", self.body(Convert, account_type="mono"))
        mid = self.owner_read()
        self.assertEqual(mid["wallet_id"], before_read["wallet_id"])
        self.assertEqual(mid["sources"], before_read["sources"])
        self.assertFalse(mid["can_purchase_cu"], "purchase stays paid-MULTI (AUTH-22)")
        self.assertTrue(mid["can_spend_cu"])
        self.command(
            "convert",
            self.body(Convert, account_type="multi", acknowledge_shared_access=True),
        )
        self.assertEqual(self.owner_read(), before_read)
        self.assertEqual(self.lots_snapshot(), before_lots)

    def test_cycle_rollover_keeps_purchased_and_spent(self):
        """E1 shape at the READ level: a new issuance basis adds a new included
        lot without restoring spent or touching purchased."""
        self.issue_included()
        self.issue_purchased(200_000)
        receipt, run = self.reserve_start(self.req(cu=INCLUDED + 50_000))
        self.ledger.settle(
            receipt.reservation_id,
            expected_version=run.version,
            actual_cu=INCLUDED + 50_000,
        )
        before = self.owner_read()
        self.assertEqual(before["sources"]["included"]["available"], 0)
        self.assertEqual(before["sources"]["purchased"]["available"], 150_000)
        second = self.issue_included(ref="rollover-base")
        after = self.owner_read()
        self.assertEqual(after["sources"]["included"]["available"], second["units"])
        self.assertEqual(
            after["sources"]["included"]["issued"], INCLUDED + second["units"]
        )
        self.assertEqual(after["sources"]["included"]["spent"], INCLUDED)
        self.assertEqual(after["sources"]["purchased"]["available"], 150_000)
        self.assertEqual(after["sources"]["purchased"]["spent"], 50_000)

    def test_expiry_sweep_preserves_purchased(self):
        self.issue_included()
        self.issue_purchased(700_000)
        self.wallet.sweep_expiry(
            limit=100, reason="native AUTH24 sweep", now=self.now + timedelta(days=16)
        )
        view = self.owner_read()
        self.assertEqual(view["sources"]["included"]["available"], 0)
        self.assertEqual(view["sources"]["included"]["expired"], INCLUDED)
        self.assertEqual(view["sources"]["purchased"]["available"], 700_000)
        self.assertIsNone(view["next_expiry"])
        self.assertTrue(view["can_spend_cu"])

    def test_expired_plan_refuses_session_but_preserves_lots(self):
        self.issue_included()
        self.issue_purchased(900_000)
        before_read = self.owner_read()
        before_lots = self.lots_snapshot()
        self.set_plan_expiry(days=-1)
        # AUTH-08 session layer: no live session on an expired plan (the AUTH-24
        # read never weakens this).
        self.error(lambda: self.owner_read(), 403, code="account_expired")
        # §13.3: nothing burned underneath (ledger view, no session involved).
        summary = self.wallet.summary(self.account.account_id)
        self.assertEqual(summary["sources"]["purchased"]["available"], 900_000)
        self.assertEqual(summary["sources"]["included"]["available"], INCLUDED)
        self.set_plan_expiry(days=15)
        self.assertEqual(self.owner_read(), before_read)
        self.assertEqual(self.lots_snapshot(), before_lots)
        self.assertTrue(self.owner_read()["can_spend_cu"])

    def test_relogin_never_creates_a_second_wallet(self):
        self.issue_purchased(100_000)
        first = self.owner_read()
        second = self.owner_read(token=self.owner_token_2)
        self.assertEqual(first["wallet_id"], second["wallet_id"])
        self.assertEqual(
            len(self.rows("auth_wallets")), 1, "re-login must not provision wallets"
        )

    def test_refund_hold_is_visible_in_projection(self):
        lot_id = self.issue_purchased(200_000)["lot_id"]
        member_token = self.make_member()
        self.wallet.refund_hold(lot_id, reason="native AUTH24 owner refund")
        owner = self.owner_read()
        self.assertEqual(owner["sources"]["purchased"]["refund_pending"], 200_000)
        self.assertEqual(owner["sources"]["purchased"]["available"], 0)
        self.assertEqual(owner["available"], 0)
        member = self.member_read(member_token)
        self.assertEqual(member["available"], 0)
        self.assertNotIn("refund_pending", member)
