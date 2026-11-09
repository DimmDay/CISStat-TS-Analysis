"""AUTH-16 durable admission, request quotas and atomic first-run claims."""

import base64
import hashlib
import json
import re
import secrets
from contextvars import ContextVar
from datetime import UTC, timedelta
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from apps.api.billing.coordinator import ReservationCoordinator, audit
from apps.api.workers.connection import bind_connection

from .context import auth_error, resolve_request_context
from .demo_lifecycle_migrations import check_schema
from .sessions import SessionService, boundary

REQUEST = ContextVar("auth16_request", default=None)


class LifecyclePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    require_admission: bool = Field(default=False, strict=True)
    participant_requests: int = Field(default=600, ge=1, le=100000, strict=True)
    campaign_requests: int = Field(default=60000, ge=1, le=10000000, strict=True)
    max_upload_bytes: int = Field(default=4194304, ge=1024, le=4194304, strict=True)
    retention_hours: int = Field(default=24, ge=1, le=720, strict=True)


def admission_digest(code):
    if not isinstance(code, str) or not re.fullmatch(r"a16_[A-Za-z0-9_-]{43}", code):
        auth_error(401, "invalid_credential")
    return hashlib.sha256(("cisstat.admission/16\0" + code).encode()).hexdigest()


def claim_admission(c, campaign, grant, code, now, *, consume=False):
    """Called under the campaign lock, inside the enter commit."""
    if grant is not None and not code:
        return
    if not campaign["policy"].get("require_admission", False) and not code:
        return
    check_schema(c)
    row = c.execute(
        "SELECT * FROM auth_demo_admissions WHERE code_hash=%s AND campaign_id=%s FOR UPDATE",
        (admission_digest(code), campaign["campaign_id"]),
    ).fetchone()
    if not row or now >= row["expires_at"]:
        auth_error(401, "invalid_credential")
    if row["redeemed_grant_id"] is not None:
        if grant is None or row["redeemed_grant_id"] != grant["grant_id"]:
            auth_error(409, "admission_consumed")
        return
    if grant is None:
        return row["admission_id"]
    if not consume:
        auth_error(409, "admission_consumed")
    c.execute(
        "UPDATE auth_demo_admissions SET redeemed_at=%s,redeemed_grant_id=%s WHERE admission_id=%s",
        (now, grant["grant_id"], row["admission_id"]),
    )


class LifecycleService(SessionService):
    @boundary
    def issue_codes(self, token, origin, cid, version, count, expires_at, reason):
        from .demo import CampaignPolicy, DemoService, effective_status

        if type(count) is not int or not 1 <= count <= 200:
            auth_error(422, "invalid_campaign_policy")
        service = DemoService(self.store, clock=self.clock)
        service._admin_preflight(token, origin)
        codes = ["a16_" + secrets.token_urlsafe(32) for _ in range(count)]
        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            admin = service._admin(c, token, origin, mutation=True)
            row = service._campaign(c, cid, lock=True)
            now = self._now(c)
            p = CampaignPolicy.model_validate(row["policy"])
            if row["policy_version"] != version:
                auth_error(409, "campaign_policy_conflict")
            if (
                effective_status(row["status"], p, now) in ("expired", "revoked")
                or not now < expires_at <= p.ends_at
            ):
                auth_error(422, "invalid_campaign_policy")
            available = c.execute(
                "SELECT count(*) AS n FROM auth_demo_admissions WHERE campaign_id=%s AND redeemed_at IS NULL AND expires_at>%s",
                (cid, now),
            ).fetchone()["n"]
            if available + row["issued_grants"] + count > p.max_grants:
                auth_error(429, "campaign_capacity_exhausted")
            for code in codes:
                c.execute(
                    "INSERT INTO auth_demo_admissions(admission_id,campaign_id,code_hash,expires_at,created_at) VALUES (%s,%s,%s,%s,%s)",
                    (uuid4(), cid, admission_digest(code), expires_at, now),
                )
            service._audit_demo(
                c, admin["subject_id"], cid, "admissions_issued", reason, version
            )
        return {"codes": codes, "expires_at": expires_at.isoformat()}

    @boundary
    def claim_request(self, ctx, entry, key, digest):
        from .demo import CampaignPolicy, grant_for_account

        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            now = self._now(c)
            grant = grant_for_account(c, ctx.account_id, now)
            if not grant or str(grant["grant_id"]) != ctx.demo_grant_id:
                auth_error(401, "invalid_credential")
            c.execute(
                "SELECT campaign_id FROM auth_demo_campaigns WHERE campaign_id=%s FOR UPDATE",
                (grant["campaign_id"],),
            )
            # Recheck after waiting on quota/administrative edits.
            ReservationCoordinator(self.store)._authority(c, ctx)
            grant = grant_for_account(c, ctx.account_id, self._now(c))
            p = CampaignPolicy.model_validate(grant["policy"])
            kh = hashlib.sha256(key.encode()).hexdigest()
            old = c.execute(
                "SELECT * FROM auth_demo_calls WHERE grant_id=%s AND entry_id=%s AND key_hash=%s",
                (grant["grant_id"], entry, kh),
            ).fetchone()
            if old:
                if old["body_hash"] != digest:
                    auth_error(409, "idempotency_conflict")
                if old["state"] != "done":
                    auth_error(409, "demo_request_incomplete")
                if old["response"] is None:
                    auth_error(503, "compute_result_unavailable")
                return old
            for sid, limit in (
                (grant["campaign_id"], p.campaign_requests),
                (grant["grant_id"], p.participant_requests),
            ):
                c.execute(
                    "INSERT INTO auth_demo_http_usage(scope_id) VALUES (%s) ON CONFLICT DO NOTHING",
                    (sid,),
                )
                used = c.execute(
                    "UPDATE auth_demo_http_usage SET requests=requests+1 WHERE scope_id=%s AND requests<%s RETURNING requests",
                    (sid, limit),
                ).fetchone()
                if not used:
                    auth_error(429, "demo_request_limit")
            row = c.execute(
                "INSERT INTO auth_demo_calls(call_id,grant_id,entry_id,key_hash,body_hash,state,created_at) VALUES (%s,%s,%s,%s,%s,'running',%s) RETURNING *",
                (uuid4(), grant["grant_id"], entry, kh, digest, now),
            ).fetchone()
            audit(
                c,
                "auth_demo_changed",
                grant["grant_id"],
                actor=ctx.subject_id,
                details={"command": "request_admitted", "entry": entry},
            )
            return row

    @boundary
    def finish(self, cid, response, state="done"):
        with self._tx() as tx:
            tx.connection.execute(
                "UPDATE auth_demo_calls SET state=%s,response=%s::jsonb WHERE call_id=%s AND state='running'",
                (state, json.dumps(response) if response is not None else None, cid),
            )

    @boundary
    def remaining(self, ctx):
        from .demo import CampaignPolicy, grant_for_account

        with self._tx() as tx:
            c = tx.connection
            check_schema(c)
            g = grant_for_account(c, ctx.account_id, self._now(c))
            p = CampaignPolicy.model_validate(g["policy"])
            counts = {
                str(row["scope_id"]): row["requests"]
                for row in c.execute(
                    "SELECT scope_id,requests FROM auth_demo_http_usage WHERE scope_id IN (%s,%s)",
                    (g["grant_id"], g["campaign_id"]),
                ).fetchall()
            }
            budgets = c.execute(
                "SELECT limit_units-spent-reserved AS remaining FROM auth_resource_budgets WHERE scope_id IN (%s,%s,%s) AND metric='analysis' AND period='lifetime'",
                (g["grant_id"], g["campaign_id"], g["account_id"]),
            ).fetchall()
            return {
                "expires_at": g["expires_at"],
                "requests_remaining": max(
                    0,
                    min(
                        p.participant_requests - counts.get(str(g["grant_id"]), 0),
                        p.campaign_requests - counts.get(str(g["campaign_id"]), 0),
                    ),
                ),
                "analyses_remaining": max(
                    0,
                    min(
                        [p.participant_analyses, p.campaign_analyses]
                        + [b["remaining"] for b in budgets]
                    ),
                ),
                "retention_hours": p.retention_hours,
            }


def prepare_analysis():
    request = REQUEST.get()
    if request is None:
        return None
    admission = request.state._auth11_admission
    if admission is None or not admission.context.demo_grant_id:
        return None
    if getattr(request.state, "_auth16_run_id", None):
        return request.state._auth16_run_id
    from apps.api.billing.contract import Admission, Cost
    from apps.api.workers.connection import access_connection

    from .storage import PostgresAccessStore

    store = (
        getattr(request.app.state, "auth_access_store", None)
        or PostgresAccessStore.from_env()
    )
    if access_connection(store) is None:
        auth_error(503, "auth_authority_unavailable")
    ctx = admission.context
    now = SessionService(store)._now(access_connection(store))
    run = "RUN-" + uuid4().hex.upper()
    ledger = ReservationCoordinator(store)
    try:
        receipt = ledger.reserve(
            ctx,
            Admission(
                entry_id=admission.entry_id,
                resource_kind="run",
                resource_id=run,
                analysis_run_id=run,
                idempotency_key="demo:" + str(request.state._auth16_call),
                payload={"body_hash": request.state._auth16_digest},
                cost=Cost(micro_cu=0, version="auth16-analysis/1"),
                deadline=min(now + timedelta(seconds=60), ctx.plan_expires_at),
                slots=0,
            ),
        )
    except Exception as exc:
        from .context import AuthHTTPException

        if (
            isinstance(exc, AuthHTTPException)
            and exc.detail.get("code") == "quota_exceeded"
        ):
            auth_error(429, "quota_exceeded")
        raise
    ledger.release(receipt.reservation_id, expected_version=receipt.version)
    request.state._auth16_run_id = run
    return run


def stage_upload_cleanup(contents):
    """Durable GC intent survives a failed dataset transaction or process crash."""
    request = REQUEST.get()
    if request is None or not request.state._auth11_admission.context.demo_grant_id:
        return
    from .demo_cleanup import DemoCleanup
    from .storage import PostgresAccessStore

    store = (
        getattr(request.app.state, "auth_access_store", None)
        or PostgresAccessStore.from_env()
    )
    digest = hashlib.sha256(contents).hexdigest()
    # Deliberately independent of the bound dataset commit: only quiesced GC
    # may consume this obligation and must first check all surviving references.
    with store._connection() as c:
        check_schema(c)
        DemoCleanup._queue(c, "upload", digest)
        audit(
            c,
            "auth_demo_changed",
            request.state._auth11_admission.context.demo_grant_id,
            details={"command": "upload_gc_intent"},
        )


async def govern(request, admission, handler):
    """All scientific aliases share the same admission, including direct API."""
    if admission is None or not admission.context.demo_grant_id:
        return await handler(request)
    from starlette.responses import Response

    from .demo import CampaignPolicy
    from .storage import PostgresAccessStore

    ctx = admission.context
    store = (
        getattr(request.app.state, "auth_access_store", None)
        or PostgresAccessStore.from_env()
    )
    service = LifecycleService(store)
    with store.transaction(readonly=True) as tx:
        row = tx.connection.execute(
            "SELECT policy FROM auth_demo_campaigns WHERE campaign_id=(SELECT campaign_id FROM auth_demo_grants WHERE grant_id=%s)",
            (ctx.demo_grant_id,),
        ).fetchone()
        p = CampaignPolicy.model_validate(row["policy"])
    key = request.headers.get("idempotency-key") or str(uuid4())
    if not 1 <= len(key) <= 128:
        auth_error(422, "invalid_scientific_request")
    # Check before copying a chunk: no unbounded temporary bytearray allocation.
    # Oversized attempts consume admission too, never a free failed upload loop.
    body = bytearray()
    ceiling = p.max_upload_bytes + 65536
    async for chunk in request.stream():
        if len(body) + len(chunk) > ceiling:
            digest = hashlib.sha256(
                b"oversized:" + bytes(body) + chunk[: max(0, ceiling - len(body))]
            ).hexdigest()
            failed = service.claim_request(ctx, admission.entry_id, key, digest)
            service.finish(failed["call_id"], None, "failed")
            auth_error(413, "demo_upload_limit")
        body.extend(chunk)
    request._body = bytes(body)
    digest = hashlib.sha256(
        request.method.encode() + str(request.url).encode() + bytes(body)
    ).hexdigest()
    call = service.claim_request(ctx, admission.entry_id, key, digest)
    if call["state"] == "done":
        saved = call["response"]
        return Response(
            content=base64.b64decode(saved["body"]),
            status_code=saved["status"],
            headers=dict(saved["headers"]),
        )
    request.state._auth16_deadline = min(
        call["created_at"] + timedelta(seconds=60), ctx.plan_expires_at
    )
    request.state._auth16_call = call["call_id"]
    request.state._auth16_digest = digest
    token = REQUEST.set(request)

    def captured(response):
        raw = getattr(response, "body", None)
        if not isinstance(raw, bytes) or len(raw) > 1048576:
            return None
        headers = [
            (k.decode(), v.decode())
            for k, v in response.raw_headers
            if k.lower() in (b"content-type", b"content-disposition", b"set-cookie")
        ]
        return {
            "status": response.status_code,
            "body": base64.b64encode(raw).decode(),
            "headers": headers,
        }

    async def checked():
        response = await handler(request)
        from datetime import datetime

        if datetime.now(UTC) >= request.state._auth16_deadline:
            auth_error(408, "worker_stopped")
        # Bust the per-request cache: current authority must win at publication.
        try:
            delattr(request.state, "_auth03_context")
        except AttributeError:
            pass
        resolve_request_context(request)
        from .demo import grant_for_account

        with store.transaction(readonly=True) as tx:
            grant_for_account(
                tx.connection, ctx.account_id, service._now(tx.connection)
            )
        return response

    try:
        if admission.operation_id in {
            "upload.file.load",
            "upload.db.load",
            "upload.demo_dataset.load",
        }:
            with store.transaction() as tx, bind_connection(tx.connection, store):
                response = await checked()
                service.finish(call["call_id"], captured(response))
        else:
            response = await checked()
            service.finish(call["call_id"], captured(response))
        if hasattr(response, "body_iterator"):
            iterator = response.body_iterator

            async def current_chunks():
                from .demo import grant_for_account

                async for chunk in iterator:
                    from datetime import datetime

                    if datetime.now(UTC) >= request.state._auth16_deadline:
                        auth_error(408, "worker_stopped")
                    try:
                        delattr(request.state, "_auth03_context")
                    except AttributeError:
                        pass
                    resolve_request_context(request)
                    with store.transaction(readonly=True) as tx:
                        grant_for_account(
                            tx.connection, ctx.account_id, service._now(tx.connection)
                        )
                    yield chunk

            response.body_iterator = current_chunks()
        return response
    except BaseException:
        service.finish(call["call_id"], None, "failed")
        raise
    finally:
        REQUEST.reset(token)
