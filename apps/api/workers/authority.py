"""AUTH-13 durable worker delegation, generation fencing and atomic publication."""

import hashlib
import hmac
import json
import os
from datetime import timedelta
from uuid import UUID, uuid4
from dataclasses import dataclass
from apps.api.authentication.context import RequestContext, auth_error
from apps.api.authentication.sessions import boundary
from apps.api.authentication.storage import PostgresAccessStore
from apps.api.accounts.entitlements import account_is_active
from apps.api.accounts.models import Account
from apps.api.access_registry import ModelWorkload, evaluate_entry
from apps.api.billing.coordinator import ReservationCoordinator, audit
from apps.api.billing.contract import Admission, MAX_UNITS, digest_payload
from .connection import bind_connection
from .migrations import check_schema
from .services import verify
from contextvars import ContextVar

MANAGED_WRITE = ContextVar("cisstat_managed_reservation_write", default=False)


@dataclass(frozen=True)
class Claim:
    worker_id: UUID
    fence: int
    phase: int
    kind: str
    deadline: object
    lease_until: object
    service_id: UUID


class WorkerAuthority:
    def __init__(self, store=None, key=None):
        self.store = store if store is not None else PostgresAccessStore.from_env()
        self.key = key if key is not None else os.environ.get("CISSTAT_WORKER_KEY", "")
        self.billing = ReservationCoordinator(self.store)

    @staticmethod
    def now(c):
        return c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]

    def _service(self, c, kind, *, lock=True):
        check_schema(c)
        return verify(c, self.key, kind, lock=lock)

    def _reservation(self, c, rid):
        token = MANAGED_WRITE.set(True)
        try:
            return self.billing._locked(c, rid)
        finally:
            MANAGED_WRITE.reset(token)

    @staticmethod
    def _delegation(ctx):
        return {
            k: getattr(ctx, k)
            for k in (
                "subject_id",
                "tenant_id",
                "account_id",
                "auth_method",
                "credential_id",
                "auth_session_id",
                "subject_version",
                "entitlement_version",
            )
        }

    @staticmethod
    def _ctx(row):
        return RequestContext(**row["delegation"])

    @staticmethod
    def _id(value):
        return UUID(str(value))

    @staticmethod
    def _row(c, wid, *, lock=True):
        row = c.execute(
            "SELECT * FROM auth_worker_jobs WHERE worker_id=%s"
            + (" FOR UPDATE" if lock else ""),
            (WorkerAuthority._id(wid),),
        ).fetchone()
        if not row:
            auth_error(404, "worker_not_found")
        return row

    def _hint(self, c, wid):
        return self._row(c, wid, lock=False)

    def _access(self, c, row, *, work=True):
        if row["kind"] == "delivery":
            raw = c.execute(
                "SELECT * FROM auth_accounts WHERE account_id=%s FOR UPDATE",
                (row["account_id"],),
            ).fetchone()
            if not raw or not account_is_active(Account(**raw), now=self.now(c)):
                auth_error(403, "account_expired")
            account = Account(**raw)
            caps = None
        else:
            ctx = self._ctx(row)
            entry = row["descriptor"]["entry_id"]
            account, caps, _ = self.billing._authority(c, ctx, entry)
            workload = row["descriptor"].get("workload")
            if (
                workload
                and caps.max_dataset_rows is not None
                and workload["rows"] > caps.max_dataset_rows
            ):
                auth_error(402, "dataset_limit_exceeded")
            dec = evaluate_entry(
                caps,
                entry,
                workload=ModelWorkload.model_validate(row["descriptor"]["workload"])
                if row["descriptor"].get("workload")
                else None,
                stage=row["descriptor"].get("stage"),
            )
            if not dec.allowed:
                auth_error(403, dec.code)
        if str(account.tenant_id) != str(row["tenant_id"]):
            auth_error(404, "scientific_object_not_found")
        # Current persisted ownership, not the job ID/creator cookie. Lock the run
        # through publication so concurrent transfer/context mutation cannot win.
        run = c.execute(
            "SELECT * FROM research_runs WHERE run_id=%s FOR SHARE", (row["run_id"],)
        ).fetchone()
        if (
            not run
            or str(run.get("owner_account_id")) != str(row["account_id"])
            or str(run.get("tenant_id")) != str(row["tenant_id"])
        ):
            auth_error(404, "scientific_object_not_found")
        if row["context_id"] and run.get("context_id") != row["context_id"]:
            auth_error(409, "worker_fenced")
        if row["session_id"] and row["kind"] in ("modeling", "delivery"):
            session = c.execute(
                "SELECT jsonb_build_object('owner_account_id',payload->'owner_account_id','run_id',payload->'run_id','dataset',payload->'dataset','data_revision',payload->'data_revision','target_column',payload->'target_column','date_column',payload->'date_column','data_digest',payload->'data_digest') AS payload FROM analysis_sessions WHERE session_id=%s AND expires_at>clock_timestamp()",
                (row["session_id"],),
            ).fetchone()
            payload = session["payload"] if session else {}
            if not session and row["kind"] == "delivery":
                return caps
            if (
                str(payload.get("owner_account_id")) != str(row["account_id"])
                or payload.get("run_id") != row["run_id"]
            ):
                auth_error(404, "scientific_object_not_found")
            if row["context_id"]:
                from apps.api.data_context import compute_context_id, context_components

                components = context_components(
                    dataset_fingerprint=(payload.get("dataset") or {}).get(
                        "dataset_fingerprint", ""
                    ),
                    data_revision=payload.get("data_revision", 0),
                    target_column=payload.get("target_column"),
                    date_column=payload.get("date_column"),
                )
                if (
                    compute_context_id(run_id=row["run_id"], components=components)
                    != row["context_id"]
                ):
                    auth_error(409, "worker_fenced")
            if (
                row["descriptor"].get("data_digest")
                and payload.get("data_digest") != row["descriptor"]["data_digest"]
            ):
                auth_error(409, "worker_fenced")
        scopes = c.execute(
            "SELECT to_regclass('auth_budget_scopes') AS present"
        ).fetchone()
        if scopes["present"]:
            has = c.execute(
                "SELECT 1 FROM auth_budget_scopes WHERE scope_id=%s",
                (row["account_id"],),
            ).fetchone()
            if has:
                self.billing._scope_lifetime(
                    self.billing._chain(c, row["account_id"]), self.now(c)
                )
        return caps

    def _check(self, c, row, claim, *, allow_queued=False):
        if (
            row["fence"] != claim.fence
            or row["service_id"] != claim.service_id
            or row["phase"] != claim.phase
            or row["kind"] != claim.kind
        ):
            auth_error(409, "worker_fenced")
        if row["state"] != "running" and not (
            allow_queued and row["state"] == "queued"
        ):
            auth_error(409, "worker_fenced")
        now = self.now(c)
        if (
            now >= row["deadline"]
            or not row["lease_until"]
            or now >= row["lease_until"]
        ):
            auth_error(409, "worker_expired")

    @boundary
    def admit(
        self,
        ctx,
        request: Admission,
        *,
        kind,
        external_id,
        run_id,
        session_id=None,
        context_id=None,
        descriptor=None,
        publisher=None,
    ):
        if kind not in ("modeling", "render"):
            raise ValueError("computational kind required")
        descriptor = descriptor or {}
        fingerprint = digest_payload(
            {
                "kind": kind,
                "external_id": external_id,
                "run_id": run_id,
                "session_id": session_id,
                "context_id": context_id,
                "descriptor": descriptor,
                "payload": request.payload,
                "entry_id": request.entry_id,
            }
        )
        with self.store.transaction() as tx:
            c = tx.connection
            self._service(c, kind)
            account, caps, now = self.billing._authority(c, ctx, request.entry_id)
            existing = c.execute(
                "SELECT * FROM auth_worker_jobs WHERE kind=%s AND external_id=%s FOR UPDATE",
                (kind, external_id),
            ).fetchone()
            if existing:
                if (
                    str(existing["account_id"]) != ctx.account_id
                    or str(existing["subject_id"]) != ctx.subject_id
                ):
                    auth_error(404, "worker_not_found")
                if existing["input_digest"] != fingerprint:
                    auth_error(409, "idempotency_conflict")
                self._access(c, existing)
                return existing
            # Finite technical slot; existing operator policy is never overwritten.
            self.billing._root(c, account, now)
            if request.slots:
                raw = os.environ.get("CISSTAT_WORKER_ACCOUNT_SLOTS", "1")
                if not raw.isdigit() or not 1 <= int(raw) <= 32:
                    auth_error(503, "budget_not_configured")
                new = c.execute(
                    "INSERT INTO auth_resource_budgets(budget_id,scope_id,metric,period,limit_units) VALUES (%s,%s,'concurrency','lifetime',%s) ON CONFLICT(scope_id,metric,period) DO NOTHING RETURNING budget_id",
                    (uuid4(), account.account_id, int(raw)),
                ).fetchone()
                if new:
                    audit(
                        c,
                        "auth_budget_changed",
                        new["budget_id"],
                        actor=ctx.subject_id,
                        tenant=account.tenant_id,
                        details={
                            "transition": "worker_technical_ceiling",
                            "policy": "auth13/1",
                        },
                    )
            with bind_connection(c, self.store):
                receipt = self.billing.reserve(ctx, request)
            now = self.now(c)
            wid = uuid4()
            persisted = {
                **descriptor,
                "entry_id": request.entry_id,
                "workload": request.workload.model_dump(mode="json")
                if request.workload
                else None,
                "stage": request.stage,
            }
            row = c.execute(
                """INSERT INTO auth_worker_jobs(worker_id,reservation_id,kind,external_id,account_id,tenant_id,subject_id,delegation,descriptor,input_digest,run_id,session_id,context_id,state,deadline,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,'queued',%s,%s) RETURNING *""",
                (
                    wid,
                    receipt.reservation_id,
                    kind,
                    external_id,
                    account.account_id,
                    account.tenant_id,
                    UUID(ctx.subject_id),
                    json.dumps(self._delegation(ctx)),
                    json.dumps(persisted),
                    fingerprint,
                    run_id,
                    session_id,
                    context_id,
                    request.deadline,
                    now,
                ),
            ).fetchone()
            self._access(c, row)
            with bind_connection(c, self.store):
                if publisher:
                    publisher(row)
            audit(
                c,
                "auth_worker_changed",
                wid,
                actor=ctx.subject_id,
                tenant=account.tenant_id,
                details={"transition": "queued", "kind": kind},
            )
            return row

    @boundary
    def find(self, kind, external_id):
        with self.store.transaction(readonly=True) as tx:
            c = tx.connection
            self._service(c, kind, lock=False)
            return c.execute(
                "SELECT * FROM auth_worker_jobs WHERE kind=%s AND external_id=%s",
                (kind, external_id),
            ).fetchone()

    @boundary
    def claim(self, wid, *, phase=0, lease_seconds=120):
        if (
            type(phase) is not int
            or phase < 0
            or type(lease_seconds) is not int
            or not 1 <= lease_seconds <= 3600
        ):
            raise ValueError("bounded worker phase required")
        with self.store.transaction() as tx:
            c = tx.connection
            hint = self._hint(c, wid)
            service = self._service(c, hint["kind"])
            self._access(c, hint)
            row = self._row(c, wid)
            now = self.now(c)
            if row["state"] != "queued" or row["phase"] != phase:
                auth_error(409, "worker_fenced")
            if now >= row["deadline"]:
                auth_error(409, "worker_expired")
            lease = min(now + timedelta(seconds=lease_seconds), row["deadline"])
            if row["reservation_id"]:
                reservation = self._reservation(c, row["reservation_id"])
                if reservation["state"] not in ("pending", "running"):
                    auth_error(409, "worker_fenced")
                c.execute(
                    "UPDATE auth_reservations SET state='running',lease_until=%s,version=version+1 WHERE reservation_id=%s",
                    (lease, reservation["reservation_id"]),
                )
            row = c.execute(
                "UPDATE auth_worker_jobs SET state='running',fence=fence+1,attempt_fence=fence+1,service_id=%s,lease_until=%s,stop_proof=NULL WHERE worker_id=%s RETURNING *",
                (service["service_id"], lease, self._id(wid)),
            ).fetchone()
            audit(
                c,
                "auth_worker_changed",
                wid,
                actor=str(row["subject_id"] or "service:projection"),
                tenant=row["tenant_id"],
                details={
                    "transition": "claimed",
                    "fence": row["fence"],
                    "phase": phase,
                },
            )
            return Claim(
                row["worker_id"],
                row["fence"],
                row["phase"],
                row["kind"],
                row["deadline"],
                row["lease_until"],
                service["service_id"],
            )

    @boundary
    def pulse(self, claim):
        with self.store.transaction() as tx:
            c = tx.connection
            self._service(c, claim.kind)
            hint = self._hint(c, claim.worker_id)
            self._access(c, hint)
            row = self._row(c, claim.worker_id)
            self._check(c, row, claim)
            return True

    def seal_stop(self, claim, proof, *, remote_unknown=False):
        if not proof.stopped:
            auth_error(409, "worker_uncertain")
        body = {
            "worker_id": str(claim.worker_id),
            "fence": claim.fence,
            "service_id": str(claim.service_id),
            "pid": proof.pid,
            "exit_code": proof.exit_code,
            "outcome": proof.outcome,
            "stopped": True,
            "remote_unknown": bool(remote_unknown),
        }
        signature = hmac.new(
            self.key.encode(),
            ("cisstat.worker.stop/1\0" + digest_payload(body)).encode(),
            hashlib.sha256,
        ).hexdigest()
        return {**body, "signature": signature}

    def _proof(self, claim, proof):
        if (
            not isinstance(proof, dict)
            or not proof.get("stopped")
            or proof.get("worker_id") != str(claim.worker_id)
            or proof.get("fence") != claim.fence
            or proof.get("service_id") != str(claim.service_id)
        ):
            auth_error(409, "worker_uncertain")
        body = {k: v for k, v in proof.items() if k != "signature"}
        signature = hmac.new(
            self.key.encode(),
            ("cisstat.worker.stop/1\0" + digest_payload(body)).encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(
            signature, str(proof.get("signature", ""))
        ) or proof.get("remote_unknown"):
            auth_error(409, "worker_uncertain")

    def _settle(self, c, row, actual_cu, result_ref=None):
        if not row["reservation_id"]:
            return
        if type(actual_cu) is not int or not 0 <= actual_cu <= MAX_UNITS:
            raise ValueError("integer actual required")
        r = self._reservation(c, row["reservation_id"])
        if r["state"] in ("settled", "released"):
            auth_error(409, "worker_fenced")
        if actual_cu > r["held_cu"]:
            auth_error(402, "cu_reserve_exceeded")
        for budget in self.billing._allocations(c, r):
            if budget["metric"] in ("cu", "concurrency"):
                self.billing._charge(
                    c,
                    r["reservation_id"],
                    r["version"] + 1,
                    budget,
                    hold=-budget["units"],
                    spend=actual_cu if budget["metric"] == "cu" else 0,
                )
        # Pending has not started; release is legal only with a no-start proof.
        if r["state"] == "pending":
            if actual_cu:
                auth_error(409, "worker_uncertain")
            c.execute(
                "UPDATE auth_reservations SET state='released',version=version+1 WHERE reservation_id=%s",
                (r["reservation_id"],),
            )
        else:
            c.execute(
                "UPDATE auth_reservations SET state='settled',actual_cu=%s,result_ref=%s,version=version+1 WHERE reservation_id=%s",
                (actual_cu, result_ref, r["reservation_id"]),
            )
        audit(
            c,
            "auth_reservation_changed",
            r["reservation_id"],
            tenant=row["tenant_id"],
            details={"transition": "worker_settle", "actual_cu": actual_cu},
        )

    @boundary
    def project(self, claim, publisher):
        with self.store.transaction() as tx:
            c = tx.connection
            self._service(c, claim.kind)
            hint = self._hint(c, claim.worker_id)
            self._access(c, hint)
            row = self._row(c, claim.worker_id)
            self._check(c, row, claim)
            with bind_connection(c, self.store):
                publisher(c)
            audit(
                c,
                "auth_worker_changed",
                row["worker_id"],
                tenant=row["tenant_id"],
                details={"transition": "running_projection", "fence": row["fence"]},
            )

    @staticmethod
    def _terminal_projection(c, row, code):
        if row["kind"] == "render":
            c.execute(
                "UPDATE document_jobs SET state=CASE WHEN state='cancelled' THEN state ELSE 'failed' END,error_code=%s,updated_at=clock_timestamp() WHERE job_id=%s AND state IN ('queued','rendering')",
                (code, row["external_id"]),
            )
        elif row["kind"] == "modeling" and row["session_id"]:
            family = row["descriptor"].get("family")
            if family not in ("model_jobs", "tuning_jobs"):
                return
            prefix = ["modeling_artifacts", family, row["external_id"]]
            c.execute(
                """UPDATE analysis_sessions SET payload=jsonb_set(jsonb_set(jsonb_set(payload,%s,'"failed"'::jsonb),%s,to_jsonb(%s::text)),ARRAY['storage_revision'],to_jsonb(storage_revision+1)),storage_revision=storage_revision+1,updated_at=clock_timestamp()
                WHERE session_id=%s AND payload->>'owner_account_id'=%s AND payload->>'run_id'=%s AND payload#>%s IS NOT NULL AND payload#>>%s<>'completed'""",
                (
                    prefix + ["status"],
                    prefix + ["error"],
                    code,
                    row["session_id"],
                    str(row["account_id"]),
                    row["run_id"],
                    prefix,
                    prefix + ["status"],
                ),
            )

    @boundary
    def publish(
        self, claim, proof, *, publisher, result_digest, final=True, actual_cu=0
    ):
        self._proof(claim, proof)
        if not isinstance(result_digest, str) or len(result_digest) != 64:
            raise ValueError("result digest required")
        with self.store.transaction() as tx:
            c = tx.connection
            self._service(c, claim.kind)
            hint = self._hint(c, claim.worker_id)
            self._access(c, hint)
            row = self._row(c, claim.worker_id)
            if (
                row["state"] in ("completed", "queued")
                and row["fence"] == claim.fence + 1
                and row["phase"] == claim.phase + 1
                and row["result_digest"] == result_digest
            ):
                return row
            self._check(c, row, claim)
            with bind_connection(c, self.store):
                publisher(c)
            if (
                type(actual_cu) is not int
                or not 0 <= actual_cu <= MAX_UNITS - row["accrued_cu"]
            ):
                raise ValueError("integer work cost required")
            total = row["accrued_cu"] + actual_cu
            if row["reservation_id"]:
                reserved = self._reservation(c, row["reservation_id"])
                if total > reserved["held_cu"]:
                    auth_error(402, "cu_reserve_exceeded")
            if final:
                self._settle(c, row, total, "worker:" + str(row["worker_id"]))
            row = c.execute(
                "UPDATE auth_worker_jobs SET state=%s,fence=fence+1,phase=phase+1,stop_proof=%s::jsonb,result_digest=%s,accrued_cu=%s,lease_until=NULL WHERE worker_id=%s RETURNING *",
                (
                    "completed" if final else "queued",
                    json.dumps(proof),
                    result_digest,
                    total,
                    row["worker_id"],
                ),
            ).fetchone()
            audit(
                c,
                "auth_worker_changed",
                row["worker_id"],
                actor=str(row["subject_id"] or "service:projection"),
                tenant=row["tenant_id"],
                details={"transition": row["state"], "fence": row["fence"]},
            )
            return row

    @boundary
    def cancel(self, ctx, wid, *, publisher=None):
        with self.store.transaction() as tx:
            c = tx.connection
            hint = self._hint(c, wid)
            self._service(c, hint["kind"])
            # Current caller can cancel within its Account; original delegation may already be revoked.
            a, _, _ = self.billing._authority(c, ctx)
            if a.account_id != hint["account_id"]:
                auth_error(404, "worker_not_found")
            row = self._row(c, wid)
            if row["state"] in ("cancelled", "failed", "completed"):
                return row
            state = (
                "uncertain" if row["state"] in ("running", "uncertain") else "cancelled"
            )
            if state == "cancelled":
                self._settle(c, row, row["accrued_cu"])
            row = c.execute(
                "UPDATE auth_worker_jobs SET state=%s,fence=fence+1,error_code=%s WHERE worker_id=%s RETURNING *",
                (state, "worker_cancelled", row["worker_id"]),
            ).fetchone()
            with bind_connection(c, self.store):
                if publisher:
                    publisher(c)
            audit(
                c,
                "auth_worker_changed",
                wid,
                actor=ctx.subject_id,
                tenant=row["tenant_id"],
                details={"transition": state},
            )
            return row

    @boundary
    def uncertain(self, wid, *, expected_fence, code="worker_uncertain"):
        with self.store.transaction() as tx:
            c = tx.connection
            hint = self._hint(c, wid)
            self._service(c, hint["kind"])
            row = self._row(c, wid)
            if row["state"] in ("completed", "failed", "cancelled"):
                return row
            if row["fence"] != expected_fence:
                return row
            row = c.execute(
                "UPDATE auth_worker_jobs SET state='uncertain',fence=fence+1,error_code=%s WHERE worker_id=%s RETURNING *",
                (code, row["worker_id"]),
            ).fetchone()
            audit(
                c,
                "auth_worker_changed",
                wid,
                tenant=row["tenant_id"],
                details={"transition": "uncertain", "reason_code": code},
            )
            return row

    @boundary
    def stopped(self, claim, proof, *, actual_cu=0, code="worker_stopped"):
        # Positive supervisor evidence, not lease expiry. Can settle after revoke/expiry,
        # but never publishes a result. A cancel/reaper fence can supersede this claim.
        self._proof(claim, proof)
        with self.store.transaction() as tx:
            c = tx.connection
            self._service(c, claim.kind)
            hint = self._hint(c, claim.worker_id)
            c.execute(
                "SELECT account_id FROM auth_accounts WHERE account_id=%s FOR UPDATE",
                (hint["account_id"],),
            )
            row = self._row(c, claim.worker_id)
            if row["state"] in ("completed", "failed", "cancelled"):
                return row
            if (
                row["service_id"] != claim.service_id
                or row["phase"] != claim.phase
                or row["attempt_fence"] != claim.fence
            ):
                auth_error(409, "worker_fenced")
            self._settle(c, row, row["accrued_cu"] + actual_cu)
            self._terminal_projection(c, row, code)
            row = c.execute(
                "UPDATE auth_worker_jobs SET state='failed',fence=fence+1,stop_proof=%s::jsonb,error_code=%s,lease_until=NULL WHERE worker_id=%s RETURNING *",
                (json.dumps(proof), code, row["worker_id"]),
            ).fetchone()
            audit(
                c,
                "auth_worker_changed",
                row["worker_id"],
                tenant=row["tenant_id"],
                details={"transition": "stopped_reconciled", "reason_code": code},
            )
            return row

    @boundary
    def reconcile(self, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("bounded batch required")
        summary = {"pending_expired": 0, "uncertain": 0, "retained": 0, "revoked": 0}
        with self.store.transaction() as tx:
            c = tx.connection
            kinds = self._service(c, None)["kinds"]
            ids = c.execute(
                "SELECT worker_id FROM auth_worker_jobs WHERE kind=ANY(%s) AND state IN ('queued','running') ORDER BY deadline,worker_id LIMIT %s",
                (kinds, limit),
            ).fetchall()
            summary["retained"] = c.execute(
                "SELECT count(*) AS n FROM auth_worker_jobs WHERE kind=ANY(%s) AND state='uncertain'",
                (kinds,),
            ).fetchone()["n"]
        for item in ids:
            with self.store.transaction() as tx:
                c = tx.connection
                hint = self._hint(c, item["worker_id"])
                self._service(c, hint["kind"])
                invalid = False
                try:
                    self._access(c, hint)
                except Exception as exc:
                    from fastapi import HTTPException

                    if not isinstance(exc, HTTPException) or exc.status_code not in (
                        401,
                        402,
                        403,
                        404,
                        409,
                    ):
                        raise
                    invalid = True
                c.execute(
                    "SELECT account_id FROM auth_accounts WHERE account_id=%s FOR UPDATE",
                    (hint["account_id"],),
                )
                row = self._row(c, hint["worker_id"])
                now = self.now(c)
                if row["state"] == "queued" and (now >= row["deadline"] or invalid):
                    self._settle(c, row, row["accrued_cu"])
                    self._terminal_projection(
                        c, row, "worker_expired" if not invalid else "worker_stopped"
                    )
                    c.execute(
                        "UPDATE auth_worker_jobs SET state='failed',fence=fence+1,error_code='worker_expired' WHERE worker_id=%s",
                        (row["worker_id"],),
                    )
                    summary["pending_expired"] += 1
                    audit(
                        c,
                        "auth_worker_changed",
                        row["worker_id"],
                        tenant=row["tenant_id"],
                        details={"transition": "expired_or_revoked_before_start"},
                    )
                elif row["state"] == "running" and (
                    invalid or now >= row["deadline"] or now >= row["lease_until"]
                ):
                    c.execute(
                        "UPDATE auth_worker_jobs SET state='uncertain',fence=fence+1,error_code='worker_uncertain' WHERE worker_id=%s",
                        (row["worker_id"],),
                    )
                    summary["uncertain"] += 1
                    self._terminal_projection(c, row, "worker_uncertain")
                    audit(
                        c,
                        "auth_worker_changed",
                        row["worker_id"],
                        tenant=row["tenant_id"],
                        details={"transition": "lease_or_revoke_unknown_hold"},
                    )
                elif row["state"] == "uncertain":
                    summary["retained"] += 1
        from .spool import reconcile as reconcile_proofs

        summary["confirmed_stopped"] = reconcile_proofs(self, limit=limit, kinds=kinds)
        return summary
