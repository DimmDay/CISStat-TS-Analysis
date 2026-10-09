"""Read-only audit of Progress at c8818de; no production connections or edits.

Run from repository root with its API dependencies installed:
  python scripts/progress_audit_readonly.py --output <results.json>

Uses actual session/progress routers and TraceHookMiddleware in a small local
FastAPI application. The upload adapter delegates to actual handle_upload.
main.py and unrelated Modeling dispatch are deliberately outside this fixture.
Fault injection is process-local; input/output files live in temporary storage.
Assertions pin observations of existing behavior, not acceptance of defects.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for key in ("DATABASE_URL", "REDIS_URL", "ALLOWED_ORIGINS"):
    os.environ.pop(key, None)
os.environ["CISSTAT_RUNS_BACKEND"] = "memory"

import pandas as pd
import fakeredis
from fastapi import FastAPI, File, Request, Response, UploadFile
from fastapi.testclient import TestClient
from app.core import mentor_rules, node_status
from app.core.pipeline_graph import STAGE_NODES
from app.core.run_report import fact_line, sort_events_chronologically
from apps.api import research_runs, session_store, trace_hook
from apps.api.research_runs import MemoryResearchRunStore, ResearchRun
from apps.api.routers import progress, session
from apps.api.schemas import UploadResponse
from apps.api.session_store import AnalysisSession, MemorySessionStore, RedisSessionStore
from apps.api.trace_events import TraceEvent, make_trace_event
from apps.api.upload_common import handle_upload

logging.basicConfig(level=logging.ERROR)
RESULTS = []


def source_hashes():
    names = subprocess.check_output(
        ["git", "ls-files", "apps", "app", "packages", "shared", "rules"],
        cwd=ROOT, text=True,
    ).splitlines()
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in names if (ROOT / name).is_file()}


def observe(code, title):
    def decorate(fn):
        try:
            evidence = fn()
            RESULTS.append({"id": code, "title": title, "result": "OBSERVED", "evidence": evidence})
            print(f"{code} OBSERVED: {title}", flush=True)
        except Exception as exc:
            RESULTS.append({"id": code, "title": title, "result": "PROBE_ERROR",
                            "error": f"{type(exc).__name__}: {exc}"})
            print(f"{code} PROBE_ERROR: {type(exc).__name__}: {exc}", flush=True)
        return fn
    return decorate


@contextmanager
def fixture(redis=False):
    with tempfile.TemporaryDirectory(prefix="progress-audit-", dir=ROOT.parent) as folder:
        ss = RedisSessionStore(fakeredis.FakeRedis(decode_responses=True)) if redis else MemorySessionStore()
        rs = MemoryResearchRunStore()
        with patch.dict(os.environ, {"CISSTAT_DATA_DIR": folder}), \
             patch.object(session_store, "_store", ss), \
             patch.object(research_runs, "_store", rs), \
             patch.object(research_runs, "_file_store", None):
            app = FastAPI()
            app.add_middleware(trace_hook.TraceHookMiddleware)

            @app.post("/v1/internal/upload", response_model=UploadResponse)
            async def upload(request: Request, response: Response, file: UploadFile = File(...)):
                return await handle_upload(file, request, response)

            app.include_router(session.router, prefix="/v1/session")
            app.include_router(progress.router, prefix="/v1/progress")
            with TestClient(app, raise_server_exceptions=False) as client:
                yield client, ss, rs, app


def upload(client, multi=False):
    lines = ["date,rain,snow" if multi else "date,rain"]
    lines += [f"2026-01-{i:02d},{i * 2.5}" + (f",{i * 0.7}" if multi else "") for i in range(1, 21)]
    response = client.post("/v1/internal/upload", files={"file": ("rain.csv", "\n".join(lines), "text/csv")})
    assert response.status_code == 200, response.text
    return client.get("/v1/progress/trace").json()["run_id"]


def states(client):
    current = client.get("/v1/session/current").json()
    trace = client.get("/v1/progress/trace").json()
    return current, trace


def active_session(client, ss):
    return ss.get(client.cookies[session_store.SESSION_COOKIE_NAME])


def event(kind, stage, node, ts="2026-10-09T10:00:00+00:00", **payload):
    return replace(make_trace_event(kind, stage=stage, node_id=node, run_id="RUN-AUDIT", **payload), ts=ts)


def main(output):
    before = source_hashes()

    @observe("P01", "Single numeric target: same auto fact in both layers")
    def _():
        with fixture() as (client, ss, rs, app):
            rid = upload(client)
            current, trace = states(client)
            durable = rs.list_events(rid)
            auto1 = [e for e in trace["events"] if e["event_type"] == "target_column_changed"]
            auto2 = [e.to_dict() for e in durable if e.event_type == "target_column_changed"]
            assert current["target_column"] == "rain" and current["target_column_source"] == "auto"
            assert len(auto1) == len(auto2) == 1 and auto1[0]["event_id"] == auto2[0]["event_id"]
            assert auto1[0]["actor"] == "system" and durable[0].event_type == "target_column_changed"
            client.post("/v1/session/date-column", json={"column": "date"})
            mentor = client.get(f"/v1/progress/runs/{rid}/mentor/next-step").json()
            assert "автоматически: rain" in mentor["phase_text"]
            return {"target": "rain", "source": "auto", "layers_same_event_id": True,
                    "order": [e.event_type for e in durable], "mentor": mentor["phase_text"]}

    @observe("P02", "Ambiguity: recommendation is not selection")
    def _():
        with fixture() as (client, ss, rs, app):
            rid = upload(client, multi=True)
            data = client.get("/v1/session/target-column").json()
            assert data["target_column"] is None and data["suggested_column"] == "rain"
            assert not any(e.event_type == "target_column_changed" for e in rs.list_events(rid))
            response = client.post("/v1/session/target-column", json={"column": "snow"})
            assert response.status_code == 200, response.text
            e = rs.list_events(rid)[-1]
            assert e.payload == {"target_column": "snow"}
            return {"before": data, "manual_event_payload": e.payload}

    @observe("P03", "Type conversion resets session target but not durable target or mentor fact")
    def _():
        with fixture() as (client, ss, rs, app):
            rid = upload(client)
            client.post("/v1/session/date-column", json={"column": "date"})
            response = client.post("/v1/session/dataset/convert-types", json={
                "conversions": [{"column": "rain", "target_type": "string"}], "apply": True})
            assert response.status_code == 200, response.text
            current, trace = states(client)
            events = rs.list_events(rid)
            assert response.json()["target_column_reset"] and current["target_column"] is None
            assert rs.get_run(rid).target_column == "rain" and mentor_rules._target_confirmed(events)
            text = mentor_rules.phase_text("upload", statuses=node_status.derive_node_statuses(events), events=events)
            assert "автоматически: rain" in text
            reason = next(n["status_reason"] for n in trace["nodes"]
                          if n["stage"] == "validation" and n["node_id"] == "sufficiency")
            return {"session_target": current["target_column"], "run_target": rs.get_run(rid).target_column,
                    "historical_mentor_upload_text": text, "sufficiency_reason": reason,
                    "reset_event": events[-1].to_dict()}

    @observe("P04", "Restore preserves auto event but drops target_column_source")
    def _():
        with fixture() as (client, ss, rs, app):
            rid = upload(client)
            response = client.get(f"/v1/progress/runs/{rid}/restore")
            assert response.status_code == 200, response.text
            current, trace = states(client)
            assert current["target_column"] == "rain" and current["target_column_source"] is None
            assert any(e["payload"].get("source") == "auto" for e in trace["events"])
            return {"session_target": current["target_column"], "session_source": current["target_column_source"],
                    "auto_fact_in_trace": True}

    @observe("P05", "Restore reloads raw values while old correction remains done")
    def _():
        with fixture() as (client, ss, rs, app):
            rid = upload(client)
            response = client.post("/v1/session/dataset/convert-types", json={
                "conversions": [{"column": "rain", "target_type": "string"}], "apply": True})
            assert response.status_code == 200
            before_type = str(active_session(client, ss).dataframe["rain"].dtype)
            response = client.get(f"/v1/progress/runs/{rid}/restore")
            assert response.status_code == 200, response.text
            current, trace = states(client)
            after_type = str(active_session(client, ss).dataframe["rain"].dtype)
            assert current["target_column"] == "rain" and pd.api.types.is_numeric_dtype(active_session(client, ss).dataframe["rain"])
            assert trace["node_statuses"]["validation/data_types"] == "done"
            return {"dtype_before_restore": before_type, "dtype_after_restore": after_type,
                    "resurrected_target": current["target_column"], "historical_data_types_status": "done"}

    @observe("P06", "Full status maps validate form but accept uncomputed client claims")
    def _():
        with fixture() as (client, ss, rs, app):
            rid = upload(client)
            before_count = len(rs.list_events(rid))
            incomplete = client.post("/v1/progress/validation-checks", json={"checks": {"data_types": "done"}})
            assert incomplete.status_code == 422 and len(rs.list_events(rid)) == before_count
            body = {"checks": dict.fromkeys(STAGE_NODES["validation"], "done")}
            response = client.post("/v1/progress/validation-checks", json=body)
            assert response.status_code == 200
            current, trace = states(client)
            assert all(trace["node_statuses"][f"validation/{n}"] == "done" for n in STAGE_NODES["validation"])
            return {"invalid_report": 422, "all_done_without_validate": 200,
                    "actor": rs.list_events(rid)[-1].actor, "payload": rs.list_events(rid)[-1].payload}

    @observe("P07", "Identical status report creates new facts on every POST")
    def _():
        with fixture() as (client, ss, rs, app):
            rid = upload(client)
            body = {"checks": dict.fromkeys(STAGE_NODES["validation"], "done")}
            initial = len(rs.list_events(rid))
            for _ in range(2):
                assert client.post("/v1/progress/validation-checks", json=body).status_code == 200
            assert len(rs.list_events(rid)) - initial == 20
            return {"identical_posts": 2, "new_events": 20, "dedupe": "client component lifetime only"}

    @observe("P08", "Report mirrors all ten facts before failed Redis save")
    def _():
        with fixture(redis=True) as (client, ss, rs, app):
            rid = upload(client)
            count = len(rs.list_events(rid))
            body = {"checks": dict.fromkeys(STAGE_NODES["validation"], "done")}
            with patch.object(ss, "save", side_effect=RuntimeError("audit injected save failure")):
                response = client.post("/v1/progress/validation-checks", json=body)
            current, trace = states(client)
            assert response.status_code == 500 and len(rs.list_events(rid)) == count + 10
            assert "validation/data_types" not in trace["node_statuses"]
            return {"HTTP": 500, "durable_facts_added": 10, "layer1_data_types": "absent"}

    @observe("P09", "Hook loss on Redis save failure is invisible in successful response")
    def _():
        with fixture(redis=True) as (client, ss, rs, app):
            rid = upload(client)
            count = len(rs.list_events(rid))
            def fail_save_hook():
                with patch.object(ss, "save", side_effect=RuntimeError("audit injected trace save failure")):
                    return client.get("/v1/session/dataset/outlier-profile")
            response = fail_save_hook()
            assert response.status_code == 200 and len(rs.list_events(rid)) == count
            return {"profile_HTTP": 200, "new_durable_events": 0, "loss_marker_in_response": False}

    @observe("P10", "Durable append failure changes run metadata without writing event")
    def _():
        ss = AnalysisSession(session_id="audit-session", run_id="RUN-AUDIT")
        rs = MemoryResearchRunStore()
        with patch.object(research_runs, "_store", rs), \
             patch.object(rs, "append_event", side_effect=RuntimeError("audit injected append failure")):
            research_runs.record_run_event(ss, event("target_column_changed", "validation", None, target_column="rain", source="auto"))
        assert rs.get_run("RUN-AUDIT").target_column == "rain" and rs.list_events("RUN-AUDIT") == []
        return {"run_target": "rain", "durable_events": 0, "exception_to_caller": False}

    @observe("P11", "Layer1 cap erases derived status and shifts displayed start")
    def _():
        with fixture() as (client, ss, rs, app):
            rid = upload(client)
            old_trace = client.get("/v1/progress/trace").json()
            s = active_session(client, ss)
            base = datetime(2026, 10, 9, 11, tzinfo=timezone.utc)
            for i in range(session_store.MAX_PIPELINE_TRACE_EVENTS + 1):
                e = replace(make_trace_event("backtest_run", stage="modeling", node_id="backtest", run_id=rid),
                            ts=(base + timedelta(seconds=i)).isoformat())
                s.append_trace_event(e)
                research_runs.record_run_event(s, e)
            ss.save(s)
            data = client.get("/v1/progress/trace").json()
            mentor = client.get(f"/v1/progress/runs/{rid}/mentor/next-step").json()
            full = node_status.derive_node_statuses(rs.list_events(rid))
            assert len(data["events"]) == 1000 and "upload/overview" not in data["node_statuses"]
            assert full["upload/overview"] == "done" and data["started_at"] != old_trace["started_at"]
            return {"layer1_events": len(data["events"]), "layer2_events": len(rs.list_events(rid)),
                    "layer1_upload": "pending", "layer2_upload": full["upload/overview"],
                    "started_at_before": old_trace["started_at"], "started_at_after": data["started_at"],
                    "run_created_at": rs.get_run(rid).created_at}

    @observe("P12", "Panel timestamp sort and durable append order can select different last facts")
    def _():
        events = [event("preprocessing_check_status", "preprocessing", "missing", "2026-10-09T11:00:00+00:00", status="warning"),
                  event("preprocessing_check_status", "preprocessing", "missing", "2026-10-09T10:59:59+00:00", status="done")]
        append_status = node_status.derive_node_statuses(events)["preprocessing/missing"]
        sorted_status = node_status.derive_node_statuses(sort_events_chronologically([e.to_dict() for e in events]))["preprocessing/missing"]
        assert append_status == "done" and sorted_status == "warning"
        return {"append_order_status": append_status, "timestamp_sort_status": sorted_status,
                "production_clock_skew_observed": False}

    @observe("P13", "Seven new Modeling event types do not project a status")
    def _():
        types = ["candidates_generated", "selection_evaluated", "models_compared", "diagnostics_run", "tuning_skipped", "tuning_job_started", "tuning_job_cancelled"]
        result = {kind: node_status.resolve_event_status({"event_type": kind, "payload": {}}) for kind in types}
        assert all(v is None for v in result.values())
        return {"projection": result, "candidate_generation_default": "pending"}

    @observe("P14", "Clean preview still implies found violations; no-op apply implies done")
    def _():
        preview = event("correction_previewed", "preprocessing", "missing", total_missing=0, total_changed=0, applied=False)
        applied = event("correction_applied", "preprocessing", "missing", total_missing=4, total_changed=0, applied=True)
        states = node_status.derive_pipeline_node_states([preview])
        a = next(n for n in states if n["stage"] == "preprocessing" and n["node_id"] == "missing")
        b = node_status.derive_node_statuses([applied])["preprocessing/missing"]
        assert a["status"] == "warning" and "Найдены нарушения" in a["status_reason"] and b == "done"
        return {"zero_problem_preview": a, "no_change_apply_status": b, "scope": "projection contract"}

    @observe("P15", "Invalid payload status is ignored for status but updates reason and badge")
    def _():
        events = [event("preprocessing_check_status", "preprocessing", "missing", status="done"),
                  event("preprocessing_check_status", "preprocessing", "missing", status="invalid", total_missing=99)]
        n = next(n for n in node_status.derive_pipeline_node_states(events) if n["stage"] == "preprocessing" and n["node_id"] == "missing")
        assert n["status"] == "done" and n["summary_count"] == 99
        return {"node": n, "invalid_status_rejected_by_HTTP_report": True}

    @observe("P16", "Status-only client snapshot preserves stale diagnostic count")
    def _():
        events = [event("outliers_profile_status", "preprocessing", "outliers", status="warning", total_outliers=4),
                  event("preprocessing_check_status", "preprocessing", "outliers", status="done")]
        n = next(n for n in node_status.derive_pipeline_node_states(events) if n["stage"] == "preprocessing" and n["node_id"] == "outliers")
        assert n["status"] == "done" and n["summary_count"] == 4
        return {"node": n, "count_observed_in_latest_snapshot": False}

    @observe("P17", "Forecast canonicalization drops already existing identity and actor")
    def _():
        e = make_trace_event("forecast_generated", run_id="RUN-AUDIT", actor="system", forecast_id="FC-AUDIT")
        reduced = progress._canonical_forecast_trace_events({"FC-AUDIT": {"trace_events": [e.to_dict()]}})[0]
        assert "event_id" not in reduced and "actor" not in reduced and "run_id" not in reduced
        merged = [e.to_dict(), reduced]
        assert len(merged) == 2
        return {"keys_retained": sorted(reduced), "same_fact_merge_count": len(merged),
                "scope": "reader contract; default restore does not reload forecast artifacts"}

    @observe("P18", "Report target line omits explicit auto source")
    def _():
        e = make_trace_event("target_column_changed", stage="validation", source="auto", target_column="rain")
        line, _ = fact_line(e.to_dict())
        assert "авто" not in line
        modern_line, _ = fact_line(event("candidates_generated", "modeling", "candidate_generation", runnable_candidates=3).to_dict())
        return {"auto_line": line, "candidates_line": modern_line}

    @observe("P19", "Outlier dedupe compares status/count, loses same-picture method change")
    def _():
        s = AnalysisSession(session_id="audit-session", run_id="RUN-AUDIT")
        s.append_trace_event(event("outliers_profile_status", "preprocessing", "outliers", status="done", total_outliers=0, method="iqr", mode="auto"))
        route = trace_hook.resolve_trace_route("GET", "/v1/session/dataset/outlier-profile")
        result = trace_hook.record_trace_event(s, route, response_body={"status": "done", "total_outliers": 0, "method": "zscore", "mode": "enabled"})
        assert result is None
        return {"old_method": "iqr", "new_method": "zscore", "event_added": False,
                "projection_same": True}

    @observe("P20", "Same event_id appended twice in Memory backend")
    def _():
        rs = MemoryResearchRunStore()
        e = event("backtest_run", "modeling", "backtest")
        rs.upsert_run(ResearchRun(run_id="RUN-AUDIT"))
        rs.append_event("RUN-AUDIT", e)
        rs.append_event("RUN-AUDIT", e)
        assert len(rs.list_events("RUN-AUDIT")) == 2
        return {"memory_count": 2, "postgres_contract": "ON CONFLICT (run_id,event_id) DO NOTHING",
                "live_postgres_tested": False}

    @observe("P21", "Explicit postgres without DATABASE_URL silently becomes Memory")
    def _():
        with patch.object(research_runs, "_store", None), patch.dict(os.environ, {"CISSTAT_RUNS_BACKEND": "postgres"}):
            rs = research_runs.get_research_run_store()
            assert isinstance(rs, MemoryResearchRunStore)
            return {"configured": "postgres", "actual": type(rs).__name__, "error_to_caller": False}

    @observe("P22", "ASGI response ends before hook recording begins")
    def _():
        timeline = []
        async def endpoint(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})
        class Hook(trace_hook.TraceHookMiddleware):
            async def _record(self, *args):
                timeline.append("record")
        async def send(message):
            if message["type"] == "http.response.body":
                timeline.append("final_body_sent")
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}
        asyncio.run(Hook(endpoint)({"type": "http", "method": "POST", "path": "/v1/session/target-column"}, receive, send))
        assert timeline == ["final_body_sent", "record"]
        return {"timeline": timeline, "live_network_race_measured": False}

    @observe("P23", "Timestamp conversion substitutes current time for invalid raw ts")
    def _():
        value = research_runs._ts_to_db("invalid-timestamp")
        assert isinstance(value, datetime)
        return {"input": "invalid-timestamp", "output": value.isoformat(), "scope": "Postgres conversion function"}

    @observe("P24", "Old unbound status report is accepted against a new run")
    def _():
        with fixture() as (client, ss, rs, app):
            old_run = upload(client)
            old_body = {"checks": dict.fromkeys(STAGE_NODES["validation"], "done")}
            new_run = upload(client, multi=True)
            assert old_run != new_run
            before = len(rs.list_events(new_run))
            response = client.post("/v1/progress/validation-checks", json=old_body)
            assert response.status_code == 200
            assert len(rs.list_events(new_run)) == before + 10
            return {"old_run": old_run, "current_run": new_run,
                    "unbound_old_report_HTTP": 200, "facts_added_to_new_run": 10,
                    "scope": "controlled delayed-report timeline, no live browser race"}

    @observe("P25", "EDA profile reopening can replace done with running")
    def _():
        with fixture() as (client, ss, rs, app):
            rid = upload(client)
            client.post("/v1/session/date-column", json={"column": "date"})
            body = {"checks": dict.fromkeys(STAGE_NODES["eda"], "pending")}
            body["checks"]["correlation"] = "done"
            assert client.post("/v1/progress/eda-checks", json=body).status_code == 200
            assert client.get("/v1/progress/trace").json()["node_statuses"]["eda/correlation"] == "done"
            response = client.get("/v1/session/dataset/eda-correlation", params={"column": "rain", "max_lags": 3})
            assert response.status_code == 200, response.text
            state = client.get("/v1/progress/trace").json()["node_statuses"]["eda/correlation"]
            assert state == "running"
            return {"before": "done", "after": state, "HTTP": response.status_code,
                    "last_event": rs.list_events(rid)[-1].event_type,
                    "scope": "controlled revisit after prior status report, no browser execution"}

    after = source_hashes()
    assert before == after, "Tracked product sources were modified during audit"
    meta = {
        "baseline": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0], "pandas": pd.__version__,
        "fixture": "actual session/progress routers + actual upload_common and ASGI middleware; not apps.api.main",
        "production_connections": False, "product_sources_unchanged": True,
        "source_files_hashed": len(before),
        "observations": RESULTS,
        "counts": {"observed": sum(r["result"] == "OBSERVED" for r in RESULTS),
                   "probe_errors": sum(r["result"] == "PROBE_ERROR" for r in RESULTS)},
    }
    Path(output).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta["counts"], ensure_ascii=False), flush=True)
    return bool(meta["counts"]["probe_errors"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raise SystemExit(main(args.output))
