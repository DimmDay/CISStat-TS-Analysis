#!/usr/bin/env python3
"""DOCLOG-5-CERT: build-проверка целевой базы (ebbfa87)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/my-project/CISStat-TS-Analysis")
PROTOCOLS = REPO / "scripts" / "doclog5cert" / "protocols"


def main() -> int:
    checks: dict[str, object] = {}
    # 1. Импорт приложения
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
    # 2. Каталоги/константы DOCLOG-5
    code2 = (
        "from apps.api.research_runs import MIGRATION_FILES, MIGRATION_STATEMENTS; "
        "from apps.api.document_renditions import RENDITION_FORMATS, HEAVY_RENDITION_FORMATS; "
        "from apps.api.document_jobs import MAX_JOB_ATTEMPTS, MAX_OPEN_JOBS_PER_TENANT; "
        "from apps.api.document_render_worker import DEFAULT_LEASE_SECONDS, DEFAULT_MAX_ATTEMPTS; "
        "import json; print(json.dumps({"
        "'migrations': len(MIGRATION_FILES),"
        "'statements': len(MIGRATION_STATEMENTS),"
        "'formats': sorted(RENDITION_FORMATS),"
        "'heavy': sorted(HEAVY_RENDITION_FORMATS),"
        "'max_job_attempts': MAX_JOB_ATTEMPTS,"
        "'max_open_per_tenant': MAX_OPEN_JOBS_PER_TENANT,"
        "'lease_seconds': DEFAULT_LEASE_SECONDS,"
        "'worker_max_attempts': DEFAULT_MAX_ATTEMPTS}))"
    )
    result2 = subprocess.run(
        [sys.executable, "-c", code2], cwd=REPO,
        capture_output=True, text=True, timeout=180,
    )
    checks["catalogs"] = result2.returncode == 0
    if result2.returncode == 0:
        checks.update(json.loads(result2.stdout.strip().splitlines()[-1]))
    # 3. /health/ops worker-блок
    code3 = (
        "from fastapi.testclient import TestClient; import apps.api.main as m; "
        "c=TestClient(m.app); import json; "
        "print(json.dumps(c.get('/health/ops').json()['document_render_worker']))"
    )
    result3 = subprocess.run(
        [sys.executable, "-c", code3], cwd=REPO,
        capture_output=True, text=True, timeout=180,
    )
    checks["health_worker"] = result3.returncode == 0
    if result3.returncode == 0:
        block = json.loads(result3.stdout.strip().splitlines()[-1])
        checks["worker_config"] = {
            k: block[k] for k in (
                "enabled", "interval_seconds", "batch_size",
                "per_tenant_limit", "render_timeout_seconds",
            )
        }
    # 4. Продуктовое дерево чистое (cert не меняет продукт)
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "apps/", "packages/", "tests/"],
        cwd=REPO, capture_output=True, text=True,
    ).stdout.strip()
    checks["product_tree_clean"] = status == ""
    checks["product_tree_status"] = status[:200]
    ok = (
        checks["import_main"]
        and checks["catalogs"]
        and checks["health_worker"]
        and checks["product_tree_clean"]
        and checks["routes"] == 192
        and checks["migrations"] == 11
        and checks["statements"] == 67
        and len(checks["formats"]) == 11
        and len(checks["heavy"]) == 6
    )
    (PROTOCOLS / "build_check.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(checks, ensure_ascii=False, indent=1))
    print("BUILD:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
