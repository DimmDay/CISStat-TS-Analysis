"""AUTH-21 wallet/credit-lot contracts. Real SQL flows live in tests/integration.

Normative rules: spec_billing_accounts.md §13 (FEFO, source separation, integer
micro-CU, expiry/pinned allocations), spec_auth_architecture.md AUTH-21.
"""

import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from apps.api.billing.wallet import (
    SOURCE_RANK,
    WALLET_SOURCES,
    WalletError,
    allocate_split,
    fefo_key,
    is_spendable,
    settle_distribution,
    validate_issue,
)


def lot(source, *, available=100, expires=None, lot_id=None, issued=None):
    return {
        "lot_id": lot_id or uuid4(),
        "source": source,
        "available": available,
        "issued": issued if issued is not None else available,
        "expires_at": expires,
    }


class SourceTaxonomy(unittest.TestCase):
    def test_sources_and_rank_match_spec_13_2(self):
        self.assertEqual(
            WALLET_SOURCES, frozenset({"included", "purchased", "promotional"})
        )
        # §13.5 tie-break: included -> promotional -> purchased.
        self.assertEqual(SOURCE_RANK["included"], 0)
        self.assertEqual(SOURCE_RANK["promotional"], 1)
        self.assertEqual(SOURCE_RANK["purchased"], 2)


class FefoOrdering(unittest.TestCase):
    def test_nearest_expiry_first(self):
        soon = lot("promotional", expires=datetime(2026, 12, 1, tzinfo=UTC))
        late = lot("included", expires=datetime(2026, 12, 31, tzinfo=UTC))
        self.assertLess(fefo_key(soon), fefo_key(late))

    def test_no_expiry_is_last(self):
        dying = lot("purchased", expires=datetime(2020, 1, 1, tzinfo=UTC))
        endless = lot("purchased", expires=None)
        self.assertLess(fefo_key(dying), fefo_key(endless))

    def test_equal_expiry_source_rank_then_lot_id(self):
        when = datetime(2026, 12, 1, tzinfo=UTC)
        a = lot("included", expires=when, lot_id=uuid4())
        b = lot("promotional", expires=when, lot_id=uuid4())
        c = lot("purchased", expires=when, lot_id=uuid4())
        self.assertLess(fefo_key(a), fefo_key(b))
        self.assertLess(fefo_key(b), fefo_key(c))
        # Stable lot_id tie-break inside one source.
        a2 = lot("included", expires=when, lot_id=a["lot_id"])
        self.assertEqual(fefo_key(a), fefo_key(a2))

    def test_expired_lot_is_not_spendable(self):
        # D3: FEFO candidates are filtered by is_spendable; expiry never revives.
        now = datetime(2026, 12, 2, tzinfo=UTC)
        self.assertFalse(
            is_spendable(lot("included", expires=now - timedelta(days=1)), now)
        )
        self.assertFalse(is_spendable(lot("included", expires=now), now))
        self.assertTrue(
            is_spendable(lot("included", expires=now + timedelta(seconds=1)), now)
        )
        self.assertTrue(is_spendable(lot("purchased", expires=None), now))
        self.assertFalse(is_spendable(lot("included", available=0), now))


class AllocateSplit(unittest.TestCase):
    def test_exact_sum_without_loss(self):
        lots = [
            lot("included", available=500, expires=datetime(2026, 12, 1, tzinfo=UTC)),
            lot("purchased", available=200, expires=None),
        ]
        plan = allocate_split(lots, 550)
        self.assertEqual(sum(take for _, take in plan), 550)
        self.assertEqual(dict(plan)[lots[0]["lot_id"]], 500)
        self.assertEqual(dict(plan)[lots[1]["lot_id"]], 50)

    def test_last_lot_carries_full_remainder(self):
        # D7: integer splits never fabricate or lose micro-CU; deterministic
        # lot_id order inside one source bucket.
        lots = [lot("included", available=7), lot("included", available=7)]
        plan = allocate_split(lots, 10)
        self.assertEqual(sum(t for _, t in plan), 10)
        self.assertEqual(sorted(t for _, t in plan), [3, 7])

    def test_insufficient_raises_domain_error(self):
        with self.assertRaises(WalletError) as ctx:
            allocate_split([lot("included", available=10)], 11)
        self.assertEqual(ctx.exception.code, "cu_insufficient")
        self.assertEqual(ctx.exception.details["required"], 11)
        self.assertEqual(ctx.exception.details["available"], 10)

    def test_zero_units_is_rejected(self):
        with self.assertRaises(ValueError):
            allocate_split([lot("included", available=10)], 0)


class SettleDistribution(unittest.TestCase):
    def test_fefo_consumption_and_tail(self):
        # E2: reserve 60 (included 40 + purchased 20), actual 45 ->
        # included 40 spent, purchased 5 spent, purchased tail 15 released.
        included = lot("included", available=0, expires=datetime(2026, 12, 1, tzinfo=UTC))
        purchased = lot("purchased", available=0, expires=None)
        allocations = [(included, 40), (purchased, 20)]
        spends, tails = settle_distribution(allocations, 45)
        self.assertEqual(dict(spends)[included["lot_id"]], 40)
        self.assertEqual(dict(spends)[purchased["lot_id"]], 5)
        self.assertEqual(dict(tails)[purchased["lot_id"]], ("available", 15))
        self.assertNotIn(included["lot_id"], dict(tails))

    def test_actual_never_exceeds_pinned(self):
        included = lot("included", available=0)
        with self.assertRaises(ValueError):
            settle_distribution([(included, 10)], 11)

    def test_tail_after_expiry_classified_expired(self):
        # D6/E2: a released tail of an expired lot never revives.
        now = datetime(2027, 1, 1, tzinfo=UTC)
        included = lot("included", expires=datetime(2026, 12, 1, tzinfo=UTC))
        purchased = lot("purchased", expires=None)
        allocations = [(included, 15), (purchased, 15)]
        _, classified = settle_distribution(allocations, 0, now=now)
        self.assertEqual(dict(classified)[included["lot_id"]], ("expired", 15))
        self.assertEqual(dict(classified)[purchased["lot_id"]], ("available", 15))

    def test_tail_before_expiry_stays_available(self):
        now = datetime(2026, 11, 1, tzinfo=UTC)
        included = lot("included", expires=datetime(2026, 12, 1, tzinfo=UTC))
        _, classified = settle_distribution([(included, 5)], 0, now=now)
        self.assertEqual(dict(classified)[included["lot_id"]], ("available", 5))


class IssueValidation(unittest.TestCase):
    def test_units_must_be_finite_positive_integers(self):
        for bad in (0, -1, 1.5, True, "10", None, 2**63):
            with self.assertRaises(ValueError):
                validate_issue("purchased", bad, origin_order="order-1")

    def test_purchased_requires_origin_order(self):
        with self.assertRaises(ValueError):
            validate_issue("purchased", 100, origin_order="")
        with self.assertRaises(ValueError):
            validate_issue("purchased", 100, origin_order=" " * 5)
        self.assertTrue(validate_issue("purchased", 100, origin_order="order-1"))

    def test_purchased_has_no_expiry_in_v1(self):
        # §13.2: purchased survives cycle/seat/plan changes; never expires.
        with self.assertRaises(ValueError):
            validate_issue(
                "purchased", 100, origin_order="o", expires_at=datetime(2030, 1, 1, tzinfo=UTC)
            )

    def test_included_requires_future_expiry_and_ref(self):
        with self.assertRaises(ValueError):
            validate_issue("included", 100, origin_ref="base")
        with self.assertRaises(ValueError):
            validate_issue(
                "included",
                100,
                origin_ref="base",
                expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        ok = validate_issue(
            "included",
            100,
            origin_ref="base",
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        self.assertTrue(ok)

    def test_promotional_requires_origin_ref(self):
        with self.assertRaises(ValueError):
            validate_issue("promotional", 100)
        self.assertTrue(validate_issue("promotional", 100, origin_ref="promo-2026"))


if __name__ == "__main__":
    unittest.main()
