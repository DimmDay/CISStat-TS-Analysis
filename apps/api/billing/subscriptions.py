"""Personal OWNER quote authority and durable YooKassa saga. No I/O inside SQL locks."""

import os
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from apps.api.accounts.team import TeamService, audit
from apps.api.authentication.context import auth_error
from apps.api.authentication.sessions import boundary
from apps.api.workers.connection import bind_connection

from .provider import ProviderMismatch, ProviderUnavailable, YooKassa
from .subscription_contract import cumulative_allocation, micros, prorate
from .subscription_migrations import check_schema


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


class SubscriptionService(TeamService):
    def __init__(self, store=None, clock=None, provider=None):
        super().__init__(store, clock)
        self.provider = provider

    def gateway(self):
        return self.provider or configured_provider()

    def owner(self, c, token, origin, aid):
        check_schema(c)
        actor = self._personal(c, token, origin)
        a = self._account(c, UUID(str(aid)), actor)
        self._owner(c, a, actor)
        if a["account_type"] != "multi" or a["plan"] in ("internal", "demo"):
            auth_error(403, "billing_unavailable")
        return actor, a

    def cycle(self, c, aid):
        cy = c.execute(
            "SELECT * FROM auth_billing_cycles WHERE account_id=%s FOR UPDATE", (aid,)
        ).fetchone()
        if not cy or not cy["starts_at"] <= self._now(c) < cy["ends_at"]:
            auth_error(409, "billing_cycle_unavailable")
        return cy

    @boundary
    def quote(self, token, origin, aid, body):
        gateway = self.gateway()
        with self._tx() as tx:
            c = tx.connection
            actor, a = self.owner(c, token, origin, aid)
            replay, kh, bh = self._replay(c, a, actor, "billing-quote", body)
            if replay:
                return replay
            self._version(a, body.expected_version)
            cy = self.cycle(c, a["account_id"])
            cfg = cy["config"]
            if (
                cfg["shop_id"] != gateway.shop_id
                or cfg["sandbox"] is not gateway.sandbox
                or a["seats"] != cy["seats"]
            ):
                auth_error(409, "billing_cycle_unavailable")
            r = c.execute(
                "SELECT * FROM auth_seat_requests WHERE request_id=%s AND account_id=%s FOR UPDATE",
                (body.request_id, a["account_id"]),
            ).fetchone()
            now = self._now(c)
            if (
                not r
                or r["state"] != "pending"
                or r["expires_at"] <= now
                or r["requested_by"] != actor["subject_id"]
            ):
                auth_error(409, "seat_request_unavailable")
            if c.execute(
                "SELECT 1 FROM auth_billing_orders WHERE request_id=%s",
                (body.request_id,),
            ).fetchone():
                auth_error(409, "billing_order_exists")
            if (
                c.execute(
                    "SELECT count(*) AS n FROM auth_billing_quotes WHERE request_id=%s",
                    (body.request_id,),
                ).fetchone()["n"]
                >= 32
            ):
                auth_error(429, "billing_quote_limit")
            delta = r["seats"] - a["seats"]
            if delta <= 0 and not cfg["allow_reduction"]:
                auth_error(409, "billing_reduction_not_approved")
            remaining = micros(cy["ends_at"] - now)
            duration = micros(cy["ends_at"] - cy["starts_at"])
            qid = uuid4()
            snapshot = {
                **cfg,
                "quote_id": str(qid),
                "request_id": str(r["request_id"]),
                "account_id": str(a["account_id"]),
                "owner_id": str(actor["subject_id"]),
                "cycle_id": str(cy["cycle_id"]),
                "cycle_version": cy["version"],
                "account_version": a["entitlement_version"],
                "old_seats": a["seats"],
                "seats": r["seats"],
                "remaining_us": remaining,
                "duration_us": duration,
                "amount_minor": prorate(
                    delta, cfg["seat_price_minor"], remaining, duration
                ),
                "delta_numerator": delta * cfg["included_per_seat"] * remaining,
                "proration_at": now.isoformat(),
                "cycle_ends_at": cy["ends_at"].isoformat(),
            }
            digest = self._digest(snapshot)
            expires = min(now + timedelta(minutes=15), r["expires_at"], cy["ends_at"])
            c.execute(
                "INSERT INTO auth_billing_quotes VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    qid,
                    a["account_id"],
                    r["request_id"],
                    actor["subject_id"],
                    cy["cycle_id"],
                    Jsonb(snapshot),
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
            return self._record(c, a, actor, "billing-quote", body, (kh, bh), result)

    @boundary
    def confirm(self, token, origin, aid, qid, body):
        gateway = self.gateway()
        with self._tx() as tx:
            c = tx.connection
            actor, a = self.owner(c, token, origin, aid)
            q = c.execute(
                "SELECT * FROM auth_billing_quotes WHERE quote_id=%s AND account_id=%s",
                (UUID(str(qid)), a["account_id"]),
            ).fetchone()
            if not q or q["owner_id"] != actor["subject_id"]:
                auth_error(404, "billing_quote_not_found")
            s = q["snapshot"]
            if q["digest"] != body.quote_digest:
                auth_error(409, "billing_quote_changed")
            old = c.execute(
                "SELECT * FROM auth_billing_orders WHERE quote_id=%s", (q["quote_id"],)
            ).fetchone()
            if old:
                return self.view(old)
            now = self._now(c)
            cy = self.cycle(c, a["account_id"])
            self._fresh(c, actor)
            self._version(a, s["account_version"])
            r = c.execute(
                "SELECT * FROM auth_seat_requests WHERE request_id=%s FOR UPDATE",
                (q["request_id"],),
            ).fetchone()
            if (
                now >= q["expires_at"]
                or r["state"] != "pending"
                or r["requested_by"] != actor["subject_id"]
                or s["cycle_version"] != cy["version"]
                or s["shop_id"] != gateway.shop_id
                or s["sandbox"] is not gateway.sandbox
            ):
                auth_error(409, "billing_quote_expired")
            row = c.execute(
                "INSERT INTO auth_billing_orders(order_id,quote_id,account_id,request_id,next_attempt_at,created_at) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                (uuid4(), q["quote_id"], a["account_id"], q["request_id"], now, now),
            ).fetchone()
            audit(
                c,
                actor["subject_id"],
                a["account_id"],
                "billing-order",
                "OWNER accepted immutable quote",
                order_id=str(row["order_id"]),
            )
            return self.view(row)

    @staticmethod
    def view(row):
        return {
            "order_id": str(row["order_id"]),
            "state": row["state"],
            "checkout_url": row["checkout_url"] if row["state"] == "pending" else None,
            "payment_id": row["payment_id"],
        }

    @boundary
    def show(self, token, origin, aid):
        with self._tx() as tx:
            c = tx.connection
            _, a = self.owner(c, token, origin, aid)
            cy = c.execute(
                "SELECT * FROM auth_billing_cycles WHERE account_id=%s",
                (a["account_id"],),
            ).fetchone()
            orders = c.execute(
                "SELECT * FROM auth_billing_orders WHERE account_id=%s ORDER BY created_at DESC LIMIT 20",
                (a["account_id"],),
            ).fetchall()
            return {
                "seats": a["seats"],
                "orders": [self.view(o) for o in orders],
                "subscription": None
                if not cy
                else {
                    "cycle_id": str(cy["cycle_id"]),
                    "ends_at": cy["ends_at"].isoformat(),
                    "sandbox": cy["config"]["sandbox"],
                    "included_entitlement": cumulative_allocation(
                        cy["config"]["base_included"],
                        int(cy["adjustment_numerator"]),
                        micros(cy["ends_at"] - cy["starts_at"]),
                    ),
                    "spendable_credit_issued": False,
                },
            }

    @boundary
    def notify(self, payment_id, event, order_hint=None):
        """Bounded untrusted wake-up; does not call provider or alter entitlement."""
        YooKassa._id(payment_id)
        if event not in (
            "payment.succeeded",
            "payment.canceled",
            "payment.waiting_for_capture",
        ):
            return {"received": True}
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            # Only known bound payments or UUID order hints. Unknown callbacks allocate no rows.
            row = c.execute(
                "SELECT * FROM auth_billing_orders WHERE payment_id=%s OR (order_id=%s AND payment_id IS NULL) LIMIT 1 FOR UPDATE",
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
                # Max 3 events per bound payment, one unverified candidate per order.
                if row["payment_id"]:
                    c.execute(
                        "INSERT INTO auth_provider_inbox VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (row["order_id"], payment_id, event, self._now(c)),
                    )
                c.execute(
                    "UPDATE auth_billing_orders SET candidate_id=%s,next_attempt_at=LEAST(next_attempt_at,%s) WHERE order_id=%s",
                    (payment_id, self._now(c), row["order_id"]),
                )
            return {"received": True}

    def provision_cycle(
        self,
        aid,
        *,
        starts_at,
        ends_at,
        seat_price_minor,
        included_per_seat,
        price_version,
        terms_version,
        reason,
        allow_reduction=False,
    ):
        """Trusted operator records existing entitlement. Does NOT grant seats or spendable CU."""
        gateway = self.gateway()
        if (
            starts_at.tzinfo is None
            or ends_at.tzinfo is None
            or not starts_at < ends_at
            or micros(ends_at - starts_at) > 366 * 86400 * 1000000
            or type(seat_price_minor) is not int
            or not 1 <= seat_price_minor <= 10**10
            or type(included_per_seat) is not int
            or not 0 <= included_per_seat <= 10**12
            or not isinstance(price_version, str)
            or not 1 <= len(price_version) <= 128
            or not isinstance(terms_version, str)
            or not 1 <= len(terms_version) <= 128
            or not isinstance(reason, str)
            or not 1 <= len(reason.strip()) <= 256
            or type(allow_reduction) is not bool
        ):
            raise ValueError("approved integer catalog/cycle required")
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            a = c.execute(
                "SELECT * FROM auth_accounts WHERE account_id=%s FOR UPDATE",
                (UUID(str(aid)),),
            ).fetchone()
            if (
                not a
                or a["account_type"] != "multi"
                or a["plan"] in ("demo", "internal")
                or a["status"] != "active"
                or a["plan_expires_at"] != ends_at
            ):
                raise ValueError("paid MULTI required")
            cfg = {
                "shop_id": gateway.shop_id,
                "sandbox": True,
                "currency": "RUB",
                "seat_price_minor": seat_price_minor,
                "included_per_seat": included_per_seat,
                "base_included": a["seats"] * included_per_seat,
                "price_version": price_version,
                "terms_version": terms_version,
                "allow_reduction": allow_reduction,
                "reduction_policy": "no-refund" if allow_reduction else "disabled",
            }
            row = c.execute(
                "INSERT INTO auth_billing_cycles(cycle_id,account_id,starts_at,ends_at,config,seats) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                (uuid4(), a["account_id"], starts_at, ends_at, Jsonb(cfg), a["seats"]),
            ).fetchone()
            audit(
                c,
                "operator:local",
                a["account_id"],
                "billing-cycle",
                reason,
                via="operator_cli",
            )
            return str(row["cycle_id"])

    def reconcile(self, order_id, payment_id, *, reason):
        """Trusted recovery of an unknown outcome. API proof still mandatory; never a paid flag."""
        YooKassa._id(payment_id)
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 256:
            raise ValueError("reason required")
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            # Same account -> order order as other commands. No session/actor claims accepted.
            hint = c.execute(
                "SELECT account_id FROM auth_billing_orders WHERE order_id=%s",
                (UUID(str(order_id)),),
            ).fetchone()
            if not hint:
                raise ValueError("known order required")
            c.execute(
                "SELECT account_id FROM auth_accounts WHERE account_id=%s FOR UPDATE",
                (hint["account_id"],),
            ).fetchone()
            o = c.execute(
                "SELECT * FROM auth_billing_orders WHERE order_id=%s FOR UPDATE",
                (UUID(str(order_id)),),
            ).fetchone()
            if (
                o["state"] not in ("pending", "review_required")
                or o["payment_id"]
                and o["payment_id"] != payment_id
            ):
                raise ValueError("order cannot be reconciled")
            c.execute(
                "UPDATE auth_billing_orders SET state='pending',candidate_id=%s,lease_until=NULL,fence=fence+1,next_attempt_at=%s WHERE order_id=%s",
                (payment_id, self._now(c), o["order_id"]),
            )
            audit(
                c,
                "operator:local",
                o["account_id"],
                "billing-reconcile",
                reason,
                via="operator_cli",
                order_id=str(o["order_id"]),
            )
            return {"queued": True, "order_id": str(o["order_id"])}

    def claim(self):
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            now = self._now(c)
            row = c.execute(
                "SELECT * FROM auth_billing_orders WHERE state='pending' AND next_attempt_at<=%s AND (lease_until IS NULL OR lease_until<=%s) ORDER BY next_attempt_at FOR UPDATE SKIP LOCKED LIMIT 1",
                (now, now),
            ).fetchone()
            if not row:
                return None
            row = c.execute(
                "UPDATE auth_billing_orders SET first_attempt_at=COALESCE(first_attempt_at,%s),lease_until=%s,fence=fence+1,attempts=attempts+1 WHERE order_id=%s RETURNING *",
                (now, now + timedelta(seconds=45), row["order_id"]),
            ).fetchone()
            q = c.execute(
                "SELECT * FROM auth_billing_quotes WHERE quote_id=%s",
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
            if job["amount_minor"] == 0:
                proof = {
                    "status": "succeeded",
                    "payment_id": None,
                    "checkout_url": None,
                }
            elif candidate:
                raw = gateway.fetch(candidate)
                proof = gateway.validate(raw, job | {"payment_id": candidate})
            elif self.now_since(job["first_attempt_at"]) >= timedelta(hours=23):
                self.finish(job, error="review_required")
                return True
            else:
                raw = gateway.create(job)
                # A POST response is normalized, then independently GET-confirmed before granting.
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
            # Match AUTH-17 identity -> Account order; never lock Account after order/cycle.
            c.execute(
                "SELECT subject_id FROM auth_identities WHERE subject_id=%s FOR UPDATE",
                (job["quote_owner"],),
            ).fetchone()
            a = c.execute(
                "SELECT * FROM auth_accounts WHERE account_id=%s FOR UPDATE",
                (UUID(job["account_id"]),),
            ).fetchone()
            cy = c.execute(
                "SELECT * FROM auth_billing_cycles WHERE cycle_id=%s FOR UPDATE",
                (UUID(job["cycle_id"]),),
            ).fetchone()
            o = c.execute(
                "SELECT * FROM auth_billing_orders WHERE order_id=%s FOR UPDATE",
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
                    "UPDATE auth_billing_orders SET state=%s,candidate_id=NULL,lease_until=NULL,last_observed_at=%s,next_attempt_at=%s WHERE order_id=%s",
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
                        "billing-review",
                        "provider proof/configuration requires review",
                        via="operator_cli",
                    )
                return False
            if o["payment_id"] and o["payment_id"] != proof["payment_id"]:
                return False
            if (
                proof["payment_id"]
                and c.execute(
                    "SELECT 1 FROM auth_billing_orders WHERE payment_id=%s AND order_id<>%s",
                    (proof["payment_id"], o["order_id"]),
                ).fetchone()
            ):
                return False
            status = proof["status"]
            state = "canceled" if status == "canceled" else "pending"
            paid_at = None
            if status == "succeeded":
                state = "paid_review"
                paid_at = now
                if (
                    a["seats"] == job["old_seats"]
                    and cy["version"] == job["cycle_version"]
                    and now < cy["ends_at"]
                ):
                    # Savepoint catches expected stale-owner/request/expiry conflicts only.
                    try:
                        with c.transaction(), bind_connection(c, self.store):
                            TeamService(self.store, self.clock).confirm_capacity(
                                a["account_id"],
                                o["request_id"],
                                expected_version=job["account_version"],
                                confirmation_ref="yk:" + str(o["order_id"]),
                                reason="AUTH-18 verified provider payment / approved reduction",
                            )
                            numerator = (
                                int(cy["adjustment_numerator"]) + job["delta_numerator"]
                            )
                            allocation = cumulative_allocation(
                                cy["config"]["base_included"],
                                numerator,
                                job["duration_us"],
                            )
                            c.execute(
                                "INSERT INTO auth_billing_adjustments VALUES (%s,%s,%s,%s,%s,%s)",
                                (
                                    o["order_id"],
                                    cy["cycle_id"],
                                    job["delta_numerator"],
                                    job["duration_us"],
                                    allocation,
                                    now,
                                ),
                            )
                            c.execute(
                                "UPDATE auth_billing_cycles SET seats=%s,adjustment_numerator=%s,version=version+1 WHERE cycle_id=%s",
                                (job["seats"], numerator, cy["cycle_id"]),
                            )
                            state = "applied"
                    except HTTPException as exc:
                        if exc.status_code not in (403, 404, 409):
                            raise
            c.execute(
                "UPDATE auth_billing_orders SET state=%s,payment_id=%s,candidate_id=NULL,checkout_url=%s,paid_at=%s,lease_until=NULL,last_observed_at=%s,next_attempt_at=%s WHERE order_id=%s",
                (
                    state,
                    proof["payment_id"],
                    proof["checkout_url"],
                    paid_at,
                    now,
                    now + timedelta(seconds=60),
                    o["order_id"],
                ),
            )
            audit(
                c,
                "provider:yookassa",
                a["account_id"],
                "billing-" + state,
                "verified provider observation",
                via="operator_cli",
                order_id=str(o["order_id"]),
            )
            return True
