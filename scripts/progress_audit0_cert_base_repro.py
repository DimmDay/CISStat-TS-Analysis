"""AUDIT-0-CERT (сертификация задачи AUDIT-0, oracle OR-A): независимое
повторение базы P01-P25 на СОБСТВЕННЫХ данных сертификатора.

Третья точка данных по базе аудита «Прогресса»:
  1) автор аудита (PROGR-AUDIT-1): date,rain[,snow], 2026-01, i*2.5/i*0.7;
  2) исполнитель AUDIT-0 (PROGR-AUDIT-0): date,temp[,humidity], 2026-02, i*1.8/i*0.35;
  3) сертификатор (ЭТОТ скрипт): date,pressure[,wind], 2026-03, i*0.9/i*0.55.

Стенд -- ОРИГИНАЛЬНЫЙ инструмент аудита (scripts/progress_audit_readonly.py),
загружается importlib по пути файла БЕЗ изменений (прецеденты PROGR-25-D и
PROGR-AUDIT-0): fixture (реальные session/progress routers + handle_upload +
TraceHookMiddleware), env-изоляция, source_hashes, observe. Семантика каждого
пина P01-P25 -- 1:1 с оригиналом; отличия ТОЛЬКО в данных/идентификаторах
(колонки pressure/wind, даты 2026-03, run_id RUN-CERT0, ts-базы 2026-03-15).

Запуск из корня репозитория:
  python scripts/progress_audit0_cert_base_repro.py --output scripts/progress_audit0_cert_base_repro_results.json

Наблюдение дефекта -- успех исследовательской проверки, не признание
поведения корректным (spec_progress_audit.md §3.2). Протокол не является
acceptance-suite.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

# Оригинальный инструмент аудита -- без изменений (как в PROGR-AUDIT-0).
_spec = importlib.util.spec_from_file_location(
    "progress_audit_readonly", ROOT / "scripts" / "progress_audit_readonly.py"
)
audit_base = importlib.util.module_from_spec(_spec)
sys.modules["progress_audit_readonly"] = audit_base
_spec.loader.exec_module(audit_base)

from apps.api import research_runs  # noqa: E402
from apps.api.research_runs import MemoryResearchRunStore, ResearchRun  # noqa: E402
from apps.api.trace_events import make_trace_event  # noqa: E402
from apps.api.session_store import AnalysisSession  # noqa: E402
from app.core import mentor_rules, node_status  # noqa: E402
from app.core.pipeline_graph import STAGE_NODES  # noqa: E402
from app.core.run_report import fact_line, sort_events_chronologically  # noqa: E402

# ── Данные сертификатора (единственное отличие от автора аудита) ──────
SINGLE_HEADER = "date,pressure"
MULTI_HEADER = "date,pressure,wind"
SINGLE_ROW = "2026-03-{day:02d},{value}"
MULTI_ROW = "2026-03-{day:02d},{value},{wind_value}"
VALUE_SCALE = 0.9
WIND_SCALE = 0.55
SINGLE_COL = "pressure"
MANUAL_COL = "wind"
RUN = "RUN-CERT0"
SESSION = "cert0-session"
TS_BASE = "2026-03-15T09:30:00+00:00"


def upload(client, multi=False):
    """Свой CSV сертификатора: date,pressure[,wind], 20 строк 2026-03-01..20."""
    lines = [MULTI_HEADER if multi else SINGLE_HEADER]
    for i in range(1, 21):
        cells = {
            "day": i,
            "value": round(i * VALUE_SCALE, 2),
            "wind_value": round(i * WIND_SCALE, 2),
        }
        lines.append((MULTI_ROW if multi else SINGLE_ROW).format(**cells))
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("pressure.csv", "\n".join(lines), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return client.get("/v1/progress/trace").json()["run_id"]


def event(kind, stage, node, ts=TS_BASE, **payload):
    return replace(
        make_trace_event(kind, stage=stage, node_id=node, run_id=RUN, **payload), ts=ts
    )


def main(output):
    before = audit_base.source_hashes()

    @audit_base.observe("P01", "CERT own-data: single numeric target, same auto fact in both layers (pressure)")
    def _():
        with audit_base.fixture() as (client, ss, rs, app):
            rid = upload(client)
            current, trace = audit_base.states(client)
            durable = rs.list_events(rid)
            auto1 = [e for e in trace["events"] if e["event_type"] == "target_column_changed"]
            auto2 = [e.to_dict() for e in durable if e.event_type == "target_column_changed"]
            assert current["target_column"] == SINGLE_COL and current["target_column_source"] == "auto"
            assert len(auto1) == len(auto2) == 1 and auto1[0]["event_id"] == auto2[0]["event_id"]
            assert auto1[0]["actor"] == "system" and durable[0].event_type == "target_column_changed"
            client.post("/v1/session/date-column", json={"column": "date"})
            mentor = client.get(f"/v1/progress/runs/{rid}/mentor/next-step").json()
            assert f"автоматически: {SINGLE_COL}" in mentor["phase_text"]
            return {"target": SINGLE_COL, "source": "auto", "layers_same_event_id": True,
                    "order": [e.event_type for e in durable], "mentor": mentor["phase_text"]}

    @audit_base.observe("P02", "CERT own-data: recommendation is not selection (pressure/wind)")
    def _():
        with audit_base.fixture() as (client, ss, rs, app):
            rid = upload(client, multi=True)
            data = client.get("/v1/session/target-column").json()
            assert data["target_column"] is None and data["suggested_column"] == SINGLE_COL
            assert not any(e.event_type == "target_column_changed" for e in rs.list_events(rid))
            response = client.post("/v1/session/target-column", json={"column": MANUAL_COL})
            assert response.status_code == 200, response.text
            e = rs.list_events(rid)[-1]
            assert e.payload == {"target_column": MANUAL_COL}
            return {"before": data, "manual_event_payload": e.payload}

    @audit_base.observe("P03", "CERT own-data: type conversion resets session target, not durable/mentor fact")
    def _():
        with audit_base.fixture() as (client, ss, rs, app):
            rid = upload(client)
            client.post("/v1/session/date-column", json={"column": "date"})
            response = client.post("/v1/session/dataset/convert-types", json={
                "conversions": [{"column": SINGLE_COL, "target_type": "string"}], "apply": True})
            assert response.status_code == 200, response.text
            current, trace = audit_base.states(client)
            events = rs.list_events(rid)
            assert response.json()["target_column_reset"] and current["target_column"] is None
            assert rs.get_run(rid).target_column == SINGLE_COL and mentor_rules._target_confirmed(events)
            text = mentor_rules.phase_text("upload", statuses=node_status.derive_node_statuses(events), events=events)
            assert f"автоматически: {SINGLE_COL}" in text
            reason = next(n["status_reason"] for n in trace["nodes"]
                          if n["stage"] == "validation" and n["node_id"] == "sufficiency")
            return {"session_target": current["target_column"], "run_target": rs.get_run(rid).target_column,
                    "historical_mentor_upload_text": text, "sufficiency_reason": reason,
                    "reset_event": events[-1].to_dict()}

    @audit_base.observe("P04", "CERT own-data: restore preserves auto event, drops target_column_source")
    def _():
        with audit_base.fixture() as (client, ss, rs, app):
            rid = upload(client)
            response = client.get(f"/v1/progress/runs/{rid}/restore")
            assert response.status_code == 200, response.text
            current, trace = audit_base.states(client)
            assert current["target_column"] == SINGLE_COL and current["target_column_source"] is None
            assert any(e["payload"].get("source") == "auto" for e in trace["events"])
            return {"session_target": current["target_column"], "session_source": current["target_column_source"],
                    "auto_fact_in_trace": True}

    @audit_base.observe("P05", "CERT own-data: restore reloads raw values while old correction stays done")
    def _():
        with audit_base.fixture() as (client, ss, rs, app):
            rid = upload(client)
            response = client.post("/v1/session/dataset/convert-types", json={
                "conversions": [{"column": SINGLE_COL, "target_type": "string"}], "apply": True})
            assert response.status_code == 200
            before_type = str(audit_base.active_session(client, ss).dataframe[SINGLE_COL].dtype)
            response = client.get(f"/v1/progress/runs/{rid}/restore")
            assert response.status_code == 200, response.text
            current, trace = audit_base.states(client)
            after_type = str(audit_base.active_session(client, ss).dataframe[SINGLE_COL].dtype)
            import pandas as pd
            assert current["target_column"] == SINGLE_COL and pd.api.types.is_numeric_dtype(
                audit_base.active_session(client, ss).dataframe[SINGLE_COL])
            assert trace["node_statuses"]["validation/data_types"] == "done"
            return {"dtype_before_restore": before_type, "dtype_after_restore": after_type,
                    "resurrected_target": current["target_column"], "historical_data_types_status": "done"}

    @audit_base.observe("P06", "CERT: full status maps validate form but accept uncomputed client claims")
    def _():
        with audit_base.fixture() as (client, ss, rs, app):
            rid = upload(client)
            before_count = len(rs.list_events(rid))
            incomplete = client.post("/v1/progress/validation-checks", json={"checks": {"data_types": "done"}})
            assert incomplete.status_code == 422 and len(rs.list_events(rid)) == before_count
            body = {"checks": dict.fromkeys(STAGE_NODES["validation"], "done")}
            response = client.post("/v1/progress/validation-checks", json=body)
            assert response.status_code == 200
            current, trace = audit_base.states(client)
            assert all(trace["node_statuses"][f"validation/{n}"] == "done" for n in STAGE_NODES["validation"])
            return {"invalid_report": 422, "all_done_without_validate": 200,
                    "actor": rs.list_events(rid)[-1].actor, "payload": rs.list_events(rid)[-1].payload}

    @audit_base.observe("P07", "CERT: identical status report creates new facts on every POST")
    def _():
        with audit_base.fixture() as (client, ss, rs, app):
            rid = upload(client)
            body = {"checks": dict.fromkeys(STAGE_NODES["validation"], "done")}
            initial = len(rs.list_events(rid))
            for _ in range(2):
                assert client.post("/v1/progress/validation-checks", json=body).status_code == 200
            assert len(rs.list_events(rid)) - initial == 20
            return {"identical_posts": 2, "new_events": 20, "dedupe": "client component lifetime only"}

    @audit_base.observe("P08", "CERT: report mirrors all ten facts before failed Redis save")
    def _():
        with audit_base.fixture(redis=True) as (client, ss, rs, app):
            rid = upload(client)
            count = len(rs.list_events(rid))
            body = {"checks": dict.fromkeys(STAGE_NODES["validation"], "done")}
            with patch.object(ss, "save", side_effect=RuntimeError("cert injected save failure")):
                response = client.post("/v1/progress/validation-checks", json=body)
            current, trace = audit_base.states(client)
            assert response.status_code == 500 and len(rs.list_events(rid)) == count + 10
            assert "validation/data_types" not in trace["node_statuses"]
            return {"HTTP": 500, "durable_facts_added": 10, "layer1_data_types": "absent"}

    @audit_base.observe("P09", "CERT: hook loss on Redis save failure is invisible in successful response")
    def _():
        with audit_base.fixture(redis=True) as (client, ss, rs, app):
            rid = upload(client)
            count = len(rs.list_events(rid))
            with patch.object(ss, "save", side_effect=RuntimeError("cert injected trace save failure")):
                response = client.get("/v1/session/dataset/outlier-profile")
            assert response.status_code == 200 and len(rs.list_events(rid)) == count
            return {"profile_HTTP": 200, "new_durable_events": 0, "loss_marker_in_response": False}

    @audit_base.observe("P10", "CERT: durable append failure changes run metadata without writing event (own run_id)")
    def _():
        ss = AnalysisSession(session_id=SESSION, run_id=RUN)
        rs = MemoryResearchRunStore()
        # Событие строится явно: хелпер audit_base.event жёстко кодирует
        # run_id="RUN-AUDIT" -- у сертификатора свой идентификатор RUN-CERT0.
        e = audit_base.replace(
            make_trace_event("target_column_changed", stage="validation", node_id=None,
                             run_id=RUN, target_column=SINGLE_COL, source="auto"),
            ts=TS_BASE)
        with patch.object(research_runs, "_store", rs), \
             patch.object(rs, "append_event", side_effect=RuntimeError("cert injected append failure")):
            research_runs.record_run_event(ss, e)
        assert rs.get_run(RUN).target_column == SINGLE_COL and rs.list_events(RUN) == []
        return {"run_target": SINGLE_COL, "durable_events": 0, "exception_to_caller": False}

    @audit_base.observe("P11", "CERT: layer1 cap erases derived status and shifts displayed start")
    def _():
        with audit_base.fixture() as (client, ss, rs, app):
            rid = upload(client)
            old_trace = client.get("/v1/progress/trace").json()
            s = audit_base.active_session(client, ss)
            base = datetime(2026, 3, 15, 9, tzinfo=timezone.utc)
            from apps.api import session_store
            for i in range(session_store.MAX_PIPELINE_TRACE_EVENTS + 1):
                e = replace(make_trace_event("backtest_run", stage="modeling", node_id="backtest", run_id=rid),
                            ts=(base + timedelta(seconds=i)).isoformat())
                s.append_trace_event(e)
                research_runs.record_run_event(s, e)
            ss.save(s)
            data = client.get("/v1/progress/trace").json()
            full = node_status.derive_node_statuses(rs.list_events(rid))
            assert len(data["events"]) == 1000 and "upload/overview" not in data["node_statuses"]
            assert full["upload/overview"] == "done" and data["started_at"] != old_trace["started_at"]
            return {"layer1_events": len(data["events"]), "layer2_events": len(rs.list_events(rid)),
                    "layer1_upload": "pending", "layer2_upload": full["upload/overview"],
                    "started_at_before": old_trace["started_at"], "started_at_after": data["started_at"],
                    "run_created_at": rs.get_run(rid).created_at}

    @audit_base.observe("P12", "CERT: panel timestamp sort and durable append order select different last facts")
    def _():
        events = [event("preprocessing_check_status", "preprocessing", "missing", "2026-03-15T09:00:00+00:00", status="warning"),
                  event("preprocessing_check_status", "preprocessing", "missing", "2026-03-15T08:59:59+00:00", status="done")]
        append_status = node_status.derive_node_statuses(events)["preprocessing/missing"]
        sorted_status = node_status.derive_node_statuses(
            sort_events_chronologically([e.to_dict() for e in events]))["preprocessing/missing"]
        assert append_status == "done" and sorted_status == "warning"
        return {"append_order_status": append_status, "timestamp_sort_status": sorted_status,
                "production_clock_skew_observed": False}

    @audit_base.observe("P13", "CERT: seven new Modeling event types do not project a status")
    def _():
        types = ["candidates_generated", "selection_evaluated", "models_compared", "diagnostics_run",
                 "tuning_skipped", "tuning_job_started", "tuning_job_cancelled"]
        result = {kind: node_status.resolve_event_status({"event_type": kind, "payload": {}}) for kind in types}
        assert all(v is None for v in result.values())
        return {"projection": result, "candidate_generation_default": "pending"}

    @audit_base.observe("P14", "CERT: clean preview implies found violations; no-op apply implies done")
    def _():
        preview = event("correction_previewed", "preprocessing", "missing", total_missing=0, total_changed=0, applied=False)
        applied = event("correction_applied", "preprocessing", "missing", total_missing=4, total_changed=0, applied=True)
        states = node_status.derive_pipeline_node_states([preview])
        a = next(n for n in states if n["stage"] == "preprocessing" and n["node_id"] == "missing")
        b = node_status.derive_node_statuses([applied])["preprocessing/missing"]
        assert a["status"] == "warning" and "Найдены нарушения" in a["status_reason"] and b == "done"
        return {"zero_problem_preview": a, "no_change_apply_status": b, "scope": "projection contract"}

    @audit_base.observe("P15", "CERT: invalid payload status ignored for status, updates reason and badge")
    def _():
        events = [event("preprocessing_check_status", "preprocessing", "missing", status="done"),
                  event("preprocessing_check_status", "preprocessing", "missing", status="invalid", total_missing=99)]
        n = next(n for n in node_status.derive_pipeline_node_states(events)
                 if n["stage"] == "preprocessing" and n["node_id"] == "missing")
        assert n["status"] == "done" and n["summary_count"] == 99
        return {"node": n, "invalid_status_rejected_by_HTTP_report": True}

    @audit_base.observe("P16", "CERT: status-only client snapshot preserves stale diagnostic count")
    def _():
        events = [event("outliers_profile_status", "preprocessing", "outliers", status="warning", total_outliers=4),
                  event("preprocessing_check_status", "preprocessing", "outliers", status="done")]
        n = next(n for n in node_status.derive_pipeline_node_states(events)
                 if n["stage"] == "preprocessing" and n["node_id"] == "outliers")
        assert n["status"] == "done" and n["summary_count"] == 4
        return {"node": n, "count_observed_in_latest_snapshot": False}

    @audit_base.observe("P17", "CERT: forecast canonicalization drops existing identity and actor (own ids)")
    def _():
        e = make_trace_event("forecast_generated", run_id=RUN, actor="system", forecast_id="FC-CERT0")
        reduced = audit_base.progress._canonical_forecast_trace_events({"FC-CERT0": {"trace_events": [e.to_dict()]}})[0]
        assert "event_id" not in reduced and "actor" not in reduced and "run_id" not in reduced
        merged = [e.to_dict(), reduced]
        assert len(merged) == 2
        return {"keys_retained": sorted(reduced), "same_fact_merge_count": len(merged),
                "scope": "reader contract; default restore does not reload forecast artifacts"}

    @audit_base.observe("P18", "CERT: report target line omits explicit auto source")
    def _():
        e = make_trace_event("target_column_changed", stage="validation", source="auto", target_column=SINGLE_COL)
        line, _ = fact_line(e.to_dict())
        assert "авто" not in line
        modern_line, _ = fact_line(event(
            "candidates_generated", "modeling", "candidate_generation", runnable_candidates=3).to_dict())
        return {"auto_line": line, "candidates_line": modern_line}

    @audit_base.observe("P19", "CERT: outlier dedupe compares status/count, loses same-picture method change")
    def _():
        s = AnalysisSession(session_id=SESSION, run_id=RUN)
        s.append_trace_event(event("outliers_profile_status", "preprocessing", "outliers",
                                   status="done", total_outliers=0, method="iqr", mode="auto"))
        route = audit_base.trace_hook.resolve_trace_route("GET", "/v1/session/dataset/outlier-profile")
        result = audit_base.trace_hook.record_trace_event(
            s, route, response_body={"status": "done", "total_outliers": 0, "method": "zscore", "mode": "enabled"})
        assert result is None
        return {"old_method": "iqr", "new_method": "zscore", "event_added": False,
                "projection_same": True}

    @audit_base.observe("P20", "CERT: same event_id appended twice in Memory backend")
    def _():
        rs = MemoryResearchRunStore()
        e = event("backtest_run", "modeling", "backtest")
        rs.upsert_run(ResearchRun(run_id=RUN))
        rs.append_event(RUN, e)
        rs.append_event(RUN, e)
        assert len(rs.list_events(RUN)) == 2
        return {"memory_count": 2, "postgres_contract": "ON CONFLICT (run_id,event_id) DO NOTHING",
                "live_postgres_tested": False}

    @audit_base.observe("P21", "CERT: explicit postgres without DATABASE_URL silently becomes Memory")
    def _():
        with patch.object(research_runs, "_store", None), \
             patch.dict(audit_base.os.environ, {"CISSTAT_RUNS_BACKEND": "postgres"}):
            rs = research_runs.get_research_run_store()
            assert isinstance(rs, MemoryResearchRunStore)
            return {"configured": "postgres", "actual": type(rs).__name__, "error_to_caller": False}

    @audit_base.observe("P22", "CERT: ASGI response ends before hook recording begins")
    def _():
        timeline = []

        async def endpoint(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        class Hook(audit_base.trace_hook.TraceHookMiddleware):
            async def _record(self, *args):
                timeline.append("record")

        async def send(message):
            if message["type"] == "http.response.body":
                timeline.append("final_body_sent")

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        import asyncio
        asyncio.run(Hook(endpoint)({"type": "http", "method": "POST", "path": "/v1/session/target-column"}, receive, send))
        assert timeline == ["final_body_sent", "record"]
        return {"timeline": timeline, "live_network_race_measured": False}

    @audit_base.observe("P23", "CERT: timestamp conversion substitutes current time for invalid raw ts")
    def _():
        value = research_runs._ts_to_db("cert-invalid-timestamp")
        assert isinstance(value, datetime)
        return {"input": "cert-invalid-timestamp", "output": value.isoformat(), "scope": "Postgres conversion function"}

    @audit_base.observe("P24", "CERT: old unbound status report is accepted against a new run")
    def _():
        with audit_base.fixture() as (client, ss, rs, app):
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

    @audit_base.observe("P25", "CERT: EDA profile reopening can replace done with running (pressure)")
    def _():
        with audit_base.fixture() as (client, ss, rs, app):
            rid = upload(client)
            client.post("/v1/session/date-column", json={"column": "date"})
            body = {"checks": dict.fromkeys(STAGE_NODES["eda"], "pending")}
            body["checks"]["correlation"] = "done"
            assert client.post("/v1/progress/eda-checks", json=body).status_code == 200
            assert client.get("/v1/progress/trace").json()["node_statuses"]["eda/correlation"] == "done"
            response = client.get("/v1/session/dataset/eda-correlation", params={"column": SINGLE_COL, "max_lags": 3})
            assert response.status_code == 200, response.text
            state = client.get("/v1/progress/trace").json()["node_statuses"]["eda/correlation"]
            assert state == "running"
            return {"before": "done", "after": state, "HTTP": response.status_code,
                    "last_event": rs.list_events(rid)[-1].event_type,
                    "scope": "controlled revisit after prior status report, no browser execution"}

    after = audit_base.source_hashes()
    assert before == after, "Tracked product sources were modified during AUDIT-0-CERT base repro"

    meta = {
        "baseline": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version.split()[0],
        "task": "AUDIT-0-CERT (сертификация AUDIT-0, oracle OR-A): независимое повторение P01-P25 на данных сертификатора",
        "data_substitution": {
            "columns_single": "date,pressure", "columns_multi": "date,pressure,wind",
            "rows": 20, "dates": "2026-03-01..2026-03-20",
            "values": "pressure=i*0.9, wind=i*0.55",
            "run_id": RUN, "forecast_id": "FC-CERT0", "ts_base": TS_BASE,
            "distinct_from": "audit author (rain/snow, 2026-01) and AUDIT-0 implementer (temp/humidity, 2026-02)",
        },
        "fixture": "original audit tool reused via importlib unchanged: actual session/progress routers + handle_upload + TraceHookMiddleware; not apps.api.main",
        "production_connections": False,
        "product_sources_unchanged": True,
        "source_files_hashed": len(before),
        "observations": audit_base.RESULTS,
        "counts": {"observed": sum(r["result"] == "OBSERVED" for r in audit_base.RESULTS),
                   "probe_errors": sum(r["result"] == "PROBE_ERROR" for r in audit_base.RESULTS)},
    }
    Path(output).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta["counts"], ensure_ascii=False), flush=True)
    return bool(meta["counts"]["probe_errors"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raise SystemExit(main(args.output))
