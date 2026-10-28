#!/usr/bin/env python3
# scripts/pgv00/check_documents.py
#
# PGV-00 — doc-contract гвард «документация == реестр» (паттерн UPLOAD-DB-9/
# EDU-API-1: расхождение документации и данных роняет проверку).
#
# Проверки:
#   A. spec_passport_graphics_visual.md — целостность постановки: 18 задач
#      (PGV-00…PGV-16 + PGV-CERT) и 24 приёмочных сценария (PGV-AC01…24).
#   B. spec_documentation_logging.md — аддитивные правки PGV-00 в §7/§9/§12/
#      §19/§19.1 (PNG-only, VisualResult/PrintSnapshot, V01/P01/P02,
#      coverage gate, точки изменения).
#   C. config/visual_registry.json — машина-читаемость: схема, уникальность
#      view_id, состав по модулям, честность исключений.
#   D. docs/pgv00_render_site_inventory.md — документ инвентаря согласован
#      с JSON (состав по модулям, классы исключений, пути реестра).
#   E. worklog/worklog11.md — запись Task ID: PGV-00.
#
# Запуск: python3 scripts/pgv00/check_documents.py   (из корня репозитория)

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

EXPECTED_MODULES = {
    "navigator": 16,
    "upload": 12,
    "validation": 12,
    "preprocessing": 20,
    "eda": 18,
    "modeling": 6,
    "forecasting": 8,
    "tasks": 1,
}
EXPECTED_TOTAL = sum(EXPECTED_MODULES.values())
EXPECTED_EXCLUSION_CLASSES = {
    "decorative",
    "ops_admin",
    "controls",
    "interactive_editor",
    "operational_list",
    "placeholder_soon",
}
EXPECTED_STATUSES = {"planned", "legacy_client", "not_mounted"}

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if not ok:
        failures.append(f"{name}{(' — ' + detail) if detail else ''}")


def section(text: str, start: str, end: str) -> str:
    """Срез раздела между заголовками (без зависимостей от номеров строк)."""
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start)) if end else -1
    return text[i : j if j > 0 else len(text)]


def main() -> int:
    # ── A. Постановка: spec_passport_graphics_visual.md ─────────────
    pgv_spec = (REPO / "spec_passport_graphics_visual.md").read_text(encoding="utf-8")
    for task_id in ["PGV-00", *[f"PGV-{i:02d}" for i in range(1, 17)], "PGV-CERT"]:
        check(f"spec_passport_graphics_visual.md: задача {task_id}", task_id in pgv_spec)
    for ac_id in [f"PGV-AC{i:02d}" for i in range(1, 25)]:
        check(f"spec_passport_graphics_visual.md: сценарий {ac_id}", ac_id in pgv_spec)

    # ── B. Родительская спека: аддитивные правки PGV-00 ─────────────
    parent = (REPO / "spec_documentation_logging.md").read_text(encoding="utf-8")
    s7 = section(parent, "## 7. Форматы", "## 8.")
    check("spec_documentation_logging.md §7: PNG-only для новых научных экспортов",
          "PNG-only" in s7 and "PGV-00" in s7)
    check("spec_documentation_logging.md §7: ссылка на реестр render-sites",
          "visualExportRegistry" in s7 and "visual_registry.json" in s7)
    s9 = section(parent, "### 9.2.", "## 10.")
    check("spec_documentation_logging.md §9.2: VisualResult/VisualPrintSnapshot (проект PGV-01/02)",
          "VisualResult" in s9 and "VisualPrintSnapshot" in s9 and "PGV-00" in s9)
    s12 = section(parent, "## 12. UI", "## 13.")
    check("spec_documentation_logging.md §12: аддитивные типы V01/P01/P02 и source picker",
          all(t in s12 for t in ("V01", "P01", "P02", "PGV-00")))
    check("spec_documentation_logging.md §12: D02 не переименовывается (D02 ≠ P01)",
          "D02" in s12 and "P01" in s12)
    s19 = section(parent, "## 19. Порядок реализации", "## 20.")
    check("spec_documentation_logging.md §19: строка PGV-00 в порядке реализации",
          "PGV-00" in s19 and "unknown" in s19.lower())
    s191 = section(parent, "### 19.1.", "## 20.")
    check("spec_documentation_logging.md §19.1: точки изменения PGV-00",
          "visualExportRegistry" in s191 and "visual_registry.json" in s191)

    # ── C. JSON-твин реестра ────────────────────────────────────────
    reg_path = REPO / "config" / "visual_registry.json"
    check("config/visual_registry.json существует", reg_path.exists())
    if reg_path.exists():
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        check("JSON: schema_version", reg.get("schema_version") == "pgv.visual_registry/1")
        check("JSON: generated_from", reg.get("generated_from") == "packages/ui/lib/visualExportRegistry.ts")
        sites: list[dict] = reg.get("sites", [])
        ids = [s.get("view_id", "") for s in sites]
        check("JSON: уникальность view_id", len(ids) == len(set(ids)))
        check(f"JSON: total_sites == {EXPECTED_TOTAL}", reg.get("total_sites") == EXPECTED_TOTAL,
              f"факт {reg.get('total_sites')}")
        modules: dict[str, int] = reg.get("modules", {})
        for m, n in EXPECTED_MODULES.items():
            check(f"JSON: состав модуля {m} == {n}", modules.get(m) == n, f"факт {modules.get(m)}")
        for s in sites:
            vid = s.get("view_id", "?")
            check(f"JSON[{vid}]: обязательные поля", all(s.get(f) for f in (
                "module_id", "stop_id", "render_site", "renderer_kind",
                "source_adapter", "required_refs", "view_params", "applicability",
                "caption_schema", "export_status", "tests")))
            check(f"JSON[{vid}]: caption_schema каноничен",
                  bool(re.match(r"^pgv\.caption/[a-z0-9_.-]+/\d+$", s.get("caption_schema", ""))))
            check(f"JSON[{vid}]: export_status честный", s.get("export_status") in EXPECTED_STATUSES)
        exclusions: list[dict] = reg.get("exclusions", [])
        classes = {e.get("reason_class") for e in exclusions}
        check("JSON: классы исключений полны", EXPECTED_EXCLUSION_CLASSES <= classes, f"факт {sorted(classes)}")
        check("JSON: у каждого исключения непустая причина",
              all(e.get("reason", "").strip() for e in exclusions))
        legacy = [s["view_id"] for s in sites if s.get("export_status") == "legacy_client"]
        check("JSON: legacy_client ровно у прогнозного меню", legacy == ["forecasting.forecast.legacy_png"])
        not_mounted = [s["view_id"] for s in sites if s.get("export_status") == "not_mounted"]
        check("JSON: not_mounted ровно у ResidualDiagnostics", not_mounted == ["modeling.diagnostics.residuals"])

    # ── D. Документ инвентаря ───────────────────────────────────────
    inv_path = REPO / "docs" / "pgv00_render_site_inventory.md"
    check("docs/pgv00_render_site_inventory.md существует", inv_path.exists())
    if inv_path.exists():
        inv = inv_path.read_text(encoding="utf-8")
        check("инвентарь: ссылка на реестр TS", "packages/ui/lib/visualExportRegistry.ts" in inv)
        check("инвентарь: ссылка на JSON-твин", "config/visual_registry.json" in inv)
        check("инвентарь: coverage-оракул упомянут",
              "visualExportRegistry.coverage.test.ts" in inv)
        for m, n in EXPECTED_MODULES.items():
            check(f"инвентарь: состав {m}={n} согласован с JSON", f"{m}" in inv and str(n) in inv)
        check("инвентарь: общий denominator", str(EXPECTED_TOTAL) in inv)
        for cls in sorted(EXPECTED_EXCLUSION_CLASSES):
            check(f"инвентарь: класс исключений {cls} описан", cls in inv)

    # ── E. Worklog ──────────────────────────────────────────────────
    worklog = (REPO / "worklog" / "worklog11.md").read_text(encoding="utf-8")
    check("worklog11.md: запись Task ID: PGV-00", "Task ID: PGV-00" in worklog)

    # ── Итог ────────────────────────────────────────────────────────
    print(f"PGV-00 doc-contract: {checks - len(failures)}/{checks} проверок пройдено")
    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("GREEN: документация согласована с реестром render-sites")
    return 0


if __name__ == "__main__":
    sys.exit(main())
