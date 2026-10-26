"""Independent certification on the actual frontend demo and disposable stores.

No deployment access; no product patches; only the audit output directory is
retained. Generate the CSV with the repository TypeScript demo generator first.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "scripts/doclogcert_2026_10_26/protocols"
SAMPLES = ROOT / "docs/doclogcert_2026_10_26/samples"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    SAMPLES.mkdir(parents=True, exist_ok=True)
    csv_path = SAMPLES / "forecast_monitor_synthetic_n150.csv"
    if not csv_path.exists():
        csv_path = ROOT.parent / "forecast_monitor_synthetic_n150.csv"
    csv_bytes = csv_path.read_bytes()
    results = {"base": "f1d61513184ee0796f285609183e9de8199ca007",
               "scope": "isolated TestClient; own disposable stores; actual TS demo bytes",
               "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(), "steps": []}
    with tempfile.TemporaryDirectory(prefix="doclogcert-", dir=ROOT.parent) as tmp:
        for name in ("DATABASE_URL", "REDIS_URL", "CISSTAT_API_KEYS", "ALLOWED_ORIGINS"):
            os.environ.pop(name, None)
        os.environ.update(CISSTAT_DATA_DIR=tmp, CISSTAT_STORAGE_MODE="advisory",
                          CISSTAT_RUNS_BACKEND="memory", CISSTAT_SESSION_BACKEND="memory",
                          CISSTAT_ARTIFACTS_BACKEND="memory", CISSTAT_DOCUMENTS_BACKEND="memory",
                          CISSTAT_SNAPSHOTS_BACKEND="memory", CISSTAT_IDENTITY_MODE="session_scoped",
                          CISSTAT_DELIVERY_WORKER_ENABLED="0", CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED="0")
        from fastapi.testclient import TestClient
        from apps.api.main import app
        from apps.api.session_store import get_session_store, SESSION_COOKIE_NAME
        from apps.api.research_runs import get_research_run_store
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.document_render_worker import DocumentRenderWorker

        with TestClient(app) as client:
            def call(method, path, *, allowed_statuses=(), **kwargs):
                response = client.request(method, path, **kwargs)
                try:
                    body = response.json()
                except Exception:
                    body = response.text
                results["steps"].append({"method": method, "path": path,
                                         "status": response.status_code})
                assert response.status_code < 400 or response.status_code in allowed_statuses, (method, path, response.status_code, body)
                return body

            upload = call("POST", "/v1/internal/upload", files={
                "file": (csv_path.name, csv_bytes, "text/csv")})
            call("POST", "/v1/session/target-column", json={"column": "value"})
            call("POST", "/v1/session/date-column", json={"column": "date"})
            start = call("POST", "/v1/session/dataset/passport/start")
            trace = call("GET", "/v1/progress/trace")
            run_id = trace["run_id"]
            base_url = f"/v1/documentation/runs/{run_id}/documents"
            results["after_upload"] = {"rows": upload["rows"], "run_id": run_id,
                                       "passport_start": bool(start.get("snapshot_id")),
                                       "documents": call("GET", base_url)["documents"]}
            validated = call("GET", "/v1/session/dataset/validate")
            (OUT / "validation_response.json").write_text(json.dumps(validated, ensure_ascii=False, indent=2))
            # The real UI delivers its displayed check map separately from
            # GET validate. Use computed statuses, never invent "done".
            validation_trace = call("GET", "/v1/progress/trace")
            call("POST", "/v1/progress/validation-checks", json={
                "schema_version": 2, "run_id": run_id,
                "context_id": validation_trace["context_id"],
                "report_id": "doclogcert-2026-10-26-validation",
                "checks": {key: value["status"] for key, value in validated["checks"].items()},
            })
            # Unchanged properties can legitimately return 409; the user only
            # stated that a passport was created at Upload, not a second copy.
            results["validation_passport_attempt"] = call(
                "POST", "/v1/session/dataset/passport/validation", allowed_statuses=(409,))
            results["after_validation_documents"] = call("GET", base_url)["documents"]
            missing_before = call("GET", "/v1/session/dataset/missing-profile")
            outlier_before = call("GET", "/v1/session/dataset/outlier-profile")
            missing = call("POST", "/v1/session/dataset/missing-corrections", json={
                "columns": ["value"], "strategy": "median_mode", "apply": True})
            outliers = call("POST", "/v1/session/dataset/outlier-corrections", json={
                "columns": ["value"], "strategy": "cap", "method": "iqr", "apply": True})
            missing_after = call("GET", "/v1/session/dataset/missing-profile")
            outliers_after = call("GET", "/v1/session/dataset/outlier-profile")
            results["corrections"] = {"missing_before": missing_before,
                                      "outliers_before": outlier_before,
                                      "missing_apply": missing, "outlier_apply": outliers,
                                      "missing_after": missing_after, "outliers_after": outliers_after}
            results["after_corrections_documents"] = call("GET", base_url)["documents"]
            session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
            registry = get_artifact_registry()
            results["artifacts_after_real_pipeline"] = [a.to_dict() for a in registry.list_artifacts(run_id)]
            results["session_after_pipeline"] = {
                "run_id": session.run_id, "context_id": session.current_context_id(),
                "data_revision": session.data_revision,
                "passports": [{"stage": p.stage, "snapshot_id": p.snapshot_id} for p in session.passport_history],
            }

            def science():
                s = get_session_store().get(session.session_id)
                return {"df": s.dataframe.to_json(date_format="iso"),
                        "context_id": s.current_context_id(), "data_revision": s.data_revision,
                        "target": s.target_column, "date": s.date_column,
                        "events": [e.to_dict() for e in get_research_run_store().list_events(run_id)]}

            initial_science = science()
            initial_events = initial_science["events"]
            (OUT / "pipeline_events.json").write_text(json.dumps(initial_events, ensure_ascii=False, indent=2))
            results["manual_documents"] = []
            for code in ("D02", "D03", "D04"):
                response = call("POST", base_url, json={"kind": code, "refresh": True})
                revision_id = response["revision"]["revision_id"]
                detail = call("GET", f"/v1/documentation/revisions/{revision_id}")
                snapshot = detail["snapshot"]
                meta = {"kind": code, "revision_id": revision_id,
                        "completeness": snapshot["completeness"],
                        "reproducibility": snapshot["reproducibility"],
                        "data_ref": snapshot["data_ref"], "sections": snapshot["sections"], "formats": {}}
                (SAMPLES / f"{code}.snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
                for fmt in ("md", "html", "json", "pdf"):
                    requested = call("POST", f"/v1/documentation/revisions/{revision_id}/renditions", json={"format": fmt})
                    job = requested["job"]
                    if job["state"] == "queued":
                        worker = DocumentRenderWorker()
                        meta["worker_summary"] = worker.run_once()
                        job = call("GET", f"/v1/documentation/jobs/{job['job_id']}")["job"]
                    meta["formats"][fmt] = {"state": job["state"], "error_code": job.get("error_code")}
                    if job["state"] == "ready":
                        rid = job["rendition"]["rendition_id"]
                        content = client.get(f"/v1/documentation/renditions/{rid}/content")
                        assert content.status_code == 200, content.text
                        (SAMPLES / f"{code}.{fmt}").write_bytes(content.content)
                        meta["formats"][fmt]["sha256"] = hashlib.sha256(content.content).hexdigest()
                with TestClient(app) as foreign:
                    foreign_response = foreign.get(f"/v1/documentation/revisions/{revision_id}")
                    meta["foreign_http"] = foreign_response.status_code
                    assert foreign_response.status_code == 404
                results["manual_documents"].append(meta)
            results["read_render_preserved_science"] = science() == initial_science
            results["after_manual_document_count"] = len(call("GET", base_url)["documents"])
            report = client.get(f"/v1/progress/runs/{run_id}/report?format=md")
            assert report.status_code == 200, report.text
            (SAMPLES / "progress_history.md").write_text(report.text)
            results["event_claim_validity"] = []
            events_by_id = {"event:" + e["event_id"]: e for e in initial_events}
            current_ctx = session.current_context_id()
            for doc in results["manual_documents"]:
                for section in doc["sections"]:
                    for claim in section["claims"]:
                        for ref in claim["event_refs"]:
                            event = events_by_id.get(ref)
                            if event:
                                results["event_claim_validity"].append({
                                    "kind": doc["kind"], "event_type": event["event_type"],
                                    "event_context": event.get("context_id"), "snapshot_context": current_ctx,
                                    "claim_validity": claim["validity"]})
            results["versions"] = {}
            from importlib.metadata import version, PackageNotFoundError
            for name in ("fastapi", "starlette", "pandas", "numpy", "SQLAlchemy", "pyarrow", "reportlab"):
                try: results["versions"][name] = version(name)
                except PackageNotFoundError: results["versions"][name] = "missing"
    (OUT / "scenario.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps({"documents_before_explicit_create": len(results["after_corrections_documents"]),
                      "artifacts_before_explicit_create": len(results["artifacts_after_real_pipeline"]),
                      "documents_after_explicit_create": results["after_manual_document_count"],
                      "read_render_preserved_science": results["read_render_preserved_science"],
                      "samples": str(SAMPLES)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
