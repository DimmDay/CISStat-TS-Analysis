# scripts/pgv01cert/test_p1cert_oracle_static.py
#
# PGV-01-CERT — Класс A: статические оракулы на своих данных (namespace
# p1cert-*). НЕ импортируют repo-гварды/тесты: каждая проверка —
# независимая транскрипция контракта из spec_passport_graphics_visual.md
# §6/§7/§13/§14 и spec_documentation_logging.md §19/§19.1.
#
# Анти-вакуус встроен: транскрипция кодов нарушений сверяется с твином,
# реестр кейсов обязан покрывать каждую семью кодов и содержать F/OO-кейсы.

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
sys.path.insert(0, str(CERT_DIR))

import pytest  # noqa: E402

import p1cases  # noqa: E402

PGV_SPEC = REPO / "spec_passport_graphics_visual.md"
PARENT_SPEC = REPO / "spec_documentation_logging.md"
TWIN_PATH = REPO / "config" / "print_schema.json"
REGISTRY_PATH = REPO / "config" / "visual_registry.json"
DOC_PATH = REPO / "docs" / "pgv01_print_schema.md"
WORKLOG_PATH = REPO / "worklog" / "worklog11.md"

# ── Собственная транскрипция контракта (анти-вакуус: сверяется с твином) ──
EXPECTED_VIOLATION_CODES = [
    "ambiguous_date",
    "ambiguous_source_hash",
    "ambiguous_unit",
    "data_included_forbidden",
    "duplicate_filename",
    "empty_sections",
    "invalid_profile",
    "invalid_section_kind",
    "missing_axes",
    "missing_checkpoint_confirmation",
    "missing_data_version",
    "missing_date",
    "missing_digest",
    "missing_expected_context",
    "missing_field",
    "missing_heatmap_scale",
    "missing_page_hash",
    "missing_point_cap",
    "missing_renderer_reason",
    "missing_required_ref",
    "missing_result_ref",
    "missing_sampling",
    "missing_sampling_reason",
    "missing_sampling_mode",
    "missing_source_hash",
    "missing_table_headings",
    "missing_title",
    "missing_units",
    "mixed_needs_multiple_sections",
    "page_order_gap",
    "panel_mixing",
    "raw_data_included_forbidden",
    "schema_version_mismatch",
    "section_kind_mismatch",
    "selection_not_allowlisted",
    "theme_not_light_print",
    "untrusted_parameter_origin",
]

EXPECTED_LIMITS = {
    "max_megapixels_per_page": 12,
    "max_pages_per_set": 20,
    "max_output_bytes": 52428800,
    "render_timeout_s": 60,
    "concurrency_per_tenant": 1,
    "concurrency_global": 2,
}

EXPECTED_A4 = {"a4-portrait": (2480, 3508), "a4-landscape": (3508, 2480)}


@pytest.fixture(scope="module")
def twin() -> dict:
    return json.loads(TWIN_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


# ── 1. Постановка: проектная спека ───────────────────────────────


def test_spec_tasks_and_scenarios_intact():
    text = PGV_SPEC.read_text(encoding="utf-8")
    for task_id in ["PGV-00", *[f"PGV-{i:02d}" for i in range(1, 17)], "PGV-CERT"]:
        assert task_id in text, task_id
    for ac_id in [f"PGV-AC{i:02d}" for i in range(1, 25)]:
        assert ac_id in text, ac_id


def test_spec_pgv01_row_criterion_and_dependency():
    text = PGV_SPEC.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| PGV-01 |"))
    assert "PGV-00" in row, "зависимость PGV-00"
    assert "shared schemas" in row and "registry" in row
    assert "Result/version/date/units/sampling" in row
    assert "параметры trusted" in row


def test_spec_sections_6_7_tokens():
    text = PGV_SPEC.read_text(encoding="utf-8")
    for token in [
        "VisualResult/1",
        "VisualPrintSnapshot/1",
        "2480×3508",
        "12 MP/page",
        "20 страниц",
        "50 MiB",
        "timeout 60 s",
        "concurrency tenant=1/global=2",
        "pHYs",
    ]:
        assert token in text, token


def test_parent_spec_pgv01_edits():
    text = PARENT_SPEC.read_text(encoding="utf-8")
    s19 = text.split("## 19. Порядок реализации", 1)[1].split("## 20.", 1)[0]
    assert "| PGV-01 —" in s19 and "print-схемы" in s19
    assert "| PGV-00 —" in s19
    s191 = text.split("### 19.1.", 1)[1].split("## 20.", 1)[0]
    assert "printSchema" in s191 and "print_schema.json" in s191
    assert "apps/api/print_schema.py" in s191


# ── 2. JSON-твин: собственная проверка целостности ───────────────


def test_twin_versions_pinned(twin):
    assert twin["schema_version"] == "pgv.print_schema/1"
    assert twin["generated_from"] == "packages/ui/print/printSchema.ts"
    assert twin["pgv_task"] == "PGV-01"
    assert twin["schema_versions"] == {
        "document": "pgv.print_schema/1",
        "visual_result": "pgv.visual_result/1",
        "visual_print_snapshot": "pgv.visual_print_snapshot/1",
        "print_manifest": "pgv.print_manifest/1",
        "profiles": "pgv.print_profiles/1",
    }


def test_twin_violation_codes_equal_own_transcription(twin):
    """Анти-вакуус: транскрипция сертификатора == контракт твина (37 кодов)."""
    assert len(twin["violation_codes"]) == 37
    assert sorted(twin["violation_codes"]) == sorted(EXPECTED_VIOLATION_CODES)


def test_twin_profiles_catalog_and_math(twin):
    profiles = twin["profiles"]
    assert [p["id"] for p in profiles] == ["figure-landscape", "a4-portrait", "a4-landscape"]
    assert twin["default_profile_id"] == "figure-landscape"
    for profile in profiles:
        assert profile["ppi"] == 300
        width_px = profile["width_mm"] / 25.4 * profile["ppi"]
        height_px = profile["height_mm"] / 25.4 * profile["ppi"]
        assert abs(profile["width_px"] - width_px) <= 1, profile["id"]
        assert abs(profile["height_px"] - height_px) <= 1, profile["id"]
        if profile["id"] in EXPECTED_A4:
            assert (profile["width_px"], profile["height_px"]) == EXPECTED_A4[profile["id"]]
        ratio_px = profile["width_px"] / profile["height_px"]
        ratio_mm = profile["width_mm"] / profile["height_mm"]
        assert math.isclose(ratio_px, ratio_mm, rel_tol=0.01), profile["id"]


def test_twin_limits_pinned(twin):
    assert twin["limits"] == EXPECTED_LIMITS


def test_twin_rules_pinned(twin):
    rules = twin["rules"]
    assert rules["mandatory_refs_by_scope"] == {
        "demo": ["demo_dataset_id"],
        "research": ["context_id", "data_revision"],
        "passport": ["context_id", "snapshot_id", "data_revision", "schema_version"],
        "comparison": ["research_run_id", "comparison_id"],
    }
    assert rules["sampling"]["exempt_renderer_kinds"] == ["html_cards"]
    assert set(rules["sampling"]["modes_requiring_point_cap"]) == {"downsampled", "windowed", "truncated"}
    assert rules["trusted_parameters"]["origins"] == ["producer_freeze", "producer_first_export"]
    assert "view_params" in rules["trusted_parameters"]["selection_allowlist_source"]
    assert rules["sensitive"]["raw_data_included"] is False
    assert rules["section_composition"]["mixed_minimum_sections"] == 2
    assert rules["units"]["legacy_unknown_reason"] == "legacy_unknown"


def test_twin_section_requirements_cover_all_kinds(twin):
    requirements = twin["section_requirements"]
    assert set(requirements) == {"recharts_svg", "html_table", "html_heatmap", "html_cards"}
    assert "обязательны" in requirements["recharts_svg"]["axes"]
    assert "обязательны" in requirements["html_table"]["table_headings"]
    assert "обязательна" in requirements["html_heatmap"]["heatmap_scale"]


# ── 3. Реестр PGV-00 ↔ твин (собственный скан) ───────────────────


def scope_of(site: dict) -> str:
    refs = set(site["required_refs"])
    if "demo_dataset_id" in refs:
        return "demo"
    if "comparison_id" in refs:
        return "comparison"
    if "snapshot_id" in refs or site.get("stop_id") == "passport":
        return "passport"
    return "research"


def test_registry_denominator_and_modules(registry):
    assert registry["schema_version"] == "pgv.visual_registry/1"
    assert registry["total_sites"] == 93 == len(registry["sites"])
    assert registry["modules"] == {
        "navigator": 16,
        "upload": 12,
        "validation": 12,
        "preprocessing": 20,
        "eda": 18,
        "modeling": 6,
        "forecasting": 8,
        "tasks": 1,
    }


def test_registry_scope_distribution_matches_twin_scope_map(registry, twin):
    scopes = {}
    for site in registry["sites"]:
        scopes.setdefault(scope_of(site), 0)
        scopes[scope_of(site)] += 1
    # Пин распределения на сертифицируемом дереве: demo 16 / research 68 /
    # passport 8 / comparison 1 (выводится моей реализацией scope-правил).
    assert scopes == {"demo": 16, "research": 68, "passport": 8, "comparison": 1}
    assert set(twin["rules"]["mandatory_refs_by_scope"]) == {"demo", "research", "passport", "comparison"}


def test_registry_research_sites_carry_version_refs(registry, twin):
    """Критерий PGV-01 «version обязателен по applicability» — весь research."""
    gaps = []
    for site in registry["sites"]:
        if scope_of(site) != "research":
            continue
        refs = set(site["required_refs"])
        for ref in twin["rules"]["mandatory_refs_by_scope"]["research"]:
            if ref not in refs:
                gaps.append(f"{site['view_id']}:-{ref}")
    assert gaps == []


def test_registry_refined_records_carry_data_revision(registry):
    by_id = {site["view_id"]: site for site in registry["sites"]}
    for view_id in ("upload.structure.schema", "forecasting.accuracy.metrics"):
        assert "data_revision" in by_id[view_id]["required_refs"], view_id


def test_registry_sampling_exemption_is_cards_only(registry, twin):
    exempt = set(twin["rules"]["sampling"]["exempt_renderer_kinds"])
    for site in registry["sites"]:
        expected = site["renderer_kind"] not in exempt
        if site["renderer_kind"] == "html_cards":
            assert not expected
        else:
            assert expected


def test_ts_py_sources_carry_contract_literals():
    """Пин литералов контракта в исходниках обоих каналов: мандат refs
    (TS без кавычек ключей / PY с кавычками), числа §7 в TS-источнике.
    Ловит дрейф «источник истины ↔ твин», который структурная проверка
    твина не видит."""
    ts_source = (REPO / "packages" / "ui" / "print" / "printSchema.ts").read_text(encoding="utf-8")
    py_source = (REPO / "apps" / "api" / "print_schema.py").read_text(encoding="utf-8")
    for literal in (
        'demo: ["demo_dataset_id"]',
        'research: ["context_id", "data_revision"]',
        'passport: ["context_id", "snapshot_id", "data_revision", "schema_version"]',
        'comparison: ["research_run_id", "comparison_id"]',
        "width_px: 2480",
        "height_px: 3508",
        "width_px: 3508",
        "height_px: 2480",
        "max_output_bytes: 52428800",
        "render_timeout_s: 60",
        "concurrency_per_tenant: 1",
        "concurrency_global: 2",
    ):
        assert literal in ts_source, f"TS: {literal}"
    for literal in (
        '"demo": ["demo_dataset_id"]',
        '"research": ["context_id", "data_revision"]',
        '"passport": ["context_id", "snapshot_id", "data_revision", "schema_version"]',
        '"comparison": ["research_run_id", "comparison_id"]',
    ):
        assert literal in py_source, f"PY: {literal}"


# ── 4. Документ поставки и worklog ───────────────────────────────


def test_delivery_files_exist():
    for rel in (
        "packages/ui/print/printSchema.ts",
        "packages/ui/print/printSchema.test.ts",
        "packages/ui/lib/visualExportRegistry.ts",
        "config/print_schema.json",
        "apps/api/print_schema.py",
        "tests/api/test_pgv01_print_schema.py",
        "scripts/pgv01/export_print_schema.ts",
        "scripts/pgv01/check_documents.py",
        "docs/pgv01_print_schema.md",
    ):
        assert (REPO / rel).exists(), rel


def test_delivery_doc_tokens():
    doc = DOC_PATH.read_text(encoding="utf-8")
    for token in (
        "packages/ui/print/printSchema.ts",
        "config/print_schema.json",
        "apps/api/print_schema.py",
        "pgv.visual_print_snapshot/1",
        "figure-landscape",
        "2480",
        "3508",
        "data_revision",
        "PGV-AC16",
        "PGV-AC21",
        "93",
    ):
        assert token in doc, token


def test_worklog_pgv01_record_present():
    worklog = WORKLOG_PATH.read_text(encoding="utf-8")
    assert "Task ID: PGV-01" in worklog
    assert "Task ID: PGV-00" in worklog


# ── 5. Самопроверки сертификатора (анти-вакуус корпуса) ──────────


def test_cert_cases_unique_ids_and_kinds():
    cases = p1cases.cases()
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids)), "id кейсов уникальны"
    assert {case["kind"] for case in cases} == {"snapshot", "result", "manifest", "unit_decl"}


def test_cert_cases_expected_codes_in_contract():
    cases = p1cases.cases()
    contract = set(EXPECTED_VIOLATION_CODES)
    for case in cases:
        for code, _path in case["expected"]:
            if code == "__exception__":
                continue
            if code.startswith("unit_"):
                continue  # псевдокоды собственной U-семьи сертификатора (пин isUnitDeclared)
            assert code in contract, f"{case['id']}: {code} не из контракта"


def test_cert_cases_cover_every_code_family():
    cases = p1cases.cases()
    covered = {code for case in cases for code, _ in case["expected"]}
    missing = sorted(set(EXPECTED_VIOLATION_CODES) - covered)
    # missing_field покрывает несколько семей; все 37 кодов обязаны иметь
    # хотя бы один кейс-семью в корпусе (или быть вне досягаемости валидатора).
    assert missing == [] or set(missing) <= {"invalid_section_kind"}, missing


def test_cert_cases_have_findings_and_oracle_only_families():
    ids = {case["id"] for case in p1cases.cases()}
    assert {"F1a", "F1b", "F1c", "F1d", "F2a", "F2b", "F2c"} <= ids, "F-семья находок"
    assert {"O01", "O02"} <= ids, "OO-семья для ORACLE-ONLY мутантов"
    valid = [case for case in p1cases.cases() if case["expected"] == []]
    assert len(valid) >= 11, "валидные кейсы-контроли"


def test_cert_namespace_disjunct_from_repo_oracles():
    """Корпус не импортирует repo-оракулы и pgv00cert (честная независимость).
    Запрещены фактические импорты; упоминания в комментариях допустимы."""
    forbidden = (
        "visualExportRegistry.coverage",
        "printSchema.test",
        "test_pgv01_print_schema",
        "pgv00cert",
        "check_documents",
    )
    for path in list(CERT_DIR.glob("*.py")) + list(CERT_DIR.glob("*.ts")):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            for token in forbidden:
                assert token not in stripped, f"{path.name}: импорт чужого оракула {token}"
