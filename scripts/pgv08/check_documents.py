#!/usr/bin/env python3
"""
PGV-08 — doc-contract гвард поставки (прецедент scripts/pgv07/check_documents.py).

Проверяет: постановку (строка §13 PGV-08, критерий, зависимость PGV-07),
проектную спеку (строка PGV-08, приёмочные сценарии), состав поставки
(все файлы существуют), связность документа поставки и worklog-записи
(Task ID, состав файлов, счётчики тестов). Гвард читает только
собственные исходники/git HEAD и пишет JSON в stdout.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT: list[dict] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    OUT.append({"check": name, "ok": bool(condition), "detail": detail})


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


spec = read(REPO / "spec_passport_graphics_visual.md")
doc = read(REPO / "docs" / "pgv08_render_container.md")
worklog = read(REPO / "worklog" / "worklog11.md")

# ── 1. Постановка в спеке ───────────────────────────────────────────
check("spec_pgv08_row", "| PGV-08 | PGV-07 | Sandboxed renderer container |" in spec, "строка §13")
check(
    "spec_criterion",
    "Final image smoke кириллица/IH/A4, no-network/non-root/hard timeout" in spec,
    "критерий готовности",
)
check("spec_dependency_pgv07", "| PGV-07 | PGV-01 | Shared pure print layout |" in spec, "зависимость PGV-07 реализована")

# ── 2. Приёмочные сценарии, затрагиваемые поставкой ─────────────────
for ac in ("PGV-AC16", "PGV-AC17", "PGV-AC19", "PGV-AC20", "PGV-AC23"):
    check(f"spec_{ac}", f"| {ac} |" in spec, "сценарий присутствует в §14")
    check(f"doc_{ac}", ac in doc, "сценарий отображён в документе поставки")

# ── 3. Состав поставки: файлы существуют ────────────────────────────
delivery_files = [
    "apps/print-renderer/package.json",
    "apps/print-renderer/tsconfig.build.json",
    "apps/print-renderer/src/rendererCore.tsx",
    "apps/print-renderer/src/renderWorker.ts",
    "apps/print-renderer/src/server.ts",
    "apps/print-renderer/src/smokeScenarios.ts",
    "apps/print-renderer/src/smoke.ts",
    "apps/print-renderer/src/rendererCore.test.ts",
    "apps/print-renderer/build/Dockerfile",
    "apps/print-renderer/build/deployment/docker-compose.yml",
    "apps/print-renderer/build/deployment/README.md",
    "tests/api/test_pgv08_render_container.py",
    "scripts/pgv08/verify_local.py",
    "scripts/pgv08/check_documents.py",
    "docs/pgv08_render_container.md",
    "scripts/pgv08/protocols/red_jest.txt",
    "scripts/pgv08/protocols/red_python.txt",
    "scripts/pgv08/protocols/smoke_run.json",
    "scripts/pgv08/protocols/local_verification.json",
]
for rel in delivery_files:
    check(f"file::{rel}", (REPO / rel).exists(), "файл поставки существует")

# ── 4. Связность документа и worklog ────────────────────────────────
check("doc_task_id", "PGV-08" in doc and "Sandboxed renderer container" in doc, "документ о задаче PGV-08")
check("worklog_entry", "Task ID: PGV-08" in worklog, "worklog-запись присутствует")
check("worklog_base", "c3dab21" in worklog, "база зафиксирована")
for marker in ("rendererCore", "renderWorker", "smokeScenarios", "docker-compose.yml", "verify_local.py"):
    check(f"worklog_mentions::{marker}", marker in worklog, "состав файлов упомянут в worklog")
check("doc_test_counts", "35/35" in doc and "22/22" in doc and "20/20" in doc, "счётчики corps в документе")
check("doc_honest_docker_boundary", "Docker-демона в среде сессии нет" in doc, "честная граница R2 зафиксирована")

# ── 5. Продуктовые пины согласованы ─────────────────────────────────
pkg = read(REPO / "apps" / "print-renderer" / "package.json")
core = read(REPO / "apps" / "print-renderer" / "src" / "rendererCore.tsx")
compose = read(REPO / "apps" / "print-renderer" / "build" / "deployment" / "docker-compose.yml")
dockerfile = read(REPO / "apps" / "print-renderer" / "build" / "Dockerfile")
check("pin_playwright", '"playwright-core": "1.57.0"' in pkg and "playwright@1.57.0" in dockerfile, "пин playwright-core 1.57.0 согласован")
check("pin_timeout", "render_timeout_s" in core and "HARD_TIMEOUT_S=60" in compose, "hard timeout 60 == PGV-01")
check("pin_port", "8907" in core and "8907" in compose and "8907" in dockerfile, "порт 8907 согласован")
check("pin_ppi", "11811" in core and "11811" in dockerfile or "chromium-1200" in dockerfile, "пины ppi/браузера")
check("sandbox_none", 'network_mode: "none"' in compose and "network_mode: none" in read(REPO / "apps" / "print-renderer" / "build" / "deployment" / "README.md"), "no-network согласован")

head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
check("head_recorded", len(head) >= 7, f"HEAD={head}")

passed = sum(1 for item in OUT if item["ok"])
print(json.dumps({"guard": "pgv08", "head": head, "passed": passed, "total": len(OUT), "checks": OUT}, ensure_ascii=False, indent=1))
raise SystemExit(0 if passed == len(OUT) else 1)
