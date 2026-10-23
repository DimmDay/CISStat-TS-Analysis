# scripts/doclog3cert/red_repro.py
"""DOCLOG-3-CERT: RED-протокол на родителе fa8c949 (git-worktree).

Доказательство честности оракульного корпуса: на родителе поставки
контур DOCLOG-3 ОТСУТСТВУЕТ ЦЕЛИКОМ -- все оракулы красны строго на
отсутствующем контуре (ImportError), статические факты фиксируют
отсутствие файлов/каталогов/полей.

Запуск: python scripts/doclog3cert/red_repro.py <путь-к-worktree-родителя>
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

STATIC_FACTS = [
    # (описание, относительный путь/проверка)
    ("telemetry.py отсутствует", "apps/api/telemetry.py", False),
    ("security_audit.py отсутствует", "apps/api/security_audit.py", False),
    ("тест поставки отсутствует", "tests/api/test_doclog3_telemetry_audit.py", False),
    ("дизайн-док поставки отсутствует", "docs/doclog3_telemetry_audit.md", False),
    ("миграция 0009 отсутствует",
     "apps/api/migrations/0009_doclog3_telemetry_audit.sql", False),
]
STRING_FACTS = [
    ("MIGRATION_STATEMENTS_0009 отсутствует в research_runs",
     "apps/api/research_runs.py", "MIGRATION_STATEMENTS_0009", False),
    ("COMPONENT_TELEMETRY отсутствует в storage_diagnostics",
     "apps/api/storage_diagnostics.py", "COMPONENT_TELEMETRY", False),
    ("TelemetryContextMiddleware не в main",
     "apps/api/main.py", "TelemetryContextMiddleware", False),
    ("_audit_authn_denied не в auth (401-аудит)",
     "apps/api/auth.py", "_audit_authn_denied", False),
    ("_audit_access_decision не в identity",
     "apps/api/identity.py", "_audit_access_decision", False),
    ("build_telemetry_health отсутствует",
     "apps/api/storage_diagnostics.py", "build_telemetry_health", False),
    ("build_audit_health отсутствует",
     "apps/api/storage_diagnostics.py", "build_audit_health", False),
    ("api.startup lifecycle не эммитится",
     "apps/api/main.py", "api.startup", False),
]


def main(worktree: str) -> int:
    root = Path(worktree)
    results = []
    all_red = True

    for desc, rel, expect_exists in STATIC_FACTS:
        path = root / rel
        exists = path.exists()
        ok = (exists == expect_exists)
        # expect_exists=False: факт RED = файл НЕ существует
        results.append({"fact": desc, "exists": exists, "red": ok})
        all_red &= ok

    for desc, rel, needle, _ in STRING_FACTS:
        path = root / rel
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        found = needle in content
        # факт RED = строка НЕ найдена (контур отсутствует)
        results.append({"fact": desc, "found": found, "red": not found})
        all_red &= not found

    report = {"worktree": str(root), "static_facts": results,
              "all_static_red": all_red}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    Path(__file__).parent.joinpath("red_static_facts.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0 if all_red else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
