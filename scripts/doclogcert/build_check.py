# scripts/doclogcert/build_check.py
"""DOCLOG-CERT: сборочная проверка цели 5856764.

- import apps.api.main: маршрут-каталог (221);
- каталог миграций 15 файлов / 93 statement (последняя 0015);
- DOCUMENT_KINDS == 12 (D12 forecast_vs_actual);
- AUDIT_ACTIONS == 28; GRANT_SCOPES/TTL; PROFILE_FORMATS;
- продуктовое дерево чистое: md5 файлов мутантов == git HEAD;
- результаты пишутся в protocols/build_check.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys_path = str(REPO_ROOT)

sys.path.insert(0, sys_path)


def main() -> None:
    import apps.api.main as main_mod
    from apps.api import admin_logs, doc_profiles, monitoring
    from apps.api import report_snapshot, research_runs
    from apps.api import security_audit
    from apps.api.document_renditions import (
        HEAVY_RENDITION_FORMATS,
        RENDITION_FORMATS,
    )

    app_routes = [r for r in main_mod.app.routes if hasattr(r, "path")]
    doc_routes = sorted(
        {r.path for r in app_routes if r.path.startswith("/v1/documentation")}
    )
    logs_routes = sorted(
        {r.path for r in app_routes if r.path.startswith("/v1/logs")}
    )
    mutated_files = {m["file"] for m in
                     __import__("scripts.doclogcert.mutations",
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
        "documentation_routes": len(doc_routes),
        "logs_routes": len(logs_routes),
        "migrations": len(research_runs.MIGRATION_FILES),
        "migration_statements": len(research_runs.MIGRATION_STATEMENTS),
        "last_migration": research_runs.MIGRATION_FILES[-1][0],
        "document_kinds": len(report_snapshot.DOCUMENT_KINDS),
        "d12_kind": report_snapshot.DOCUMENT_KINDS.get("D12"),
        "audit_actions": len(security_audit.AUDIT_ACTIONS),
        "grant_scopes": sorted(admin_logs.GRANT_SCOPES),
        "grant_ttl_max_hours": admin_logs.GRANT_TTL_MAX_HOURS,
        "profile_formats": sorted(doc_profiles.PROFILE_FORMATS),
        "rendition_formats": sorted(RENDITION_FORMATS),
        "heavy_formats": sorted(HEAVY_RENDITION_FORMATS),
        "decision_actions": sorted(monitoring.DECISION_ACTIONS),
        "threshold_metrics": sorted(monitoring.THRESHOLD_METRICS),
        "product_tree_md5_eq_head": tree_clean,
    }
    verdict = (
        payload["routes_total"] == 221
        and payload["migrations"] == 15
        and payload["migration_statements"] == 93
        and payload["document_kinds"] == 12
        and payload["audit_actions"] == 28
        and payload["grant_ttl_max_hours"] == 168
        and payload["profile_formats"] == ["docx", "pdfa"]
        and tree_clean
    )
    payload["BUILD"] = "OK" if verdict else "MISMATCH"
    (HERE / "protocols" / "build_check.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
