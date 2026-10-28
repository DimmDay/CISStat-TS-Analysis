# scripts/pgv01cert/p1cases.py
#
# PGV-01-CERT — СОБСТВЕННЫЕ данные сертификатора (оракулы на своих данных).
#
# Namespace: p1cert-* (дизъюнктен с repo-сюитами packages/ui/print/,
# tests/api/test_pgv01_print_schema.py, скриптами scripts/pgv00cert/ и
# scripts/pgv00/). Ни один фиксатор здесь не импортирует repo-тесты или
# repo-билдеры: снапшоты/результаты/манифесты строятся независимой
# реализацией по тексту spec_passport_graphics_visual.md §6/§7 и JSON-твину
# config/visual_registry.json (паритет TS⇄твин гвардят repo-каналы —
# здесь он НЕ перепроверяется, чтобы не дублировать чужой оракул).
#
# Каждому кейсу прегистрировано ожидание исхода (мультимножество пар
# [code, path]) — моя собственная транскрипция контракта кодов нарушений.
# Анти-вакуус: статический оракул сверяет транскрипцию с twin
# violation_codes, паритетный оракул — каналы TS и Python между собой.
#
# Спец-значения чисел передаются в TS-драйвер маркерами {"__special__":
# "NaN" | "Infinity" | "-Infinity"} (JSON не носит non-finite); Python-канал
# строит те же значения нативно.

from __future__ import annotations

import json
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
REGISTRY_PATH = REPO / "config" / "visual_registry.json"

PRINT_SNAPSHOT_VERSION = "pgv.visual_print_snapshot/1"
VISUAL_RESULT_VERSION = "pgv.visual_result/1"
PRINT_MANIFEST_VERSION = "pgv.print_manifest/1"

MANDATORY_REFS = {
    "demo": ["demo_dataset_id"],
    "research": ["context_id", "data_revision"],
    "passport": ["context_id", "snapshot_id", "data_revision", "schema_version"],
    "comparison": ["research_run_id", "comparison_id"],
}


def load_registry() -> dict:
    with REGISTRY_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def site(view_id: str) -> dict:
    for candidate in load_registry()["sites"]:
        if candidate["view_id"] == view_id:
            return candidate
    raise AssertionError(f"p1cert: site not found: {view_id}")


def scope_of(site_rec: dict) -> str:
    refs = set(site_rec["required_refs"])
    if "demo_dataset_id" in refs:
        return "demo"
    if "comparison_id" in refs:
        return "comparison"
    if "snapshot_id" in refs or site_rec.get("stop_id") == "passport":
        return "passport"
    return "research"


# ── Собственные секции/снапшоты (независимая реализация) ──────────


def section(kind: str) -> dict:
    base = {
        "section_id": "sec-1",
        "renderer_kind": kind,
        "title": None,
        "axes": [],
        "legend_ordering": ["s1"],
        "table_headings": None,
        "heatmap_scale": None,
        "units": [{"value": "unit-fixed", "reason": None}],
    }
    if kind == "recharts_svg":
        base["axes"] = [
            {"name": "Время", "units": {"value": "date", "reason": None}, "scale": "time", "limits": None},
            {"name": "Значение", "units": {"value": "unit-fixed", "reason": None}, "scale": "linear", "limits": None},
        ]
    if kind == "html_table":
        base["table_headings"] = {"row": ["Строка-1"], "column": ["Колонка-1"]}
        base["units"] = [{"value": None, "reason": "dimensionless"}]
    if kind == "html_heatmap":
        base["heatmap_scale"] = {"domain": [0.0, 1.0], "units": {"value": "share", "reason": None}}
    if kind == "html_cards":
        base["units"] = [{"value": None, "reason": "dimensionless"}]
    return base


def sections_for(renderer_kind: str) -> list[dict]:
    if renderer_kind == "mixed":
        return [section("recharts_svg"), section("html_table")]
    return [section(renderer_kind)]


def build_snapshot(view_id: str) -> dict:
    site_rec = site(view_id)
    scope = scope_of(site_rec)
    refs = {key: f"p1cert-ref:{key}" for key in MANDATORY_REFS[scope]}
    for key in site_rec["required_refs"]:
        refs.setdefault(key, f"p1cert-ref:{key}")
    demo = scope == "demo"
    mode = "panel" if site_rec["applicability"] == "panel" else "univariate"
    cards = site_rec["renderer_kind"] == "html_cards"
    return {
        "schema_version": PRINT_SNAPSHOT_VERSION,
        "view_id": site_rec["view_id"],
        "scope": scope,
        "refs": refs,
        "result": {
            "result_ref": f"p1cert:visual_result:{view_id}",
            "result_schema_version": VISUAL_RESULT_VERSION,
            "result_digest": "a" * 64,
            "result_digest_reason": None,
        },
        "data_artifact": {
            "artifact_id": None if demo else "p1cert:data:1",
            "artifact_version": "demo-v1" if demo else "v1",
            "source_hash": None if demo else "b" * 64,
            "hash_algorithm": None if demo else "sha256",
            "hash_reason": "demo_dataset" if demo else None,
        },
        "expected_context": {
            "context_id": refs.get("context_id"),
            "data_revision": refs.get("data_revision"),
            "expected_data_digest": None,
        }
        if not demo
        else {"context_id": None, "data_revision": None, "expected_data_digest": None},
        "dimensions": {
            "target_column": refs.get("target_column"),
            "date_column": refs.get("date_column"),
            "entity_column": refs.get("entity_column"),
            "entity_id": "p1cert:entity" if mode == "panel" else None,
            "mode": mode,
        },
        "times": {
            "computed_at": "2026-10-28T00:00:00Z",
            "computed_at_reason": None,
            "captured_at": "2026-10-28T00:00:00Z",
            "captured_at_reason": None,
            "checkpoint_confirmed_at": None,
            "render_requested_at": "2026-10-28T00:00:01Z",
            "timezone": "UTC",
            "locale": "ru-RU",
        },
        "checkpoint": None,
        "display": {
            "title": f"p1cert {view_id}",
            "subtitle": None,
            "detail_level": "compact",
            "sections": sections_for(site_rec["renderer_kind"]),
        },
        "method": {"origin": "producer_freeze", "method": "p1cert-fixture", "parameters": {}},
        "selection": {"allowlist": list(site_rec["view_params"]), "values": {}},
        "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None}
        if not cards
        else {"applicable": False, "mode": None, "point_cap": None, "reason": "p1cert: cards view"},
        "annotations": {"revision": 0, "author": "analyst", "text": None},
        "print": {"profile_id": "figure-landscape", "page_count": 1, "theme": "light-print"},
        "renderer_env": {
            "renderer_version": "p1cert/1",
            "font_profile": "p1cert-font/1",
            "dependency_status": "available",
            "unavailable_reason": None,
        },
        "data_flow": {"before_revision": None, "after_revision": None},
        "sensitive": {"raw_data_included": False, "sensitive_fields_policy": "p1cert-redacted"},
        "warnings": [],
    }


def build_result() -> dict:
    return {
        "schema_version": VISUAL_RESULT_VERSION,
        "view_id": "upload.chart.series",
        "payload": {"kind": "recharts_svg", "series_cap": None, "digest": "c" * 64, "digest_reason": None},
        "parameters": {"origin": "producer_freeze", "method": "p1cert", "parameters": {}},
        "units": [{"value": "unit-fixed", "reason": None}],
        "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
        "warnings": [],
        "execution": {
            "execution_ref": "p1cert-exec-1",
            "result_ref": "p1cert:visual_result:1",
            "computed_at": "2026-10-28T00:00:00Z",
            "computed_at_reason": None,
        },
    }


def manifest_pages(indexes: list[int]) -> list[dict]:
    return [
        {
            "filename": f"p1cert-page-{i:02d}.png",
            "page_role": "p1cert.role",
            "index": i,
            "width_px": 2480,
            "height_px": 3508,
            "png_sha256": "d" * 64,
        }
        for i in indexes
    ]


def build_manifest(indexes: list[int] | None = None, page_list: list[dict] | None = None, **overrides) -> dict:
    manifest = {
        "schema_version": PRINT_MANIFEST_VERSION,
        "set_id": "p1cert-set-1",
        "render_version": "p1cert-renderer/1",
        "profile_id": "a4-portrait",
        "pages": page_list if page_list is not None else manifest_pages(indexes or [1, 2, 3]),
        "metadata_filename": "p1cert-metadata.json",
        "dependencies": [],
        "data_included": False,
    }
    manifest.update(overrides)
    return manifest


# ── Реестр кейсов: id → (kind, payload, site_view_id, ожидание) ───
# Ожидание — мультимножество пар [code, path] (список с повторами).

SITES = {
    "demo_chart": "navigator.upload.chart.series",
    "research_chart": "upload.chart.series",
    "research_table": "upload.overview.preview",
    "research_heatmap": "eda.feature_select.matrix",
    "research_cards": "upload.quality.teaser",
    "research_mixed": "preprocessing.outliers.series_profile",
    "panel": "modeling.panel.metrics",
    "passport": "upload.passport.panel",
    "comparison": "forecasting.monitoring.d12",
}


def _snap(key: str) -> dict:
    return build_snapshot(SITES[key])


def _deep(base: dict, **path_value) -> dict:
    """Мутирует вложенные поля по путям 'a.b.0.c' (цифры — индексы списков)."""
    import copy

    clone = copy.deepcopy(base)
    for dotted, value in path_value.items():
        parts = dotted.split(".")
        node = clone
        for part in parts[:-1]:
            node = node[int(part)] if isinstance(node, list) else node[part]
        last = parts[-1]
        if isinstance(node, list):
            node[int(last)] = value
        else:
            node[last] = value
    return clone


def cases() -> list[dict]:
    """Полный реестр кейсов сертификатора (свои данные + прегистрации)."""
    out: list[dict] = []

    def add(cid: str, kind: str, payload: dict, expected: list, site_key: str | None = None):
        out.append(
            {
                "id": cid,
                "kind": kind,
                "payload": payload,
                "expected": expected,
                "site": SITES[site_key] if site_key else None,
            }
        )

    # ── Валидные кейсы (CONTROL ALIVE): оба канала обязаны дать [] ──
    add("C01", "snapshot", _snap("demo_chart"), [], "demo_chart")
    add("C02", "snapshot", _snap("research_chart"), [], "research_chart")
    add("C03", "snapshot", _snap("research_table"), [], "research_table")
    add("C04", "snapshot", _snap("research_heatmap"), [], "research_heatmap")
    add("C05", "snapshot", _snap("research_cards"), [], "research_cards")
    add("C06", "snapshot", _snap("research_mixed"), [], "research_mixed")
    add("C07", "snapshot", _snap("panel"), [], "panel")
    add("C08", "snapshot", _snap("passport"), [], "passport")
    add("C09", "snapshot", _snap("comparison"), [], "comparison")
    add("C10", "result", build_result(), [])
    add("C11", "manifest", build_manifest(), [])

    # ── Негативные кейсы (по одному на семейство кодов) ────────────
    s = _snap("research_chart")
    add("N01", "snapshot", _deep(s, **{"refs.data_revision": None}), [["missing_required_ref", "refs.data_revision"]], "research_chart")
    add("N02", "snapshot", _deep(s, **{"refs.context_id": ""}), [["missing_required_ref", "refs.context_id"]], "research_chart")
    add("N03", "snapshot", _deep(s, **{"result.result_ref": "", "result.result_schema_version": ""}), [["missing_result_ref", "result"]], "research_chart")
    add("N04", "snapshot", _deep(s, **{"times.computed_at": None, "times.computed_at_reason": None}), [["missing_date", "times.computed_at"]], "research_chart")
    add("N05", "snapshot", _deep(s, **{"times.computed_at": "2026-10-28T00:00:00Z", "times.computed_at_reason": "legacy_unknown"}), [["ambiguous_date", "times.computed_at"]], "research_chart")
    add("N06", "snapshot", _deep(s, **{"times.captured_at": None, "times.captured_at_reason": None}), [["missing_date", "times.captured_at"]], "research_chart")
    add("N07", "snapshot", _deep(s, **{"times.render_requested_at": None}), [["missing_field", "times.render_requested_at"]], "research_chart")
    add("N08", "snapshot", _deep(s, **{"times.timezone": ""}), [["missing_field", "times.timezone/locale"]], "research_chart")
    add("N09", "snapshot", _deep(s, **{"data_artifact.artifact_version": None}), [["missing_data_version", "data_artifact.artifact_version"]], "research_chart")
    add("N10", "snapshot", _deep(s, **{"data_artifact.source_hash": None, "data_artifact.hash_reason": None}), [["missing_source_hash", "data_artifact.source_hash"]], "research_chart")
    add("N11", "snapshot", _deep(s, **{"data_artifact.source_hash": "b" * 64, "data_artifact.hash_reason": "legacy_unknown"}), [["ambiguous_source_hash", "data_artifact.source_hash"]], "research_chart")
    add("N12", "snapshot", _deep(s, **{"result.result_digest": None, "result.result_digest_reason": None}), [["missing_source_hash", "result.result_digest"]], "research_chart")
    add("N13", "snapshot", _deep(s, **{"result.result_digest": "a" * 64, "result.result_digest_reason": "legacy_unknown"}), [["ambiguous_source_hash", "result.result_digest"]], "research_chart")
    add("N14", "snapshot", _deep(s, **{"expected_context.context_id": None, "expected_context.data_revision": None}), [["missing_expected_context", "expected_context"]], "research_chart")
    add("N15", "snapshot", _deep(s, **{"schema_version": "pgv.visual_print_snapshot/2"}), [["schema_version_mismatch", "schema_version"]], "research_chart")
    add("N16", "snapshot", _deep(s, **{"display.title": "   "}), [["missing_title", "display.title"]], "research_chart")
    add("N17", "snapshot", _deep(s, **{"display.sections": []}), [["empty_sections", "display.sections"]], "research_chart")
    add("N18", "snapshot", _deep(s, **{"display.sections.0.axes": []}), [["missing_axes", "display.sections[0].axes"]], "research_chart")
    add("N19", "snapshot", _deep(s, **{"display.sections.0.axes.0.name": ""}), [["missing_axes", "display.sections[0].axes[0].name"]], "research_chart")
    add("N20", "snapshot", _deep(s, **{"display.sections.0.axes.0.units": {"value": None, "reason": None}}), [["missing_units", "display.sections[0].axes[0].units"]], "research_chart")
    add("N21", "snapshot", _deep(s, **{"display.sections.0.axes.0.units": {"value": "date", "reason": "dimensionless"}}), [["ambiguous_unit", "display.sections[0].axes[0].units"]], "research_chart")
    add("N22", "snapshot", _deep(s, **{"display.sections.0.units": []}), [["missing_units", "display.sections[0].units"]], "research_chart")
    add("N23", "snapshot", _deep(s, **{"display.sections.0.renderer_kind": "canvas2d"}), [["invalid_section_kind", "display.sections[0].renderer_kind"], ["section_kind_mismatch", "display.sections"]], "research_chart")
    add("N24", "snapshot", _deep(s, **{"method.origin": "client_request"}), [["untrusted_parameter_origin", "method.origin"]], "research_chart")
    add("N25", "snapshot", _deep(s, **{"selection.allowlist": ["selected_column", "window", "zoom", "authoritative_series_override"]}), [["selection_not_allowlisted", "selection.allowlist.authoritative_series_override"]], "research_chart")
    add("N26", "snapshot", _deep(s, **{"selection.values": {"unauthorized_key": 1}}), [["selection_not_allowlisted", "selection.values.unauthorized_key"]], "research_chart")
    add("N27", "snapshot", _deep(s, **{"sampling": {"applicable": False, "mode": None, "point_cap": None, "reason": None}}), [["missing_sampling", "sampling"]], "research_chart")
    add("N28", "snapshot", _deep(s, **{"sampling": {"applicable": True, "mode": "hyper", "point_cap": None, "reason": None}}), [["missing_sampling_mode", "sampling.mode"]], "research_chart")
    add("N29", "snapshot", _deep(s, **{"sampling": {"applicable": True, "mode": "downsampled", "point_cap": None, "reason": None}}), [["missing_point_cap", "sampling.point_cap"]], "research_chart")
    add("N30", "snapshot", _deep(s, **{"sampling": {"applicable": True, "mode": "truncated", "point_cap": 0, "reason": None}}), [["missing_point_cap", "sampling.point_cap"]], "research_chart")
    add("N31", "snapshot", _deep(s, **{"print.profile_id": "poster-huge"}), [["invalid_profile", "print.profile_id"]], "research_chart")
    add("N32", "snapshot", _deep(s, **{"print.page_count": 0}), [["missing_field", "print.page_count"]], "research_chart")
    add("N33", "snapshot", _deep(s, **{"print.theme": "dark"}), [["theme_not_light_print", "print.theme"]], "research_chart")
    add("N34", "snapshot", _deep(s, **{"renderer_env.dependency_status": "unavailable", "renderer_env.unavailable_reason": None}), [["missing_renderer_reason", "renderer_env.unavailable_reason"]], "research_chart")
    add("N35", "snapshot", _deep(s, **{"sensitive.raw_data_included": True}), [["raw_data_included_forbidden", "sensitive.raw_data_included"]], "research_chart")
    add("N36", "snapshot", _deep(s, **{"sensitive.sensitive_fields_policy": ""}), [["missing_field", "sensitive.sensitive_fields_policy"]], "research_chart")
    add("N37", "snapshot", _deep(s, **{"annotations.revision": -1}), [["missing_field", "annotations.revision"]], "research_chart")
    add("N38", "snapshot", _deep(s, **{"view_id": "upload.overview.preview"}), [["missing_field", "view_id"]], "research_chart")
    add("N39", "snapshot", _deep(s, **{"scope": "demo"}), [["missing_field", "scope"]], "research_chart")
    add("N40", "snapshot", _deep(_snap("research_table"), **{"display.sections.0.table_headings": None}), [["missing_table_headings", "display.sections[0].table_headings"]], "research_table")
    add("N41", "snapshot", _deep(_snap("research_table"), **{"display.sections.0.table_headings": {"row": [], "column": ["К1"]}}), [["missing_table_headings", "display.sections[0].table_headings"]], "research_table")
    add("N42", "snapshot", _deep(_snap("research_heatmap"), **{"display.sections.0.heatmap_scale": None}), [["missing_heatmap_scale", "display.sections[0].heatmap_scale"]], "research_heatmap")
    add("N43", "snapshot", _deep(_snap("research_heatmap"), **{"display.sections.0.heatmap_scale": {"domain": [0], "units": {"value": "share", "reason": None}}}), [["missing_heatmap_scale", "display.sections[0].heatmap_scale"]], "research_heatmap")
    add("N44", "snapshot", _deep(_snap("research_heatmap"), **{"display.sections.0.heatmap_scale": {"domain": [0, 1], "units": {"value": None, "reason": None}}}), [["missing_units", "display.sections[0].heatmap_scale.units"]], "research_heatmap")
    add("N45", "snapshot", _deep(_snap("research_cards"), **{"sampling": {"applicable": False, "mode": None, "point_cap": None, "reason": None}}), [["missing_sampling_reason", "sampling.reason"]], "research_cards")
    add("N46", "snapshot", _deep(_snap("research_mixed"), **{"display.sections": [section("recharts_svg")]}), [["mixed_needs_multiple_sections", "display.sections"]], "research_mixed")  # noqa: E501
    add("N47", "snapshot", _deep(s, **{"display.sections": [section("html_table")]}), [["section_kind_mismatch", "display.sections"]], "research_chart")
    add("N48", "snapshot", _deep(_snap("panel"), **{"dimensions.mode": "univariate"}), [["panel_mixing", "dimensions.mode"]], "panel")
    add("N49", "snapshot", _deep(s, **{"dimensions.entity_id": "p1cert:entity"}), [["panel_mixing", "dimensions.entity_id"]], "research_chart")
    add("N50", "snapshot", _deep(_snap("passport"), **{"checkpoint": {"reused": True, "source_snapshot_ref": None}, "times.checkpoint_confirmed_at": None}), [["missing_checkpoint_confirmation", "checkpoint"]], "passport")
    add("N51", "result", _deep(build_result(), **{"parameters.origin": "client_request"}), [["untrusted_parameter_origin", "method.origin"]])
    add("N52", "result", _deep(build_result(), **{"payload.digest": None, "payload.digest_reason": None}), [["missing_digest", "payload.digest"]])
    add("N53", "result", _deep(build_result(), **{"payload.digest": "c" * 64, "payload.digest_reason": "legacy_unknown"}), [["ambiguous_source_hash", "payload.digest"]])
    add("N54", "result", _deep(build_result(), **{"payload.kind": "mixed"}), [["invalid_section_kind", "payload.kind"]])
    add("N55", "result", _deep(build_result(), **{"units": []}), [["missing_units", "units"]])
    add("N56", "result", _deep(build_result(), **{"sampling": {"applicable": False, "mode": None, "point_cap": None, "reason": None}}), [["missing_sampling", "sampling"]])
    add("N57", "result", _deep(build_result(), **{"execution.result_ref": ""}), [["missing_result_ref", "execution.result_ref"]])
    add("N58", "result", _deep(build_result(), **{"execution.computed_at": None, "execution.computed_at_reason": None}), [["missing_date", "execution.computed_at"]])
    add("N59", "result", _deep(build_result(), **{"schema_version": "pgv.visual_result/2"}), [["schema_version_mismatch", "schema_version"]])
    add("N60", "manifest", build_manifest(indexes=[1, 1]), [["duplicate_filename", "pages[1].filename"], ["page_order_gap", "pages.index"]])
    add("N61", "manifest", build_manifest(indexes=[1, 3]), [["page_order_gap", "pages.index"]])
    add("N62", "manifest", build_manifest(page_list=[{**manifest_pages([1])[0], "png_sha256": ""}]), [["missing_page_hash", "pages[0].png_sha256"]])
    add("N63", "manifest", build_manifest(data_included=True), [["data_included_forbidden", "data_included"]])
    add("N64", "manifest", build_manifest(profile_id="poster-huge"), [["invalid_profile", "profile_id"]])
    add("N65", "manifest", build_manifest(render_version=""), [["missing_field", "render_version"]])
    add("N66", "manifest", build_manifest(metadata_filename=None), [["missing_field", "metadata_filename"]])
    add("N67", "manifest", build_manifest(page_list=[{"filename": "x.png", "page_role": "r", "index": 0, "width_px": 2480, "height_px": 3508, "png_sha256": "d" * 64}, manifest_pages([2])[0]]), [["page_order_gap", "pages[0].index"], ["page_order_gap", "pages.index"]])
    add("N68", "manifest", build_manifest(page_list=[{"filename": "x.png", "page_role": "r", "index": 1, "width_px": 0, "height_px": 3508, "png_sha256": "d" * 64}]), [["missing_field", "pages[0].width_px/height_px"]])
    add("N69", "manifest", build_manifest(set_id=""), [["missing_field", "set_id"]])

    # ── OO-кейсы для ORACLE-ONLY мутантов (сейчас оба канала согласны) ─
    add("O01", "snapshot", _deep(s, **{"times.timezone": " "}), [["missing_field", "times.timezone/locale"]], "research_chart")
    add("O02", "manifest", build_manifest(page_list=[{**manifest_pages([1])[0], "png_sha256": "D" * 64}]), [["missing_page_hash", "pages[0].png_sha256"]])
    add("O03", "snapshot", _deep(_snap("research_heatmap"), **{"sampling": {"applicable": False, "mode": None, "point_cap": None, "reason": "p1cert: pretend cards"}}), [["missing_sampling", "sampling"]], "research_heatmap")

    # ── U-семья: XOR-контракт isUnitDeclared (прямой пин хелпера) ──
    add("U01", "unit_decl", {"value": "usd", "reason": None}, [["unit_declared", "value"]])
    add("U02", "unit_decl", {"value": None, "reason": "legacy_unknown"}, [["unit_declared", "value"]])
    add("U03", "unit_decl", {"value": None, "reason": None}, [["unit_not_declared", "value"]])
    add("U04", "unit_decl", {"value": "usd", "reason": "dimensionless"}, [["unit_not_declared", "value"]])

    # ── F-кейсы (Класс B): свидетельства находок F-P1C1/F-P1C2 ─────
    # Ожидания — общеконтрактное поведение TS-канала (честные нарушения
    # вместо crash/acceptance); RED = Python-канал расходится.
    add("F1a", "snapshot", _deep(s, **{"print.page_count": {"__special__": "Infinity"}}), [["missing_field", "print.page_count"]], "research_chart")
    add("F1b", "snapshot", _deep(s, **{"sampling": {"applicable": True, "mode": "downsampled", "point_cap": {"__special__": "NaN"}, "reason": None}}), [["missing_point_cap", "sampling.point_cap"]], "research_chart")
    add("F1c", "snapshot", _deep(_snap("research_heatmap"), **{"display.sections.0.heatmap_scale": {"domain": [{"__special__": "Infinity"}, 1], "units": {"value": "share", "reason": None}}}), [["missing_heatmap_scale", "display.sections[0].heatmap_scale"]], "research_heatmap")
    add("F1d", "snapshot", _deep(s, **{"annotations.revision": {"__special__": "NaN"}}), [["missing_field", "annotations.revision"]], "research_chart")
    add("F2a", "manifest", build_manifest(indexes=[1, 2, 4, 5]), [["page_order_gap", "pages.index"], ["page_order_gap", "pages.index"]])
    add("F2b", "manifest", build_manifest(indexes=[0, 1]), [["page_order_gap", "pages[0].index"], ["page_order_gap", "pages.index"], ["page_order_gap", "pages.index"]])
    add("F2c", "manifest", build_manifest(indexes=[1, 1, 2]), [["duplicate_filename", "pages[1].filename"], ["page_order_gap", "pages.index"], ["page_order_gap", "pages.index"]])

    return out


def encode_specials(obj):
    """Рекурсивно заменяет маркеры {"__special__": ...} на float-значения (Python-канал)."""
    if isinstance(obj, dict):
        if set(obj.keys()) == {"__special__"}:
            marker = obj["__special__"]
            if marker == "NaN":
                return float("nan")
            if marker == "Infinity":
                return float("inf")
            if marker == "-Infinity":
                return float("-inf")
            raise ValueError(f"p1cert: unknown special marker {marker!r}")
        return {key: encode_specials(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [encode_specials(item) for item in obj]
    return obj


def ts_job() -> dict:
    """Джоб для TS-драйвера: кейсы как есть (маркеры разворачивает драйвер)."""
    return {
        "cases": [
            {"id": case["id"], "kind": case["kind"], "payload": case["payload"], "site": case["site"]}
            for case in cases()
        ]
    }


if __name__ == "__main__":
    registry_cases = cases()
    print(f"p1cert cases: {len(registry_cases)}")
    kinds = {}
    for case in registry_cases:
        kinds.setdefault(case["kind"], 0)
        kinds[case["kind"]] += 1
    print("by kind:", kinds)
    print("valid:", sum(1 for case in registry_cases if case["expected"] == []))
