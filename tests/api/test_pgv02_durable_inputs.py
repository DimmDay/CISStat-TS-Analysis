# tests/api/test_pgv02_durable_inputs.py
"""Task PGV-02 (spec_passport_graphics_visual.md §6/§8/§10.2/§13, строка
PGV-02): durable inputs -- устойчивые print-артефакты визуализаций и
паспортов + печатные типы документов V01/P01/P02.

Точки изменения (spec §13): «artifact_store / report_snapshot / SQL /
validators». Критерий готовности: «Versioned migrations и legacy
D01-D12/readers работают».

Что фиксирует сюита (оракулы на СВОИХ данных, RUN-P02xxxxxx):
  1) Новые kinds durable-слоя: visual_result / visual_print_snapshot /
     passport_checkpoint (spec §6 «Новый kind visual_result расширяет
     schema/migrations/pins/tests»; §8 «Новый artifact kind
     passport_checkpoint») -- регистрация, schema_version пины, legacy
     kinds не задеты.
  2) Валидаторы payload (validators): pgv.visual_result/1 и
     pgv.visual_print_snapshot/1 -- зеркало print_schema PGV-01;
     pgv.passport_checkpoint/1 -- новый контракт §8 (checkpoint_id,
     stage, confirmed_at, snapshot/previous refs, flags, точные
     stage-refs, context). Честные отказы: reused/unchanged требуют
     подтверждение и ссылку на исходный снимок (PGV-AC11), missing
     confirmed_at -- violation, а не выдуманная дата (PGV-AC12),
     panel_entry отдельно от single-series (PGV-AC14).
  3) Freeze-семантика: идемпотентность по producer_key (AC09-дух),
     CAS expected_context -- расхождение контекста при freeze даёт
     честный конфликт 409-семантики, а не смешанный print (PGV-AC07);
     повторный freeze изменившегося состояния -- НОВЫЙ immutable
     артефакт, старый не переписывается.
  4) Durable read без session/Redis: артефакты и чекпоинты читаются из
     реестра/ObjectStore после утраты сессии (субстрат PGV-AC09; полный
     reader -- PGV-05).
  5) Versioned каталог документов: PRINT_DOCUMENT_KINDS V01/P01/P02
     (spec §10.2 «аддитивные типы ... не переименование D02»),
     DOCUMENT_KINDS D01-D12 не тронут (пины DOCLOG-2/8), resolve_kinds
     печатные типы НЕ резолвит (их ревизии идут мимо снапшот-сборщика).
  6) Печатные ревизии: document_print_revisions -- basis = frozen
     print-inputs (артефакты), идемпотентность по basis_fingerprint,
     pins basis-артефактов; legacy-поток document_revisions работает
     как прежде.
  7) Миграция 0016 versioned: каталог MIGRATION_STATEMENTS_0016 +
     файл-дубль migrations/0016_pgv2_print_documents.sql (паритет,
     паттерн PROGR-5.1), сумма групп == полный каталог.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.api import research_runs
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
from apps.api.research_runs import ResearchRun
from apps.api.print_schema import PrintSchemaViolation

# ── Изоляция КАЖДОГО теста (паттерн test_doclog1_artifacts.py) ────────


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    monkeypatch.delenv("CISSTAT_ARTIFACTS_BACKEND", raising=False)
    research_runs.reset_research_run_store_for_testing()
    from apps.api import artifact_store
    from apps.api.document_jobs import reset_document_registry_for_testing
    from apps.api.session_store import reset_session_store_for_testing

    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    reset_document_registry_for_testing()
    reset_session_store_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    reset_document_registry_for_testing()
    reset_session_store_for_testing()


# ── Сид-хелперы на СВОИХ данных ──────────────────────────────────────

RUN_ID = "RUN-P02A0001"
SESSION_ID = "p02-seed-session"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_run(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    context_id: str | None = None,
    data_revision: int | None = None,
) -> ResearchRun:
    """Сид запуска; ResearchRun иммутабелен -- контекст через replace()."""
    from dataclasses import replace as dc_replace

    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="p02" * 8,
        dataset_name="pgv02-durable-inputs-seed",
        target_column="value",
        created_at=_now(),
        last_active_at=_now(),
        status="active",
        owner_subject=SubjectRef.from_session(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    if context_id is not None or data_revision is not None:
        run = dc_replace(
            run,
            context_id=context_id if context_id is not None else run.context_id,
            data_revision=(
                data_revision if data_revision is not None else run.data_revision
            ),
        )
    get_research_run_store().upsert_run(run)
    return run


def _owner_subject(session_id: str = SESSION_ID) -> SubjectRef:
    return SubjectRef.from_session(session_id)


# ── Фикстуры payload'ов (валидные по PGV-01 правилам) ────────────────

VIEW_SCATTER = "upload.distribution.scatter"  # research-scope, recharts_svg


def _site(view_id: str) -> dict:
    from apps.api.print_schema import load_visual_registry

    for site in load_visual_registry()["sites"]:
        if site["view_id"] == view_id:
            return site
    raise AssertionError(f"site not found: {view_id}")


def _visual_result(view_id: str = VIEW_SCATTER, **overrides) -> dict:
    from apps.api.print_schema import PRINT_RESULT_SCHEMA_VERSION

    result = {
        "schema_version": PRINT_RESULT_SCHEMA_VERSION,
        "view_id": view_id,
        "payload": {
            "kind": "recharts_svg",
            "series_cap": None,
            "digest": "a" * 64,
            "digest_reason": None,
        },
        "parameters": {"origin": "producer_freeze", "method": "scatter", "parameters": {}},
        "units": [{"value": "usd", "reason": None}],
        "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
        "warnings": [],
        "execution": {
            "execution_ref": "exec-p02-1",
            "result_ref": "session:upload.distribution.scatter:v7",
            "computed_at": "2026-10-28T09:00:00Z",
            "computed_at_reason": None,
        },
    }
    result.update(overrides)
    return result


def _print_snapshot(
    view_id: str = VIEW_SCATTER,
    *,
    result_digest: str = "a" * 64,
    context_id: str | None = "ctx-p02-1",
    data_revision: int | None = 7,
    **overrides,
) -> dict:
    """Валидный VisualPrintSnapshot/1 (правила PGV-01; сборка по сайту
    реестра PGV-00)."""
    from apps.api.print_schema import PRINT_SNAPSHOT_SCHEMA_VERSION

    site = _site(view_id)
    from apps.api.print_schema import resolve_scope

    scope = resolve_scope(site)
    refs = {ref: f"p02:{ref}" for ref in site["required_refs"]}
    if scope == "research":
        refs.setdefault("context_id", context_id or "ctx-p02-1")
        refs.setdefault("data_revision", str(data_revision or 7))
    demo = scope == "demo"

    def _units(value: str | None, reason: str | None = None) -> list[dict]:
        return [{"value": value, "reason": reason}]

    section = {
        "section_id": "s1",
        "renderer_kind": "recharts_svg",
        "title": "Диаграмма рассеяния",
        "axes": [
            {"name": "Дата", "units": {"value": "date", "reason": None}, "scale": "time", "limits": None},
            {"name": "Ряд", "units": {"value": "usd", "reason": None}, "scale": "linear", "limits": None},
        ],
        "legend_ordering": ["series-1"],
        "table_headings": None,
        "heatmap_scale": None,
        "units": _units("usd"),
    }

    snap = {
        "schema_version": PRINT_SNAPSHOT_SCHEMA_VERSION,
        "view_id": view_id,
        "scope": scope,
        "refs": refs,
        "result": {
            "result_ref": "artifact:visual_result:p02",
            "result_schema_version": "pgv.visual_result/1",
            "result_digest": result_digest,
            "result_digest_reason": None,
        },
        "data_artifact": {
            "artifact_id": None if demo else "artifact:p02-data",
            "artifact_version": "demo-v1" if demo else "v7",
            "source_hash": None if demo else "b" * 64,
            "hash_algorithm": None if demo else "sha256",
            "hash_reason": "demo_dataset" if demo else None,
        },
        "expected_context": {
            "context_id": None if demo else (context_id or "ctx-p02-1"),
            # Контракт PGV-01 (_str): ревизия в expected_context -- строка
            "data_revision": None if demo else str(data_revision or 7),
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
            "computed_at": "2026-10-28T09:00:00Z",
            "computed_at_reason": None,
            "captured_at": "2026-10-28T09:00:01Z",
            "captured_at_reason": None,
            "checkpoint_confirmed_at": None,
            "render_requested_at": "2026-10-28T09:00:02Z",
            "timezone": "UTC",
            "locale": "ru-RU",
        },
        "checkpoint": None,
        "display": {
            "title": "Диаграмма рассеяния",
            "subtitle": None,
            "detail_level": "compact",
            "sections": [section],
        },
        "method": {"origin": "producer_freeze", "method": "scatter", "parameters": {}},
        "selection": {"allowlist": list(site["view_params"]), "values": {}},
        "sampling": {"applicable": True, "mode": "full", "point_cap": None, "reason": None},
        "annotations": {"revision": 0, "author": "analyst", "text": None},
        "print": {"profile_id": "figure-landscape", "page_count": 1, "theme": "light-print"},
        "renderer_env": {
            "renderer_version": "print-renderer-p02/1",
            "font_profile": "dejavu-sans/1",
            "dependency_status": "available",
            "unavailable_reason": None,
        },
        "data_flow": {"before_revision": None, "after_revision": None},
        "sensitive": {"raw_data_included": False, "sensitive_fields_policy": "redacted"},
        "warnings": [],
    }
    if not (site.get("renderer_kind") in ("recharts_svg", "html_table", "html_heatmap", "mixed")):
        snap["sampling"] = {"applicable": False, "mode": None, "point_cap": None, "reason": "cards_view_no_series"}
    if scope == "demo":
        snap["expected_context"] = {"context_id": None, "data_revision": None, "expected_data_digest": None}
    snap.update(overrides)
    return snap


def _checkpoint(**overrides) -> dict:
    from apps.api.visual_artifacts import CHECKPOINT_SCHEMA_VERSION

    payload = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "checkpoint_id": "pck-p02-0001",
        "stage": "modeling_entry",
        "confirmed_at": "2026-10-28T10:00:00Z",
        "confirmed_at_reason": None,
        "snapshot_ref": "rs-" + "0" * 32,
        "previous_snapshot_ref": None,
        "flags": {"created": True, "reused": False, "unchanged": False},
        "stage_refs": {
            "start": "rs-" + "1" * 32,
            "validation": "rs-" + "2" * 32,
            "exit": "rs-" + "3" * 32,
        },
        "context": {
            "run_id": RUN_ID,
            "context_id": "ctx-p02-1",
            "data_revision": 7,
            "target_column": "value",
            "entity_id": None,
        },
        "provenance": {"source": "producer_capture"},
    }
    payload.update(overrides)
    return payload


def _codes(violations: list[PrintSchemaViolation]) -> list[str]:
    return [v.code for v in violations]


# ══════════════════════════════════════════════════════════════════════
# 1. Kinds durable-слоя (spec §6/§8: schema/migrations/pins/tests)
# ══════════════════════════════════════════════════════════════════════


class TestVisualArtifactKinds:
    def test_new_kinds_registered_in_artifact_store(self):
        from apps.api.artifact_store import ARTIFACT_KINDS

        for kind in ("visual_result", "visual_print_snapshot", "passport_checkpoint"):
            assert kind in ARTIFACT_KINDS, kind

    def test_legacy_kinds_untouched(self):
        from apps.api.artifact_store import ARTIFACT_KINDS

        # Пин legacy-состава DOCLOG-1: существующие kinds сохранены
        # поимённо (читатели/продюсеры DOCLOG-1..8 не ломаются).
        for kind in (
            "passport",
            "oof_backtest",
            "model_card",
            "forecast",
            "data_frame",
            "validation_result",
            "correction_recipe",
        ):
            assert kind in ARTIFACT_KINDS, kind

    def test_schema_versions_pinned(self):
        from apps.api.visual_artifacts import VISUAL_ARTIFACT_SCHEMA_VERSIONS

        assert VISUAL_ARTIFACT_SCHEMA_VERSIONS == {
            "visual_result": "pgv.visual_result/1",
            "visual_print_snapshot": "pgv.visual_print_snapshot/1",
            "passport_checkpoint": "pgv.passport_checkpoint/1",
        }

    def test_kind_registry_roundtrip_memory(self):
        """Регистрация нового kind проходит оба реестра-класса: kind
        расширяет schema/pins/tests (spec §6)."""
        from apps.api.artifact_store import (
            MemoryArtifactRegistry,
            ResultArtifact,
            new_artifact_id,
        )

        registry = MemoryArtifactRegistry()
        artifact = ResultArtifact(
            artifact_id=new_artifact_id(),
            run_id=RUN_ID,
            kind="visual_result",
            producer_key="pgv.visual_result:x:1",
            payload_sha256="c" * 64,
        )
        stored, created = registry.register_artifact(artifact)
        assert created is True
        assert stored.kind == "visual_result"
        assert registry.get_artifact(artifact.artifact_id).kind == "visual_result"


# ══════════════════════════════════════════════════════════════════════
# 2. Валидатор passport_checkpoint/1 (spec §8; AC11/AC12/AC14)
# ══════════════════════════════════════════════════════════════════════


class TestCheckpointValidator:
    def test_valid_modeling_entry_checkpoint(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        assert validate_passport_checkpoint(_checkpoint()) == []

    def test_missing_confirmed_at_is_violation_not_fabrication(self):
        """PGV-AC12: missing/corrupt -- gaps, БЕЗ выдуманной даты."""
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = _checkpoint(confirmed_at=None)
        codes = _codes(validate_passport_checkpoint(payload))
        assert "missing_date" in codes

        # Честная причина вместо даты -- валидно (legacy_unknown).
        legacy = _checkpoint(confirmed_at=None, confirmed_at_reason="legacy_unknown")
        assert validate_passport_checkpoint(legacy) == []

        # Значение И причина одновременно -- неоднозначно.
        ambiguous = _checkpoint(confirmed_at_reason="legacy_unknown")
        codes = _codes(validate_passport_checkpoint(ambiguous))
        assert "ambiguous_source_hash" in codes

    def test_reused_requires_source_snapshot_and_confirmation(self):
        """PGV-AC11: reused-подтверждение обязано нести ссылку на
        исходный снимок; без неё -- violation, не «готовая» картинка."""
        from apps.api.visual_artifacts import validate_passport_checkpoint

        reused = _checkpoint(
            flags={"created": False, "reused": True, "unchanged": False},
            snapshot_ref=None,
        )
        codes = _codes(validate_passport_checkpoint(reused))
        assert "missing_required_ref" in codes

    def test_unchanged_is_not_a_fourth_physical_passport(self):
        """PGV-AC11: unchanged-EDA не создаёт четвёртую физическую
        копию -- флаги created+unchanged взаимоисключающи."""
        from apps.api.visual_artifacts import validate_passport_checkpoint

        bad = _checkpoint(
            flags={"created": True, "reused": False, "unchanged": True}
        )
        codes = _codes(validate_passport_checkpoint(bad))
        assert "conflicting_flags" in codes

        good = _checkpoint(
            flags={"created": False, "reused": True, "unchanged": True}
        )
        assert validate_passport_checkpoint(good) == []

    def test_created_and_reused_are_exclusive(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        bad = _checkpoint(
            flags={"created": True, "reused": True, "unchanged": False}
        )
        assert "conflicting_flags" in _codes(validate_passport_checkpoint(bad))

    def test_stage_refs_required_for_modeling_entry(self):
        """Spec §8: «точные start/validation/exit refs на момент
        подтверждения»."""
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = _checkpoint(stage_refs={"start": "rs-" + "1" * 32})
        codes = _codes(validate_passport_checkpoint(payload))
        assert codes.count("missing_required_ref") >= 2

    def test_panel_entry_requires_entity_context(self):
        """PGV-AC14: panel_entry отдельно от single-series."""
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = _checkpoint(
            stage="panel_entry",
            stage_refs={"panel": "rs-" + "4" * 32},
        )
        # entity_id отсутствует -- смешивание панели с single-series
        codes = _codes(validate_passport_checkpoint(payload))
        assert "panel_mixing" in codes

        payload["context"]["entity_id"] = "entity-42"
        assert validate_passport_checkpoint(payload) == []

    def test_unknown_stage_rejected(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = _checkpoint(stage="exit")
        codes = _codes(validate_passport_checkpoint(payload))
        assert "invalid_value" in codes

    def test_schema_version_and_checkpoint_id_pins(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        codes = _codes(validate_passport_checkpoint(_checkpoint(schema_version="pgv.x/9")))
        assert "schema_version_mismatch" in codes
        codes = _codes(validate_passport_checkpoint(_checkpoint(checkpoint_id="")))
        assert "missing_field" in codes

    def test_context_required(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = _checkpoint(context={"run_id": RUN_ID, "context_id": None, "data_revision": 7})
        codes = _codes(validate_passport_checkpoint(payload))
        assert "missing_required_ref" in codes


# ══════════════════════════════════════════════════════════════════════
# 3. Freeze visual_result / visual_print_snapshot (§6; AC07/AC09)
# ══════════════════════════════════════════════════════════════════════


class TestFreezeVisualResult:
    def test_freeze_and_idempotent_retransfer(self):
        from apps.api.visual_artifacts import freeze_visual_result

        _seed_run()
        subject = _owner_subject()
        first = freeze_visual_result(RUN_ID, subject, payload=_visual_result())
        assert first.kind == "visual_result"
        assert first.schema_version == "pgv.visual_result/1"
        # Повтор того же результата -- идемпотентный перенос (§6),
        # байты не дублируются.
        second = freeze_visual_result(RUN_ID, subject, payload=_visual_result())
        assert second.artifact_id == first.artifact_id

    def test_producer_key_convention(self):
        from apps.api.visual_artifacts import freeze_visual_result

        _seed_run()
        artifact = freeze_visual_result(RUN_ID, _owner_subject(), payload=_visual_result())
        assert artifact.producer_key == (
            "pgv.visual_result:upload.distribution.scatter:"
            "session:upload.distribution.scatter:v7"
        )
        assert artifact.refs["view_id"] == VIEW_SCATTER

    def test_invalid_payload_is_honest_failure(self):
        """Невалидный payload не регистрируется (честный отказ, §6:
        параметры/units/sampling обязательны по applicability)."""
        from apps.api.visual_artifacts import (
            ArtifactPayloadInvalid,
            freeze_visual_result,
        )

        _seed_run()
        payload = _visual_result(units=[])
        with pytest.raises(ArtifactPayloadInvalid):
            freeze_visual_result(RUN_ID, _owner_subject(), payload=payload)
        # Ничего не зарегистрировано
        from apps.api.artifact_store import get_artifact_registry

        assert get_artifact_registry().list_artifacts(RUN_ID) == []

    def test_unknown_view_rejected(self):
        """View вне реестра PGV-00 не морозится (unknown site блокирует
        CERT, spec §5)."""
        from apps.api.visual_artifacts import ArtifactPayloadInvalid, freeze_visual_result

        _seed_run()
        with pytest.raises(ArtifactPayloadInvalid, match="unknown_view"):
            freeze_visual_result(
                RUN_ID, _owner_subject(), payload=_visual_result(view_id="no.such.view")
            )

    def test_context_cas_conflict(self):
        """PGV-AC07: смена context/data_revision при freeze -- честный
        конфликт 409-семантики, НИЧЕГО не регистрируется."""
        from apps.api.visual_artifacts import (
            PrintContextConflict,
            freeze_visual_result,
        )

        _seed_run(context_id="ctx-p02-1", data_revision=7)

        with pytest.raises(PrintContextConflict):
            freeze_visual_result(
                RUN_ID,
                _owner_subject(),
                payload=_visual_result(),
                expected_context_id="ctx-p02-1",
                expected_data_revision=8,  # данные ушли вперёд
            )
        from apps.api.artifact_store import get_artifact_registry

        assert get_artifact_registry().list_artifacts(RUN_ID) == []

    def test_cas_match_registers(self):
        from apps.api.research_runs import get_research_run_store
        from apps.api.visual_artifacts import freeze_visual_result

        _seed_run(context_id="ctx-p02-1", data_revision=7)
        artifact = freeze_visual_result(
            RUN_ID,
            _owner_subject(),
            payload=_visual_result(),
            expected_context_id="ctx-p02-1",
            expected_data_revision=7,
        )
        assert artifact.context_id == "ctx-p02-1"
        assert artifact.data_revision == 7

    def test_state_change_creates_new_immutable_artifact(self):
        """Новая версия результата -- НОВЫЙ артефакт; старый не
        переписывается (spec §8: старые snapshots не переписываются)."""
        from apps.api.visual_artifacts import freeze_visual_result, list_visual_results

        _seed_run()
        subject = _owner_subject()
        old = freeze_visual_result(
            RUN_ID,
            subject,
            payload=_visual_result(
                execution={
                    "execution_ref": "exec-p02-1",
                    "result_ref": "session:v7",
                    "computed_at": "2026-10-28T09:00:00Z",
                    "computed_at_reason": None,
                }
            ),
        )
        new = freeze_visual_result(
            RUN_ID,
            subject,
            payload=_visual_result(
                execution={
                    "execution_ref": "exec-p02-2",
                    "result_ref": "session:v8",
                    "computed_at": "2026-10-28T09:05:00Z",
                    "computed_at_reason": None,
                }
            ),
        )
        assert old.artifact_id != new.artifact_id
        results = list_visual_results(RUN_ID, view_id=VIEW_SCATTER)
        assert {a.artifact_id for a in results} == {old.artifact_id, new.artifact_id}


class TestFreezeVisualPrintSnapshot:
    def test_freeze_snapshot_and_dependency_pin(self):
        """Print snapshot закрепляет зависимость: visual_result пинится
        (§16: metadata graph хранит причины ссылок)."""
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.visual_artifacts import (
            freeze_visual_print_snapshot,
            freeze_visual_result,
        )

        _seed_run(context_id="ctx-p02-1", data_revision=7)
        subject = _owner_subject()
        result = freeze_visual_result(RUN_ID, subject, payload=_visual_result())
        snapshot = freeze_visual_print_snapshot(
            RUN_ID,
            subject,
            payload=_print_snapshot(result_digest="a" * 64),
            result_artifact_id=result.artifact_id,
        )
        assert snapshot.kind == "visual_print_snapshot"
        assert result.artifact_id in snapshot.dependencies
        pins = get_artifact_registry().list_pins(RUN_ID, ref_kind="artifact")
        assert any(p.ref_id == result.artifact_id for p in pins)

    def test_freeze_validates_against_registry_site(self):
        from apps.api.visual_artifacts import (
            ArtifactPayloadInvalid,
            freeze_visual_print_snapshot,
        )

        _seed_run(context_id="ctx-p02-1", data_revision=7)
        # html_heatmap-секция без шкалы -- нарушение правил PGV-01.
        payload = _print_snapshot()
        payload["display"]["sections"][0]["renderer_kind"] = "html_heatmap"
        payload["display"]["sections"][0]["axes"] = []
        payload["display"]["sections"][0]["heatmap_scale"] = None
        with pytest.raises(ArtifactPayloadInvalid):
            freeze_visual_print_snapshot(RUN_ID, _owner_subject(), payload=payload)

    def test_context_cas_uses_expected_context(self):
        """PGV-AC07: CAS freeze по expected_context снапшота против
        текущего состояния запуска."""
        from apps.api.visual_artifacts import (
            PrintContextConflict,
            freeze_visual_print_snapshot,
        )

        _seed_run(context_id="ctx-p02-1", data_revision=7)

        payload = _print_snapshot(context_id="ctx-p02-1", data_revision=9)
        with pytest.raises(PrintContextConflict):
            freeze_visual_print_snapshot(RUN_ID, _owner_subject(), payload=payload)

    def test_demo_scope_skips_context_cas(self):
        from apps.api.visual_artifacts import freeze_visual_print_snapshot

        _seed_run()
        snapshot = freeze_visual_print_snapshot(
            RUN_ID, _owner_subject(), payload=_print_snapshot(view_id="navigator.upload.chart.series")
        )
        assert snapshot.kind == "visual_print_snapshot"

    def test_research_freeze_carries_context_metadata(self):
        from apps.api.research_runs import get_research_run_store
        from apps.api.visual_artifacts import freeze_visual_print_snapshot

        _seed_run(context_id="ctx-p02-1", data_revision=7)
        artifact = freeze_visual_print_snapshot(
            RUN_ID, _owner_subject(), payload=_print_snapshot()
        )
        assert artifact.context_id == "ctx-p02-1"
        assert artifact.data_revision == 7


# ══════════════════════════════════════════════════════════════════════
# 4. Freeze/чтение passport_checkpoint (§8; AC09/AC11)
# ══════════════════════════════════════════════════════════════════════


class TestPassportCheckpointFreeze:
    def test_register_and_idempotency_by_checkpoint_id(self):
        """Spec §8: «Идемпотентность по checkpoint_id»."""
        from apps.api.visual_artifacts import (
            get_passport_checkpoint,
            register_passport_checkpoint,
        )

        _seed_run()
        subject = _owner_subject()
        first = register_passport_checkpoint(RUN_ID, subject, payload=_checkpoint())
        assert first.kind == "passport_checkpoint"
        assert first.producer_key == "pgv.checkpoint:pck-p02-0001"
        second = register_passport_checkpoint(RUN_ID, subject, payload=_checkpoint())
        assert second.artifact_id == first.artifact_id
        loaded = get_passport_checkpoint(RUN_ID, "pck-p02-0001")
        assert loaded is not None
        assert loaded.payload_sha256 == first.payload_sha256

    def test_same_checkpoint_id_different_payload_conflicts(self):
        from apps.api.artifact_store import ArtifactConflictError
        from apps.api.visual_artifacts import register_passport_checkpoint

        _seed_run()
        register_passport_checkpoint(RUN_ID, _owner_subject(), payload=_checkpoint())
        tampered = _checkpoint(confirmed_at="2026-10-28T11:00:00Z")
        with pytest.raises(ArtifactConflictError):
            register_passport_checkpoint(RUN_ID, _owner_subject(), payload=tampered)

    def test_invalid_checkpoint_not_registered(self):
        from apps.api.visual_artifacts import (
            ArtifactPayloadInvalid,
            register_passport_checkpoint,
        )

        _seed_run()
        with pytest.raises(ArtifactPayloadInvalid):
            register_passport_checkpoint(
                RUN_ID, _owner_subject(), payload=_checkpoint(confirmed_at=None)
            )

    def test_checkpoint_read_after_session_loss(self):
        """Субстрат PGV-AC09: durable-факты читаются после утраты
        session/Redis (реестр + ObjectStore, не SessionStore)."""
        from apps.api.session_store import reset_session_store_for_testing
        from apps.api.visual_artifacts import (
            freeze_visual_result,
            get_passport_checkpoint,
            list_visual_results,
            register_passport_checkpoint,
        )

        _seed_run()
        subject = _owner_subject()
        result = freeze_visual_result(RUN_ID, subject, payload=_visual_result())
        checkpoint = register_passport_checkpoint(RUN_ID, subject, payload=_checkpoint())
        # Сессия утрачена (TTL/рестарт)...
        reset_session_store_for_testing()
        # ...durable inputs остаются читаемыми и целостными.
        results = list_visual_results(RUN_ID)
        assert len(results) == 1
        loaded = get_passport_checkpoint(RUN_ID, "pck-p02-0001")
        assert loaded.artifact_id == checkpoint.artifact_id
        assert result.payload_sha256  # digest на месте


# ══════════════════════════════════════════════════════════════════════
# 5. Versioned каталог документов V01/P01/P02 (§10.2; AC22-дух)
# ══════════════════════════════════════════════════════════════════════


class TestDocumentCatalog:
    def test_legacy_document_kinds_untouched(self):
        """Пины DOCLOG-2/DOCLOG-8: D01-D12 сохранены (legacy readers)."""
        from apps.api.report_snapshot import DOCUMENT_KINDS

        assert len(DOCUMENT_KINDS) == 12
        assert DOCUMENT_KINDS["D02"] == ("source_passport", "Паспорт источника", "upload")
        assert DOCUMENT_KINDS["D12"] == ("forecast_vs_actual", "Сверка прогноза с фактом", None)

    def test_print_document_kinds_added(self):
        from apps.api.report_snapshot import PRINT_DOCUMENT_KINDS

        assert set(PRINT_DOCUMENT_KINDS) == {"V01", "P01", "P02"}
        assert PRINT_DOCUMENT_KINDS["V01"][0] == "scientific_visual"
        assert PRINT_DOCUMENT_KINDS["P01"][0] == "passport_print"
        assert PRINT_DOCUMENT_KINDS["P02"][0] == "passport_comparison"

    def test_d02_is_not_renamed_into_p01(self):
        """Spec §10.2: «не переименование D02» -- kind-имена различны."""
        from apps.api.report_snapshot import DOCUMENT_KINDS, PRINT_DOCUMENT_KINDS

        assert DOCUMENT_KINDS["D02"][0] == "source_passport"
        assert PRINT_DOCUMENT_KINDS["P01"][0] == "passport_print"
        kind_names = {spec[0] for spec in DOCUMENT_KINDS.values()}
        assert PRINT_DOCUMENT_KINDS["P01"][0] not in kind_names

    def test_document_kind_family(self):
        from apps.api.report_snapshot import document_kind_family

        assert document_kind_family("D05") == "snapshot_section"
        assert document_kind_family("V01") == "print_document"
        assert document_kind_family("P01") == "print_document"
        assert document_kind_family("P02") == "print_document"
        assert document_kind_family("D99") is None

    def test_resolve_kinds_still_rejects_print_kinds(self):
        """Печатные типы НЕ резолвятся через снапшот-сборщик: их
        ревизии создаются печатным потоком (POST /visuals,
        /passport-documents -- PGV-13/15), а не секциями отчёта."""
        from apps.api.report_snapshot import resolve_kinds

        for code in ("V01", "P01", "P02"):
            with pytest.raises(ValueError, match="печатн"):
                resolve_kinds([code])

    def test_document_catalog_version(self):
        from apps.api.report_snapshot import DOCUMENT_CATALOG_VERSION

        assert DOCUMENT_CATALOG_VERSION == "pgv.document_catalog/2"


# ══════════════════════════════════════════════════════════════════════
# 6. Печатные ревизии документов (document_print_revisions)
# ══════════════════════════════════════════════════════════════════════


class TestPrintDocumentRevisions:
    def _service(self):
        from apps.api.document_jobs import DocumentDeliveryService

        return DocumentDeliveryService.create_default()

    def test_ensure_print_document_revision_created(self):
        from apps.api.visual_artifacts import freeze_visual_result

        _seed_run()
        subject = _owner_subject()
        result = freeze_visual_result(RUN_ID, subject, payload=_visual_result())
        service = self._service()
        document, revision, created = service.ensure_print_document_revision(
            RUN_ID,
            subject,
            session_id=SESSION_ID,
            print_kind="V01",
            basis_kind="visual_print_snapshot",
            basis_artifact_ids=[result.artifact_id],
        )
        assert created is True
        assert document.kind_code == "V01"
        assert document.run_id == RUN_ID
        assert revision.print_kind == "V01"
        assert revision.basis_kind == "visual_print_snapshot"
        assert revision.basis_artifact_ids == [result.artifact_id]
        assert revision.version_no == 1
        assert revision.basis_fingerprint  # закреплён

    def test_idempotent_by_basis_fingerprint(self):
        """Повтор с тем же basis -- та же ревизия (§12.2 дух: повторный
        клик не создаёт дубли; §11: идемпотентность по payload digest)."""
        from apps.api.visual_artifacts import freeze_visual_result

        _seed_run()
        subject = _owner_subject()
        result = freeze_visual_result(RUN_ID, subject, payload=_visual_result())
        service = self._service()
        kwargs = dict(
            session_id=SESSION_ID,
            print_kind="V01",
            basis_kind="visual_print_snapshot",
            basis_artifact_ids=[result.artifact_id],
        )
        first = service.ensure_print_document_revision(RUN_ID, subject, **kwargs)
        second = service.ensure_print_document_revision(RUN_ID, subject, **kwargs)
        assert second[2] is False
        assert second[1].print_revision_id == first[1].print_revision_id
        assert second[1].version_no == 1

    def test_profile_change_creates_new_revision(self):
        from apps.api.visual_artifacts import freeze_visual_result

        _seed_run()
        subject = _owner_subject()
        result = freeze_visual_result(RUN_ID, subject, payload=_visual_result())
        service = self._service()
        kwargs = dict(
            session_id=SESSION_ID,
            print_kind="V01",
            basis_kind="visual_print_snapshot",
            basis_artifact_ids=[result.artifact_id],
        )
        _, rev1, _ = service.ensure_print_document_revision(RUN_ID, subject, **kwargs)
        _, rev2, created = service.ensure_print_document_revision(
            RUN_ID, subject, profile_id="a4-portrait", **kwargs
        )
        assert created is True
        assert rev2.version_no == 2
        assert rev2.profile_id == "a4-portrait"

    def test_print_kind_must_be_print_kind(self):
        """D01-D12 идут через снапшот-поток; печатные ревизии -- только
        для печатных типов (каталог различает семейства)."""
        from apps.api.document_jobs import UnsupportedFormatError

        _seed_run()
        with pytest.raises(UnsupportedFormatError):
            self._service().ensure_print_document_revision(
                RUN_ID,
                _owner_subject(),
                session_id=SESSION_ID,
                print_kind="D02",
                basis_kind="visual_print_snapshot",
                basis_artifact_ids=["artifact:x"],
            )

    def test_basis_artifacts_pinned(self):
        """Basis печатной ревизии защищён pins (§16: причины ссылок;
        keeper не сотрёт basis)."""
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.visual_artifacts import freeze_visual_result

        _seed_run()
        subject = _owner_subject()
        result = freeze_visual_result(RUN_ID, subject, payload=_visual_result())
        service = self._service()
        _, revision, _ = service.ensure_print_document_revision(
            RUN_ID,
            subject,
            session_id=SESSION_ID,
            print_kind="V01",
            basis_kind="visual_print_snapshot",
            basis_artifact_ids=[result.artifact_id],
        )
        pins = get_artifact_registry().list_pins(RUN_ID, ref_kind="artifact")
        assert any(
            p.ref_id == result.artifact_id
            and revision.print_revision_id in p.reason
            for p in pins
        )

    def test_list_print_documents_with_filter(self):
        from apps.api.visual_artifacts import freeze_visual_result

        _seed_run()
        subject = _owner_subject()
        result = freeze_visual_result(RUN_ID, subject, payload=_visual_result())
        service = self._service()
        service.ensure_print_document_revision(
            RUN_ID,
            subject,
            session_id=SESSION_ID,
            print_kind="V01",
            basis_kind="visual_print_snapshot",
            basis_artifact_ids=[result.artifact_id],
        )
        documents = service.list_print_documents(RUN_ID, subject, session_id=SESSION_ID)
        assert len(documents) == 1
        assert documents[0][0].kind_code == "V01"
        assert len(documents[0][1]) == 1
        # Фильтр по P01 -- пусто, но авторизация отрабатывает.
        assert (
            service.list_print_documents(
                RUN_ID, subject, session_id=SESSION_ID, print_kind="P01"
            )
            == []
        )

    def test_registry_roundtrip_print_revision(self):
        from apps.api.document_jobs import DocumentPrintRevisionRecord
        from apps.api.document_jobs import new_print_revision_id

        record = DocumentPrintRevisionRecord(
            print_revision_id=new_print_revision_id(),
            document_id="doc-x",
            run_id=RUN_ID,
            print_kind="P02",
            basis_kind="comparison",
            basis_artifact_ids=["art-1"],
            snapshot_id=None,
            profile_id="figure-landscape",
            manifest_artifact_id=None,
            basis_fingerprint="fp-1",
            version_no=1,
            created_by="subj",
        )
        assert record.to_dict()["print_kind"] == "P02"
        restored = DocumentPrintRevisionRecord.from_dict(record.to_dict())
        assert restored == record

    def test_legacy_revision_flow_unaffected(self):
        """Legacy readers: document_revisions (snapshot-based) работают
        как прежде -- пин критерия готовности PGV-02."""
        from apps.api.document_jobs import (
            DocumentRecord,
            DocumentRevisionRecord,
            new_document_id,
            new_revision_id,
        )
        from apps.api.report_snapshot import new_snapshot_id

        service = self._service()
        registry = service.registry
        document = registry.register_document(
            DocumentRecord(
                document_id=new_document_id(), run_id=RUN_ID, kind_code="D03"
            )
        )
        revision = registry.register_revision(
            DocumentRevisionRecord(
                revision_id=new_revision_id(),
                document_id=document.document_id,
                snapshot_id=new_snapshot_id(),
                run_id=RUN_ID,
                version_no=1,
            )
        )
        assert registry.list_revisions(document.document_id)[0].revision_id == (
            revision.revision_id
        )
        # Печатная ревизия НЕ попала в snapshot-ревизии документа D03.
        assert registry.find_print_revision_by_fingerprint(
            document.document_id, "no-such-fp"
        ) is None


# ══════════════════════════════════════════════════════════════════════
# 7. Миграция 0016 (versioned migrations; файл-дубль; паритет)
# ══════════════════════════════════════════════════════════════════════


class TestMigration0016:
    def test_migration_catalog_contains_0016(self):
        joined = "\n".join(research_runs.MIGRATION_STATEMENTS)
        assert "document_print_revisions" in joined
        assert any(
            name == "0016_pgv2_print_documents.sql" for name, _ in research_runs.MIGRATION_FILES
        )

    def test_migration_file_parity_with_catalog(self):
        """Паритет источников DDL (паттерн PROGR-5.1/DOCLOG-1)."""
        def _norm(value: str) -> str:
            return " ".join(value.split())

        statements = dict(research_runs.MIGRATION_FILES)[
            "0016_pgv2_print_documents.sql"
        ]
        sql_path = (
            Path(research_runs.__file__).parent
            / "migrations"
            / "0016_pgv2_print_documents.sql"
        )
        normalized = _norm(sql_path.read_text(encoding="utf-8"))
        assert statements, "каталог 0016 не пуст"
        for statement in statements:
            assert _norm(statement) in normalized, statement[:60]

    def test_migration_files_sum_matches_full_catalog(self):
        assert sum(len(stmts) for _, stmts in research_runs.MIGRATION_FILES) == len(
            research_runs.MIGRATION_STATEMENTS
        )

    def test_print_revisions_ddl_constraints(self):
        statements = dict(research_runs.MIGRATION_FILES)[
            "0016_pgv2_print_documents.sql"
        ]
        joined = "\n".join(statements)
        assert "CREATE TABLE IF NOT EXISTS document_print_revisions" in joined
        assert "UNIQUE (document_id, version_no)" in joined
        assert "UNIQUE (document_id, basis_fingerprint)" in joined
        # basis -- frozen print inputs: snapshot_id допускает NULL
        # (паспортный anchor опционален), НЕ NOT NULL.
        assert "snapshot_id TEXT" in joined
        assert "snapshot_id TEXT NOT NULL" not in joined

    def test_foundation_document_tables_intact(self):
        """Legacy DDL 0010 не тронут: documents/document_revisions с
        NOT NULL snapshot_id -- читатели D01-D12 работают."""
        joined = "\n".join(research_runs.MIGRATION_STATEMENTS)
        assert "CREATE TABLE IF NOT EXISTS documents" in joined
        assert "CREATE TABLE IF NOT EXISTS document_revisions" in joined
        assert "CREATE TABLE IF NOT EXISTS document_renditions" in joined
        assert "CREATE TABLE IF NOT EXISTS document_jobs" in joined

    def test_registry_classes_implement_print_contract(self):
        """Паритет Memory/Postgres: оба реестра реализуют печатный
        контракт (структурный паритет -- урок F-D2C1)."""
        from apps.api.document_jobs import (
            MemoryDocumentRegistry,
            PostgresDocumentRegistry,
        )

        for method in (
            "register_print_revision",
            "get_print_revision",
            "find_print_revision_by_fingerprint",
            "list_print_revisions",
        ):
            assert callable(getattr(MemoryDocumentRegistry, method, None)), method
            assert callable(getattr(PostgresDocumentRegistry, method, None)), method


# ══════════════════════════════════════════════════════════════════════
# 8. Спецификация и честность поставки
# ══════════════════════════════════════════════════════════════════════


class TestSpecContract:
    def test_spec_row_pgv02_present(self):
        spec = (
            Path(__file__).resolve().parents[2]
            / "spec_documentation_logging.md"
        ).read_text(encoding="utf-8")
        assert "PGV-02" in spec
        assert "Durable inputs" in spec or "durable inputs" in spec.lower()


# ══════════════════════════════════════════════════════════════════════
# 9. PGV-02-FIX: исправления находок сертификации PGV-02-CERT
#    (docs/cert_pgv02_2026-10-28.md §7: F-P2C1..F-P2C6 + N-P2C1;
#    F-P2C7 закрыта upstream PGV-03 -- пины doclog3/7/9 обновлены).
#    Class B корпуса scripts/pgv02cert обязан стать GREEN без правки
#    смысла (прецедент PGV-00-FIX §7.4). Оракулы на СВОИХ данных
#    (RUN-P02A0001/RUN-P02B0002 -- namespace repo-сюиты).
# ══════════════════════════════════════════════════════════════════════

RUN_ID_FOREIGN = "RUN-P02B0002"
SESSION_ID_FOREIGN = "p02-fix-session-b"


class TestFP2C1BasisGate:
    """F-P2C1: ensure_print_document_revision проверяет существование и
    run-принадлежность basis-артефактов (§10.2 «revision с frozen
    refs/pins»; §5/§11 object authorization) ДО создания документа,
    ревизии и пинов."""

    def test_dangling_basis_artifact_refused(self):
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.document_jobs import (
            DocumentDeliveryService,
            PrintBasisInvalid,
        )

        _seed_run()
        missing = "art-" + "0d" * 16
        assert get_artifact_registry().get_artifact(missing) is None
        service = DocumentDeliveryService.create_default()
        with pytest.raises(PrintBasisInvalid) as excinfo:
            service.ensure_print_document_revision(
                RUN_ID,
                _owner_subject(),
                session_id=SESSION_ID,
                print_kind="V01",
                basis_kind="visual_print_snapshot",
                basis_artifact_ids=[missing],
            )
        # Отказ по причине basis-гейта, не kind-проверки.
        assert "не печатный тип" not in str(excinfo.value)
        # Ничего не зарегистрировано: документа V01 нет.
        assert service.registry.find_document_by_kind(RUN_ID, "V01") is None

    def test_foreign_run_basis_artifact_refused(self):
        from apps.api.document_jobs import (
            DocumentDeliveryService,
            PrintBasisInvalid,
        )
        from apps.api.visual_artifacts import freeze_visual_result

        _seed_run(RUN_ID_FOREIGN, SESSION_ID_FOREIGN)
        foreign_artifact = freeze_visual_result(
            RUN_ID_FOREIGN,
            _owner_subject(SESSION_ID_FOREIGN),
            payload=_visual_result(),
            session_id=SESSION_ID_FOREIGN,
        )
        _seed_run()
        service = DocumentDeliveryService.create_default()
        with pytest.raises(PrintBasisInvalid):
            service.ensure_print_document_revision(
                RUN_ID,
                _owner_subject(),
                session_id=SESSION_ID,
                print_kind="V01",
                basis_kind="visual_print_snapshot",
                basis_artifact_ids=[foreign_artifact.artifact_id],
            )
        assert service.registry.find_document_by_kind(RUN_ID, "V01") is None


class TestFP2C2CasNonNumericRevision:
    """F-P2C2: CAS freeze fail-closed на нечисловой непустой строке
    expected_context.data_revision -- честный конфликт (409
    context_changed), не тихий пропуск сверки (PGV-AC07)."""

    def test_non_numeric_expected_revision_conflicts(self):
        from apps.api.visual_artifacts import (
            PrintContextConflict,
            freeze_visual_print_snapshot,
        )

        _seed_run(RUN_ID, SESSION_ID, context_id="ctx-p02-1", data_revision=7)
        snap = _print_snapshot(data_revision=42)
        snap["expected_context"]["data_revision"] = "abc"
        with pytest.raises(PrintContextConflict):
            freeze_visual_print_snapshot(
                RUN_ID,
                _owner_subject(),
                payload=snap,
                session_id=SESSION_ID,
            )

    def test_numeric_expected_revision_still_accepted(self):
        """Регресс-честность: числовая строка сверяется как прежде."""
        from apps.api.visual_artifacts import freeze_visual_print_snapshot

        _seed_run(RUN_ID, SESSION_ID, context_id="ctx-p02-1", data_revision=7)
        snap = _print_snapshot(data_revision=7)
        artifact = freeze_visual_print_snapshot(
            RUN_ID,
            _owner_subject(),
            payload=snap,
            session_id=SESSION_ID,
        )
        assert artifact.kind == "visual_print_snapshot"


class TestFP2C3ManifestInFingerprint:
    """F-P2C3: manifest_artifact_id входит в basis_fingerprint --
    повтор с тем же basis, но другим manifest -- НОВАЯ ревизия (§11
    идемпотентность по телу), не тихий возврат прежнего manifest."""

    def test_manifest_change_creates_new_revision(self):
        from apps.api.document_jobs import DocumentDeliveryService

        _seed_run()
        service = DocumentDeliveryService.create_default()
        kwargs = dict(
            session_id=SESSION_ID,
            print_kind="P01",
            basis_kind="passport",
            basis_artifact_ids=[],
        )
        _, rev1, created1 = service.ensure_print_document_revision(
            RUN_ID,
            _owner_subject(),
            manifest_artifact_id="art-" + "11" * 16,
            **kwargs,
        )
        _, rev2, created2 = service.ensure_print_document_revision(
            RUN_ID,
            _owner_subject(),
            manifest_artifact_id="art-" + "22" * 16,
            **kwargs,
        )
        assert created1 is True
        assert created2 is True
        assert rev2.manifest_artifact_id == "art-" + "22" * 16
        assert rev2.version_no == rev1.version_no + 1

    def test_same_manifest_is_idempotent(self):
        """§12.2: повтор с тем же телом (включая manifest) -- та же
        ревизия, дубли не плодятся."""
        from apps.api.document_jobs import DocumentDeliveryService

        _seed_run()
        service = DocumentDeliveryService.create_default()
        kwargs = dict(
            session_id=SESSION_ID,
            print_kind="P01",
            basis_kind="passport",
            basis_artifact_ids=[],
            manifest_artifact_id="art-" + "33" * 16,
        )
        first = service.ensure_print_document_revision(
            RUN_ID, _owner_subject(), **kwargs
        )
        second = service.ensure_print_document_revision(
            RUN_ID, _owner_subject(), **kwargs
        )
        assert second[2] is False
        assert second[1].print_revision_id == first[1].print_revision_id
        assert second[1].version_no == first[1].version_no


class TestFP2C4SelfReference:
    """F-P2C4: previous_snapshot_ref == snapshot_ref отвергается
    валидатором чекпоинта (§8: previous -- ссылка на ПРЕДЫДУЩИЙ снимок
    цепочки подтверждений, самоссылка не имеет смысла истории)."""

    def test_self_reference_refused(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        payload = _checkpoint(previous_snapshot_ref="rs-" + "0" * 32)
        violations = validate_passport_checkpoint(payload)
        assert "invalid_value" in _codes(violations)
        assert any(v.path == "previous_snapshot_ref" for v in violations)

    def test_distinct_previous_ref_still_valid(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        ok = _checkpoint(previous_snapshot_ref="rs-" + "9" * 32)
        assert validate_passport_checkpoint(ok) == []


class TestFP2C5AtomicPinFailure:
    """F-P2C5: отказ пина зависимости после persist НЕ оставляет
    зарегистрированный артефакт (AC08-дух: либо валидный результат, либо
    явный отказ без частичного состояния)."""

    def test_pin_failure_leaves_no_artifact(self):
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.visual_artifacts import (
            freeze_visual_print_snapshot,
            freeze_visual_result,
        )

        _seed_run(RUN_ID, SESSION_ID, context_id="ctx-p02-1", data_revision=7)
        subject = _owner_subject()
        result = freeze_visual_result(
            RUN_ID, subject, payload=_visual_result(), session_id=SESSION_ID
        )
        registry = get_artifact_registry()
        count_before = len(registry.list_artifacts(RUN_ID))

        class _PinDown(Exception):
            pass

        original = type(registry).pin_ref

        def boom(*args, **kwargs):
            raise _PinDown("pin storage down")

        type(registry).pin_ref = boom
        try:
            with pytest.raises(_PinDown):
                freeze_visual_print_snapshot(
                    RUN_ID,
                    subject,
                    payload=_print_snapshot(result_digest="b" * 64),
                    session_id=SESSION_ID,
                    result_artifact_id=result.artifact_id,
                )
            # AC08-компенсация: артефакт не остаётся в реестре.
            assert len(registry.list_artifacts(RUN_ID)) == count_before
        finally:
            type(registry).pin_ref = original


class TestFP2C5EnsurePathAtomicity:
    """Симметричный класс частичного состояния в ensure_print_document_revision:
    отказ пина basis не оставляет ревизии (пин ДО регистрации); отказ
    регистрации после поставленных пинов -- unpin-компенсация."""

    def test_pin_failure_during_ensure_leaves_no_revision(self):
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.visual_artifacts import freeze_visual_result

        _seed_run()
        subject = _owner_subject()
        result = freeze_visual_result(
            RUN_ID, subject, payload=_visual_result(), session_id=SESSION_ID
        )
        service = DocumentDeliveryService.create_default()
        registry = get_artifact_registry()

        class _PinDown(Exception):
            pass

        original = type(registry).pin_ref

        def boom(*args, **kwargs):
            raise _PinDown("pin storage down")

        type(registry).pin_ref = boom
        try:
            with pytest.raises(_PinDown):
                service.ensure_print_document_revision(
                    RUN_ID,
                    subject,
                    session_id=SESSION_ID,
                    print_kind="V01",
                    basis_kind="visual_print_snapshot",
                    basis_artifact_ids=[result.artifact_id],
                )
        finally:
            type(registry).pin_ref = original
        # Ревизия не зарегистрирована; документ-контейнер (find-or-create)
        # без ревизий допустим и переиспользуется повтором.
        document = service.registry.find_document_by_kind(RUN_ID, "V01")
        if document is not None:
            assert service.registry.list_print_revisions(document.document_id) == []


class TestFP2C6MemoryUniqueParity:
    """F-P2C6 (класс F-D2C1): Memory-реестр печатных ревизий даёт
    конфликт на дубликатах UNIQUE(document_id, version_no) и
    UNIQUE(document_id, basis_fingerprint) из DDL 0016, а не молчаливый
    дубликат (Postgres отклонил бы вставку)."""

    def _record(self, doc_id: str, version_no: int, fingerprint: str):
        from apps.api.document_jobs import (
            DocumentPrintRevisionRecord,
            new_print_revision_id,
        )

        return DocumentPrintRevisionRecord(
            print_revision_id=new_print_revision_id(),
            document_id=doc_id,
            run_id=RUN_ID,
            print_kind="P01",
            basis_kind="passport",
            basis_artifact_ids=[],
            profile_id="figure-landscape",
            manifest_artifact_id=None,
            basis_fingerprint=fingerprint,
            version_no=version_no,
            created_by="subj",
        )

    def test_duplicate_version_no_refused(self):
        from apps.api.document_jobs import (
            PrintRevisionConflictError,
            get_document_registry,
        )

        _seed_run()
        registry = get_document_registry()
        first = self._record("doc-" + "f1" * 16, 1, "fp-p02-fix-a")
        duplicate = self._record(first.document_id, 1, "fp-p02-fix-b")
        registry.register_print_revision(first)
        with pytest.raises(PrintRevisionConflictError):
            registry.register_print_revision(duplicate)
        assert len(registry.list_print_revisions(first.document_id)) == 1

    def test_duplicate_fingerprint_refused(self):
        from apps.api.document_jobs import (
            PrintRevisionConflictError,
            get_document_registry,
        )

        _seed_run()
        registry = get_document_registry()
        doc_id = "doc-" + "f2" * 16
        registry.register_print_revision(self._record(doc_id, 1, "fp-p02-fix-x"))
        with pytest.raises(PrintRevisionConflictError):
            registry.register_print_revision(
                self._record(doc_id, 2, "fp-p02-fix-x")
            )
        assert len(registry.list_print_revisions(doc_id)) == 1

    def test_distinct_version_and_fingerprint_accepted(self):
        from apps.api.document_jobs import get_document_registry

        _seed_run()
        registry = get_document_registry()
        doc_id = "doc-" + "f3" * 16
        registry.register_print_revision(self._record(doc_id, 1, "fp-p02-fix-1"))
        registry.register_print_revision(self._record(doc_id, 2, "fp-p02-fix-2"))
        assert len(registry.list_print_revisions(doc_id)) == 2


class TestNP2C1EmptyRevisionString:
    """N-P2C1 (класс F-D7C2): пустая строка context.data_revision --
    «обязательная ревизия» без значения -- missing_required_ref; 0
    остаётся значением (контекст 0-как-значение)."""

    def test_empty_string_refused(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        ctx = {
            "run_id": RUN_ID,
            "context_id": "ctx-p02-1",
            "data_revision": "",
            "target_column": "value",
            "entity_id": None,
        }
        violations = validate_passport_checkpoint(_checkpoint(context=ctx))
        assert any(
            v.code == "missing_required_ref" and v.path == "context.data_revision"
            for v in violations
        )

    def test_zero_revision_is_a_value(self):
        from apps.api.visual_artifacts import validate_passport_checkpoint

        ctx = {
            "run_id": RUN_ID,
            "context_id": "ctx-p02-1",
            "data_revision": 0,
            "target_column": "value",
            "entity_id": None,
        }
        violations = validate_passport_checkpoint(_checkpoint(context=ctx))
        assert not any(v.path == "context.data_revision" for v in violations)


class TestUnregisterArtifactCompensation:
    """Субстрат F-P2C5: unregister_artifact в контракте реестра
    (ABC/Memory/Postgres -- паритет F-D2C1); компенсация AC08 отказана
    для пин-защищённого артефакта (§16: защищённое не удаляется)."""

    def test_contract_implemented_by_both_backends(self):
        from apps.api.artifact_store import (
            ArtifactRegistry,
            MemoryArtifactRegistry,
            PostgresArtifactRegistry,
        )

        for cls in (ArtifactRegistry, MemoryArtifactRegistry, PostgresArtifactRegistry):
            assert callable(getattr(cls, "unregister_artifact", None)), cls

    def test_unregister_roundtrip(self):
        from apps.api.artifact_store import (
            MemoryArtifactRegistry,
            ResultArtifact,
            new_artifact_id,
        )

        registry = MemoryArtifactRegistry()
        artifact = ResultArtifact(
            artifact_id=new_artifact_id(),
            run_id=RUN_ID,
            kind="visual_result",
            producer_key="pgv.visual_result:fix:1",
            payload_sha256="d" * 64,
        )
        registry.register_artifact(artifact)
        assert registry.unregister_artifact(artifact.artifact_id) is True
        assert registry.get_artifact(artifact.artifact_id) is None
        assert registry.unregister_artifact(artifact.artifact_id) is False

    def test_unregister_refuses_pinned_artifact(self):
        from apps.api.artifact_store import (
            MemoryArtifactRegistry,
            ResultArtifact,
            new_artifact_id,
        )

        registry = MemoryArtifactRegistry()
        artifact = ResultArtifact(
            artifact_id=new_artifact_id(),
            run_id=RUN_ID,
            kind="visual_result",
            producer_key="pgv.visual_result:fix:2",
            payload_sha256="e" * 64,
        )
        registry.register_artifact(artifact)
        registry.pin_ref(RUN_ID, "artifact", artifact.artifact_id, reason="print_snapshot:guard")
        with pytest.raises(ValueError):
            registry.unregister_artifact(artifact.artifact_id)
        assert registry.get_artifact(artifact.artifact_id) is not None
