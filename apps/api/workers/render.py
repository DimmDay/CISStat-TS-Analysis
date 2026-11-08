"""Protected render adapter: current delegation, isolated pure bytes, one publication."""

from dataclasses import replace
from datetime import UTC, datetime
from .bridge import render_attempt, authority
from .execution import ACTIVE
from apps.api.authentication.context import auth_error


def render_bytes(snapshot, fmt, profile):
    from apps.api.document_jobs import _render_snapshot_by_format

    return _render_snapshot_by_format(snapshot, fmt, profile)


def print_bytes(payload, url, timeout):
    from apps.api.png_renderer_client import PngRendererClient

    return PngRendererClient(base_url=url, timeout_s=timeout, enabled=True).render_page(
        payload
    )


def process(worker, job, snapshot=None):
    from apps.api.document_jobs import JOB_RENDERING, JOB_READY
    from apps.api.document_renditions import RENDITION_FORMATS

    auth = worker._worker_authority or authority()
    work = render_attempt(job, auth, timeout=worker._render_timeout, memory_mb=1024)
    token = ACTIVE.set(work)
    service = worker._delivery_service()
    try:
        claimed = replace(
            job,
            state=JOB_RENDERING,
            claimed_at=datetime.now(UTC).isoformat(),
            lease_expires_at=work.claim.lease_until.isoformat(),
        )
        auth.project(work.claim, lambda c: service.registry.update_job(claimed))
        source = None
        if job.print_revision_id:
            from apps.api.document_render_worker import (
                _load_print_render_input_default,
                _build_print_payload,
            )

            loader = worker._print_input_loader or _load_print_render_input_default
            basis = loader(job.basis_artifact_id)
            payload = _build_print_payload(basis, job)
            client = worker._png_renderer_client()
            # No session/service key is forwarded to the renderer container.
            content = work.run(
                print_bytes, payload, client.base_url, client.timeout_s, remote=True
            )
            from apps.api.png_renderer_client import PNG_SIGNATURE

            if not content.startswith(PNG_SIGNATURE):
                auth_error(409, "worker_stopped")
            source = str(basis.get("basis_sha256") or "")
        else:
            snapshot = (
                snapshot
                if snapshot is not None
                else worker._snapshot_loader(job.snapshot_id)
            )
            profile = None
            if claimed.org_profile_id:
                from apps.api import doc_profiles as dp

                profile = dp.org_profile_service().registry.get_profile(
                    claimed.org_profile_id
                )
                if (
                    not profile
                    or profile.status != dp.PROFILE_ACTIVE
                    or profile.format != claimed.format
                ):
                    auth_error(409, "worker_stopped")
            content = work.run(render_bytes, snapshot, claimed.format, profile)
        spec = RENDITION_FORMATS.get(claimed.format)
        if spec is None:
            auth_error(409, "worker_stopped")
        output = {}

        def publish(c):
            output["value"] = service.complete_render(
                claimed, spec, content, snapshot, source_sha256=source
            )
            if output["value"][0].state != JOB_READY:
                auth_error(409, "worker_stopped")

        import hashlib

        work.publish(
            publish,
            descriptor={
                "job_id": job.job_id,
                "sha256": hashlib.sha256(content).hexdigest(),
            },
            final=True,
        )
        return "ready"
    finally:
        ACTIVE.reset(token)
        work.abort()


def sync(service, job, snapshot):
    from apps.api.document_render_worker import DocumentRenderWorker

    worker = DocumentRenderWorker(service=service)
    try:
        process(worker, job, snapshot)
    except Exception as exc:
        import logging
        from apps.api.storage_diagnostics import safe_error

        logging.getLogger(__name__).warning(
            "Guarded render failed: %s", safe_error(exc)
        )
        raise
    current = service.registry.get_job(job.job_id)
    rendition = (
        service.registry.get_rendition(current.rendition_id)
        if current and current.rendition_id
        else None
    )
    return current, rendition


def reconcile(worker):
    auth = worker._worker_authority or authority()
    result = auth.reconcile()
    return result["pending_expired"] + result["uncertain"] + result["confirmed_stopped"]


def queued(worker, job):
    row = (worker._worker_authority or authority()).find("render", job.job_id)
    return bool(row and row["state"] == "queued")
