# tests/api/test_pgv01_print_schema.py
"""PGV-01 (2026-10-27): print schema/metadata/profile -- Python-зеркало
print-схем (spec_passport_graphics_visual.md §6/§7/§13; строка PGV-01:
точки изменения «shared schemas, registry», критерий готовности
«Result/version/date/units/sampling обязательны по applicability,
параметры trusted»).

Источник истины -- packages/ui/print/printSchema.ts (TypeScript);
config/print_schema.json -- JSON-твин (паритет гвардится jest-оракулом
packages/ui/print/printSchema.test.ts). apps/api/print_schema.py --
Python-зеркало правил для preflight PGV-02/09 (jobs/worker): те же
обязательные refs по scope, units XOR reason, sampling по applicability,
trusted-параметры producer, манифест комплекта без raw данных.

Оракулы этого сюита:
  1) JSON-твин целостен и согласован с реестром PGV-00 (93 sites).
  2) Профили/лимиты §7: figure-landscape / A4 300 ppi 2480x3508 /
     3508x2480; согласованность px<->мм (PGV-AC16).
  3) Валидация снапшота: обязательные metadata по applicability
     (PGV-AC05/AC07/AC08), честные null-причины (PGV-AC12), trusted
     параметры, панель без смешивания (PGV-AC14), reused checkpoint
     (PGV-AC11), renderer env (PGV-AC17), sensitive-политика (PGV-AC21).
  4) Манифест: порядок/hash/data_included=false.
  5) Реестр PGV-00: research-scope сайты несут context_id+data_revision
     (уточнение required_refs -- PGV-01).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.api.print_schema import (
    MANDATORY_REFS_BY_SCOPE,
    PRINT_MANIFEST_SCHEMA_VERSION,
    PRINT_SCHEMA_DOCUMENT_VERSION,
    PRINT_SNAPSHOT_SCHEMA_VERSION,
    PRINT_RESULT_SCHEMA_VERSION,
    SamplingError,
    PrintSchemaViolation,
    load_print_schema,
    load_visual_registry,
    mandatory_ref_keys,
    profile_pixel_consistency,
    resolve_print_profile,
    resolve_scope,
    sampling_required,
    validate_print_set_manifest,
    validate_print_snapshot,
    validate_visual_result,
)

REPO = Path(__file__).resolve().parents[2]


# ── Фикстуры ─────────────────────────────────────────────────────


def _site(view_id: str) -> dict:
    registry = load_visual_registry()
    for site in registry["sites"]:
        if site["view_id"] == view_id:
            return site
    raise AssertionError(f"site not found: {view_id}")


def _units(value: str | None = "usd", reason: str | None = None) -> list[dict]:
    return [{"value": value, "reason": reason}]


def _axes() -> list[dict]:
    return [
        {"name": "Дата", "units": {"value": "date", "reason": None}, "scale": "time", "limits": None},
        {"name": "Ряд", "units": {"value": "usd", "reason": None}, "scale": "linear", "limits": None},
    ]


def _section(kind: str) -> dict:
    section = {
        "section_id": "s1",
        "renderer_kind": kind,
        "title": "Секция",
        "axes": [],
        "legend_ordering": ["series-1"],
        "table_headings": None,
        "heatmap_scale": None,
        "units": _units(),
    }
    if kind == "recharts_svg":
        section["axes"] = _axes()
    if kind == "html_table":
        section["table_headings"] = {"row": ["Строка"], "column": ["Колонка"]}
        section["units"] = _units(value=None, reason="dimensionless")
    if kind == "html_heatmap":
        section["heatmap_scale"] = {"domain": [0, 1], "units": {"value": "share", "reason": None}}
    if kind == "html_cards":
        section["units"] = _units(value=None, reason="dimensionless")
    return section


def _sections_for_kind(renderer_kind: str) -> list[dict]:
    if renderer_kind == "mixed":
        return [_section("recharts_svg"), _section("html_table")]
    return [_section(renderer_kind)]


def _snapshot(view_id: str = "upload.distribution.scatter", **overrides) -> dict:
    site = _site(view_id)
    scope = resolve_scope(site)
    refs = {ref: f"fixture:{ref}" for ref in site["required_refs"]}
    demo = scope == "demo"
    snap = {
        "schema_version": PRINT_SNAPSHOT_SCHEMA_VERSION,
        "view_id": view_id,
        "scope": scope,
        "refs": refs,
        "result": {
            "result_ref": "artifact:visual_result:fixture",
            "result_schema_version": PRINT_RESULT_SCHEMA_VERSION,
            "result_digest": "a" * 64,
            "result_digest_reason": None,
        },
        "data_artifact": {
            "artifact_id": None if demo else "artifact:fixture",
            "artifact_version": "demo-v1" if demo else "v1",
            "source_hash": None if demo else "b" * 64,
            "hash_algorithm": None if demo else "sha256",
            "hash_reason": "demo_dataset" if demo else None,
        },
        "expected_context": {
            "context_id": refs.get("context_id"),
            "data_revision": refs.get("data_revision"),
            "expected_data_digest": None,
        },
        "dimensions": {
            "target_column": refs.get("target_column"),
            "date_column": refs.get("date_column"),
            "entity_column": refs.get("entity_column"),
            "entity_id": refs.get("entity"),
            "mode": "panel" if site["applicability"] == "panel" else "univariate",
        },
        "times": {
            "computed_at": "2026-10-27T00:00:00Z",
            "computed_at_reason": None,
            "captured_at": "2026-10-27T00:00:00Z",
            "captured_at_reason": None,
            "checkpoint_confirmed_at": None,
            "render_requested_at": "2026-10-27T00:00:01Z",
            "timezone": "UTC",
            "locale": "ru-RU",
        },
        "checkpoint": None,
        "display": {
            "title": view_id,
            "subtitle": None,
            "detail_level": "compact",
            "sections": _sections_for_kind(site["renderer_kind"]),
        },
        "method": {"origin": "producer_freeze", "method": "fixture", "parameters": {}},
        "selection": {"allowlist": list(site["view_params"]), "values": {}},
        "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
        "annotations": {"revision": 0, "author": "analyst", "text": None},
        "print": {"profile_id": "figure-landscape", "page_count": 1, "theme": "light-print"},
        "renderer_env": {
            "renderer_version": "print-renderer-fixture/1",
            "font_profile": "dejavu-sans/1",
            "dependency_status": "available",
            "unavailable_reason": None,
        },
        "data_flow": {"before_revision": None, "after_revision": None},
        "sensitive": {"raw_data_included": False, "sensitive_fields_policy": "redacted"},
        "warnings": [],
    }
    if not sampling_required(site):
        snap["sampling"] = {"applicable": False, "mode": None, "point_cap": None, "reason": "cards_view_no_series"}
    if scope == "demo":
        snap["expected_context"] = {"context_id": None, "data_revision": None, "expected_data_digest": None}
    snap.update(overrides)
    return snap


def _manifest(pages: int = 2, **overrides) -> dict:
    manifest = {
        "schema_version": PRINT_MANIFEST_SCHEMA_VERSION,
        "set_id": "set-0001",
        "render_version": "print-renderer/1",
        "profile_id": "a4-portrait",
        "pages": [
            {
                "filename": f"page-{i:02d}.png",
                "page_role": "passport.groups",
                "index": i,
                "width_px": 2480,
                "height_px": 3508,
                "png_sha256": "a" * 64,
            }
            for i in range(1, pages + 1)
        ],
        "metadata_filename": "metadata.json",
        "dependencies": [],
        "data_included": False,
    }
    manifest.update(overrides)
    return manifest


def _result(**overrides) -> dict:
    result = {
        "schema_version": PRINT_RESULT_SCHEMA_VERSION,
        "view_id": "upload.chart.series",
        "payload": {"kind": "recharts_svg", "series_cap": None, "digest": "b" * 64, "digest_reason": None},
        "parameters": {"origin": "producer_freeze", "method": "line", "parameters": {}},
        "units": _units(),
        "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
        "warnings": [],
        "execution": {
            "execution_ref": "exec-1",
            "result_ref": "artifact:visual_result:1",
            "computed_at": "2026-10-27T00:00:00Z",
            "computed_at_reason": None,
        },
    }
    result.update(overrides)
    return result


def codes(violations: list[PrintSchemaViolation]) -> list[str]:
    return [v.code for v in violations]


# ── 1. JSON-твин и версии схем ───────────────────────────────────


class TestPrintSchemaTwin:
    def test_twin_loads_with_pinned_versions(self):
        doc = load_print_schema()
        assert doc["schema_version"] == PRINT_SCHEMA_DOCUMENT_VERSION == "pgv.print_schema/1"
        assert doc["generated_from"] == "packages/ui/print/printSchema.ts"
        assert doc["pgv_task"] == "PGV-01"
        assert doc["schema_versions"]["visual_result"] == "pgv.visual_result/1"
        assert doc["schema_versions"]["visual_print_snapshot"] == "pgv.visual_print_snapshot/1"
        assert doc["schema_versions"]["print_manifest"] == "pgv.print_manifest/1"

    def test_twin_consistent_with_pgv00_registry(self):
        registry = load_visual_registry()
        assert registry["schema_version"] == "pgv.visual_registry/1"
        assert registry["total_sites"] == 93


# ── 2. Профили и лимиты (spec §7, PGV-AC16) ──────────────────────


class TestProfilesAndLimits:
    def test_three_profiles_with_exact_a4_pixels(self):
        doc = load_print_schema()
        assert [p["id"] for p in doc["profiles"]] == ["figure-landscape", "a4-portrait", "a4-landscape"]
        portrait = resolve_print_profile("a4-portrait")
        landscape = resolve_print_profile("a4-landscape")
        assert (portrait["width_px"], portrait["height_px"]) == (2480, 3508)
        assert (landscape["width_px"], landscape["height_px"]) == (3508, 2480)
        assert all(p["ppi"] == 300 for p in doc["profiles"])

    def test_pixel_mm_consistency(self):
        doc = load_print_schema()
        for profile in doc["profiles"]:
            assert profile_pixel_consistency(profile), profile["id"]

    def test_unknown_profile_not_resolved(self):
        assert resolve_print_profile("poster-huge") is None
        assert resolve_print_profile("") is None

    def test_limits_pinned(self):
        doc = load_print_schema()
        assert doc["limits"] == {
            "max_megapixels_per_page": 12,
            "max_pages_per_set": 20,
            "max_output_bytes": 52428800,
            "render_timeout_s": 60,
            "concurrency_per_tenant": 1,
            "concurrency_global": 2,
        }


# ── 3. Scope и обязательные refs (version по applicability) ──────


class TestScopeAndRefs:
    def test_scope_resolution_from_registry(self):
        assert resolve_scope(_site("navigator.upload.chart.series")) == "demo"
        assert resolve_scope(_site("upload.distribution.scatter")) == "research"
        assert resolve_scope(_site("upload.passport.panel")) == "passport"
        assert resolve_scope(_site("forecasting.monitoring.d12")) == "comparison"

    def test_mandatory_refs_by_scope_pinned(self):
        assert MANDATORY_REFS_BY_SCOPE["demo"] == ["demo_dataset_id"]
        assert MANDATORY_REFS_BY_SCOPE["research"] == ["context_id", "data_revision"]
        assert MANDATORY_REFS_BY_SCOPE["passport"] == [
            "context_id",
            "snapshot_id",
            "data_revision",
            "schema_version",
        ]
        assert MANDATORY_REFS_BY_SCOPE["comparison"] == ["research_run_id", "comparison_id"]

    def test_research_sites_missing_data_revision(self):
        """Уточнение required_refs PGV-01: research-scope сайты несут version."""
        gaps = []
        for site in load_visual_registry()["sites"]:
            if resolve_scope(site) != "research":
                continue
            refs = set(site["required_refs"])
            for ref in MANDATORY_REFS_BY_SCOPE["research"]:
                if ref not in refs:
                    gaps.append(f"{site['view_id']}:-{ref}")
        assert gaps == []

    def test_snapshot_missing_declared_ref_is_violation(self):
        site = _site("forecasting.forecast.chart")
        snap = _snapshot("forecasting.forecast.chart")
        snap["refs"] = {k: v for k, v in snap["refs"].items() if k != "forecast_artifact_ref"}
        assert "missing_required_ref" in codes(validate_print_snapshot(snap, site))


# ── 4. Валидация снапшота: metadata по applicability ─────────────


class TestSnapshotValidation:
    def test_valid_snapshot_for_every_registry_site(self):
        problems = []
        for site in load_visual_registry()["sites"]:
            violations = validate_print_snapshot(_snapshot(site["view_id"]), site)
            if violations:
                problems.append(f"{site['view_id']}:{','.join(v.code for v in violations)}")
        assert problems == []

    def test_missing_date_without_reason(self):
        site = _site("upload.distribution.scatter")
        snap = _snapshot()
        snap["times"]["computed_at"] = None
        snap["times"]["computed_at_reason"] = None
        assert "missing_date" in codes(validate_print_snapshot(snap, site))
        snap["times"]["computed_at_reason"] = "legacy_unknown"
        assert validate_print_snapshot(snap, site) == []

    def test_missing_result_ref(self):
        site = _site("upload.distribution.scatter")
        snap = _snapshot()
        snap["result"]["result_ref"] = ""
        assert "missing_result_ref" in codes(validate_print_snapshot(snap, site))

    def test_units_xor_reason_in_axes(self):
        site = _site("upload.chart.series")
        snap = _snapshot("upload.chart.series")
        assert validate_print_snapshot(snap, site) == []
        snap["display"]["sections"][0]["axes"][0]["units"] = {"value": None, "reason": None}
        assert "missing_units" in codes(validate_print_snapshot(snap, site))
        snap["display"]["sections"][0]["axes"][0]["units"] = {"value": "usd", "reason": "dimensionless"}
        assert "ambiguous_unit" in codes(validate_print_snapshot(snap, site))

    def test_table_headings_mandatory(self):
        site = _site("upload.overview.preview")
        snap = _snapshot("upload.overview.preview")
        assert validate_print_snapshot(snap, site) == []
        snap["display"]["sections"][0]["table_headings"] = None
        assert "missing_table_headings" in codes(validate_print_snapshot(snap, site))

    def test_heatmap_scale_mandatory(self):
        site = _site("eda.feature_select.matrix")
        snap = _snapshot("eda.feature_select.matrix")
        assert validate_print_snapshot(snap, site) == []
        snap["display"]["sections"][0]["heatmap_scale"] = None
        assert "missing_heatmap_scale" in codes(validate_print_snapshot(snap, site))

    def test_sampling_required_and_point_cap(self):
        site = _site("upload.chart.series")
        snap = _snapshot("upload.chart.series")
        snap["sampling"] = {"applicable": False, "mode": None, "point_cap": None, "reason": None}
        assert "missing_sampling" in codes(validate_print_snapshot(snap, site))
        snap["sampling"] = {"applicable": True, "mode": "downsampled", "point_cap": None, "reason": None}
        assert "missing_point_cap" in codes(validate_print_snapshot(snap, site))
        snap["sampling"] = {"applicable": True, "mode": "downsampled", "point_cap": 500, "reason": None}
        assert validate_print_snapshot(snap, site) == []

    def test_sampling_not_applicable_only_for_cards(self):
        site = _site("upload.quality.teaser")
        snap = _snapshot("upload.quality.teaser")
        assert snap["sampling"]["applicable"] is False
        assert snap["sampling"]["reason"]
        assert validate_print_snapshot(snap, site) == []
        # График с not applicable -- нарушение.
        chart_site = _site("upload.chart.series")
        chart_snap = _snapshot("upload.chart.series", sampling={"applicable": False, "mode": None, "point_cap": None, "reason": "x"})
        assert "missing_sampling" in codes(validate_print_snapshot(chart_snap, chart_site))


# ── 5. Trusted-параметры и allowlist selection ───────────────────


class TestTrustedParameters:
    def test_client_origin_rejected(self):
        site = _site("upload.chart.series")
        snap = _snapshot("upload.chart.series")
        snap["method"]["origin"] = "client_request"
        assert "untrusted_parameter_origin" in codes(validate_print_snapshot(snap, site))

    def test_selection_outside_allowlist_rejected(self):
        site = _site("upload.chart.series")
        snap = _snapshot("upload.chart.series")
        snap["selection"]["allowlist"] = list(site["view_params"]) + ["authoritative_series_override"]
        assert "selection_not_allowlisted" in codes(validate_print_snapshot(snap, site))

    def test_selection_within_view_params_ok(self):
        site = _site("forecasting.forecast.chart")
        snap = _snapshot("forecasting.forecast.chart")
        snap["selection"]["values"] = {"origin": "2025-01", "horizon": 12}
        assert validate_print_snapshot(snap, site) == []


# ── 6. Панель (PGV-AC14) и checkpoint (PGV-AC11) ─────────────────


class TestPanelAndCheckpoint:
    def test_panel_view_requires_entity(self):
        site = _site("modeling.panel.metrics")
        snap = _snapshot("modeling.panel.metrics")
        assert snap["dimensions"]["mode"] == "panel"
        assert snap["dimensions"]["entity_column"]
        assert validate_print_snapshot(snap, site) == []

    def test_entity_on_univariate_view_is_mixing(self):
        site = _site("upload.chart.series")
        snap = _snapshot("upload.chart.series")
        snap["dimensions"]["entity_id"] = "Kazakhstan"
        assert "panel_mixing" in codes(validate_print_snapshot(snap, site))

    def test_reused_checkpoint_needs_confirmation(self):
        site = _site("eda.passport.panel")
        snap = _snapshot(
            "eda.passport.panel",
            checkpoint={"reused": True, "source_snapshot_ref": "snapshot:fixture"},
            times_overridden=True,
        )
        snap["times"]["checkpoint_confirmed_at"] = "2026-10-27T12:00:00Z"
        assert validate_print_snapshot(snap, site) == []
        snap["times"]["checkpoint_confirmed_at"] = None
        snap["checkpoint"]["source_snapshot_ref"] = None
        assert "missing_checkpoint_confirmation" in codes(validate_print_snapshot(snap, site))


# ── 7. Renderer env и sensitive-политика ─────────────────────────


class TestRendererEnvAndSensitive:
    def test_unavailable_dependency_requires_reason(self):
        site = _site("upload.chart.series")
        snap = _snapshot("upload.chart.series")
        snap["renderer_env"]["dependency_status"] = "unavailable"
        snap["renderer_env"]["unavailable_reason"] = None
        assert "missing_renderer_reason" in codes(validate_print_snapshot(snap, site))
        snap["renderer_env"]["unavailable_reason"] = "print_renderer_not_deployed"
        assert validate_print_snapshot(snap, site) == []

    def test_raw_data_included_forbidden(self):
        site = _site("upload.chart.series")
        snap = _snapshot("upload.chart.series")
        snap["sensitive"]["raw_data_included"] = True
        assert "raw_data_included_forbidden" in codes(validate_print_snapshot(snap, site))

    def test_schema_version_mismatch(self):
        site = _site("upload.chart.series")
        snap = _snapshot("upload.chart.series")
        snap["schema_version"] = "pgv.visual_print_snapshot/2"
        assert "schema_version_mismatch" in codes(validate_print_snapshot(snap, site))


# ── 8. Манифест комплекта (PGV-AC21) ─────────────────────────────


class TestManifest:
    def test_valid_manifest(self):
        assert validate_print_set_manifest(_manifest()) == []

    def test_duplicate_filename_and_order_gap(self):
        dup = _manifest(pages=1)
        dup["pages"].append(dict(dup["pages"][0], index=2))
        assert "duplicate_filename" in codes(validate_print_set_manifest(dup))
        gap = _manifest()
        gap["pages"][1]["index"] = 3
        assert "page_order_gap" in codes(validate_print_set_manifest(gap))

    def test_missing_hash_and_data_included(self):
        no_hash = _manifest(pages=1)
        no_hash["pages"][0]["png_sha256"] = ""
        assert "missing_page_hash" in codes(validate_print_set_manifest(no_hash))
        assert "data_included_forbidden" in codes(validate_print_set_manifest(_manifest(data_included=True)))


# ── 9. VisualResult/1 ────────────────────────────────────────────


class TestVisualResult:
    def test_valid_result(self):
        assert validate_visual_result(_result()) == []

    def test_client_origin_rejected(self):
        assert "untrusted_parameter_origin" in codes(
            validate_visual_result(_result(parameters={"origin": "client_request", "method": "line", "parameters": {}}))
        )

    def test_digest_xor_reason(self):
        broken = _result(payload={"kind": "recharts_svg", "series_cap": None, "digest": None, "digest_reason": None})
        assert "missing_digest" in codes(validate_visual_result(broken))


# ── 10. Согласованность зеркала с реестром (sanity) ──────────────


class TestMirrorConsistency:
    def test_sampling_rules_match_registry_kinds(self):
        for site in load_visual_registry()["sites"]:
            expected = site["renderer_kind"] != "html_cards"
            assert sampling_required(site) == expected, site["view_id"]

    def test_scope_mandatory_refs_cover_declared_refs(self):
        """Каждый сайт реестра несёт все обязательные refs своей scope."""
        for site in load_visual_registry()["sites"]:
            refs = set(site["required_refs"])
            for ref in mandatory_ref_keys(site):
                assert ref in refs, f"{site['view_id']}:-{ref}"
