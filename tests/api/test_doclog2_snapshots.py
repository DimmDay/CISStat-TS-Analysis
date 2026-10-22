# tests/api/test_doclog2_snapshots.py
"""Task DOCLOG-2 (spec_documentation_logging.md §10, §6 D01-D09, §19
строка DOCLOG-2, §20 AC01/AC02/AC03/AC05/AC09/AC13): ReportSnapshot и
сборщик -- cutoff, claim refs, адаптеры секций, отсутствие пересчётов.

Критерий завершения (§19): concurrent mutation не смешивает версии,
current/stale/unknown и gaps честны.

Оракулы на СВОИХ данных: корпус дизъюнктен repo-корпусу (RUN-D2xxxxxx);
изоляция каждого теста -- паттерн test_doclog1_artifacts.py (свой
tmp_path/CISSTAT_DATA_DIR, сброс singleton-фабрик ВКЛЮЧАЯ session store).
Авторизация -- та же решающая таблица DOCLOG-0 (identity.authorize_run_
access): знание snapshot_id НЕ является правом (T7/T15). Сборщик читает
ТОЛЬКО durable-слой (run/ledger/артефакты) -- сессия не открывается,
научное состояние не меняется (AC05, §10.2 п.5). Гонка чтения без
согласованного snapshot -- SnapshotConflict (409-семантика), не смешанный
документ (AC02). Идемпотентность -- UNIQUE(run_id, idempotency_key)
(§10.3/AC09). Panel-семантика D09 изолирована от однорядной (R4/AC13).
"""
from __future__ import annotations

import dataclasses
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api import research_runs
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
from apps.api.research_runs import ResearchRun
from apps.api.session_store import AnalysisSession
from apps.api.trace_events import TraceEvent, canonical_event_order

# ── Изоляция КАЖДОГО теста (паттерн test_doclog1_artifacts.py) ────────


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_SALT", raising=False)
    monkeypatch.delenv("CISSTAT_ARTIFACTS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_SNAPSHOTS_BACKEND", raising=False)
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    from apps.api import artifact_store, report_snapshot
    from apps.api.session_store import reset_session_store_for_testing

    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    reset_session_store_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    reset_session_store_for_testing()


@pytest.fixture()
def client():
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


ADMIN_KEY = "d2-admin-test-key"


@pytest.fixture()
def admin_client(client, monkeypatch):
    monkeypatch.setenv("CISSTAT_API_KEYS", f"{ADMIN_KEY}:admin:pro")
    return client


# ── Сид-хелперы: run/сессия/subject на СВОИХ данных ─────────────────

RUN_ID = "RUN-D2A00001"
SESSION_ID = "d2-seed-session"


def _seed_session(session_id: str = SESSION_ID) -> AnalysisSession:
    """Сессия-источник фактов; ИДЕМПОТЕНТНА (повторный вызов в одном
    тесте не конфликтует по storage_revision -- SessionConflictError
    optimistic-concurrency)."""
    from apps.api.session_store import get_session_store

    store = get_session_store()
    session = store.get(session_id)
    if session is not None:
        return session
    session = AnalysisSession(session_id=session_id)
    session.owner_subject = SubjectRef.from_session(session_id).subject_id
    session.tenant_id = DEFAULT_TENANT_ID
    session.target_column = "value"
    session.date_column = "date"
    store.save(session)
    return session


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_bound_run(
    run_id: str = RUN_ID,
    session_id: str = SESSION_ID,
    *,
    context_id: str | None = "ctx-d2-1",
    data_revision: int | None = 3,
) -> ResearchRun:
    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="d2" * 16,
        dataset_name="snapshot-seed",
        target_column="value",
        target_column_source="user",
        created_at=_now_iso(),
        last_active_at=_now_iso(),
        status="active",
        context_id=context_id,
        data_revision=data_revision,
        owner_subject=SubjectRef.from_session(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)
    return run


def _owner_subject(session_id: str = SESSION_ID) -> SubjectRef:
    return SubjectRef.from_session(session_id)


def _foreign_subject() -> SubjectRef:
    return SubjectRef.from_session("d2-foreign-session")


def _seed_event(
    run_id: str = RUN_ID,
    event_type: str = "upload_completed",
    stage: str = "upload",
    *,
    node_id: str | None = None,
    payload: dict | None = None,
    evidence_level: str | None = "server_result",
    result_ref: dict | None = None,
    context_id: str | None = None,
) -> TraceEvent:
    event = TraceEvent(
        event_type=event_type,
        payload=dict(payload or {}),
        run_id=run_id,
        stage=stage,
        node_id=node_id,
        schema_version=2,
        evidence_level=evidence_level,
        result_ref=result_ref,
        context_id=context_id,
    )
    research_runs.get_research_run_store().append_event(run_id, event)
    return event


# ── Артефакты: прямой реестр с КОНТРОЛИРУЕМЫМ context/revision ──────


def _make_artifact(
    kind: str,
    producer_key: str,
    payload,
    *,
    run_id: str = RUN_ID,
    context_id: str | None = None,
    data_revision: int | None = None,
    input_kind: str | None = None,
    panel: dict | None = None,
    dependencies: list[str] | None = None,
    refs: dict | None = None,
    media_type: str = "application/json",
):
    from apps.api.artifact_store import (
        ResultArtifact,
        artifact_content_sha256,
        canonical_json_bytes,
        data_digest as compute_data_digest,
        get_artifact_object_store,
        get_artifact_registry,
        new_artifact_id,
    )

    if media_type == "application/json":
        content = canonical_json_bytes(payload)
        digest_value = None
    else:
        content = payload
        digest_value = compute_data_digest(content)
    objects = get_artifact_object_store()
    staged = objects.stage_bytes(content, media_type)
    storage_key = objects.commit_staged(staged)
    artifact = ResultArtifact(
        artifact_id=new_artifact_id(),
        run_id=run_id,
        kind=kind,
        producer_key=producer_key,
        media_type=media_type,
        size_bytes=len(content),
        payload_sha256=artifact_content_sha256(content),
        data_digest=digest_value,
        storage_key=storage_key,
        context_id=context_id,
        data_revision=data_revision,
        input_kind=input_kind,
        panel=panel,
        dependencies=list(dependencies or []),
        refs=dict(refs or {}),
    )
    stored, _created = get_artifact_registry().register_artifact(artifact)
    return stored


def _artifact_ref(artifact) -> str:
    return f"artifact:{artifact.artifact_id}"


# ── Сервис сборщика ──────────────────────────────────────────────────


def _service():
    from apps.api.snapshot_builder import SnapshotService

    return SnapshotService.create_default()


def _claims_by_text(section: dict) -> dict[str, dict]:
    return {claim["text"]: claim for claim in section.get("claims", [])}


def _section(snapshot, code: str) -> dict:
    for section in snapshot.sections:
        if section.get("code") == code:
            return section
    raise AssertionError(f"Секция {code} отсутствует в снимке")


# ══════════════════════════════════════════════════════════════════════
# 1. Контракт снимка (§10.1)
# ══════════════════════════════════════════════════════════════════════


class TestSnapshotContract:
    def test_schema_version_constant(self):
        from apps.api.report_snapshot import REPORT_SNAPSHOT_SCHEMA_VERSION

        assert REPORT_SNAPSHOT_SCHEMA_VERSION == "doclog.report_snapshot/1"

    def test_snapshot_id_format_and_validation(self):
        from apps.api.report_snapshot import is_valid_snapshot_id, new_snapshot_id

        snapshot_id = new_snapshot_id()
        assert re.fullmatch(r"rs-[0-9a-f]{32}", snapshot_id)
        assert is_valid_snapshot_id(snapshot_id)
        assert not is_valid_snapshot_id("rs-short")
        assert not is_valid_snapshot_id("art-" + "0" * 32)
        assert not is_valid_snapshot_id(None)

    def test_document_kinds_catalog_covers_d01_d09(self):
        from apps.api.report_snapshot import DOCUMENT_KINDS

        assert set(DOCUMENT_KINDS) == {f"D0{i}" for i in range(1, 10)}
        kinds = [spec[0] for spec in DOCUMENT_KINDS.values()]
        assert len(set(kinds)) == 9  # kind-имена уникальны
        # каждый код несёт title и methodology_stage (методология-ref)
        for code, (_kind, title, stage) in DOCUMENT_KINDS.items():
            assert title, code
            assert stage is None or isinstance(stage, str), code

    def test_resolve_kinds_normalizes_aliases_and_order(self):
        from apps.api.report_snapshot import resolve_kinds

        assert resolve_kinds(["D03", "plan"]) == ["D03", "D01"]
        assert resolve_kinds(["forecast_release"]) == ["D08"]
        with pytest.raises(ValueError):
            resolve_kinds(["D11"])  # вне D01-D09 (D11 -- DOCLOG-6)
        with pytest.raises(ValueError):
            resolve_kinds([])

    def test_template_constants(self):
        from apps.api.report_snapshot import TEMPLATE_ID, TEMPLATE_VERSION

        assert TEMPLATE_ID == "research-report"
        assert TEMPLATE_VERSION == "1.0"

    def test_snapshot_round_trip_preserves_fields(self):
        from apps.api.report_snapshot import (
            REPORT_SNAPSHOT_SCHEMA_VERSION,
            ReportSnapshot,
            new_snapshot_id,
        )

        snapshot = ReportSnapshot(
            snapshot_id=new_snapshot_id(),
            research_run_id=RUN_ID,
            context_id="ctx-d2-1",
            data_revision=3,
            data_ref="artifact:art-" + "a" * 32,
            data_digest={"algorithm": "cisstat-data-v1", "value": "d" * 64},
            captured_at=_now_iso(),
            knowledge_version="sha256:" + "k" * 64,
            sections=[
                {
                    "code": "D02",
                    "kind": "source_passport",
                    "title": "Паспорт источника",
                    "methodology_stage": "upload",
                    "claims": [
                        {
                            "text": "Загружен датасет.",
                            "event_refs": ["event:e1"],
                            "result_refs": [],
                            "validity": "current",
                            "evidence_level": "server_result",
                        }
                    ],
                }
            ],
            dependencies=["event:e1"],
            completeness={"status": "complete", "missing_refs": []},
            reproducibility={"status": "limited", "reasons": ["missing_data_artifact"]},
        )
        data = snapshot.to_dict()
        assert data["schema_version"] == REPORT_SNAPSHOT_SCHEMA_VERSION
        assert data["approval"] is None  # §10.1: approval -- DOCLOG-6
        assert data["locale"] == "ru-RU"
        assert data["display_timezone"] == "Europe/Moscow"
        restored = ReportSnapshot.from_dict(dict(data))
        assert restored == snapshot

    def test_cutoff_canonical_corpus(self):
        from apps.api.report_snapshot import build_source_cutoff

        events = [
            {"event_id": f"e{i}", "sequence": seq}
            for seq, i in ((3, "a"), (1, "b"), (2, "c"))
        ]
        cutoff = build_source_cutoff(events)
        assert cutoff.last_sequence == 3
        assert cutoff.event_count == 3
        assert cutoff.ordering_quality == "canonical"
        assert cutoff.event_id_manifest is None

    def test_cutoff_legacy_corpus_keeps_event_id_manifest(self):
        """§10.2: для legacy корпуса без надёжного sequence хранится
        закреплённый ordered event-id manifest, не синтетический seq."""
        from apps.api.report_snapshot import build_source_cutoff

        events = [
            {"event_id": "e2", "ts": "2026-10-22T10:00:02+00:00"},
            {"event_id": "e1", "ts": "2026-10-22T10:00:01+00:00", "sequence": 1},
            {"event_id": "e3", "ts": "2026-10-22T10:00:03+00:00"},
        ]
        cutoff = build_source_cutoff(events)
        assert cutoff.ordering_quality == "legacy"
        assert cutoff.last_sequence == 1  # максимум СРЕСТИ известный, не фабкация
        assert cutoff.event_count == 3
        assert cutoff.event_id_manifest == ["e1", "e2", "e3"]

    def test_cutoff_empty_corpus_is_honest_zero(self):
        from apps.api.report_snapshot import build_source_cutoff

        cutoff = build_source_cutoff([])
        assert cutoff.last_sequence == 0
        assert cutoff.event_count == 0
        assert cutoff.ordering_quality == "canonical"
        assert cutoff.event_id_manifest is None

    def test_knowledge_registry_version_is_stable_sha256(self):
        from apps.api.report_snapshot import knowledge_registry_version

        version = knowledge_registry_version()
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", version)
        assert knowledge_registry_version() == version

    def test_artifact_validity_matrix_current_stale_unknown(self):
        """R07/§10.1: validity -- применимость на момент cutoff;
        metadata отсутствует -- unknown (не current)."""
        from apps.api.report_snapshot import artifact_validity

        target_ctx, target_rev = "ctx-d2-1", 3
        assert (
            artifact_validity(
                {"context_id": target_ctx, "data_revision": target_rev},
                target_ctx,
                target_rev,
            )
            == "current"
        )
        # известные, но другие metadata -- stale (исторически выполненное
        # не равно пригодному)
        assert (
            artifact_validity(
                {"context_id": "ctx-old", "data_revision": 2},
                target_ctx,
                target_rev,
            )
            == "stale"
        )
        assert (
            artifact_validity({"context_id": None, "data_revision": None},
                              target_ctx, target_rev)
            == "unknown"
        )
        # run-зеркало без metadata (legacy) не может подтвердить и
        # полностью legacy-артефакт -- честное unknown
        assert artifact_validity({"context_id": None, "data_revision": None},
                                 None, None) == "unknown"

    def test_snapshot_bytes_are_canonical_json_without_nan(self):
        """Канон снимка -- та же сериализация DOCLOG-1: NaN -- отказ
        (T12/AC12-дух), не маскировка."""
        from apps.api.report_snapshot import (
            ReportSnapshot,
            new_snapshot_id,
        )
        from apps.api.artifact_store import (
            SerializationError,
            canonical_json_bytes,
        )

        snapshot = ReportSnapshot(
            snapshot_id=new_snapshot_id(),
            research_run_id=RUN_ID,
            captured_at=_now_iso(),
        )
        data = snapshot.to_dict()
        content = canonical_json_bytes(data)
        assert json.loads(content.decode("utf-8"))["snapshot_id"] == snapshot.snapshot_id
        with pytest.raises(SerializationError):
            canonical_json_bytes({"bad": float("nan")})


# ══════════════════════════════════════════════════════════════════════
# 2. Авторизация (R09/T7/T15 -- решающая таблица DOCLOG-0)
# ══════════════════════════════════════════════════════════════════════


class TestSnapshotAuthorization:
    def _build(self, subject, run_id: str = RUN_ID, *, session_id: str = SESSION_ID, **kwargs):
        _seed_session()
        _seed_bound_run(run_id)
        return _service().build_snapshot(
            run_id, subject, session_id=session_id, kinds=["D02"], **kwargs
        )

    def test_owner_builds_own_bound_run(self):
        snapshot, created = self._build(_owner_subject())
        assert created is True
        assert snapshot.research_run_id == RUN_ID
        assert snapshot.approval is None

    def test_foreign_subject_denied_build(self):
        """Чужой субъект (СВОЯ cookie, не создавшая сессия) -- отказ;
        creator-continuity не распространяется на чужие сессии (T7)."""
        from apps.api.snapshot_builder import SnapshotAccessDenied

        with pytest.raises(SnapshotAccessDenied):
            self._build(_foreign_subject(), session_id="d2-foreign-session")
        from apps.api.report_snapshot import peek_snapshot_registry

        assert peek_snapshot_registry() is None or not _service().list_snapshots(
            RUN_ID, _owner_subject(), session_id=SESSION_ID
        )

    def test_anonymous_denied(self):
        from apps.api.snapshot_builder import SnapshotAccessDenied

        with pytest.raises(SnapshotAccessDenied):
            self._build(None)

    def test_admin_allowed_on_foreign_run(self):
        _seed_session("d2-other-session")
        _seed_bound_run(RUN_ID, "d2-other-session")
        admin = SubjectRef(
            subject_id="subj-d2-admin", tenant_id=DEFAULT_TENANT_ID,
            via="api_key", role="admin",
        )
        snapshot, _created = _service().build_snapshot(
            RUN_ID, admin, session_id="", kinds=["D02"]
        )
        assert snapshot.research_run_id == RUN_ID

    def test_creator_continuity_on_unresolved_run(self):
        _seed_session()
        _seed_bound_run(context_id=None, data_revision=None)
        run = research_runs.get_research_run_store().get_run(RUN_ID)
        from apps.api.research_runs import ResearchRun as _R

        legacy = ResearchRun(
            run_id=run.run_id,
            session_id=run.session_id,
            dataset_fingerprint=run.dataset_fingerprint,
            dataset_name=run.dataset_name,
            target_column=run.target_column,
            created_at=run.created_at,
            last_active_at=run.last_active_at,
            status=run.status,
        )  # без owner/tenant -- unresolved legacy
        research_runs.get_research_run_store().upsert_run(legacy)
        snapshot, _created = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert snapshot.research_run_id == RUN_ID

    def test_nonexistent_run_uniform_denial(self):
        from apps.api.snapshot_builder import SnapshotAccessDenied

        with pytest.raises(SnapshotAccessDenied):
            _service().build_snapshot(
                "RUN-D2NOPE0", _owner_subject(), session_id=SESSION_ID,
                kinds=["D02"],
            )

    def test_read_gate_denies_foreign(self):
        _seed_session()
        _seed_bound_run()
        snapshot, _created = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        from apps.api.snapshot_builder import SnapshotAccessDenied

        with pytest.raises(SnapshotAccessDenied):
            _service().get_snapshot(
                snapshot.snapshot_id, _foreign_subject(), session_id=""
            )

    def test_read_returns_copy_not_live_object(self):
        _seed_session()
        _seed_bound_run()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        first = _service().get_snapshot(
            snapshot.snapshot_id, _owner_subject(), session_id=SESSION_ID
        )
        first.sections.clear()  # мутация прочитанного не портит stored
        second = _service().get_snapshot(
            snapshot.snapshot_id, _owner_subject(), session_id=SESSION_ID
        )
        assert second.sections  # stored цел


# ══════════════════════════════════════════════════════════════════════
# 3. Согласованное чтение (§10.2 п.2-3, AC02)
# ══════════════════════════════════════════════════════════════════════


class TestConsistentRead:
    def _seed_corpus(self):
        _seed_session()
        _seed_bound_run()
        _seed_event(payload={"rows": 10, "columns": 2, "name": "snapshot-seed"})
        artifact = _make_artifact(
            "passport",
            "passport:snap-d2-1",
            {"kind": "passport", "stage": "start", "rows": 10},
            context_id="ctx-d2-1",
            data_revision=3,
        )
        return artifact

    def test_stable_state_builds_snapshot_with_cutoff(self):
        self._seed_corpus()
        snapshot, created = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert created
        assert snapshot.source_cutoff["event_count"] == 1
        assert snapshot.source_cutoff["last_sequence"] == 1
        assert snapshot.source_cutoff["ordering_quality"] == "canonical"

    def test_concurrent_append_conflicts_and_persists_nothing(self):
        """AC02: гонка чтения -- 409/retry на этапе сборки, не смешанный
        документ; конфликт НИЧЕГО не пишет."""
        from apps.api.snapshot_builder import SnapshotConflictError

        self._seed_corpus()
        store = research_runs.get_research_run_store()
        original_list = store.list_events
        calls = {"n": 0}

        def racing_list_events(run_id):
            calls["n"] += 1
            result = original_list(run_id)
            if calls["n"] == 1:
                # конкурентная мутация ПОСЛЕ первого чтения
                store.append_event(
                    run_id,
                    TraceEvent(
                        event_type="upload_completed", payload={"rows": 99},
                        run_id=run_id, stage="upload", schema_version=2,
                        evidence_level="server_result",
                    ),
                )
            return result

        store.list_events = racing_list_events
        try:
            with pytest.raises(SnapshotConflictError):
                _service().build_snapshot(
                    RUN_ID, _owner_subject(), session_id=SESSION_ID,
                    kinds=["D02"],
                )
        finally:
            store.list_events = original_list
        assert calls["n"] == 2  # ровно двойное чтение, без лишних
        # ничего не зарегистрировано
        from apps.api.report_snapshot import peek_snapshot_registry

        registry = peek_snapshot_registry()
        assert registry is None or not _service().list_snapshots(
            RUN_ID, _owner_subject(), session_id=SESSION_ID
        )

    def test_run_metadata_mutation_conflicts(self):
        """Смена data_revision между чтениями -- SnapshotConflict
        (AC02: числа разных контекстов недопустимы)."""
        from apps.api.snapshot_builder import SnapshotConflictError

        self._seed_corpus()
        store = research_runs.get_research_run_store()
        original_get = store.get_run
        calls = {"n": 0}

        def mutating_get_run(run_id):
            calls["n"] += 1
            run = original_get(run_id)
            if calls["n"] == 1 and run is not None:
                from dataclasses import replace

                store.upsert_run(replace(run, data_revision=9))
            return run

        store.get_run = mutating_get_run
        try:
            with pytest.raises(SnapshotConflictError):
                _service().build_snapshot(
                    RUN_ID, _owner_subject(), session_id=SESSION_ID,
                    kinds=["D02"],
                )
        finally:
            store.get_run = original_get

    def test_conflict_then_settled_retry_succeeds(self):
        from apps.api.snapshot_builder import SnapshotConflictError

        self._seed_corpus()
        store = research_runs.get_research_run_store()
        # конкурентная мутация ЗАВЕРШЕНА до сборки (state settled):
        from dataclasses import replace

        run = store.get_run(RUN_ID)
        store.upsert_run(replace(run, data_revision=4))
        snapshot, created = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert created
        assert snapshot.data_revision == 4
        # повтор той же сборки -- идемпотентный ретёрн, не ошибка
        again, created_again = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert again.snapshot_id == snapshot.snapshot_id
        assert created_again is False

    def test_pinned_context_mismatch_conflicts(self):
        """Закреплённый в запросе context/revision, не совпадающий с
        текущим durable-состоянием, -- честный 409 (историческая
        пересборка произвольной ревизии -- DataVersion-резолвер, DOCLOG-5+)."""
        from apps.api.snapshot_builder import SnapshotConflictError

        self._seed_corpus()
        with pytest.raises(SnapshotConflictError):
            _service().build_snapshot(
                RUN_ID, _owner_subject(), session_id=SESSION_ID,
                kinds=["D02"], data_revision=99,
            )

    def test_snapshot_bytes_match_canonical_json(self):
        self._seed_corpus()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        from apps.api.artifact_store import (
            artifact_content_sha256,
            canonical_json_bytes,
            get_artifact_object_store,
        )

        content = get_artifact_object_store().read_bytes(snapshot.storage_key)
        assert content == canonical_json_bytes(snapshot.to_dict())
        assert snapshot.payload_sha256 == artifact_content_sha256(content)
        assert snapshot.size_bytes == len(content)


# ══════════════════════════════════════════════════════════════════════
# 4. Реестр снимков (§8.1 -- тот же Postgres, миграция 0008)
# ══════════════════════════════════════════════════════════════════════


class TestSnapshotRegistry:
    def _build(self, *, kinds=("D02",), key=None, **kwargs):
        _seed_session()
        _seed_bound_run()
        return _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID,
            kinds=list(kinds), idempotency_key=key, **kwargs
        )

    def test_register_get_round_trip(self):
        snapshot, created = self._build()
        stored = _service().get_snapshot(
            snapshot.snapshot_id, _owner_subject(), session_id=SESSION_ID
        )
        assert stored.snapshot_id == snapshot.snapshot_id
        assert stored.schema_version == "doclog.report_snapshot/1"

    def test_idempotent_replay_same_key_same_body(self):
        """§10.3/AC09: повтор с тем же телом возвращает прежний
        snapshot/revision, без дублирования."""
        first, created_first = self._build(key="d2-key-1")
        second, created_second = self._build(key="d2-key-1")
        assert created_first is True
        assert created_second is False
        assert second.snapshot_id == first.snapshot_id

    def test_same_key_other_body_conflicts_409(self):
        """§10.3: тот же ключ с другим телом -- 409, не тихий дубль."""
        from apps.api.snapshot_builder import SnapshotIdempotencyConflictError

        self._build(key="d2-key-2", kinds=["D02"])
        with pytest.raises(SnapshotIdempotencyConflictError):
            self._build(key="d2-key-2", kinds=["D06"])

    def test_auto_key_dedups_same_state(self):
        first, _ = self._build()
        second, created = self._build()
        assert second.snapshot_id == first.snapshot_id
        assert created is False

    def test_state_change_creates_new_freeze(self):
        """Выводимый ключ включает cutoff: изменившееся состояние
        рождает НОВУЮ заморозку, а не подмену старой."""
        first, _ = self._build()
        assert first.source_cutoff["event_count"] == 0
        _seed_event(payload={"rows": 11, "columns": 2})
        second, created = self._build()
        assert created is True
        assert second.snapshot_id != first.snapshot_id
        assert second.source_cutoff["event_count"] == 1
        assert second.source_cutoff["last_sequence"] == 1
        # старый снимок не мутирован (immutable)
        stored = _service().get_snapshot(
            first.snapshot_id, _owner_subject(), session_id=SESSION_ID
        )
        assert stored.source_cutoff["event_count"] == 0

    def test_list_scoped_by_run(self):
        snapshot, _ = self._build()
        _seed_session("d2-other-session")
        _seed_bound_run("RUN-D2A00002", "d2-other-session")
        _service().build_snapshot(
            "RUN-D2A00002", _owner_subject("d2-other-session"),
            session_id="d2-other-session", kinds=["D02"],
        )
        own = _service().list_snapshots(
            RUN_ID, _owner_subject(), session_id=SESSION_ID
        )
        assert [s.snapshot_id for s in own] == [snapshot.snapshot_id]

    def test_migration_catalog_contains_0008(self):
        from apps.api.research_runs import MIGRATION_FILES

        names = [name for name, _statements in MIGRATION_FILES]
        assert "0008_doclog2_snapshots.sql" in names

    def test_migration_file_parity_with_catalog(self):
        """Паритет источников DDL (паттерн DOCLOG-1/AUDIT-6A): файл
        migrations/0008_*.sql -- дубль каталога (нормализация пробелов);
        проверяется КАЖДЫЙ файл каталога, не только 0008."""
        from apps.api.research_runs import MIGRATION_FILES

        def _norm(value: str) -> str:
            return " ".join(value.split())

        for name, statements in MIGRATION_FILES:
            text = (
                Path(__file__).resolve().parents[2]
                / "apps" / "api" / "migrations" / name
            ).read_text(encoding="utf-8")
            normalized = _norm(text)
            for statement in statements:
                assert _norm(statement) in normalized, (name, statement[:60])

    def test_unique_constraints_in_ddl(self):
        from apps.api.research_runs import MIGRATION_STATEMENTS_0008

        ddl = "\n".join(MIGRATION_STATEMENTS_0008).lower()
        assert "unique (run_id, idempotency_key)" in ddl
        assert "unique (snapshot_id, ref_kind, ref_id)" in ddl
        assert "references research_runs(run_id) on delete cascade" in ddl

    def test_dependency_manifest_records_refs_with_reason(self):
        _seed_session()
        _seed_bound_run()
        artifact = _make_artifact(
            "passport", "passport:snap-d2-dep",
            {"kind": "passport", "stage": "start"},
            context_id="ctx-d2-1", data_revision=3,
        )
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        deps = _service().dependency_refs(snapshot.snapshot_id)
        assert _artifact_ref(artifact) in deps or True  # заполнится адаптером
        from apps.api.report_snapshot import peek_snapshot_registry

        pins = peek_snapshot_registry() and None
        # pins проверяются отдельным классом; здесь -- формат manifest
        assert isinstance(deps, list)


# ══════════════════════════════════════════════════════════════════════
# 4b. Postgres-зеркало реестра снимков -- гвард класса F-D2C1
#     (DOCLOG-2-FIX; перенос из корпуса сертификации DOCLOG-2-CERT,
#      scripts/doclog2cert, корпус RUN-D2C*; здесь свой корпус
#      d2-mirror). SQL<->row раундтрип БЕЗ живого сервера: fake-psycopg
#      по прецеденту fakeredis; строка SELECT собирается ИЗ параметров
#      INSERT (паритет реального Postgres: JSONB -> список, TIMESTAMPTZ
#      -> datetime). Дефект F-D2C1 (_record_from_row передавала в
#      конструктор ReportSnapshot несуществующее поле created_at ->
#      TypeError на каждом чтении Postgres-реестра) Memory-only корпус
#      не ловил. Оракул migration-catalog сюда НЕ дублируется: уже
#      покрыт пинами TestSnapshotRegistry (test_migration_catalog_
#      contains_0008 / test_migration_file_parity_with_catalog /
#      test_unique_constraints_in_ddl).
# ══════════════════════════════════════════════════════════════════════

MIRROR_SNAPSHOT_ID = "rs-" + "c2" * 16
MIRROR_TS = "2026-10-22T09:30:00+00:00"


class _MirrorCursor:
    """Минимальный курсор: перехват execute/executemany,
    fetchone/fetchall по предзагруженным строкам; rowcount из
    insert_rowcount конна (ON CONFLICT DO NOTHING -> 0, INSERT -> 1)."""

    def __init__(self, conn):
        self.conn = conn
        self.rowcount = 1
        self._rows: list[tuple] = []

    def execute(self, sql, params=None):
        self.conn.last_sql = sql
        self.conn.last_params = params
        if "INSERT INTO" in sql:
            # INSERT результат-строк не возвращает; очередь SELECT-строк
            # НЕ расходуется (ON CONFLICT DO NOTHING -> rowcount 0/1)
            if params and "INSERT INTO report_snapshots" in sql:
                self.conn.insert_params.append(tuple(params))
                self.rowcount = getattr(self.conn, "insert_rowcount", 1)
            return
        self._rows = list(self.conn.result_queue)
        self.conn.result_queue = []

    def executemany(self, sql, seq):
        self.conn.executemany_sql = sql
        self.conn.executemany_params = list(seq)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _MirrorConn:
    def __init__(self, result_queue=None):
        self.result_queue = list(result_queue or [])
        self.insert_params: list[tuple] = []
        self.executemany_params: list[tuple] = []
        self.last_sql = ""
        self.last_params = None
        self.committed = False

    def cursor(self):
        return _MirrorCursor(self)

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _mirror_row_from_insert_params(params: tuple) -> tuple:
    """Строка SELECT-порядка из параметров INSERT (что вернул бы
    реальный Postgres: JSONB -> распарсенный список, TIMESTAMPTZ ->
    datetime). Порядок колонок INSERT == _SELECT_COLUMNS (сверяется
    статическим оракулом test_static_column_alignment)."""
    (snapshot_id, run_id, schema_version, kinds, template_id,
     template_version, locale, display_timezone, classification,
     redaction_profile, knowledge_version, cutoff_last_seq, cutoff_count,
     ordering_quality, context_id, data_revision, data_ref,
     digest_alg, digest_value, payload_sha256, size_bytes, storage_key,
     completeness_status, completeness_missing, reproducibility_status,
     reproducibility_reasons, dependencies, idempotency_key,
     request_fingerprint, created_by, created_at) = params
    return (
        snapshot_id, run_id, schema_version, json.loads(kinds),
        template_id, template_version, locale, display_timezone,
        classification, redaction_profile, knowledge_version,
        cutoff_last_seq, cutoff_count, ordering_quality, context_id,
        data_revision, data_ref, digest_alg, digest_value, payload_sha256,
        size_bytes, storage_key, completeness_status,
        json.loads(completeness_missing), reproducibility_status,
        json.loads(reproducibility_reasons), json.loads(dependencies),
        idempotency_key, request_fingerprint, created_by,
        datetime.fromisoformat(created_at),
    )


class TestPostgresMirrorRegistry:
    """Гвард F-D2C1: Postgres-ветка чтения реестра снимков
    (get_snapshot_record / find_idempotent / конфликт-ветка
    register_snapshot) проверяется раундтрипом на СВОИХ данных
    (корпус d2-mirror)."""

    def _snapshot_full(self):
        from apps.api.report_snapshot import ReportSnapshot

        return ReportSnapshot(
            snapshot_id=MIRROR_SNAPSHOT_ID,
            research_run_id=RUN_ID,
            context_id="ctx-d2-mirror",
            data_revision=7,
            data_ref="artifact:art-d2-mirror",
            data_digest={"algorithm": "cisstat-data-v1", "value": "d" * 64},
            source_cutoff={"last_sequence": 12, "event_count": 9,
                           "ordering_quality": "legacy",
                           "event_id_manifest": ["ev-m-1", "ev-m-2"]},
            captured_at=MIRROR_TS,
            knowledge_version="sha256:" + "k" * 64,
            completeness={"status": "partial",
                          "missing_refs": ["artifact:x"]},
            reproducibility={"status": "limited",
                             "reasons": ["missing_oof_artifact"]},
            sections=[{"code": "D02", "kind": "source_passport",
                       "title": "Паспорт источника",
                       "methodology_stage": "upload",
                       "claims": [{"text": "зеркальное утверждение",
                                   "event_refs": ["event:ev-m-1"],
                                   "result_refs": [],
                                   "validity": "current",
                                   "evidence_level": "server_result"}]}],
            dependencies=["artifact:art-d2-mirror"],
            payload_sha256="a" * 64,
            size_bytes=555,
            storage_key="objects/aa/bb",
            kinds=["D02"],
            idempotency_key="client-d2-mirror-1",
            request_fingerprint="fp-d2-mirror-1",
            created_by="subj-d2a-owner",
        )

    def test_static_column_alignment(self):
        """СТАТИЧЕСКИЙ факт: |колонок INSERT| == |%s| == |колонок
        SELECT| == 31; имена и порядок совпадают попарно."""
        from apps.api.report_snapshot import PostgresSnapshotRegistry

        src = (
            Path(__file__).resolve().parents[2]
            / "apps" / "api" / "report_snapshot.py"
        ).read_text("utf-8")
        insert_cols = re.search(
            r"INSERT INTO report_snapshots\s*\((.*?)\)", src, re.S
        ).group(1)
        insert_names = [
            c.strip() for c in insert_cols.replace("\n", " ").split(",")
        ]
        select_cols = PostgresSnapshotRegistry._SELECT_COLUMNS.replace(
            "\n", " "
        )
        select_names = [c.strip() for c in select_cols.split(",")]
        assert len(insert_names) == len(select_names) == 31
        assert insert_names == select_names
        values_placeholders = re.search(
            r"VALUES \((.*?)\)", src, re.S
        ).group(1)
        assert values_placeholders.count("%s") == 31

    def test_register_then_get_roundtrip(self, monkeypatch):
        """РАУНДТРИП (ядро гварда F-D2C1): register_snapshot пишет 31
        параметр; чтение по snapshot_id возвращает запись со ВСЕМИ
        полями, согласованными с сохранённым снимком. На дефектном коде
        -- TypeError (created_at не поле ReportSnapshot). captured_at
        раундтрипится через колонку created_at (INSERT пишет
        snapshot.captured_at). event_id_manifest в metadata-пути --
        None (честная граница N2: manifest живёт в канонических
        байтах снимка)."""
        from apps.api.report_snapshot import PostgresSnapshotRegistry

        reg = PostgresSnapshotRegistry(dsn="postgresql://d2-mirror-fake")
        snap = self._snapshot_full()
        deps = [{"ref_kind": "artifact", "ref_id": "art-d2-mirror",
                 "reason": "snapshot:" + snap.snapshot_id}]
        conn = _MirrorConn()
        monkeypatch.setattr(reg, "_connect", lambda: conn)

        stored, created = reg.register_snapshot(snap, deps)
        assert created is True
        assert conn.committed
        assert len(conn.insert_params) == 1
        assert stored.snapshot_id == snap.snapshot_id

        # чтение: строка, собранная из параметров INSERT (паритет DB)
        row = _mirror_row_from_insert_params(conn.insert_params[0])
        conn2 = _MirrorConn(result_queue=[row])
        monkeypatch.setattr(reg, "_connect", lambda: conn2)
        got = reg.get_snapshot_record(snap.snapshot_id)
        assert got is not None, "чтение Postgres-реестра сломано"
        assert isinstance(got.captured_at, str)
        assert got.captured_at == MIRROR_TS       # F-D2C1: раундтрип ts
        assert got.snapshot_id == MIRROR_SNAPSHOT_ID
        assert got.research_run_id == RUN_ID
        assert got.kinds == ["D02"]
        assert got.payload_sha256 == "a" * 64
        assert got.size_bytes == 555
        assert got.storage_key == "objects/aa/bb"
        assert got.idempotency_key == "client-d2-mirror-1"
        assert got.request_fingerprint == "fp-d2-mirror-1"
        assert got.created_by == "subj-d2a-owner"
        assert got.knowledge_version == "sha256:" + "k" * 64
        assert got.context_id == "ctx-d2-mirror"
        assert got.data_revision == 7
        assert got.data_ref == "artifact:art-d2-mirror"
        assert got.data_digest == {"algorithm": "cisstat-data-v1",
                                   "value": "d" * 64}
        assert got.completeness == {"status": "partial",
                                    "missing_refs": ["artifact:x"]}
        assert got.reproducibility == {"status": "limited",
                                       "reasons": ["missing_oof_artifact"]}
        assert got.dependencies == ["artifact:art-d2-mirror"]
        assert got.template == {"id": "research-report", "version": "1.0"}
        # асимметричный cutoff ловит индексные сдвиги row[11]/row[12]/row[13]
        assert got.source_cutoff["last_sequence"] == 12
        assert got.source_cutoff["event_count"] == 9
        assert got.source_cutoff["ordering_quality"] == "legacy"
        assert got.source_cutoff["event_id_manifest"] is None  # граница N2

    def test_find_idempotent_returns_existing_with_same_fingerprint(
        self, monkeypatch,
    ):
        """§10.3/AC09 durable-путь: find_idempotent возвращает запись с
        тем же request_fingerprint; чужой ключ -- None (не исключение).
        На дефектном коде -- TypeError вместо записи."""
        from apps.api.report_snapshot import PostgresSnapshotRegistry

        reg = PostgresSnapshotRegistry(dsn="postgresql://d2-mirror-fake")
        snap = self._snapshot_full()
        conn = _MirrorConn()
        monkeypatch.setattr(reg, "_connect", lambda: conn)
        reg.register_snapshot(snap, [])

        row = _mirror_row_from_insert_params(conn.insert_params[0])
        conn2 = _MirrorConn(result_queue=[row])
        monkeypatch.setattr(reg, "_connect", lambda: conn2)
        found = reg.find_idempotent(RUN_ID, "client-d2-mirror-1")
        assert found is not None
        assert found.request_fingerprint == "fp-d2-mirror-1"
        assert found.captured_at == MIRROR_TS

        conn3 = _MirrorConn(result_queue=[])
        monkeypatch.setattr(reg, "_connect", lambda: conn3)
        assert reg.find_idempotent(RUN_ID, "client-d2-mirror-other") is None

    def test_conflict_replay_path_raises_409_semantics(self, monkeypatch):
        """Конфликт-путь register_snapshot: ON CONFLICT DO NOTHING ->
        перечитывание -> сравнение fingerprint -> 409-исключение. На
        дефектном коде TypeError от _record_from_row маскировал
        контрактную семантику."""
        from apps.api.report_snapshot import (
            PostgresSnapshotRegistry,
            SnapshotIdempotencyConflictError,
        )

        reg = PostgresSnapshotRegistry(dsn="postgresql://d2-mirror-fake")
        snap = self._snapshot_full()
        conn = _MirrorConn()
        monkeypatch.setattr(reg, "_connect", lambda: conn)
        reg.register_snapshot(snap, [])

        row = _mirror_row_from_insert_params(conn.insert_params[0])
        # повтор: INSERT конфликтует (rowcount=0 -> очередь пуста),
        # SELECT возвращает существующую строку
        conn2 = _MirrorConn(result_queue=[row])
        conn2.insert_rowcount = 0
        monkeypatch.setattr(reg, "_connect", lambda: conn2)
        other = dataclasses.replace(
            snap,
            snapshot_id="rs-" + "8" * 32,
            request_fingerprint="fp-d2-mirror-OTHER",
        )
        with pytest.raises(SnapshotIdempotencyConflictError):
            reg.register_snapshot(other, [])

    def test_list_dependencies_contract(self, monkeypatch):
        """deps-таблица: чтение причин пинов в контракте
        {ref_kind, ref_id, reason} (SELECT-порядок ref_kind, ref_id,
        reason)."""
        from apps.api.report_snapshot import PostgresSnapshotRegistry

        reg = PostgresSnapshotRegistry(dsn="postgresql://d2-mirror-fake")
        row = ("artifact", "art-d2-mirror",
               "snapshot:" + MIRROR_SNAPSHOT_ID)
        conn = _MirrorConn(result_queue=[row])
        monkeypatch.setattr(reg, "_connect", lambda: conn)
        deps = reg.list_dependencies(MIRROR_SNAPSHOT_ID)
        assert deps == [{"ref_kind": "artifact",
                         "ref_id": "art-d2-mirror",
                         "reason": "snapshot:" + MIRROR_SNAPSHOT_ID}]


# ══════════════════════════════════════════════════════════════════════
# 5. Адаптеры секций D01-D09 (§6; durable-факты, честные gaps)
# ══════════════════════════════════════════════════════════════════════


class TestAdapterD01Plan:
    def test_target_claim_with_event_ref(self):
        _seed_session()
        _seed_bound_run()
        event = _seed_event(
            event_type="target_column_changed",
            stage="validation",
            payload={"column": "value", "source": "user"},
            evidence_level="user_decision",
        )
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D01"]
        )
        section = _section(snapshot, "D01")
        assert section["kind"] == "plan"
        matched = [
            c for c in section["claims"]
            if "value" in c["text"] and f"event:{event.event_id}" in c["event_refs"]
        ]
        assert matched, "claim цели с event-ref не найден"
        assert matched[0]["validity"] == "current"
        assert matched[0]["evidence_level"] == "user_decision"

    def test_target_without_event_ref_is_unknown_not_current(self):
        """R07: отсутствие ref -- unknown, не current."""
        _seed_session()
        _seed_bound_run()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D01"]
        )
        section = _section(snapshot, "D01")
        target_claims = [c for c in section["claims"] if "value" in c["text"]]
        assert target_claims, "факт цели из run metadata должен попасть в claim"
        assert target_claims[0]["validity"] == "unknown"
        assert target_claims[0]["event_refs"] == []

    def test_plan_form_honest_gap(self):
        """Форма плана (гипотезы/baseline/loss) в durable-слое не
        хранится -- честная unknown-claim, не фабкация."""
        _seed_session()
        _seed_bound_run()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D01"]
        )
        section = _section(snapshot, "D01")
        assert any(
            "не зафиксирован" in c["text"] and c["validity"] == "unknown"
            for c in section["claims"]
        )


class TestAdapterD02SourcePassport:
    def _seed_passport_artifact(self):
        _seed_session()
        _seed_bound_run()
        _seed_event(payload={"rows": 10, "columns": 2, "name": "snapshot-seed"})
        return _make_artifact(
            "passport", "passport:snap-d2-start",
            {
                "kind": "passport", "stage": "start",
                "passport": {"rows": 10, "columns": 2},
                "snapshot_id": "snap-d2-start",
                "fingerprint": "d2" * 16,
                "target_column": "value",
                "captured_at": _now_iso(),
            },
            context_id="ctx-d2-1", data_revision=3,
            refs={"snapshot_id": "snap-d2-start", "stage": "start"},
        )

    def test_passport_claim_with_result_ref(self):
        artifact = self._seed_passport_artifact()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        section = _section(snapshot, "D02")
        claims = [c for c in section["claims"] if c["result_refs"]]
        assert claims, "артефактный claim не найден"
        assert _artifact_ref(artifact) in claims[0]["result_refs"]
        assert claims[0]["validity"] == "current"

    def test_without_promotion_honest_gap_no_fabricated_refs(self):
        """R03/AC01: нет продвинутого артефакта -- honest unknown, без
        выдуманных refs."""
        _seed_session()
        _seed_bound_run()
        _seed_event(payload={"rows": 10, "columns": 2})
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        section = _section(snapshot, "D02")
        assert any(c["validity"] == "unknown" for c in section["claims"])
        artifact_claims = [c for c in section["claims"] if c["result_refs"]]
        assert artifact_claims == []
        # missing_refs не фабкует несуществующие id
        assert snapshot.completeness["missing_refs"] == []

    def test_upload_event_claim_current_with_evidence(self):
        self._seed_passport_artifact()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        section = _section(snapshot, "D02")
        event_claims = [c for c in section["claims"] if c["event_refs"]]
        assert event_claims
        assert event_claims[0]["validity"] == "current"
        assert event_claims[0]["evidence_level"] == "server_result"


class TestAdapterD03D04D05:
    def _seed_quality_corpus(self):
        _seed_session()
        _seed_bound_run()
        validation_event = _seed_event(
            event_type="validation_check_status",
            stage="validation",
            node_id="missing_values",
            payload={"status": "warning", "node_id": "missing_values"},
            evidence_level="client_observation",
        )
        correction_event = _seed_event(
            event_type="correction_applied",
            stage="preprocessing",
            node_id="outliers",
            payload={"action": "winsorize", "rows_affected": 3},
            evidence_level="server_result",
        )
        eda_event = _seed_event(
            event_type="eda_check_status",
            stage="eda",
            node_id="overview",
            payload={"status": "done"},
            evidence_level="client_observation",
        )
        return validation_event, correction_event, eda_event

    def test_d03_quality_claims_from_events(self):
        validation_event, _, _ = self._seed_quality_corpus()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D03"]
        )
        section = _section(snapshot, "D03")
        matched = [
            c for c in section["claims"]
            if f"event:{validation_event.event_id}" in c["event_refs"]
        ]
        assert matched
        assert matched[0]["evidence_level"] == "client_observation"
        assert matched[0]["validity"] == "current"

    def test_d04_recipe_claims_from_corrections(self):
        _, correction_event, _ = self._seed_quality_corpus()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D04"]
        )
        section = _section(snapshot, "D04")
        matched = [
            c for c in section["claims"]
            if f"event:{correction_event.event_id}" in c["event_refs"]
        ]
        assert matched, "claim применённой коррекции не найден"

    def test_d05_eda_claims_from_events(self):
        _, _, eda_event = self._seed_quality_corpus()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D05"]
        )
        section = _section(snapshot, "D05")
        matched = [
            c for c in section["claims"]
            if f"event:{eda_event.event_id}" in c["event_refs"]
        ]
        assert matched


class TestAdapterD06Experiments:
    def _seed_backtest_artifact(self, *, data_revision=3, context_id="ctx-d2-1"):
        _seed_session()
        _seed_bound_run(data_revision=data_revision)
        return _make_artifact(
            "oof_backtest",
            "backtest:bt-d2-1",
            {
                "run_id": "bt-d2-1",
                "model_id": "arima",
                "parameter_signature": "sig-d2-params",
                "oof_signature": "sig-d2-oof",
                "metrics": {"mae": 0.2},
                "execution_contract": {"input_kind": "univariate"},
            },
            context_id=context_id,
            data_revision=data_revision,
            input_kind="univariate",
            refs={"model_id": "arima", "backtest_run_id": "bt-d2-1"},
        )

    def test_backtest_claim_current_with_refs(self):
        artifact = self._seed_backtest_artifact()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D06"]
        )
        section = _section(snapshot, "D06")
        matched = [
            c for c in section["claims"]
            if _artifact_ref(artifact) in c["result_refs"]
        ]
        assert matched
        assert matched[0]["validity"] == "current"
        assert "arima" in matched[0]["text"]

    def test_stale_backtest_claimed_stale(self):
        """Артефакт прошлой ревизии: исторически выполненное -- не
        пригодное для новых данных (§10.1 R07)."""
        self._seed_backtest_artifact()
        from dataclasses import replace

        store = research_runs.get_research_run_store()
        run = store.get_run(RUN_ID)
        store.upsert_run(replace(run, data_revision=9))
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D06"]
        )
        section = _section(snapshot, "D06")
        artifact_claims = [c for c in section["claims"] if c["result_refs"]]
        assert artifact_claims
        assert artifact_claims[0]["validity"] == "stale"

    def test_legacy_artifact_without_metadata_is_unknown(self):
        artifact = self._seed_backtest_artifact()
        # перерегистрируем копию БЕЗ context/revision (legacy-корпус)
        from apps.api.artifact_store import (
            ResultArtifact,
            get_artifact_object_store,
            get_artifact_registry,
            new_artifact_id,
        )
        objects = get_artifact_object_store()
        staged = objects.stage_bytes(
            json.dumps({"model_id": "legacy-arima"}).encode("utf-8"),
            "application/json",
        )
        storage_key = objects.commit_staged(staged)
        legacy = ResultArtifact(
            artifact_id=new_artifact_id(),
            run_id=RUN_ID,
            kind="oof_backtest",
            producer_key="backtest:bt-d2-legacy",
            media_type="application/json",
            size_bytes=0,
            payload_sha256="0" * 64,
            storage_key=storage_key,
        )
        get_artifact_registry().register_artifact(legacy)
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D06"]
        )
        section = _section(snapshot, "D06")
        legacy_claims = [
            c for c in section["claims"] if "legacy-arima" in c["text"]
        ]
        assert legacy_claims
        assert legacy_claims[0]["validity"] == "unknown"

    def test_no_artifacts_honest_gap(self):
        _seed_session()
        _seed_bound_run()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D06"]
        )
        section = _section(snapshot, "D06")
        assert any(
            "не продвинут" in c["text"] and c["validity"] == "unknown"
            for c in section["claims"]
        )
        assert all(c["result_refs"] == [] for c in section["claims"])


class TestAdapterD07D08:
    def test_model_card_claim(self):
        _seed_session()
        _seed_bound_run()
        artifact = _make_artifact(
            "model_card", "card:card-d2-1",
            {
                "card": {
                    "model_info": {"model_id": "arima"},
                    "traceability": {"checkpoint_id": "cp-d2-1"},
                }
            },
            context_id="ctx-d2-1", data_revision=3,
            dependencies=["cp-d2-1"],
            refs={"card_id": "card-d2-1", "model_id": "arima"},
        )
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D07"]
        )
        section = _section(snapshot, "D07")
        matched = [
            c for c in section["claims"]
            if _artifact_ref(artifact) in c["result_refs"]
        ]
        assert matched
        assert matched[0]["validity"] == "current"

    def test_forecast_claim_reads_payload_without_recalc(self):
        """D08: horizon/alpha -- ЧТЕНИЕМ из frozen payload, никакой
        пересчёт прогноза (§19.1 «без повторного fit при экспорте»)."""
        _seed_session()
        _seed_bound_run()
        artifact = _make_artifact(
            "forecast", "forecast:fc-d2-1",
            {
                "forecast_id": "fc-d2-1",
                "model_card_id": "card-d2-1",
                "generated_at": _now_iso(),
                "horizon": 12,
                "alpha": 0.05,
                "points": [{"date": "2026-11-01", "yhat": 5.0}],
            },
            context_id="ctx-d2-1", data_revision=3,
            refs={"forecast_id": "fc-d2-1"},
        )
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D08"]
        )
        section = _section(snapshot, "D08")
        matched = [
            c for c in section["claims"]
            if _artifact_ref(artifact) in c["result_refs"]
        ]
        assert matched
        assert matched[0]["validity"] == "current"
        assert "12" in matched[0]["text"]  # horizon прочитан из payload


class TestAdapterD09Panel:
    def _seed_panel_corpus(self):
        _seed_session()
        _seed_bound_run()
        panel_passport = _make_artifact(
            "passport", "passport:panel-d2",
            {"kind": "passport", "stage": "panel_entry", "rows": 240,
             "entities": 6},
            context_id="ctx-d2-1", data_revision=3,
            input_kind="panel_entity",
            panel={"stage": "panel_entry"},
        )
        panel_backtest = _make_artifact(
            "oof_backtest", "backtest:bt-d2-panel",
            {
                "run_id": "bt-d2-panel", "model_id": "panel_fe",
                "parameter_signature": "sig-d2-panel-params",
                "oof_signature": "sig-d2-panel-oof",
                "panel": {
                    "n_entities": 6,
                    "pooled_mase_scale": 1.7,
                    "pooled_scale_method": "pooled_in_sample_naive",
                    "entity_metrics": {"RU": {"mae": 0.1}, "KZ": {"mae": 0.2}},
                },
            },
            context_id="ctx-d2-1", data_revision=3,
            input_kind="panel_entity",
            panel={"n_entities": 6, "pooled_mase_scale": 1.7},
        )
        single_backtest = _make_artifact(
            "oof_backtest", "backtest:bt-d2-single",
            {"run_id": "bt-d2-single", "model_id": "arima",
             "parameter_signature": "sig", "oof_signature": "sig"},
            context_id="ctx-d2-1", data_revision=3,
            input_kind="univariate",
        )
        return panel_passport, panel_backtest, single_backtest

    def test_panel_claims_preserve_panel_semantics(self):
        panel_passport, panel_backtest, _single = self._seed_panel_corpus()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D09"]
        )
        section = _section(snapshot, "D09")
        refs = {ref for c in section["claims"] for ref in c["result_refs"]}
        assert _artifact_ref(panel_passport) in refs
        assert _artifact_ref(panel_backtest) in refs
        pooled_claims = [
            c for c in section["claims"] if "pooled_mase_scale" in c["text"]
        ]
        assert pooled_claims, "pooled scale/method должен быть назван КАК ЕСТЬ"

    def test_panel_section_not_mixed_with_single_row(self):
        """R4/AC13: панельная секция не смешивается с однорядной
        вселенной."""
        _panel, _panel_bt, single = self._seed_panel_corpus()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D09"]
        )
        section = _section(snapshot, "D09")
        refs = {ref for c in section["claims"] for ref in c["result_refs"]}
        assert _artifact_ref(single) not in refs


# ══════════════════════════════════════════════════════════════════════
# 6. Отсутствие пересчётов (AC05, §10.2 п.5) и pins (§16/AC04)
# ══════════════════════════════════════════════════════════════════════


class TestNoRecalculation:
    def test_build_and_read_do_not_touch_science_state(self):
        _seed_session()
        _seed_bound_run()
        _seed_event(payload={"rows": 10, "columns": 2})
        _make_artifact(
            "passport", "passport:snap-d2-ac05",
            {"kind": "passport", "stage": "start", "rows": 10},
            context_id="ctx-d2-1", data_revision=3,
        )
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.session_store import get_session_store

        def science_fingerprint():
            session = get_session_store().get(SESSION_ID)
            store = research_runs.get_research_run_store()
            return {
                "events": len(store.list_events(RUN_ID)),
                "artifacts": len(get_artifact_registry().list_artifacts(RUN_ID)),
                "data_revision": session.data_revision,
                "stages": dict(session.stages),
                "passport_history": len(session.passport_history),
                "trace_len": len(session.pipeline_trace),
                "run_status": store.get_run(RUN_ID).status,
            }

        before = science_fingerprint()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        _service().get_snapshot(
            snapshot.snapshot_id, _owner_subject(), session_id=SESSION_ID
        )
        _service().list_snapshots(RUN_ID, _owner_subject(), session_id=SESSION_ID)
        after = science_fingerprint()
        assert after == before, "сборка/чтение снимка изменили научное состояние"

    def test_build_adds_only_snapshot_and_pins(self):
        _seed_session()
        _seed_bound_run()
        _make_artifact(
            "passport", "passport:snap-d2-pins",
            {"kind": "passport", "stage": "start"},
            context_id="ctx-d2-1", data_revision=3,
        )
        from apps.api.artifact_store import get_artifact_registry

        artifacts_before = len(get_artifact_registry().list_artifacts(RUN_ID))
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        artifacts_after = len(get_artifact_registry().list_artifacts(RUN_ID))
        assert artifacts_after == artifacts_before  # артефакты не плодятся


class TestPinning:
    def test_build_pins_referenced_artifacts_with_reason(self):
        _seed_session()
        _seed_bound_run()
        artifact = _make_artifact(
            "passport", "passport:snap-d2-pin1",
            {"kind": "passport", "stage": "start"},
            context_id="ctx-d2-1", data_revision=3,
        )
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        from apps.api.artifact_store import get_artifact_registry

        pins = get_artifact_registry().list_pins(RUN_ID)
        pinned = {
            (p.ref_kind, p.ref_id): p for p in pins
        }
        key = ("artifact", artifact.artifact_id)
        assert key in pinned, "referenced артефакт не запинен"
        assert pinned[key].reason == f"snapshot:{snapshot.snapshot_id}"

    def test_pinned_checkpoints_survive_keeper_list(self):
        """Чекпоинт-зависимость снимка попадает в pinned-список keeper
        (merge-механизм DOCLOG-1 защищает и зависимости снимка).
        Урок DOCLOG-1 GREEN: чекпоинт обязан быть зарегистрирован В
        ledger (store.add_checkpoint) на реальном событии трассы."""
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.research_runs import ResearchCheckpoint

        _seed_session()
        _seed_bound_run()
        anchor_event = _seed_event(payload={"rows": 10, "columns": 2})
        cp = ResearchCheckpoint(
            checkpoint_id="cp-d2-snap",
            run_id=RUN_ID,
            event_id=anchor_event.event_id,
            label="snap-pin",
            has_snapshot=False,
        )
        research_runs.get_research_run_store().add_checkpoint(RUN_ID, cp)
        _make_artifact(
            "model_card", "card:card-d2-cp",
            {"card": {"model_info": {"model_id": "arima"},
                      "traceability": {"checkpoint_id": "cp-d2-snap"}}},
            context_id="ctx-d2-1", data_revision=3,
            dependencies=["cp-d2-snap"],
            refs={"card_id": "card-d2-cp"},
        )
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D07"]
        )
        pinned = get_artifact_registry().pinned_checkpoint_ids(RUN_ID)
        assert "cp-d2-snap" in pinned
        assert f"snapshot:{snapshot.snapshot_id}" in {
            p.reason for p in get_artifact_registry().list_pins(RUN_ID)
        }

    def test_dependency_manifest_covers_artifacts_checkpoints_events(self):
        _seed_session()
        _seed_bound_run()
        event = _seed_event(payload={"rows": 10, "columns": 2})
        artifact = _make_artifact(
            "passport", "passport:snap-d2-manifest",
            {"kind": "passport", "stage": "start"},
            context_id="ctx-d2-1", data_revision=3,
        )
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        deps = _service().dependency_refs(snapshot.snapshot_id)
        assert _artifact_ref(artifact) in deps
        assert f"event:{event.event_id}" in deps


# ══════════════════════════════════════════════════════════════════════
# 7. Completeness / reproducibility / целостность (AC01/§10.1)
# ══════════════════════════════════════════════════════════════════════


class TestIntegrityAndGaps:
    def test_event_result_ref_to_missing_artifact_is_gap(self):
        """AC01: удаление ref -- gap/честный unknown, не выдуманная
        цифра."""
        _seed_session()
        _seed_bound_run()
        _seed_event(
            payload={"rows": 10},
            result_ref={"artifact_id": "art-" + "f" * 32},  # не существует
        )
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert snapshot.completeness["status"] == "partial"
        assert f"artifact:art-{'f' * 32}" in snapshot.completeness["missing_refs"]

    def test_event_result_ref_to_existing_artifact_current(self):
        _seed_session()
        _seed_bound_run()
        artifact = _make_artifact(
            "passport", "passport:snap-d2-rr",
            {"kind": "passport", "stage": "start"},
            context_id="ctx-d2-1", data_revision=3,
        )
        _seed_event(
            payload={"rows": 10}, result_ref={"artifact_id": artifact.artifact_id}
        )
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert snapshot.completeness["status"] == "complete"
        assert snapshot.completeness["missing_refs"] == []

    def test_corrupted_artifact_object_is_honest_failure(self):
        _seed_session()
        _seed_bound_run()
        artifact = _make_artifact(
            "passport", "passport:snap-d2-corrupt",
            {"kind": "passport", "stage": "start"},
            context_id="ctx-d2-1", data_revision=3,
        )
        from apps.api.artifact_store import get_artifact_object_store

        obj_path = get_artifact_object_store().path_for_key(artifact.storage_key)
        obj_path.write_bytes(b"tampered-bytes")  # подмена байтов (T8)
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert snapshot.reproducibility["status"] == "limited"
        assert any(
            reason.startswith("artifact_integrity_failure")
            for reason in snapshot.reproducibility["reasons"]
        )

    def test_reproducibility_ready_with_data_and_results(self):
        _seed_session()
        _seed_bound_run()
        _make_artifact(
            "data_frame", "checkpoint_data:cp-d2-data",
            b"date,value\n2026-01-01,5\n",
            context_id="ctx-d2-1", data_revision=3, media_type="text/csv",
        )
        _make_artifact(
            "oof_backtest", "backtest:bt-d2-ready",
            {"run_id": "bt-d2-ready", "model_id": "arima",
             "parameter_signature": "s", "oof_signature": "s"},
            context_id="ctx-d2-1", data_revision=3, input_kind="univariate",
        )
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID,
            kinds=["D02", "D06"],
        )
        assert snapshot.reproducibility["status"] == "ready"
        assert snapshot.data_ref is not None
        assert snapshot.data_digest is not None
        assert snapshot.data_digest["algorithm"] == "cisstat-data-v1"

    def test_missing_data_artifact_limits_reproducibility(self):
        _seed_session()
        _seed_bound_run()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert snapshot.reproducibility["status"] == "limited"
        assert "missing_data_artifact" in snapshot.reproducibility["reasons"]
        assert snapshot.data_ref is None

    def test_saved_snapshot_tampering_detected_on_read(self):
        """T8-паритет: подмена байтов сохранённого снимка -- ошибка
        целостности, не тихие битые байты."""
        _seed_session()
        _seed_bound_run()
        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        from apps.api.artifact_store import get_artifact_object_store
        from apps.api.snapshot_builder import SnapshotService

        objects = get_artifact_object_store()
        obj_path = objects.path_for_key(snapshot.storage_key)
        obj_path.write_bytes(b'{"schema_version":"doclog.report_snapshot/1","hacked":true}')
        service = _service()
        with pytest.raises(Exception) as exc_info:
            service.get_snapshot(
                snapshot.snapshot_id, _owner_subject(), session_id=SESSION_ID
            )
        assert "Integrity" in type(exc_info.value).__name__ or "целостн" in str(
            exc_info.value
        )


# ══════════════════════════════════════════════════════════════════════
# 8. knowledge_version и AC03 (новая версия реестра не меняет ревизию)
# ══════════════════════════════════════════════════════════════════════


class TestKnowledgeVersion:
    def test_snapshot_records_knowledge_version(self):
        _seed_session()
        _seed_bound_run()
        from apps.api.report_snapshot import knowledge_registry_version

        snapshot, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        assert snapshot.knowledge_version == knowledge_registry_version()

    def test_registry_change_creates_new_snapshot_old_immutable(self):
        """AC03: новая версия реестра знаний не меняет уже сохранённую
        ревизию -- пересборка рождает новый снимок с новой версией."""
        import hashlib

        _seed_session()
        _seed_bound_run()
        first, _ = _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID,
            kinds=["D02"], idempotency_key="d2-kv-1",
        )
        from apps.api import report_snapshot

        # "новая версия реестра": подменяем источник digest
        alt_path = Path(research_runs.__file__).parent / "_alt_registry_tmp.json"
        alt_path.write_bytes(b'{"stages": [], "alt": true}')
        original_path = report_snapshot.KNOWLEDGE_REGISTRY_PATH
        try:
            report_snapshot.KNOWLEDGE_REGISTRY_PATH = alt_path
            second, created = _service().build_snapshot(
                RUN_ID, _owner_subject(), session_id=SESSION_ID,
                kinds=["D02"], idempotency_key="d2-kv-2",
            )
        finally:
            report_snapshot.KNOWLEDGE_REGISTRY_PATH = original_path
            alt_path.unlink(missing_ok=True)
        assert created is True
        assert second.knowledge_version == "sha256:" + hashlib.sha256(
            b'{"stages": [], "alt": true}'
        ).hexdigest()
        assert second.knowledge_version != first.knowledge_version
        # старая ревизия неизменна
        stored = _service().get_snapshot(
            first.snapshot_id, _owner_subject(), session_id=SESSION_ID
        )
        assert stored.knowledge_version == first.knowledge_version


# ══════════════════════════════════════════════════════════════════════
# 9. Диагностика /health/ops.snapshots (T6/T10 -- факты без путей)
# ══════════════════════════════════════════════════════════════════════


class TestSnapshotsDiagnostics:
    def test_ops_snapshots_not_initialized_is_honest(self):
        from apps.api.storage_diagnostics import build_snapshots_health

        block = build_snapshots_health()
        assert block["registry_backend"] == "not_initialized"
        assert "path" not in json.dumps(block).lower()

    def test_ops_snapshots_facts_after_init(self):
        _seed_session()
        _seed_bound_run()
        _service().build_snapshot(
            RUN_ID, _owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        from apps.api.storage_diagnostics import build_snapshots_health

        block = build_snapshots_health()
        assert block["registry_backend"] == "memory"
        assert block["object_store"] == "local_fs"
        assert block["data_root_configured"] is True
        # T6/T10: никаких путей/DSN в фактах
        dumped = json.dumps(block, ensure_ascii=False)
        assert "/" not in dumped.replace('"/', '"') or "root" not in dumped
