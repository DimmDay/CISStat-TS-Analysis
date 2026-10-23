#!/usr/bin/env python3
"""DOCLOG-6-CERT: build-проверка целевой базы (70c9c1a)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
PROTOCOLS = REPO / "scripts" / "doclog6cert" / "protocols"


def main() -> int:
    checks: dict[str, object] = {}
    # 1. Импорт приложения и маршруты
    code = (
        "import apps.api.main as m; "
        "routes=[r.path for r in m.app.routes if hasattr(r,'path')]; "
        "print(len(routes))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO,
        capture_output=True, text=True, timeout=180,
    )
    checks["import_main"] = result.returncode == 0
    checks["routes"] = int(result.stdout.strip().splitlines()[-1])
    # 2. Каталоги/константы DOCLOG-6
    code2 = (
        "from apps.api.research_runs import MIGRATION_FILES, MIGRATION_STATEMENTS; "
        "from apps.api.report_snapshot import DOCUMENT_KINDS; "
        "from apps.api.security_audit import AUDIT_ACTIONS; "
        "from apps.api.document_lifecycle import (STATE_DRAFT, STATE_READY_FOR_REVIEW, "
        "STATE_APPROVED, STATE_PUBLISHED, STATE_REJECTED, STATE_RETRACTED, "
        "STATE_SUPERSEDED, LIFECYCLE_EVENTS, _PROTECTED_STATES, "
        "DEFAULT_RETENTION_DRAFT_DAYS, ARCHIVE_BUNDLE_PREFIX); "
        "import json; print(json.dumps({"
        "'migrations': len(MIGRATION_FILES),"
        "'statements': len(MIGRATION_STATEMENTS),"
        "'kinds': sorted(DOCUMENT_KINDS),"
        "'audit_actions': len(AUDIT_ACTIONS),"
        "'states': [STATE_DRAFT, STATE_READY_FOR_REVIEW, STATE_APPROVED, "
        "STATE_PUBLISHED, STATE_REJECTED, STATE_RETRACTED, STATE_SUPERSEDED],"
        "'events': sorted(LIFECYCLE_EVENTS),"
        "'protected': sorted(_PROTECTED_STATES),"
        "'retention_default_days': DEFAULT_RETENTION_DRAFT_DAYS,"
        "'bundle_prefix': ARCHIVE_BUNDLE_PREFIX}))"
    )
    result2 = subprocess.run(
        [sys.executable, "-c", code2], cwd=REPO,
        capture_output=True, text=True, timeout=180,
    )
    checks["catalogs"] = result2.returncode == 0
    if result2.returncode == 0:
        checks.update(json.loads(result2.stdout.strip().splitlines()[-1]))
    # 3. Маршруты /v1/documentation
    code3 = (
        "import apps.api.main as m; "
        "paths=sorted({r.path for r in m.app.routes if hasattr(r,'path') and '/documentation' in r.path}); "
        "import json; print(json.dumps(paths))"
    )
    result3 = subprocess.run(
        [sys.executable, "-c", code3], cwd=REPO,
        capture_output=True, text=True, timeout=180,
    )
    checks["documentation_routes"] = result3.returncode == 0
    if result3.returncode == 0:
        checks["documentation_route_count"] = len(
            json.loads(result3.stdout.strip().splitlines()[-1])
        )
    # 4. Продуктовое дерево чистое (сертификатор продукт не менял)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "apps/", "packages/", "tests/"],
        cwd=REPO, capture_output=True, text=True,
    ).stdout.strip()
    checks["product_tree_clean"] = status == ""
    checks["product_tree_status"] = status[:200]
    ok = (
        checks["import_main"]
        and checks["catalogs"]
        and checks["documentation_routes"]
        and checks["product_tree_clean"]
        and checks["routes"] == 201
        and checks["migrations"] == 12
        and checks["statements"] == 74
        and len(checks["kinds"]) == 11
        and checks["audit_actions"] == 21
        and checks["documentation_route_count"] == 17
    )
    (PROTOCOLS / "build_check.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(checks, ensure_ascii=False, indent=1))
    print("BUILD:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
