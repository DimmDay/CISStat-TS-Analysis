"""Native PostgreSQL saga, real SQL rollback, no real merchant/network."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID

import httpx

from apps.api.accounts.team_contract import SeatRequest
from apps.api.billing.provider import YooKassa
from apps.api.billing.subscription_contract import Confirm, Quote
from apps.api.billing.subscription_migrations import apply_migration, check_schema
from apps.api.billing.subscriptions import SubscriptionService
from tests.integration import test_auth17_team as previous
from tests.integration.test_auth04_sessions import ORIGIN


@unittest.skipUnless(
    os.environ.get("CISSTAT_AUTH_TEST_DSN"), "disposable PostgreSQL required"
)
class SagaSQLTests(unittest.TestCase):
    cleanup = previous.TeamSQLTests.cleanup
    login = previous.TeamSQLTests.login
    error = previous.TeamSQLTests.error
    rows = previous.TeamSQLTests.rows
    person = previous.TeamSQLTests.person
    current = previous.TeamSQLTests.current
    body = previous.TeamSQLTests.body
    command = previous.TeamSQLTests.command

    def setUp(self):
        previous.TeamSQLTests.setUp(self)
        self.calls = []
        self.status = "pending"
        self.payment_id = "payment-18"
        self.outage = False
        self.bad = False
        self.lost = False
        self.gateway = YooKassa(
            "test-shop", "not-a-real-secret", transport=httpx.MockTransport(self.http)
        )
        self.billing = SubscriptionService(self.store, lambda: self.now, self.gateway)
        with self.store.transaction() as tx:
            apply_migration(tx.connection)
            tx.connection.execute(
                "UPDATE auth_accounts SET plan_expires_at=%s,entitlement_version=entitlement_version+1 WHERE account_id=%s",
                (self.now + timedelta(days=15), self.account.account_id),
            )
        self.billing.provision_cycle(
            self.account.account_id,
            starts_at=self.now - timedelta(days=15),
            ends_at=self.now + timedelta(days=15),
            seat_price_minor=101,
            included_per_seat=1000000,
            price_version="fixture-v1",
            terms_version="fixture-terms",
            reason="isolated test shop",
            allow_reduction=True,
        )

    def http(self, r):
        self.calls.append(r)
        if self.outage:
            return httpx.Response(500)
        if r.url.path == "/v3/me":
            return httpx.Response(
                200, json={"account_id": "test-shop", "test": True, "status": "enabled"}
            )
        if r.method == "POST":
            import json

            self.created = json.loads(r.content)
            self.key = r.headers["Idempotence-Key"]
            if self.lost:
                raise httpx.ReadTimeout("lost response")
        p = {
            "id": self.payment_id,
            "status": self.status,
            "paid": self.status == "succeeded",
            "test": True,
            "recipient": {"account_id": "test-shop"},
            "amount": self.created["amount"],
            "metadata": self.created["metadata"],
            "confirmation": {
                "type": "redirect",
                "confirmation_url": "https://yoomoney.ru/checkout/payments/v2/contract",
            },
        }
        if self.bad:
            p["amount"] = {"value": "999.00", "currency": "RUB"}
        return httpx.Response(200, json=p)

    def order(self, seats=4):
        r = self.command("seat-request", self.body(SeatRequest, seats=seats))
        b = self.body(Quote, request_id=UUID(r["request_id"]))
        q = self.billing.quote(self.token, ORIGIN, self.account.account_id, b)
        o = self.billing.confirm(
            self.token,
            ORIGIN,
            self.account.account_id,
            q["quote_id"],
            Confirm(quote_digest=q["digest"]),
        )
        return r, q, o

    def due(self):
        self.now += timedelta(minutes=2)

    def test_migration_quote_snapshot_owner_and_confirmation_replay(self):
        with self.store.transaction() as tx:
            self.assertFalse(apply_migration(tx.connection))
            check_schema(tx.connection)
        _r, q, o = self.order()
        self.assertEqual(q["snapshot"]["amount_minor"], 101)
        self.assertEqual(self.current().seats, 2)
        again = self.billing.confirm(
            self.token,
            ORIGIN,
            self.account.account_id,
            q["quote_id"],
            Confirm(quote_digest=q["digest"]),
        )
        self.assertEqual(o, again)
        self.error(
            lambda: self.billing.show(
                self.other_token, ORIGIN, self.account.account_id
            ),
            404,
        )
        self.error(
            lambda: self.billing.confirm(
                self.token,
                ORIGIN,
                self.account.account_id,
                q["quote_id"],
                Confirm(quote_digest="a" * 64),
            ),
            409,
        )
        self.assertEqual(len(self.rows("auth_billing_orders")), 1)

    def test_paid_dedup_out_of_order_and_allocation(self):
        _r, _q, o = self.order()
        self.billing.step()
        self.assertEqual(self.current().seats, 2)
        self.status = "succeeded"
        self.due()
        for event in ("payment.canceled", "payment.succeeded", "payment.succeeded"):
            self.billing.notify("payment-18", event, UUID(o["order_id"]))
        self.billing.step()
        self.assertEqual(self.current().seats, 4)
        self.assertEqual(len(self.rows("auth_billing_adjustments")), 1)
        self.assertEqual(
            self.rows("auth_billing_adjustments")[0]["included_entitlement"], 3000000
        )
        self.assertEqual(self.rows("auth_billing_orders")[0]["state"], "applied")
        self.status = "pending"
        self.billing.notify("payment-18", "payment.canceled")
        self.due()
        self.assertFalse(self.billing.step())
        self.assertEqual(self.current().seats, 4)
        # No changes to reservations/spent or spendable CU policies.
        self.assertFalse(self.rows("auth_usage_postings"))

    def test_outage_response_loss_and_24h_hold(self):
        _r, _q, _o = self.order()
        self.lost = True
        self.billing.step()
        self.assertEqual(self.current().seats, 2)
        first = self.key
        self.lost = False
        self.due()
        self.billing.step()
        self.assertEqual(self.key, first)
        self.assertEqual(len([r for r in self.calls if r.method == "POST"]), 2)

    def test_unknown_over_window_no_second_post(self):
        self.order()
        self.lost = True
        self.billing.step()
        self.now += timedelta(hours=24)
        self.lost = False
        self.billing.step()
        self.assertEqual(len([r for r in self.calls if r.method == "POST"]), 1)
        self.assertEqual(
            self.rows("auth_billing_orders")[0]["state"], "review_required"
        )
        self.assertEqual(self.current().seats, 2)

    def test_callback_before_response_proof_and_forgery(self):
        _r, _q, o = self.order()
        # provider accepted POST but response lost; callback offers untrusted candidate
        self.lost = True
        self.billing.step()
        self.status = "succeeded"
        self.lost = False
        self.due()
        self.billing.notify("payment-18", "payment.succeeded", UUID(o["order_id"]))
        self.billing.step()
        self.assertEqual(self.current().seats, 4)
        self.assertEqual(len([r for r in self.calls if r.method == "POST"]), 1)

    def test_bad_provider_amount_no_activation(self):
        _r, _q, _o = self.order()
        self.billing.step()
        self.bad = True
        self.status = "succeeded"
        self.due()
        self.billing.notify("payment-18", "payment.succeeded")
        self.billing.step()
        self.assertEqual(self.current().seats, 2)
        self.assertEqual(
            self.rows("auth_billing_orders")[0]["state"], "review_required"
        )

    def test_stale_paid_request_is_preserved_for_review(self):
        r, _q, _o = self.order()
        self.billing.step()
        self.command("cancel-seat-request", target=UUID(r["request_id"]))
        self.status = "succeeded"
        self.due()
        self.billing.notify("payment-18", "payment.succeeded")
        self.billing.step()
        row = self.rows("auth_billing_orders")[0]
        self.assertEqual(row["state"], "paid_review")
        self.assertIsNotNone(row["paid_at"])
        self.assertEqual(self.current().seats, 2)

    def test_claim_fencing_and_atomic_audit_rollback(self):
        self.order()
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _: self.billing.claim(), range(2)))
        job = next(x for x in claims if x)
        self.assertEqual(sum(x is not None for x in claims), 1)
        self.now += timedelta(seconds=46)
        newer = self.billing.claim()
        self.assertFalse(
            self.billing.finish(
                job,
                proof={
                    "status": "succeeded",
                    "payment_id": "payment-18",
                    "checkout_url": None,
                },
            )
        )
        with patch(  # noqa: SIM117 -- assert rollback explicitly
            "apps.api.billing.subscriptions.audit",
            side_effect=RuntimeError("audit fault"),
        ):
            with self.assertRaises(RuntimeError):
                self.billing.finish(
                    newer,
                    proof={
                        "status": "succeeded",
                        "payment_id": "payment-18",
                        "checkout_url": None,
                    },
                )
        self.assertEqual(self.current().seats, 2)
        self.assertFalse(self.rows("auth_billing_adjustments"))
        self.assertTrue(
            self.billing.finish(
                newer,
                proof={
                    "status": "succeeded",
                    "payment_id": "payment-18",
                    "checkout_url": None,
                },
            )
        )
        self.assertEqual(self.current().seats, 4)

    def test_unknown_reconcile_still_requires_provider_proof(self):
        _, _, order = self.order()
        self.lost = True
        self.billing.step()
        self.now += timedelta(hours=24)
        self.lost = False
        self.billing.step()
        self.assertEqual(
            self.rows("auth_billing_orders")[0]["state"], "review_required"
        )
        self.billing.reconcile(
            order["order_id"], "payment-18", reason="merchant dashboard recovery"
        )
        self.status = "succeeded"
        self.billing.step()
        self.assertEqual(self.rows("auth_billing_orders")[0]["state"], "applied")
        self.assertEqual(self.current().seats, 4)
        self.assertEqual(len([r for r in self.calls if r.method == "POST"]), 1)

    def test_quote_expiry_and_exact_snapshot_guard(self):
        request = self.command("seat-request", self.body(SeatRequest, seats=4))
        quote = self.billing.quote(
            self.token,
            ORIGIN,
            self.account.account_id,
            self.body(Quote, request_id=UUID(request["request_id"])),
        )
        self.now += timedelta(minutes=16)
        # Fresh login proof is irrelevant to quote expiry.
        self.token = self.login().token
        self.error(
            lambda: self.billing.confirm(
                self.token,
                ORIGIN,
                self.account.account_id,
                quote["quote_id"],
                Confirm(quote_digest=quote["digest"]),
            ),
            409,
        )
        self.assertFalse(self.rows("auth_billing_orders"))
        from apps.api.authentication.errors import AuthSchemaNotReady

        with self.assertRaises(AuthSchemaNotReady), self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_billing_quotes SET digest=%s", ("a" * 64,)
            )

    def test_forged_candidate_cannot_poison_or_grant(self):
        _, _, order = self.order()
        self.created = {
            "amount": {"value": "1.01", "currency": "RUB"},
            "metadata": {"order_id": "wrong", "quote_digest": "wrong"},
        }
        self.status = "succeeded"
        self.billing.notify(
            "forged-payment", "payment.succeeded", UUID(order["order_id"])
        )
        self.billing.step()
        self.assertEqual(self.current().seats, 2)
        self.assertEqual(self.rows("auth_billing_orders")[0]["state"], "pending")
        self.assertIsNone(self.rows("auth_billing_orders")[0]["candidate_id"])
        self.due()
        self.status = "pending"
        self.billing.step()
        self.assertEqual(
            self.rows("auth_billing_orders")[0]["payment_id"], "payment-18"
        )

    def test_seat_churn_keeps_signed_allocation_history(self):
        self.order()
        self.billing.step()
        self.status = "succeeded"
        self.due()
        self.billing.step()
        self.assertEqual(self.current().seats, 4)
        before = self.rows("auth_resource_budgets")
        posts = self.rows("auth_usage_postings")
        self.order(seats=2)
        self.billing.step()
        self.assertEqual(self.current().seats, 2)
        allocations = self.rows("auth_billing_adjustments")
        self.assertEqual(len(allocations), 2)
        # Only the actual extra seats' 2-minute interval remains, no full reset.
        lower = min(a["included_entitlement"] for a in allocations)
        self.assertTrue(2000000 <= lower < 2000100, lower)
        self.assertEqual(self.rows("auth_resource_budgets"), before)
        self.assertEqual(self.rows("auth_usage_postings"), posts)

    def test_reduction_does_not_refund_or_reset_usage(self):
        self.order(seats=1)
        self.billing.step()
        self.assertFalse(self.calls)
        self.assertEqual(self.current().seats, 1)
        self.assertEqual(
            self.rows("auth_billing_adjustments")[0]["included_entitlement"], 1500000
        )

    def test_http_cookie_csrf_callback_and_body_boundaries(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from apps.api.authentication.csrf import AUTH_COOKIE
        from apps.api.routers import authentication, billing

        app = FastAPI()
        app.state.auth_access_store = self.store
        app.state.auth_session_service = self.service
        app.state.auth_subscription_service = self.billing
        app.include_router(authentication.router, prefix="/v1/auth")
        app.include_router(billing.router, prefix="/v1/billing")
        with (
            patch.dict(
                os.environ,
                {
                    "CISSTAT_AUTH_ALLOWED_ORIGINS": ORIGIN,
                    "CISSTAT_AUTH_CSRF_KEY": "auth18-test-key-" + "x" * 40,
                },
            ),
            TestClient(app, base_url=ORIGIN) as client,
        ):
            aid = str(self.account.account_id)
            self.assertEqual(
                client.get("/v1/billing/" + aid + "/subscription").status_code, 401
            )
            client.cookies.set(
                AUTH_COOKIE, self.token, domain="standalone.example", path="/"
            )
            self.assertEqual(
                client.get("/v1/billing/" + aid + "/subscription").status_code, 200
            )
            self.assertEqual(
                client.get(
                    "/v1/billing/" + aid + "/subscription",
                    headers={"X-API-Key": "fake"},
                ).status_code,
                401,
            )
            request = self.command("seat-request", self.body(SeatRequest, seats=4))
            body = self.body(Quote, request_id=UUID(request["request_id"])).model_dump(
                mode="json"
            )
            self.assertEqual(
                client.post("/v1/billing/" + aid + "/quotes", json=body).status_code,
                403,
            )
            proof = client.get("/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
                "csrf_token"
            ]
            result = client.post(
                "/v1/billing/" + aid + "/quotes",
                json=body,
                headers={"Origin": ORIGIN, "X-CSRF-Token": proof},
            )
            self.assertEqual(result.status_code, 200, result.text)
            notify = {
                "type": "notification",
                "event": "payment.succeeded",
                "object": {"id": "unknown-payment"},
            }
            self.assertEqual(
                client.post("/v1/billing/webhooks/yookassa", json=notify).status_code,
                200,
            )
            self.assertFalse(self.calls)
            self.assertFalse(self.rows("auth_provider_inbox"))
            self.assertEqual(self.current().seats, 2)
            self.assertEqual(
                client.post(
                    "/v1/billing/webhooks/yookassa", content=b"x" * 17000
                ).status_code,
                413,
            )
            self.assertEqual(
                client.post(
                    "/v1/billing/webhooks/yookassa",
                    json={"type": "notification", "object": []},
                ).status_code,
                422,
            )

    def test_provider_outage_and_expired_quote_do_not_charge(self):
        self.order()
        self.outage = True
        self.billing.step()
        self.assertEqual(self.current().seats, 2)
        self.assertFalse(self.rows("auth_billing_adjustments"))
        self.assertEqual(self.rows("auth_billing_orders")[0]["state"], "pending")

    def test_expired_accepted_but_never_attempted_order_is_held(self):
        self.order()
        self.now += timedelta(minutes=16)
        self.billing.step()
        self.assertFalse(self.calls)
        self.assertEqual(
            self.rows("auth_billing_orders")[0]["state"], "review_required"
        )


if __name__ == "__main__":
    unittest.main()
