"""Trusted operator provisioning, CAS + existing mandatory audit outbox. No HTTP API."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from apps.api.authentication.context import auth_error
from apps.api.authentication.storage import PostgresAccessStore

from .contract import MAX_UNITS
from .coordinator import audit
from .migrations import check_schema


class BudgetPolicy:
    def __init__(self, store=None):
        self.store = store if store is not None else PostgresAccessStore.from_env()

    @staticmethod
    def _reason(reason):
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 256:
            raise ValueError("reason required")

    def create_scope(
        self,
        kind,
        *,
        scope_id=None,
        parent_id=None,
        account_id=None,
        starts_at=None,
        ends_at=None,
        reason,
    ):
        self._reason(reason)
        if kind not in ("sponsor", "campaign", "account", "grant"):
            raise ValueError("known scope required")
        sid = UUID(str(scope_id)) if scope_id else uuid4()
        account_id = UUID(str(account_id)) if account_id else None
        parent_id = UUID(str(parent_id)) if parent_id else None
        if kind == "account":
            if account_id is None or scope_id is not None and sid != account_id:
                raise ValueError("Account scope identity required")
            sid = account_id
        start = starts_at or datetime.now(UTC)
        if start.tzinfo is None or ends_at and ends_at.tzinfo is None:
            raise ValueError("aware scope lifetime required")
        with self.store.transaction() as tx:
            c = tx.connection
            check_schema(c)
            if account_id:
                c.execute(
                    "SELECT account_id FROM auth_accounts WHERE account_id=%s FOR UPDATE",
                    (account_id,),
                )
            row = c.execute(
                "INSERT INTO auth_budget_scopes(scope_id,kind,parent_id,account_id,starts_at,ends_at) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
                (sid, kind, parent_id, account_id, start, ends_at),
            ).fetchone()
            audit(
                c,
                "auth_budget_changed",
                sid,
                details={"command": "scope_created", "kind": kind, "reason": reason},
            )
            return row

    def set_status(self, scope_id, *, expected_version, status, reason):
        self._reason(reason)
        if type(expected_version) is not int or status not in (
            "active",
            "paused",
            "closed",
        ):
            raise ValueError("version/status required")
        with self.store.transaction() as tx:
            c = tx.connection
            check_schema(c)
            row = c.execute(
                "UPDATE auth_budget_scopes SET status=%s,version=version+1 WHERE scope_id=%s AND version=%s RETURNING *",
                (status, UUID(str(scope_id)), expected_version),
            ).fetchone()
            if not row:
                auth_error(409, "reservation_conflict")
            audit(
                c,
                "auth_budget_changed",
                scope_id,
                details={"command": "scope_status", "status": status, "reason": reason},
            )
            return row

    def set_budget(
        self,
        scope_id,
        metric,
        *,
        limit_units,
        period="lifetime",
        expected_version=0,
        reason,
    ):
        self._reason(reason)
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError("CAS version required")
        if (
            metric not in ("cu", "api", "analysis", "concurrency")
            or limit_units is not None
            and (type(limit_units) is not int or not 0 <= limit_units <= MAX_UNITS)
        ):
            raise ValueError("finite integer policy required")
        if limit_units is None and metric in ("cu", "concurrency"):
            raise ValueError("finite monetary/resource budget required")
        import re

        if period != "lifetime" and not re.fullmatch(
            r"[0-9]{4}-(0[1-9]|1[0-2])", period
        ):
            raise ValueError("known period required")
        sid = UUID(str(scope_id))
        with self.store.transaction() as tx:
            c = tx.connection
            check_schema(c)
            scope = c.execute(
                "SELECT * FROM auth_budget_scopes WHERE scope_id=%s FOR UPDATE", (sid,)
            ).fetchone()
            if not scope:
                auth_error(503, "budget_not_configured")
            if scope["kind"] == "account" and metric in ("api", "analysis"):
                raise ValueError("Account counters derive only from current caps")
            old = c.execute(
                "SELECT * FROM auth_resource_budgets WHERE scope_id=%s AND metric=%s AND period=%s FOR UPDATE",
                (sid, metric, period),
            ).fetchone()
            if (old["version"] if old else 0) != expected_version:
                auth_error(409, "reservation_conflict")
            if old:
                row = c.execute(
                    "UPDATE auth_resource_budgets SET limit_units=%s,version=version+1 WHERE budget_id=%s RETURNING *",
                    (limit_units, old["budget_id"]),
                ).fetchone()
            else:
                row = c.execute(
                    "INSERT INTO auth_resource_budgets(budget_id,scope_id,metric,period,limit_units) VALUES (%s,%s,%s,%s,%s) RETURNING *",
                    (uuid4(), sid, metric, period, limit_units),
                ).fetchone()
            audit(
                c,
                "auth_budget_changed",
                row["budget_id"],
                details={
                    "command": "budget_policy",
                    "metric": metric,
                    "period": period,
                    "reason": reason,
                },
            )
            return row
