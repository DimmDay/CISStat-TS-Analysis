"""Trusted AUTH-12 coordinator. No broker/network, public writer or auto-credit."""

import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from apps.api.access_registry import REGISTRY, evaluate_entry
from apps.api.accounts.entitlements import account_capabilities, account_is_active
from apps.api.accounts.models import Account
from apps.api.authentication.context import RequestContext, auth_error
from apps.api.authentication.sessions import SessionService, boundary
from apps.api.authentication.storage import PostgresAccessStore

from .contract import MAX_UNITS, Admission, digest_payload, utc_month
from .migrations import VERSION, check_schema

NEW_RUN_OPERATIONS = frozenset(
    {"upload.file.load", "upload.db.load", "upload.demo_dataset.load"}
)
# v1 counts accepted programmatic scientific requests; no current binding is polling/health.
API_QUOTA_POLICY = "accepted-programmatic/1"
RANK = {"sponsor": 0, "campaign": 1, "account": 2, "grant": 3}


class Receipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    reservation_id: UUID
    account_id: UUID
    subject_id: UUID
    canonical_operation: str
    state: str
    version: int
    held_cu: int
    quote_version: str
    deadline: datetime
    lease_until: datetime | None
    actual_cu: int | None
    result_ref: str | None

    @classmethod
    def of(cls, row):
        return cls(**{k: row[k] for k in cls.model_fields})


def audit(c, action, resource, *, actor="operator:local", tenant=None, details=None):
    from apps.api.security_audit import build_audit_record

    record = build_audit_record(
        action,
        "allowed",
        actor_subject=str(actor),
        actor_via="trusted_coordinator",
        tenant_id=str(tenant) if tenant else None,
        resource_kind="budget_reservation",
        resource_id=str(resource),
        policy_basis="AUTH-12 atomic coordinator",
        details=details,
    )
    c.execute(
        "INSERT INTO auth_audit_outbox(audit_id,payload) VALUES (%s,%s::jsonb)",
        (record["audit_id"], json.dumps(record)),
    )


class ReservationCoordinator:
    """Caller must already prove object access and normalize actual workload (AUTH-11).

    This module rechecks current credentials/Account/functional permissions; it is
    NOT a replacement object gate. Do not mount its provisioning/settlement API.
    """

    def __init__(self, store=None):
        self.store = store if store is not None else PostgresAccessStore.from_env()

    @staticmethod
    def _now(c):
        return c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]

    @staticmethod
    def _root(c, account, now):
        c.execute(
            """INSERT INTO auth_budget_scopes(scope_id,kind,account_id,starts_at)
        VALUES (%s,'account',%s,%s) ON CONFLICT(scope_id) DO NOTHING""",
            (account.account_id, account.account_id, now),
        )

    def _authority(self, c, ctx, entry=None):
        if (
            not isinstance(ctx, RequestContext)
            or not ctx.is_authenticated
            or not ctx.account_id
        ):
            auth_error(401, "authentication_required")
        u = c.execute(
            "SELECT * FROM auth_identities WHERE subject_id=%s FOR UPDATE",
            (UUID(ctx.subject_id),),
        ).fetchone()
        row = c.execute(
            "SELECT * FROM auth_accounts WHERE account_id=%s FOR UPDATE",
            (UUID(ctx.account_id),),
        ).fetchone()
        now = ReservationCoordinator._now(c)
        if (
            not u
            or u["status"] != "active"
            or u["subject_version"] != ctx.subject_version
        ):
            auth_error(401, "invalid_credential", ctx.request_id)
        member = c.execute(
            "SELECT status FROM auth_memberships WHERE account_id=%s AND subject_id=%s",
            (UUID(ctx.account_id), UUID(ctx.subject_id)),
        ).fetchone()
        if (
            not row
            or not member
            or member["status"] != "active"
            or str(row["tenant_id"]) != ctx.tenant_id
        ):
            auth_error(403, "account_access_denied", ctx.request_id)
        a = Account(**row)
        if not account_is_active(a, now=now):
            auth_error(403, "account_expired", ctx.request_id)
        from apps.api.authentication.demo import restrict_capabilities
        caps, _ = restrict_capabilities(c, a, account_capabilities(a, now=now), now)
        if ctx.auth_method == "auth_session" and ctx.auth_session_id:
            hint = c.execute(
                "SELECT token_hash FROM auth_sessions WHERE session_id=%s",
                (UUID(ctx.auth_session_id),),
            ).fetchone()
            session = SessionService(self.store)
            verified = (
                session._load(c, hint["token_hash"], touch=False) if hint else None
            )
            if (
                not verified
                or str(verified["account_id"]) != ctx.account_id
                or str(verified["subject_id"]) != ctx.subject_id
            ):
                auth_error(401, "invalid_credential", ctx.request_id)
            if entry and REGISTRY.bindings[entry].programmatic_api:
                auth_error(401, "api_key_required", ctx.request_id)
        elif ctx.auth_method == "api_key" and ctx.credential_id:
            key = c.execute(
                "SELECT * FROM auth_api_keys WHERE key_id=%s",
                (UUID(ctx.credential_id),),
            ).fetchone()
            if (
                not key
                or key["revoked_at"] is not None
                or key["expires_at"] <= now
                or key["subject_id"] != a_subject(ctx)
                or key["account_id"] != a.account_id
                or key["subject_version"] != u["subject_version"]
            ):
                auth_error(401, "invalid_credential", ctx.request_id)
            if not caps.can_use_api:
                auth_error(403, "api_not_allowed", ctx.request_id)
            if entry:
                from apps.api.authentication.api_key_policy import OPERATION_SCOPES

                binding = REGISTRY.bindings[entry]
                if (
                    not binding.programmatic_api
                    or OPERATION_SCOPES.get(binding.operation_id) not in key["scopes"]
                ):
                    auth_error(403, "api_scope_denied", ctx.request_id)
        else:
            auth_error(401, "invalid_credential", ctx.request_id)
        return a, caps, now

    @staticmethod
    def _chain(c, account_id):
        leaf = c.execute(
            "SELECT scope_id FROM auth_budget_scopes WHERE account_id=%s AND kind='grant'",
            (account_id,),
        ).fetchone()
        sid = leaf["scope_id"] if leaf else account_id
        chain = []
        for _ in range(4):
            row = c.execute(
                "SELECT * FROM auth_budget_scopes WHERE scope_id=%s", (sid,)
            ).fetchone()
            if not row:
                auth_error(503, "budget_not_configured")
            chain.append(row)
            if row["parent_id"] is None:
                break
            sid = row["parent_id"]
        else:
            auth_error(503, "budget_not_configured")
        chain.sort(key=lambda x: (RANK[x["kind"]], str(x["scope_id"])))
        return [
            c.execute(
                "SELECT * FROM auth_budget_scopes WHERE scope_id=%s FOR UPDATE",
                (r["scope_id"],),
            ).fetchone()
            for r in chain
        ]

    @staticmethod
    def _scope_lifetime(chain, now, deadline=None):
        if any(
            r["status"] != "active"
            or now < r["starts_at"]
            or (
                r["ends_at"]
                and (now >= r["ends_at"] or deadline and deadline > r["ends_at"])
            )
            for r in chain
        ):
            auth_error(403, "budget_scope_inactive")

    @staticmethod
    def _account_counters(c, a, caps, now):
        for metric, period, limit in [
            ("api", utc_month(now), caps.max_api_calls_per_month),
            ("analysis", "lifetime", caps.max_analyses_total),
        ]:
            row = c.execute(
                "SELECT * FROM auth_resource_budgets WHERE scope_id=%s AND metric=%s AND period=%s",
                (a.account_id, metric, period),
            ).fetchone()
            if row is None:
                c.execute(
                    "INSERT INTO auth_resource_budgets(budget_id,scope_id,metric,period,limit_units) VALUES (%s,%s,%s,%s,%s)",
                    (uuid4(), a.account_id, metric, period, limit),
                )
            elif row["limit_units"] != limit:
                c.execute(
                    "UPDATE auth_resource_budgets SET limit_units=%s,version=version+1 WHERE budget_id=%s",
                    (limit, row["budget_id"]),
                )

    @staticmethod
    def _charge(c, rid, event, b, *, hold=0, spend=0):
        reserved = b["reserved"] + hold
        spent = b["spent"] + spend
        if reserved < 0 or spent < 0 or reserved + spent > MAX_UNITS:
            auth_error(409, "budget_overflow")
        if (
            hold + spend > 0
            and b["limit_units"] is not None
            and reserved + spent > b["limit_units"]
        ):
            auth_error(
                429 if b["metric"] == "concurrency" else 402,
                "concurrency_exceeded"
                if b["metric"] == "concurrency"
                else "quota_exceeded",
            )
        if hold == 0 and spend == 0:
            return
        c.execute(
            "INSERT INTO auth_usage_postings(reservation_id,event_no,budget_id,available_delta,reserved_delta,spent_delta) VALUES (%s,%s,%s,%s,%s,%s)",
            (rid, event, b["budget_id"], -hold - spend, hold, spend),
        )

    @boundary
    def reserve(self, ctx, admission):
        if not isinstance(admission, Admission):
            raise TypeError("validated Admission required")
        req = Admission.model_validate(admission.model_dump())
        binding = REGISTRY.bindings.get(req.entry_id)
        if not binding:
            auth_error(403, "unknown_entry")
        op = binding.operation_id
        if req.analysis_run_id and (
            op not in NEW_RUN_OPERATIONS
            or req.resource_kind != "run"
            or req.analysis_run_id != req.resource_id
        ):
            auth_error(409, "invalid_analysis_claim")
        safe = req.model_dump(
            mode="json", exclude={"payload", "idempotency_key", "cost"}
        )
        canonical = {
            **safe,
            "operation": op,
            "payload_digest": digest_payload(req.payload),
            "cost": req.cost.model_dump(),
            "api_quota_policy": API_QUOTA_POLICY,
        }
        digest = digest_payload(canonical)
        key = digest_payload(req.idempotency_key)
        with self.store.transaction() as tx:
            c = tx.connection
            check_schema(c)
            a, caps, now = self._authority(c, ctx, req.entry_id)
            decision = evaluate_entry(
                caps, req.entry_id, workload=req.workload, stage=req.stage
            )
            if not decision.allowed:
                auth_error(
                    402
                    if decision.code
                    in (
                        "capability_not_included",
                        "baseline_limit_exceeded",
                        "dataset_limit_exceeded",
                    )
                    else 403,
                    decision.code,
                    ctx.request_id,
                )
            old = c.execute(
                "SELECT * FROM auth_reservations WHERE account_id=%s AND subject_id=%s AND canonical_operation=%s AND key_digest=%s",
                (a.account_id, a_subject(ctx), op, key),
            ).fetchone()
            if old:
                if old["payload_digest"] != digest:
                    auth_error(409, "idempotency_conflict", ctx.request_id)
                return Receipt.of(old)
            if req.deadline <= now or req.deadline > now + timedelta(days=1):
                auth_error(403, "reservation_expired")
            self._root(c, a, now)
            chain = self._chain(c, a.account_id)
            now = self._now(c)
            self._scope_lifetime(chain, now, req.deadline)
            if now >= req.deadline or not account_is_active(a, now=now):
                auth_error(403, "reservation_expired")
            if a.plan_expires_at and req.deadline > a.plan_expires_at:
                auth_error(403, "reservation_expired")
            self._account_counters(c, a, caps, now)
            claimed = bool(
                req.analysis_run_id
                and c.execute(
                    "SELECT 1 FROM auth_analysis_claims WHERE account_id=%s AND run_id=%s",
                    (a.account_id, req.analysis_run_id),
                ).fetchone()
            )
            amounts = {
                "cu": req.cost.micro_cu,
                "api": int(binding.programmatic_api),
                "analysis": int(bool(req.analysis_run_id) and not claimed),
                "concurrency": req.slots,
            }
            budgets = []
            for scope in chain:
                for metric, n in sorted(amounts.items()):
                    if not n:
                        continue
                    period = utc_month(now) if metric == "api" else "lifetime"
                    row = c.execute(
                        "SELECT * FROM auth_resource_budgets WHERE scope_id=%s AND metric=%s AND period=%s FOR UPDATE",
                        (scope["scope_id"], metric, period),
                    ).fetchone()
                    if not row:
                        auth_error(503, "budget_not_configured")
                    budgets.append((row, n))
            safe = {
                **safe,
                "subject_version": ctx.subject_version,
                "entitlement_version": a.entitlement_version,
                "api_quota_policy": API_QUOTA_POLICY,
                "scope_versions": [
                    {"scope_id": str(s["scope_id"]), "version": s["version"]}
                    for s in chain
                ],
            }
            rid = uuid4()
            row = c.execute(
                """INSERT INTO auth_reservations(reservation_id,account_id,subject_id,tenant_id,canonical_operation,key_digest,payload_digest,admission,quote_version,held_cu,state,created_at,deadline)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,'pending',%s,%s) RETURNING *""",
                (
                    rid,
                    a.account_id,
                    a_subject(ctx),
                    a.tenant_id,
                    op,
                    key,
                    digest,
                    json.dumps(safe),
                    req.cost.version,
                    req.cost.micro_cu,
                    now,
                    req.deadline,
                ),
            ).fetchone()
            for b, n in budgets:
                held = b["metric"] in ("cu", "concurrency")
                self._charge(
                    c, rid, 1, b, hold=n if held else 0, spend=0 if held else n
                )
                c.execute(
                    "INSERT INTO auth_reservation_allocations(reservation_id,budget_id,units,metric) VALUES (%s,%s,%s,%s)",
                    (rid, b["budget_id"], n, b["metric"]),
                )
            if amounts["analysis"]:
                c.execute(
                    "INSERT INTO auth_analysis_claims(account_id,run_id,reservation_id) VALUES (%s,%s,%s)",
                    (a.account_id, req.analysis_run_id, rid),
                )
            c.execute(
                "INSERT INTO auth_job_outbox(reservation_id,payload,created_at) VALUES (%s,%s::jsonb,%s)",
                (
                    rid,
                    json.dumps(
                        {
                            "reservation_id": str(rid),
                            "resource_kind": req.resource_kind,
                            "resource_id": req.resource_id,
                            "payload_digest": canonical["payload_digest"],
                        }
                    ),
                    now,
                ),
            )
            audit(
                c,
                "auth_reservation_changed",
                rid,
                actor=ctx.subject_id,
                tenant=a.tenant_id,
                details={"transition": "reserved", "quote_version": req.cost.version},
            )
            return Receipt.of(row)

    @staticmethod
    def _locked(c, rid):
        row = c.execute(
            "SELECT * FROM auth_reservations WHERE reservation_id=%s FOR UPDATE",
            (UUID(str(rid)),),
        ).fetchone()
        if not row:
            auth_error(404, "reservation_not_found")
        # AUTH-13 managed reservations require the execution generation/service gate.
        present=c.execute("SELECT to_regclass('auth_worker_jobs') AS present").fetchone()
        if present['present'] and c.execute("SELECT 1 FROM auth_worker_jobs WHERE reservation_id=%s",(row['reservation_id'],)).fetchone():
            from apps.api.workers.authority import MANAGED_WRITE
            if not MANAGED_WRITE.get():
                auth_error(409, "worker_managed_reservation")
        return row

    @staticmethod
    def _version(row, expected):
        if type(expected) is not int or expected < 1 or row["version"] != expected:
            auth_error(409, "reservation_conflict")

    @boundary
    def get(self, ctx, rid):
        with self.store.transaction() as tx:
            c = tx.connection
            check_schema(c)
            a, _, _ = self._authority(c, ctx)
            row = c.execute(
                "SELECT * FROM auth_reservations WHERE reservation_id=%s AND account_id=%s AND subject_id=%s",
                (UUID(str(rid)), a.account_id, a_subject(ctx)),
            ).fetchone()
            if not row:
                auth_error(404, "reservation_not_found")
            return Receipt.of(row)

    @boundary
    def start(self, ctx, rid, *, expected_version, lease_seconds=60):
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise ValueError("bounded lease required")
        with self.store.transaction() as tx:
            c = tx.connection
            check_schema(c)
            a, caps, now = self._authority(c, ctx)
            chain = self._chain(c, a.account_id)
            now = self._now(c)
            self._scope_lifetime(chain, now)
            row = self._locked(c, rid)
            if row["account_id"] != a.account_id or row["subject_id"] != a_subject(ctx):
                auth_error(404, "reservation_not_found")
            req = row["admission"]
            entry = req["entry_id"]
            # Recheck credential channel/scope as well as current capabilities before claim.
            self._authority(c, ctx, entry)
            from apps.api.access_registry import ModelWorkload

            dec = evaluate_entry(
                caps,
                entry,
                workload=ModelWorkload.model_validate(req["workload"])
                if req.get("workload")
                else None,
                stage=req.get("stage"),
            )
            if not dec.allowed:
                auth_error(403, dec.code)
            now = self._now(c)
            self._version(row, expected_version)
            if row["state"] != "pending":
                auth_error(409, "reservation_conflict")
            if now >= row["deadline"]:
                auth_error(403, "reservation_expired")
            row = c.execute(
                "UPDATE auth_reservations SET state='running',version=version+1,lease_until=%s WHERE reservation_id=%s RETURNING *",
                (
                    min(now + timedelta(seconds=lease_seconds), row["deadline"]),
                    row["reservation_id"],
                ),
            ).fetchone()
            audit(
                c,
                "auth_reservation_changed",
                rid,
                actor=ctx.subject_id,
                tenant=a.tenant_id,
                details={"transition": "running"},
            )
            return Receipt.of(row)

    @staticmethod
    def _allocations(c, row):
        # Account serializes reserve; terminal writers lock only persisted budget snapshot.
        return c.execute(
            """SELECT b.*,x.units,x.metric AS allocated_metric FROM auth_reservation_allocations x
            JOIN auth_resource_budgets b USING(budget_id) JOIN auth_budget_scopes s USING(scope_id)
            WHERE x.reservation_id=%s ORDER BY CASE s.kind WHEN 'sponsor' THEN 0 WHEN 'campaign' THEN 1 WHEN 'account' THEN 2 ELSE 3 END,s.scope_id,b.metric,b.budget_id FOR UPDATE OF b""",
            (row["reservation_id"],),
        ).fetchall()

    @boundary
    def extend(self, ctx, rid, *, expected_version, additional_cu):
        # Trusted execution adapter; reserve BEFORE work beyond the existing estimate.
        if type(additional_cu) is not int or not 1 <= additional_cu <= MAX_UNITS:
            raise ValueError("integer extension required")
        with self.store.transaction() as tx:
            c = tx.connection
            check_schema(c)
            account, caps, _ = self._authority(c, ctx)
            chain = self._chain(c, account.account_id)
            now = self._now(c)
            self._scope_lifetime(chain, now)
            row = self._locked(c, rid)
            if row["account_id"] != account.account_id or row[
                "subject_id"
            ] != a_subject(ctx):
                auth_error(404, "reservation_not_found")
            saved = row["admission"]
            self._authority(c, ctx, saved["entry_id"])
            from apps.api.access_registry import ModelWorkload

            decision = evaluate_entry(
                caps,
                saved["entry_id"],
                workload=ModelWorkload.model_validate(saved["workload"])
                if saved.get("workload")
                else None,
                stage=saved.get("stage"),
            )
            if not decision.allowed:
                auth_error(403, decision.code)
            self._version(row, expected_version)
            now = self._now(c)
            if (
                row["state"] != "running"
                or now >= row["deadline"]
                or now >= row["lease_until"]
            ):
                auth_error(409, "reservation_conflict")
            if row["held_cu"] > MAX_UNITS - additional_cu:
                auth_error(409, "budget_overflow")
            allocations = self._allocations(c, row)
            cu = [b for b in allocations if b["metric"] == "cu"]
            if not cu:
                auth_error(503, "budget_not_configured")
            for b in cu:
                self._charge(
                    c, row["reservation_id"], row["version"] + 1, b, hold=additional_cu
                )
                c.execute(
                    "UPDATE auth_reservation_allocations SET units=units+%s WHERE reservation_id=%s AND budget_id=%s",
                    (additional_cu, row["reservation_id"], b["budget_id"]),
                )
            row = c.execute(
                "UPDATE auth_reservations SET held_cu=held_cu+%s,version=version+1 WHERE reservation_id=%s RETURNING *",
                (additional_cu, row["reservation_id"]),
            ).fetchone()
            audit(
                c,
                "auth_reservation_changed",
                rid,
                tenant=row["tenant_id"],
                details={"transition": "extended"},
            )
            return Receipt.of(row)

    @boundary
    def settle(self, rid, *, expected_version, actual_cu, result_ref=None):
        if type(actual_cu) is not int or not 0 <= actual_cu <= MAX_UNITS:
            raise ValueError("integer actual required")
        if result_ref is not None:
            import re

            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", result_ref):
                raise ValueError("safe result reference required")
        return self._finish(rid, expected_version, actual_cu, result_ref)

    @boundary
    def release(self, rid, *, expected_version):
        return self._finish(rid, expected_version, None, None)

    def _finish(self, rid, expected, actual, result):
        with self.store.transaction() as tx:
            c = tx.connection
            check_schema(c)
            row = self._locked(c, rid)
            target = "released" if actual is None else "settled"
            if (
                row["state"] == target
                and row["actual_cu"] == actual
                and row["result_ref"] == result
            ):
                if type(expected) is not int or expected != row["version"] - 1:
                    auth_error(409, "reservation_conflict")
                return Receipt.of(row)
            self._version(row, expected)
            if row["state"] != ("pending" if actual is None else "running"):
                auth_error(409, "reservation_conflict")
            # Lease/deadline timeout NEVER refunds. Reconciliation after expiry is AUTH-13.
            now = self._now(c)
            if actual is not None and (
                now >= row["deadline"] or now >= row["lease_until"]
            ):
                auth_error(409, "reservation_conflict")
            if actual is not None and actual > row["held_cu"]:
                auth_error(402, "cu_reserve_exceeded")
            for b in self._allocations(c, row):
                if b["metric"] in ("cu", "concurrency"):
                    self._charge(
                        c,
                        row["reservation_id"],
                        row["version"] + 1,
                        b,
                        hold=-b["units"],
                        spend=actual
                        if b["metric"] == "cu" and actual is not None
                        else 0,
                    )
            row = c.execute(
                "UPDATE auth_reservations SET state=%s,actual_cu=%s,result_ref=%s,version=version+1 WHERE reservation_id=%s RETURNING *",
                (target, actual, result, row["reservation_id"]),
            ).fetchone()
            audit(
                c,
                "auth_reservation_changed",
                rid,
                tenant=row["tenant_id"],
                details={"transition": target},
            )
            return Receipt.of(row)

    @boundary
    def readiness(self):
        with self.store.transaction(readonly=True) as tx:
            check_schema(tx.connection)
        return {
            "ok": True,
            "backend": "postgres",
            "schema_version": VERSION,
            "worker_adapters": "AUTH-13",
            "commercial_cu": "AUTH-14",
        }


def a_subject(ctx):
    return UUID(ctx.subject_id)
