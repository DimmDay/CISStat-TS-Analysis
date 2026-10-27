# scripts/pgv00cert/p0scan.py
#
# PGV-00-CERT — собственная библиотека скана сертификатора.
# Независимая реализация (не импортирует repo-оракул visualExportRegistry.coverage.test.ts):
#   - 6 научных рендер-паттернов spec §5 (свой код);
#   - разбор источников истины: navigator-stops.ts, CHECK_META (TsAnalysisValidation),
#     CHECKS (TsAnalysisPreprocessing), маппинг веток TsAnalysisNavigator.tsx;
#   - разбор JSON-твина config/visual_registry.json;
#   - классификация закрытия: реестр ∪ исключения ⊇ скан.
#
# Namespace сертификатора: p0cert-*, RUN-P0C*. Дизъюнктен repo и предыдущим
# сертификаторам (d6cert-*, d7c-*, d8cert-*, d9cert-*, e2c*).

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Каталоги скана — те же области, что у repo-оракула (spec §5: components + страницы apps).
SCAN_ROOTS = [
    REPO / "packages" / "ui" / "components",
    REPO / "apps" / "standalone" / "app",
    REPO / "apps" / "embedded" / "app",
]

# 6 паттернов spec §5 («Поиск recharts/svg/canvas/HTML table/CSS heatmap — вспомогательный oracle»).
SPEC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("recharts-import", re.compile(r"from\s+[\"']recharts[\"']")),
    ("inline-svg", re.compile(r"<svg[\s>]")),
    ("canvas", re.compile(r"<canvas[\s>]")),
    ("html-table", re.compile(r"<table[\s>]")),
    ("css-heatmap-gradient", re.compile(r"linear-gradient\(")),
    ("css-heatmap-color-scale", re.compile(r"backgroundColor:\s*[`a-zA-Z]")),
]

# Семейные правила сертификатора (свои формулировки, то же покрытие).
FAMILY_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("NavigatorPreview", re.compile(r"^packages/ui/components/Navigator\w*Preview\.tsx$")),
    ("EdaOverview", re.compile(r"^packages/ui/components/Eda\w*Overview\.tsx$")),
    ("ValidationOverview", re.compile(r"^packages/ui/components/Validation\w*Overview\.tsx$")),
    ("PreprocessingOverview", re.compile(r"^packages/ui/components/Preprocessing\w*Overview\.tsx$")),
    ("PreprocessingVisualizations", re.compile(r"^packages/ui/components/Preprocessing\w*Visualizations\.tsx$")),
]

EXPECTED_MODULES = {
    "navigator": 14,
    "upload": 12,
    "validation": 12,
    "preprocessing": 20,
    "eda": 18,
    "modeling": 6,
    "forecasting": 6,
    "tasks": 1,
}
EXPECTED_TOTAL = 89
EXPECTED_EXCLUSIONS = 9
SCHEMA_VERSION = "pgv.visual_registry/1"

# Обязательные поля записи (spec §5: «view_id, module_id, stop_id, render_site,
# renderer_kind, source_adapter, required refs, view params, applicability,
# caption schema, export status and tests»).
MANDATORY_SITE_FIELDS = [
    "view_id", "module_id", "stop_id", "render_site", "renderer_kind",
    "source_adapter", "required_refs", "view_params", "applicability",
    "caption_schema", "export_status", "tests",
]

# Записи с ослабленной паттерн-доказательностью renderer_kind (пин сертификатора,
# версия 1.0 по акту PGV-00-CERT: renderer живёт в дочернем компоненте / CSS-var
# цвета не матчатся / чистая разметка cards). Новые слабые записи = падение оракула.
KIND_WEAK_EVIDENCE_PIN = {
    "navigator.upload.distribution.scatter",
    "navigator.upload.distribution.histogram",
    "navigator.upload.passport.groups",
    "preprocessing.regularity.gap_map",
}


def list_source_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    out: list[Path] = []
    for p in sorted(root.rglob("*.tsx")):
        if p.stem.endswith(".test"):
            continue
        parts = p.parts
        if "node_modules" in parts or any(x.startswith(".") for x in parts):
            continue
        out.append(p)
    return out


def scan_scientific_files() -> dict[str, list[str]]:
    """Собственный pattern-скан (6 паттернов spec §5). Возвращает {repo-rel: [kinds]}."""
    hits: dict[str, list[str]] = {}
    for root in SCAN_ROOTS:
        for f in list_source_files(root):
            text = f.read_text(encoding="utf-8", errors="replace")
            kinds = [k for k, rx in SPEC_PATTERNS if rx.search(text)]
            if kinds:
                hits[str(f.relative_to(REPO))] = kinds
    return hits


def registry_covered_files() -> set[str]:
    covered: set[str] = set()
    for site in load_registry()["sites"]:
        covered.add(site["render_site"].split("#")[0])
        if site.get("renderer_component"):
            covered.add(site["renderer_component"].split("#")[0])
    return covered


def exclusion_covered_files() -> set[str]:
    """Файлы под исключениями: строки + glob (свой glob→regex)."""
    all_files = [str(f.relative_to(REPO)) for root in SCAN_ROOTS for f in list_source_files(root)]
    files: set[str] = set()
    for exc in load_registry()["exclusions"]:
        for target in exc["targets"]:
            if "*" in target:
                rx = re.compile("^" + re.escape(target).replace(r"\*", ".*") + "$")
                files.update(f for f in all_files if rx.match(f))
            else:
                files.add(target)
    return files


def load_registry() -> dict:
    return json.loads((REPO / "config" / "visual_registry.json").read_text(encoding="utf-8"))


def load_ts_registry_text() -> str:
    return (REPO / "packages" / "ui" / "lib" / "visualExportRegistry.ts").read_text(encoding="utf-8")


def _ts_ids(src: str, array_name: str) -> list[str]:
    """id из TS-массива объектов: [{ id: "x", ... }, ...] (первое вхождение id в каждом объекте)."""
    m = re.search(re.escape(array_name) + r"[^=]*=\s*\[(.*?)\n\]", src, re.S)
    if not m:
        return []
    body = m.group(1)
    return re.findall(r"\bid:\s*\"([a-z0-9_]+)\"", body)


def parse_navigator_stops() -> dict[str, list[str]]:
    """{stage: [item ids]} из packages/ui/lib/navigator-stops.ts (свой разбор)."""
    src = (REPO / "packages" / "ui" / "lib" / "navigator-stops.ts").read_text(encoding="utf-8")
    stages: dict[str, list[str]] = {}
    for sm in re.finditer(r"\{\s*\n?\s*id:\s*\"([a-z_]+)\",(.*?)\n  \},", src, re.S):
        stage_id, body = sm.group(1), sm.group(2)
        items = re.findall(r"\{\s*id:\s*\"([a-z0-9_]+)\",\s*title:", body)
        if items:
            stages[stage_id] = items
    return stages


def parse_validation_check_meta() -> list[str]:
    src = (REPO / "packages" / "ui" / "components" / "TsAnalysisValidation.tsx").read_text(encoding="utf-8")
    return _ts_ids(src, "CHECK_META")


def parse_preprocessing_checks() -> list[str]:
    src = (REPO / "packages" / "ui" / "components" / "TsAnalysisPreprocessing.tsx").read_text(encoding="utf-8")
    return _ts_ids(src, "CHECKS")


def parse_navigator_item_mapping() -> list[tuple[str, str, str]]:
    """[(stage, item, component)] из веток TsAnalysisNavigator.tsx."""
    src = (REPO / "packages" / "ui" / "components" / "TsAnalysisNavigator.tsx").read_text(encoding="utf-8")
    out: list[tuple[str, str, str]] = []
    for m in re.finditer(
        r"activeStopId\s*===\s*\"([a-z_]+)\"\s*&&\s*activeItemId\s*===\s*\"([a-z0-9_]+)\"\s*\?\s*\n?\s*<(\w+)",
        src,
    ):
        out.append((m.group(1), m.group(2), m.group(3)))
    return out


def file_has_pattern(rel_path: str, kinds: set[str]) -> bool:
    p = REPO / rel_path
    if not p.exists():
        return False
    text = p.read_text(encoding="utf-8", errors="replace")
    rx_by_kind = dict(SPEC_PATTERNS)
    return any(rx_by_kind[k].search(text) for k in kinds if k in rx_by_kind)


def site_pattern_union(site: dict) -> set[str]:
    """Сигнатуры паттернов по {render_site, renderer_component} записи."""
    rx_by_kind = dict(SPEC_PATTERNS)
    sig: set[str] = set()
    for rel in {site["render_site"].split("#")[0], (site.get("renderer_component") or "#").split("#")[0]}:
        p = REPO / rel
        if not rel or rel == "#" or not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        sig.update(k for k, rx in rx_by_kind.items() if rx.search(text))
    return sig


def kind_consistent(site: dict) -> bool:
    """Согласованность renderer_kind с паттерн-сигнатурами (Class A, с пином слабых записей)."""
    kind = site["renderer_kind"]
    sig = site_pattern_union(site)
    if kind == "recharts_svg":
        ok = bool(sig & {"recharts-import", "inline-svg"})
    elif kind == "html_table":
        ok = "html-table" in sig
    elif kind == "html_heatmap":
        ok = bool(sig & {"css-heatmap-gradient", "css-heatmap-color-scale"})
    elif kind == "mixed":
        ok = len(sig) >= 1
    else:  # html_cards — контейнеры-карточки, паттерн-нейтральный
        ok = True
    if ok:
        return True
    return site["view_id"] in KIND_WEAK_EVIDENCE_PIN
