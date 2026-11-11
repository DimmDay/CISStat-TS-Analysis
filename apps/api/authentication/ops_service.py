"""AUTH-20 operations authority: audit outbox delivery, durable revocation
ledger reconciliation, quarantine and health facts.

CLI-first (scripts/auth20/reconcile.py); no HTTP routes are added. Every
mutation writes the mandatory auth_ops_changed audit intent into the existing
auth_audit_outbox inside the SAME transaction (fail-closed). Reconciliation
re-applies terminal states recorded by the 0032 capture triggers and never
creates a second charge: reservations are closed without posting deltas
(under-charge is reported, over-charge is impossible by construction).
"""

import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

from .context import AuthHTTPException, auth_error
from .sessions import boundary
from .storage import PostgresAccessStore

MARKS_FORMAT = "cisstat-auth20-marks/1"
MARKS_MAX_ENTRIES = 100_000
RECONCILE_MAX_ITEMS = 5_000
QUARANTINE_BATCH = 100
PRUNE_BATCH = 1_000
LEDGER_RETENTION_MIN_DAYS = 7
LEDGER_RETENTION_DEFAULT_DAYS = 180

# Reconcilable (table, event) pairs; anything else is rejected before SQL.
RECONCILABLE = {
    ("auth_password_credentials", "revoked"),
    ("auth_sessions", "revoked"),
    ("auth_api_keys", "revoked"),
    ("auth_worker_services", "revoked"),
    ("auth_demo_grants", "revoked"),
    ("auth_demo_admissions", "consumed"),
    ("auth_reservations", "settled"),
    ("auth_reservations", "released"),
    ("auth_billing_orders", "applied"),
    ("auth_billing_orders", "canceled"),
}


def parse_retention_days(raw):
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return LEDGER_RETENTION_DEFAULT_DAYS
    if value < LEDGER_RETENTION_MIN_DAYS:
        return LEDGER_RETENTION_MIN_DAYS
    return value


def _iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


class AuthOpsService:
    """Durable ops on top of the existing PostgresAccessStore connection
    discipline; never runs DDL and never bypasses store transactions."""

    def __init__(self, store=None):
        self.store = store if store is not None else PostgresAccessStore.from_env()

    # -- shared ---------------------------------------------------------

    @staticmethod
    def _ops_audit(c, kind, details, now):
        """Mandatory auth_ops_changed intent in the SAME transaction."""
        import json as _json

        from apps.api.security_audit import build_audit_record

        record = build_audit_record(
            "auth_ops_changed",
            "allowed",
            actor_subject="ops-cli",
            actor_via="auth_ops",
            resource_kind="auth_ops",
            resource_id=kind,
            policy_basis="AUTH-20 operations runbook",
            details={"kind": kind, **details, "at": _iso(now)},
        )
        c.execute(
            "INSERT INTO auth_audit_outbox(audit_id,payload) VALUES (%s,%s::jsonb)",
            (record["audit_id"], _json.dumps(record)),
        )
        return record["audit_id"]

    def _now(self, c):
        row = c.execute("SELECT now() AS t").fetchone()
        return row["t"]

    def _check(self, c):
        from .auth20_migrations import check_schema

        check_schema(c)

    # -- audit delivery --------------------------------------------------

    @boundary
    def drain_audit(self, *, limit=100, sink=None):
        """One bounded delivery batch of the AUTH-04 audit outbox.
        Memory sink refusal stays a 503 (no pretend-durable delivery)."""
        if not isinstance(limit, int) or not 1 <= limit <= 200:
            auth_error(422, "invalid_request")
        from .audit_outbox import publish_pending

        return publish_pending(store=self.store, sink=sink, limit=limit)

    # -- ledger facts ----------------------------------------------------

    @boundary
    def ledger_stats(self):
        with self.store.transaction(readonly=True) as tx:
            c = tx.connection
            self._check(c)
            total = c.execute("SELECT count(*) AS n FROM auth_ops_ledger").fetchone()["n"]
            recent = c.execute(
                "SELECT count(*) AS n FROM auth_ops_ledger WHERE occurred_at > now() - interval '24 hours'"
            ).fetchone()["n"]
            oldest = c.execute(
                "SELECT min(occurred_at) AS t FROM auth_ops_ledger"
            ).fetchone()["t"]
        return {"total": total, "last_24h": recent, "oldest_at": _iso(oldest)}

    @boundary
    def prune_ledger(self, *, retention_days=None, batch=PRUNE_BATCH):
        days = (
            LEDGER_RETENTION_DEFAULT_DAYS
            if retention_days is None
            else parse_retention_days(retention_days)
        )
        if not isinstance(batch, int) or not 1 <= batch <= PRUNE_BATCH:
            auth_error(422, "invalid_request")
        with self.store.transaction() as tx:
            c = tx.connection
            self._check(c)
            removed = c.execute(
                """DELETE FROM auth_ops_ledger WHERE entry_id IN (
                    SELECT entry_id FROM auth_ops_ledger
                    WHERE occurred_at < clock_timestamp() - (%s || ' days')::interval
                    ORDER BY entry_id LIMIT %s) RETURNING entry_id""",
                (str(days), batch),
            ).fetchall()
        return {"pruned": len(removed), "retention_days": days}

    # -- marks export ----------------------------------------------------

    @boundary
    def read_ledger(self, *, after_entry_id=0, limit=MARKS_MAX_ENTRIES):
        if not isinstance(after_entry_id, int) or after_entry_id < 0:
            auth_error(422, "invalid_request")
        if not isinstance(limit, int) or not 1 <= limit <= MARKS_MAX_ENTRIES:
            auth_error(422, "invalid_request")
        with self.store.transaction(readonly=True) as tx:
            c = tx.connection
            self._check(c)
            rows = c.execute(
                """SELECT entry_id,table_name,row_id,event,row_image,occurred_at
                FROM auth_ops_ledger WHERE entry_id>%s ORDER BY entry_id LIMIT %s""",
                (after_entry_id, limit),
            ).fetchall()
        entries = [
            {
                "entry_id": r["entry_id"],
                "table": r["table_name"],
                "row_id": str(r["row_id"]),
                "event": r["event"],
                "occurred_at": _iso(r["occurred_at"]),
                "row_image": r["row_image"],
            }
            for r in rows
        ]
        return entries

    def export_marks(self, path, *, after_entry_id=0):
        """Out-of-band marks file (atomic tmp+rename, owner-only). The file
        lives on a volume OUTSIDE pgdata; restore reconciliation replays it."""
        if not path or not isinstance(path, str):
            auth_error(422, "invalid_request")
        entries = self.read_ledger(after_entry_id=after_entry_id)
        complete = len(entries) < MARKS_MAX_ENTRIES
        document = {
            "format": MARKS_FORMAT,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "after_entry_id": after_entry_id,
            "complete": complete,
            "counts": {
                key: sum(
                    1
                    for e in entries
                    if f"{e['table']}:{e['event']}" == key
                )
                for key in sorted({f"{e['table']}:{e['event']}" for e in entries})
            },
            "entries": entries,
        }
        target = os.path.abspath(path)
        directory = os.path.dirname(target) or "."
        os.makedirs(directory, exist_ok=True)
        tmp = target + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        os.chmod(target, 0o600)
        with self.store.transaction() as tx:
            c = tx.connection
            self._check(c)
            self._ops_audit(
                c,
                "marks_export",
                {"entries": len(entries), "after_entry_id": after_entry_id, "complete": complete},
                self._now(c),
            )
        return {
            "path": target,
            "entries": len(entries),
            "last_entry_id": entries[-1]["entry_id"] if entries else after_entry_id,
            "complete": complete,
        }

    # -- quarantine ------------------------------------------------------

    @boundary
    def quarantine(self, *, reason, batch=QUARANTINE_BATCH):
        """Doubt before reconciliation (architecture §8): close ALL sessions
        (epoch bump + revoke) and pause active campaigns. API/worker keys and
        password credentials are intentionally NOT touched here."""
        if not isinstance(reason, str) or not reason.strip():
            auth_error(422, "invalid_request")
        if not isinstance(batch, int) or not 1 <= batch <= 500:
            auth_error(422, "invalid_request")
        summary = {"sessions_revoked": 0, "subjects": 0, "campaigns_paused": 0, "batches": 0}
        while True:
            with self.store.transaction() as tx:
                c = tx.connection
                self._check(c)
                now = self._now(c)
                subjects = [
                    r["subject_id"]
                    for r in c.execute(
                        """SELECT DISTINCT subject_id FROM auth_sessions
                        WHERE revoked_at IS NULL LIMIT %s""",
                        (batch,),
                    ).fetchall()
                ]
                if not subjects:
                    break
                epoch = 0
                revoked = 0
                for subject_id in subjects:
                    epoch += c.execute(
                        "UPDATE auth_subject_security SET session_epoch=session_epoch+1 WHERE subject_id=%s",
                        (subject_id,),
                    ).rowcount
                    revoked += c.execute(
                        "UPDATE auth_sessions SET revoked_at=%s WHERE subject_id=%s AND revoked_at IS NULL",
                        (now, subject_id),
                    ).rowcount
                self._ops_audit(
                    c,
                    "quarantine",
                    {
                        "reason": reason.strip()[:200],
                        "subjects": len(subjects),
                        "sessions_revoked": revoked,
                    },
                    now,
                )
                summary["sessions_revoked"] += revoked
                summary["subjects"] += len(subjects)
                summary["batches"] += 1
        with self.store.transaction() as tx:
            c = tx.connection
            self._check(c)
            now = self._now(c)
            paused = c.execute(
                "UPDATE auth_demo_campaigns SET status='paused' WHERE status='active' RETURNING campaign_id"
            ).fetchall()
            if paused:
                self._ops_audit(
                    c,
                    "quarantine",
                    {"reason": reason.strip()[:200], "campaigns_paused": len(paused)},
                    now,
                )
            summary["campaigns_paused"] = len(paused)
        return summary

    # -- restore reconciliation -------------------------------------------

    @staticmethod
    def validate_marks(document):
        """Marks contract: format tag, bounded entry list, known table/event
        pairs, UUID row ids, object row images, ISO timestamps."""
        if not isinstance(document, dict):
            raise ValueError("marks document must be an object")
        if document.get("format") != MARKS_FORMAT:
            raise ValueError("unsupported marks format")
        entries = document.get("entries")
        if not isinstance(entries, list):
            raise ValueError("marks entries must be a list")
        if len(entries) > MARKS_MAX_ENTRIES:
            raise ValueError("marks exceed bounded export size")
        parsed = []
        for raw in entries:
            if not isinstance(raw, dict):
                raise ValueError("mark entry must be an object")
            table = raw.get("table")
            event = raw.get("event")
            if (table, event) not in RECONCILABLE:
                raise ValueError(f"unreconcilable capture {table}:{event}")
            row_id = raw.get("row_id")
            image = raw.get("row_image")
            occurred = raw.get("occurred_at")
            if not isinstance(row_id, str) or not isinstance(image, dict):
                raise ValueError("mark row binding incomplete")
            UUID(row_id)
            if not isinstance(occurred, str) or not occurred:
                raise ValueError("mark timestamp missing")
            datetime.fromisoformat(occurred.replace("Z", "+00:00"))
            if int(raw.get("entry_id", 0)) <= 0:
                raise ValueError("mark entry_id missing")
            parsed.append(
                {
                    "entry_id": int(raw["entry_id"]),
                    "table": table,
                    "event": event,
                    "row_id": row_id,
                    "occurred_at": occurred,
                    "row_image": image,
                }
            )
        parsed.sort(key=lambda item: item["entry_id"])
        return parsed

    def reconcile_marks(self, document, *, reason=None):
        """Re-apply terminal states from an exported marks document after a
        backup restore. Idempotent: each item is a no-op once the row is
        already in the recorded terminal state. Bounded per run."""
        items = self.validate_marks(document)
        if len(items) > RECONCILE_MAX_ITEMS:
            auth_error(422, "invalid_request")
        summary = {
            "applied": 0,
            "skipped": 0,
            "unrepairable": [],
            "budget_recheck_required": 0,
            "items": len(items),
        }
        for item in items:
            handler = {
                ("auth_password_credentials", "revoked"): self._reconcile_password,
                ("auth_sessions", "revoked"): self._reconcile_session,
                ("auth_api_keys", "revoked"): self._reconcile_api_key,
                ("auth_worker_services", "revoked"): self._reconcile_worker,
                ("auth_demo_grants", "revoked"): self._reconcile_grant,
                ("auth_demo_admissions", "consumed"): self._reconcile_admission,
                ("auth_reservations", "settled"): self._reconcile_reservation,
                ("auth_reservations", "released"): self._reconcile_reservation,
                ("auth_billing_orders", "applied"): self._reconcile_order,
                ("auth_billing_orders", "canceled"): self._reconcile_order,
            }[(item["table"], item["event"])]
            try:
                outcome = handler(item)
            except AuthHTTPException:
                # One broken item must not stop a bounded reconcile run;
                # the item stays in the marks file for a later re-run.
                outcome = "reconcile_item_failed"
            if outcome in ("applied", "applied_undercharged"):
                summary["applied"] += 1
                if outcome == "applied_undercharged":
                    summary["budget_recheck_required"] += 1
            elif outcome == "skipped":
                summary["skipped"] += 1
            else:
                summary["unrepairable"].append(
                    {
                        "table": item["table"],
                        "row_id": item["row_id"],
                        "event": item["event"],
                        "reason": outcome,
                    }
                )
        with self.store.transaction() as tx:
            c = tx.connection
            self._check(c)
            self._ops_audit(
                c,
                "reconcile",
                {
                    "items": summary["items"],
                    "applied": summary["applied"],
                    "skipped": summary["skipped"],
                    "unrepairable": len(summary["unrepairable"]),
                    "reason": (reason or "").strip()[:200] or None,
                },
                self._now(c),
            )
        return summary

    # -- per-table re-apply (each returns applied|skipped|<reason>) -------

    def _reconcile_password(self, item):
        with self.store.transaction() as tx:
            c = tx.connection
            self._check(c)
            row = c.execute(
                "SELECT credential_id,subject_id,status FROM auth_password_credentials WHERE credential_id=%s",
                (UUID(item["row_id"]),),
            ).fetchone()
            if not row or row["status"] == "revoked":
                return "skipped" if row else "credential_row_absent"
            now = self._now(c)
            c.execute(
                "UPDATE auth_password_credentials SET status='revoked' WHERE credential_id=%s AND status='active'",
                (row["credential_id"],),
            )
            c.execute(
                "UPDATE auth_subject_security SET session_epoch=session_epoch+1 WHERE subject_id=%s",
                (row["subject_id"],),
            )
            revoked = c.execute(
                "UPDATE auth_sessions SET revoked_at=%s WHERE subject_id=%s AND revoked_at IS NULL",
                (now, row["subject_id"]),
            ).rowcount
            self._ops_audit(
                c,
                "reconcile",
                {"target": "auth_password_credentials", "row_id": item["row_id"], "sessions_revoked": revoked},
                now,
            )
            return "applied"

    def _reconcile_session(self, item):
        with self.store.transaction() as tx:
            c = tx.connection
            self._check(c)
            row = c.execute(
                "SELECT session_id,revoked_at FROM auth_sessions WHERE session_id=%s",
                (UUID(item["row_id"]),),
            ).fetchone()
            if not row or row["revoked_at"] is not None:
                return "skipped" if row else "session_row_absent"
            occurred = datetime.fromisoformat(item["occurred_at"].replace("Z", "+00:00"))
            c.execute(
                "UPDATE auth_sessions SET revoked_at=%s WHERE session_id=%s AND revoked_at IS NULL",
                (occurred, row["session_id"]),
            )
            return "applied"

    def _reconcile_api_key(self, item):
        with self.store.transaction() as tx:
            c = tx.connection
            self._check(c)
            row = c.execute(
                "SELECT key_id,revoked_at,created_at,version FROM auth_api_keys WHERE key_id=%s",
                (UUID(item["row_id"]),),
            ).fetchone()
            if not row or row["revoked_at"] is not None:
                return "skipped" if row else "api_key_row_absent"
            occurred = datetime.fromisoformat(item["occurred_at"].replace("Z", "+00:00"))
            revoked_at = max(occurred, row["created_at"])
            c.execute(
                "UPDATE auth_api_keys SET revoked_at=%s,version=version+1 WHERE key_id=%s AND revoked_at IS NULL",
                (revoked_at, row["key_id"]),
            )
            return "applied"

    def _reconcile_worker(self, item):
        with self.store.transaction() as tx:
            c = tx.connection
            self._check(c)
            row = c.execute(
                "SELECT service_id,revoked_at FROM auth_worker_services WHERE service_id=%s",
                (UUID(item["row_id"]),),
            ).fetchone()
            if not row or row["revoked_at"] is not None:
                return "skipped" if row else "worker_service_row_absent"
            occurred = datetime.fromisoformat(item["occurred_at"].replace("Z", "+00:00"))
            c.execute(
                "UPDATE auth_worker_services SET revoked_at=%s WHERE service_id=%s AND revoked_at IS NULL",
                (occurred, row["service_id"]),
            )
            return "applied"

    def _reconcile_grant(self, item):
        with self.store.transaction() as tx:
            c = tx.connection
            self._check(c)
            row = c.execute(
                "SELECT grant_id,status FROM auth_demo_grants WHERE grant_id=%s",
                (UUID(item["row_id"]),),
            ).fetchone()
            if row:
                if row["status"] == "revoked":
                    return "skipped"
                now = self._now(c)
                c.execute(
                    "UPDATE auth_demo_grants SET status='revoked' WHERE grant_id=%s AND status<>'revoked'",
                    (row["grant_id"],),
                )
                c.execute(
                    "UPDATE auth_budget_scopes SET status='closed',version=version+1 WHERE scope_id=%s AND status<>'closed'",
                    (row["grant_id"],),
                )
                c.execute(
                    "UPDATE auth_sessions SET revoked_at=%s WHERE demo_grant_id=%s AND revoked_at IS NULL",
                    (now, row["grant_id"]),
                )
                return "applied"
            return self._reinsert_grant_tombstone(item, c)

    def _reinsert_grant_tombstone(self, item, c):
        """Grant created after the snapshot: replay the recorded terminal row
        when every FK parent exists; otherwise honest report."""
        image = item["row_image"]
        grant_id = UUID(item["row_id"])
        campaign_id = image.get("campaign_id")
        account_id = image.get("account_id")
        subject_id = image.get("subject_id")
        if not campaign_id or not account_id or not subject_id:
            return "grant_image_incomplete"
        campaign = c.execute(
            "SELECT 1 FROM auth_demo_campaigns WHERE campaign_id=%s", (UUID(campaign_id),)
        ).fetchone()
        membership = c.execute(
            "SELECT 1 FROM auth_memberships WHERE account_id=%s AND subject_id=%s",
            (UUID(account_id), UUID(subject_id)),
        ).fetchone()
        account_scope = c.execute(
            "SELECT 1 FROM auth_budget_scopes WHERE scope_id=%s AND kind='account'",
            (UUID(account_id),),
        ).fetchone()
        if not (campaign and membership and account_scope):
            return "grant_parents_absent"
        c.execute(
            """INSERT INTO auth_budget_scopes(scope_id,kind,parent_id,account_id,starts_at,ends_at,status)
            VALUES (%s,'grant',%s,%s,%s,%s,'closed')""",
            (
                grant_id,
                UUID(account_id),
                UUID(account_id),
                datetime.fromisoformat(image["issued_at"].replace("Z", "+00:00")),
                datetime.fromisoformat(image["expires_at"].replace("Z", "+00:00")),
            ),
        )
        c.execute(
            """INSERT INTO auth_demo_grants(grant_id,campaign_id,subject_id,account_id,resume_hash,
            issued_at,expires_at,policy_version,status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'revoked')""",
            (
                grant_id,
                UUID(campaign_id),
                UUID(subject_id),
                UUID(account_id),
                image["resume_hash"],
                datetime.fromisoformat(image["issued_at"].replace("Z", "+00:00")),
                datetime.fromisoformat(image["expires_at"].replace("Z", "+00:00")),
                int(image["policy_version"]),
            ),
        )
        c.execute(
            "UPDATE auth_demo_campaigns SET issued_grants=issued_grants+1 WHERE campaign_id=%s",
            (UUID(campaign_id),),
        )
        return "applied"

    def _reconcile_admission(self, item):
        with self.store.transaction() as tx:
            c = tx.connection
            self._check(c)
            row = c.execute(
                "SELECT admission_id,redeemed_at FROM auth_demo_admissions WHERE admission_id=%s",
                (UUID(item["row_id"]),),
            ).fetchone()
            if not row or row["redeemed_at"] is not None:
                return "skipped" if row else "admission_row_absent"
            image = item["row_image"]
            grant_id = image.get("redeemed_grant_id")
            if not grant_id:
                return "admission_image_incomplete"
            exists = c.execute(
                "SELECT 1 FROM auth_demo_grants WHERE grant_id=%s", (UUID(grant_id),)
            ).fetchone()
            if not exists:
                # auth16 guard requires a non-null redeemed_grant_id; a lost
                # grant cannot be fabricated here -> operator finding.
                return "consumed_grant_absent"
            occurred = datetime.fromisoformat(item["occurred_at"].replace("Z", "+00:00"))
            c.execute(
                "UPDATE auth_demo_admissions SET redeemed_at=%s,redeemed_grant_id=%s WHERE admission_id=%s AND redeemed_at IS NULL",
                (occurred, UUID(grant_id), row["admission_id"]),
            )
            return "applied"

    def _reconcile_reservation(self, item):
        with self.store.transaction() as tx:
            c = tx.connection
            self._check(c)
            row = c.execute(
                "SELECT reservation_id,state,version,held_cu,actual_cu FROM auth_reservations WHERE reservation_id=%s",
                (UUID(item["row_id"]),),
            ).fetchone()
            if not row:
                return "reservation_row_absent"
            if row["state"] in ("settled", "released"):
                return "skipped"
            image = item["row_image"]
            if item["event"] == "released":
                if row["state"] != "pending":
                    # running->released is not a legal transition; only the
                    # operator can close it via the AUTH-13 reconciler.
                    return "released_from_running"
                c.execute(
                    "UPDATE auth_reservations SET state='released',actual_cu=NULL,version=version+1 WHERE reservation_id=%s AND version=%s",
                    (row["reservation_id"], row["version"]),
                )
                return "applied"
            # settled: never fabricate postings/budget deltas (no over-charge);
            # clip actual to the restored hold and report the under-charge.
            actual = image.get("actual_cu")
            if actual is None:
                return "settled_image_incomplete"
            actual = min(int(actual), int(row["held_cu"] or 0))
            if actual <= 0 and int(row["held_cu"] or 0) <= 0:
                return "settled_image_incomplete"
            if row["state"] == "running":
                c.execute(
                    "UPDATE auth_reservations SET state='settled',actual_cu=%s,version=version+1 WHERE reservation_id=%s AND version=%s",
                    (actual, row["reservation_id"], row["version"]),
                )
            else:  # pending -> running -> settled
                c.execute(
                    "UPDATE auth_reservations SET state='running',version=version+1 WHERE reservation_id=%s AND version=%s",
                    (row["reservation_id"], row["version"]),
                )
                c.execute(
                    "UPDATE auth_reservations SET state='settled',actual_cu=%s,version=version+1 WHERE reservation_id=%s AND version=%s",
                    (actual, row["reservation_id"], row["version"]),
                )
            if actual < int(image.get("actual_cu") or 0):
                return "applied_undercharged"
            return "applied"

    def _reconcile_order(self, item):
        with self.store.transaction() as tx:
            c = tx.connection
            self._check(c)
            row = c.execute(
                "SELECT order_id,state,payment_id FROM auth_billing_orders WHERE order_id=%s",
                (UUID(item["row_id"]),),
            ).fetchone()
            if not row:
                return "order_row_absent"
            if row["state"] not in ("pending",):
                return "skipped"
            image = item["row_image"]
            payment = image.get("payment_id")
            if row["payment_id"] is None and payment:
                c.execute(
                    "UPDATE auth_billing_orders SET payment_id=%s,state=%s WHERE order_id=%s AND state='pending'",
                    (payment, item["event"], row["order_id"]),
                )
            else:
                c.execute(
                    "UPDATE auth_billing_orders SET state=%s WHERE order_id=%s AND state='pending'",
                    (item["event"], row["order_id"]),
                )
            return "applied"
