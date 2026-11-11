"""AUTH-22 top-up quote/checkout/credit saga. Only a confirmed server payment
credits CU; callback fields are never proof (design docs/auth22/design.md).

Normative rules: spec_billing_accounts.md §13.4 (quote → payment → credit),
§13.3 (can_purchase_cu), E3/E5/E6; spec_auth_architecture.md AUTH-22. Saga
mechanics mirror the AUTH-18 subscription authority (lease/fence/attempts,
GET-confirmed proof, durable orders, bounded inbox wake-up); the credit itself
is the AUTH-21 wallet purchased lot bound to the order id, committed in the
same transaction as the order transition and the mandatory audit.
"""

import hashlib
import json
import os
from datetime import timedelta
from uuid import UUID, uuid4

from apps.api.accounts.team import TeamService, audit
from apps.api.authentication.context import auth_error
from apps.api.authentication.sessions import boundary
from apps.api.billing.provider import ProviderMismatch, ProviderUnavailable, YooKassa
from apps.api.billing.topup_migrations import check_schema
from apps.api.billing.wallet import WalletError, credit_purchased_order

WEBHOOK_EVENTS = frozenset(
    {
        "payment.succeeded",
        "payment.canceled",
        "payment.waiting_for_capture",
    }
)
TOPUP_STATES = frozenset(
    {"pending", "credited", "canceled", "review_required", "paid_review"}
)
# Terminal for the automatic saga; paid_review still admits the single audited
# operator resolution paid_review -> credited (design D3/D5).
TERMINAL_TOPUP_STATES = frozenset({"credited", "canceled", "paid_review"})

MAX_UNITS = 10**12
MAX_PRICE_MINOR = 10**10
QUOTE_TTL = timedelta(minutes=15)
QUOTE_RATE_LIMIT = 32
TOPUP_DESCRIPTION = "CISStat DataTime Lab CU top-up"


def topup_transition_allowed(old, new):
    """Pure mirror of the 0034 auth22_order_guard state rules."""
    if old not in TOPUP_STATES or new not in TOPUP_STATES or old == new:
        return False
    if old == "pending":
        return True
    if old == "paid_review":
        return new == "credited"
    return False


def validate_package(title, units, price_minor, currency, price_version, terms_version):
    """D1: operator catalog bounds; integer money/units; RUB-only v1."""
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 128:
        raise ValueError("package title required")
    if type(units) is not int or not 1 <= units <= MAX_UNITS:
        raise ValueError("integer micro-CU package units required")
    if type(price_minor) is not int or not 1 <= price_minor <= MAX_PRICE_MINOR:
        raise ValueError("integer minor-unit price required")
    if currency != "RUB":
        raise ValueError("RUB-only catalog in v1")
    for text in (price_version, terms_version):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 128:
            raise ValueError("versioned price/terms required")
    return True


def build_topup_snapshot(package, *, account_id, owner_id, quote_id, now, expires_at):
    """Server-side copy of the package row; the client supplies nothing."""
    return {
        "package_id": str(package["package_id"]),
        "title": package["title"],
        "units": int(package["units"]),
        "amount_minor": int(package["price_minor"]),
        "currency": package["currency"],
        "price_version": package["price_version"],
        "terms_version": package["terms_version"],
        "account_id": str(account_id),
        "owner_id": str(owner_id),
        "quote_id": str(quote_id),
        "account_version": None,  # filled by the service at quote time
        "priced_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


def snapshot_digest(snapshot):
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def configured_provider():
    if os.environ.get("CISSTAT_YOOKASSA_ENABLED") != "test":
        auth_error(503, "billing_not_configured")
    try:
        return YooKassa(
            os.environ["CISSTAT_YOOKASSA_SHOP_ID"],
            os.environ["CISSTAT_YOOKASSA_SECRET_KEY"],
        )
    except (KeyError, ValueError):
        auth_error(503, "billing_not_configured")


class TopupService(TeamService):
    def __init__(self, store=None, clock=None, provider=None):
        super().__init__(store, clock)
        self.provider = provider

    def gateway(self):
        return self.provider or configured_provider()

    def _topup_account(self, c, token, origin, aid):
        """§13.3 can_purchase_cu base: personal current OWNER of paid MULTI."""
        check_schema(c)
        actor = self._personal(c, token, origin)
        a = self._account(c, UUID(str(aid)), actor)
        self._owner(c, a, actor)
        if a["account_type"] != "multi" or a["plan"] in ("internal", "demo"):
            auth_error(403, "billing_unavailable")
        return actor, a

    def _active_wallet(self, c, aid):
        row = c.execute(
            "SELECT wallet_id,status FROM auth_wallets WHERE account_id=%s", (aid,)
        ).fetchone()
        if row is None:
            auth_error(403, "wallet_required")
        if row["status"] != "active":
            auth_error(403, "wallet_locked")
        return row

    @staticmethod
    def package_view(row):
        return {
            "package_id": str(row["package_id"]),
            "title": row["title"],
            "units": int(row["units"]),
            "price_minor": int(row["price_minor"]),
            "currency": row["currency"],
            "price_version": row["price_version"],
            "terms_version": row["terms_version"],
        }

    @staticmethod
    def view(row):
        return {
            "order_id": str(row["order_id"]),
            "state": row["state"],
            "units": int(row["units"]),
            "checkout_url": row["checkout_url"] if row["state"] == "pending" else None,
            "payment_id": row["payment_id"],
            "credited_at": row["credited_at"].isoformat() if row["credited_at"] else None,
        }

    # ---------------------------------------------------------------- trusted

    def provision_package(
        self, *, title, units, price_minor, currency, price_version, terms_version, reason
    ):
        """Trusted operator catalogs a price package; every command is audited."""
        _validate_reason_local(reason)
        validate_package(title, units, price_minor, currency, price_version, terms_version)
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            package_id = uuid4()
            c.execute(
                "INSERT INTO auth_topup_packages(package_id,title,units,price_minor,"
                "currency,price_version,terms_version,enabled,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,true,%s)",
                (
                    package_id,
                    title.strip(),
                    units,
                    price_minor,
                    currency,
                    price_version.strip(),
                    terms_version.strip(),
                    self._now(c),
                ),
            )
            audit(
                c,
                "operator:local",
                None,
                "billing-topup-package",
                reason,
                via="operator_cli",
                package_id=str(package_id),
                units=units,
                price_minor=price_minor,
            )
            return {"package_id": str(package_id)}

    def disable_package(self, package_id, *, reason):
        _validate_reason_local(reason)
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            row = c.execute(
                "UPDATE auth_topup_packages SET enabled=false WHERE package_id=%s AND enabled RETURNING package_id",
                (UUID(str(package_id)),),
            ).fetchone()
            if not row:
                raise ValueError("enabled package required")
            audit(
                c,
                "operator:local",
                None,
                "billing-topup-package",
                reason,
                via="operator_cli",
                package_id=str(row["package_id"]),
                enabled=False,
            )
            return {"package_id": str(row["package_id"]), "enabled": False}

    # ------------------------------------------------------------- OWNER HTTP

    @boundary
    def show(self, token, origin, aid):
        """Package catalog + bounded order history; read-only, no gateway."""
        with self._tx() as tx:
            c = tx.connection
            actor, a = self._topup_account(c, token, origin, aid)
            packages = c.execute(
                "SELECT * FROM auth_topup_packages WHERE enabled ORDER BY created_at,package_id LIMIT 50"
            ).fetchall()
            orders = c.execute(
                "SELECT * FROM auth_topup_orders WHERE account_id=%s ORDER BY created_at DESC LIMIT 20",
                (a["account_id"],),
            ).fetchall()
            return {
                "packages": [self.package_view(p) for p in packages],
                "orders": [self.view(o) for o in orders],
            }

    @boundary
    def quote(self, token, origin, aid, body):
        gateway = self.gateway()
        with self._tx() as tx:
            c = tx.connection
            actor, a = self._topup_account(c, token, origin, aid)
            self._active_wallet(c, a["account_id"])
            replay, kh, bh = self._replay(c, a, actor, "billing-topup-quote", body)
            if replay:
                return replay
            self._version(a, body.expected_version)
            pkg = c.execute(
                "SELECT * FROM auth_topup_packages WHERE package_id=%s AND enabled",
                (body.package_id,),
            ).fetchone()
            if not pkg:
                auth_error(404, "topup_package_not_found")
            now = self._now(c)
            if (
                c.execute(
                    "SELECT count(*) AS n FROM auth_topup_quotes WHERE account_id=%s AND created_at>%s",
                    (a["account_id"], now - timedelta(hours=24)),
                ).fetchone()["n"]
                >= QUOTE_RATE_LIMIT
            ):
                auth_error(429, "topup_quote_limit")
            qid = uuid4()
            expires = now + QUOTE_TTL
            snapshot = build_topup_snapshot(
                pkg,
                account_id=a["account_id"],
                owner_id=actor["subject_id"],
                quote_id=qid,
                now=now,
                expires_at=expires,
            )
            snapshot["account_version"] = a["entitlement_version"]
            # Merchant binding pins the checkout environment (design D6):
            # a quote created on one shop/sandbox never executes on another.
            snapshot["shop_id"] = gateway.shop_id
            snapshot["sandbox"] = gateway.sandbox
            digest = snapshot_digest(snapshot)
            c.execute(
                "INSERT INTO auth_topup_quotes VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    qid,
                    a["account_id"],
                    actor["subject_id"],
                    pkg["package_id"],
                    _jsonb(snapshot),
                    digest,
                    now,
                    expires,
                ),
            )
            result = {
                "quote_id": str(qid),
                "digest": digest,
                "expires_at": expires.isoformat(),
                "snapshot": snapshot,
            }
            return self._record(c, a, actor, "billing-topup-quote", body, (kh, bh), result)

    @boundary
    def confirm(self, token, origin, aid, body):
        gateway = self.gateway()
        with self._tx() as tx:
            c = tx.connection
            actor, a = self._topup_account(c, token, origin, aid)
            self._active_wallet(c, a["account_id"])
            q = c.execute(
                "SELECT * FROM auth_topup_quotes WHERE quote_id=%s AND account_id=%s",
                (body.quote_id, a["account_id"]),
            ).fetchone()
            if not q or q["owner_id"] != actor["subject_id"]:
                auth_error(404, "topup_quote_not_found")
            if q["digest"] != body.quote_digest:
                auth_error(409, "topup_quote_changed")
            old = c.execute(
                "SELECT * FROM auth_topup_orders WHERE quote_id=%s", (q["quote_id"],)
            ).fetchone()
            if old:
                # Repeated click with the same payload: same order, no second checkout.
                return self.view(old)
            replay, kh, bh = self._replay(c, a, actor, "billing-topup-order", body)
            if replay:
                return replay
            now = self._now(c)
            self._fresh(c, actor)
            s = q["snapshot"]
            self._version(a, s["account_version"])
            if now >= q["expires_at"]:
                auth_error(409, "topup_quote_expired")
            row = c.execute(
                "INSERT INTO auth_topup_orders(order_id,quote_id,account_id,units,next_attempt_at,created_at) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    uuid4(),
                    q["quote_id"],
                    a["account_id"],
                    int(s["units"]),
                    now,
                    now,
                ),
            ).fetchone()
            audit(
                c,
                actor["subject_id"],
                a["account_id"],
                "billing-topup-order",
                "OWNER accepted immutable top-up quote",
                order_id=str(row["order_id"]),
            )
            return self._record(
                c, a, actor, "billing-topup-order", body, (kh, bh), self.view(row)
            )

    # -------------------------------------------------------- untrusted inbox

    @boundary
    def notify(self, payment_id, event, order_hint=None):
        """Bounded untrusted wake-up; does not call provider or credit CU."""
        YooKassa._id(payment_id)
        if event not in WEBHOOK_EVENTS:
            return {"received": True}
        with self._tx() as tx:
            c = tx.connection
            # Deployment-order parity (AUTH-21 hooks): an unapplied 0034 is an
            # honest "nothing to wake" instead of breaking the shared webhook.
            if not c.execute(
                "SELECT to_regclass('auth_topup_orders') AS present"
            ).fetchone()["present"]:
                return {"received": True}
            row = c.execute(
                "SELECT * FROM auth_topup_orders WHERE payment_id=%s OR (order_id=%s AND payment_id IS NULL) LIMIT 1 FOR UPDATE",
                (payment_id, order_hint),
            ).fetchone()
            if (
                row
                and row["state"] == "pending"
                and (
                    not row["last_observed_at"]
                    or row["last_observed_at"] <= self._now(c) - timedelta(seconds=30)
                )
                and (
                    row["payment_id"]
                    or not row["candidate_id"]
                    or row["candidate_id"] == payment_id
                )
            ):
                if row["payment_id"]:
                    c.execute(
                        "INSERT INTO auth_topup_inbox VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (row["order_id"], payment_id, event, self._now(c)),
                    )
                c.execute(
                    "UPDATE auth_topup_orders SET candidate_id=%s,next_attempt_at=LEAST(next_attempt_at,%s) WHERE order_id=%s",
                    (payment_id, self._now(c), row["order_id"]),
                )
            return {"received": True}

    # ------------------------------------------------------------------ saga

    def claim(self):
        with self._tx() as tx:
            c = tx.connection
            # Deployment-order parity (AUTH-21 hooks): an unapplied 0034 means
            # honest "no work" for the shared worker instead of a crash loop.
            if not c.execute(
                "SELECT to_regclass('auth_topup_orders') AS present"
            ).fetchone()["present"]:
                return None
            now = self._now(c)
            row = c.execute(
                "SELECT * FROM auth_topup_orders WHERE state='pending' AND next_attempt_at<=%s AND (lease_until IS NULL OR lease_until<=%s) ORDER BY next_attempt_at FOR UPDATE SKIP LOCKED LIMIT 1",
                (now, now),
            ).fetchone()
            if not row:
                return None
            row = c.execute(
                "UPDATE auth_topup_orders SET first_attempt_at=COALESCE(first_attempt_at,%s),lease_until=%s,fence=fence+1,attempts=attempts+1 WHERE order_id=%s RETURNING *",
                (now, now + timedelta(seconds=45), row["order_id"]),
            ).fetchone()
            q = c.execute(
                "SELECT * FROM auth_topup_quotes WHERE quote_id=%s",
                (row["quote_id"],),
            ).fetchone()
            return (
                dict(row)
                | q["snapshot"]
                | {"digest": q["digest"], "quote_owner": q["owner_id"]}
            )

    def step(self):
        gateway = self.gateway()
        job = self.claim()
        if not job:
            return False
        if job["shop_id"] != gateway.shop_id or job["sandbox"] is not gateway.sandbox:
            self.finish(job, error="review_required")
            return True
        candidate = job["payment_id"] or job["candidate_id"]
        try:
            if (
                not candidate
                and job["attempts"] == 1
                and self.now_since(job["created_at"]) >= timedelta(minutes=15)
            ):
                self.finish(job, error="review_required")
                return True
            if candidate:
                raw = gateway.fetch(candidate)
                proof = gateway.validate(raw, job | {"payment_id": candidate})
            elif self.now_since(job["first_attempt_at"]) >= timedelta(hours=23):
                self.finish(job, error="review_required")
                return True
            else:
                raw = gateway.create(
                    job | {"description": TOPUP_DESCRIPTION}
                )
                # A POST response is normalized, then independently GET-confirmed
                # before any credit (browser return never credits, 13.4.3).
                pid = gateway._id(raw.get("id"))
                proof = gateway.validate(raw, job | {"payment_id": pid})
                if proof["status"] == "succeeded":
                    proof = gateway.validate(
                        gateway.fetch(pid), job | {"payment_id": pid}
                    )
            self.finish(job, proof=proof)
        except ProviderUnavailable:
            self.finish(job, error="retry")
        except (ProviderMismatch, ValueError, TypeError, KeyError, AttributeError):
            # Untrusted notification candidates cannot poison a valid durable payment intent.
            self.finish(
                job,
                error="candidate_invalid"
                if not job["payment_id"] and candidate
                else "review_required",
            )
        return True

    def now_since(self, stamp):
        with self._tx() as tx:
            return self._now(tx.connection) - stamp

    def finish(self, job, *, proof=None, error=None):
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            # Match the AUTH-18 lock order: identity -> account -> order.
            c.execute(
                "SELECT subject_id FROM auth_identities WHERE subject_id=%s FOR UPDATE",
                (job["quote_owner"],),
            ).fetchone()
            a = c.execute(
                "SELECT * FROM auth_accounts WHERE account_id=%s FOR UPDATE",
                (UUID(job["account_id"]),),
            ).fetchone()
            o = c.execute(
                "SELECT * FROM auth_topup_orders WHERE order_id=%s FOR UPDATE",
                (job["order_id"],),
            ).fetchone()
            now = self._now(c)
            if (
                o["state"] != "pending"
                or o["fence"] != job["fence"]
                or o["lease_until"] <= now
            ):
                return False
            if error:
                c.execute(
                    "UPDATE auth_topup_orders SET state=%s,candidate_id=NULL,lease_until=NULL,last_observed_at=%s,next_attempt_at=%s WHERE order_id=%s",
                    (
                        "review_required" if error == "review_required" else "pending",
                        now,
                        now
                        + timedelta(seconds=min(900, 15 * 2 ** min(o["attempts"], 6))),
                        o["order_id"],
                    ),
                )
                if error == "review_required":
                    audit(
                        c,
                        "provider:yookassa",
                        a["account_id"],
                        "billing-topup-review",
                        "provider proof/configuration requires review",
                        via="operator_cli",
                        order_id=str(o["order_id"]),
                    )
                return False
            if o["payment_id"] and o["payment_id"] != proof["payment_id"]:
                return False
            if (
                proof["payment_id"]
                and c.execute(
                    "SELECT 1 FROM auth_topup_orders WHERE payment_id=%s AND order_id<>%s",
                    (proof["payment_id"], o["order_id"]),
                ).fetchone()
            ):
                return False
            status = proof["status"]
            state = "canceled" if status == "canceled" else "pending"
            paid_at = None
            credited_at = None
            if status == "succeeded":
                # Money confirmed by the authenticated GET; credit and order
                # transition commit together (design D4). A missing/locked
                # wallet parks the order in paid_review without losing money (D5).
                state = "paid_review"
                paid_at = now
                try:
                    with c.transaction():
                        credit_purchased_order(
                            c,
                            a["account_id"],
                            int(job["units"]),
                            origin_order=str(o["order_id"]),
                            reason="AUTH-22 confirmed provider payment",
                        )
                    state = "credited"
                    credited_at = now
                except (WalletError, ValueError):
                    state = "paid_review"
            c.execute(
                "UPDATE auth_topup_orders SET state=%s,payment_id=%s,candidate_id=NULL,checkout_url=%s,paid_at=%s,credited_at=%s,lease_until=NULL,last_observed_at=%s,next_attempt_at=%s WHERE order_id=%s",
                (
                    state,
                    proof["payment_id"],
                    proof["checkout_url"],
                    paid_at,
                    credited_at,
                    now,
                    now + timedelta(seconds=60),
                    o["order_id"],
                ),
            )
            audit(
                c,
                "provider:yookassa",
                a["account_id"],
                "billing-topup-" + state,
                "verified provider observation",
                via="operator_cli",
                order_id=str(o["order_id"]),
            )
            return True

    def reconcile(self, order_id, payment_id, *, reason):
        """Trusted recovery of an unknown outcome. API proof still mandatory."""
        YooKassa._id(payment_id)
        _validate_reason_local(reason)
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            hint = c.execute(
                "SELECT account_id FROM auth_topup_orders WHERE order_id=%s",
                (UUID(str(order_id)),),
            ).fetchone()
            if not hint:
                raise ValueError("known order required")
            c.execute(
                "SELECT account_id FROM auth_accounts WHERE account_id=%s FOR UPDATE",
                (hint["account_id"],),
            ).fetchone()
            o = c.execute(
                "SELECT * FROM auth_topup_orders WHERE order_id=%s FOR UPDATE",
                (UUID(str(order_id)),),
            ).fetchone()
            if (
                o["state"] not in ("pending", "review_required")
                or o["payment_id"]
                and o["payment_id"] != payment_id
            ):
                raise ValueError("order cannot be reconciled")
            c.execute(
                "UPDATE auth_topup_orders SET state='pending',candidate_id=%s,lease_until=NULL,fence=fence+1,next_attempt_at=%s WHERE order_id=%s",
                (payment_id, self._now(c), o["order_id"]),
            )
            audit(
                c,
                "operator:local",
                o["account_id"],
                "billing-topup-reconcile",
                reason,
                via="operator_cli",
                order_id=str(o["order_id"]),
            )
            return {"queued": True, "order_id": str(o["order_id"])}

    def credit_paid(self, order_id, *, reason):
        """Trusted paid_review -> credited after the manual wallet credit.

        Requires an existing purchased lot with origin_order=order_id; the
        AUTH-21 unique basis makes a second lot for the same order impossible.
        """
        _validate_reason_local(reason)
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            o = c.execute(
                "SELECT * FROM auth_topup_orders WHERE order_id=%s FOR UPDATE",
                (UUID(str(order_id)),),
            ).fetchone()
            if not o:
                raise ValueError("known order required")
            if o["state"] != "paid_review":
                raise ValueError("paid_review order required")
            lot = c.execute(
                "SELECT 1 FROM auth_wallet_lots WHERE account_id=%s AND origin_order=%s",
                (o["account_id"], str(o["order_id"])),
            ).fetchone()
            if not lot:
                raise ValueError("purchased lot for this order required")
            c.execute(
                "UPDATE auth_topup_orders SET state='credited',credited_at=%s WHERE order_id=%s",
                (self._now(c), o["order_id"]),
            )
            audit(
                c,
                "operator:local",
                o["account_id"],
                "billing-topup-credited",
                reason,
                via="operator_cli",
                order_id=str(o["order_id"]),
            )
            return {"order_id": str(o["order_id"]), "state": "credited"}


def _validate_reason_local(reason):
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 256:
        raise ValueError("reason required")


def _jsonb(value):
    from psycopg.types.json import Jsonb

    return Jsonb(value)
