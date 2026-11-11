"""AUTH-21 source-aware wallet authority. Trusted provisioning only; no money,
no pricing, no provider calls, no HTTP surface (design docs/auth21/design.md).

Normative rules: spec_billing_accounts.md §13 (FEFO spend, source separation,
integer micro-CU, pinned allocations, expiry). Reservation-level movements run
inside the AUTH-12 coordinator transaction; standalone commands are trusted
operator CLI with mandatory audit in the same transaction (D9).
"""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from apps.api.authentication.context import AuthHTTPException, auth_error
from apps.api.authentication.errors import AuthSchemaNotReady
from apps.api.billing.subscription_contract import cumulative_allocation, micros
from apps.api.billing.wallet_migrations import VERSION, check_schema

WALLET_SOURCES = frozenset({"included", "purchased", "promotional"})
SOURCE_RANK = {"included": 0, "promotional": 1, "purchased": 2}
MAX_UNITS = 2**63 - 1
MAX_LOTS = 4096
MAX_REASON = 256

POSTING_EVENTS = frozenset(
    {
        "reserve",
        "settle",
        "release",
        "expire",
        "refund_hold",
        "refund_confirmed",
        "refund_failed",
        "adjust",
    }
)


class WalletError(AuthHTTPException):
    """Domain refusal with safe, non-secret details (design D4)."""

    def __init__(self, status_code, code, **details):
        from apps.api.authentication.context import _MESSAGES

        self.code = code
        self.details = details
        super().__init__(
            status_code=status_code,
            headers={"Cache-Control": "no-store"},
            detail={
                "code": code,
                "message": _MESSAGES.get(code, "Ошибка кошелька"),
                "request_id": "",
                **details,
            },
        )


def audit(c, action, resource, *, actor="operator:local", details=None):
    from apps.api.security_audit import build_audit_record

    record = build_audit_record(
        action,
        "allowed",
        actor_subject=str(actor) if actor != "operator:local" else None,
        actor_via="operator_cli" if actor == "operator:local" else "trusted_coordinator",
        resource_kind="billing_wallet",
        resource_id=str(resource),
        policy_basis="AUTH-21 source-aware wallet",
        details=details,
    )
    c.execute(
        "INSERT INTO auth_audit_outbox(audit_id,payload) VALUES (%s,%s::jsonb)",
        (record["audit_id"], json.dumps(record)),
    )


def _wallet_audit(c, command, wallet_id, reason, **extra):
    audit(
        c,
        "auth_wallet_changed",
        wallet_id,
        details={"command": command, "reason": reason, **extra},
    )


def validate_issue(source, units, *, origin_order="", origin_ref="", expires_at=None, now=None):
    """Shared integer/bounds contract for every issuance path (D7/D8)."""
    if source not in WALLET_SOURCES:
        raise ValueError("known wallet source required")
    if type(units) is not int or not 1 <= units <= MAX_UNITS:
        raise ValueError("positive integer micro-CU required")
    if source == "purchased":
        if not isinstance(origin_order, str) or not 1 <= len(origin_order.strip()) <= 128:
            raise ValueError("purchased lot requires an origin order reference")
        if expires_at is not None:
            raise ValueError("purchased lots never expire in v1")
    else:
        if not isinstance(origin_ref, str) or not 1 <= len(origin_ref.strip()) <= 256:
            raise ValueError(f"{source} lot requires an origin reference")
    if source == "included" and expires_at is None:
        raise ValueError("included lots carry the cycle expiry")
    if expires_at is not None:
        if not isinstance(expires_at, datetime) or expires_at.tzinfo is None:
            raise ValueError("aware expiry required")
        now = now or datetime.now(UTC)
        if expires_at <= now:
            raise ValueError("future expiry required")
        if expires_at > now + timedelta(days=366 * 10):
            raise ValueError("bounded expiry required")
    return True


def _validate_reason(reason):
    if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= MAX_REASON:
        raise ValueError("reason required")


def _validate_expires(source, expires_at, now):
    if source == "purchased":
        if expires_at is not None:
            raise ValueError("purchased lots never expire in v1")
        return None
    if not isinstance(expires_at, datetime) or expires_at.tzinfo is None:
        raise ValueError("aware expiry required")
    if expires_at <= now:
        raise ValueError("future expiry required")
    if expires_at > now + timedelta(days=366 * 10):
        raise ValueError("bounded expiry required")
    return expires_at


def fefo_key(row):
    """§13.5 FEFO: nearest expiry, then endless, then source rank, then lot_id."""
    expires = row["expires_at"]
    return (
        1 if expires is None else 0,
        expires if expires is not None else datetime.max.replace(tzinfo=UTC),
        SOURCE_RANK[row["source"]],
        row["lot_id"],
    )


def allocate_split(lots, units):
    """Deterministic exact split (D7): every micro-CU lands in exactly one lot."""
    if type(units) is not int or units <= 0:
        raise ValueError("positive integer units required")
    remaining = units
    plan = []
    for row in sorted(lots, key=fefo_key):
        if remaining <= 0:
            break
        take = min(int(row["available"]), remaining)
        if take > 0:
            plan.append((row["lot_id"], take))
            remaining -= take
    if remaining > 0:
        raise WalletError(
            402,
            "cu_insufficient",
            required=units,
            available=units - remaining,
        )
    return plan


def settle_distribution(allocations, actual, *, now=None):
    """FEFO consumption of pinned allocations; unspent tails per lot, classified.

    A reservation is settled OR released, never both (AUTH-12 state guard), so
    the unspent tail of every allocation is `units - consumed` and is returned
    per lot: a dead lot (already expired or swept) never revives (D6/E2).
    """
    if type(actual) is not int or actual < 0:
        raise ValueError("integer actual required")
    pinned = sum(units for _, units in allocations)
    if actual > pinned:
        raise ValueError("actual exceeds pinned wallet allocations")
    order = {row["lot_id"]: fefo_key(row) for row, _ in allocations}
    ordered = sorted(allocations, key=lambda pair: order[pair[0]["lot_id"]])
    remaining = actual
    spends = []
    classified = []
    for row, units in ordered:
        take = min(units, remaining)
        remaining -= take
        if take > 0:
            spends.append((row["lot_id"], take))
        tail = units - take
        if tail > 0:
            expires = row["expires_at"]
            dead = int(row.get("expired", 0) or 0) > 0 or (
                expires is not None and now is not None and now >= expires
            )
            classified.append(
                (row["lot_id"], ("expired" if dead else "available", tail))
            )
    return spends, classified


def _present(c):
    return bool(
        c.execute("SELECT to_regclass('auth_wallets') AS present").fetchone()["present"]
    )


def _wallet_row(c, account_id):
    return c.execute(
        "SELECT * FROM auth_wallets WHERE account_id=%s FOR UPDATE", (account_id,)
    ).fetchone()


def _locked_lots(c, wallet_id, lot_ids=None):
    sql = "SELECT * FROM auth_wallet_lots WHERE wallet_id=%s"
    args = [wallet_id]
    if lot_ids:
        sql += " AND lot_id=ANY(%s)"
        args.append(list(lot_ids))
    # D14: every path locks lots in the same stable lot_id order.
    sql += " ORDER BY lot_id FOR UPDATE"
    return c.execute(sql, args).fetchall()


def _insert_lot(c, wallet, *, source, units, origin_order=None, origin_cycle=None, origin_ref=None, expires_at=None):
    total = c.execute(
        "SELECT count(*) AS n FROM auth_wallet_lots WHERE wallet_id=%s",
        (wallet["wallet_id"],),
    ).fetchone()["n"]
    if total >= MAX_LOTS:
        raise ValueError("lot budget exhausted")
    lot_id = uuid4()
    c.execute(
        "INSERT INTO auth_wallet_lots(lot_id,wallet_id,account_id,source,issued,available,"
        "expires_at,origin_cycle,origin_order,origin_ref,created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            lot_id,
            wallet["wallet_id"],
            wallet["account_id"],
            source,
            units,
            units,
            expires_at,
            origin_cycle,
            origin_order,
            origin_ref,
            _clock(c),
        ),
    )
    return lot_id


def credit_purchased_order(c, account_id, units, *, origin_order, reason):
    """AUTH-22 saga credit hook: one whole purchased lot per confirmed order.

    Runs inside the caller's transaction (order transition + credit + mandatory
    audit commit together). Missing wallet -> WalletError(403 wallet_required);
    locked wallet -> WalletError(403 wallet_locked) so the top-up saga can park
    the order in paid_review instead of losing captured money (design D5).
    A duplicate basis is impossible: the partial unique index
    auth21_lot_order(account_id, origin_order) rejects a second lot.
    """
    _validate_reason(reason)
    validate_issue("purchased", units, origin_order=origin_order)
    aid = UUID(str(account_id))
    if not _present(c):
        raise WalletError(403, "wallet_required")
    wallet = _wallet_row(c, aid)
    if wallet is None:
        raise WalletError(403, "wallet_required")
    if wallet["status"] != "active":
        raise WalletError(403, "wallet_locked")
    lot_id = _insert_lot(
        c, wallet, source="purchased", units=units, origin_order=origin_order.strip()
    )
    _wallet_audit(
        c,
        "lot_issued",
        wallet["wallet_id"],
        reason,
        lot_id=str(lot_id),
        source="purchased",
        units=units,
        origin_order=origin_order.strip(),
    )
    return {"lot_id": str(lot_id), "units": units}


def _posting(c, lot_id, event, *, reservation_id=None, **deltas):
    if event not in POSTING_EVENTS:
        raise ValueError("known posting event required")
    columns = {
        "available_delta",
        "reserved_delta",
        "spent_delta",
        "expired_delta",
        "refund_pending_delta",
        "refunded_delta",
    }
    values = {k: int(deltas.get(k, 0)) for k in columns}
    c.execute(
        "INSERT INTO auth_wallet_postings(posting_id,lot_id,reservation_id,event,"
        "available_delta,reserved_delta,spent_delta,expired_delta,"
        "refund_pending_delta,refunded_delta,created_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            uuid4(),
            lot_id,
            reservation_id,
            event,
            values["available_delta"],
            values["reserved_delta"],
            values["spent_delta"],
            values["expired_delta"],
            values["refund_pending_delta"],
            values["refunded_delta"],
            _clock(c),
        ),
    )


def _clock(c):
    return c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]


def allocate_for_reservation(c, account_id, reservation_id, units, now, *, total_if_unpinned=None):
    """Coordinator hook (reserve/extend): FEFO pin, same transaction.

    No wallet -> no-op (additive boundary D1/D4). Locked wallet -> 403
    wallet_locked. Insufficient credit -> 402 cu_insufficient. For an extend of
    a reservation started before wallet provisioning (no pinned allocations)
    the coordinator passes total_if_unpinned=held_cu so the whole hold stays
    covered (D5); otherwise `units` is the delta/full cost to pin.
    """
    if type(units) is not int or units < 0:
        raise ValueError("integer wallet units required")
    if units == 0 or not _present(c):
        return None
    wallet = _wallet_row(c, account_id)
    if wallet is None:
        return None
    if wallet["status"] != "active":
        raise WalletError(403, "wallet_locked")
    existing = c.execute(
        "SELECT lot_id,units FROM auth_reservation_lot_allocations WHERE reservation_id=%s ORDER BY lot_id",
        (reservation_id,),
    ).fetchall()
    lots = [row for row in _locked_lots(c, wallet["wallet_id"]) if is_spendable(row, now)]
    target = units
    if not existing and total_if_unpinned is not None:
        if type(total_if_unpinned) is not int or total_if_unpinned < units:
            raise ValueError("integer unpinned total required")
        target = total_if_unpinned
    plan = allocate_split(lots, target)
    for lot_id, take in plan:
        _posting(
            c,
            lot_id,
            "reserve",
            reservation_id=reservation_id,
            available_delta=-take,
            reserved_delta=take,
        )
        if any(row["lot_id"] == lot_id for row in existing):
            c.execute(
                "UPDATE auth_reservation_lot_allocations SET units=units+%s WHERE reservation_id=%s AND lot_id=%s",
                (take, reservation_id, lot_id),
            )
        else:
            c.execute(
                "INSERT INTO auth_reservation_lot_allocations(reservation_id,lot_id,units) VALUES (%s,%s,%s)",
                (reservation_id, lot_id, take),
            )
    return plan


def is_spendable(row, now):
    """D3: available credit only; an expired lot is never spendable lazily."""
    return int(row["available"]) > 0 and (
        row["expires_at"] is None or now < row["expires_at"]
    )


def settle_reservation(c, account_id, reservation_id, actual, now):
    """Coordinator hook (settle): spend `actual` across pinned lots FEFO (D6)."""
    if type(actual) is not int or actual < 0:
        raise ValueError("integer wallet actual required")
    if actual == 0 or not _present(c):
        return None
    # Schema existence is implied by pinned rows; hot paths stay lean (D15).
    allocations = _pinned(c, account_id, reservation_id)
    if not allocations:
        return None
    spends, _ = settle_distribution(allocations, actual, now=now)
    for lot_id, take in spends:
        _posting(
            c,
            lot_id,
            "settle",
            reservation_id=reservation_id,
            reserved_delta=-take,
            spent_delta=take,
        )
    return spends


def release_reservation(c, account_id, reservation_id, now):
    """Coordinator hook (release): free unspent pinned tail; expired never revives."""
    if not _present(c):
        return None
    allocations = _pinned(c, account_id, reservation_id)
    if not allocations:
        return None
    _, classified = settle_distribution(allocations, 0, now=now)
    for lot_id, (kind, units) in classified:
        if kind == "expired":
            _posting(
                c,
                lot_id,
                "release",
                reservation_id=reservation_id,
                reserved_delta=-units,
                expired_delta=units,
            )
        else:
            _posting(
                c,
                lot_id,
                "release",
                reservation_id=reservation_id,
                reserved_delta=-units,
                available_delta=units,
            )
    return classified


def _pinned(c, account_id, reservation_id):
    rows = c.execute(
        """SELECT l.*,a.units FROM auth_reservation_lot_allocations a
        JOIN auth_wallet_lots l USING(lot_id)
        WHERE a.reservation_id=%s AND l.account_id=%s
        ORDER BY l.lot_id FOR UPDATE OF l""",
        (reservation_id, account_id),
    ).fetchall()
    return [(row, int(row["units"])) for row in rows]


class WalletService:
    """Trusted operator authority (CLI). Never a public writer; audit mandatory."""

    def __init__(self, store):
        self.store = store

    def _tx(self):
        return self.store.transaction()

    def create_wallet(self, account_id, *, reason):
        _validate_reason(reason)
        aid = UUID(str(account_id))
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            account = c.execute(
                "SELECT * FROM auth_accounts WHERE account_id=%s FOR UPDATE", (aid,)
            ).fetchone()
            if not account or account["plan"] in ("demo", "internal"):
                raise ValueError("personal paid account required")
            if c.execute(
                "SELECT 1 FROM auth_wallets WHERE account_id=%s", (aid,)
            ).fetchone():
                raise ValueError("wallet already exists")
            wallet_id = uuid4()
            c.execute(
                "INSERT INTO auth_wallets(wallet_id,account_id,created_at) VALUES (%s,%s,%s)",
                (wallet_id, aid, _clock(c)),
            )
            _wallet_audit(c, "wallet_created", wallet_id, reason)
            return {"wallet_id": str(wallet_id), "account_id": str(aid)}

    def _wallet(self, c, account_id):
        row = _wallet_row(c, UUID(str(account_id)))
        if row is None:
            raise ValueError("wallet not provisioned for this account")
        return row

    def _insert_lot(self, c, wallet, *, source, units, origin_order=None, origin_cycle=None, origin_ref=None, expires_at=None):
        return _insert_lot(
            c,
            wallet,
            source=source,
            units=units,
            origin_order=origin_order,
            origin_cycle=origin_cycle,
            origin_ref=origin_ref,
            expires_at=expires_at,
        )

    def issue_included_for_cycle(self, account_id, cycle_id, *, ref, reason):
        """Base cycle issuance; amount is the cycle's own entitlement formula (D8)."""
        _validate_reason(reason)
        if not isinstance(ref, str) or not 1 <= len(ref.strip()) <= 128:
            raise ValueError("origin ref required")
        ref = ref.strip()
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            wallet = self._wallet(c, account_id)
            cycle = c.execute(
                "SELECT * FROM auth_billing_cycles WHERE cycle_id=%s FOR UPDATE",
                (UUID(str(cycle_id)),),
            ).fetchone()
            if not cycle or cycle["account_id"] != wallet["account_id"]:
                raise ValueError("account cycle required")
            duration = micros(cycle["ends_at"] - cycle["starts_at"])
            expected = cumulative_allocation(
                cycle["config"]["base_included"],
                int(cycle["adjustment_numerator"]),
                duration,
            )
            if expected <= 0:
                raise ValueError("cycle entitlement is empty")
            if c.execute(
                "SELECT 1 FROM auth_wallet_lots WHERE account_id=%s AND origin_cycle=%s AND origin_ref=%s",
                (wallet["account_id"], cycle["cycle_id"], ref),
            ).fetchone():
                raise ValueError("issuance basis already exists")
            lot_id = self._insert_lot(
                c,
                wallet,
                source="included",
                units=expected,
                origin_cycle=cycle["cycle_id"],
                origin_ref=ref,
                expires_at=cycle["ends_at"],
            )
            _wallet_audit(
                c,
                "lot_issued",
                wallet["wallet_id"],
                reason,
                lot_id=str(lot_id),
                source="included",
                units=expected,
                origin_cycle=str(cycle["cycle_id"]),
                origin_ref=ref,
                expires_at=cycle["ends_at"].isoformat(),
            )
            return {"lot_id": str(lot_id), "units": expected}

    def issue_purchased(self, account_id, units, *, origin_order, reason):
        _validate_reason(reason)
        validate_issue("purchased", units, origin_order=origin_order)
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            wallet = self._wallet(c, account_id)
            if wallet["status"] != "active":
                raise ValueError("wallet locked")
            lot_id = self._insert_lot(
                c,
                wallet,
                source="purchased",
                units=units,
                origin_order=origin_order.strip(),
            )
            _wallet_audit(
                c,
                "lot_issued",
                wallet["wallet_id"],
                reason,
                lot_id=str(lot_id),
                source="purchased",
                units=units,
                origin_order=origin_order.strip(),
            )
            return {"lot_id": str(lot_id), "units": units}

    def issue_promotional(self, account_id, units, *, origin_ref, expires_at, reason):
        _validate_reason(reason)
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            now = _clock(c)
            validate_issue("promotional", units, origin_ref=origin_ref)
            wallet = self._wallet(c, account_id)
            if wallet["status"] != "active":
                raise ValueError("wallet locked")
            lot_id = self._insert_lot(
                c,
                wallet,
                source="promotional",
                units=units,
                origin_ref=origin_ref.strip(),
                expires_at=_validate_expires("promotional", expires_at, now)
                if expires_at
                else None,
            )
            _wallet_audit(
                c,
                "lot_issued",
                wallet["wallet_id"],
                reason,
                lot_id=str(lot_id),
                source="promotional",
                units=units,
                origin_ref=origin_ref.strip(),
            )
            return {"lot_id": str(lot_id), "units": units}

    def set_status(self, wallet_id, *, expected_version, status, reason):
        _validate_reason(reason)
        if type(expected_version) is not int or expected_version < 1:
            raise ValueError("wallet version required")
        if status not in ("active", "locked"):
            raise ValueError("known wallet status required")
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            row = c.execute(
                "UPDATE auth_wallets SET status=%s,locked_reason=%s,version=version+1 "
                "WHERE wallet_id=%s AND version=%s RETURNING *",
                (
                    status,
                    None if status == "active" else reason.strip(),
                    UUID(str(wallet_id)),
                    expected_version,
                ),
            ).fetchone()
            if not row:
                raise ValueError("wallet version conflict")
            _wallet_audit(
                c,
                "wallet_status",
                row["wallet_id"],
                reason,
                status=status,
                expected_version=expected_version,
            )
            return {"wallet_id": str(row["wallet_id"]), "status": status}

    def sweep_expiry(self, *, limit=100, reason, now=None):
        _validate_reason(reason)
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ValueError("bounded sweep limit required")
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            stamp = _clock(c) if now is None else now
            rows = c.execute(
                "SELECT * FROM auth_wallet_lots WHERE expires_at IS NOT NULL AND expires_at<=%s "
                "AND available>0 ORDER BY expires_at,lot_id FOR UPDATE SKIP LOCKED LIMIT %s",
                (stamp, limit),
            ).fetchall()
            swept = 0
            for row in rows:
                units = int(row["available"])
                _posting(
                    c,
                    row["lot_id"],
                    "expire",
                    available_delta=-units,
                    expired_delta=units,
                )
                swept += units
            _wallet_audit(
                c,
                "expiry_sweep",
                "operator:sweep",
                reason,
                lots=len(rows),
                units=swept,
            )
            return {"lots": len(rows), "units": swept}

    def adjust_lot(self, lot_id, *, available_delta, expired_delta, reason):
        """Trusted correction; rebalances buckets, never rewrites history (D16)."""
        _validate_reason(reason)
        if type(available_delta) is not int or type(expired_delta) is not int:
            raise ValueError("integer deltas required")
        if (available_delta, expired_delta) == (0, 0):
            raise ValueError("adjustment required")
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            row = c.execute(
                "SELECT * FROM auth_wallet_lots WHERE lot_id=%s FOR UPDATE",
                (UUID(str(lot_id)),),
            ).fetchone()
            if not row:
                raise ValueError("known lot required")
            available = int(row["available"]) + available_delta
            expired = int(row["expired"]) + expired_delta
            if available < 0 or expired < 0 or available_delta + expired_delta != 0:
                raise ValueError("balanced non-negative adjustment required")
            _posting(
                c,
                row["lot_id"],
                "adjust",
                available_delta=available_delta,
                expired_delta=expired_delta,
            )
            _wallet_audit(
                c,
                "lot_adjusted",
                row["wallet_id"],
                reason,
                lot_id=str(row["lot_id"]),
                available_delta=available_delta,
                expired_delta=expired_delta,
            )
            return {"lot_id": str(row["lot_id"])}

    def refund_hold(self, lot_id, *, reason):
        """E4: whole unused purchased lot only; spend/reserve race is exclusive."""
        _validate_reason(reason)
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            row = c.execute(
                "SELECT * FROM auth_wallet_lots WHERE lot_id=%s FOR UPDATE",
                (UUID(str(lot_id)),),
            ).fetchone()
            if not row:
                raise ValueError("known lot required")
            if row["source"] != "purchased":
                raise ValueError("self-service refund covers purchased lots only")
            if (
                int(row["reserved"]) > 0
                or int(row["spent"]) > 0
                or int(row["refund_pending"]) > 0
                or int(row["refunded"]) > 0
            ):
                raise WalletError(409, "refund_not_eligible")
            units = int(row["available"])
            _posting(
                c,
                row["lot_id"],
                "refund_hold",
                available_delta=-units,
                refund_pending_delta=units,
            )
            _wallet_audit(
                c,
                "refund_hold",
                row["wallet_id"],
                reason,
                lot_id=str(row["lot_id"]),
                units=units,
            )
            return {"lot_id": str(row["lot_id"]), "refund_pending": units}

    def refund_confirmed(self, lot_id, *, reason):
        _validate_reason(reason)
        return self._refund_finish(lot_id, "refund_confirmed", reason)

    def refund_failed(self, lot_id, *, reason):
        _validate_reason(reason)
        return self._refund_finish(lot_id, "refund_failed", reason)

    def _refund_finish(self, lot_id, event, reason):
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            row = c.execute(
                "SELECT * FROM auth_wallet_lots WHERE lot_id=%s FOR UPDATE",
                (UUID(str(lot_id)),),
            ).fetchone()
            if not row or int(row["refund_pending"]) <= 0:
                raise ValueError("refund hold required")
            units = int(row["refund_pending"])
            if event == "refund_confirmed":
                _posting(
                    c,
                    row["lot_id"],
                    "refund_confirmed",
                    refund_pending_delta=-units,
                    refunded_delta=units,
                )
            else:
                _posting(
                    c,
                    row["lot_id"],
                    "refund_failed",
                    refund_pending_delta=-units,
                    available_delta=units,
                )
            _wallet_audit(
                c,
                event,
                row["wallet_id"],
                reason,
                lot_id=str(row["lot_id"]),
                units=units,
            )
            return {"lot_id": str(row["lot_id"]), "units": units}

    def summary(self, account_id):
        """Projection per source; None without a wallet (D1/D11)."""
        with self.store.transaction(readonly=True) as tx:
            c = tx.connection
            if not _present(c):
                return None
            wallet = c.execute(
                "SELECT * FROM auth_wallets WHERE account_id=%s",
                (UUID(str(account_id)),),
            ).fetchone()
            if wallet is None:
                return None
            rows = c.execute(
                "SELECT * FROM auth_wallet_lots WHERE wallet_id=%s ORDER BY lot_id",
                (wallet["wallet_id"],),
            ).fetchall()
            buckets = {}
            for source in sorted(WALLET_SOURCES):
                buckets[source] = {
                    key: sum(
                        int(row[key]) for row in rows if row["source"] == source
                    )
                    for key in ("issued", "available", "reserved", "spent", "expired", "refund_pending", "refunded")
                }
            expiries = sorted(
                row["expires_at"].isoformat()
                for row in rows
                if row["expires_at"] is not None and int(row["available"]) > 0
            )
            return {
                "wallet_id": str(wallet["wallet_id"]),
                "status": wallet["status"],
                "locked_reason": wallet["locked_reason"],
                "sources": buckets,
                "reserved": sum(int(row["reserved"]) for row in rows),
                "next_expiry": expiries[0] if expiries else None,
                "schema_version": VERSION,
            }
