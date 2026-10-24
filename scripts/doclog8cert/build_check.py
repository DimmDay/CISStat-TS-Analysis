# scripts/doclog8cert/build_check.py
"""DOCLOG-8-CERT: сборочная проверка цели 659db3d.

- import apps.api.main: маршрут-каталог (216, из них ровно 7 /monitoring/);
- каталог миграций 14 файлов / 85 statement (последняя 0014);
- DOCUMENT_KINDS == 12 (D12 forecast_vs_actual);
- AUDIT_ACTIONS == 24 (три monitoring_*);
- продуктовое дерево чистое: md5 файлов мутантов == git HEAD;
- результаты пишутся в protocols/build_check.json.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys_path = str(REPO_ROOT)

import sys  # noqa: E402

sys.path.insert(0, sys_path)


def main() -> None:
    import apps.api.main as main_mod
    from apps.api import monitoring, report_snapshot, research_runs
    from apps.api import security_audit

    routes = [r for r in main_mod.app.routes
              if hasattr(r, "path") and "/monitoring/" in r.path]
    app_routes = [r for r in main_mod.app.routes if hasattr(r, "path")]
    mutated_files = {m["file"] for m in
                     __import__("scripts.doclog8cert.mutations",
                                fromlist=["MUTANTS"]).MUTANTS}
    tree_clean = all(
        hashlib.md5((REPO_ROOT / f).read_bytes()).hexdigest()
        == hashlib.md5(subprocess.run(
            ["git", "show", f"HEAD:{f}"], cwd=REPO_ROOT,
            capture_output=True).stdout).hexdigest()
        for f in sorted(mutated_files)
    )
    payload = {
        "routes_total": len(app_routes),
        "monitoring_routes": len(routes),
        "monitoring_paths": sorted({r.path for r in routes}),
        "migrations": len(research_runs.MIGRATION_FILES),
        "migration_statements": len(research_runs.MIGRATION_STATEMENTS),
        "last_migration": research_runs.MIGRATION_FILES[-1][0],
        "document_kinds": len(report_snapshot.DOCUMENT_KINDS),
        "d12_kind": report_snapshot.DOCUMENT_KINDS.get("D12"),
        "audit_actions": len(security_audit.AUDIT_ACTIONS),
        "monitoring_actions": sorted(
            a for a in security_audit.AUDIT_ACTIONS
            if a.startswith("monitoring_")
        ),
        "decision_actions": sorted(monitoring.DECISION_ACTIONS),
        "threshold_metrics": sorted(monitoring.THRESHOLD_METRICS),
        "schema_versions": {
            "monitoring": monitoring.MONITORING_SCHEMA_VERSION,
            "actual_vintage": monitoring.ACTUAL_VINTAGE_SCHEMA_VERSION,
            "comparison": monitoring.COMPARISON_SCHEMA_VERSION,
            "decision": monitoring.DECISION_SCHEMA_VERSION,
            "result": monitoring.RESULT_SCHEMA_VERSION,
        },
        "product_tree_md5_eq_head": tree_clean,
    }
    verdict = (
        payload["monitoring_routes"] == 7
        and payload["migrations"] == 14
        and payload["migration_statements"] == 85
        and payload["document_kinds"] == 12
        and payload["audit_actions"] == 24
        and tree_clean
    )
    payload["BUILD"] = "OK" if verdict else "MISMATCH"
    (HERE / "protocols" / "build_check.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
