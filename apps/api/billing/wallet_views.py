"""AUTH-24 wallet READ surface: usage projection for members, full financial
journal for OWNER, lifecycle flags. Read-only: no DDL, no writes, no provider
calls (design docs/auth24/design.md D1).

Normative rules: spec_billing_accounts.md §13.3 (can_purchase_cu / can_spend_cu,
expired subscription preserves purchased and reports the reason), §13.6 (MEMBER
messages lead to the OWNER), §13.8 (GET wallet breakdown/reserved/status; GET
ledger OWNER-only full journal, MEMBER usage facts only); spec_auth_architecture.md
§12.2/§12.3/§12.5 (AUTH-24). Admission to actual spending stays with the AUTH-12
coordinator; these flags are advisory UI facts computed server-side.
"""

from apps.api.accounts.entitlements import account_is_active
from apps.api.accounts.team import TeamService
from apps.api.authentication.context import auth_error
from apps.api.authentication.sessions import boundary
from apps.api.billing.refunds import dispute_view, refund_view
from apps.api.billing.topup_migrations import check_schema
from apps.api.billing.wallet_migrations import VERSION
from apps.api.billing.wallet_migrations import check_schema as check_wallet_schema

WALLET_SOURCES = ("included", "promotional", "purchased")
BUCKET_KEYS = ("issued", "available", "reserved", "spent", "expired", "refund_pending", "refunded")
LEDGER_POSTINGS_LIMIT = 200
LEDGER_LOTS_LIMIT = 100
LEDGER_ORDERS_LIMIT = 20

POSTING_FIELDS = (
    "posting_id",
    "lot_id",
    "reservation_id",
    "event",
    "available_delta",
    "reserved_delta",
    "spent_delta",
    "expired_delta",
    "refund_pending_delta",
    "refunded_delta",
    "created_at",
)
LOT_FIELDS = (
    "lot_id",
    "source",
    "issued",
    "available",
    "reserved",
    "spent",
    "expired",
    "refund_pending",
    "refunded",
    "expires_at",
    "origin_cycle",
    "origin_order",
    "origin_ref",
)


def source_buckets(lots):
    """§13.2 per-source projection; same math as WalletService.summary()."""
    return {
        source: {
            key: sum(int(row[key]) for row in lots if row["source"] == source)
            for key in BUCKET_KEYS
        }
        for source in WALLET_SOURCES
    }


def next_expiry(lots):
    expiries = sorted(
        row["expires_at"].isoformat()
        for row in lots
        if row["expires_at"] is not None and int(row["available"]) > 0
    )
    return expiries[0] if expiries else None


def spending_block(wallet, *, account_active):
    """§13.3: a locked wallet or an expired subscription blocks new paid
    computations; the preserved balance is still reported with the reason."""
    if wallet["status"] != "active":
        return "wallet_locked"
    if not account_active:
        return "account_expired"
    return None


def wallet_view(account, wallet, lots, *, is_owner, account_active, now=None):
    """OWNER: full breakdown; MEMBER: usage totals only (§13.8 privacy).

    No money fields ever: prices/payment documents live in the OWNER ledger.
    """
    available = sum(int(row["available"]) for row in lots)
    reserved = sum(int(row["reserved"]) for row in lots)
    block = spending_block(wallet, account_active=account_active)
    active_wallet = wallet["status"] == "active"
    paid_multi = (
        account["account_type"] == "multi"
        and account["plan"] not in ("internal", "demo")
    )
    view = {
        "wallet_id": str(wallet["wallet_id"]),
        "status": wallet["status"],
        "available": available,
        "reserved": reserved,
        "next_expiry": next_expiry(lots),
        "can_purchase_cu": bool(is_owner and paid_multi and active_wallet and account_active),
        "can_spend_cu": bool(active_wallet and account_active),
        "account_active": bool(account_active),
        "spending_blocked_reason": block,
        "schema_version": VERSION,
    }
    if is_owner:
        view["sources"] = source_buckets(lots)
        view["locked_reason"] = wallet["locked_reason"]
    return view


def lot_view(row):
    view = {key: row[key] for key in LOT_FIELDS}
    if view["expires_at"] is not None:
        view["expires_at"] = view["expires_at"].isoformat()
    for key in ("issued", "available", "reserved", "spent", "expired",
                "refund_pending", "refunded"):
        view[key] = int(view[key])
    return view


def posting_view(row):
    view = {key: row[key] for key in POSTING_FIELDS}
    for key in ("available_delta", "reserved_delta", "spent_delta",
                "expired_delta", "refund_pending_delta", "refunded_delta"):
        view[key] = int(view[key])
    return view


def order_view(row):
    """TopupService.view parity for the OWNER journal (no quote/owner ids)."""
    return {
        "order_id": str(row["order_id"]),
        "state": row["state"],
        "units": int(row["units"]),
        "checkout_url": row["checkout_url"] if row["state"] == "pending" else None,
        "payment_id": row["payment_id"],
        "credited_at": row["credited_at"].isoformat() if row["credited_at"] else None,
    }


def ledger_view(lots, postings, orders, refunds, disputes, *, limits=None):
    """OWNER-only bounded financial journal (design D5). Money fields are
    legitimate here: the endpoint never answers to MEMBER."""
    limits = limits or {}
    max_postings = limits.get("postings", LEDGER_POSTINGS_LIMIT)
    max_lots = limits.get("lots", LEDGER_LOTS_LIMIT)
    max_orders = limits.get("orders", LEDGER_ORDERS_LIMIT)
    return {
        "lots": [lot_view(row) for row in sorted(lots, key=lambda r: str(r["lot_id"]))[:max_lots]],
        "postings": [posting_view(row) for row in postings[:max_postings]],
        "orders": [order_view(row) for row in orders[:max_orders]],
        "refunds": [refund_view(row) for row in refunds[:max_orders]],
        "disputes": [dispute_view(row) for row in disputes[:max_orders]],
        "schema_version": VERSION,
    }


class WalletReadService(TeamService):
    """Member wallet READ and OWNER-only ledger; the wallet itself has no
    public writer (AUTH-21). No FOR UPDATE: projections never contend with
    the coordinator."""

    def _readable_account(self, c, token, origin, aid):
        """D2/D3: membership read gate that tolerates an expired plan while
        every other refusal matches the team contract byte-for-byte."""
        check_schema(c)
        actor = self._personal(c, token, origin)
        row = c.execute(
            "SELECT * FROM auth_accounts WHERE account_id=%s", (aid,)
        ).fetchone()
        if not row or row["account_id"] != actor["account_id"]:
            auth_error(404, "account_not_found")
        if row["status"] != "active":
            auth_error(403, "account_expired")
        if c.execute(
            "SELECT 1 FROM auth_demo_grants WHERE account_id=%s", (row["account_id"],)
        ).fetchone():
            auth_error(403, "team_unavailable")
        member = self._member(c, row["account_id"], actor["subject_id"])
        if not member:
            auth_error(404, "account_not_found")
        return actor, row, member

    def _wallet(self, c, account_id):
        wallet = c.execute(
            "SELECT wallet_id,status,locked_reason FROM auth_wallets WHERE account_id=%s",
            (account_id,),
        ).fetchone()
        if wallet is None:
            auth_error(403, "wallet_required")
        return wallet

    @boundary
    def wallet(self, token, origin, aid):
        with self._tx() as tx:
            c = tx.connection
            check_wallet_schema(c)
            _, a, member = self._readable_account(c, token, origin, aid)
            wallet = self._wallet(c, a["account_id"])
            lots = c.execute(
                "SELECT * FROM auth_wallet_lots WHERE wallet_id=%s ORDER BY lot_id",
                (wallet["wallet_id"],),
            ).fetchall()
            now = self._now(c)
            return wallet_view(
                a,
                wallet,
                lots,
                is_owner=member["account_role"] == "owner",
                account_active=account_is_active(a, now=now),
                now=now,
            )

    @boundary
    def ledger(self, token, origin, aid):
        with self._tx() as tx:
            c = tx.connection
            check_wallet_schema(c)
            _, a, member = self._readable_account(c, token, origin, aid)
            if member["account_role"] != "owner":
                auth_error(403, "owner_required")
            wallet = self._wallet(c, a["account_id"])
            lots = c.execute(
                "SELECT * FROM auth_wallet_lots WHERE wallet_id=%s ORDER BY lot_id LIMIT %s",
                (wallet["wallet_id"], LEDGER_LOTS_LIMIT),
            ).fetchall()
            postings = c.execute(
                "SELECT p.* FROM auth_wallet_postings p "
                "JOIN auth_wallet_lots l USING(lot_id) WHERE l.wallet_id=%s "
                "ORDER BY p.created_at DESC, p.posting_id LIMIT %s",
                (wallet["wallet_id"], LEDGER_POSTINGS_LIMIT),
            ).fetchall()
            orders = c.execute(
                "SELECT * FROM auth_topup_orders WHERE account_id=%s "
                "ORDER BY created_at DESC LIMIT %s",
                (a["account_id"], LEDGER_ORDERS_LIMIT),
            ).fetchall()
            refunds = c.execute(
                "SELECT * FROM auth_refund_orders WHERE account_id=%s "
                "ORDER BY created_at DESC LIMIT %s",
                (a["account_id"], LEDGER_ORDERS_LIMIT),
            ).fetchall()
            disputes = c.execute(
                "SELECT * FROM auth_disputes WHERE account_id=%s "
                "ORDER BY created_at DESC LIMIT %s",
                (a["account_id"], LEDGER_ORDERS_LIMIT),
            ).fetchall()
            return ledger_view(lots, postings, orders, refunds, disputes)
