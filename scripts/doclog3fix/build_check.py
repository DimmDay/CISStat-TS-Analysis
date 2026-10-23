# scripts/doclog3fix/build_check.py
"""DOCLOG-3-FIX: проверка сборки пост-фикса.

Паритеты с актом DOCLOG-3-CERT: импорт apps.api.main, OpenAPI 171
путь (новых HTTP-поверхностей нет), каталог миграций 9 файлов /
53 statement, AUDIT_ACTIONS=20, схемы doclog.telemetry/1 +
doclog.security_audit/1, порядок middleware-стека, новый pgm-гвард
и N4-пины в репо-сюите (111 тестов).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ.setdefault("CISSTAT_DATA_DIR", tempfile.mkdtemp(prefix="d3fix-build-"))


def main() -> int:
    from apps.api.main import app
    from apps.api import research_runs, security_audit, telemetry

    openapi = app.openapi()
    paths = len(openapi.get("paths", {}))
    ops = sum(
        len(methods) for methods in openapi.get("paths", {}).values()
    )
    print(f"OpenAPI: {paths} путей / {ops} операций (ожидание 171/179)")

    kinds = [mw.cls.__name__ for mw in app.user_middleware]
    print("middleware:", kinds)

    print("MIGRATION_FILES:", len(research_runs.MIGRATION_FILES),
          "MIGRATION_STATEMENTS:", len(research_runs.MIGRATION_STATEMENTS))
    print("AUDIT_ACTIONS:", len(security_audit.AUDIT_ACTIONS))
    print("telemetry schema:", telemetry.SCHEMA_VERSION,
          "| audit schema:", security_audit.SCHEMA_VERSION)

    ok = (
        paths == 171 and ops == 179
        and kinds == [
            "CORSMiddleware", "TelemetryContextMiddleware",
            "TraceHookMiddleware",
        ]
        and len(research_runs.MIGRATION_FILES) == 9
        and len(research_runs.MIGRATION_STATEMENTS) == 53
        and len(security_audit.AUDIT_ACTIONS) == 20
        and telemetry.SCHEMA_VERSION == "doclog.telemetry/1"
        and security_audit.SCHEMA_VERSION == "doclog.security_audit/1"
    )
    print("СБОРКА:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
