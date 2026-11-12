"""AUTH-24 wallet READ contracts without a database: OWNER/member projections,
financial privacy, lifecycle flags, bounded ledger view. Native PostgreSQL
flows live in tests/integration/test_auth24_wallet.py.

Normative rules: spec_billing_accounts.md §13.3/13.6/13.8, spec_auth_architecture.md
§12.2/§12.3/§12.5 (AUTH-24): OWNER buys, MEMBER only permittedly spends; prices and
money documents never reach MEMBER; expired subscription preserves purchased and
reports the reason."""

import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from apps.api.authentication.context import _MESSAGES

NOW = datetime(2026, 11, 12, 12, 0, 0, tzinfo=UTC)


def lot(source, *, issued=1000, available=None, reserved=0, spent=0, expired=0,
        refund_pending=0, refunded=0, expires_at=None, origin_order="", origin_ref=""):
    return {
        "lot_id": str(uuid4()),
        "wallet_id": "w",
        "account_id": "a",
        "source": source,
        "issued": issued if available is None else issued,
        "available": issued if available is None else available,
        "reserved": reserved,
        "spent": spent,
        "expired": expired,
        "refund_pending": refund_pending,
        "refunded": refunded,
        "expires_at": expires_at,
        "origin_cycle": None if origin_order else uuid4(),
        "origin_order": origin_order or None,
        "origin_ref": origin_ref or None,
        "created_at": NOW,
    }


class MemberPrivacyTests(unittest.TestCase):
    """§13.8: MEMBER sees permitted usage facts only; §12.2: prices and money
    documents are OWNER-side."""

    def wallet_view(self, rows, *, is_owner=False, account_active=True):
        from apps.api.billing.wallet_views import wallet_view

        return wallet_view(
            {"account_type": "multi", "plan": "professional",
             "plan_expires_at": NOW + timedelta(days=30), "status": "active"},
            {"wallet_id": "11111111-1111-1111-1111-111111111111", "status": "active",
             "locked_reason": None},
            rows,
            is_owner=is_owner,
            account_active=account_active,
            now=NOW,
        )

    def test_member_projection_is_usage_only(self):
        rows = [
            lot("included", expires_at=NOW + timedelta(days=20)),
            lot("purchased", origin_order="order-1"),
        ]
        view = self.wallet_view(rows, is_owner=False)
        self.assertEqual(view["wallet_id"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(view["available"], 2000)
        self.assertEqual(view["reserved"], 0)
        self.assertEqual(view["next_expiry"], (NOW + timedelta(days=20)).isoformat())
        self.assertTrue(view["can_spend_cu"])
        self.assertFalse(view["can_purchase_cu"])
        self.assertTrue(view["account_active"])
        self.assertIsNone(view["spending_blocked_reason"])
        # Financial privacy: no per-source breakdown, no history, no operator
        # reason, no money. The projection carries usage facts only.
        for key in ("sources", "issued", "spent", "expired", "refund_pending",
                    "refunded", "locked_reason", "amount_minor", "currency",
                    "price_version", "terms_version", "origin_order"):
            self.assertNotIn(key, view)

    def test_owner_projection_has_breakdown_and_flags(self):
        rows = [
            lot("included", issued=500, available=300, spent=200,
                expires_at=NOW + timedelta(days=10)),
            lot("purchased", issued=200, origin_order="order-1"),
        ]
        view = self.wallet_view(rows, is_owner=True)
        self.assertEqual(view["sources"]["included"]["available"], 300)
        self.assertEqual(view["sources"]["included"]["spent"], 200)
        self.assertEqual(view["sources"]["purchased"]["available"], 200)
        self.assertEqual(view["sources"]["promotional"]["available"], 0)
        self.assertEqual(view["available"], 500)
        self.assertEqual(view["next_expiry"], (NOW + timedelta(days=10)).isoformat())
        self.assertTrue(view["can_purchase_cu"])
        self.assertTrue(view["can_spend_cu"])
        self.assertIn("locked_reason", view)
        # Still no money in the wallet projection: money lives in the ledger.
        for key in ("amount_minor", "currency", "price_version", "terms_version"):
            self.assertNotIn(key, view)

    def test_owner_sees_refund_pending_in_projection(self):
        rows = [lot("purchased", issued=200, available=0, refund_pending=200,
                    origin_order="order-1")]
        view = self.wallet_view(rows, is_owner=True)
        self.assertEqual(view["sources"]["purchased"]["refund_pending"], 200)
        self.assertEqual(view["available"], 0)

    def test_member_and_owner_agree_on_usage_totals(self):
        rows = [
            lot("included", available=300, reserved=100),
            lot("purchased", available=500),
        ]
        member = self.wallet_view(rows, is_owner=False)
        owner = self.wallet_view(rows, is_owner=True)
        for key in ("available", "reserved", "next_expiry", "account_active"):
            self.assertEqual(member[key], owner[key])
        self.assertEqual(member["wallet_id"], owner["wallet_id"])


class LifecycleFlagTests(unittest.TestCase):
    """§13.3: can_purchase_cu/can_spend_cu are server-computed effective
    permissions; expired subscription preserves the balance and reports why."""

    def wallet_view(self, *, is_owner=False, account_active=True, wallet_status="active",
                    account_type="multi", plan="professional"):
        from apps.api.billing.wallet_views import wallet_view

        return wallet_view(
            {"account_type": account_type, "plan": plan,
             "plan_expires_at": NOW + timedelta(days=30) if account_active else NOW - timedelta(days=1),
             "status": "active"},
            {"wallet_id": "w", "status": wallet_status, "locked_reason": "dispute"},
            [lot("purchased", issued=200, origin_order="order-1")],
            is_owner=is_owner,
            account_active=account_active,
            now=NOW,
        )

    def test_member_cannot_purchase_even_on_paid_multi(self):
        view = self.wallet_view(is_owner=False)
        self.assertFalse(view["can_purchase_cu"])
        self.assertTrue(view["can_spend_cu"])

    def test_mono_owner_reads_wallet_but_cannot_purchase(self):
        # AUTH-21 provisions wallets on any personal paid account; purchase
        # stays a paid-MULTI capability (AUTH-22 _topup_account parity).
        view = self.wallet_view(is_owner=True, account_type="mono")
        self.assertTrue(view["can_spend_cu"])
        self.assertFalse(view["can_purchase_cu"])

    def test_locked_wallet_blocks_spend_with_reason(self):
        view = self.wallet_view(wallet_status="locked")
        self.assertFalse(view["can_spend_cu"])
        self.assertFalse(view["can_purchase_cu"])
        self.assertEqual(view["spending_blocked_reason"], "wallet_locked")
        self.assertEqual(view["status"], "locked")
        self.assertEqual(view["available"], 200)  # preserved, not burned

    def test_expired_subscription_preserves_balance_and_reports_reason(self):
        # View-contract (defense-in-depth): production sessions on an expired
        # plan are refused earlier by the AUTH-08 session layer (403
        # account_expired, pinned natively). The projection still knows how to
        # report the preserved balance with the reason instead of inventing a
        # spendable state.
        view = self.wallet_view(account_active=False)
        self.assertFalse(view["account_active"])
        self.assertEqual(view["spending_blocked_reason"], "account_expired")
        self.assertFalse(view["can_spend_cu"])
        self.assertFalse(view["can_purchase_cu"])
        self.assertEqual(view["available"], 200)

    def test_demo_and_internal_accounts_cannot_purchase(self):
        for plan in ("demo", "internal"):
            view = self.wallet_view(is_owner=True, plan=plan)
            self.assertFalse(view["can_purchase_cu"])


class LedgerViewTests(unittest.TestCase):
    """D5: OWNER-only bounded journal, safe projections, no lease/fence."""

    def ledger_view(self):
        from apps.api.billing.wallet_views import ledger_view

        postings = [
            {"posting_id": str(uuid4()), "lot_id": "l1", "reservation_id": None,
             "event": "settle", "available_delta": 0, "reserved_delta": -45,
             "spent_delta": 45, "expired_delta": 0, "refund_pending_delta": 0,
             "refunded_delta": 0, "created_at": NOW},
            {"posting_id": str(uuid4()), "lot_id": "l1", "reservation_id": "r1",
             "event": "reserve", "available_delta": -60, "reserved_delta": 60,
             "spent_delta": 0, "expired_delta": 0, "refund_pending_delta": 0,
             "refunded_delta": 0, "created_at": NOW - timedelta(minutes=5)},
        ]
        lots = [lot("purchased", issued=200, spent=45, origin_order="order-1")]
        orders = [{"order_id": "order-1", "state": "credited", "units": 200,
                   "checkout_url": None, "payment_id": "payment-22",
                   "credited_at": NOW - timedelta(days=1)}]
        refunds = [{"refund_id": "r", "order_id": "order-1", "state": "pending",
                    "units": 155, "amount_minor": 4900, "currency": "RUB",
                    "terms_version": "t1", "provider_refund_id": None,
                    "lease_until": NOW, "fence": 3, "owner_id": "someone",
                    "created_at": NOW, "decided_at": None}]
        disputes = [{"dispute_id": "d", "order_id": "order-1", "state": "open",
                     "spent_units": 45, "disputed_units": 155, "amount_minor": 4900,
                     "currency": "RUB", "opened_reason": "chargeback",
                     "resolution_reason": None, "created_at": NOW, "resolved_at": None}]
        return ledger_view(
            lots, postings, orders, refunds, disputes,
            limits={"postings": 200, "lots": 100, "orders": 20},
        )

    def test_owner_ledger_carries_money_and_safe_projections(self):
        view = self.ledger_view()
        self.assertEqual(len(view["postings"]), 2)
        self.assertEqual(view["postings"][0]["event"], "settle")
        self.assertEqual(view["lots"][0]["origin_order"], "order-1")
        self.assertEqual(view["orders"][0]["state"], "credited")
        self.assertEqual(view["refunds"][0]["amount_minor"], 4900)
        self.assertEqual(view["disputes"][0]["disputed_units"], 155)
        # Saga internals never leave the service boundary.
        self.assertNotIn("lease_until", view["refunds"][0])
        self.assertNotIn("fence", view["refunds"][0])
        self.assertNotIn("owner_id", view["refunds"][0])

    def test_posting_projection_is_integral_deltas_only(self):
        view = self.ledger_view()
        allowed = {"posting_id", "lot_id", "reservation_id", "event",
                   "available_delta", "reserved_delta", "spent_delta",
                   "expired_delta", "refund_pending_delta", "refunded_delta",
                   "created_at"}
        self.assertTrue(set(view["postings"][0]) <= allowed)
        for posting in view["postings"]:
            for key in ("available_delta", "reserved_delta", "spent_delta",
                        "expired_delta", "refund_pending_delta", "refunded_delta"):
                self.assertIsInstance(posting[key], int)

    def test_lot_projection_has_no_secret_columns(self):
        view = self.ledger_view()
        lot_view = view["lots"][0]
        self.assertEqual(lot_view["source"], "purchased")
        for forbidden in ("wallet_id", "account_id", "created_at"):
            self.assertNotIn(forbidden, lot_view)


class WalletSurfaceTests(unittest.TestCase):
    def test_safe_codes_are_member_safe_and_translated(self):
        # AUTH-24 introduces no new codes; every refusal the UI can hit is
        # already in the shared safe catalogue.
        for code in (
            "wallet_required",
            "wallet_locked",
            "owner_required",
            "account_not_found",
            "account_expired",
            "team_unavailable",
            "refund_not_eligible",
            "refund_window",
            "refund_not_found",
        ):
            self.assertIn(code, _MESSAGES)
            self.assertTrue(str(_MESSAGES[code]).strip())

    def test_member_message_leads_to_owner(self):
        self.assertIn("владельц", _MESSAGES["wallet_locked"].lower())

    def test_router_registers_two_read_routes(self):
        from apps.api.routers import billing

        paths = {
            (route.path, tuple(sorted(route.methods)))
            for route in billing.router.routes
        }
        self.assertIn(("/{account_id}/wallet", ("GET",)), paths)
        self.assertIn(("/{account_id}/wallet/ledger", ("GET",)), paths)


if __name__ == "__main__":
    unittest.main()
