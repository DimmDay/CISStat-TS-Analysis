# scripts/pgv00cert/test_p0cert_oracle_coverage.py
#
# PGV-00-CERT — coverage-оракулы сертификатора (СВОЙ скан, СВОЙ разбор
# источников истины). Канал ORACLE кампании мутантов. GREEN на 2ef6947,
# RED на родителе 754219a.

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import p0scan as S

REPO = S.REPO


# ── 1. Собственный pattern-скан и закрытие классификации ─────────────


def test_own_scan_baseline_at_least_58_files():
    hits = S.scan_scientific_files()
    assert len(hits) >= 58, f"базлайн 58 потерян: {len(hits)}"


def test_own_scan_closure_every_hit_registered_or_excluded():
    hits = S.scan_scientific_files()
    covered = S.registry_covered_files()
    excluded = S.exclusion_covered_files()
    unknown = {f: k for f, k in hits.items() if f not in covered and f not in excluded}
    assert not unknown, f"unknown scientific site: {unknown}"


def test_own_family_rules_fully_covered():
    covered = S.registry_covered_files()
    excluded = S.exclusion_covered_files()
    all_files = [str(f.relative_to(REPO)) for root in S.SCAN_ROOTS for f in S.list_source_files(root)]
    uncovered = [
        f for f in all_files
        if any(rx.match(f) for _, rx in S.FAMILY_RULES) and f not in covered and f not in excluded
    ]
    assert not uncovered, f"семейные правила: не покрыто {uncovered}"


def test_own_scan_all_hits_classified_count_matches():
    hits = S.scan_scientific_files()
    covered = S.registry_covered_files()
    excluded = S.exclusion_covered_files()
    classified = [f for f in hits if f in covered or f in excluded]
    assert len(classified) == len(hits), "часть скана не классифицирована"


# ── 2. Остановки против источников истины (прямой канал) ─────────────


def test_validation_check_meta_each_check_has_site():
    checks = S.parse_validation_check_meta()
    assert len(checks) == 10, f"CHECK_META: {checks}"
    sites = S.load_registry()["sites"]
    stops = {s["stop_id"] for s in sites if s["module_id"] == "validation"}
    for c in checks:
        assert c in stops, f"Валидация: проверка {c} без render-site"


def test_preprocessing_checks_each_check_has_site():
    checks = S.parse_preprocessing_checks()
    assert len(checks) == 10, f"CHECKS: {checks}"
    sites = S.load_registry()["sites"]
    stops = {s["stop_id"] for s in sites if s["module_id"] == "preprocessing"}
    for c in checks:
        assert c in stops, f"Предобработка: остановка {c} без render-site"


def test_eda_subviews_each_has_site():
    nav = S.parse_navigator_stops()
    assert "eda" in nav and len(nav["eda"]) >= 10
    sites = S.load_registry()["sites"]
    stops = {s["stop_id"] for s in sites if s["module_id"] == "eda"}
    for item in nav["eda"]:
        if item == "passport":
            continue
        assert item in stops, f"EDA: субвид {item} без render-site"
    assert "passport" in stops, "EDA: паспортная остановка без записи"


def test_upload_active_stop_branches_have_sites():
    sites = S.load_registry()["sites"]
    stops = {s["stop_id"] for s in sites if s["module_id"] == "upload"}
    for branch in ("overview", "chart", "distribution", "structure", "quality", "passport"):
        assert branch in stops, f"Загрузка: ветка {branch} без записи"


def test_navigator_site_stops_belong_to_navigator_stops_source():
    nav = S.parse_navigator_stops()
    sites = S.load_registry()["sites"]
    for s in sites:
        if s["module_id"] != "navigator":
            continue
        stage, item = s["stop_id"].split(".", 1)
        assert stage in nav, f"{s['view_id']}: стадия {stage} вне navigator-stops"
        assert item in nav[stage], f"{s['view_id']}: пункт {item} вне navigator-stops[{stage}]"


def test_navigator_items_with_real_render_have_site_or_exclusion():
    """Обратный канал по маппингу TsAnalysisNavigator.tsx (component-level):
    каждый пункт Навигатора, рендерящий реальный компонент, обязан быть
    зарегистрирован либо исключён."""
    covered = S.registry_covered_files()
    excluded = S.exclusion_covered_files()
    unregistered: list[str] = []
    for stage, item, component in S.parse_navigator_item_mapping():
        fname = f"packages/ui/components/{component}.tsx"
        if fname not in covered and fname not in excluded:
            unregistered.append(f"{stage}.{item} -> {component}")
    assert not unregistered, f"пункты Навигатора без регистрации/исключения: {unregistered}"


def test_navigator_item_mapping_is_non_vacuous():
    """Анти-вакуумный гвард (урок PGV-00-FIX): regex-парсер веток Навигатора
    v1.0 молча возвращал 0 записей (`? (` не матчился), и branch-оракул выше
    проходил вакуусно. Маппинг обязан быть непустым и содержать известные
    ветки, иначе канал недееспособен."""
    mapping = S.parse_navigator_item_mapping()
    assert len(mapping) >= 10, f"branch-маппинг вырожден: {len(mapping)} записей"
    as_dict = {(st, it): comp for st, it, comp in mapping}
    assert as_dict.get(("upload", "preview")) == "UploadAutoPreviewPipeline", as_dict.get(("upload", "preview"))
    assert as_dict.get(("upload", "chart")) == "NavigatorChartPreview", as_dict.get(("upload", "chart"))


def test_module_stop_catalog_uses_truth_sources():
    """Каталоги остановок validation/preprocessing/eda в реестре совпадают
    с CHECK_META/CHECKS/navigator-stops (+passport)."""
    reg = S.load_registry()
    sites = reg["sites"]
    val_stops = {s["stop_id"] for s in sites if s["module_id"] == "validation"}
    pre_stops = {s["stop_id"] for s in sites if s["module_id"] == "preprocessing"}
    eda_stops = {s["stop_id"] for s in sites if s["module_id"] == "eda"}
    val_expected = set(S.parse_validation_check_meta()) | {"passport"}
    pre_expected = set(S.parse_preprocessing_checks()) | {"passport"}
    nav = S.parse_navigator_stops()
    eda_expected = (set(nav.get("eda", [])) - {"passport"}) | {"passport"}
    assert val_stops == val_expected, f"validation: {val_stops ^ val_expected}"
    assert pre_stops == pre_expected, f"preprocessing: {pre_stops ^ pre_expected}"
    assert eda_stops == eda_expected, f"eda: {eda_stops ^ eda_expected}"


# ── 3. renderer_kind согласован с сигнатурами файлов ─────────────────


def test_renderer_kind_consistent_with_file_signatures():
    bad = []
    for s in S.load_registry()["sites"]:
        if not S.kind_consistent(s):
            bad.append((s["view_id"], s["renderer_kind"], sorted(S.site_pattern_union(s))))
    assert not bad, f"renderer_kind без сигнатур (вне пина слабых записей): {bad}"


def test_weak_evidence_pin_is_exactly_known_records():
    """Пин слабых записей не растёт молча: все записи пина реально имеют
    слабую сигнатуру, все слабые записи — в пине."""
    weak_actual = set()
    for s in S.load_registry()["sites"]:
        kind = s["renderer_kind"]
        sig = S.site_pattern_union(s)
        if kind == "recharts_svg" and not (sig & {"recharts-import", "inline-svg"}):
            weak_actual.add(s["view_id"])
        elif kind == "html_table" and "html-table" not in sig:
            weak_actual.add(s["view_id"])
        elif kind == "html_heatmap" and not (sig & {"css-heatmap-gradient", "css-heatmap-color-scale"}):
            weak_actual.add(s["view_id"])
        elif kind == "mixed" and len(sig) < 2:
            weak_actual.add(s["view_id"])
    assert weak_actual == S.KIND_WEAK_EVIDENCE_PIN, (
        f"пин слабых записей рассинхронизирован: факт {sorted(weak_actual)}"
    )


# ── 4. Панельная применимость (spec AC14 — панель не смешивается) ────


def test_panel_records_declared_with_entity_refs():
    sites = S.load_registry()["sites"]
    panel = [s for s in sites if "panel" in (s.get("applicability") or "") or "panel" in s["stop_id"]]
    assert panel, "нет панельных записей"
    for s in panel:
        joined = " ".join(s["required_refs"]) + " " + " ".join(s["view_params"])
        # Entity-scoped виды (панельный прогноз/метрики по сущностям) обязаны
        # нести entity/grouping-ref (spec AC14: entities не смешиваются).
        # Датасет-уровневые виды (структура, teaser качества) работают с
        # панельным датасетом целиком — entity-ref им не требуется.
        entity_scoped = s["view_id"].count("panel") > 0
        if entity_scoped:
            assert re.search(r"entity|grouping", joined, re.I), (
                f"{s['view_id']}: панель без entity/grouping-refs"
            )


def test_html_kinds_present_real_navigator_included():
    """Критерий PGV-00: HTML/panel/real navigator включены."""
    sites = S.load_registry()["sites"]
    kinds = {s["renderer_kind"] for s in sites}
    assert {"html_table", "html_heatmap", "html_cards", "recharts_svg"} <= kinds
    navigator = [s for s in sites if s["module_id"] == "navigator"]
    assert len(navigator) == S.EXPECTED_MODULES["navigator"]
    assert all("static_demo" in s["applicability"] for s in navigator)


# ── 5. Денominator-пины сертификатора (свои, независимо от repo) ─────


def test_denominator_pins_own():
    reg = S.load_registry()
    assert reg["total_sites"] == 93
    assert reg["modules"] == S.EXPECTED_MODULES
    assert len(reg["exclusions"]) == 9
    per = {}
    for s in reg["sites"]:
        per[s["module_id"]] = per.get(s["module_id"], 0) + 1
    assert per == S.EXPECTED_MODULES
