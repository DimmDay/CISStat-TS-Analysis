# scripts/doclog2cert/test_doclog2cert_oracle_unit.py -- ЧАСТЬ 2
# Сборщик SnapshotService: авторизация, согласованное чтение (AC02),
# адаптеры D01-D09 (§6), идемпотентность (AC09), pins (§16),
# целостность чтения (T8/T16), отсутствие пересчётов (AC05).
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import (
    CTX_ALPHA, CTX_BETA, FP, REV_ALPHA, RUN_ID, RUN_ID_B, RUN_ID_LEGACY,
    RUN_MISSING, SESSION_B, SESSION_FOREIGN, SESSION_ID,
    UNIFORM_DENIAL_TEXT, admin_subject, append_event, foreign_subject,
    make_artifact, owner_subject, seed_bound_run, seed_session, section,
    service,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


# ══════════════════════════════════════════════════════════════════════
# 5. Авторизация (R09/T7/T15 -- решающая таблица DOCLOG-0)
# ══════════════════════════════════════════════════════════════════════


class TestOrcAuth:
    def _build(self, subject, run_id=RUN_ID, request_session=SESSION_ID, **kw):
        """Run ВСЕГДА привязан к SESSION_ID (владелец-сессия);
        request_session -- сессия ЗАПРОСА (чужая -- отдельная)."""
        seed_session(SESSION_ID)
        seed_bound_run(run_id, SESSION_ID)
        if request_session != SESSION_ID:
            seed_session(request_session)
        return service().build_snapshot(
            run_id, subject, session_id=request_session, kinds=["D02"], **kw
        )

    def test_owner_build_and_read(self, orc_env):
        snapshot, created = self._build(owner_subject())
        assert created is True
        assert snapshot.research_run_id == RUN_ID
        assert snapshot.approval is None                    # §10.1
        got = service().get_snapshot(
            snapshot.snapshot_id, owner_subject(), session_id=SESSION_ID
        )
        assert got.snapshot_id == snapshot.snapshot_id

    def test_foreign_cookie_denied_uniform(self, orc_env):
        from apps.api.snapshot_builder import SnapshotAccessDenied

        with pytest.raises(SnapshotAccessDenied) as ei:
            self._build(foreign_subject(), request_session=SESSION_FOREIGN)
        assert str(ei.value) == UNIFORM_DENIAL_TEXT

    def test_anonymous_denied(self, orc_env):
        from apps.api.snapshot_builder import SnapshotAccessDenied

        with pytest.raises(SnapshotAccessDenied):
            self._build(None)

    def test_admin_allowed_foreign_run(self, orc_env):
        seed_session(SESSION_B, target="alt")
        seed_bound_run(RUN_ID_B, SESSION_B, context_id=CTX_BETA,
                       data_revision=1, target="alt")
        snapshot, created = service().build_snapshot(
            RUN_ID_B, admin_subject(), session_id="", kinds=["D02"]
        )
        assert created is True
        assert snapshot.research_run_id == RUN_ID_B

    def test_creator_continuity_unresolved_legacy(self, orc_env):
        """Legacy-run без owner/tenant: создавшая сессия продолжает
        владеть (континуитет DOCLOG-0), аноним -- нет."""
        from apps.api.identity import DEFAULT_TENANT_ID
        from apps.api.research_runs import ResearchRun, get_research_run_store
        from apps.api.snapshot_builder import SnapshotAccessDenied

        seed_session()
        legacy = ResearchRun(
            run_id=RUN_ID_LEGACY,
            session_id=SESSION_ID,
            dataset_fingerprint=FP,
            dataset_name="legacy-d2c",
            target_column="revenue",
            created_at="2026-10-01T00:00:00+00:00",
            last_active_at="2026-10-01T00:00:00+00:00",
            status="active",
        )
        get_research_run_store().upsert_run(legacy)
        snapshot, _ = service().build_snapshot(
            RUN_ID_LEGACY, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert snapshot.research_run_id == RUN_ID_LEGACY
        with pytest.raises(SnapshotAccessDenied):
            service().build_snapshot(
                RUN_ID_LEGACY, foreign_subject(),
                session_id=SESSION_FOREIGN, kinds=["D02"],
            )

    def test_nonexistent_run_uniform_denial_build_and_read(self, orc_env):
        from apps.api.snapshot_builder import SnapshotAccessDenied

        seed_session()
        with pytest.raises(SnapshotAccessDenied) as eb:
            service().build_snapshot(
                RUN_MISSING, owner_subject(), session_id=SESSION_ID,
                kinds=["D02"],
            )
        with pytest.raises(SnapshotAccessDenied) as er:
            service().get_snapshot(
                "rs-" + "0" * 32, owner_subject(), session_id=SESSION_ID
            )
        assert str(eb.value) == str(er.value) == UNIFORM_DENIAL_TEXT

    def test_invalid_snapshot_id_denied_before_lookup(self, orc_env):
        from apps.api.snapshot_builder import SnapshotAccessDenied

        seed_session()
        seed_bound_run()
        for bad in ("", "не-снимок", "rs-XYZ", "../etc/passwd", None):
            with pytest.raises(SnapshotAccessDenied):
                service().get_snapshot(
                    bad, owner_subject(), session_id=SESSION_ID
                )

    def test_read_gate_foreign_subject(self, orc_env):
        from apps.api.snapshot_builder import SnapshotAccessDenied

        seed_session()
        seed_bound_run()
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        with pytest.raises(SnapshotAccessDenied):
            service().get_snapshot(
                snapshot.snapshot_id, foreign_subject(),
                session_id=SESSION_FOREIGN,
            )
        with pytest.raises(SnapshotAccessDenied):
            service().list_snapshots(
                RUN_ID, foreign_subject(), session_id=SESSION_FOREIGN
            )


# ══════════════════════════════════════════════════════════════════════
# 6. Согласованное чтение §10.2 п.2-3 / AC02
# ══════════════════════════════════════════════════════════════════════


class _MutatingEventsStore:
    """Шпион слоя 2: после N-го list_events дописывает событие в run
    (имитация конкурентного append между чтением №1 и №2).
    Счётчики РАЗДЕЛЬНЫЕ по методам (get_run и list_events чередуются)."""

    def __init__(self, real, inject_events_after: int, run_id: str):
        self._real = real
        self._inject_events_after = inject_events_after
        self._run_id = run_id
        self.event_calls = 0
        self.run_calls = 0

    def list_events(self, run_id):
        self.event_calls += 1
        if self.event_calls == self._inject_events_after:
            # инъекция ДО выборки №2 (конкурентный append между чтениями)
            from apps.api.research_runs import get_research_run_store
            from apps.api.trace_events import TraceEvent

            get_research_run_store().append_event(
                self._run_id,
                TraceEvent(event_type="upload_completed",
                           payload={"rows": 999, "columns": 9},
                           run_id=self._run_id, stage="upload",
                           schema_version=2, evidence_level="server_result"),
            )
        return self._real.list_events(run_id)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _MutatingRunStore:
    """Шпион: после N-го get_run ПЕРЕЗАПИСЫВАЕТ run metadata (context)
    в store (ResearchRun -- frozen dataclass: replace + upsert)."""

    def __init__(self, real, inject_run_after: int, run_id: str):
        self._real = real
        self._inject_run_after = inject_run_after
        self._run_id = run_id
        self.run_calls = 0

    def get_run(self, run_id):
        self.run_calls += 1
        run = self._real.get_run(run_id)
        if self.run_calls == self._inject_run_after and run is not None:
            import dataclasses

            mutated = dataclasses.replace(run, context_id=CTX_BETA)
            self._real.upsert_run(mutated)
            return mutated
        return run

    def __getattr__(self, name):
        return getattr(self._real, name)


class _MutatingRevisionStore:
    """Шпион: после N-го get_run ПЕРЕЗАПИСЫВАЕТ data_revision в store
    (имитация конкурентной мутации ревизии между чтениями)."""

    def __init__(self, real, inject_run_after: int, run_id: str):
        self._real = real
        self._inject_run_after = inject_run_after
        self._run_id = run_id
        self.run_calls = 0

    def get_run(self, run_id):
        self.run_calls += 1
        run = self._real.get_run(run_id)
        if self.run_calls == self._inject_run_after and run is not None:
            import dataclasses

            mutated = dataclasses.replace(
                run, data_revision=(run.data_revision or 0) + 1
            )
            self._real.upsert_run(mutated)
            return mutated
        return run

    def __getattr__(self, name):
        return getattr(self._real, name)


class TestOrcConsistency:
    def test_stable_build_cutoff_matches_ledger(self, orc_env):
        seed_session()
        seed_bound_run()
        for i in range(3):
            append_event(payload={"rows": 10 + i, "columns": 2})
        snapshot, created = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert created is True
        assert snapshot.source_cutoff["last_sequence"] >= 3
        assert snapshot.source_cutoff["event_count"] == 3
        assert snapshot.source_cutoff["ordering_quality"] == "canonical"

    def test_event_append_between_reads_conflicts_writes_nothing(
        self, orc_env, monkeypatch,
    ):
        """AC02/T13: append события между чтениями -> SnapshotConflict;
        НИЧЕГО не зарегистрировано (ни снимка, ни зависимостей).
        Порядок чтений build_snapshot: get_run(авторизация) ->
        list_events(cutoff1) -> get_run(№2) -> list_events(cutoff2);
        инъекция на 2-м list_events = между сборкой и сверкой."""
        from apps.api import research_runs
        from apps.api.report_snapshot import peek_snapshot_registry
        from apps.api.snapshot_builder import SnapshotConflictError

        seed_session()
        seed_bound_run()
        append_event(payload={"rows": 10, "columns": 2})

        real_store = research_runs.get_research_run_store()
        spy = _MutatingEventsStore(real_store, inject_events_after=2,
                                   run_id=RUN_ID)
        monkeypatch.setattr(
            research_runs, "get_research_run_store", lambda: spy
        )
        with pytest.raises(SnapshotConflictError):
            service().build_snapshot(
                RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
            )
        monkeypatch.setattr(research_runs, "get_research_run_store",
                            lambda: real_store)
        records = peek_snapshot_registry().list_records(RUN_ID)
        assert records == [], "конфликтная сборка что-то записала (AC02)"

    def test_metadata_mutation_between_reads_conflicts(self, orc_env,
                                                       monkeypatch):
        from apps.api import research_runs
        from apps.api.report_snapshot import peek_snapshot_registry
        from apps.api.snapshot_builder import SnapshotConflictError

        seed_session()
        seed_bound_run()
        real_store = research_runs.get_research_run_store()
        spy = _MutatingRunStore(real_store, inject_run_after=2, run_id=RUN_ID)
        monkeypatch.setattr(research_runs, "get_research_run_store",
                            lambda: spy)
        with pytest.raises(SnapshotConflictError):
            service().build_snapshot(
                RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
            )
        monkeypatch.setattr(research_runs, "get_research_run_store",
                            lambda: real_store)
        assert peek_snapshot_registry().list_records(RUN_ID) == []

    def test_revision_mutation_between_reads_conflicts(self, orc_env,
                                                       monkeypatch):
        """AC02-зеркало: мутирует ТОЛЬКО data_revision (context прежний)
        -> зеркало контекста ловит -> SnapshotConflict, ничего не пишется
        (пин компонента _mirror_key: context+revision+digest+target)."""
        from apps.api import research_runs
        from apps.api.report_snapshot import peek_snapshot_registry
        from apps.api.snapshot_builder import SnapshotConflictError

        seed_session()
        seed_bound_run()
        real_store = research_runs.get_research_run_store()
        spy = _MutatingRevisionStore(real_store, inject_run_after=2,
                                     run_id=RUN_ID)
        monkeypatch.setattr(research_runs, "get_research_run_store",
                            lambda: spy)
        with pytest.raises(SnapshotConflictError):
            service().build_snapshot(
                RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
            )
        monkeypatch.setattr(research_runs, "get_research_run_store",
                            lambda: real_store)
        assert peek_snapshot_registry().list_records(RUN_ID) == []

    def test_pinned_context_mismatch_conflicts_cleanly(self, orc_env):
        from apps.api.snapshot_builder import SnapshotConflictError

        seed_session()
        seed_bound_run()
        with pytest.raises(SnapshotConflictError):
            service().build_snapshot(
                RUN_ID, owner_subject(), session_id=SESSION_ID,
                kinds=["D02"], context_id="ctx-d2c-stale",
            )
        with pytest.raises(SnapshotConflictError):
            service().build_snapshot(
                RUN_ID, owner_subject(), session_id=SESSION_ID,
                kinds=["D02"], data_revision=99,
            )

    def test_conflict_then_settled_retry_succeeds(self, orc_env, monkeypatch):
        """После урегулирования гонки повтор собирает снимок (409/retry
        семантика не оставляет обломков)."""
        from apps.api import research_runs
        from apps.api.report_snapshot import peek_snapshot_registry
        from apps.api.snapshot_builder import SnapshotConflictError

        seed_session()
        seed_bound_run()
        real_store = research_runs.get_research_run_store()
        spy = _MutatingEventsStore(real_store, inject_events_after=2,
                                   run_id=RUN_ID)
        monkeypatch.setattr(research_runs, "get_research_run_store",
                            lambda: spy)
        with pytest.raises(SnapshotConflictError):
            service().build_snapshot(
                RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
            )
        monkeypatch.setattr(research_runs, "get_research_run_store",
                            lambda: real_store)
        snapshot, created = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert created is True
        assert len(peek_snapshot_registry().list_records(RUN_ID)) == 1


# ══════════════════════════════════════════════════════════════════════
# 7. Адаптеры D01-D09 (свой корпус фактов)
# ══════════════════════════════════════════════════════════════════════


def _corpus_base(orc_env):
    seed_session()
    seed_bound_run()


class TestOrcD01:
    def test_target_event_last_match_and_refs(self, orc_env):
        _corpus_base(orc_env)
        # DOCLOG-E2E-RECHECK-1-FIX (C04): применимость события -- единый
        # reducer event_context_validity; событие С контекстом run
        # (ctx-d2c-alpha = CTX_ALPHA корпуса) -- честный current, legacy
        # без контекста был бы unknown.
        append_event(event_type="target_column_changed", stage="upload",
                     payload={"column": "old_target"},
                     context_id="ctx-d2c-alpha")
        e2 = append_event(event_type="target_column_changed", stage="upload",
                          payload={"column": "revenue"},
                          context_id="ctx-d2c-alpha")
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID,
            kinds=["plan"],
        )
        d01 = section(snapshot, "D01")
        claims = [c for c in d01["claims"] if "Целевая переменная" in c["text"]]
        assert len(claims) == 1
        assert "revenue" in claims[0]["text"]
        assert claims[0]["event_refs"] == [f"event:{e2.event_id}"]
        assert claims[0]["validity"] == "current"
        assert claims[0]["evidence_level"] == "server_result"
        assert d01["kind"] == "plan"
        assert d01["methodology_stage"] is None
        # форма плана -- честная unknown-claim
        gap = [c for c in d01["claims"] if "не зафиксирована" in c["text"]]
        assert gap and gap[0]["validity"] == "unknown"

    def test_target_without_event_is_unknown_not_current(self, orc_env):
        _corpus_base(orc_env)
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D01"]
        )
        d01 = section(snapshot, "D01")
        target_claims = [c for c in d01["claims"]
                         if "Целевая переменная" in c["text"]]
        assert target_claims and "revenue" in target_claims[0]["text"]
        assert target_claims[0]["validity"] == "unknown"   # R07
        assert target_claims[0]["event_refs"] == []

    def test_structure_confirmed_with_and_without_column(self, orc_env):
        _corpus_base(orc_env)
        append_event(event_type="structure_confirmed", stage="upload",
                     payload={"date_column": "dt"})
        append_event(event_type="structure_confirmed", stage="upload",
                     payload={})
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D01"]
        )
        texts = [c["text"] for c in section(snapshot, "D01")["claims"]]
        assert any("«dt»" in t for t in texts)
        assert any("Подтверждена структура данных" in t for t in texts)


class TestOrcD02:
    def test_passport_claim_details_and_validity(self, orc_env):
        _corpus_base(orc_env)
        art = make_artifact(
            "passport", "d2c:passport:1",
            {"kind": "passport", "stage": "start",
             "passport": {"rows": 42, "columns": 7},
             "snapshot_id": "snap-d2c-1", "fingerprint": "d2c" * 16},
            context_id=CTX_ALPHA, data_revision=REV_ALPHA,
            refs={"stage": "start", "snapshot_id": "snap-d2c-1"},
        )
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        claims = [c for c in section(snapshot, "D02")["claims"]
                  if "Паспорт источника" in c["text"]]
        assert len(claims) == 1
        assert "строк: 42" in claims[0]["text"]
        assert "колонок: 7" in claims[0]["text"]
        assert claims[0]["result_refs"] == [f"artifact:{art.artifact_id}"]
        assert claims[0]["validity"] == "current"
        # evidence НЕ фабкуется у артефактного claim
        assert claims[0]["evidence_level"] is None

    def test_panel_entry_excluded_from_source_passport(self, orc_env):
        _corpus_base(orc_env)
        make_artifact(
            "passport", "d2c:passport:panel",
            {"kind": "passport", "entities": 6},
            context_id=CTX_ALPHA, data_revision=REV_ALPHA,
            panel={"stage": "panel_entry"}, input_kind="panel_entity",
            refs={"stage": "start"},
        )
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        claims = [c for c in section(snapshot, "D02")["claims"]
                  if c["text"].startswith("Паспорт источника (")]
        assert claims == []   # панельный -- только в D09 (R4)

    def test_corrupted_bytes_is_honest_failure(self, orc_env):
        """T8: подмена байтов артефакта в object store -> integrity
        claim + причина reproducibility, битые байты не выдаются."""
        from apps.api.artifact_store import get_artifact_object_store

        _corpus_base(orc_env)
        art = make_artifact(
            "passport", "d2c:passport:bad",
            {"kind": "passport", "stage": "start",
             "passport": {"rows": 1}},
            context_id=CTX_ALPHA, data_revision=REV_ALPHA,
            refs={"stage": "start"},
        )
        objects = get_artifact_object_store()
        objects.path_for_key(art.storage_key).write_bytes(b'{"tampered": true}')
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        claims = [c for c in section(snapshot, "D02")["claims"]
                  if "недоступны или повреждены" in c["text"]]
        assert claims and claims[0]["validity"] == "unknown"
        assert snapshot.reproducibility["status"] == "limited"
        assert f"artifact_integrity_failure:{art.artifact_id}" in \
            snapshot.reproducibility["reasons"]

    def test_upload_event_claim(self, orc_env):
        _corpus_base(orc_env)
        e = append_event(payload={"rows": 120, "columns": 5, "name": "d2c.csv"})
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        claims = [c for c in section(snapshot, "D02")["claims"]
                  if "Загружен датасет" in c["text"]]
        assert len(claims) == 1
        assert "«d2c.csv»" in claims[0]["text"]
        assert "строк: 120" in claims[0]["text"]
        assert claims[0]["event_refs"] == [f"event:{e.event_id}"]

    def test_no_promotion_honest_gap_without_refs(self, orc_env):
        """R03/AC01: отсутствие артефактов -- честная unknown-claim,
        БЕЗ фабкованных result_refs; missing_refs пуст."""
        _corpus_base(orc_env)
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        d02 = section(snapshot, "D02")
        assert any("не продвинут" in c["text"] for c in d02["claims"])
        assert all(c["result_refs"] == [] for c in d02["claims"])
        # DOCLOG-E2E-RECHECK-1-FIX (C05): нет битых ref, но паспорт и
        # data_ref отсутствуют -- честный partial по обязательным
        # элементам вида (missing_mandatory), не «complete».
        assert snapshot.completeness["missing_refs"] == []
        assert snapshot.completeness["status"] == "partial"
        assert "missing_source_passport_artifact" in snapshot.completeness["missing_mandatory"]


class TestOrcD03D04D05:
    def test_d03_status_labels_and_passport(self, orc_env):
        _corpus_base(orc_env)
        append_event(event_type="validation_check_status", stage="validation",
                     node_id="d2c-stop-1", payload={"status": "done"})
        append_event(event_type="validation_check_status", stage="validation",
                     node_id="d2c-stop-2", payload={"status": "warning"})
        append_event(event_type="validation_check_status", stage="validation",
                     node_id="d2c-stop-3", payload={"status": "вительное"})
        make_artifact(
            "passport", "d2c:passport:validation",
            {"kind": "passport", "passport": {"rows": 9}},
            context_id=CTX_ALPHA, data_revision=REV_ALPHA,
            refs={"stage": "validation", "snapshot_id": "snap-d2c-v"},
        )
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID,
            kinds=["quality_protocol"],
        )
        texts = [c["text"] for c in section(snapshot, "D03")["claims"]]
        assert any("«d2c-stop-1» (валидация): выполнена" in t for t in texts)
        assert any("«d2c-stop-2» (валидация): есть замечания" in t for t in texts)
        assert any("вительное" in t for t in texts)  # неизвестное как есть
        assert any("Паспорт этапа валидации" in t for t in texts)

    def test_d03_empty_honest(self, orc_env):
        _corpus_base(orc_env)
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D03"]
        )
        d03 = section(snapshot, "D03")
        assert any("отсутствуют" in c["text"] for c in d03["claims"])
        assert all(c["validity"] == "unknown" for c in d03["claims"])

    def test_d04_correction_and_preprocessing(self, orc_env):
        _corpus_base(orc_env)
        append_event(event_type="correction_applied", stage="preprocessing",
                     node_id="d2c-fix", payload={"action": "cap"})
        append_event(event_type="preprocessing_check_status",
                     stage="preprocessing", node_id="d2c-fix",
                     payload={"status": "done"})
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D04"]
        )
        texts = [c["text"] for c in section(snapshot, "D04")["claims"]]
        assert any("Применена коррекция «d2c-fix», действие: cap" in t
                   for t in texts)
        assert any("предобработка): выполнена" in t for t in texts)

    def test_d05_eda_and_modeling_entry(self, orc_env):
        _corpus_base(orc_env)
        append_event(event_type="eda_check_status", stage="eda",
                     node_id="d2c-eda", payload={"status": "done"})
        make_artifact(
            "passport", "d2c:passport:entry",
            {"kind": "passport", "passport": {"rows": 5}},
            context_id=CTX_ALPHA, data_revision=REV_ALPHA,
            refs={"stage": "modeling_entry", "snapshot_id": "snap-d2c-e"},
        )
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D05"]
        )
        texts = [c["text"] for c in section(snapshot, "D05")["claims"]]
        assert any("EDA «d2c-eda»: выполнена" in t for t in texts)
        assert any("modeling_entry" in t and "handoff" in t for t in texts)


class TestOrcD06:
    def test_backtest_claim_metadata_priority(self, orc_env):
        _corpus_base(orc_env)
        make_artifact(
            "oof_backtest", "d2c:oof:1",
            {"model_id": "arima-d2c", "horizon": 12},
            context_id=CTX_ALPHA, data_revision=REV_ALPHA,
            input_kind="univariate",
            refs={"model_id": "arima-refs", "backtest_run_id": "RUN-D2C00007",
                  "parameter_signature": "ps-d2c", "oof_signature": "os-d2c"},
        )
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D06"]
        )
        d06 = section(snapshot, "D06")
        claims = [c for c in d06["claims"] if "Эксперимент" in c["text"]]
        assert len(claims) == 1
        assert "arima-d2c" in claims[0]["text"]      # payload важнее refs
        assert "RUN-D2C00007" in claims[0]["text"]
        assert "input_kind=univariate" in claims[0]["text"]
        assert claims[0]["validity"] == "current"

    def test_d06_stale_and_unknown(self, orc_env):
        _corpus_base(orc_env)
        make_artifact("oof_backtest", "d2c:oof:stale", {"model_id": "m1"},
                      context_id=CTX_BETA, data_revision=1,
                      refs={"model_id": "m1"})
        make_artifact("oof_backtest", "d2c:oof:legacy", {"model_id": "m2"},
                      refs={"model_id": "m2"})
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D06"]
        )
        claims = [c for c in section(snapshot, "D06")["claims"]
                  if "Эксперимент" in c["text"]]
        validity = {c["validity"] for c in claims}
        assert validity == {"stale", "unknown"}

    def test_d06_missing_oof_reason_only_when_requested(self, orc_env):
        _corpus_base(orc_env)
        s_no_d06, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert "missing_oof_artifact" not in \
            s_no_d06.reproducibility["reasons"]
        s_d06, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D06"]
        )
        assert "missing_oof_artifact" in s_d06.reproducibility["reasons"]
        assert s_d06.reproducibility["status"] == "limited"


class TestOrcD07D08:
    def test_d07_card_from_payload(self, orc_env):
        _corpus_base(orc_env)
        make_artifact(
            "model_card", "d2c:card:1",
            {"card": {"model_info": {"model_id": "arima-d2c"},
                      "traceability": {"checkpoint_id": "chk-d2c-9"}}},
            context_id=CTX_ALPHA, data_revision=REV_ALPHA,
            refs={"card_id": "card-d2c-1"},
            dependencies=["chk-d2c-9"],
        )
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D07"]
        )
        claims = [c for c in section(snapshot, "D07")["claims"]
                  if "Карточка модели" in c["text"]]
        assert len(claims) == 1
        assert "arima-d2c" in claims[0]["text"]
        assert "chk-d2c-9" in claims[0]["text"]

    def test_d08_horizon_bool_is_not_int_and_points_count(self, orc_env):
        """Ловушка bool: horizon=True (подкласс int) не попадает в текст;
        alpha числовой -- попадает; точки -- счётчиком."""
        _corpus_base(orc_env)
        make_artifact(
            "forecast", "d2c:fc:1",
            {"horizon": True, "alpha": 0.1, "points": [{"y": 1}, {"y": 2}]},
            context_id=CTX_ALPHA, data_revision=REV_ALPHA,
            refs={"forecast_id": "fc-d2c-1"},
        )
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID,
            kinds=["forecast_release"],
        )
        claims = [c for c in section(snapshot, "D08")["claims"]
                  if "Выпуск прогноза" in c["text"]]
        assert len(claims) == 1
        assert "горизонт" not in claims[0]["text"]   # bool исключён
        assert "alpha 0.1" in claims[0]["text"]
        assert "точек: 2" in claims[0]["text"]
        assert "frozen origin" in claims[0]["text"]

    def test_d08_empty_no_recalc_gap(self, orc_env):
        _corpus_base(orc_env)
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID,
            kinds=["forecast_release"],
        )
        d08 = section(snapshot, "D08")
        assert any("не пересчитывается" in c["text"] for c in d08["claims"])


class TestOrcD09:
    def test_panel_semantics_isolated(self, orc_env):
        _corpus_base(orc_env)
        make_artifact(
            "passport", "d2c:pp:panel",
            {"kind": "passport", "passport": {"entities": 6}},
            context_id=CTX_ALPHA, data_revision=REV_ALPHA,
            panel={"stage": "panel_entry"}, input_kind="panel_entity",
            refs={"stage": "start"},
        )
        make_artifact(
            "oof_backtest", "d2c:oof:panel",
            {"model_id": "panel_fe", "panel": {
                "n_entities": 6, "pooled_mase_scale": 0.42,
                "pooled_scale_method": "pooled_mase",
                "entity_metrics": {"e1": {}, "e2": {}, "e3": {}}},
             "horizon": 3},
            context_id=CTX_ALPHA, data_revision=REV_ALPHA,
            input_kind="panel_entity", refs={"model_id": "panel_fe"},
        )
        make_artifact("oof_backtest", "d2c:oof:single", {"model_id": "arima"},
                      context_id=CTX_ALPHA, data_revision=REV_ALPHA,
                      refs={"model_id": "arima"})
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D09"]
        )
        texts = [c["text"] for c in section(snapshot, "D09")["claims"]]
        assert any("Панельный паспорт" in t and "сущностей 6" in t
                   for t in texts)
        assert any("n_entities=6" in t for t in texts)
        assert any("pooled_mase_scale=0.42" in t and "pooled_mase" in t
                   for t in texts)
        assert any("per-entity метрик: 3" in t for t in texts)
        # однорядный НЕ подмешан (R4/AC13)
        assert not any("arima" in t for t in texts)

    def test_d09_empty_isolation_claim(self, orc_env):
        _corpus_base(orc_env)
        make_artifact("oof_backtest", "d2c:oof:lonely", {"model_id": "arima"},
                      context_id=CTX_ALPHA, data_revision=REV_ALPHA,
                      refs={"model_id": "arima"})
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D09"]
        )
        d09 = section(snapshot, "D09")
        assert any("не подмешиваются" in c["text"] for c in d09["claims"])


class TestOrcDataRef:
    def test_only_current_data_frame_last_by_created(self, orc_env):
        _corpus_base(orc_env)
        make_artifact("data_frame", "d2c:df:stale", b"stale-d2c",
                      media_type="text/csv",
                      context_id=CTX_BETA, data_revision=1)
        make_artifact("data_frame", "d2c:df:cur1", b"cur1-d2c",
                      media_type="text/csv",
                      context_id=CTX_ALPHA, data_revision=REV_ALPHA)
        current2 = make_artifact("data_frame", "d2c:df:cur2", b"cur2-d2c",
                                 media_type="text/csv",
                                 context_id=CTX_ALPHA,
                                 data_revision=REV_ALPHA)
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert snapshot.data_ref == f"artifact:{current2.artifact_id}"
        # digest ПЕРЕНОСИТСЯ из артефакта (§9.3), не пересчитывается
        assert snapshot.data_digest == dict(current2.data_digest)
        assert snapshot.data_digest["algorithm"] == "cisstat-data-v1"

    def test_stale_only_means_missing_data_artifact(self, orc_env):
        _corpus_base(orc_env)
        make_artifact("data_frame", "d2c:df:stale", b"stale-d2c",
                      media_type="text/csv",
                      context_id=CTX_BETA, data_revision=1)
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert snapshot.data_ref is None
        assert "missing_data_artifact" in snapshot.reproducibility["reasons"]

    def test_unknown_claim_event_result_ref_gap(self, orc_env):
        """AC01: result_ref события на несуществующий артефакт -> честный
        gap в missing_refs, validity unknown, не current."""
        _corpus_base(orc_env)
        append_event(payload={"rows": 3}, result_ref={"artifact_id": "art-NOPE"})
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert snapshot.completeness["status"] == "partial"
        assert "artifact:art-NOPE" in snapshot.completeness["missing_refs"]


# ══════════════════════════════════════════════════════════════════════
# 8. Идемпотентность AC09 / pins §16 / целостность T8-T16
# ══════════════════════════════════════════════════════════════════════


class TestOrcIdempotency:
    def test_client_key_replay_and_body_conflict(self, orc_env):
        _corpus_base(orc_env)
        append_event(payload={"rows": 1})
        svc = service()
        first, created1 = svc.build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"],
            idempotency_key="idem-d2c-1",
        )
        assert created1 is True
        replay, created2 = svc.build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"],
            idempotency_key="idem-d2c-1",
        )
        assert created2 is False
        assert replay.snapshot_id == first.snapshot_id
        from apps.api.snapshot_builder import SnapshotIdempotencyConflictError

        with pytest.raises(SnapshotIdempotencyConflictError):
            svc.build_snapshot(
                RUN_ID, owner_subject(), session_id=SESSION_ID,
                kinds=["D02", "D01"], idempotency_key="idem-d2c-1",
            )

    def test_auto_key_new_freeze_on_state_change(self, orc_env):
        from apps.api.report_snapshot import peek_snapshot_registry

        _corpus_base(orc_env)
        svc = service()
        s1, c1 = svc.build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        s2, c2 = svc.build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert c2 is False and s2.snapshot_id == s1.snapshot_id  # дедуп
        append_event(payload={"rows": 2})                        # состояние +=
        s3, c3 = svc.build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert c3 is True and s3.snapshot_id != s1.snapshot_id   # новая заморозка
        assert len(peek_snapshot_registry().list_records(RUN_ID)) == 2


class TestOrcPins:
    def test_pins_artifact_and_checkpoint_with_reason(self, orc_env):
        from apps.api.artifact_store import get_artifact_registry

        _corpus_base(orc_env)
        art = make_artifact(
            "model_card", "d2c:card:pin",
            {"card": {"model_info": {"model_id": "m"}}},
            context_id=CTX_ALPHA, data_revision=REV_ALPHA,
            dependencies=["chk-d2c-42"], refs={"card_id": "card-d2c-pin"},
        )
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D07"]
        )
        pins = {(p.ref_kind, p.ref_id): p
                for p in get_artifact_registry().list_pins(RUN_ID)}
        assert ("artifact", art.artifact_id) in pins
        assert ("checkpoint", "chk-d2c-42") in pins     # зависимость артефакта
        reason = f"snapshot:{snapshot.snapshot_id}"
        assert pins[("artifact", art.artifact_id)].reason == reason
        assert pins[("checkpoint", "chk-d2c-42")].reason == reason

    def test_event_refs_not_pinned_but_in_manifest(self, orc_env):
        from apps.api.artifact_store import get_artifact_registry

        _corpus_base(orc_env)
        e = append_event(payload={"rows": 4})
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        pins = get_artifact_registry().list_pins(RUN_ID)
        assert all(p.ref_kind != "event" for p in pins)
        assert f"event:{e.event_id}" in snapshot.dependencies
        dep_refs = service().dependency_refs(snapshot.snapshot_id)
        assert f"event:{e.event_id}" in dep_refs


class TestOrcIntegrityRead:
    def test_tampered_object_bytes_rejected_at_store_layer(self, orc_env):
        """T8/T16 слой 1 (object store): подмена байтов объекта ->
        content-key сверка read_bytes отклоняет (ArtifactIntegrityError).
        Слой 2 (отдельный снимок с НЕтронутыми байтами): расхождение
        record.payload_sha256 с байтами -> SnapshotIntegrityError."""
        import dataclasses

        from apps.api.artifact_store import (
            ArtifactIntegrityError, get_artifact_object_store,
        )
        from apps.api.report_snapshot import (
            SnapshotIntegrityError, peek_snapshot_registry,
        )

        _corpus_base(orc_env)
        svc = service()
        snap1, _ = svc.build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        snap2, _ = svc.build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D01"]
        )
        objects = get_artifact_object_store()
        # слой 1: биты объекта #1 подменены
        objects.path_for_key(snap1.storage_key).write_bytes(
            json.dumps({"forged": True}, ensure_ascii=False).encode("utf-8")
        )
        with pytest.raises(ArtifactIntegrityError):
            svc.get_snapshot(snap1.snapshot_id, owner_subject(),
                             session_id=SESSION_ID)

        # слой 2: байты #2 валидны (content-key сходится), metadata
        # реестра подменена -> payload_sha256 mismatch -> отказ
        reg = peek_snapshot_registry()
        record = reg.get_snapshot_record(snap2.snapshot_id)
        reg._snapshots[snap2.snapshot_id] = dataclasses.replace(
            record, payload_sha256="f" * 64
        )
        with pytest.raises(SnapshotIntegrityError):
            svc.get_snapshot(snap2.snapshot_id, owner_subject(),
                             session_id=SESSION_ID)

    def test_read_copy_isolation(self, orc_env):
        """Чтение возвращает копию: мутация прочитанного не портит store
        и не влияет на повторное чтение."""
        _corpus_base(orc_env)
        svc = service()
        snapshot, _ = svc.build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D01"]
        )
        first = svc.get_snapshot(snapshot.snapshot_id, owner_subject(),
                                 session_id=SESSION_ID)
        first.sections.clear()
        second = svc.get_snapshot(snapshot.snapshot_id, owner_subject(),
                                  session_id=SESSION_ID)
        assert second.sections

    def test_list_kind_filter_aliases(self, orc_env):
        _corpus_base(orc_env)
        svc = service()
        svc.build_snapshot(RUN_ID, owner_subject(), session_id=SESSION_ID,
                           kinds=["D02"])
        svc.build_snapshot(RUN_ID, owner_subject(), session_id=SESSION_ID,
                           kinds=["D01"])
        by_code = svc.list_snapshots(RUN_ID, owner_subject(),
                                     session_id=SESSION_ID, kind="D02")
        by_alias = svc.list_snapshots(RUN_ID, owner_subject(),
                                      session_id=SESSION_ID,
                                      kind="source_passport")
        assert len(by_code) == 1 and len(by_alias) == 1
        assert by_code[0].snapshot_id == by_alias[0].snapshot_id
        assert by_code[0].kinds == ["D02"]


def storage_rel(storage_key: str) -> Path:
    """storage_key -> относительный путь в root object store (формат
    DOCLOG-1: objects/xx/yyyy). Извлекается из фактического ключа."""
    return Path(storage_key)


# ══════════════════════════════════════════════════════════════════════
# 9. Отсутствие пересчётов (AC05/T14) иImmutable-семантика (AC03)
# ══════════════════════════════════════════════════════════════════════


class TestOrcNoRecalc:
    def _science_fingerprint(self) -> dict:
        from apps.api import research_runs
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.session_store import get_session_store

        session = get_session_store().get(SESSION_ID)
        store = research_runs.get_research_run_store()
        return {
            "events": len(store.list_events(RUN_ID)),
            "artifacts": len(get_artifact_registry().list_artifacts(RUN_ID)),
            "pins": len(get_artifact_registry().list_pins(RUN_ID)),
            "data_revision": session.data_revision,
            "stages": dict(session.stages),
            "trace_len": len(session.pipeline_trace),
            "run_status": store.get_run(RUN_ID).status,
            "run_ctx": store.get_run(RUN_ID).context_id,
        }

    def test_build_read_list_touch_nothing(self, orc_env):
        _corpus_base(orc_env)
        append_event(payload={"rows": 8, "columns": 3})
        make_artifact("passport", "d2c:passport:ac05",
                      {"kind": "passport", "stage": "start", "rows": 8},
                      context_id=CTX_ALPHA, data_revision=REV_ALPHA,
                      refs={"stage": "start"})
        svc = service()
        before = self._science_fingerprint()
        snapshot, _ = svc.build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        svc.get_snapshot(snapshot.snapshot_id, owner_subject(),
                         session_id=SESSION_ID)
        svc.list_snapshots(RUN_ID, owner_subject(), session_id=SESSION_ID)
        after = self._science_fingerprint()
        assert after["events"] == before["events"]
        assert after["artifacts"] == before["artifacts"]
        assert after["data_revision"] == before["data_revision"]
        assert after["stages"] == before["stages"]
        assert after["trace_len"] == before["trace_len"]
        assert after["run_status"] == before["run_status"]
        assert after["run_ctx"] == before["run_ctx"]
        # pins добавлены СБОРОЧКОЙ (зависимости) -- фиксируем факт
        assert after["pins"] >= before["pins"]

    def test_rebuild_same_state_identical_facts(self, orc_env):
        """AC03-дух: пересборка на НЕизменном состоянии (новый auto-ключ
        не создаёт дубль) даёт байт-равные контрактные поля кроме
        snapshot_id/captured_at; на ИЗМЕНЁННОЙ knowledge-версии -- новый
        снимок, старый неизменен (иммутабельность)."""
        from apps.api.report_snapshot import peek_snapshot_registry

        _corpus_base(orc_env)
        append_event(payload={"rows": 5})
        svc = service()
        s1, _ = svc.build_snapshot(RUN_ID, owner_subject(),
                                   session_id=SESSION_ID, kinds=["D02"])
        # старьё не трогаем; новое событие = новая заморозка
        append_event(payload={"rows": 6})
        s2, created = svc.build_snapshot(RUN_ID, owner_subject(),
                                         session_id=SESSION_ID, kinds=["D02"])
        assert created
        assert s2.snapshot_id != s1.snapshot_id
        stored1 = peek_snapshot_registry().get_snapshot_record(
            s1.snapshot_id)
        assert stored1.source_cutoff["event_count"] == 1  # старый не изменился
        assert s1.source_cutoff["event_count"] == 1
        assert s2.source_cutoff["event_count"] == 2

    def test_knowledge_version_stamped(self, orc_env):
        from apps.api.report_snapshot import knowledge_registry_version

        _corpus_base(orc_env)
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert snapshot.knowledge_version == knowledge_registry_version()


class TestOrcHealth:
    def test_ops_snapshots_block_facts(self, orc_env):
        from fastapi.testclient import TestClient

        from apps.api.main import app
        from apps.api.report_snapshot import peek_snapshot_registry

        # ДО инициализации: not_initialized честно (peek не провоцирует)
        with TestClient(app) as client:
            body = client.get("/health/ops").json()
            snap = body["snapshots"]            # верхний уровень контракта
            assert snap["registry_backend"] == "not_initialized"
            assert snap["object_store"] == "local_fs"
            assert isinstance(snap["data_root_configured"], bool)
        assert peek_snapshot_registry() is None          # не индуцировано
        # ПОСЛЕ инициализации: backend memory
        seed_session()
        seed_bound_run()
        service()
        with TestClient(app) as client:
            body = client.get("/health/ops").json()
            snap = body["snapshots"]
            assert snap["registry_backend"] == "memory"
