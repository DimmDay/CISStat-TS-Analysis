"""AUTH-12 portable money/idempotency/policy contract oracles."""

import unittest
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from apps.api.billing.contract import Admission, Cost, digest_payload, utc_month


class LedgerContracts(unittest.TestCase):
    def test_money_is_bounded_integer_never_float_or_bool(self):
        for bad in (True, 1.0, -1, 2**63):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                Cost(micro_cu=bad, version="test/v1")
        self.assertEqual(
            Cost(micro_cu=2**63 - 1, version="test/v1").micro_cu, 2**63 - 1
        )

    def test_digest_is_canonical_and_finite(self):
        self.assertEqual(
            digest_payload({"b": 2, "a": [1]}), digest_payload({"a": [1], "b": 2})
        )
        with self.assertRaises(ValueError):
            digest_payload({"x": float("nan")})

    def test_admission_cannot_supply_budget_chain_or_price_float(self):
        with self.assertRaises(ValidationError):
            Admission(
                entry_id="api:POST:/v1/public/passport",
                resource_kind="run",
                resource_id="RUN-A",
                idempotency_key="k",
                payload={},
                cost=Cost(micro_cu=0, version="counters/v1"),
                deadline=datetime.now(UTC),
                budget_ids=[str(uuid4())],
            )

    def test_month_is_explicit_utc_not_browser_clock(self):
        self.assertEqual(utc_month(datetime(2026, 11, 1, tzinfo=UTC)), "2026-11")
        with self.assertRaises(ValueError):
            utc_month(datetime(2026, 11, 1))

    def test_cu_cannot_skip_concurrency(self):
        with self.assertRaises(ValidationError):
            Admission(
                entry_id="api:POST:/v1/public/passport",
                resource_kind="stateless",
                resource_id="one",
                idempotency_key="k",
                payload={},
                cost=Cost(micro_cu=1, version="test/v1"),
                deadline=datetime.now(UTC),
                slots=0,
            )
