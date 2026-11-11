"""Bounded YooKassa HTTP adapter. Callback fields are never payment proof."""

import re
from urllib.parse import urlsplit

import httpx


class ProviderUnavailable(Exception):
    """Unknown outcome; caller must preserve durable intent/idempotency key."""


class ProviderMismatch(Exception):
    """Authenticated provider object does not match the accepted quote."""


class YooKassa:
    def __init__(self, shop_id, secret, *, sandbox=True, transport=None):
        if not shop_id or not secret or sandbox is not True:
            raise ValueError("test shop required; live launch is separately gated")
        self.shop_id = shop_id
        self.sandbox = sandbox
        self._secret = secret
        self._transport = transport

    def __repr__(self):
        return "YooKassa(configured=True, sandbox=True)"

    def _request(self, method, path, **kwargs):
        try:
            with httpx.Client(  # noqa: SIM117 -- response stream closes before HTTP client
                auth=(self.shop_id, self._secret),
                timeout=httpx.Timeout(8, connect=3),
                follow_redirects=False,
                transport=self._transport,
                trust_env=False,
            ) as client:
                with client.stream(
                    method, "https://api.yookassa.ru/v3/" + path, **kwargs
                ) as r:
                    if r.status_code != 200:
                        raise ProviderUnavailable()
                    data = bytearray()
                    for chunk in r.iter_bytes():
                        if len(data) + len(chunk) > 65536:
                            raise ProviderUnavailable()
                        data.extend(chunk)
                    import json

                    value = json.loads(data)
                    if not isinstance(value, dict):
                        raise ProviderUnavailable()
                    return value
        except (httpx.HTTPError, ValueError, TypeError):
            raise ProviderUnavailable() from None

    @staticmethod
    def _id(payment_id):
        if not isinstance(payment_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,64}", payment_id
        ):
            raise ValueError("invalid payment id")
        return payment_id

    def fetch(self, payment_id):
        return self._request("GET", "payments/" + self._id(payment_id))

    # ---------------------------------------------------------------- refunds
    # AUTH-23: bounded refund surface. Only the test shop is constructible;
    # every refund is created with the refund_id idempotence key and confirmed
    # by an independent authenticated GET before any wallet movement.

    def create_refund(self, job):
        merchant = self._request("GET", "me")
        if (
            merchant.get("account_id") != self.shop_id
            or merchant.get("test") is not True
            or merchant.get("status") != "enabled"
        ):
            raise ProviderMismatch()
        minor = job["amount_minor"]
        return self._request(
            "POST",
            "refunds",
            headers={"Idempotence-Key": str(job["refund_id"])},
            json={
                "payment_id": job["payment_id"],
                "amount": {
                    "value": f"{minor // 100}.{minor % 100:02d}",
                    "currency": job["currency"],
                },
            },
        )

    def fetch_refund(self, refund_id):
        return self._request("GET", "refunds/" + self._id(refund_id))

    def validate_refund(self, r, job):
        expected = f"{job['amount_minor'] // 100}.{job['amount_minor'] % 100:02d}"
        if (
            r.get("id") != job["refund_id"]
            or r.get("payment_id") != job["payment_id"]
            or r.get("amount") != {"value": expected, "currency": job["currency"]}
            or r.get("status") not in ("pending", "succeeded", "canceled")
        ):
            raise ProviderMismatch()
        return {"status": r["status"], "refund_id": r["id"]}

    def create(self, order):
        # Before ANY payment POST, verify merchant environment with authenticated /me.
        # A mode flag alone must not turn accidentally supplied live credentials into checkout.
        merchant = self._request("GET", "me")
        if (
            merchant.get("account_id") != self.shop_id
            or merchant.get("test") is not True
            or merchant.get("status") != "enabled"
        ):
            raise ProviderMismatch()
        minor = order["amount_minor"]
        return self._request(
            "POST",
            "payments",
            headers={"Idempotence-Key": str(order["order_id"])},
            json={
                "amount": {
                    "value": f"{minor // 100}.{minor % 100:02d}",
                    "currency": order["currency"],
                },
                "capture": True,
                "confirmation": {
                    "type": "redirect",
                    "return_url": "https://datasetup.ru/",
                },
                # AUTH-22 top-ups carry their own bounded description; the
                # subscription default is preserved byte-for-byte.
                "description": order.get("description", "CISStat DataTime Lab seats"),
                "metadata": {
                    "order_id": str(order["order_id"]),
                    "quote_digest": order["digest"],
                },
            },
        )

    def validate(self, p, order):
        expected = f"{order['amount_minor'] // 100}.{order['amount_minor'] % 100:02d}"
        if (
            p.get("id") != order["payment_id"]
            or p.get("test") is not order["sandbox"]
            or p.get("recipient", {}).get("account_id") != order["shop_id"]
            or p.get("metadata", {}).get("order_id") != str(order["order_id"])
            or p.get("metadata", {}).get("quote_digest") != order["digest"]
            or p.get("amount") != {"value": expected, "currency": order["currency"]}
            or p.get("status")
            not in ("pending", "waiting_for_capture", "succeeded", "canceled")
            or p.get("status") == "succeeded"
            and p.get("paid") is not True
        ):
            raise ProviderMismatch()
        confirmation = p.get("confirmation") or {}
        url = confirmation.get("confirmation_url")
        if url:
            u = urlsplit(url)
            if (
                u.scheme != "https"
                or u.hostname not in ("yoomoney.ru", "yookassa.ru")
                or u.port not in (None, 443)
                or u.username
                or u.password
                or len(url) > 2048
            ):
                raise ProviderMismatch()
        return {"status": p["status"], "payment_id": p["id"], "checkout_url": url}
