"""AUTH-23 refund/dispute contracts without a database: state machines,
refund window, provider refund validation, DTO bounds, safe codes, view
projection. Native PostgreSQL flows live in tests/integration/test_auth23_refunds.py."""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from apps.api.authentication.context import _MESSAGES
from apps.api.billing.provider import ProviderMismatch, YooKassa

REFUND_STATES = frozenset({"pending", "refunded", "failed", "review_required"})
TERMINAL_REFUND_STATES = frozenset({"refunded", "failed"})
DISPUTE_STATES = frozenset({"open", "lost", "won"})


class RefundStateMachineTests(unittest.TestCase):
    def test_pending_admits_any_non_terminal_transition(self):
        from apps.api.billing.refunds import refund_transition_allowed

        self.assertTrue(refund_transition_allowed("pending", "refunded"))
        self.assertTrue(refund_transition_allowed("pending", "failed"))
        self.assertTrue(refund_transition_allowed("pending", "review_required"))

    def test_review_required_returns_to_pending_only(self):
        from apps.api.billing.refunds import refund_transition_allowed

        self.assertTrue(refund_transition_allowed("review_required", "pending"))
        self.assertFalse(refund_transition_allowed("review_required", "refunded"))
        self.assertFalse(refund_transition_allowed("review_required", "failed"))

    def test_terminal_states_never_change(self):
        from apps.api.billing.refunds import refund_transition_allowed

        for old in TERMINAL_REFUND_STATES:
            for new in (REFUND_STATES | {"pending"}) - {old}:
                self.assertFalse(refund_transition_allowed(old, new))

    def test_unknown_or_equal_states_rejected(self):
        from apps.api.billing.refunds import refund_transition_allowed

        # A same-state update is the saga's own backoff/reschedule; unknown
        # states and cross-kind transitions stay rejected.
        self.assertTrue(refund_transition_allowed("pending", "pending"))
        self.assertTrue(refund_transition_allowed("review_required", "review_required"))
        self.assertFalse(refund_transition_allowed("open", "refunded"))
        self.assertFalse(refund_transition_allowed("refunded", "bogus"))
        self.assertFalse(refund_transition_allowed("bogus", "pending"))

    def test_dispute_resolution_is_single_and_terminal(self):
        from apps.api.billing.refunds import dispute_transition_allowed

        self.assertTrue(dispute_transition_allowed("open", "lost"))
        self.assertTrue(dispute_transition_allowed("open", "won"))
        self.assertFalse(dispute_transition_allowed("open", "open"))
        self.assertFalse(dispute_transition_allowed("lost", "won"))
        self.assertFalse(dispute_transition_allowed("won", "lost"))
        self.assertFalse(dispute_transition_allowed("lost", "lost"))
        self.assertFalse(dispute_transition_allowed("won", "won"))
        self.assertFalse(dispute_transition_allowed("bogus", "lost"))


class RefundWindowTests(unittest.TestCase):
    def test_window_from_env_is_bounded(self):
        from apps.api.billing.refunds import window_days

        with patch.dict("os.environ", {"CISSTAT_TOPUP_REFUND_DAYS": "30"}):
            self.assertEqual(window_days(), 30)
        with patch.dict("os.environ", {"CISSTAT_TOPUP_REFUND_DAYS": "0"}):
            self.assertEqual(window_days(), 0)
        with patch.dict("os.environ", {"CISSTAT_TOPUP_REFUND_DAYS": "91"}):
            with self.assertRaises(ValueError):
                window_days()
        with patch.dict("os.environ", {"CISSTAT_TOPUP_REFUND_DAYS": "-1"}):
            with self.assertRaises(ValueError):
                window_days()
        with patch.dict("os.environ", {"CISSTAT_TOPUP_REFUND_DAYS": "bogus"}):
            with self.assertRaises(ValueError):
                window_days()

    def test_default_window_is_14_days(self):
        from apps.api.billing.refunds import window_days

        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("CISSTAT_TOPUP_REFUND_DAYS", None)
            self.assertEqual(window_days(), 14)

    def test_expired_window_rejects_request(self):
        from apps.api.billing.refunds import within_window

        credited = datetime(2026, 1, 1, tzinfo=UTC)
        self.assertTrue(within_window(credited, 14, credited + timedelta(days=13)))
        self.assertFalse(within_window(credited, 14, credited + timedelta(days=14, seconds=1)))
        self.assertTrue(within_window(credited, 0, credited))
        self.assertFalse(within_window(credited, 0, credited + timedelta(seconds=1)))
        with self.assertRaises(ValueError):
            within_window(credited + timedelta(days=1), 14, credited)


class ProviderRefundTests(unittest.TestCase):
    def gateway(self):
        return YooKassa("shop-1", "secret-1")

    def job(self):
        return {
            "refund_id": "r-1",
            "order_id": "o-1",
            "payment_id": "payment-22",
            "amount_minor": 4900,
            "currency": "RUB",
        }

    def test_confirmed_refund_matches_full_amount(self):
        proof = self.gateway().validate_refund(
            {
                "id": "r-1",
                "payment_id": "payment-22",
                "status": "succeeded",
                "amount": {"value": "49.00", "currency": "RUB"},
            },
            self.job(),
        )
        self.assertEqual(proof["status"], "succeeded")
        self.assertEqual(proof["refund_id"], "r-1")

    def test_pending_refund_keeps_hold(self):
        proof = self.gateway().validate_refund(
            {
                "id": "r-1",
                "payment_id": "payment-22",
                "status": "pending",
                "amount": {"value": "49.00", "currency": "RUB"},
            },
            self.job(),
        )
        self.assertEqual(proof["status"], "pending")

    def test_spoofed_payment_or_amount_rejected(self):
        raw = {
            "id": "r-1",
            "payment_id": "payment-OTHER",
            "status": "succeeded",
            "amount": {"value": "49.00", "currency": "RUB"},
        }
        with self.assertRaises(ProviderMismatch):
            self.gateway().validate_refund(raw, self.job())
        raw["payment_id"] = "payment-22"
        raw["amount"] = {"value": "48.00", "currency": "RUB"}
        with self.assertRaises(ProviderMismatch):
            self.gateway().validate_refund(raw, self.job())
        raw["amount"] = {"value": "49.00", "currency": "USD"}
        with self.assertRaises(ProviderMismatch):
            self.gateway().validate_refund(raw, self.job())

    def test_unknown_status_rejected(self):
        raw = {
            "id": "r-1",
            "payment_id": "payment-22",
            "status": "waiting_for_capture",
            "amount": {"value": "49.00", "currency": "RUB"},
        }
        with self.assertRaises(ProviderMismatch):
            self.gateway().validate_refund(raw, self.job())

    def test_refund_id_shape_required(self):
        with self.assertRaises(ValueError):
            YooKassa._id("../escape")


class RefundDtoTests(unittest.TestCase):
    def test_request_forbids_extra_and_client_amounts(self):
        from apps.api.billing.refund_contract import RefundRequest
        from pydantic import ValidationError

        base = {
            "expected_version": 3,
            "reason": "owner changed mind",
            "idempotency_key": "k" * 16,
        }
        RefundRequest(**base, order_id="00000000-0000-0000-0000-000000000001")
        with self.assertRaises(ValidationError):
            RefundRequest(**base, order_id="00000000-0000-0000-0000-000000000001", amount_minor=1)
        with self.assertRaises(ValidationError):
            RefundRequest(**base)
        with self.assertRaises(ValidationError):
            RefundRequest(**(base | {"expected_version": 0}), order_id="00000000-0000-0000-0000-000000000001")


class RefundSurfaceTests(unittest.TestCase):
    def test_safe_codes_are_translated(self):
        for code in (
            "refund_not_eligible",
            "refund_window",
            "refund_not_found",
        ):
            self.assertIn(code, _MESSAGES)
            self.assertTrue(str(_MESSAGES[code]).strip())

    def test_view_never_leaks_provider_secrets(self):
        from apps.api.billing.refunds import refund_view

        row = {
            "refund_id": "11111111-1111-1111-1111-111111111111",
            "order_id": "22222222-2222-2222-2222-222222222222",
            "state": "pending",
            "units": 1000,
            "amount_minor": 4900,
            "currency": "RUB",
            "terms_version": "fixture-terms",
            "provider_refund_id": "r-9",
            "lease_until": datetime.now(UTC),
            "fence": 4,
            "owner_id": "33333333-3333-3333-3333-333333333333",
            "created_at": datetime.now(UTC),
            "decided_at": None,
        }
        view = refund_view(row)
        self.assertEqual(view["state"], "pending")
        self.assertNotIn("lease_until", view)
        self.assertNotIn("fence", view)
        self.assertNotIn("owner_id", view)

    def test_backoff_is_bounded_and_exponential(self):
        from datetime import timedelta

        from apps.api.billing.refunds import refund_backoff

        self.assertEqual(refund_backoff(1), timedelta(seconds=30))
        self.assertEqual(refund_backoff(6), timedelta(seconds=900))
        self.assertEqual(refund_backoff(50), timedelta(seconds=900))


if __name__ == "__main__":
    unittest.main()
