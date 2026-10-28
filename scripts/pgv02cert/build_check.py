# scripts/pgv02cert/build_check.py
"""Сборочные проверки PGV-02-CERT: import apps.api.main (маршруты),
каталоги миграций/каталога документов, py_compile, git diff --check,
продуктовое дерево == HEAD. Jest/typecheck не требуются -- дифф не
трогает packages/ui (граница зафиксирована в акте).
"""
from __future__ import annotations

import hashlib
import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
os.chdir(REPO)
sys.path.insert(0, str(REPO))


def md5_head(rel: str) -> bool:
    out = subprocess.run(
        ["git", "show", f"HEAD:{rel}"], cwd=REPO, capture_output=True
    )
    return hashlib.md5((REPO / rel).read_bytes()).hexdigest() == hashlib.md5(out.stdout).hexdigest()


def main() -> int:
    checks: dict = {}
    # 1) импорт полного API + счётчики
    import apps.api.main as main  # noqa: E402

    paths = {getattr(r, "path", "") for r in main.app.routes}
    checks["routes_total"] = len(main.app.routes)
    checks["routes_documentation"] = sum(1 for p in paths if "/documentation" in p)
    checks["no_print_routes"] = not any("print" in p for p in paths)

    from apps.api.artifact_store import ARTIFACT_KINDS
    from apps.api.document_jobs import DocumentRegistry
    from apps.api.report_snapshot import (
        DOCUMENT_CATALOG_VERSION,
        DOCUMENT_KINDS,
        PRINT_DOCUMENT_KINDS,
    )
    from apps.api.research_runs import MIGRATION_FILES, MIGRATION_STATEMENTS
    from apps.api.security_audit import AUDIT_ACTIONS
    from apps.api.visual_artifacts import VISUAL_ARTIFACT_SCHEMA_VERSIONS

    checks["artifact_kinds"] = list(ARTIFACT_KINDS)
    checks["visual_schema_versions"] = dict(VISUAL_ARTIFACT_SCHEMA_VERSIONS)
    checks["document_kinds_count"] = len(DOCUMENT_KINDS)
    checks["print_kinds"] = {k: v[0] for k, v in PRINT_DOCUMENT_KINDS.items()}
    checks["catalog_version"] = DOCUMENT_CATALOG_VERSION
    checks["migration_files"] = len(MIGRATION_FILES)
    checks["migration_statements"] = len(MIGRATION_STATEMENTS)
    checks["audit_actions"] = len(AUDIT_ACTIONS)
    checks["print_methods_in_abc"] = sorted(
        m for m in DocumentRegistry.__abstractmethods__ if "print" in m
    )

    # 2) py_compile изменённых/новых python-файлов поставки
    targets = [
        "apps/api/visual_artifacts.py",
        "apps/api/artifact_promotion.py",
        "apps/api/report_snapshot.py",
        "apps/api/document_jobs.py",
        "apps/api/research_runs.py",
        "scripts/pgv02/check_documents.py",
    ]
    compiled = []
    for rel in targets:
        py_compile.compile(str(REPO / rel), doraise=True)
        compiled.append(rel)
    checks["py_compile"] = compiled

    # 3) git diff --check (пробельные дефекты)
    diff = subprocess.run(["git", "diff", "--check", "HEAD"], cwd=REPO, capture_output=True, text=True)
    checks["git_diff_check_rc"] = diff.returncode

    # 4) продуктовое дерево -- байт-в-байт HEAD (после кампании мутантов)
    product_files = [
        "apps/api/visual_artifacts.py",
        "apps/api/artifact_promotion.py",
        "apps/api/report_snapshot.py",
        "apps/api/document_jobs.py",
        "apps/api/research_runs.py",
        "apps/api/artifact_store.py",
        "apps/api/migrations/0016_pgv2_print_documents.sql",
        "tests/api/test_pgv02_durable_inputs.py",
    ]
    checks["product_tree_eq_head"] = {rel: md5_head(rel) for rel in product_files}

    ok = (
        checks["no_print_routes"]
        and checks["migration_files"] == 16
        and checks["migration_statements"] == 96
        and checks["document_kinds_count"] == 12
        and all(checks["product_tree_eq_head"].values())
        and checks["git_diff_check_rc"] == 0
    )
    checks["BUILD"] = "OK" if ok else "FAIL"
    out = CERT_DIR / "protocols" / "build_check.json"
    out.write_text(json.dumps(checks, ensure_ascii=False, indent=1))
    print(json.dumps(checks, ensure_ascii=False, indent=1))
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
