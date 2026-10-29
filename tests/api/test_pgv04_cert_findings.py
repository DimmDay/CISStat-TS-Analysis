"""Сертификация PGV-04-CERT (2026-10-29) -- Class B: RED-СВИДЕТЕЛЬСТВА
НАХОДОК (обязаны быть RED на родителе c4e90b8 и стать GREEN после
PGV-04-FIX БЕЗ правки смысла оракулов; прецедент PGV-03-CERT).

В мутационной кампании НЕ участвует (RED на родителе независимо от
мутантов).

Находки акта docs/cert_pgv04_2026-10-29.md:

  F-P4C1 (средняя; класс F-P2C2 «контракт не enforced» + молчаливый
  пропуск): backfill_passport_checkpoints читает несуществующее поле
  session ``panel_passport_checkpoints`` (реальное поле --
  ``panel_entry_checkpoints``): панельные чекпоинты НИКОГДА не
  добираются sweep-каналом -- «retry без capture» (критерий §13) для
  panel_entry не работает; счётчики честны, но молчаливы (панель не
  попадает ни в frozen, ни в skipped).

  F-P4C2 (средняя; нарушение per-entry устойчивости sweep-канала):
  backfill ловит только PromotionUnavailable; прочие сбои одной записи
  (ArtifactPayloadInvalid -- валидационный отказ payload при битой
  легаси-фактуре, ArtifactConflictError, KeyError) прерывают ВЕСЬ добор:
  остальные легитимные чекпоинты не доставляются, каждый следующий
  sweep упирается в тот же сбой (доставка не восстановима). Прецедент
  паттерна -- per-entry try/except в sweep-цикле
  notify_modeling_artifacts_updated для backtests/cards/forecasts.

  F-P4C3 (низкая; документная честность): докстринг
  freeze_passport_checkpoint утверждает «вызывающий гарантированно
  ничего не записал» при честном недоборе -- фактически rs-записи
  вовлечённых снимков создаются ДО отказа на недостающей точке
  траектории (честные адресуемые факты, но контракт-текст лжёт; класс
  F-P3C2-подобной документной неточности).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from apps.api.session_store import (
    get_session_store,
    reset_session_store_for_testing,
)

RUN_ID = "RUN-P4CERTB01"
SESSION_ID = "p4cert-finding-session"
PANEL_SESSION_ID = "p4cert-finding-panel"


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    monkeypatch.delenv("CISSTAT_ARTIFACTS_BACKEND", raising=False)
    from apps.api import artifact_store, research_runs
    from apps.api.document_jobs import reset_document_registry_for_testing

    research_runs.reset_research_run_store_for_testing()
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


def _seed_run(run_id, session_id):
    from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
    from apps.api.research_runs import ResearchRun, get_research_run_store

    now = datetime.now(timezone.utc).isoformat()
    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="p4b" * 8,
        dataset_name="p4cert-finding-seed",
        target_column="value",
        created_at=now,
        last_active_at=now,
        status="active",
        owner_subject=SubjectRef.from_session(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)
    return run


def _seed_session(session_id=SESSION_ID, run_id=RUN_ID):
    from apps.api.session_store import AnalysisSession, DatasetInfo

    session = AnalysisSession(session_id=session_id)
    session.run_id = run_id
    session.dataset = DatasetInfo(
        dataset_id="p4cert-b-ds",
        name="p4cert-finding-seed",
        rows=12,
        columns=2,
        size_label="1 KB",
        dataset_fingerprint="p4b" * 8,
    )
    session.data_revision = 7
    session.target_column = "value"
    session.date_column = "date"
    return session


def _owner_subject(session_id=SESSION_ID):
    from apps.api.identity import SubjectRef

    return SubjectRef.from_session(session_id)


def _checkpoint_payload(artifact) -> dict:
    import json

    from apps.api.artifact_store import get_artifact_object_store

    data = get_artifact_object_store().read_bytes(artifact.storage_key)
    return json.loads(data.decode("utf-8"))


def _durable_checkpoint(run_id, session_checkpoint_id):
    from apps.api.visual_artifacts import get_passport_checkpoint

    return get_passport_checkpoint(run_id, f"pck-{session_checkpoint_id}")


# ══════════════════════════════════════════════════════════════════════
# F-P4C1: панельный backfill
# ══════════════════════════════════════════════════════════════════════


class TestFP4C1PanelBackfill:
    def test_panel_checkpoint_is_backfilled_as_legacy_import(self):
        """B1: панельный чекпоинт добирается backfill'ом ИЗ session-
        записей (панель-сид -- РЕАЛЬНЫЕ методы panel-контура); payload:
        stage=panel_entry, entity-контекст, stage_refs.panel=rs-*,
        provenance=legacy_import."""
        from apps.api.passport_checkpoints import backfill_passport_checkpoints

        _seed_run(RUN_ID, PANEL_SESSION_ID)
        session = _seed_session(PANEL_SESSION_ID, RUN_ID)
        snapshot = session.append_panel_passport_snapshot(
            passport={"entity_column": "region", "models": {}},
            fingerprint="fp-panel-" + "0" * 55,
        )
        session.modeling_artifacts["panel_columns"] = {
            "date_column": "date",
            "entity_column": "entity",
            "value_columns": ["y"],
            "target_column": "value",
        }
        checkpoint = session.append_panel_entry_checkpoint(
            snapshot,
            previous_snapshot_id=snapshot.snapshot_id,
            created_snapshot=False,
        )
        get_session_store().save(session)

        counts = backfill_passport_checkpoints(
            RUN_ID, _owner_subject(PANEL_SESSION_ID),
            session=session, session_id=PANEL_SESSION_ID,
        )
        artifact = _durable_checkpoint(RUN_ID, checkpoint.checkpoint_id)
        assert artifact is not None, (
            "F-P4C1: панельный чекпоинт не добирается backfill'ом "
            "(backfill читает несуществующее поле panel_passport_"
            "checkpoints вместо panel_entry_checkpoints)"
        )
        payload = _checkpoint_payload(artifact)
        assert payload["stage"] == "panel_entry"
        assert payload["provenance"]["source"] == "legacy_import"
        assert payload["context"]["entity_id"] == "entity"
        assert payload["stage_refs"]["panel"].startswith("rs-")
        assert counts["frozen"] >= 1

    def test_panel_backfill_idempotent_repeat(self):
        """B2: повторный backfill после панельного добора -- no-op
        (идемпотентность §8; счётчик честен)."""
        from apps.api.passport_checkpoints import backfill_passport_checkpoints

        _seed_run(RUN_ID, PANEL_SESSION_ID)
        session = _seed_session(PANEL_SESSION_ID, RUN_ID)
        snapshot = session.append_panel_passport_snapshot(
            passport={"entity_column": "region", "models": {}},
            fingerprint="fp-panel-" + "0" * 55,
        )
        session.modeling_artifacts["panel_columns"] = {
            "date_column": "date",
            "entity_column": "entity",
            "value_columns": ["y"],
            "target_column": "value",
        }
        checkpoint = session.append_panel_entry_checkpoint(
            snapshot,
            previous_snapshot_id=snapshot.snapshot_id,
            created_snapshot=False,
        )
        get_session_store().save(session)

        first = backfill_passport_checkpoints(
            RUN_ID, _owner_subject(PANEL_SESSION_ID),
            session=session, session_id=PANEL_SESSION_ID,
        )
        assert first["frozen"] == 1, "F-P4C1: панельный чекпоинт не добран"
        second = backfill_passport_checkpoints(
            RUN_ID, _owner_subject(PANEL_SESSION_ID),
            session=session, session_id=PANEL_SESSION_ID,
        )
        assert second["frozen"] == 0, "повторный backfill не идемпотентен"

    def test_panel_and_single_backfilled_together(self):
        """B3 (объединённая вселенная добора): в одной сессии panel_entry
        и modeling_entry чекпоинты добираются ОДНИМ backfill'ом; счётчик
        отражает оба."""
        from apps.api.passport_checkpoints import backfill_passport_checkpoints

        _seed_run(RUN_ID, SESSION_ID)
        session = _seed_session()
        snaps = {}
        old = "2026-01-01T00:00:00+00:00"
        for stage in ("start", "validation", "exit"):
            s = session.append_passport_snapshot(
                stage, {"basic_stats": {"n": 84}},
                fingerprint=f"fp-{stage}-" + "0" * 52,
            )
            object.__setattr__(s, "captured_at", old)
            snaps[stage] = s
        single_ck = session.append_passport_checkpoint(
            "modeling_entry", snaps["start"],
            previous_snapshot_id=snaps["exit"].snapshot_id,
            created_snapshot=False,
        )
        panel_snapshot = session.append_panel_passport_snapshot(
            passport={"entity_column": "region", "models": {}},
            fingerprint="fp-panel-" + "0" * 55,
        )
        session.modeling_artifacts["panel_columns"] = {
            "date_column": "date",
            "entity_column": "entity",
            "value_columns": ["y"],
            "target_column": "value",
        }
        panel_ck = session.append_panel_entry_checkpoint(
            panel_snapshot,
            previous_snapshot_id=panel_snapshot.snapshot_id,
            created_snapshot=False,
        )
        get_session_store().save(session)

        counts = backfill_passport_checkpoints(
            RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
        )
        assert counts["frozen"] == 2, (
            f"F-P4C1: объединённый добор не доставляет оба чекпоинта: {counts}"
        )
        assert _durable_checkpoint(RUN_ID, single_ck.checkpoint_id) is not None
        assert _durable_checkpoint(RUN_ID, panel_ck.checkpoint_id) is not None


# ══════════════════════════════════════════════════════════════════════
# F-P4C2: per-entry изоляция backfill
# ══════════════════════════════════════════════════════════════════════


class TestFP4C2BackfillIsolation:
    def test_broken_entry_does_not_block_legitimate_ones(self):
        """B4: сбой ОДНОЙ записи (панельный чекпоинт с утраченными
        panel_columns -> ArtifactPayloadInvalid -- реалистичный легаси-
        путь) НЕ прерывает добор остальных: легитимный modeling_entry
        доставлен тем же вызовом; вызов не бросает; счётчик failed
        отражает сбойную запись."""
        from apps.api.passport_checkpoints import backfill_passport_checkpoints

        _seed_run(RUN_ID, SESSION_ID)
        session = _seed_session()
        old = "2026-01-01T00:00:00+00:00"
        snaps = {}
        for stage in ("start", "validation", "exit"):
            s = session.append_passport_snapshot(
                stage, {"basic_stats": {"n": 84}},
                fingerprint=f"fp-{stage}-" + "0" * 52,
            )
            object.__setattr__(s, "captured_at", old)
            snaps[stage] = s
        # Легитимный однорядный чекпоинт (полная траектория)
        single_ck = session.append_passport_checkpoint(
            "modeling_entry", snaps["start"],
            previous_snapshot_id=snaps["exit"].snapshot_id,
            created_snapshot=False,
        )
        # Сбойный панельный чекпоинт: панель-снимок есть, panel_columns
        # УТРАЧЕНЫ (легаси-сессия) -> payload entity_id=None ->
        # ArtifactPayloadInvalid из register (не PromotionUnavailable).
        panel_snapshot = session.append_panel_passport_snapshot(
            passport={"entity_column": "region", "models": {}},
            fingerprint="fp-panel-" + "0" * 55,
        )
        panel_ck = session.append_panel_entry_checkpoint(
            panel_snapshot,
            previous_snapshot_id=panel_snapshot.snapshot_id,
            created_snapshot=False,
        )
        get_session_store().save(session)
        # panel_columns сознательно НЕ устанавливаем (легаси-фактура).

        counts = backfill_passport_checkpoints(
            RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
        )
        assert _durable_checkpoint(RUN_ID, single_ck.checkpoint_id) is not None, (
            "F-P4C2: сбой одной записи прервал добор легитимного чекпоинта"
        )
        assert _durable_checkpoint(RUN_ID, panel_ck.checkpoint_id) is None, (
            "сбойная запись не должна доставляться (честный сбой)"
        )
        assert counts.get("frozen", 0) == 1
        assert counts.get("failed", 0) == 1, (
            f"счётчик failed обязан отражать сбойную запись: {counts}"
        )

    def test_broken_entry_receipt_and_retry_isolation(self, monkeypatch):
        """B5: сбойная запись получает durable-receipt (класс сбоя
        промоушена), легитимная -- доставляется; повторный sweep НЕ
        упирается в блокирующий сбой всей партии (восстановимая
        доставка)."""
        from apps.api import security_audit
        from apps.api.passport_checkpoints import backfill_passport_checkpoints

        calls: list[tuple] = []
        real_record_standard = security_audit.record_standard

        def _spy(action, *args, **kwargs):
            calls.append((action, args, kwargs))
            return real_record_standard(action, *args, **kwargs)

        monkeypatch.setattr(security_audit, "record_standard", _spy)

        _seed_run(RUN_ID, SESSION_ID)
        session = _seed_session()
        old = "2026-01-01T00:00:00+00:00"
        snaps = {}
        for stage in ("start", "validation", "exit"):
            s = session.append_passport_snapshot(
                stage, {"basic_stats": {"n": 84}},
                fingerprint=f"fp-{stage}-" + "0" * 52,
            )
            object.__setattr__(s, "captured_at", old)
            snaps[stage] = s
        single_ck = session.append_passport_checkpoint(
            "modeling_entry", snaps["start"],
            previous_snapshot_id=snaps["exit"].snapshot_id,
            created_snapshot=False,
        )
        panel_snapshot = session.append_panel_passport_snapshot(
            passport={"entity_column": "region", "models": {}},
            fingerprint="fp-panel-" + "0" * 55,
        )
        session.append_panel_entry_checkpoint(
            panel_snapshot,
            previous_snapshot_id=panel_snapshot.snapshot_id,
            created_snapshot=False,
        )
        get_session_store().save(session)

        counts = backfill_passport_checkpoints(
            RUN_ID, _owner_subject(), session=session, session_id=SESSION_ID,
        )
        assert counts.get("frozen", 0) == 1, (
            "F-P4C2: легитимный чекпоинт не доставлен из-за сбойной записи"
        )
        # Сбоку -- durable-receipt (durable-сбой, не info-гэп); фильтр по
        # ФАКТИЧЕСКОЙ структуре записи _record_failure: operation -- в
        # details, producer_key -- в resource_id (урок первой порции
        # кампании: слепые kwargs-фильтры не видят receipt).
        receipts = [
            c for c in calls
            if c[0] == "artifact_promotion_failed"
            and (
                "checkpoint"
                in str((c[2].get("details") or {}).get("operation", "")).lower()
                or str(c[2].get("resource_id") or "").startswith("pgv.checkpoint")
            )
        ]
        assert receipts, "сбой одной записи должен получить durable-receipt"

    def test_payload_invalid_is_not_honest_gap(self):
        """B6 (уточнение класса сбоя): ArtifactPayloadInvalid от битой
        легаси-фактуры НЕ является PromotionUnavailable (честным недобором
        штата конвейера) -- это сбой доставки конкретной записи, изолируемый
        per-entry, с receipt, без прерывания остальных."""
        from apps.api.artifact_promotion import PromotionUnavailable
        from apps.api.visual_artifacts import ArtifactPayloadInvalid

        assert not issubclass(ArtifactPayloadInvalid, PromotionUnavailable), (
            "инвариант классов изменился -- пересмотреть классификацию сбоя"
        )


# ══════════════════════════════════════════════════════════════════════
# F-P4C3: документная честность freeze
# ══════════════════════════════════════════════════════════════════════


class TestFP4C3FreezeDocstring:
    def test_freeze_docstring_does_not_claim_nothing_written(self):
        """B7 (статический): докстринг freeze_passport_checkpoint не
        утверждает «гарантированно ничего не записал» -- фактическое
        поведение: rs-записи вовлечённых снимков создаются до отказа
        (честные адресуемые факты). Текст обязан описывать реальную
        семантику (класс F-P3C2-подобной документной неточности)."""
        import inspect

        from apps.api import passport_checkpoints

        doc = inspect.getdoc(passport_checkpoints.freeze_passport_checkpoint) or ""
        assert "гарантированно ничего не записал" not in doc, (
            "F-P4C3: докстринг лжёт о частичной записи rs-записей"
        )
        # После фикса текст должен честно описывать rs-семантику
        lowered = doc.lower()
        assert ("rs-запис" in lowered) or ("снимк" in lowered), (
            "докстринг не описывает семантику rs-записей вовлечённых снимков"
        )

    def test_delivery_doc_matches_partial_rs_semantics(self):
        """B8 (статический): документ поставки/док-строка модуля честно
        описывают частичную rs-запись при honest-skip (после PGV-04-FIX)."""
        module = (
            __import__("pathlib").Path(__file__).resolve().parents[2]
            / "apps/api/passport_checkpoints.py"
        ).read_text(encoding="utf-8")
        assert "гарантированно ничего не записал" not in module, (
            "F-P4C3: ложная формулировка осталась в модуле"
        )
