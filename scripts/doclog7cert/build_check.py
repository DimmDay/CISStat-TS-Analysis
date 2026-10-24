#!/usr/bin/env python3
"""DOCLOG-7-CERT: проверка сборки (build check, прецедент DOCLOG-6-CERT).

Импорт apps.api.main, каталоги маршрутов/миграций/констант, чистота
продуктового дерева. Результат: protocols/build_check.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/z/CISStat-TS-Analysis")
PROTOCOLS = REPO / "scripts" / "doclog7cert" / "protocols"


def main() -> int:
    checks: dict[str, object] = {}

    # 1. Импорт приложения и счётчик маршрутов
    code = (
        "import apps.api.main as m; "
        "logs = {r.path for r in m.app.routes if getattr(r, 'path', '').startswith('/v1/logs')}; "
        "print(len(m.app.routes), len(logs))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True
    )
    ok = result.returncode == 0
    total, logs_routes = (None, None)
    if ok:
        total_s, logs_s = result.stdout.strip().splitlines()[-1].split()
        total, logs_routes = int(total_s), int(logs_s)
    checks["import_main"] = {
        "ok": ok, "routes_total": total, "routes_logs": logs_routes,
        "expected_routes_total": 209, "expected_routes_logs": 7,
    }

    # 2. Каталог миграций 13/78 и константы DOCLOG-7
    code2 = (
        "from apps.api.research_runs import MIGRATION_FILES, MIGRATION_STATEMENTS; "
        "from apps.api import admin_logs; "
        "from apps.api.security_audit import AUDIT_ACTIONS; "
        "print(len(MIGRATION_FILES), len(MIGRATION_STATEMENTS), "
        "len(AUDIT_ACTIONS), sorted(admin_logs.GRANT_SCOPES), "
        "admin_logs.GRANT_TTL_MAX_HOURS, admin_logs.WINDOW_MAX_DAYS, "
        "admin_logs.QUERY_LIMIT_MAX, admin_logs.EXPORT_LIMIT)"
    )
    result2 = subprocess.run(
        [sys.executable, "-c", code2], cwd=REPO, capture_output=True, text=True
    )
    ok2 = result2.returncode == 0
    if ok2:
        parts = result2.stdout.strip().splitlines()[-1]
        checks["catalogs"] = {
            "ok": True, "raw": parts,
            "expected": "13 files / 78 statements / 21 audit actions / "
                        "GRANT_SCOPES [audit.read, logs.export, logs.read] / "
                        "TTL 168 / window 31 / limit 200 / export 2000",
        }
    else:
        checks["catalogs"] = {"ok": False, "stderr": result2.stderr[-300:]}

    # 3. Чистота продуктового дерева (md5 целей == HEAD)
    targets = ["apps/api/admin_logs.py", "apps/api/routers/logs.py",
               "apps/api/document_jobs.py", "apps/api/security_audit.py",
               "apps/api/telemetry.py", "apps/api/main.py",
               "apps/api/research_runs.py"]
    import hashlib
    clean = True
    for t in targets:
        current = hashlib.md5((REPO / t).read_bytes()).hexdigest()
        head = subprocess.run(["git", "show", f"HEAD:{t}"], cwd=REPO,
                              capture_output=True).stdout
        if hashlib.md5(head).hexdigest() != current:
            clean = False
    checks["product_tree_clean"] = {"ok": clean, "targets": targets}

    verdict = "OK" if all(
        v.get("ok") for v in checks.values() if isinstance(v, dict)
    ) else "FAIL"
    checks["verdict"] = verdict
    PROTOCOLS.mkdir(parents=True, exist_ok=True)
    (PROTOCOLS / "build_check.json").write_text(
        json.dumps(checks, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False, indent=1))
    return 0 if verdict == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
