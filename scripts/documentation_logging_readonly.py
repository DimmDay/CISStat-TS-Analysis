"""Static evidence collector: no product imports, HTTP, storage or model calls.

Run from any directory: python scripts/documentation_logging_readonly.py
Output is JSON on stdout. Redirect it only to a NEW research artifact.
This verifies source facts, not deployment configuration or live behaviour.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
BASE = "bee3f8e300e6d2f5de6f8c9d9e4d6bc6e4091065"


def main() -> None:
    findings = []
    files = {}

    def source(path):
        content = (ROOT / path).read_text(encoding="utf-8")
        files[path] = hashlib.sha256(content.encode()).hexdigest()
        return content

    def evidence(path, needle):
        text = source(path)
        assert needle in text, (path, needle)
        return {"path": path, "line": text[:text.index(needle)].count("\n") + 1,
                "anchor": needle}

    def observe(key, fact, *anchors):
        findings.append({"id": key, "level": "source_fact",
                         "fact": fact, "evidence": [evidence(*a) for a in anchors]})

    def constant(path, name):
        def value(node):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
                left, right = value(node.left), value(node.right)
                assert isinstance(left, int) and isinstance(right, int)
                return left * right
            return ast.literal_eval(node)
        tree = ast.parse(source(path))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets
            ):
                return value(node.value)
        raise AssertionError((path, name))

    session = "apps/api/session_store.py"
    assert constant(session, "SESSION_TTL_SECONDS") == 2592000
    assert constant(session, "MAX_PIPELINE_TRACE_EVENTS") == 1000
    assert constant(session, "PASSPORT_STAGES") == ("start", "validation", "exit", "modeling_entry")
    assert constant(session, "PANEL_PASSPORT_STAGES") == ("panel_entry",)
    observe("F01", "Six canonical stages; session TTL 30d; short trace cap 1000; four single-series passport points and separate panel_entry.",
            (session, 'STAGES = ["upload"'), (session, "SESSION_TTL_SECONDS ="),
            (session, "MAX_PIPELINE_TRACE_EVENTS ="), (session, "PASSPORT_STAGES ="),
            (session, "PANEL_PASSPORT_STAGES ="))
    observe("F02", "TraceEvent v2 has context/result/method/operation refs; required and advisory producer guarantees differ.",
            ("apps/api/trace_events.py", "class TraceEvent:"),
            ("apps/api/delivery_outbox.py", "ADVISORY_PRODUCERS"))
    router = "apps/api/routers/progress.py"
    tree = ast.parse(source(router))
    get_report = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "get_run_report")
    get_report_source = ast.get_source_segment(source(router), get_report)
    assert 'pattern="^(md|html)$"' in get_report_source
    observe("F03", "Existing MD/HTML report reads durable events and current knowledge; v2 preserves event refs and current/stale/unknown validity.",
            (router, 'def get_run_report('),
            ("app/core/run_report.py", 'REPORT_VERSION = "2"'),
            ("app/core/run_report.py", "ТЕКСТ ТЕКУЩЕЙ версии реестра знаний"))
    observe("F04", "Report forecast links use a session-relative export URL, not a frozen artifact.",
            ("app/core/run_report.py", 'href = f"/v1/session/modeling/forecast/{fid}/export.json"'))
    forecast = "apps/api/routers/forecasting_session.py"
    f_tree = ast.parse(source(forecast))
    functions = {n.name: n for n in f_tree.body if isinstance(n, ast.FunctionDef)}
    for name in ("export_forecast_csv", "export_forecast_json"):
        calls = [n for n in ast.walk(functions[name]) if isinstance(n, ast.Call)]
        assert any(isinstance(c.func, ast.Name) and c.func.id == "_record_export" for c in calls)
    observe("F05", "Both forecast GET export functions call _record_export; it touches and saves session state.",
            (forecast, "def _record_export("), (forecast, "def export_forecast_csv("),
            (forecast, "def export_forecast_json("))
    observe("F06", "Forecast UI implements CSV/JSON/PNG; PDF is explicitly unavailable in v1.",
            ("packages/ui/components/ForecastExportMenu.tsx", "PDF сознательно не реализован"),
            ("packages/ui/components/ForecastExportMenu.tsx", "downloadChartPng"))
    observe("F07", "AdminProgressDashboard is aggregate monitoring, with ADMIN API-key auth; no technical log browser was found in the inspected UI.",
            ("packages/ui/components/AdminProgressDashboard.tsx", "fetchAdminOverview"),
            (router, "principal: Any = Depends(require_admin_role)"))
    assert "Request" not in ast.unparse(get_report.args)
    assert "Depends" not in get_report_source
    observe("F08", "Local report handler has no principal/ownership dependency; _require_run only looks up existence. This is a source-level gap, not a live exposure proof.",
            (router, "router = APIRouter()"), (router, "def _require_run("),
            (router, "def get_run_report("))
    observe("F09", "Root API logging defaults to DEBUG; a safe_error helper exists, but some paths log raw exception info.",
            ("apps/api/main.py", "logging.basicConfig(level=logging.DEBUG)"),
            ("apps/api/storage_diagnostics.py", "def safe_error("),
            (router, '"Progress: долговременный слой недоступен (%s)", exc, exc_info=True'))
    observe("F10", "Checkpoint DataFrames are CSV on local filesystem; checkpoint retention currently keeps the last five.",
            ("apps/api/research_runs.py", "def save_checkpoint_snapshot("),
            (router, 'store.list_checkpoints(run_id)][-5:]'))
    observe("F11", "Monitoring task UI is a ModulePlaceholder; implemented Causes returns existing artifacts and marks unavailable methods not_computed.",
            ("apps/standalone/app/tasks/monitoring/page.tsx", 'ModulePlaceholder title="Мониторинг прогноза"'),
            ("apps/api/routers/tasks_session.py", '"method_id": "fold_importance"'))
    observe("F12", "Entity-panel passports/backtests/forecasts are a separate contour; documentation must preserve panel lineage.",
            ("apps/api/routers/modeling_session.py", '"/panel/passport"'),
            ("apps/api/routers/modeling_session.py", '"/panel/backtest"'),
            ("apps/api/routers/modeling_session.py", '"/panel/forecast"'))
    observe("F13", "Legacy Excel exporter hardcodes an institution-verification footer; it is not evidence of approval.",
            ("app/core/export.py", "Верифицировано СтатКомитетом СНГ"),
            ("app.py", "from app.core.export import export_passport_to_excel"))
    observe("F14", "Database upload defaults to an empty source-file fingerprint; data-version evidence needs a separate typed snapshot/digest.",
            ("apps/api/upload_common.py", 'dataset_fingerprint: str = ""'))
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    assert commit == BASE, (commit, BASE)
    print(json.dumps({"base_commit": commit, "method": "static AST and source inspection",
                      "product_imported": False, "http_calls": 0, "database_calls": 0,
                      "product_files_changed": False, "findings": findings,
                      "source_sha256": files}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
