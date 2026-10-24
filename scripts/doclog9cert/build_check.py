# scripts/doclog9cert/build_check.py
"""DOCLOG-9-CERT: сборочная проверка цели 5856764.

- import apps.api.main: маршрут-каталог (221, из них ровно 4 пути
  DOCLOG-9: org-profiles + retire + validations + verify-signature);
- каталог миграций 15 файлов / 93 statement (последняя 0015, 8 statement);
- DOCUMENT_KINDS == 12 (DOCLOG-9 не добавляет вид);
- AUDIT_ACTIONS == 28 (четвёрка org_profile_*/rendition_*);
- HEAVY_RENDITION_FORMATS содержит docx/pdfa;
- продуктовое дерево чистое: md5 файлов мутантов == git HEAD;
- результаты пишутся в protocols/build_check.json.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]

import sys  # noqa: E402

sys.path.insert(0, str(REPO_ROOT))


def main() -> None:
    import apps.api.main as main_mod
    from apps.api import doc_profiles, research_runs, security_audit
    from apps.api import document_renditions, report_snapshot

    routes = [
        r for r in main_mod.app.routes
        if hasattr(r, "path")
        and ("org-profile" in r.path or "validations" in r.path
             or "verify-signature" in r.path)
    ]
    app_routes = [r for r in main_mod.app.routes if hasattr(r, "path")]
    mutated_files = {m["file"] for m in
                     __import__("scripts.doclog9cert.mutations",
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
        "doclog9_routes": len(routes),
        "doclog9_paths": sorted({r.path for r in routes}),
        "migrations": len(research_runs.MIGRATION_FILES),
        "migration_statements": len(research_runs.MIGRATION_STATEMENTS),
        "last_migration": research_runs.MIGRATION_FILES[-1][0],
        "migration_0015_statements": len(research_runs.MIGRATION_STATEMENTS_0015),
        "document_kinds": len(report_snapshot.DOCUMENT_KINDS),
        "audit_actions": len(security_audit.AUDIT_ACTIONS),
        "doclog9_audit_actions": sorted(
            a for a in security_audit.AUDIT_ACTIONS
            if a.startswith("org_profile_") or a.startswith("rendition_v")
            or a.startswith("rendition_a")
        ),
        "profile_formats": sorted(doc_profiles.PROFILE_FORMATS),
        "heavy_has_docx_pdfa": {"docx", "pdfa"} <= set(
            document_renditions.HEAVY_RENDITION_FORMATS
        ),
        "profile_schema_version": doc_profiles.PROFILE_SCHEMA_VERSION,
        "product_tree_md5_eq_head": tree_clean,
    }
    verdict = (
        payload["doclog9_routes"] == 5
        and len(payload["doclog9_paths"]) == 4
        and payload["migrations"] == 15
        and payload["migration_statements"] == 93
        and payload["migration_0015_statements"] == 8
        and payload["document_kinds"] == 12
        and payload["audit_actions"] == 28
        and payload["heavy_has_docx_pdfa"]
        and payload["profile_schema_version"] == "doclog.org_profile/1"
        and tree_clean
    )
    payload["BUILD"] = "OK" if verdict else "MISMATCH"
    (HERE / "protocols" / "build_check.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
