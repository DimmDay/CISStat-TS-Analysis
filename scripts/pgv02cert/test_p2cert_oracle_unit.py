# scripts/pgv02cert/test_p2cert_oracle_unit.py
"""Class A unit-оракулы: валидаторы/конвенции/каталог на СВОИХ данных.

GREEN на цели 2f412d6; RED на родителе 0f8b9a0 (нет apps.api.visual_artifacts).
"""
from __future__ import annotations

import sys
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CERT_DIR.parents[1]
sys.path.insert(0, str(CERT_DIR))

import pytest

from p2cases import (
    ARTIFACT_MISSING,
    CHECKPOINT_ID,
    CTX_A,
    RUN_A,
    VIEW_DEMO_KDE,
    VIEW_RESEARCH_CHART,
    VIEW_RESEARCH_HEATMAP,
    checkpoint_payload,
    print_snapshot_payload,
    visual_result_payload,
)


def codes(violations) -> list[str]:
    return [v.code for v in violations]


def paths_of(violations, code: str) -> list[str]:
    return [v.path for v in violations if v.code == code]


# ══════════════════════════════════════════════════════════════════════
# pgv.passport_checkpoint/1 -- правила честности §8 (AC11/AC12/AC14)
# ══════════════════════════════════════════════════════════════════════


class TestCheckpointValidatorOwnData:
    def test_u01_valid_modeling_entry(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        assert validate_passport_checkpoint(checkpoint_payload()) == []

    def test_u02_valid_panel_entry_with_entity(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = checkpoint_payload(
            CHECKPOINT_ID,
            stage="panel_entry",
            flags={"created": True, "reused": False, "unchanged": False},
            entity_id="region-north",
        )
        assert validate_passport_checkpoint(payload) == []

    def test_u03_missing_confirmed_at_is_gap_not_fabrication(self):
        # AC12: нет даты и нет причины -> missing_date, а не подстановка
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = checkpoint_payload(confirmed_at=None, confirmed_at_reason=None)
        assert "missing_date" in codes(validate_passport_checkpoint(payload))

    def test_u04_legacy_unknown_reason_is_honest(self):
        # AC12: утраченная дата легаси -- явная причина, валидно
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = checkpoint_payload(confirmed_at=None, confirmed_at_reason="legacy_unknown")
        assert validate_passport_checkpoint(payload) == []

    def test_u05_date_and_reason_are_exclusive(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = checkpoint_payload(
            confirmed_at="2026-10-28T10:00:00Z", confirmed_at_reason="legacy_unknown"
        )
        assert "ambiguous_source_hash" in codes(validate_passport_checkpoint(payload))

    def test_u06_neither_created_nor_reused_is_conflict(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = checkpoint_payload(flags={"created": False, "reused": False, "unchanged": False})
        out = validate_passport_checkpoint(payload)
        assert "conflicting_flags" in codes(out)

    def test_u07_reused_requires_source_snapshot_ref(self):
        # AC11: reused обязан нести ссылку на исходный снимок; valid при
        # reused-флагах -- подтверждение + ссылка, без четвёртой копии
        from apps.api.visual_artifacts import validate_passport_checkpoint

        reused = dict(
            flags={"created": False, "reused": True, "unchanged": False},
            previous_snapshot_ref="rs-" + "b3" * 16,
        )
        assert validate_passport_checkpoint(checkpoint_payload(**reused)) == []

    def test_u08_unchanged_plus_created_is_fourth_copy(self):
        # AC11: unchanged не создаёт новую физическую копию паспорта
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = checkpoint_payload(
            flags={"created": True, "reused": False, "unchanged": True}
        )
        out = validate_passport_checkpoint(payload)
        assert "conflicting_flags" in codes(out)
        assert any("flags.unchanged" in p for p in paths_of(out, "conflicting_flags"))

    def test_u09_unchanged_requires_reused(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = checkpoint_payload(
            flags={"created": False, "reused": False, "unchanged": True}
        )
        assert codes(validate_passport_checkpoint(payload)).count("conflicting_flags") >= 2

    def test_u10_modeling_entry_requires_all_stage_refs(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        base = checkpoint_payload()
        for missing in ("start", "validation", "exit"):
            refs = dict(base["stage_refs"])
            refs.pop(missing)
            payload = checkpoint_payload(stage_refs=refs)
            assert paths_of(validate_passport_checkpoint(payload), "missing_required_ref") == [
                f"stage_refs.{missing}"
            ], f"missing {missing}"

    def test_u11_bad_rs_format_in_stage_refs(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = checkpoint_payload(
            stage_refs={"start": "snapshot-1", "validation": "rs-" + "d5" * 16, "exit": "rs-" + "e6" * 16}
        )
        out = validate_passport_checkpoint(payload)
        assert paths_of(out, "invalid_value") == ["stage_refs.start"]

    def test_u12_panel_entry_without_entity_is_mixing(self):
        # AC14: панели не смешиваются с single-series
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = checkpoint_payload(
            CHECKPOINT_ID,
            stage="panel_entry",
            entity_id=None,
        )
        out = validate_passport_checkpoint(payload)
        assert "panel_mixing" in codes(out)
        assert paths_of(out, "panel_mixing") == ["context.entity_id"]

    def test_u13_panel_entry_requires_panel_stage_ref(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = checkpoint_payload(
            CHECKPOINT_ID,
            stage="panel_entry",
            entity_id="region-north",
            stage_refs={"start": "rs-" + "c4" * 16},
        )
        out = validate_passport_checkpoint(payload)
        assert paths_of(out, "missing_required_ref") == ["stage_refs.panel"]

    def test_u14_unknown_stage_rejected(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = checkpoint_payload(stage="eda_entry")
        assert "invalid_value" in codes(validate_passport_checkpoint(payload))

    def test_u15_schema_version_pin(self):
        from apps.api.visual_artifacts import CHECKPOINT_SCHEMA_VERSION, validate_passport_checkpoint

        assert CHECKPOINT_SCHEMA_VERSION == "pgv.passport_checkpoint/1"
        payload = checkpoint_payload(schema_version="pgv.passport_checkpoint/2")
        assert "schema_version_mismatch" in codes(validate_passport_checkpoint(payload))

    def test_u16_checkpoint_id_format_pck(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        # пустая строка -- отсутствие значения (missing_field), не формат
        empty = checkpoint_payload(checkpoint_id="")
        assert codes(validate_passport_checkpoint(empty)) == ["missing_field"]
        for bad in ("ckpt-1", "pck-", "pck-слэнг"):
            payload = checkpoint_payload(checkpoint_id=bad)
            assert "invalid_value" in codes(validate_passport_checkpoint(payload)), bad

    def test_u17_provenance_sources_catalog(self):
        from apps.api.visual_artifacts import PROVENANCE_SOURCES, validate_passport_checkpoint

        assert PROVENANCE_SOURCES == ("producer_capture", "legacy_import", "session_replay")
        ok = checkpoint_payload(provenance={"source": "legacy_import"})
        assert validate_passport_checkpoint(ok) == []
        bad = checkpoint_payload(provenance={"source": "guessed"})
        assert paths_of(validate_passport_checkpoint(bad), "invalid_value") == ["provenance.source"]

    def test_u18_non_dict_checkpoint(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        assert codes(validate_passport_checkpoint(["nope"])) == ["missing_field"]

    def test_u19_previous_ref_format(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = checkpoint_payload(previous_snapshot_ref="rs:legacy")
        assert paths_of(validate_passport_checkpoint(payload), "invalid_value") == [
            "previous_snapshot_ref"
        ]

    def test_u20_snapshot_ref_required(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = checkpoint_payload(snapshot_ref=None)
        assert paths_of(validate_passport_checkpoint(payload), "missing_required_ref") == [
            "snapshot_ref"
        ]

    def test_u21_context_required_refs(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        base = checkpoint_payload()
        for key in ("run_id", "context_id", "data_revision"):
            ctx = dict(base["context"])
            ctx.pop(key)
            payload = checkpoint_payload(context=ctx)
            assert paths_of(validate_passport_checkpoint(payload), "missing_required_ref") == [
                f"context.{key}"
            ], key

    def test_u22_context_revision_zero_is_value_not_absence(self):
        # 0 -- легитимное значение ревизии; None/отсутствие -- пропуск
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = checkpoint_payload(context_revision=0)
        assert validate_passport_checkpoint(payload) == []


# ══════════════════════════════════════════════════════════════════════
# Конвенции producer_key (идемпотентность §8/§11) и диспетчер валидации
# ══════════════════════════════════════════════════════════════════════


class TestProducerKeyConventions:
    def test_u23_visual_result_key_identity(self):
        from apps.api.visual_artifacts import visual_result_producer_key

        payload = visual_result_payload(result_ref="session:p2cert:hist:v9")
        assert (
            visual_result_producer_key(payload)
            == "pgv.visual_result:upload.distribution.histogram:session:p2cert:hist:v9"
        )

    def test_u24_print_snapshot_key_digest_xor_reason(self):
        from apps.api.visual_artifacts import print_snapshot_producer_key

        snap = print_snapshot_payload(result_digest="88" * 32)
        assert (
            print_snapshot_producer_key(snap)
            == f"pgv.print_snapshot:{VIEW_RESEARCH_CHART}:{'88' * 32}"
        )
        # reason-ветка -- подмена на уровне result (не корня снапшота)
        reason_snap = print_snapshot_payload()
        reason_snap["result"] = {
            **reason_snap["result"],
            "result_digest": None,
            "result_digest_reason": "legacy_unknown",
        }
        assert print_snapshot_producer_key(reason_snap).endswith(":legacy_unknown")

    def test_u25_checkpoint_key_by_id(self):
        from apps.api.visual_artifacts import checkpoint_producer_key

        assert (
            checkpoint_producer_key(checkpoint_payload())
            == f"pgv.checkpoint:{CHECKPOINT_ID}"
        )


class TestPayloadDispatcher:
    def test_u26_unknown_kind_rejected(self):
        from apps.api.visual_artifacts import validate_visual_artifact_payload

        out = validate_visual_artifact_payload("passport", {})
        assert codes(out) == ["invalid_value"]

    def test_u27_visual_result_unknown_view(self):
        from apps.api.visual_artifacts import validate_visual_artifact_payload

        payload = visual_result_payload(view_id="future.module.chart")
        assert "unknown_view" in codes(validate_visual_artifact_payload("visual_result", payload))

    def test_u28_print_snapshot_unknown_view(self):
        from apps.api.visual_artifacts import validate_visual_artifact_payload

        payload = print_snapshot_payload()  # валидный research-снапшот
        payload["view_id"] = "future.module.chart"  # вне реестра PGV-00
        assert "unknown_view" in codes(validate_visual_artifact_payload("visual_print_snapshot", payload))

    def test_u29_valid_payloads_of_three_kinds_clean(self):
        from apps.api.visual_artifacts import validate_visual_artifact_payload

        assert validate_visual_artifact_payload("visual_result", visual_result_payload()) == []
        assert (
            validate_visual_artifact_payload("visual_print_snapshot", print_snapshot_payload())
            == []
        )
        assert validate_visual_artifact_payload("passport_checkpoint", checkpoint_payload()) == []


# ══════════════════════════════════════════════════════════════════════
# Versioned каталог pgv.document_catalog/2 (§10.2)
# ══════════════════════════════════════════════════════════════════════


class TestDocumentCatalog:
    def test_u30_catalog_version_and_kinds(self):
        from apps.api.report_snapshot import (
            DOCUMENT_CATALOG_VERSION,
            PRINT_DOCUMENT_KINDS,
        )

        assert DOCUMENT_CATALOG_VERSION == "pgv.document_catalog/2"
        assert PRINT_DOCUMENT_KINDS == {
            "V01": ("scientific_visual", "Научная визуализация"),
            "P01": ("passport_print", "Паспорта свойств ряда"),
            "P02": ("passport_comparison", "Сравнение паспортов"),
        }

    def test_u31_kind_family_total_function(self):
        from apps.api.report_snapshot import document_kind_family, is_print_document_kind

        assert document_kind_family("V01") == "print_document"
        assert document_kind_family("P02") == "print_document"
        assert document_kind_family("D02") == "snapshot_section"
        assert document_kind_family("D99") is None
        assert document_kind_family(None) is None
        assert document_kind_family(7) is None
        assert is_print_document_kind("P01") is True
        assert is_print_document_kind("D02") is False

    def test_u32_resolve_kinds_rejects_print_kinds_with_hint(self):
        # §10.2: печатные ревизии идут мимо снапшот-сборщика
        from apps.api.report_snapshot import DOCUMENT_CATALOG_VERSION, resolve_kinds

        for code in ("V01", "P01", "P02"):
            with pytest.raises(ValueError) as excinfo:
                resolve_kinds([code])
            assert DOCUMENT_CATALOG_VERSION in str(excinfo.value)
            assert "печатный" in str(excinfo.value)

    def test_u33_d02_is_not_renamed_into_p01(self):
        from apps.api.report_snapshot import DOCUMENT_KINDS, PRINT_DOCUMENT_KINDS

        assert DOCUMENT_KINDS["D02"][0] == "source_passport"
        assert PRINT_DOCUMENT_KINDS["P01"][0] == "passport_print"
        assert "P01" not in DOCUMENT_KINDS
        assert "D02" not in PRINT_DOCUMENT_KINDS

    def test_u34_legacy_document_kinds_untouched(self):
        from apps.api.report_snapshot import DOCUMENT_KINDS

        expected = {
            "D01": "plan",
            "D02": "source_passport",
            "D03": "quality_protocol",
            "D04": "transformation_recipe",
            "D05": "eda_note",
            "D06": "experiment_protocol",
            "D07": "model_card",
            "D08": "forecast_release",
            "D09": "panel_appendix",
            "D10": "recommendations_limits",
            "D11": "final_report",
            "D12": "forecast_vs_actual",
        }
        assert {code: kind[0] for code, kind in DOCUMENT_KINDS.items()} == expected

    def test_u35_expected_revision_raw_variants_parse(self):
        # CAS-парсер снапшота: строка-цифра по контракту PGV-01 + допуск int
        from apps.api.print_schema import resolve_scope

        site = None
        from apps.api.print_schema import load_visual_registry

        for s in load_visual_registry()["sites"]:
            if s["view_id"] == VIEW_RESEARCH_CHART:
                site = s
        assert resolve_scope(site) == "research"
        snap_int = print_snapshot_payload(expected_revision_raw=7)
        snap_str = print_snapshot_payload(expected_revision_raw="7")
        assert snap_int["expected_context"]["data_revision"] == 7
        assert snap_str["expected_context"]["data_revision"] == "7"


# ══════════════════════════════════════════════════════════════════════
# Ошибки durable-слоя (роутер-маппинг PGV-13/15: 409/422)
# ══════════════════════════════════════════════════════════════════════


class TestErrorSemantics:
    def test_u36_conflict_carries_context_changed_code(self):
        from apps.api.visual_artifacts import PrintContextConflict

        exc = PrintContextConflict("тест")
        assert exc.error_code == "context_changed"

    def test_u37_payload_invalid_lists_stable_codes(self):
        from apps.api.visual_artifacts import ArtifactPayloadInvalid

        exc = ArtifactPayloadInvalid([])
        assert exc.violations == []
        assert "visual artifact payload invalid" in str(exc)
