"""Service-only recovery of committed facts: no user impersonation or scientific replay."""

import json
from datetime import timedelta
from uuid import uuid4
from apps.api.authentication.context import auth_error
from apps.api.billing.contract import digest_payload
from apps.api.billing.coordinator import audit
from .authority import WorkerAuthority
from .process import StopProof


def deliver(task, run_store, session_store, *, at, worker=None):
    from apps.api.session_store import PostgresSessionStore
    from apps.api.delivery_outbox import PostgresDeliveryOutbox, deliver_layer1_mirror

    if not isinstance(session_store, PostgresSessionStore) or not isinstance(
        run_store.delivery_outbox, PostgresDeliveryOutbox
    ):
        auth_error(503, "auth_authority_unavailable")
    auth = worker or WorkerAuthority()
    immutable = {
        "operation_id": task.operation_id,
        "kind": task.kind,
        "run_id": task.run_id,
        "payload": task.payload,
        "commit_key_digest": digest_payload(task.idempotency_key),
    }
    fingerprint = digest_payload(immutable)
    if task.kind != "layer1_mirror":
        auth_error(403, "unknown_operation")
    if any(
        event.get("run_id") not in (None, "", task.run_id)
        for event in task.payload.get("events") or []
    ):
        auth_error(404, "scientific_object_not_found")
    with auth.store.transaction() as tx:
        c = tx.connection
        auth._service(c, "delivery")
        run = c.execute(
            "SELECT * FROM research_runs WHERE run_id=%s", (task.run_id,)
        ).fetchone()
        if not run or not run.get("owner_account_id"):
            auth_error(404, "scientific_object_not_found")
        account = c.execute(
            "SELECT account_id FROM auth_accounts WHERE account_id=%s FOR UPDATE",
            (run["owner_account_id"],),
        ).fetchone()
        if not account:
            auth_error(404, "scientific_object_not_found")
        previous = c.execute(
            "SELECT * FROM auth_worker_jobs WHERE kind='delivery' AND external_id=%s FOR UPDATE",
            (task.operation_id,),
        ).fetchone()
        if previous:
            if previous["input_digest"] != fingerprint:
                auth_error(409, "idempotency_conflict")
            row = previous
        else:
            now = auth.now(c)
            row = c.execute(
                """INSERT INTO auth_worker_jobs(worker_id,kind,external_id,account_id,tenant_id,delegation,descriptor,input_digest,run_id,session_id,state,deadline,created_at)
                VALUES (%s,'delivery',%s,%s,%s,'{}'::jsonb,%s::jsonb,%s,%s,%s,'queued',%s,%s) RETURNING *""",
                (
                    uuid4(),
                    task.operation_id,
                    run["owner_account_id"],
                    run["tenant_id"],
                    json.dumps({"policy": "committed_layer1_maintenance/1"}),
                    fingerprint,
                    task.run_id,
                    task.payload.get("session_id"),
                    now + timedelta(minutes=5),
                    now,
                ),
            ).fetchone()
            audit(
                c,
                "auth_worker_changed",
                row["worker_id"],
                tenant=row["tenant_id"],
                details={"transition": "projection_queued"},
            )
        auth._access(c, row)
    if row["state"] == "completed":
        return "delivered"
    claim = auth.claim(row["worker_id"], phase=row["phase"], lease_seconds=30)
    proof = auth.seal_stop(claim, StopProof(True, None, 0, "no_external_computation"))
    result = {}

    def project(c):
        persisted = run_store.delivery_outbox.get_task(task.operation_id)
        if persisted is None or digest_payload(persisted.payload) != digest_payload(
            task.payload
        ):
            auth_error(409, "worker_fenced")
        result["outcome"] = deliver_layer1_mirror(task, session_store)
        run_store.delivery_outbox.mark_delivered(task.operation_id, delivered_at=at)

    try:
        auth.publish(
            claim, proof, publisher=project, result_digest=fingerprint, final=True
        )
        return result["outcome"]
    except Exception:
        try:
            auth.stopped(claim, proof)
        except Exception:
            pass
        raise
