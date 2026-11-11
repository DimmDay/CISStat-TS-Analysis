"""AUTH-23 refund/dispute authority. Only a provider-confirmed refund moves
money back; an unknown outcome keeps the hold (spec_billing_accounts.md
§13.7.3), and a spent chargeback becomes exposure in auth_disputes, never a
negative available balance (§13.7.5).

Saga mechanics mirror the AUTH-22 top-up authority (lease/fence/attempts,
bounded backoff, POST + independent GET-confirmed proof, trusted reconcile);
the wallet movements reuse the AUTH-21 bucket events committed in the same
transaction as the refund/dispute transition and the mandatory audit.
"""

from datetime import timedelta
from uuid import UUID, uuid4

from apps.api.accounts.team import audit
from apps.api.authentication.context import auth_error
from apps.api.authentication.sessions import boundary
from apps.api.billing.provider import (
    ProviderMismatch,
    ProviderUnavailable,
    YooKassa,
)
from apps.api.billing.refund_migrations import check_schema
from apps.api.billing.topups import TopupService
from apps.api.billing.topups import _validate_reason_local
from apps.api.billing.wallet import (
    WalletError,
    dispute_hold_in_tx,
    refund_hold_in_tx,
    refund_release_in_tx,
)

REFUND_STATES = frozenset({"pending", "refunded", "failed", "review_required"})
TERMINAL_REFUND_STATES = frozenset({"refunded", "failed"})
DISPUTE_STATES = frozenset({"open", "lost", "won"})
TERMINAL_DISPUTE_STATES = frozenset({"lost", "won"})

MAX_WINDOW_DAYS = 90
DEFAULT_WINDOW_DAYS = 14
REFUND_DESCRIPTION = "CISStat DataTime Lab CU refund"


def refund_transition_allowed(old, new):
    """Pure mirror of the 0035 auth23_refund_guard state rules."""
    if old not in REFUND_STATES or new not in REFUND_STATES:
        return False
    if old == new:
        return True
    if old == "pending":
        return new in ("refunded", "failed", "review_required")
    if old == "review_required":
        # Trusted reconcile requeues; the saga still needs a provider proof.
        return new == "pending"
    return False


def dispute_transition_allowed(old, new):
    """Pure mirror of the 0035 auth23_dispute_guard state rules."""
    if old not in DISPUTE_STATES or new not in DISPUTE_STATES or old == new:
        return False
    return old == "open" and new in ("lost", "won")


def window_days(environ=None):
    """Refund policy window in days: CISSTAT_TOPUP_REFUND_DAYS, 0..90."""
    import os

    raw = (environ or os.environ).get("CISSTAT_TOPUP_REFUND_DAYS")
    if raw is None:
        return DEFAULT_WINDOW_DAYS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError("integer CISSTAT_TOPUP_REFUND_DAYS required") from None
    if not 0 <= value <= MAX_WINDOW_DAYS:
        raise ValueError("CISSTAT_TOPUP_REFUND_DAYS must be within 0..90")
    return value


def within_window(credited_at, days, now):
    """§13.7.1: the owner's window is fixed against credited_at."""
    if type(days) is not int or not 0 <= days <= MAX_WINDOW_DAYS:
        raise ValueError("integer window days required")
    if now < credited_at:
        raise ValueError("credited_at must not be in the future")
    return now <= credited_at + timedelta(days=days)


def refund_backoff(attempts):
    """Same bounded exponential schedule as the AUTH-22 saga."""
    return timedelta(seconds=min(900, 15 * 2 ** min(attempts, 6)))


def refund_view(row):
    """Safe projection: no lease/fencing internals, no owner identifiers."""
    return {
        "refund_id": str(row["refund_id"]),
        "order_id": str(row["order_id"]),
        "state": row["state"],
        "units": int(row["units"]),
        "amount_minor": int(row["amount_minor"]),
        "currency": row["currency"],
        "terms_version": row["terms_version"],
        "provider_refund_id": row["provider_refund_id"],
        "created_at": row["created_at"].isoformat(),
        "decided_at": row["decided_at"].isoformat() if row["decided_at"] else None,
    }


def dispute_view(row):
    return {
        "dispute_id": str(row["dispute_id"]),
        "order_id": str(row["order_id"]),
        "state": row["state"],
        "spent_units": int(row["spent_units"]),
        "disputed_units": int(row["disputed_units"]),
        "amount_minor": int(row["amount_minor"]),
        "currency": row["currency"],
        "opened_reason": row["opened_reason"],
        "resolution_reason": row["resolution_reason"],
        "created_at": row["created_at"].isoformat(),
        "resolved_at": row["resolved_at"].isoformat() if row["resolved_at"] else None,
    }


class RefundService(TopupService):
    """OWNER refund requests + trusted dispute commands; saga step for the
    shared billing worker. No client path opens or resolves a dispute."""

    # ------------------------------------------------------------- OWNER HTTP

    @boundary
    def request(self, token, origin, aid, order_id, body):
        """OWNER full refund of a credited whole unused purchased lot."""
        gateway = self.gateway()
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            actor, a = self._topup_account(c, token, origin, aid)
            o = c.execute(
                "SELECT * FROM auth_topup_orders WHERE order_id=%s AND account_id=%s FOR UPDATE",
                (UUID(str(order_id)), a["account_id"]),
            ).fetchone()
            if not o:
                auth_error(404, "topup_order_not_found")
            existing = c.execute(
                "SELECT * FROM auth_refund_orders WHERE order_id=%s",
                (o["order_id"],),
            ).fetchone()
            if existing:
                # Repeated click with any payload: same refund, no second hold.
                return refund_view(existing)
            replay, kh, bh = self._replay(c, a, actor, "billing-refund-request", body)
            if replay:
                return replay
            self._version(a, body.expected_version)
            if o["state"] != "credited" or not o["credited_at"]:
                auth_error(409, "refund_not_eligible")
            now = self._now(c)
            days = window_days()
            if not within_window(o["credited_at"], days, now):
                auth_error(403, "refund_window")
            lot = c.execute(
                "SELECT * FROM auth_wallet_lots WHERE account_id=%s AND origin_order=%s AND source='purchased' FOR UPDATE",
                (a["account_id"], str(o["order_id"])),
            ).fetchone()
            if not lot:
                auth_error(409, "refund_not_eligible")
            q = c.execute(
                "SELECT snapshot FROM auth_topup_quotes WHERE quote_id=%s",
                (o["quote_id"],),
            ).fetchone()
            snapshot = q["snapshot"] if q else {}
            amount_minor = int(snapshot.get("amount_minor") or 0)
            currency = snapshot.get("currency") or ""
            terms_version = str(snapshot.get("terms_version") or "")
            if amount_minor <= 0 or currency != "RUB" or not 1 <= len(terms_version) <= 128:
                # Without a bound price/terms snapshot a refund is unprovable.
                auth_error(409, "refund_not_eligible")
            try:
                refund_hold_in_tx(
                    c, lot, reason="AUTH-23 owner refund request"
                )
            except WalletError:
                auth_error(409, "refund_not_eligible")
            refund_id = uuid4()
            row = c.execute(
                "INSERT INTO auth_refund_orders(refund_id,order_id,account_id,lot_id,"
                "owner_id,units,amount_minor,currency,terms_version,window_days,"
                "state,next_attempt_at,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s) RETURNING *",
                (
                    refund_id,
                    o["order_id"],
                    a["account_id"],
                    lot["lot_id"],
                    actor["subject_id"],
                    int(o["units"]),
                    amount_minor,
                    currency,
                    terms_version,
                    days,
                    now,
                    now,
                ),
            ).fetchone()
            audit(
                c,
                actor["subject_id"],
                a["account_id"],
                "billing-refund-request",
                body.reason,
                refund_id=str(refund_id),
                order_id=str(o["order_id"]),
            )
            return self._record(
                c, a, actor, "billing-refund-request", body, (kh, bh),
                refund_view(row),
            )

    @boundary
    def refund_get(self, token, origin, aid, refund_id):
        """OWNER read of one refund; object ids are checked per account."""
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            actor, a = self._topup_account(c, token, origin, aid)
            row = c.execute(
                "SELECT * FROM auth_refund_orders WHERE refund_id=%s AND account_id=%s",
                (UUID(str(refund_id)), a["account_id"]),
            ).fetchone()
            if not row:
                auth_error(404, "refund_not_found")
            return refund_view(row)

    # ------------------------------------------------------------------ saga

    def claim(self):
        with self._tx() as tx:
            c = tx.connection
            # Deployment-order parity: an unapplied 0035 is honest "no work"
            # for the shared worker instead of a crash loop.
            if not c.execute(
                "SELECT to_regclass('auth_refund_orders') AS present"
            ).fetchone()["present"]:
                return None
            now = self._now(c)
            row = c.execute(
                "SELECT r.*,o.payment_id AS payment_id FROM auth_refund_orders r "
                "JOIN auth_topup_orders o ON o.order_id=r.order_id "
                "WHERE r.state='pending' AND r.next_attempt_at<=%s "
                "AND (r.lease_until IS NULL OR r.lease_until<=%s) "
                "ORDER BY r.next_attempt_at FOR UPDATE SKIP LOCKED LIMIT 1",
                (now, now),
            ).fetchone()
            if not row:
                return None
            payment_id = row["payment_id"]
            row = c.execute(
                "UPDATE auth_refund_orders SET first_attempt_at=COALESCE(first_attempt_at,%s),"
                "lease_until=%s,fence=fence+1,attempts=attempts+1 WHERE refund_id=%s RETURNING *",
                (now, now + timedelta(seconds=45), row["refund_id"]),
            ).fetchone()
            # RETURNING * loses the join column; the provider proof needs it.
            return dict(row) | {"payment_id": payment_id}

    def step(self):
        gateway = self.gateway()
        job = self.claim()
        if not job:
            return False
        candidate = job["provider_refund_id"]
        try:
            if candidate:
                raw = gateway.fetch_refund(candidate)
                proof = gateway.validate_refund(
                    raw, job | {"refund_id": candidate}
                )
            else:
                raw = gateway.create_refund(job)
                rid = YooKassa._id(raw.get("id"))
                proof = gateway.validate_refund(raw, job | {"refund_id": rid})
                if proof["status"] == "succeeded":
                    # A POST response is normalized, then independently
                    # GET-confirmed before any wallet movement.
                    proof = gateway.validate_refund(
                        gateway.fetch_refund(rid), job | {"refund_id": rid}
                    )
            self.finish(job, proof=proof)
        except ProviderUnavailable:
            # Unknown outcome: the hold stays, only the schedule moves.
            self.finish(job, error="retry")
        except (ProviderMismatch, ValueError, TypeError, KeyError, AttributeError):
            self.finish(job, error="review_required")
        return True

    def finish(self, job, *, proof=None, error=None):
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            # Match the inherited lock order: identity -> account -> refund.
            # The claim row carries UUID objects; psycopg adapts them directly.
            c.execute(
                "SELECT subject_id FROM auth_identities WHERE subject_id=%s FOR UPDATE",
                (job["owner_id"],),
            ).fetchone()
            a = c.execute(
                "SELECT * FROM auth_accounts WHERE account_id=%s FOR UPDATE",
                (job["account_id"],),
            ).fetchone()
            r = c.execute(
                "SELECT * FROM auth_refund_orders WHERE refund_id=%s FOR UPDATE",
                (job["refund_id"],),
            ).fetchone()
            now = self._now(c)
            if (
                r["state"] != "pending"
                or r["fence"] != job["fence"]
                or r["lease_until"] <= now
            ):
                return False
            if error:
                state = "review_required" if error == "review_required" else "pending"
                c.execute(
                    "UPDATE auth_refund_orders SET state=%s,lease_until=NULL,next_attempt_at=%s WHERE refund_id=%s",
                    (
                        state,
                        now + (timedelta(seconds=0) if state == "review_required" else refund_backoff(r["attempts"])),
                        r["refund_id"],
                    ),
                )
                if state == "review_required":
                    audit(
                        c,
                        "provider:yookassa",
                        a["account_id"],
                        "billing-refund-review",
                        "provider proof/configuration requires review",
                        via="operator_cli",
                        refund_id=str(r["refund_id"]),
                    )
                return False
            if (
                r["provider_refund_id"]
                and r["provider_refund_id"] != proof["refund_id"]
            ):
                return False
            if c.execute(
                "SELECT 1 FROM auth_refund_orders WHERE provider_refund_id=%s AND refund_id<>%s",
                (proof["refund_id"], r["refund_id"]),
            ).fetchone():
                return False
            status = proof["status"]
            state = "pending"
            decided_at = None
            if status in ("succeeded", "canceled"):
                state = "refunded" if status == "succeeded" else "failed"
                decided_at = now
                lot = c.execute(
                    "SELECT * FROM auth_wallet_lots WHERE lot_id=%s FOR UPDATE",
                    (r["lot_id"],),
                ).fetchone()
                try:
                    with c.transaction():
                        refund_release_in_tx(
                            c,
                            lot,
                            "refund_confirmed" if status == "succeeded" else "refund_failed",
                            reason="AUTH-23 provider-confirmed refund",
                        )
                except (WalletError, ValueError):
                    # Money proof retained; the hold persists for reconcile.
                    state = "review_required"
                    decided_at = None
            c.execute(
                "UPDATE auth_refund_orders SET state=%s,provider_refund_id=%s,"
                "decided_at=%s,lease_until=NULL,next_attempt_at=%s WHERE refund_id=%s",
                (
                    state,
                    proof["refund_id"],
                    decided_at,
                    now + (timedelta(seconds=60) if state == "pending" else timedelta(seconds=0)),
                    r["refund_id"],
                ),
            )
            audit(
                c,
                "provider:yookassa",
                a["account_id"],
                "billing-refund-" + state,
                "verified provider observation",
                via="operator_cli",
                refund_id=str(r["refund_id"]),
            )
            return True

    def reconcile(self, refund_id, *, reason):
        """Trusted recovery of review_required; API proof still mandatory."""
        _validate_reason_local(reason)
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            r = c.execute(
                "SELECT * FROM auth_refund_orders WHERE refund_id=%s FOR UPDATE",
                (UUID(str(refund_id)),),
            ).fetchone()
            if not r or r["state"] != "review_required":
                raise ValueError("review_required refund required")
            c.execute(
                "UPDATE auth_refund_orders SET state='pending',lease_until=NULL,"
                "fence=fence+1,next_attempt_at=%s WHERE refund_id=%s",
                (self._now(c), r["refund_id"]),
            )
            audit(
                c,
                "operator:local",
                r["account_id"],
                "billing-refund-reconcile",
                reason,
                via="operator_cli",
                refund_id=str(r["refund_id"]),
            )
            return {"queued": True, "refund_id": str(r["refund_id"])}

    # --------------------------------------------------- trusted dispute path

    def dispute_open(self, order_id, *, reason):
        """Trusted chargeback opening: wallet lock + hold of the remaining
        available on the order's purchased lot + exposure record (§13.7.4)."""
        _validate_reason_local(reason)
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            o = c.execute(
                "SELECT * FROM auth_topup_orders WHERE order_id=%s FOR UPDATE",
                (UUID(str(order_id)),),
            ).fetchone()
            if not o or o["state"] != "credited":
                raise ValueError("credited order required")
            if c.execute(
                "SELECT 1 FROM auth_disputes WHERE order_id=%s", (o["order_id"],)
            ).fetchone():
                raise ValueError("dispute already exists for this order")
            prior = c.execute(
                "SELECT state FROM auth_refund_orders WHERE order_id=%s",
                (o["order_id"],),
            ).fetchone()
            if prior and prior["state"] != "failed":
                # A failed self-service refund keeps the dispute path open;
                # a pending/refunded refund means money is moving or moved.
                raise ValueError("refund already exists for this order")
            wallet = c.execute(
                "SELECT * FROM auth_wallets WHERE account_id=%s FOR UPDATE",
                (o["account_id"],),
            ).fetchone()
            if wallet is None:
                raise ValueError("wallet not provisioned for this account")
            was_locked = wallet["status"] != "active"
            if not was_locked:
                updated = c.execute(
                    "UPDATE auth_wallets SET status='locked',locked_reason=%s,version=version+1 "
                    "WHERE wallet_id=%s AND version=%s RETURNING wallet_id",
                    (reason.strip(), wallet["wallet_id"], wallet["version"]),
                ).fetchone()
                if not updated:
                    raise ValueError("wallet version conflict")
                from apps.api.billing.wallet import _wallet_audit

                _wallet_audit(
                    c, "wallet_status", wallet["wallet_id"], reason, status="locked"
                )
            lot = c.execute(
                "SELECT * FROM auth_wallet_lots WHERE account_id=%s AND origin_order=%s AND source='purchased' FOR UPDATE",
                (o["account_id"], str(o["order_id"])),
            ).fetchone()
            if not lot:
                raise ValueError("purchased lot for this order required")
            try:
                dispute_hold_in_tx(c, lot, reason=reason)
            except WalletError:
                raise ValueError("lot cannot be disputed") from None
            q = c.execute(
                "SELECT snapshot FROM auth_topup_quotes WHERE quote_id=%s",
                (o["quote_id"],),
            ).fetchone()
            snapshot = q["snapshot"] if q else {}
            amount_minor = int(snapshot.get("amount_minor") or 0)
            currency = snapshot.get("currency") or ""
            if amount_minor <= 0 or currency != "RUB":
                raise ValueError("order price snapshot required")
            dispute_id = uuid4()
            row = c.execute(
                "INSERT INTO auth_disputes(dispute_id,order_id,account_id,lot_id,"
                "payment_id,spent_units,disputed_units,amount_minor,currency,"
                "wallet_was_locked,state,opened_reason,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'open',%s,%s) RETURNING *",
                (
                    dispute_id,
                    o["order_id"],
                    o["account_id"],
                    lot["lot_id"],
                    o["payment_id"],
                    int(lot["spent"]),
                    int(lot["available"]),
                    amount_minor,
                    currency,
                    was_locked,
                    reason.strip(),
                    self._now(c),
                ),
            ).fetchone()
            audit(
                c,
                "operator:local",
                o["account_id"],
                "billing-dispute-open",
                reason,
                via="operator_cli",
                dispute_id=str(dispute_id),
                order_id=str(o["order_id"]),
                spent_units=int(lot["spent"]),
                disputed_units=int(lot["available"]),
            )
            return dispute_view(row)

    def dispute_resolve(self, dispute_id, outcome, *, reason):
        """Trusted single-shot resolution: lost extinguishes held CU, won
        unlocks them back; the wallet stays locked after lost (§13.7.5)."""
        _validate_reason_local(reason)
        if outcome not in ("lost", "won"):
            raise ValueError("lost or won outcome required")
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            d = c.execute(
                "SELECT * FROM auth_disputes WHERE dispute_id=%s FOR UPDATE",
                (UUID(str(dispute_id)),),
            ).fetchone()
            if not d or d["state"] != "open":
                raise ValueError("open dispute required")
            lot = c.execute(
                "SELECT * FROM auth_wallet_lots WHERE lot_id=%s FOR UPDATE",
                (d["lot_id"],),
            ).fetchone()
            refund_release_in_tx(
                c,
                lot,
                "refund_confirmed" if outcome == "lost" else "refund_failed",
                reason=reason,
                command="dispute_" + outcome,
            )
            if outcome == "won" and not d["wallet_was_locked"]:
                wallet = c.execute(
                    "SELECT * FROM auth_wallets WHERE account_id=%s FOR UPDATE",
                    (d["account_id"],),
                ).fetchone()
                updated = c.execute(
                    "UPDATE auth_wallets SET status='active',locked_reason=NULL,version=version+1 "
                    "WHERE wallet_id=%s AND version=%s RETURNING wallet_id",
                    (wallet["wallet_id"], wallet["version"]),
                ).fetchone()
                if not updated:
                    raise ValueError("wallet version conflict")
                from apps.api.billing.wallet import _wallet_audit

                _wallet_audit(
                    c, "wallet_status", wallet["wallet_id"], reason, status="active"
                )
            row = c.execute(
                "UPDATE auth_disputes SET state=%s,resolution_reason=%s,resolved_at=%s "
                "WHERE dispute_id=%s RETURNING *",
                (outcome, reason.strip(), self._now(c), d["dispute_id"]),
            ).fetchone()
            audit(
                c,
                "operator:local",
                d["account_id"],
                "billing-dispute-" + outcome,
                reason,
                via="operator_cli",
                dispute_id=str(d["dispute_id"]),
                order_id=str(d["order_id"]),
            )
            return dispute_view(row)

    def dispute_status(self, order_id):
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            row = c.execute(
                "SELECT * FROM auth_disputes WHERE order_id=%s",
                (UUID(str(order_id)),),
            ).fetchone()
            if not row:
                raise ValueError("known dispute required")
            return dispute_view(row)

    def refunds_of(self, account_id, limit=50):
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            rows = c.execute(
                "SELECT * FROM auth_refund_orders WHERE account_id=%s "
                "ORDER BY created_at DESC LIMIT %s",
                (UUID(str(account_id)), int(limit)),
            ).fetchall()
            return {"refunds": [refund_view(r) for r in rows]}

    def disputes_of(self, account_id, limit=50):
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            rows = c.execute(
                "SELECT * FROM auth_disputes WHERE account_id=%s "
                "ORDER BY created_at DESC LIMIT %s",
                (UUID(str(account_id)), int(limit)),
            ).fetchall()
            return {"disputes": [dispute_view(r) for r in rows]}
