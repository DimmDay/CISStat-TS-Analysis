"""AUDIT-CERT: identical real-store contracts, independent event corpus.

Postgres is opt-in via the disposable local runner. No schema/table drop,
no production DSN probing: each test owns a uuid run and operation.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
import uuid

import pytest

from apps.api.delivery_outbox import layer1_mirror_task, run_delivery_recovery
from apps.api.research_runs import CommitEventBatch, MemoryResearchRunStore, PostgresResearchRunStore, ResearchRun, ResearchCheckpoint
from apps.api.session_store import AnalysisSession, MemorySessionStore
from apps.api.trace_events import make_trace_event


@pytest.fixture(params=["memory", "postgres"])
def store(request):
    if request.param == "memory":
        return MemoryResearchRunStore()
    dsn = os.environ.get("CISSTAT_CERT_LOCAL_PG_DSN")
    if not dsn:
        pytest.skip("Run scripts/prograuditcert_pg_runner.py for a disposable local Postgres")
    return PostgresResearchRunStore(dsn=dsn)


def batch_for(store):
    rid = "CERT-" + uuid.uuid4().hex
    run = ResearchRun(run_id=rid, session_id="cert-session", dataset_fingerprint="a" * 64,
                      dataset_name="cert-store.csv", target_column="flow", context_id="ctx-cert-store")
    store.upsert_run(run)
    event = make_trace_event("validation_check_status", stage="validation", node_id="missing", run_id=rid, status="done")
    task = layer1_mirror_task(session_id="cert-session", run_id=rid, events=[event], operation_id="cert-op-" + uuid.uuid4().hex)
    batch = CommitEventBatch(run=run, events=(event,), expected_context_id=run.context_id,
                             idempotency_key="cert-key-" + uuid.uuid4().hex, delivery_task=task)
    return batch


def test_concurrent_duplicate_lost_receipt_one_batch_effect(store):
    batch = batch_for(store)
    with ThreadPoolExecutor(max_workers=6) as pool:
        receipts = list(pool.map(lambda _: store.commit_event_batch(batch).to_dict(), range(12)))
    assert all(r == receipts[0] for r in receipts)
    assert len(store.list_events(batch.run.run_id)) == 1
    assert len(store.delivery_outbox.list_by_run(batch.run.run_id)) == 1
    assert receipts[0]["accepted_event_ids"] == [batch.events[0].event_id]
    assert receipts[0]["committed_watermark"] == 1
    assert store.commit_event_batch(batch).to_dict() == receipts[0]


@pytest.mark.parametrize("after_register", [False, True])
def test_outbox_failure_rolls_back_all_four_surfaces(store, monkeypatch, after_register):
    batch = batch_for(store)
    cp = ResearchCheckpoint(checkpoint_id="cert-cp-" + uuid.uuid4().hex, run_id=batch.run.run_id, event_id=batch.events[0].event_id)
    changed = replace(batch, run=replace(batch.run, target_column="stock"), checkpoints=(cp,))
    original = store.delivery_outbox.register
    constraint = "cert_refuse_" + uuid.uuid4().hex
    if isinstance(store, MemoryResearchRunStore):
        def refuse(*args, **kwargs):
            if after_register:
                original(*args, **kwargs)
            raise RuntimeError("CERT outbox refused")
        monkeypatch.setattr(store.delivery_outbox, "register", refuse)
        error = RuntimeError
    else:
        import psycopg
        from psycopg import sql
        # Physical PostgreSQL constraint failure, not a mocked SQL string.
        with psycopg.connect(os.environ["CISSTAT_CERT_LOCAL_PG_DSN"]) as conn:
            conn.execute(sql.SQL("ALTER TABLE progress_delivery_outbox ADD CONSTRAINT {} CHECK (operation_id <> {})").format(sql.Identifier(constraint), sql.Literal(batch.delivery_task.operation_id)))
        error = psycopg.errors.CheckViolation
    with pytest.raises(error):
        store.commit_event_batch(changed)
    assert store.get_run(batch.run.run_id).target_column == "flow"
    assert store.list_events(batch.run.run_id) == []
    assert store.list_checkpoints(batch.run.run_id) == []
    assert store.get_commit_receipt(batch.idempotency_key) is None
    assert store.delivery_outbox.get_task(batch.delivery_task.operation_id) is None
    if isinstance(store, MemoryResearchRunStore):
        monkeypatch.setattr(store.delivery_outbox, "register", original)
    else:
        with psycopg.connect(os.environ["CISSTAT_CERT_LOCAL_PG_DSN"]) as conn:
            conn.execute(sql.SQL("ALTER TABLE progress_delivery_outbox DROP CONSTRAINT {}").format(sql.Identifier(constraint)))
    assert store.commit_event_batch(changed).committed_watermark == 1


def test_committed_obligation_recovers_without_repeating_operation(store):
    batch = batch_for(store)
    receipt = store.commit_event_batch(batch)
    cache = MemorySessionStore()
    cache.save(AnalysisSession(session_id="cert-session"))
    # Another store instance proves actual persistence, not singleton cache.
    if isinstance(store, PostgresResearchRunStore):
        store = PostgresResearchRunStore(dsn=os.environ["CISSTAT_CERT_LOCAL_PG_DSN"])
    assert store.get_commit_receipt(batch.idempotency_key).to_dict() == receipt.to_dict()
    assert run_delivery_recovery(store, session_store=cache)["delivered"] == 1
    assert run_delivery_recovery(store, session_store=cache)["due"] == 0
    assert len(cache.get("cert-session").pipeline_trace) == 1
    assert len(store.list_events(batch.run.run_id)) == 1
    assert store.delivery_outbox.get_task(batch.delivery_task.operation_id).state == "delivered"

