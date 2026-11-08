"""Adapters over existing model/document queues. No caller-supplied execution claims."""

import functools
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from uuid import uuid5, NAMESPACE_URL
from fastapi.routing import APIRoute
from apps.api.authentication.context import auth_error, resolve_request_context
from apps.api.billing.contract import Admission, Cost
from .authority import WorkerAuthority
from .execution import ACTIVE, Execution

REQUEST = ContextVar("cisstat_worker_request", default=None)


class WorkerRequestRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def wrapped(request):
            token = REQUEST.set(request)
            try:
                return await original(request)
            finally:
                REQUEST.reset(token)

        return wrapped


def enabled():
    from apps.api.storage_diagnostics import get_storage_mode
    from apps.api.identity import get_identity_mode, MODE_SCOPED

    return get_storage_mode() == "required" or get_identity_mode() == MODE_SCOPED


def authority(request=None):
    request = request if request is not None else REQUEST.get()
    store = (
        getattr(request.app.state, "auth_access_store", None)
        if request is not None
        else None
    )
    return WorkerAuthority(store=store)


def ctx(request=None):
    request = request if request is not None else REQUEST.get()
    if request is None:
        auth_error(401, "authentication_required")
    return resolve_request_context(request)


def model_job_id(request, session, signature, key=None):
    if not enabled():
        from uuid import uuid4

        return str(uuid4())
    return str(
        uuid5(
            NAMESPACE_URL,
            "cisstat.worker.model/1:"
            + str(session.owner_account_id)
            + ":"
            + session.run_id
            + ":"
            + (key or signature),
        )
    )


def persist_model_job(request, store, session, job, *, family):
    if not enabled():
        store.save(session)
        return job
    from apps.api.session_store import PostgresSessionStore

    if not isinstance(store, PostgresSessionStore):
        auth_error(503, "auth_authority_unavailable")
    auth = authority(request)
    context = ctx(request)
    policy = job.get("resource_policy") or {
        "step_timeout_seconds": 60,
        "total_timeout_seconds": 900,
        "memory_limit_mb": 1024,
    }
    deadline = datetime.fromisoformat(
        job.get("deadline_at")
        or (
            datetime.now(UTC) + timedelta(seconds=policy["total_timeout_seconds"])
        ).isoformat()
    )
    if context.plan_expires_at:
        deadline = min(deadline, context.plan_expires_at)
    entry = (
        "api:POST:/v1/session/modeling/jobs/start"
        if family == "model_jobs"
        else "api:POST:/v1/session/modeling/tuning/start"
    )
    description = {
        "family": family,
        "job_signature": job["job_signature"],
        "model_id": job["model_id"],
        "data_digest": session.data_digest,
    }
    from apps.api.scientific_workload import _work

    workload = _work([job["model_id"]], session, record=job, custom=True)
    req = Admission(
        entry_id=entry,
        resource_kind="run",
        resource_id=session.run_id,
        idempotency_key="model:" + job["job_id"],
        payload=description,
        cost=Cost(micro_cu=0, version="unpriced-auth13/1"),
        deadline=deadline,
        slots=1,
        workload=workload,
    )

    def publish(row):
        job["worker_id"] = str(row["worker_id"])
        store.save(session)

    row = auth.admit(
        context,
        req,
        kind="modeling",
        external_id=job["job_id"],
        run_id=session.run_id,
        session_id=session.session_id,
        context_id=session.current_context_id(),
        descriptor=description,
        publisher=publish,
    )
    if "worker_id" not in job:
        current = store.get(session.session_id)
        existing = (
            (current.modeling_artifacts.get(family) or {}).get(row["external_id"])
            if current
            else None
        )
        if not existing:
            auth_error(409, "worker_uncertain")
        return existing
    return job


def model_step(family):
    def decorate(fn):
        import inspect, typing

        signature = inspect.signature(fn)
        hints = typing.get_type_hints(fn)
        signature = signature.replace(
            parameters=[
                p.replace(annotation=hints.get(n, p.annotation))
                for n, p in signature.parameters.items()
            ],
            return_annotation=hints.get("return", signature.return_annotation),
        )

        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            if not enabled():
                return fn(*args, **kwargs)
            bound = signature.bind(*args, **kwargs).arguments
            request = bound.get("request")
            payload = bound.get("payload")
            job_id = bound.get("job_id") or getattr(payload, "job_id", None)
            from apps.api.session_store import get_session_store, SESSION_COOKIE_NAME

            store = get_session_store()
            session = store.get(request.cookies.get(SESSION_COOKIE_NAME))
            job = (
                (session.modeling_artifacts.get(family) or {}).get(job_id)
                if session
                else None
            )
            if not job:
                auth_error(404, "worker_not_found")
            expected = getattr(
                payload, "expected_step", getattr(payload, "expected_trial_index", None)
            )
            current = int(job.get("next_step", job.get("next_trial_index", 0)))
            if (
                job.get("status") in {"completed", "failed", "stale", "cancelled"}
                or expected is not None
                and expected != current
            ):
                return fn(*args, **kwargs)
            wid = job.get("worker_id")
            if not wid:
                auth_error(409, "worker_uncertain")
            policy = job.get("resource_policy") or {
                "step_timeout_seconds": 60,
                "memory_limit_mb": 1024,
            }
            timeout = float(policy["step_timeout_seconds"])
            auth = authority(request)
            claim = auth.claim(
                wid, phase=current, lease_seconds=min(3600, max(1, int(timeout) + 30))
            )
            work = Execution(
                auth, claim, timeout=timeout, memory_mb=float(policy["memory_limit_mb"])
            )
            work.model_job = (family, job_id)
            token = ACTIVE.set(work)
            try:
                return fn(*args, **kwargs)
            finally:
                ACTIVE.reset(token)
                work.abort()

        wrapped.__signature__ = signature
        return wrapped

    return decorate


def cancel_model(request, store, session, job):
    if not enabled():
        store.save(session)
        return
    if not job.get("worker_id"):
        auth_error(409, "worker_uncertain")
    authority(request).cancel(
        ctx(request), job["worker_id"], publisher=lambda c: store.save(session)
    )


def render_descriptor(job):
    return {
        key: getattr(job, key)
        for key in (
            "run_id",
            "snapshot_id",
            "format",
            "redaction_profile",
            "revision_id",
            "org_profile_id",
            "print_revision_id",
            "basis_artifact_id",
        )
    }


def register_render(registry, job, subject):
    if not enabled():
        return registry.register_job(job)
    from apps.api.document_jobs import PostgresDocumentRegistry

    if not isinstance(registry, PostgresDocumentRegistry):
        auth_error(503, "auth_authority_unavailable")
    request = REQUEST.get()
    context = ctx(request)
    if context.account_id != getattr(subject, "account_id", None):
        auth_error(404, "scientific_object_not_found")
    auth = authority(request)
    now = datetime.now(UTC)
    deadline = now + timedelta(minutes=15)
    if context.plan_expires_at:
        deadline = min(deadline, context.plan_expires_at)
    entry = (
        "api:POST:/v1/documentation/print-revisions/{print_revision_id}/renditions"
        if job.print_revision_id
        else "api:POST:/v1/documentation/revisions/{revision_id}/renditions"
    )
    # Entry names come from the existing reviewed registry, not raw browser paths.
    from apps.api.access_registry import REGISTRY

    op = (
        "documentation.request_print_rendition"
        if job.print_revision_id
        else "documentation.request_rendition"
    )
    entry = next(
        k
        for k, v in REGISTRY.bindings.items()
        if k.startswith("api:POST:") and v.operation_id == op
    )
    desc = render_descriptor(job)
    req = Admission(
        entry_id=entry,
        resource_kind="run",
        resource_id=job.run_id,
        idempotency_key="render:" + job.job_id,
        payload=desc,
        cost=Cost(micro_cu=0, version="unpriced-auth13/1"),
        deadline=deadline,
        slots=1,
    )
    auth.admit(
        context,
        req,
        kind="render",
        external_id=job.job_id,
        run_id=job.run_id,
        descriptor=desc,
        publisher=lambda row: registry.register_job(job),
    )
    return job


def render_attempt(job, auth=None, timeout=60, memory_mb=1024):
    auth = auth or authority()
    row = auth.find("render", job.job_id)
    if not row:
        auth_error(409, "worker_uncertain")
    for k, v in render_descriptor(job).items():
        if row["descriptor"].get(k) != v:
            auth_error(409, "worker_fenced")
    claim = auth.claim(
        row["worker_id"], phase=row["phase"], lease_seconds=min(3600, int(timeout) + 30)
    )
    return Execution(auth, claim, timeout=timeout, memory_mb=memory_mb)
