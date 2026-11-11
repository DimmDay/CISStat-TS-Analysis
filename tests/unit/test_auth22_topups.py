"""AUTH-22 quote/top-up checkout and credit contracts. Real SQL flows live in
tests/integration.

Normative rules: spec_billing_accounts.md §13.4/§13.8 (server-side snapshot,
browser return never credits, unique credit-per-order), spec_auth_architecture.md
AUTH-22 (duplicate events/callback spoof/currency tamper closed).
"""

import unittest
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError

from apps.api.authentication.context import _MESSAGES


def package_row(**overrides):
    row = {
        "package_id": uuid4(),
        "title": "100 CU",
        "units": 100_000_000,
        "price_minor": 4900,
        "currency": "RUB",
        "price_version": "price-v1",
        "terms_version": "terms-v1",
        "enabled": True,
        "created_at": datetime.now(UTC),
    }
    row.update(overrides)
    return row


class PackageValidation(unittest.TestCase):
    """D1: operator catalog only; integer money/units; RUB-only v1."""

    def test_valid_package_passes(self):
        from apps.api.billing.topups import validate_package

        validate_package(
            "100 CU", 100_000_000, 4900, "RUB", "price-v1", "terms-v1"
        )

    def test_integer_units_and_price_bounds(self):
        from apps.api.billing.topups import validate_package

        for bad_units in (0, -1, 1.5, True, "100", 10**12 + 1):
            with self.assertRaises(ValueError):
                validate_package(
                    "p", bad_units, 4900, "RUB", "v", "t"
                )
        for bad_price in (0, -1, 1.5, True, "1", 10**10 + 1):
            with self.assertRaises(ValueError):
                validate_package("p", 1000, bad_price, "RUB", "v", "t")

    def test_currency_rub_only_v1_and_text_bounds(self):
        from apps.api.billing.topups import validate_package

        for bad_currency in ("USD", "EUR", "rub", "", None):
            with self.assertRaises(ValueError):
                validate_package("p", 1000, 100, bad_currency, "v", "t")
        for bad_text in ("", " ", "x" * 129, None, 5):
            with self.assertRaises(ValueError):
                validate_package(bad_text, 1000, 100, "RUB", "v", "t")
            with self.assertRaises(ValueError):
                validate_package("p", 1000, 100, "RUB", bad_text, "t")
            with self.assertRaises(ValueError):
                validate_package("p", 1000, 100, "RUB", "v", bad_text)


class TopupState(unittest.TestCase):
    """D3: pending -> credited|canceled|review_required|paid_review; terminal."""

    def test_state_vocabulary_and_terminals(self):
        from apps.api.billing.topups import TERMINAL_TOPUP_STATES, TOPUP_STATES

        self.assertEqual(
            TOPUP_STATES,
            frozenset({"pending", "credited", "canceled", "review_required", "paid_review"}),
        )
        self.assertEqual(
            TERMINAL_TOPUP_STATES,
            frozenset({"credited", "canceled", "paid_review"}),
        )

    def test_transitions(self):
        from apps.api.billing.topups import topup_transition_allowed

        for new in ("credited", "canceled", "review_required", "paid_review"):
            self.assertTrue(topup_transition_allowed("pending", new))
        self.assertFalse(topup_transition_allowed("pending", "pending"))
        # credited/canceled never reopen (out-of-order events, 13.4.5).
        for terminal in ("credited", "canceled"):
            for new in ("pending", "credited", "canceled", "review_required", "paid_review"):
                self.assertFalse(topup_transition_allowed(terminal, new))
        # paid_review -> credited is the single audited operator resolution (D5).
        self.assertTrue(topup_transition_allowed("paid_review", "credited"))
        for new in ("pending", "canceled", "review_required", "paid_review"):
            self.assertFalse(topup_transition_allowed("paid_review", new))
        self.assertFalse(topup_transition_allowed("unknown", "pending"))


class Snapshot(unittest.TestCase):
    """D1/D2: the server copies the package row; the client supplies none of it."""

    def test_snapshot_pins_package_fields_only(self):
        from apps.api.billing.topups import build_topup_snapshot

        pkg = package_row()
        now = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
        snap = build_topup_snapshot(
            pkg,
            account_id=uuid4(),
            owner_id=uuid4(),
            quote_id=uuid4(),
            now=now,
            expires_at=now + timedelta(minutes=15),
        )
        self.assertIn("amount_minor", snap)
        self.assertNotIn("enabled", snap)
        self.assertNotIn("price_minor", snap)
        self.assertEqual(snap["units"], pkg["units"])
        self.assertEqual(snap["amount_minor"], pkg["price_minor"])

    def test_digest_is_canonical_sha256_hex(self):
        from apps.api.billing.topups import build_topup_snapshot, snapshot_digest

        pkg = package_row()
        now = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
        snap = build_topup_snapshot(
            pkg,
            account_id=uuid4(),
            owner_id=uuid4(),
            quote_id=uuid4(),
            now=now,
            expires_at=now + timedelta(minutes=15),
        )
        digest = snapshot_digest(snap)
        self.assertRegex(digest, r"^[a-f0-9]{64}$")
        self.assertEqual(digest, snapshot_digest(dict(reversed(list(snap.items())))))


class ContractDTO(unittest.TestCase):
    """D1/D8: the browser cannot inject amount/units/currency into the flow."""

    def test_quote_command_fields_and_forbid(self):
        from apps.api.billing.topup_contract import TopupQuote

        body = TopupQuote(
            package_id=str(uuid4()),
            expected_version=1,
            reason="OWNER top-up",
            idempotency_key="key-1",
        )
        self.assertIsInstance(body.package_id, UUID)
        for extra in ({"amount_minor": 1}, {"units": 10}, {"currency": "USD"}):
            with self.assertRaises(ValidationError):
                TopupQuote(
                    package_id=str(uuid4()),
                    expected_version=1,
                    reason="r",
                    idempotency_key="k",
                    **extra,
                )

    def test_order_command_digest_pattern(self):
        from apps.api.billing.topup_contract import TopupOrder

        TopupOrder(
            quote_id=str(uuid4()),
            quote_digest="a" * 64,
            expected_version=1,
            reason="confirm top-up",
            idempotency_key="key-2",
        )
        with self.assertRaises(ValidationError):
            TopupOrder(
                quote_id=str(uuid4()),
                quote_digest="not-a-digest",
                expected_version=1,
                reason="r",
                idempotency_key="k",
            )


class WebhookParity(unittest.TestCase):
    """D7: same bounded provider event vocabulary as the AUTH-18 inbox."""

    def test_event_allowlist_matches_auth18(self):
        from apps.api.billing.topups import WEBHOOK_EVENTS

        self.assertEqual(
            WEBHOOK_EVENTS,
            frozenset(
                {"payment.succeeded", "payment.canceled", "payment.waiting_for_capture"}
            ),
        )


class SafeCodes(unittest.TestCase):
    """D5/D9/D12: refusals carry safe, non-secret codes."""

    def test_topup_codes_registered(self):
        for code in (
            "wallet_required",
            "topup_not_configured",
            "topup_package_not_found",
            "topup_quote_not_found",
            "topup_quote_changed",
            "topup_quote_expired",
            "topup_quote_limit",
            "topup_order_not_found",
        ):
            self.assertIn(code, _MESSAGES)
            self.assertTrue(str(_MESSAGES[code]).strip())

    def test_no_secrets_in_messages(self):
        for code, text in _MESSAGES.items():
            self.assertNotIn("secret", str(text).lower())
            self.assertNotIn("key", str(text).lower())


if __name__ == "__main__":
    unittest.main()
