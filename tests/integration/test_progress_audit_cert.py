"""AUDIT-CERT §19: independent HTTP observations on a full local API.

Own generated CSV, fixed expectations and persisted ids are the oracle;
the reducer is never copied. Faults affect only disposable test stores.
"""
from dataclasses import replace
import re

import pytest
from fastapi.testclient import TestClient

from app.core.pipeline_graph import STAGE_NODES
from apps.api import research_runs as rr
from apps.api.main import app
from apps.api.session_store import SESSION_COOKIE_NAME, get_session_store, reset_session_store_for_testing
from apps.api.trace_events import make_trace_event, stamp_envelope


@pytest.fixture
def http(tmp_path, monkeypatch):
    for key in ("DATABASE_URL", "REDIS_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_SESSION_BACKEND", "memory")
    monkeypatch.setenv("CISSTAT_STORAGE_MODE", "advisory")
    monkeypatch.setenv("CISSTAT_DELIVERY_WORKER_ENABLED", "0")
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path))
    reset_session_store_for_testing()
    rr.reset_research_run_store_for_testing()
    rr.reset_dataset_file_store_for_testing()
    with TestClient(app) as client:
        yield client
    reset_session_store_for_testing()
    rr.reset_research_run_store_for_testing()
    rr.reset_dataset_file_store_for_testing()


def upload(http, ambiguous=False):
    csv = "date,flow" + (",stock" if ambiguous else "") + "\n"
    for i in range(72):
        csv += f"{2020 + i // 12}-{1 + i % 12:02d}-01,{31 + i * .7 + i % 5}"
        csv += (f",{90 + i * 1.2}" if ambiguous else "") + "\n"
    response = http.post("/v1/internal/upload", files={"file": ("cert-monthly.csv", csv.encode(), "text/csv")})
    assert response.status_code == 200, response.text
    return trace(http)


def trace(http):
    response = http.get("/v1/progress/trace")
    assert response.status_code == 200, response.text
    return response.json()


def node(data, stage, name):
    return next(n for n in data["nodes"] if (n["stage"], n["node_id"]) == (stage, name))


def map_body(data, stage, report_id, fill="done"):
    key = "stops" if stage == "upload" else "checks"
    return {key: {n: fill for n in STAGE_NODES[stage]}, "schema_version": 2,
            "run_id": data["run_id"], "context_id": data["context_id"], "report_id": report_id}


def report(http, body, stage="validation"):
    path = "upload-stops" if stage == "upload" else f"{stage}-checks"
    return http.post(f"/v1/progress/{path}", json=body)


def events(run_id):
    return rr.get_research_run_store().list_events(run_id)


def seed(http, event_type, stage, name, payload=None, ts=None):
    data = trace(http)
    event = make_trace_event(event_type, stage=stage, node_id=name, run_id=data["run_id"], **(payload or {}))
    event = stamp_envelope(event, context_id=data["context_id"])
    if ts:
        event = replace(event, ts=ts)
    rr.get_research_run_store().append_event(data["run_id"], event)
    session = get_session_store().get(http.cookies.get(SESSION_COOKIE_NAME))
    session.append_trace_event(event)
    get_session_store().save(session)
    return event


def test_singleton_identity_ambiguity_manual(http):
    data = upload(http)
    choices = [e for e in data["events"] if e["event_type"] == "target_column_changed"]
    assert len(choices) == 1 and choices[0]["payload"]["source"] == "auto"
    assert choices[0]["actor"] == "system"
    ledger = {e.event_id: e for e in events(data["run_id"])}
    assert ledger[choices[0]["event_id"]].payload == choices[0]["payload"]
    assert data["target_column_source"] == "auto"
    ambiguous = upload(http, True)
    assert ambiguous["target_column"] is None
    assert not any(e["event_type"] == "target_column_changed" for e in ambiguous["events"])
    assert http.post("/v1/session/target-column", json={"column": "stock"}).status_code == 200
    manual = trace(http)
    assert manual["target_column"] == "stock" and manual["target_column_source"] == "user"


def test_demo_uses_same_singleton_rule(http, tmp_path, monkeypatch):
    from apps.api.routers import session
    demo = tmp_path / "owned-demo.csv"
    demo.write_text("date,flow\n2026-01-01,1.2\n2026-01-02,2.3\n2026-01-03,3.4\n")
    monkeypatch.setattr(session, "DEMO_DATASET_PATH", demo)
    response = http.post("/v1/session/demo")
    assert response.status_code == 200, response.text
    data = trace(http)
    assert data["target_column"] == "flow" and data["target_column_source"] == "auto"
    choice = [e for e in data["events"] if e["event_type"] == "target_column_changed"]
    assert len(choice) == 1
    assert sum(e.event_id == choice[0]["event_id"] for e in events(data["run_id"])) == 1


def test_unmodified_auto_restore_preserves_source_without_new_choice(http):
    data = upload(http)
    count = len(events(data["run_id"]))
    with TestClient(app) as restored:
        response = restored.get(f"/v1/progress/runs/{data['run_id']}/restore")
        assert response.status_code == 200, response.text
        result = trace(restored)
        assert result["target_column"] == "flow" and result["target_column_source"] == "auto"
        assert result["context_id"] == data["context_id"]
    assert len(events(data["run_id"])) == count + 1  # run_restored only
    assert sum(e.event_type == "target_column_changed" for e in events(data["run_id"])) == 1


def test_auto_convert_reset_restore_manual_consumers(http):
    data = upload(http)
    body = map_body(data, "validation", "cert-before-convert")
    assert report(http, body).status_code == 200
    converted = http.post("/v1/session/dataset/convert-types", json={"conversions": [{"column": "flow", "target_type": "string"}], "invalid_policy": "coerce", "apply": True})
    assert converted.status_code == 200, converted.text
    cleared = trace(http)
    run_id = data["run_id"]
    assert cleared["target_column"] is None and cleared["target_column_source"] is None
    assert rr.get_research_run_store().get_run(run_id).target_column is None
    assert any(e.event_type == "target_column_cleared" for e in events(run_id))
    mentor = http.get(f"/v1/progress/runs/{run_id}/mentor/next-step")
    assert mentor.status_code == 200
    assert "flow (авто)" not in mentor.json()["phase_text"]
    before = sum(e.event_type == "target_column_changed" for e in events(run_id))
    with TestClient(app) as restored:
        response = restored.get(f"/v1/progress/runs/{run_id}/restore")
        assert response.status_code == 200, response.text
        assert response.json()["mode"] == "raw" and response.json()["data_revision"] == 0
        recovered = trace(restored)
        assert recovered["target_column"] is None, "raw restore must not resurrect a cleared choice"
        assert node(recovered, "validation", "data_types")["validity"] == "stale"
        assert sum(e.event_type == "target_column_changed" for e in events(run_id)) == before
        assert restored.post("/v1/session/target-column", json={"column": "flow"}).status_code == 200
        assert trace(restored)["target_column_source"] == "user"
    assert sum(e.event_type == "target_column_changed" for e in events(run_id)) == before + 1


@pytest.mark.parametrize("stage", ["upload", "validation", "preprocessing", "eda"])
def test_four_maps_form_stale_run_context_duplicate_and_conflict(http, stage):
    a = upload(http, True)
    body = map_body(a, stage, f"cert-{stage}", "pending")
    bad = dict(body)
    key = "stops" if stage == "upload" else "checks"
    bad[key] = {next(iter(body[key])): "pending"}
    size = len(events(a["run_id"]))
    assert report(http, bad, stage).status_code == 422
    assert len(events(a["run_id"])) == size
    accepted = report(http, body, stage)
    assert accepted.status_code == 200, accepted.text
    receipt = accepted.json()["receipt"]
    size = len(events(a["run_id"]))
    again = report(http, body, stage)
    assert again.json()["receipt"] == receipt and again.json()["deduplicated"]
    assert len(events(a["run_id"])) == size
    conflict = dict(body, **{key: {n: "done" for n in body[key]}})
    assert report(http, conflict, stage).status_code == 409
    assert len(events(a["run_id"])) == size
    assert http.post("/v1/session/target-column", json={"column": "stock"}).status_code == 200
    shifted_size = len(events(a["run_id"]))
    assert report(http, dict(body, report_id="cert-old-context"), stage).status_code == 409
    assert len(events(a["run_id"])) == shifted_size
    b = upload(http, True)
    before_b = len(events(b["run_id"]))
    assert report(http, body, stage).status_code == 409
    assert len(events(b["run_id"])) == before_b


def test_cache_failure_lost_receipt_retry_recovery_one_effect(http, monkeypatch):
    from copy import deepcopy
    from apps.api.delivery_outbox import run_delivery_recovery
    data = upload(http)
    store = get_session_store()
    original_get = store.get
    original_create = store.get_or_create
    original_save = store.save
    monkeypatch.setattr(store, "get", lambda sid: deepcopy(original_get(sid)))
    monkeypatch.setattr(store, "get_or_create", lambda sid: deepcopy(original_create(sid)))
    def unavailable(_session):
        raise RuntimeError("cert-cache-unavailable")
    monkeypatch.setattr(store, "save", unavailable)
    body = map_body(data, "validation", "cert-lost-response")
    response = report(http, body)
    assert response.status_code == 500
    durable = rr.get_research_run_store()
    receipt = durable.get_commit_receipt(f"report:{data['run_id']}:cert-lost-response")
    assert receipt and len(receipt.accepted_event_ids) == len(STAGE_NODES["validation"])
    status = http.get(f"/v1/progress/runs/{data['run_id']}/delivery/cert-lost-response").json()
    assert status["state"] == "committed_projection_pending"
    monkeypatch.setattr(store, "save", original_save)
    retry = report(http, body)
    assert retry.status_code == 200 and retry.json()["receipt"] == receipt.to_dict()
    size = len(events(data["run_id"]))
    assert run_delivery_recovery(durable, session_store=store)["delivered"] == 1
    assert run_delivery_recovery(durable, session_store=store)["due"] == 0
    assert len(events(data["run_id"])) == size
    local = original_get(http.cookies.get(SESSION_COOKIE_NAME)).pipeline_trace
    for eid in receipt.accepted_event_ids:
        assert sum(e["event_id"] == eid for e in local) == 1
    response = http.get("/v1/progress/trace", params={"after_watermark": receipt.committed_watermark})
    assert response.status_code == 200 and response.json()["watermark"] >= receipt.committed_watermark


def test_eda_get_remount_pending_seed_failure_and_new_context(http):
    data = upload(http, True)
    assert http.post("/v1/session/target-column", json={"column": "flow"}).status_code == 200
    assert http.post("/v1/session/date-column", json={"column": "date"}).status_code == 200
    data = trace(http)
    assert report(http, map_body(data, "eda", "cert-eda-shown"), "eda").status_code == 200
    for _ in range(2):
        response = http.get("/v1/session/dataset/eda-correlation", params={"column": "flow"})
        assert response.status_code == 200, response.text
        assert node(trace(http), "eda", "correlation")["status"] == "done"
    assert report(http, map_body(data, "eda", "cert-eda-seed-failed", "pending"), "eda").status_code == 200
    assert node(trace(http), "eda", "correlation")["status"] == "done"
    assert http.post("/v1/session/target-column", json={"column": "stock"}).status_code == 200
    shifted = trace(http)
    assert node(shifted, "eda", "correlation")["validity"] == "stale"
    assert report(http, map_body(shifted, "eda", "cert-eda-new", "pending"), "eda").status_code == 200
    current = node(trace(http), "eda", "correlation")
    assert current["status"] == "pending" and current["validity"] == "current"


def test_full_projection_reverse_equal_clocks_forecast_identity(http):
    data = upload(http)
    seed(http, "validation_check_status", "validation", "data_types", {"status": "warning", "count": 6}, "2099-01-01T00:00:00Z")
    final = seed(http, "validation_check_status", "validation", "data_types", {"status": "done"}, "1999-01-01T00:00:00Z")
    forecast = seed(http, "forecast_generated", "forecasting", "forecast_generated", {"model_id": "naive"})
    session = get_session_store().get(http.cookies.get(SESSION_COOKIE_NAME))
    store = rr.get_research_run_store()
    for i in range(1007):
        event = make_trace_event("profile_requested", stage="eda", node_id="distribution", run_id=data["run_id"])
        event = replace(event, ts="2026-01-01T00:00:00Z")
        store.append_event(data["run_id"], event)
        session.append_trace_event(event)
    session.modeling_artifacts["forecasts"] = {"cert-forecast": {"trace_events": [forecast.to_dict()]}}
    get_session_store().save(session)
    size = len(events(data["run_id"]))
    result = trace(http)
    assert result["watermark"] == size and len(result["events"]) == 1000
    assert result["started_at"] == store.get_run(data["run_id"]).created_at
    state = node(result, "validation", "data_types")
    assert state["status"] == "done" and state["source_event_id"] == final.event_id
    assert state["summary_count"] is None
    assert node(result, "upload", "overview")["status"] == "done"
    mentor = http.get(f"/v1/progress/runs/{data['run_id']}/mentor/next-step").json()
    assert mentor["watermark"] == result["watermark"]
    assert http.get("/v1/progress/trace", params={"after_watermark": size + 1}).status_code == 409


def test_forecast_merge_preserves_id_actor_and_independent_equal_actions(http):
    data = upload(http)
    first = seed(http, "forecast_generated", "forecasting", "forecast_generated", {"model_id": "naive"}, "2026-01-01T00:00:00Z")
    second = seed(http, "forecast_generated", "forecasting", "forecast_generated", {"model_id": "naive"}, "2026-01-01T00:00:00Z")
    session = get_session_store().get(http.cookies.get(SESSION_COOKIE_NAME))
    session.modeling_artifacts["forecasts"] = {"cert": {"trace_events": [first.to_dict(), second.to_dict()]}}
    get_session_store().save(session)
    for _ in range(2):
        result = trace(http)
        actual = [e for e in result["events"] if e["event_type"] == "forecast_generated"]
        assert [e["event_id"] for e in actual] == [first.event_id, second.event_id]
        assert all(e["actor"] == first.actor and e["run_id"] == data["run_id"] for e in actual)
        assert result["watermark"] == len(events(data["run_id"]))


def test_db_failure_is_honest_incomplete_projection(http, monkeypatch):
    data = upload(http)
    store = rr.get_research_run_store()
    def refuse(_rid):
        raise RuntimeError("CERT unavailable ledger")
    monkeypatch.setattr(store, "list_events", refuse)
    partial = trace(http)
    assert partial["projection_complete"] is False
    assert partial["projection_source"] == "session_tail" and partial["started_at"] is None
    for endpoint in ("report", "mentor/next-step"):
        response = http.get(f"/v1/progress/runs/{data['run_id']}/{endpoint}")
        assert response.status_code == 503, response.text


def test_artifact_failure_and_staged_commit_cleanup(http, monkeypatch):
    from apps.api.delivery_outbox import sweep_orphaned_checkpoints
    data = upload(http)
    run_id = data["run_id"]
    anchor = events(run_id)[0].event_id
    store = rr.get_research_run_store()
    files = rr.get_dataset_file_store()
    save = files.save_checkpoint_snapshot
    def disk_failure(*args):
        raise OSError("CERT artifact failure")
    monkeypatch.setattr(files, "save_checkpoint_snapshot", disk_failure)
    response = http.post(f"/v1/progress/runs/{run_id}/checkpoints", json={"event_id": anchor, "label": "no snapshot"})
    assert response.status_code == 201, response.text
    assert response.json()["checkpoint"]["has_snapshot"] is False
    monkeypatch.setattr(files, "save_checkpoint_snapshot", save)
    count = len(events(run_id))
    cps = len(store.list_checkpoints(run_id))
    def commit_failure(_batch):
        raise RuntimeError("CERT commit refused")
    monkeypatch.setattr(store, "commit_event_batch", commit_failure)
    response = http.post(f"/v1/progress/runs/{run_id}/checkpoints", json={"event_id": anchor, "label": "orphan staged"})
    assert response.status_code == 503
    assert len(events(run_id)) == count and len(store.list_checkpoints(run_id)) == cps
    assert len(files.checkpoint_snapshot_files(run_id)) == 1
    assert len(sweep_orphaned_checkpoints(store, files, run_ids=[run_id])) == 1
    assert sweep_orphaned_checkpoints(store, files, run_ids=[run_id]) == []


@pytest.mark.parametrize("kind,payload,expected,count", [
    ("correction_previewed", {"total_missing": 0, "total_changed": 0, "total_still_missing": 0}, "pending", 0),
    ("correction_applied", {"total_missing": 5, "total_changed": 0, "total_still_missing": 5}, "warning", 5),
    ("correction_applied", {"total_missing": 5, "total_changed": 3, "total_still_missing": 2}, "warning", 2),
])
def test_outcome_and_invalid_event_details(http, kind, payload, expected, count):
    upload(http)
    good = seed(http, kind, "preprocessing", "missing", payload)
    before = node(trace(http), "preprocessing", "missing")
    assert before["status"] == expected and before["summary_count"] == count
    assert before["reason_source_event_id"] == good.event_id
    assert "Найдены нарушения" not in (before["status_reason"] or "") if count == 0 else True
    seed(http, "preprocessing_check_status", "preprocessing", "missing", {"status": "invalid-cert", "count": 999})
    after = node(trace(http), "preprocessing", "missing")
    for key in ("status", "status_reason", "summary_count", "reason_source_event_id"):
        assert after[key] == before[key]


def test_reports_mentor_panel_one_watermark_provenance_and_validity(http):
    initial = upload(http)
    assert report(http, map_body(initial, "validation", "cert-document")).status_code == 200
    assert http.post("/v1/session/date-column", json={"column": "date"}).status_code == 200
    data = trace(http)
    run_id = data["run_id"]
    mentor = http.get(f"/v1/progress/runs/{run_id}/mentor/next-step").json()
    assert mentor["watermark"] == data["watermark"] == len(events(run_id))
    assert node(data, "validation", "data_types")["validity"] == "stale"
    for fmt in ("md", "html"):
        response = http.get(f"/v1/progress/runs/{run_id}/report", params={"format": fmt})
        assert response.status_code == 200
        text = re.sub("<[^>]*>", "", response.text)
        assert f"Позиция истории (watermark): {data['watermark']}" in text
        assert "автоматически" in text.lower() and "исторический факт: другой контекст" in text.lower()
        source = node(data, "validation", "data_types")["source_event_id"]
        assert source in response.text


def test_model_job_cancel_context_late_result_and_phase(http):
    upload(http, True)
    for endpoint, body in (("target-column", {"column": "flow"}), ("date-column", {"column": "date"})):
        assert http.post(f"/v1/session/{endpoint}", json=body).status_code == 200
    for point in ("start", "modeling_entry"):
        assert http.post(f"/v1/session/dataset/passport/{point}").status_code == 200
    response = http.post("/v1/session/modeling/candidates", json={"strategy": "expanding", "horizon": 3, "n_splits": 2})
    assert response.status_code == 200, response.text
    response = http.post("/v1/session/modeling/jobs/start", json={"operation": "tuning", "model_id": "ets", "max_trials": 2, "metric": "rmse", "idempotency_key": "cert-model-job"})
    assert response.status_code == 200, response.text
    job = response.json()["job_id"]
    assert node(trace(http), "modeling", "tuning")["status"] == "in_progress"
    assert http.post(f"/v1/session/modeling/jobs/{job}/cancel", json={"reason": "cert: cancelled before completion"}).status_code == 200
    cancelled = trace(http)
    assert node(cancelled, "modeling", "tuning")["status"] == "pending"
    linked = [e for e in cancelled["events"] if e["event_type"] in ("tuning_job_started", "tuning_job_cancelled")]
    assert len(linked) == 2 and all(e["payload"]["job_id"] == job for e in linked)
    mentor = http.get(f"/v1/progress/runs/{cancelled['run_id']}/mentor/next-step").json()
    assert mentor["last_active_stage"] == "modeling" and mentor["watermark"] == cancelled["watermark"]
    assert http.post(f"/v1/session/modeling/jobs/{job}/step", json={"expected_step": 0}).status_code == 409
    assert http.post("/v1/session/target-column", json={"column": "stock"}).status_code == 200
    assert node(trace(http), "modeling", "tuning")["validity"] == "stale"
    size = len(events(cancelled["run_id"]))
    assert http.post(f"/v1/session/modeling/jobs/{job}/cancel", json={"reason": "late"}).status_code == 404
    assert http.post(f"/v1/session/modeling/jobs/{job}/step", json={"expected_step": 0}).status_code == 404
    assert len(events(cancelled["run_id"])) == size

