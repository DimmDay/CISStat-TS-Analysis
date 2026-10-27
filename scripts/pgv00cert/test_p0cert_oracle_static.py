# scripts/pgv00cert/test_p0cert_oracle_static.py
#
# PGV-00-CERT — статические оракулы сертификатора (СВОИ данные и СВОИ проверки).
# Канал ORACLE кампании мутантов. GREEN на сертифицируемом дереве 2ef6947,
# RED на родителе 754219a (нет реестра/JSON/правок спеки).

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p0scan as S

REPO = S.REPO


def _spec_pgv() -> str:
    return (REPO / "spec_passport_graphics_visual.md").read_text(encoding="utf-8")


def _spec_doclog() -> str:
    return (REPO / "spec_documentation_logging.md").read_text(encoding="utf-8")


def _section(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start)) if end else -1
    return text[i : j if j > 0 else len(text)]


# ── 1. Постановка: spec_passport_graphics_visual.md ─────────────────


def test_spec_pgv_tasks_and_acs_complete():
    t = _spec_pgv()
    task_ids = ["PGV-00", *[f"PGV-{i:02d}" for i in range(1, 17)], "PGV-CERT"]
    for tid in task_ids:
        assert tid in t, f"нет задачи {tid}"
    for i in range(1, 25):
        assert f"PGV-AC{i:02d}" in t, f"нет сценария PGV-AC{i:02d}"


def test_spec_pgv_section13_dag_dependencies_resolve():
    t = _spec_pgv()
    sec = _section(t, "## 13. Пошаговые задачи", "## 14.")
    rows = re.findall(r"^\| (PGV-[0-9CERTK]+) \| ([^|]*) \|", sec, re.M)
    assert len(rows) == 18, f"ожидалось 18 строк задач, факт {len(rows)}"
    known = {r[0] for r in rows} | {"—"}
    for tid, deps in rows:
        for d in re.findall(r"PGV-\d{2}|PGV-CERT", deps.split("|")[0]):
            assert d in known, f"{tid}: зависимость {d} не существует"


def test_spec_pgv_section5_registry_field_list_matches_implementation():
    spec = _spec_pgv()
    sec5 = _section(spec, "## 5. Инвентарь всех остановок", "## 6.")
    assert "machine-readable registry" in sec5
    reg = S.load_registry()
    assert reg["sites"], "реестр пуст"
    # spec §5 формулирует состав через пробел («required refs, view params»);
    # TS/JSON — в snake_case. Проверяем обе формулировки против своих словарей.
    spec_field_tokens = {
        "view_id": "view_id", "module_id": "module_id", "stop_id": "stop_id",
        "render_site": "render_site", "renderer_kind": "renderer_kind",
        "source_adapter": "source_adapter", "required_refs": "required refs",
        "view_params": "view params", "applicability": "applicability",
        "caption_schema": "caption schema", "export_status": "export status",
        "tests": "tests",
    }
    for field, token in spec_field_tokens.items():
        assert token in sec5, f"поле {token} не заявлено в spec §5"
        for s in reg["sites"]:
            assert field in s, f"{s['view_id']}: нет поля {field}"


def test_spec_pgv_section14_acceptance_oracle_data_mentioned():
    t = _spec_pgv()
    sec14 = _section(t, "## 14. Приёмочные сценарии", "## 15.")
    assert "Мутанты" in sec14 and "oracle" in sec14.lower()


# ── 2. Родительская спека: аддитивные правки PGV-00 ──────────────────


def test_doclog_spec_png_only_amendment_in_section7():
    s7 = _section(_spec_doclog(), "## 7. Форматы", "## 8.")
    assert "PNG-only" in s7 and "PGV-00" in s7
    assert "visualExportRegistry" in s7 and "visual_registry.json" in s7


def test_doclog_spec_visualresult_amendment_in_section92():
    s9 = _section(_spec_doclog(), "### 9.2.", "## 10.")
    assert "VisualResult" in s9 and "VisualPrintSnapshot" in s9 and "PGV-00" in s9


def test_doclog_spec_v01_p01_p02_amendment_in_section12_d02_not_renamed():
    s12 = _section(_spec_doclog(), "## 12. UI", "## 13.")
    for tok in ("V01", "P01", "P02", "PGV-00", "D02"):
        assert tok in s12, f"нет {tok} в §12"
    # Полный инвариант D02 (усиление по M18: обе части обязательны —
    # «не переименовывается» и «не равен P01» вместе).
    assert "не переименовывается" in s12 and "не равен P01" in s12, (
        "инвариант D02 ослаблен: требуется «не переименовывается И не равен P01»"
    )


def test_doclog_spec_section19_row_pgv00_unknown_gate():
    s19 = _section(_spec_doclog(), "## 19. Порядок реализации", "## 20.")
    assert "PGV-00" in s19
    row = next(ln for ln in s19.splitlines() if "PGV-00" in ln)
    assert "unknown" in row.lower(), "в строке PGV-00 нет unknown-гейта"


def test_doclog_spec_section191_files_row_registry():
    s191 = _section(_spec_doclog(), "### 19.1.", "## 20.")
    assert "visualExportRegistry" in s191 and "visual_registry.json" in s191


def test_doclog_spec_document_kinds_d01_d12_not_renamed():
    t = _spec_doclog()
    for i in range(1, 13):
        assert re.search(rf"D{i:02d}", t), f"D{i:02d} исчез из родительской спеки"
    # «Дополнение PGV-00» не удаляет каталог: заголовок каталога видов на месте
    assert "## 6." in t or "каталог" in t.lower()


# ── 3. JSON-твин: machine-readability (свои проверки) ────────────────


def test_json_schema_and_composition():
    reg = S.load_registry()
    assert reg["schema_version"] == S.SCHEMA_VERSION
    assert reg["generated_from"] == "packages/ui/lib/visualExportRegistry.ts"
    assert reg.get("pgv_task") == "PGV-00"
    assert reg["total_sites"] == S.EXPECTED_TOTAL
    assert reg["modules"] == S.EXPECTED_MODULES
    assert len(reg["exclusions"]) == S.EXPECTED_EXCLUSIONS


def test_json_view_ids_unique_and_canonical():
    ids = [s["view_id"] for s in S.load_registry()["sites"]]
    assert len(ids) == len(set(ids))
    for vid in ids:
        assert re.match(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$", vid), vid


def test_json_sites_mandatory_fields_and_honest_statuses():
    reg = S.load_registry()
    for s in reg["sites"]:
        for f in S.MANDATORY_SITE_FIELDS:
            assert s.get(f), f"{s['view_id']}: пусто {f}"
        assert re.match(r"^pgv\.caption/[a-z0-9_.-]+/\d+$", s["caption_schema"]), s["view_id"]
        assert s["export_status"] in ("planned", "legacy_client", "not_mounted")
        assert re.match(r"^pgv-\d{2}/", s["source_adapter"]), s["view_id"]
        if s["export_status"] in ("legacy_client", "not_mounted"):
            assert (s.get("notes") or "").strip(), f"{s['view_id']}: нет notes"
    legacy = [s["view_id"] for s in reg["sites"] if s["export_status"] == "legacy_client"]
    assert legacy == ["forecasting.forecast.legacy_png"]
    not_mounted = [s["view_id"] for s in reg["sites"] if s["export_status"] == "not_mounted"]
    assert not_mounted == ["modeling.diagnostics.residuals"]


def test_json_exclusions_have_reasons_and_known_classes():
    known = {"decorative", "ops_admin", "controls", "interactive_editor", "operational_list", "placeholder_soon"}
    for exc in S.load_registry()["exclusions"]:
        assert exc["reason"].strip()
        assert exc["reason_class"] in known, exc["reason_class"]
        assert exc["targets"]
    classes = {e["reason_class"] for e in S.load_registry()["exclusions"]}
    assert known <= classes, f"классы не полны: {sorted(known - classes)}"


def test_json_ts_registry_view_id_count_parity():
    ts = S.load_ts_registry_text()
    ts_count = len(re.findall(r"view_id:\s*\"", ts))
    reg = S.load_registry()
    assert ts_count == len(reg["sites"]) == S.EXPECTED_TOTAL


def test_json_ts_view_id_set_parity():
    """Множество view_id в TS-реестре совпадает с JSON-твином (дрейф ловится)."""
    ts_ids = set(re.findall(r"view_id:\s*\"([^\"]+)\"", S.load_ts_registry_text()))
    json_ids = {s["view_id"] for s in S.load_registry()["sites"]}
    assert ts_ids == json_ids, f"ддрейф TS⇄JSON: {sorted(ts_ids ^ json_ids)}"


def test_json_ts_schema_version_parity():
    ts = S.load_ts_registry_text()
    m = re.search(r'PGV_REGISTRY_SCHEMA_VERSION\s*=\s*"([^"]+)"', ts)
    assert m and m.group(1) == S.SCHEMA_VERSION
    assert S.load_registry()["schema_version"] == m.group(1)


def test_json_ts_exclusion_class_multiset_parity():
    ts_classes = re.findall(r'reason_class:\s*"([^"]+)"', S.load_ts_registry_text())
    json_classes = [e["reason_class"] for e in S.load_registry()["exclusions"]]
    assert sorted(ts_classes) == sorted(json_classes), (
        f"мультимножество классов исключений TS⇄JSON: TS={ts_classes} JSON={json_classes}"
    )


def test_json_stop_catalog_in_ts_matches_expected_shape():
    ts = S.load_ts_registry_text()
    for module, stops in {
        "navigator": 13, "upload": 6, "validation": 11,
        "preprocessing": 11, "eda": 11, "modeling": 5,
        "forecasting": 3, "tasks": 1,
    }.items():
        m = re.search(re.escape(f"{module}:") + r"\s*\[(.*?)\]", ts, re.S)
        assert m, f"нет каталога остановок {module}"
        n = len(re.findall(r"\"[a-z0-9_.]+\"", m.group(1)))
        assert n == stops, f"{module}: ожидалось {stops} остановок, факт {n}"


# ── 4. Регенерация JSON из TS (экспортер байт-честен) ────────────────


def test_export_registry_regen_byte_identical():
    """Регенерация JSON из TS байт-честна и неинвазивна: экспортёр запускается
    реально, но исходные байты JSON восстанавливаются после сравнения (оракул
    не мутирует дерево — урок MV3: регенерация из мутантного TS иначе
    перезаписала бы твин и сорвала протокол восстановления)."""
    json_path = REPO / "config" / "visual_registry.json"
    committed = json_path.read_bytes()
    try:
        r = subprocess.run(
            ["node", "--experimental-strip-types", "scripts/pgv00/export_registry.ts"],
            cwd=REPO, capture_output=True, text=True, timeout=120,
        )
        assert r.returncode == 0, r.stderr
        regenerated = json_path.read_bytes()
        assert regenerated == committed, (
            "экспортёр из TS порождает JSON, отличный от закоммиченного твина"
        )
    finally:
        if json_path.read_bytes() != committed:
            json_path.write_bytes(committed)
    # Чистота дерева после регенерации: экспортёр не оставляет ПОБОЧНЫХ
    # (untracked) файлов. Изменения tracked-файлов — законная территория
    # мутационной кампании (восстановление контролирует MV3), их ловим
    # только вне кампании — в чистом дереве untracked-мусор невозможен.
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True
    ).stdout.splitlines()
    unexpected = [
        ln for ln in status
        if ln.startswith("??")
        and not ln.startswith("?? scripts/")
        and not ln.strip().endswith("worklog/worklog11.md")
    ]
    assert not unexpected, f"экспортёр/оракул оставил мусор: {unexpected}"


# ── 5. Документ инвентаря согласован с JSON ──────────────────────────


def test_inventory_doc_counts_match_json():
    inv = (REPO / "docs" / "pgv00_render_site_inventory.md").read_text(encoding="utf-8")
    reg = S.load_registry()
    for m, n in S.EXPECTED_MODULES.items():
        assert re.search(rf"\|\s*{m}\s*\|\s*{n}\s*\|", inv), f"инвентарь: строка {m}={n}"
    assert str(S.EXPECTED_TOTAL) in inv
    for f in ("packages/ui/lib/visualExportRegistry.ts", "config/visual_registry.json",
              "visualExportRegistry.coverage.test.ts"):
        assert f in inv
    classes = {e["reason_class"] for e in reg["exclusions"]}
    for c in sorted(classes):
        assert c in inv, f"инвентарь: класс {c} не описан"


def test_inventory_doc_delivery_scope_files_exist():
    inv = (REPO / "docs" / "pgv00_render_site_inventory.md").read_text(encoding="utf-8")
    for rel in re.findall(r"`((?:packages|config|scripts|docs|spec_)[^`]+\.(?:ts|json|py|md))`", inv):
        assert (REPO / rel).exists(), f"инвентарь ссылается на несуществующий {rel}"


# ── 6. Guard check_documents.py: состав проверок на месте ────────────


def test_guard_contains_all_check_sections():
    g = (REPO / "scripts" / "pgv00" / "check_documents.py").read_text(encoding="utf-8")
    for token in (
        "spec_passport_graphics_visual.md", "PGV-AC", "## 7. Форматы", "### 9.2.",
        "## 12. UI", "## 19. Порядок реализации", "### 19.1.",
        "visual_registry.json", "pgv00_render_site_inventory.md", "worklog11.md",
        "EXPECTED_MODULES", "EXPECTED_TOTAL", "D02",
        "legacy_client", "not_mounted", "caption_schema", "source_adapter",
        'Task ID: PGV-00" in worklog',
    ):
        assert token in g, f"guard утратил проверку: {token}"


def test_guard_runs_green():
    r = subprocess.run([sys.executable, "scripts/pgv00/check_documents.py"], cwd=REPO,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "GREEN" in r.stdout


# ── 7. Worklog-запись поставки ───────────────────────────────────────


def test_worklog11_contains_pgv00_entry():
    wl = (REPO / "worklog" / "worklog11.md").read_text(encoding="utf-8")
    assert "Task ID: PGV-00" in wl
    assert "89" in wl and "754219a" in wl
