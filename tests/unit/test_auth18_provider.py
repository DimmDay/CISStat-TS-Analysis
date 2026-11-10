"""AUTH-18 protocol and integer proration contracts, no real provider calls."""

import unittest

import httpx

from apps.api.billing.provider import ProviderMismatch, ProviderUnavailable, YooKassa
from apps.api.billing.subscription_contract import cumulative_allocation, prorate


class ProviderTests(unittest.TestCase):
    def test_proration_integer_and_churn(self):
        self.assertEqual(prorate(3, 101, 1, 3), 101)
        self.assertEqual(prorate(1, 100, 1, 3), 34)
        self.assertEqual(prorate(-1, 100, 1, 3), 0)
        self.assertEqual(cumulative_allocation(100, 100 * 2, 3), 166)
        self.assertEqual(cumulative_allocation(100, 100 * 2 - 100 * 2, 3), 100)
        for bad in (True, 1.2, "1"):
            with self.assertRaises(ValueError):
                prorate(bad, 100, 1, 3)

    def test_yookassa_fixed_origin_and_proof(self):
        seen = []
        payload = {
            "id": "p-1",
            "status": "succeeded",
            "paid": True,
            "test": True,
            "recipient": {"account_id": "shop"},
            "amount": {"value": "1.01", "currency": "RUB"},
            "metadata": {"order_id": "order", "quote_digest": "digest"},
        }

        def handle(r):
            seen.append(r)
            return httpx.Response(200, json=payload)

        p = YooKassa("shop", "secret", transport=httpx.MockTransport(handle))
        proof = p.fetch("p-1")
        p.validate(
            proof,
            {
                "payment_id": "p-1",
                "order_id": "order",
                "digest": "digest",
                "shop_id": "shop",
                "sandbox": True,
                "amount_minor": 101,
                "currency": "RUB",
            },
        )
        self.assertEqual(str(seen[0].url), "https://api.yookassa.ru/v3/payments/p-1")
        self.assertNotIn("secret", repr(p))
        for field, value in [
            ("paid", False),
            ("test", False),
            ("recipient", {"account_id": "another-shop"}),
            ("metadata", {"order_id": "another-order", "quote_digest": "digest"}),
            ("amount", {"value": "1.01", "currency": "USD"}),
            ("amount", {"value": "1.02", "currency": "RUB"}),
        ]:
            forged = payload | {field: value}
            with self.assertRaises(ProviderMismatch):
                p.validate(
                    forged,
                    {
                        "payment_id": "p-1",
                        "order_id": "order",
                        "digest": "digest",
                        "shop_id": "shop",
                        "sandbox": True,
                        "amount_minor": 101,
                        "currency": "RUB",
                    },
                )
        with self.assertRaises(ValueError):
            p.fetch("../evil")

    def test_outage_and_no_live(self):
        p = YooKassa(
            "shop",
            "secret",
            transport=httpx.MockTransport(lambda r: httpx.Response(500)),
        )
        with self.assertRaises(ProviderUnavailable):
            p.fetch("p-1")
        with self.assertRaises(ValueError):
            YooKassa("shop", "secret", sandbox=False)


if __name__ == "__main__":
    unittest.main()


class MalformedProviderTests(unittest.TestCase):
    def test_oversized_and_unavailable_responses(self):
        for response in (
            httpx.Response(200, content=b"x" * 65537),
            httpx.Response(200, json=[]),
            httpx.Response(302, headers={"location": "https://evil.invalid"}),
        ):
            p = YooKassa(
                "shop",
                "secret",
                transport=httpx.MockTransport(lambda r, response=response: response),
            )
            with self.assertRaises(ProviderUnavailable):
                p.fetch("p-1")

    def test_cumulative_rounding_preserves_signed_debt(self):
        # No rounding credit from repeated equal-time add/remove; negative carry persists.
        n = 0
        for _ in range(1000):
            n += 7
            n -= 7
        self.assertEqual(cumulative_allocation(100, n, 3), 100)
        self.assertEqual(cumulative_allocation(100, -301, 3), 0)
        self.assertEqual(cumulative_allocation(100, -301 + 1, 3), 0)


class ShopPreflightTests(unittest.TestCase):
    def test_live_shop_never_receives_create_payment(self):
        calls = []

        def response(r):
            calls.append(r)
            return httpx.Response(
                200, json={"account_id": "shop", "test": False, "status": "enabled"}
            )

        gateway = YooKassa("shop", "secret", transport=httpx.MockTransport(response))
        with self.assertRaises(ProviderMismatch):
            gateway.create(
                {
                    "order_id": "order",
                    "digest": "digest",
                    "amount_minor": 100,
                    "currency": "RUB",
                }
            )
        self.assertEqual([r.method for r in calls], ["GET"])
