"""AUTH-25 payment reconciliation, restore watermark and the pre-launch
gate. Read-mostly detection over the existing AUTH-21/22/23 financial state;
no HTTP routes, no silent money repair, no live-checkout switch.

Normative rules: spec_auth_architecture.md AUTH-25 (crash/backup/provider
replay produce no duplicates; terms/catalog confirmed before real checkout),
§12.2 (billing/reconciliation reads the provider adapter/inbox/outbox state),
§12.4 (uncertain financial state holds; restart/backup/reconcile never
revive consumed credits or refunded lots), spec_billing_accounts.md §13.9 and
§13.10 E6 (restart/backup/reconcile do not duplicate credit/settlement/refund).
Restore mechanics follow the AUTH-20 marks pattern: a watermark file outside
pgdata records terminal financial facts; after a restore the operator runs
the comparison and resolves every regression with the existing trusted
commands (manage_topups, manage_refunds, manage_wallet).
"""

import json
import os
from datetime import timezone
from uuid import UUID, uuid4

from apps.api.billing.refunds import DEFAULT_WINDOW_DAYS, window_days
from apps.api.billing.topups import _validate_reason_local, validate_package

WATERMARK_FORMAT = "cisstat-auth25-watermark/1"
WATERMARK_MAX_ENTRIES = 100_000
MAX_FINDINGS = 500
DETAIL_LIMIT = 512
LOCK_REASON_PREFIX = "auth25-reconciliation"
REFUND_WINDOW_DEFAULT_DAYS = DEFAULT_WINDOW_DAYS

BLOCKING_CODES = frozenset(
    {
        "credit_order_mismatch",
        "payment_id_collision",
        "refund_state_mismatch",
        "dispute_state_mismatch",
        "lot_projection_drift",
        "lot_balance_violation",
        "restore_regression",
    }
)
INFO_CODES = frozenset(
    {"paid_review_open", "inbox_unowned_event", "audit_outbox_pending"}
)
ALL_CODES = BLOCKING_CODES | INFO_CODES

LAUNCH_CHECK_NAMES = (
    "schema_ready",
    "catalog_valid",
    "refund_window",
    "provider_mode",
    "reconciliation_clean",
    "audit_delivery",
)

# Terminal financial facts recorded outside pgdata before every backup.
_WATERMARK_FIELDS = {
    "order": ("kind", "order_id", "account_id", "state"),
    "refund": ("kind", "refund_id", "order_id", "state"),
    "dispute": ("kind", "dispute_id", "order_id", "state"),
}


def _bounded_detail(detail):
    if isinstance(detail, (dict, list)):
        text = json.dumps(detail, sort_keys=True, default=str)
    else:
        text = str(detail)
    return text[:DETAIL_LIMIT]


def finding(code, subject, detail=""):
    """One bounded report finding; unknown codes are rejected before SQL."""
    if code not in ALL_CODES:
        raise ValueError("known finding code required")
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("finding subject required")
    return {
        "code": code,
        "severity": "blocking" if code in BLOCKING_CODES else "info",
        "subject": subject[:DETAIL_LIMIT],
        "detail": _bounded_detail(detail),
    }


def validate_watermark(document):
    """cisstat-auth25-watermark/1 envelope: bounded, typed entries."""
    if not isinstance(document, dict):
        raise ValueError("watermark document must be an object")
    if document.get("format") != WATERMARK_FORMAT:
        raise ValueError("unsupported watermark format")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise ValueError("watermark entries must be a list")
    if len(entries) > WATERMARK_MAX_ENTRIES:
        raise ValueError("watermark exceed bounded export size")
    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("watermark entry must be an object")
        kind = entry.get("kind")
        if kind not in _WATERMARK_FIELDS:
            raise ValueError("unknown watermark entry kind")
        for field in _WATERMARK_FIELDS[kind]:
            value = entry.get(field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"watermark {kind} requires {field}")
        out.append(dict(entry))
    return out


def provider_mode(environ=None):
    """D4: report the provider configuration fact. Live credentials are
    blocked by contract: YooKassa constructs the test shop only and every
    payment is /me-verified against the test merchant."""
    env = os.environ if environ is None else environ
    raw = env.get("CISSTAT_YOOKASSA_ENABLED")
    if raw is None or raw == "":
        return (
            "not_configured",
            True,
            "billing admission answers 503 billing_not_configured; checkout disabled",
        )
    if raw == "test":
        return (
            "sandbox",
            True,
            "provider constructs the test shop only; live launch is separately gated",
        )
    return (
        "blocked",
        False,
        "CISSTAT_YOOKASSA_ENABLED must be unset or 'test'; live launch is separately gated",
    )


def parse_refund_window(environ=None):
    """Single policy source with the AUTH-23 refund window."""
    return window_days(environ)


def restore_suggestions(entry):
    """Watermark regressions map to existing trusted commands; money is never
    re-applied automatically."""
    kind = entry.get("kind")
    state = entry.get("state")
    if kind == "order":
        return [
            "manage_topups reconcile --order-id {0} (provider-confirmed retry)".format(
                entry.get("order_id", "<order_id>")
            ),
            "manage_topups credit-paid --order-id {0} (only after the manual wallet credit)".format(
                entry.get("order_id", "<order_id>")
            ),
        ]
    if kind == "refund":
        if state == "refunded":
            return [
                "manage_refunds refund-reconcile --refund-id {0} (re-queue provider-confirmed refund)".format(
                    entry.get("refund_id", "<refund_id>")
                )
            ]
        return [
            "manage_wallet adjust per the AUTH-21 runbook for order {0}".format(
                entry.get("order_id", "<order_id>")
            )
        ]
    if kind == "dispute":
        return [
            "manage_refunds dispute-resolve --dispute-id {0} --outcome lost|won (after the bank outcome)".format(
                entry.get("dispute_id", "<dispute_id>")
            )
        ]
    return []


def assemble_launch_verdict(checks, *, allow_empty_catalog=False):
    """D4: pure verdict assembly. Nothing is switched on by this command."""
    seen = []
    for check in checks:
        if not isinstance(check, dict) or check.get("name") not in LAUNCH_CHECK_NAMES:
            raise ValueError("known launch check required")
        if check.get("status") not in ("ok", "blocked", "warn"):
            raise ValueError("check status must be ok|blocked|warn")
        seen.append(dict(check))
    reasons = []
    ok = True
    for check in seen:
        if check["name"] == "catalog_valid" and check["status"] == "blocked":
            if allow_empty_catalog:
                check["status"] = "warn"
            else:
                ok = False
                reasons.append(
                    "catalog_valid: checkout is disabled until the operator provisions "
                    "a versioned catalog (terms/price) -- empty catalog blocks real checkout"
                )
                continue
        if check["status"] == "blocked":
            ok = False
            reasons.append(f"{check['name']}: {check.get('detail', '')}")
    return {
        "ok": ok,
        "verdict": "ok" if ok else "blocked",
        "checks": seen,
        "reasons": reasons,
    }


class FinancialReconciliationService:
    """AUTH-25 read-mostly authority on top of PostgresAccessStore."""

    def __init__(self, store=None, clock=None):
        if store is None:
            from apps.api.authentication.storage import PostgresAccessStore

            store = PostgresAccessStore.from_env()
        self.store = store
        self.clock = clock

    # ------------------------------------------------------------- internals

    def _now(self, c):
        if self.clock is not None:
            return self.clock()
        return c.execute("SELECT now() AS t").fetchone()["t"]

    def _audit(self, c, kind, resource, reason, **extra):
        """Mandatory audit intent, AUTH-20 ops pattern: the existing
        auth_ops_changed action with kind/details inside the same
        transaction. No new audit vocabulary is introduced."""
        from apps.api.security_audit import build_audit_record

        record = build_audit_record(
            "auth_ops_changed",
            "allowed",
            actor_subject="ops-cli",
            actor_via="auth_ops",
            resource_kind="billing_reconciliation",
            resource_id=str(resource),
            policy_basis="AUTH-25 payment reconciliation/restore",
            details={
                "kind": kind,
                "reason": reason,
                **extra,
                "at": self._now(c).astimezone(timezone.utc).isoformat(),
            },
        )
        c.execute(
            "INSERT INTO auth_audit_outbox(audit_id,payload) VALUES (%s,%s::jsonb)",
            (record["audit_id"], json.dumps(record)),
        )
        return record["audit_id"]

    @staticmethod
    def _schema_state(c):
        return {
            "wallet": bool(
                c.execute("SELECT to_regclass('auth_wallet_lots') AS t").fetchone()["t"]
            ),
            "topups": bool(
                c.execute("SELECT to_regclass('auth_topup_orders') AS t").fetchone()["t"]
            ),
            "refunds": bool(
                c.execute("SELECT to_regclass('auth_refund_orders') AS t").fetchone()["t"]
            ),
        }

    def _require_schema(self, c):
        state = self._schema_state(c)
        missing = [name for name, present in state.items() if not present]
        if missing:
            raise ValueError("billing schema required: " + ",".join(sorted(missing)))
        return state

    # ---------------------------------------------------------------- report

    def report(self):
        """Bounded read-only consistency report; ok means no blocking findings."""
        with self.store.transaction(readonly=True) as tx:
            c = tx.connection
            self._require_schema(c)
            findings = []
            accounts = []
            checked = {}

            def add(code, subject, account_id, detail=""):
                findings.append(finding(code, subject, detail))
                if code in BLOCKING_CODES and account_id:
                    accounts.append(str(account_id))

            # 1. credited order without its purchased lot
            rows = c.execute(
                "SELECT o.order_id::text AS oid, o.account_id::text AS aid "
                "FROM auth_topup_orders o WHERE o.state='credited' AND NOT EXISTS ("
                " SELECT 1 FROM auth_wallet_lots l WHERE l.origin_order=o.order_id::text"
                " AND l.account_id=o.account_id AND l.source='purchased')"
                " ORDER BY o.created_at LIMIT %s",
                (MAX_FINDINGS,),
            ).fetchall()
            checked["credited_orders"] = len(rows)
            for r in rows:
                add(
                    "credit_order_mismatch",
                    "order " + r["oid"],
                    r["aid"],
                    "credited order has no purchased lot bound to origin_order",
                )

            # 2. purchased lot whose origin_order is not a credited order
            rows = c.execute(
                "SELECT l.lot_id::text AS lid, l.account_id::text AS aid, l.origin_order AS ref "
                "FROM auth_wallet_lots l WHERE l.source='purchased' AND l.origin_order IS NOT NULL"
                " AND NOT EXISTS (SELECT 1 FROM auth_topup_orders o WHERE o.order_id::text=l.origin_order"
                " AND o.account_id=l.account_id AND o.state='credited')"
                " ORDER BY l.created_at LIMIT %s",
                (MAX_FINDINGS,),
            ).fetchall()
            checked["purchased_lots"] = len(rows)
            for r in rows:
                add(
                    "credit_order_mismatch",
                    "lot " + r["lid"],
                    r["aid"],
                    "purchased lot origin_order is not a credited order: " + str(r["ref"]),
                )

            # 3. payment_id bound to two orders (0034 UNIQUE also prevents)
            rows = c.execute(
                "SELECT payment_id::text AS pid, count(*)::int AS n,"
                " min(account_id::text) AS aid FROM auth_topup_orders"
                " WHERE payment_id IS NOT NULL GROUP BY payment_id"
                " HAVING count(*)>1 ORDER BY payment_id LIMIT %s",
                (MAX_FINDINGS,),
            ).fetchall()
            checked["payment_ids"] = len(rows)
            for r in rows:
                add(
                    "payment_id_collision",
                    "payment " + r["pid"],
                    r["aid"],
                    f"payment_id bound to {r['n']} orders",
                )

            # 4. refund state vs lot buckets
            rows = c.execute(
                "SELECT r.refund_id::text AS rid, r.state, r.units, r.account_id::text AS aid,"
                " l.refund_pending, l.refunded, o.state AS order_state"
                " FROM auth_refund_orders r JOIN auth_wallet_lots l ON l.lot_id=r.lot_id"
                " LEFT JOIN auth_topup_orders o ON o.order_id=r.order_id"
                " ORDER BY r.created_at LIMIT %s",
                (MAX_FINDINGS,),
            ).fetchall()
            checked["refund_orders"] = len(rows)
            for r in rows:
                units = int(r["units"])
                pending = int(r["refund_pending"] or 0)
                refunded = int(r["refunded"] or 0)
                bad = None
                if r["order_state"] != "credited":
                    bad = f"refund order references order state {r['order_state']}"
                elif r["state"] == "refunded":
                    if refunded < units or pending > 0:
                        bad = "refunded refund but lot buckets regressed"
                elif r["state"] in ("pending", "review_required"):
                    if pending <= 0:
                        bad = "alive refund without the refund_pending hold"
                elif r["state"] == "failed" and pending > 0:
                    bad = "failed refund kept the hold"
                if bad:
                    add("refund_state_mismatch", r["rid"], r["aid"], bad)

            # 5. dispute state vs wallet lock
            rows = c.execute(
                "SELECT d.dispute_id::text AS did, d.state, d.opened_reason,"
                " d.wallet_was_locked, d.account_id::text AS aid,"
                " w.status AS wallet_status, w.locked_reason"
                " FROM auth_disputes d LEFT JOIN auth_wallets w ON w.account_id=d.account_id"
                " ORDER BY d.created_at LIMIT %s",
                (MAX_FINDINGS,),
            ).fetchall()
            checked["disputes"] = len(rows)
            for r in rows:
                if r["state"] == "open" and r["wallet_status"] != "locked":
                    add(
                        "dispute_state_mismatch",
                        r["did"],
                        r["aid"],
                        "open dispute without the wallet finance hold",
                    )
                elif (
                    r["state"] == "won"
                    and not r["wallet_was_locked"]
                    and r["wallet_status"] == "locked"
                    and r["locked_reason"] == r["opened_reason"]
                ):
                    add(
                        "dispute_state_mismatch",
                        r["did"],
                        r["aid"],
                        "won dispute but the wallet is still locked by it",
                    )

            # 6./7. lot projection and balance drift (restore/DBA artifacts).
            # Posting reconstruction: available = original issue + sum(deltas);
            # every other bucket equals its delta sum; issued equals the bucket sum.
            rows = c.execute(
                "SELECT l.lot_id::text AS lid, l.account_id::text AS aid, l.issued,"
                " l.available, l.reserved, l.spent, l.expired, l.refund_pending, l.refunded"
                " FROM auth_wallet_lots l"
                " WHERE l.available::numeric <> l.issued::numeric + COALESCE(("
                "  SELECT sum(p.available_delta) FROM auth_wallet_postings p WHERE p.lot_id=l.lot_id),0)::numeric"
                " OR l.reserved::numeric <> COALESCE(("
                "  SELECT sum(p.reserved_delta) FROM auth_wallet_postings p WHERE p.lot_id=l.lot_id),0)::numeric"
                " OR l.spent::numeric <> COALESCE(("
                "  SELECT sum(p.spent_delta) FROM auth_wallet_postings p WHERE p.lot_id=l.lot_id),0)::numeric"
                " OR l.expired::numeric <> COALESCE(("
                "  SELECT sum(p.expired_delta) FROM auth_wallet_postings p WHERE p.lot_id=l.lot_id),0)::numeric"
                " OR l.refund_pending::numeric <> COALESCE(("
                "  SELECT sum(p.refund_pending_delta) FROM auth_wallet_postings p WHERE p.lot_id=l.lot_id),0)::numeric"
                " OR l.refunded::numeric <> COALESCE(("
                "  SELECT sum(p.refunded_delta) FROM auth_wallet_postings p WHERE p.lot_id=l.lot_id),0)::numeric"
                " OR l.issued::numeric <> (l.available::numeric+l.reserved::numeric"
                "  +l.spent::numeric+l.expired::numeric+l.refund_pending::numeric+l.refunded::numeric)"
                " ORDER BY l.lot_id LIMIT %s",
                (MAX_FINDINGS,),
            ).fetchall()
            checked["lot_projections"] = len(rows)
            for r in rows:
                buckets = (
                    int(r["available"]),
                    int(r["reserved"]),
                    int(r["spent"]),
                    int(r["expired"]),
                    int(r["refund_pending"]),
                    int(r["refunded"]),
                )
                if int(r["issued"]) != sum(buckets):
                    add(
                        "lot_balance_violation",
                        "lot " + r["lid"],
                        r["aid"],
                        "issued != sum of buckets (0033 CHECK normally prevents)",
                    )
                else:
                    add(
                        "lot_projection_drift",
                        "lot " + r["lid"],
                        r["aid"],
                        "lot columns differ from the posting reconstruction "
                        "(projection must move only by append-only postings)",
                    )

            # 8. captured money waiting for the operator resolution (info)
            rows = c.execute(
                "SELECT o.order_id::text AS oid, o.account_id::text AS aid"
                " FROM auth_topup_orders o WHERE o.state='paid_review'"
                " ORDER BY o.created_at LIMIT %s",
                (MAX_FINDINGS,),
            ).fetchall()
            checked["paid_review"] = len(rows)
            for r in rows:
                add(
                    "paid_review_open",
                    "order " + r["oid"],
                    r["aid"],
                    "captured money awaits manage_topups credit-paid",
                )

            # 9. inbox events for unowned payment ids (info)
            rows = c.execute(
                "SELECT i.payment_id, count(*)::int AS n FROM auth_topup_inbox i"
                " WHERE NOT EXISTS (SELECT 1 FROM auth_topup_orders o WHERE o.payment_id=i.payment_id)"
                " GROUP BY i.payment_id ORDER BY i.payment_id LIMIT %s",
                (MAX_FINDINGS,),
            ).fetchall()
            checked["unowned_inbox"] = len(rows)
            for r in rows:
                add(
                    "inbox_unowned_event",
                    "payment " + str(r["payment_id"]),
                    None,
                    f"{r['n']} inbox events without a bound order",
                )

            pending_audit = int(
                c.execute(
                    "SELECT count(*) AS n FROM auth_audit_outbox WHERE delivered_at IS NULL"
                ).fetchone()["n"]
            )
            if pending_audit:
                add(
                    "audit_outbox_pending",
                    "audit_outbox",
                    None,
                    f"{pending_audit} mandatory audit intents await delivery (AUTH-20)",
                )

            counts = {
                "blocking": sum(1 for f in findings if f["severity"] == "blocking"),
                "info": sum(1 for f in findings if f["severity"] == "info"),
            }
            now = self._now(c)
        return {
            "ok": counts["blocking"] == 0,
            "checked": checked,
            "findings": findings,
            "counts": counts,
            "accounts_with_blockers": sorted(set(accounts)),
            "generated_at": now.astimezone(timezone.utc).isoformat(),
            "bounded": len(findings) >= MAX_FINDINGS,
        }

    # ------------------------------------------------------------- watermark

    def export_watermark(self, path):
        """Out-of-pgdata terminal financial facts (atomic tmp+rename, 0600).
        Run BEFORE every backup (runbook)."""
        with self.store.transaction(readonly=True) as tx:
            c = tx.connection
            self._require_schema(c)
            entries = []
            for r in c.execute(
                "SELECT order_id::text AS oid, account_id::text AS aid, payment_id,"
                " credited_at FROM auth_topup_orders WHERE state='credited'"
                " ORDER BY created_at LIMIT %s",
                (WATERMARK_MAX_ENTRIES,),
            ).fetchall():
                entries.append(
                    {
                        "kind": "order",
                        "order_id": r["oid"],
                        "account_id": r["aid"],
                        "payment_id": r["payment_id"] or "",
                        "state": "credited",
                        "credited_at": r["credited_at"].isoformat()
                        if r["credited_at"]
                        else "",
                    }
                )
            for r in c.execute(
                "SELECT refund_id::text AS rid, order_id::text AS oid, state"
                " FROM auth_refund_orders WHERE state='refunded'"
                " ORDER BY created_at LIMIT %s",
                (max(0, WATERMARK_MAX_ENTRIES - len(entries)),),
            ).fetchall():
                entries.append(
                    {
                        "kind": "refund",
                        "refund_id": r["rid"],
                        "order_id": r["oid"],
                        "state": r["state"],
                    }
                )
            for r in c.execute(
                "SELECT dispute_id::text AS did, order_id::text AS oid, state"
                " FROM auth_disputes WHERE state IN ('lost','won')"
                " ORDER BY created_at LIMIT %s",
                (max(0, WATERMARK_MAX_ENTRIES - len(entries)),),
            ).fetchall():
                entries.append(
                    {
                        "kind": "dispute",
                        "dispute_id": r["did"],
                        "order_id": r["oid"],
                        "state": r["state"],
                    }
                )
        if len(entries) > WATERMARK_MAX_ENTRIES:
            raise ValueError("watermark exceed bounded export size")
        document = {"format": WATERMARK_FORMAT, "entries": entries}
        directory = os.path.dirname(os.path.abspath(path)) or "."
        tmp = os.path.join(directory, ".auth25-watermark-" + uuid4().hex + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(document, fh, ensure_ascii=False, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return {"path": path, "format": WATERMARK_FORMAT, "entries": len(entries)}

    def reconcile_watermark(self, document, *, reason):
        """Compare a watermark with the live DB after a backup restore.
        Money is never re-applied: every lost/regressed terminal fact becomes
        a restore_regression finding with trusted-command suggestions, and
        the run itself is audited in the same transaction."""
        _validate_reason_local(reason)
        entries = validate_watermark(document)
        regressions = []
        suggestions = {}
        with self.store.transaction() as tx:
            c = tx.connection
            self._require_schema(c)
            now = self._now(c)
            for entry in entries:
                row = None
                detail = None
                if entry["kind"] == "order":
                    row = c.execute(
                        "SELECT state FROM auth_topup_orders WHERE order_id=%s",
                        (UUID(entry["order_id"]),),
                    ).fetchone()
                    item_id = entry["order_id"]
                elif entry["kind"] == "refund":
                    # The terminal refund fact includes its lot backing: the
                    # provider-confirmed money must stay extinguished in the
                    # buckets (restore regressions revert buckets, not rows).
                    row = c.execute(
                        "SELECT r.state, r.units, l.refunded, l.refund_pending"
                        " FROM auth_refund_orders r JOIN auth_wallet_lots l ON l.lot_id=r.lot_id"
                        " WHERE r.refund_id=%s",
                        (UUID(entry["refund_id"]),),
                    ).fetchone()
                    item_id = entry["refund_id"]
                else:
                    row = c.execute(
                        "SELECT state FROM auth_disputes WHERE dispute_id=%s",
                        (UUID(entry["dispute_id"]),),
                    ).fetchone()
                    item_id = entry["dispute_id"]
                actual = row["state"] if row else None
                regressed = row is None or actual != entry["state"]
                if (
                    not regressed
                    and entry["kind"] == "refund"
                    and entry["state"] == "refunded"
                ):
                    if int(row["refunded"] or 0) < int(row["units"]) or int(
                        row["refund_pending"] or 0
                    ) > 0:
                        regressed = True
                        actual = "refunded"
                        detail = (
                            f"lot buckets regressed: refunded={row['refunded']} "
                            f"refund_pending={row['refund_pending']} units={row['units']}"
                        )
                if regressed:
                    item = {
                        "kind": entry["kind"],
                        "id": item_id,
                        "expected_state": entry["state"],
                        "actual_state": actual,
                    }
                    if detail:
                        item["detail"] = detail
                    regressions.append(item)
                    suggestions.setdefault(item_id, restore_suggestions(entry))
            self._audit(
                c,
                "reconcile_watermark",
                "billing_reconciliation",
                reason,
                compared=len(entries),
                regressions=len(regressions),
            )
        return {
            "ok": not regressions,
            "compared": len(entries),
            "regressions": regressions[:MAX_FINDINGS],
            "suggestions": suggestions,
            "audited_at": now.astimezone(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------ quarantine

    def lock_flagged(self, *, reason):
        """D3: finance hold on every wallet whose account has a blocking
        finding (uncertain state holds, never a pretend wallet). The lock,
        the wallet audit and the command audit commit in one transaction;
        unlocking stays the existing audited manage_wallet.py procedure."""
        _validate_reason_local(reason)
        rep = self.report()
        locked = []
        already = []
        if rep["accounts_with_blockers"]:
            bounded_reason = (LOCK_REASON_PREFIX + ": " + reason)[:256]
            with self.store.transaction() as tx:
                c = tx.connection
                from apps.api.billing.wallet import _wallet_audit

                for aid in rep["accounts_with_blockers"]:
                    row = c.execute(
                        "SELECT w.wallet_id, w.status, w.version FROM auth_wallets w"
                        " WHERE w.account_id=%s FOR UPDATE",
                        (UUID(aid),),
                    ).fetchone()
                    if not row:
                        continue
                    if row["status"] == "locked":
                        already.append(
                            {"account_id": aid, "wallet_id": str(row["wallet_id"])}
                        )
                        continue
                    updated = c.execute(
                        "UPDATE auth_wallets SET status='locked',locked_reason=%s,"
                        "version=version+1 WHERE wallet_id=%s AND version=%s"
                        " RETURNING wallet_id",
                        (bounded_reason, row["wallet_id"], row["version"]),
                    ).fetchone()
                    if not updated:
                        raise ValueError("wallet version conflict")
                    _wallet_audit(
                        c,
                        "wallet_status",
                        row["wallet_id"],
                        bounded_reason,
                        status="locked",
                    )
                    self._audit(
                        c,
                        "lock_flagged",
                        aid,
                        reason,
                        wallet_id=str(row["wallet_id"]),
                        blocking=rep["counts"]["blocking"],
                    )
                    locked.append(
                        {"account_id": aid, "wallet_id": str(row["wallet_id"])}
                    )
        return {
            "locked": locked,
            "already_locked": already,
            "blocking": rep["counts"]["blocking"],
        }

    # --------------------------------------------------------------- launch

    def launch_check(self, environ=None, *, allow_empty_catalog=False):
        """D4 pre-launch gate: terms/catalog/provider facts confirmed before
        real checkout. The command confirms readiness and never enables
        anything; opening live payments stays a separate delivery."""
        env = os.environ if environ is None else environ
        checks = []
        with self.store.transaction(readonly=True) as tx:
            c = tx.connection
            state = self._schema_state(c)
            now = self._now(c)
            missing = [n for n, present in state.items() if not present]
            checks.append(
                {
                    "name": "schema_ready",
                    "status": "ok" if not missing else "blocked",
                    "detail": "billing schema 0033/0034/0035 present"
                    if not missing
                    else "missing tables: " + ",".join(missing),
                }
            )
            catalog_rows = []
            if state["topups"]:
                catalog_rows = c.execute(
                    "SELECT title, units, price_minor, currency, price_version,"
                    " terms_version FROM auth_topup_packages WHERE enabled"
                    " ORDER BY created_at LIMIT 200"
                ).fetchall()
            problems = []
            for row in catalog_rows:
                try:
                    validate_package(
                        row["title"],
                        int(row["units"]),
                        int(row["price_minor"]),
                        row["currency"],
                        row["price_version"],
                        row["terms_version"],
                    )
                except ValueError as exc:
                    problems.append(f"{row['title']}: {exc}")
            if not catalog_rows:
                checks.append(
                    {
                        "name": "catalog_valid",
                        "status": "blocked",
                        "detail": "no enabled packages: checkout is disabled until "
                        "the operator provisions a versioned catalog",
                    }
                )
            elif problems:
                checks.append(
                    {
                        "name": "catalog_valid",
                        "status": "blocked",
                        "detail": "; ".join(problems)[:DETAIL_LIMIT],
                    }
                )
            else:
                terms = sorted({r["terms_version"] for r in catalog_rows})
                checks.append(
                    {
                        "name": "catalog_valid",
                        "status": "ok",
                        "detail": f"{len(catalog_rows)} enabled package(s); "
                        f"terms versions: {','.join(terms)}",
                    }
                )
        try:
            days = parse_refund_window(env)
            checks.append(
                {
                    "name": "refund_window",
                    "status": "ok",
                    "detail": f"CISSTAT_TOPUP_REFUND_DAYS={days}",
                }
            )
        except ValueError as exc:
            checks.append(
                {"name": "refund_window", "status": "blocked", "detail": str(exc)}
            )
        mode, ok, detail = provider_mode(env)
        checks.append(
            {
                "name": "provider_mode",
                "status": "ok" if ok else "blocked",
                "detail": f"mode={mode}; {detail}",
            }
        )
        rep = self.report()
        checks.append(
            {
                "name": "reconciliation_clean",
                "status": "ok" if rep["ok"] else "blocked",
                "detail": f"blocking findings: {rep['counts']['blocking']}",
            }
        )
        pending_audit = any(f["code"] == "audit_outbox_pending" for f in rep["findings"])
        checks.append(
            {
                "name": "audit_delivery",
                "status": "warn" if pending_audit else "ok",
                "detail": "pending mandatory audit intents await AUTH-20 delivery"
                if pending_audit
                else "audit outbox fully delivered",
            }
        )
        verdict = assemble_launch_verdict(checks, allow_empty_catalog=allow_empty_catalog)
        verdict["generated_at"] = now.astimezone(timezone.utc).isoformat()
        return verdict
