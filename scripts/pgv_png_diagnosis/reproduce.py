"""Read-only product investigation on disposable native PostgreSQL.

Run from the repository root: python scripts/pgv_png_diagnosis/reproduce.py --out DIR
Requires the API's import dependencies, psycopg[binary], pgserver.
Never connects to production: starts its own TCP-only PostgreSQL cluster.
The only monkeypatch changing behavior is an explicitly labelled control that
preserves revision zero in a newly built print snapshot, in memory only.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def run(out: Path) -> dict:
    import pgserver
    import psycopg
    from tests.integration import authcert_harness as harness

    if out.is_relative_to(ROOT):
        raise ValueError("Evidence output must be outside the source checkout")
    out.mkdir(parents=True, exist_ok=False)
    # Keep disposable DB/object files outside AUTH-00's source tree.
    tempfile.tempdir = str(out.parent)
    cluster = Path(tempfile.mkdtemp(prefix="pgv-png-diag-"))
    bindir = Path(pgserver.__file__).parent / "pginstall" / "bin"
    exe = ".exe" if os.name == "nt" else ""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (out / "initdb.log").open("w", encoding="utf-8") as log:
        subprocess.run([str(bindir / ("initdb" + exe)), "-D", str(cluster),
                        "-U", "postgres", "--auth=trust", "--encoding=UTF8",
                        "--no-locale"], stdout=log, stderr=subprocess.STDOUT, check=True)
    server_log = (out / "postgres.log").open("w", encoding="utf-8")
    server = subprocess.Popen([str(bindir / ("postgres" + exe)), "-D", str(cluster),
                               "-h", "127.0.0.1", "-k", "", "-p", str(port)],
                              stdout=server_log, stderr=subprocess.STDOUT)
    uri = f"postgresql://postgres@127.0.0.1:{port}/postgres?connect_timeout=1"
    dep = None
    previous_server = harness._server
    summary = {"base": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "backend": "native PostgreSQL TCP/UTF8", "steps": [], "exceptions": [],
               "browser_clicks": False, "production_access": False, "renderer_calls": 0}
    try:
        for _ in range(100):
            try:
                with psycopg.connect(uri):
                    break
            except psycopg.OperationalError:
                if server.poll() is not None:
                    raise RuntimeError("Disposable PostgreSQL exited before readiness") from None
                time.sleep(0.1)
        else:
            raise RuntimeError("Disposable PostgreSQL readiness timeout")
        harness._server = SimpleNamespace(get_uri=lambda: uri)
        dep = harness.Deployment()
        dep.personal_user("pgv-png-diagnosis")
        from apps.api import visual_exports
        original_export = visual_exports.request_visual_export
        original_builder = visual_exports.build_visual_print_snapshot

        def observe(*args, **kwargs):
            try:
                return original_export(*args, **kwargs)
            except Exception as exc:
                summary["exceptions"].append({"type": type(exc).__name__, "message": str(exc),
                                               "traceback": traceback.format_exc()})
                raise

        def preserve_zero_control(*args, **kwargs):
            result = original_builder(*args, **kwargs)
            revision = kwargs["result_artifact"].data_revision
            summary["control"] = {"actual_revision": revision,
                                  "original_artifact_version": result["data_artifact"]["artifact_version"]}
            if revision is not None:
                result["data_artifact"]["artifact_version"] = str(revision)
            return result

        with dep.http() as client, patch.object(visual_exports, "request_visual_export", side_effect=observe):
            harness.Deployment.login(client, "pgv-png-diagnosis")
            harness.Deployment.upload(client)
            date = harness.Deployment.post(client, "/v1/session/date-column",
                                           json={"column": "date", "confirmed": True})
            assert date.status_code == 200, date.text
            trace = client.get("/v1/progress/trace").json()
            run_id = trace["run_id"]
            summary["run_initial_data_revision"] = next(r["data_revision"] for r in dep.rows("research_runs") if r["run_id"] == run_id)
            path = f"/v1/documentation/runs/{run_id}/visuals"

            def export(label, view_id, svg=None):
                payload = {"view_id": view_id, "expected_context_id": trace["context_id"]}
                if svg:
                    payload["screen_svg"] = svg
                response = harness.Deployment.post(client, path, json=payload)
                summary["steps"].append({"label": label, "view_id": view_id,
                                         "status": response.status_code, "body": response.json()})
                return response

            first = export("fresh upload before GET dataset", "upload.overview.tech_table")
            assert first.status_code == 409 and first.json()["code"] == "source_unavailable", first.text
            cases = [
                ("upload.overview.tech_table", "/v1/session/dataset", None),
                ("upload.chart.series", "/v1/session/dataset/timeseries?column=value&date_column=date",
                 '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="300"><path d="M0 200 L600 0"/></svg>'),
                ("eda.descriptive.stats", "/v1/session/dataset/stats", None),
                ("preprocessing.missing.overview", "/v1/session/dataset/missing-profile", None),
            ]
            for view, endpoint, svg in cases:
                source = client.get(endpoint)
                assert source.status_code == 200, source.text
                assert source.headers.get("x-visual-result-ref"), endpoint
                response = export("producer GET succeeded, unmodified export", view, svg)
                assert response.status_code == 503 and response.json()["code"] == "visual_export_unavailable", response.text
            summary["jobs_before_control"] = len(dep.rows("document_jobs"))
            assert summary["jobs_before_control"] == 0
            assert all(e["type"] == "ArtifactPayloadInvalid" and "missing_data_version" in e["message"]
                       for e in summary["exceptions"][1:])
            with patch.object(visual_exports, "build_visual_print_snapshot", side_effect=preserve_zero_control):
                control = export("CONTROL only: preserve revision zero; not a product fix", "upload.overview.tech_table")
                assert control.status_code == 202, control.text
                assert control.json()["job"]["state"] == "queued"
            summary["control"]["managed_jobs"] = len(dep.rows("auth_worker_jobs"))
            summary["control"]["result"] = "202 queued, without renderer invocation"
            summary["visual_result_revisions"] = sorted({r["data_revision"] for r in dep.rows("research_artifacts") if r["kind"] == "visual_result"})
        summary["reproduced"] = True
    finally:
        try:
            if dep is not None:
                dep.stop()
            with psycopg.connect(uri) as conn:
                summary["leftover_diagnostic_databases"] = [r[0] for r in conn.execute("SELECT datname FROM pg_database WHERE datname LIKE 'authcert_%'")]
        finally:
            harness._server = previous_server
            server.terminate()
            server.wait(timeout=15)
            server_log.close()
            (out / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    result = run(parser.parse_args().out.resolve())
    print(json.dumps({k: v for k, v in result.items() if k != "exceptions"}, ensure_ascii=False, indent=2))
