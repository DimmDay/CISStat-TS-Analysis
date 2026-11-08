"""Current attempt runtime: parent-only service capability, pure work, guarded write."""

from contextvars import ContextVar
import logging
from datetime import UTC, datetime
from apps.api.authentication.context import auth_error
from apps.api.billing.contract import digest_payload
from .process import run_bounded, StopProof, WorkStopped, WorkFailed

ACTIVE = ContextVar("cisstat_worker_execution", default=None)
PUBLISHING = ContextVar("cisstat_worker_publishing", default=False)


class Execution:
    def __init__(self, authority, claim, *, timeout=60, memory_mb=None):
        self.authority = authority
        self.claim = claim
        self.timeout = timeout
        self.memory_mb = memory_mb
        self.proof = authority.seal_stop(claim, StopProof(True, None, 0, "not_started"))
        self.published = False
        self.remote = False

    def run(self, target, *args, remote=False, **kwargs):
        from apps.api.scientific import ACTIVE_ADMISSION, ScientificAdmission

        admission = ACTIVE_ADMISSION.get()
        # Do not send request/session objects or service credentials into pure work.
        if admission is not None:
            admission = ScientificAdmission(
                admission.context,
                admission.caps,
                admission.operation_id,
                admission.entry_id,
                None,
            )
        remaining = min(
            self.timeout,
            (self.claim.deadline - datetime.now(UTC)).total_seconds(),
            (self.claim.lease_until - datetime.now(UTC)).total_seconds(),
        )
        self.remote = remote
        # From spawn onwards, absence of positive join evidence means hold.
        # Never fall back to the constructor's no-start proof after a launch.
        self.proof = None
        try:
            result, proof = run_bounded(
                target,
                args,
                kwargs,
                timeout=max(0.01, remaining),
                memory_mb=self.memory_mb,
                checkpoint=lambda: self.authority.pulse(self.claim),
                admission=admission,
            )
            self.proof = self.authority.seal_stop(self.claim, proof)
            from .spool import save

            save(self.claim, self.proof)
            return result
        except WorkFailed as exc:
            self.proof = self.authority.seal_stop(
                self.claim, exc.proof, remote_unknown=remote
            )
            from .spool import save

            save(self.claim, self.proof)
            raise exc.error
        except WorkStopped as exc:
            logging.getLogger(__name__).warning(
                "Worker execution stopped: %s", exc.code
            )
            self.proof = self.authority.seal_stop(
                self.claim, exc.proof, remote_unknown=remote
            )
            from .spool import save

            save(self.claim, self.proof)
            auth_error(408 if exc.code == "worker_timeout" else 409, "worker_stopped")

    def publish(self, publisher, *, descriptor, final=True):
        token = PUBLISHING.set(True)
        try:
            result = self.authority.publish(
                self.claim,
                self.proof,
                publisher=publisher,
                result_digest=digest_payload(descriptor),
                final=final,
                actual_cu=0,
            )
            self.published = True
            from .spool import remove

            remove(self.claim)
            return result
        finally:
            PUBLISHING.reset(token)

    def abort(self, code="worker_stopped"):
        if self.published:
            return
        try:
            if self.proof is None or self.proof.get("remote_unknown"):
                self.authority.uncertain(
                    self.claim.worker_id, expected_fence=self.claim.fence
                )
            else:
                self.authority.stopped(self.claim, self.proof, code=code)
        except Exception:
            pass


def execute_trial(**kwargs):
    from apps.api.modeling_tuning import execute_tuning_trial

    active = ACTIVE.get()
    return (
        active.run(execute_tuning_trial, **kwargs)
        if active
        else execute_tuning_trial(**kwargs)
    )


def publish_session(store, session):
    active = ACTIVE.get()
    if active is None or PUBLISHING.get() or active.claim.kind != "modeling":
        return False
    record = getattr(active, "model_job", None)
    if not record:
        auth_error(409, "worker_fenced")
    family, jid = record
    job = (session.modeling_artifacts.get(family) or {}).get(jid)
    if not job:
        auth_error(409, "worker_fenced")
    final = job.get("status") in {"completed", "failed", "cancelled", "stale"}
    active.publish(
        lambda c: store.save(session),
        descriptor={
            "job": job,
            "session": session.session_id,
            "revision": session.storage_revision,
        },
        final=final,
    )
    return True
