#!/usr/bin/env python3
# scripts/pgv01/check_documents.py
#
# PGV-01 — doc-contract гвард «документация == print-схема» (паттерн
# UPLOAD-DB-9/EDU-API-1/PGV-00: расхождение документации и данных роняет
# проверку).
#
# Проверки:
#   A. spec_passport_graphics_visual.md — постановка PGV-01: строка задачи
#      (зависимость PGV-00, точки «shared schemas, registry», критерий
#      «Result/version/date/units/sampling обязательны по applicability,
#      параметры trusted»), целостность 18 задач + 24 AC.
#   B. spec_documentation_logging.md — аддитивные правки PGV-01 в §19/§19.1
#      (print-схемы, источник истины, твин, Python-зеркало).
#   C. config/print_schema.json — машина-читаемость: версии схем, каталог
#      профилей §7 (точные пиксели A4), лимиты, правила обязательности,
#      контракт кодов нарушений.
#   D. config/visual_registry.json — уточнение PGV-01 не повредило PGV-00
#      (89 sites, состав модулей, data_revision в уточнённых записях).
#   E. Файлы поставки существуют.
#   F. docs/pgv01_print_schema.md — документ согласован с поставкой.
#   G. worklog/worklog11.md — запись Task ID: PGV-01.
#
# Запуск: python3 scripts/pgv01/check_documents.py   (из корня репозитория)

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
REFINED_RECORDS = ("upload.structure.schema", "forecasting.accuracy.metrics")

EXPECTED_PROFILES = ["figure-landscape", "a4-portrait", "a4-landscape"]
EXPECTED_A4_PIXELS = {"a4-portrait": (2480, 3508), "a4-landscape": (3508, 2480)}
EXPECTED_LIMITS = {
    "max_megapixels_per_page": 12,
    "max_pages_per_set": 20,
    "max_output_bytes": 52428800,
    "render_timeout_s": 60,
    "concurrency_per_tenant": 1,
    "concurrency_global": 2,
}
EXPECTED_MANDATORY_REFS = {
    "demo": ["demo_dataset_id"],
    "research": ["context_id", "data_revision"],
    "passport": ["context_id", "snapshot_id", "data_revision", "schema_version"],
    "comparison": ["research_run_id", "comparison_id"],
}
KEY_VIOLATION_CODES = (
    "missing_required_ref",
    "missing_result_ref",
    "missing_date",
    "missing_units",
    "missing_sampling",
    "missing_point_cap",
    "untrusted_parameter_origin",
    "selection_not_allowlisted",
    "panel_mixing",
    "missing_checkpoint_confirmation",
    "missing_renderer_reason",
    "raw_data_included_forbidden",
    "schema_version_mismatch",
)

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if not ok:
        failures.append(f"{name}{(' — ' + detail) if detail else ''}")


def section(text: str, start: str, end: str) -> str:
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
    row = section(pgv_spec, "| PGV-01 |", "\n")
    check("spec PGV-01: строка задачи присутствует", row.startswith("| PGV-01 |"))
    check("spec PGV-01: зависимость PGV-00", "PGV-00" in row)
    check("spec PGV-01: точки изменения «shared schemas, registry»",
          "shared schemas" in row and "registry" in row)
    check("spec PGV-01: критерий Result/version/date/units/sampling",
          "Result/version/date/units/sampling" in row)
    check("spec PGV-01: критерий параметры trusted", "параметры trusted" in row)

    # ── B. Родительская спека: аддитивные правки PGV-01 ─────────────
    parent = (REPO / "spec_documentation_logging.md").read_text(encoding="utf-8")
    s19 = section(parent, "## 19. Порядок реализации", "## 20.")
    check("spec_documentation_logging.md §19: строка PGV-01 в порядке реализации",
          "| PGV-01 —" in s19 and "print-схемы" in s19)
    check("spec_documentation_logging.md §19: строка PGV-00 сохранена",
          "| PGV-00 —" in s19)
    s191 = section(parent, "### 19.1.", "## 20.")
    check("spec_documentation_logging.md §19.1: точка print-схем PGV-01",
          "printSchema" in s191 and "print_schema.json" in s191)
    check("spec_documentation_logging.md §19.1: Python-зеркало упомянуто",
          "apps/api/print_schema.py" in s191)
    check("spec_documentation_logging.md §19.1: точка PGV-00 (реестр) сохранена",
          "visualExportRegistry" in s191 and "visual_registry.json" in s191)

    # ── C. JSON-твин print-схем ─────────────────────────────────────
    schema_path = REPO / "config" / "print_schema.json"
    check("config/print_schema.json существует", schema_path.exists())
    if schema_path.exists():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        check("твин: schema_version", schema.get("schema_version") == "pgv.print_schema/1")
        check("твин: generated_from",
              schema.get("generated_from") == "packages/ui/print/printSchema.ts")
        check("твин: pgv_task", schema.get("pgv_task") == "PGV-01")
        versions = schema.get("schema_versions", {})
        check("твин: версии схем закреплены",
              versions.get("visual_result") == "pgv.visual_result/1"
              and versions.get("visual_print_snapshot") == "pgv.visual_print_snapshot/1"
              and versions.get("print_manifest") == "pgv.print_manifest/1"
              and versions.get("profiles") == "pgv.print_profiles/1")
        profiles = schema.get("profiles", [])
        check("твин: каталог профилей §7",
              [p.get("id") for p in profiles] == EXPECTED_PROFILES)
        check("твин: все профили 300 ppi", all(p.get("ppi") == 300 for p in profiles))
        for profile in profiles:
            pid = profile.get("id", "?")
            px = EXPECTED_A4_PIXELS.get(pid)
            if px:
                check(f"твин: пиксели {pid} == {px[0]}×{px[1]}",
                      (profile.get("width_px"), profile.get("height_px")) == px)
            w_mm = profile.get("width_mm", 0) / 25.4 * 300
            h_mm = profile.get("height_mm", 0) / 25.4 * 300
            check(f"твин: {pid} px⇄мм согласованы (PGV-AC16)",
                  abs(profile.get("width_px", 0) - w_mm) <= 1
                  and abs(profile.get("height_px", 0) - h_mm) <= 1)
        check("твин: лимиты §7", schema.get("limits") == EXPECTED_LIMITS)
        rules = schema.get("rules", {})
        check("твин: mandatory_refs_by_scope",
              {k: list(v) for k, v in rules.get("mandatory_refs_by_scope", {}).items()}
              == EXPECTED_MANDATORY_REFS)
        sampling = rules.get("sampling", {})
        check("твин: sampling exempt html_cards",
              sampling.get("exempt_renderer_kinds") == ["html_cards"])
        check("твин: sampling point-cap режимы",
              set(sampling.get("modes_requiring_point_cap", []))
              == {"downsampled", "windowed", "truncated"})
        trusted = rules.get("trusted_parameters", {})
        check("твин: trusted origins",
              list(trusted.get("origins", [])) == ["producer_freeze", "producer_first_export"])
        check("твин: allowlist из view_params реестра",
              "view_params" in trusted.get("selection_allowlist_source", ""))
        check("твин: raw_data_included=false пин",
              rules.get("sensitive", {}).get("raw_data_included") is False)
        codes = schema.get("violation_codes", [])
        for code in KEY_VIOLATION_CODES:
            check(f"твин: код нарушения {code} в контракте", code in codes)

    # ── D. Реестр PGV-00 после уточнения ────────────────────────────
    reg_path = REPO / "config" / "visual_registry.json"
    check("config/visual_registry.json существует", reg_path.exists())
    if reg_path.exists():
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        check("реестр: schema_version PGV-00", reg.get("schema_version") == "pgv.visual_registry/1")
        sites: list[dict] = reg.get("sites", [])
        check(f"реестр: total_sites == {EXPECTED_TOTAL}", reg.get("total_sites") == EXPECTED_TOTAL)
        modules: dict[str, int] = reg.get("modules", {})
        for m, n in EXPECTED_MODULES.items():
            check(f"реестр: состав модуля {m} == {n}", modules.get(m) == n)
        by_id = {s.get("view_id"): s for s in sites}
        for view_id in REFINED_RECORDS:
            site = by_id.get(view_id)
            check(f"реестр: {view_id} существует", site is not None)
            if site:
                check(f"реестр: {view_id} несёт data_revision (уточнение PGV-01)",
                      "data_revision" in site.get("required_refs", []))

    # ── E. Файлы поставки ───────────────────────────────────────────
    delivery_files = (
        "packages/ui/print/printSchema.ts",
        "packages/ui/print/printSchema.test.ts",
        "config/print_schema.json",
        "apps/api/print_schema.py",
        "tests/api/test_pgv01_print_schema.py",
        "scripts/pgv01/export_print_schema.ts",
        "scripts/pgv01/check_documents.py",
        "docs/pgv01_print_schema.md",
    )
    for rel in delivery_files:
        check(f"файл поставки существует: {rel}", (REPO / rel).exists())

    # ── F. Документ поставки ────────────────────────────────────────
    doc_path = REPO / "docs" / "pgv01_print_schema.md"
    check("docs/pgv01_print_schema.md существует", doc_path.exists())
    if doc_path.exists():
        doc = doc_path.read_text(encoding="utf-8")
        for token in (
            "packages/ui/print/printSchema.ts",
            "config/print_schema.json",
            "apps/api/print_schema.py",
            "tests/api/test_pgv01_print_schema.py",
            "pgv.visual_print_snapshot/1",
            "figure-landscape",
            "2480",
            "3508",
            "data_revision",
            "PGV-AC16",
            "PGV-AC21",
        ):
            check(f"документ: упоминание {token}", token in doc)

    # ── G. Worklog ──────────────────────────────────────────────────
    worklog = (REPO / "worklog" / "worklog11.md").read_text(encoding="utf-8")
    check("worklog11.md: запись Task ID: PGV-01", "Task ID: PGV-01" in worklog)
    check("worklog11.md: запись Task ID: PGV-00 сохранена", "Task ID: PGV-00" in worklog)

    # ── Итог ────────────────────────────────────────────────────────
    print(f"PGV-01 doc-contract: {checks - len(failures)}/{checks} проверок пройдено")
    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("GREEN: документация согласована с print-схемами PGV-01")
    return 0


if __name__ == "__main__":
    sys.exit(main())
