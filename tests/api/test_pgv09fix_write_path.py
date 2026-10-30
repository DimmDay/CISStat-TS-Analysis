"""PGV-09-FIX: исправления находок независимой сертификации PGV-09
(docs/cert_pgv09_2026-10-30.md):

  F-P9C1 (CRITICAL) -- Postgres write-path печатных jobs/renditions
      нарушал контуры 0010/0017: snapshot_id='' вместо NULL (FK
      document_jobs/document_renditions.snapshot_id ->
      report_snapshots), revision_id=dprint-... против FK
      document_renditions.revision_id -> document_revisions (NOT NULL),
      латентный перехват чужой строки rendition через общий
      UNIQUE('' , format, profile) + ON CONFLICT DO UPDATE.

  N-P9C2 (MINOR) -- непериализуемый payload (NaN вне канонического
      freeze) давал transient (render_failed/renderer_unavailable,
      requeue-цикл) вместо честного terminal invalid_payload.

Оракулы на СВОИХ данных (корпус дизъюнктен: RUN-P9FIXxxxx, p9fix-*,
djob-p9fix-*, dprint-p9fix-*); изоляция каждого теста -- паттерн
test_pgv09_jobs_renderer_integration.py. Классы:

  A -- мини-модель ограничений 0010+0016+0017+0018 (SQLite): РЕАЛЬНЫЕ
       формы INSERT Postgres-адаптера (перехват через fake-соединение,
       replay %s->?) проходят FK/UNIQUE; печатные ревизии сосуществуют
       (перехват строки исключён); snapshot-путь сохраняет прежнюю
       идемпотентность. Усиление proof-оракула O11 сертификатора:
       replay реального SQL адаптера, а не ручных форм.
  B -- чтение durable-строк: NULL -> '' в-process (не строка "None").
  C -- сервис (Memory): печатная rendition несёт revision_id=''
       (связь через print_revision_id, FK 0017); in-process ''-маркер
       «нет значения» сохранён (паритет авторского корпуса).
  D -- N-P9C2: непериализуемый payload -- RendererPayloadInvalid
       (terminal invalid_payload) ДО сетевого вызова; worker --
       честный terminal без requeue, без rendition.
  E -- миграция 0018: revision_id DROP NOT NULL (FK сохранён);
       файл/каталог/паритет/аддитивность (паттерн PROGR-5.1).

Граница: живой Postgres в среде отсутствует (унаследовано от CERT);
write-путь страхуется мини-моделью точных форм адаптера; complete
runbook живого прогона -- docs/pgv09_jobs_renderer_integration.md §FIX.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.api import research_runs
from apps.api.document_jobs import (
    DocumentJobRecord,
    DocumentRenditionRecord,
    PostgresDocumentRegistry,
)
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
from apps.api.research_runs import ResearchRun

# ── Изоляция КАЖДОГО теста (паттерн авторского корпуса PGV-09) ────────


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    for name in (
        "DATABASE_URL",
        "CISSTAT_RUNS_BACKEND",
        "CISSTAT_IDENTITY_MODE",
        "CISSTAT_API_KEYS",
        "CISSTAT_IDENTITY_SALT",
        "CISSTAT_ARTIFACTS_BACKEND",
        "CISSTAT_SNAPSHOTS_BACKEND",
        "CISSTAT_DOCUMENTS_BACKEND",
        "CISSTAT_DOCUMENT_RENDER_WORKER_ENABLED",
        "CISSTAT_DOCUMENT_RENDER_WORKER_INTERVAL",
        "CISSTAT_PNG_RENDERER_URL",
        "CISSTAT_PNG_RENDERER_TIMEOUT_S",
        "CISSTAT_PNG_RENDERER_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    from apps.api import artifact_store, document_jobs, document_render_worker
    from apps.api import report_snapshot
    from apps.api.routers import documentation as documentation_router
    from apps.api.session_store import reset_session_store_for_testing
    from apps.api.security_audit import reset_audit_for_testing
    from apps.api.telemetry import reset_telemetry_for_testing

    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    document_render_worker.reset_document_render_worker_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    artifact_store.reset_artifact_object_store_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    document_render_worker.reset_document_render_worker_for_testing()
    documentation_router.reset_documentation_service_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()


# ── Сид на СВОИХ данных (корпус p9fix) ────────────────────────────────

RUN_ID = "RUN-P9FIX0001"
SESSION_ID = "p9fix-seed-session"
VIEW_HEATMAP = "preprocessing.missing.coverage_matrix"

PRINT_A = "dprint-p9fix-" + "a" * 24
PRINT_B = "dprint-p9fix-" + "b" * 24
SNAP_1 = "rs-p9fix-1"
SNAP_2 = "rs-p9fix-2"
DREV_1 = "drev-p9fix-1"
DREV_2 = "drev-p9fix-2"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_run() -> ResearchRun:
    from dataclasses import replace as dc_replace

    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=RUN_ID,
        session_id=SESSION_ID,
        dataset_fingerprint="p9fix" * 8,
        dataset_name="pgv09fix-write-path-seed",
        target_column="Значение",
        created_at=_now(),
        last_active_at=_now(),
        status="active",
        owner_subject=SubjectRef.from_session(SESSION_ID).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    run = dc_replace(run, context_id="ctx-p9fix-1", data_revision=11)
    get_research_run_store().upsert_run(run)
    return run


def _owner_subject() -> SubjectRef:
    return SubjectRef.from_session(SESSION_ID)


# ══════════════════════════════════════════════════════════════════════
# A. Мини-модель 0010+0016+0017+0018: replay РЕАЛЬНОГО SQL адаптера
# ══════════════════════════════════════════════════════════════════════

_MINI_MODEL_DDL = """
CREATE TABLE report_snapshots (snapshot_id TEXT PRIMARY KEY);
CREATE TABLE document_revisions (revision_id TEXT PRIMARY KEY);
CREATE TABLE document_print_revisions (print_revision_id TEXT PRIMARY KEY);
CREATE TABLE document_jobs (
    job_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    snapshot_id TEXT REFERENCES report_snapshots(snapshot_id) ON DELETE CASCADE,
    format TEXT NOT NULL,
    redaction_profile TEXT NOT NULL DEFAULT 'owner-v1',
    revision_id TEXT,
    rendition_id TEXT,
    state TEXT NOT NULL DEFAULT 'queued',
    error_code TEXT,
    attempt BIGINT NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at TEXT,
    updated_at TEXT,
    tenant_id TEXT,
    claimed_at TEXT,
    lease_expires_at TEXT,
    org_profile_id TEXT NOT NULL DEFAULT '',
    print_revision_id TEXT
        REFERENCES document_print_revisions(print_revision_id) ON DELETE CASCADE,
    basis_artifact_id TEXT
);
CREATE TABLE document_renditions (
    rendition_id TEXT PRIMARY KEY,
    revision_id TEXT
        REFERENCES document_revisions(revision_id) ON DELETE CASCADE,
    snapshot_id TEXT REFERENCES report_snapshots(snapshot_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    format TEXT NOT NULL,
    redaction_profile TEXT NOT NULL DEFAULT 'owner-v1',
    state TEXT NOT NULL DEFAULT 'ready',
    media_type TEXT NOT NULL DEFAULT '',
    size_bytes BIGINT NOT NULL DEFAULT 0,
    content_sha256 TEXT NOT NULL DEFAULT '',
    storage_key TEXT NOT NULL DEFAULT '',
    job_id TEXT,
    created_by TEXT,
    created_at TEXT,
    snapshot_payload_sha256 TEXT NOT NULL DEFAULT '',
    org_profile_id TEXT NOT NULL DEFAULT '',
    print_revision_id TEXT
        REFERENCES document_print_revisions(print_revision_id) ON DELETE CASCADE,
    UNIQUE (snapshot_id, format, redaction_profile)
);
CREATE UNIQUE INDEX uq_document_renditions_print
ON document_renditions (print_revision_id, format, redaction_profile)
WHERE print_revision_id IS NOT NULL;
INSERT INTO report_snapshots VALUES ('rs-p9fix-1');
INSERT INTO report_snapshots VALUES ('rs-p9fix-2');
INSERT INTO document_revisions VALUES ('drev-p9fix-1');
INSERT INTO document_revisions VALUES ('drev-p9fix-2');
INSERT INTO document_print_revisions VALUES ('dprint-p9fix-aaaaaaaaaaaaaaaaaaaaaaaa');
INSERT INTO document_print_revisions VALUES ('dprint-p9fix-bbbbbbbbbbbbbbbbbbbbbbbb');
"""


class _CapturingCursor:
    """psycopg-подобный курсор: capture (sql, params) для replay."""

    def __init__(self, log: list):
        self._log = log

    def execute(self, sql, params=None):
        self._log.append((sql, tuple(params) if params is not None else ()))

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _CapturingConnection:
    def __init__(self):
        self._log: list = []

    def cursor(self):
        return _CapturingCursor(self._log)

    def commit(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _capturing_registry(monkeypatch: pytest.MonkeyPatch) -> tuple[
    PostgresDocumentRegistry, list
]:
    """Postgres-адаптер с fake-соединением: каждая register_* ловит
    СВОЙ SQL+params (точная форма INSERT уходит в мини-модель)."""
    registry = PostgresDocumentRegistry("postgresql://p9fix:fake@localhost/db")
    captured: list = []

    def _fake_connect():
        conn = _CapturingConnection()
        captured.append(conn)
        return conn

    monkeypatch.setattr(registry, "_connect", _fake_connect)
    return registry, captured


def _last_statement(captured: list) -> tuple[str, tuple]:
    assert captured, "адаптер не выполнил ни одного execute"
    sql, params = captured[-1]._log[-1]
    return sql.replace("%s", "?"), params


def _mini_model() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_MINI_MODEL_DDL)
    return conn


def _print_job_record() -> DocumentJobRecord:
    """Точная форма печатной job'а из request_print_rendition
    (in-process маркер «нет значения» -- пустая строка)."""
    return DocumentJobRecord(
        job_id="djob-p9fix-" + "1" * 24,
        run_id=RUN_ID,
        snapshot_id="",
        format="png",
        redaction_profile="owner-v1",
        revision_id=PRINT_A,
        state="queued",
        attempt=1,
        created_by="subj-p9fix",
        print_revision_id=PRINT_A,
        basis_artifact_id="art-p9fix-basis",
    )


def _print_rendition_record(
    *, rendition_id: str, print_revision_id: str, job_id: str, state: str = "ready"
) -> DocumentRenditionRecord:
    """Точная форма печатной rendition из complete_render (FIX):
    revision_id='' (связь через print_revision_id с FK 0017)."""
    return DocumentRenditionRecord(
        rendition_id=rendition_id,
        revision_id="",
        snapshot_id="",
        run_id=RUN_ID,
        format="png",
        redaction_profile="owner-v1",
        state=state,
        media_type="image/png",
        size_bytes=70,
        content_sha256="f" * 64,
        storage_key="objects/p9fix",
        job_id=job_id,
        created_by="subj-p9fix",
        snapshot_payload_sha256="e" * 64,
        print_revision_id=print_revision_id,
    )


def _snapshot_rendition_record(
    *,
    rendition_id: str,
    snapshot_id: str,
    revision_id: str,
    job_id: str | None,
    state: str = "ready",
) -> DocumentRenditionRecord:
    return DocumentRenditionRecord(
        rendition_id=rendition_id,
        revision_id=revision_id,
        snapshot_id=snapshot_id,
        run_id=RUN_ID,
        format="png",
        redaction_profile="owner-v1",
        state=state,
        media_type="image/png",
        size_bytes=70,
        content_sha256="f" * 64,
        storage_key="objects/p9fix",
        job_id=job_id,
        created_by="subj-p9fix",
        snapshot_payload_sha256="e" * 64,
    )


class TestF9C1MiniModelReplay:
    """F-P9C1: реальные INSERT-формы адаптера обязаны проходить
    ограничения 0010/0016/0017/0018 без FK-нарушений и без перехвата
    чужих строк."""

    def test_print_job_insert_passes_snapshot_fk(self):
        """Печатная job (snapshot_id in-process '') пишется NULL'ом:
        FK document_jobs.snapshot_id -> report_snapshots не нарушается."""
        monkeypatch = pytest.MonkeyPatch()
        try:
            registry, captured = _capturing_registry(monkeypatch)
            registry.register_job(_print_job_record())
            sql, params = _last_statement(captured)
        finally:
            monkeypatch.undo()
        conn = _mini_model()
        conn.execute(sql, params)  # не должно поднять IntegrityError
        row = conn.execute(
            "SELECT snapshot_id, print_revision_id, basis_artifact_id "
            "FROM document_jobs WHERE job_id = ?",
            ("djob-p9fix-" + "1" * 24,),
        ).fetchone()
        assert row == (None, PRINT_A, "art-p9fix-basis")

    def test_print_rendition_insert_passes_fks(self):
        """Печатная rendition (revision_id='' и snapshot_id='') пишется
        NULL'ами: FK revision_id -> document_revisions (NOT NULL снят
        0018) и snapshot_id -> report_snapshots (0017) не нарушаются."""
        monkeypatch = pytest.MonkeyPatch()
        try:
            registry, captured = _capturing_registry(monkeypatch)
            registry.register_rendition(
                _print_rendition_record(
                    rendition_id="drend-p9fix-1",
                    print_revision_id=PRINT_A,
                    job_id="djob-p9fix-" + "1" * 24,
                )
            )
            sql, params = _last_statement(captured)
        finally:
            monkeypatch.undo()
        conn = _mini_model()
        conn.execute(sql, params)  # не должно поднять IntegrityError
        row = conn.execute(
            "SELECT revision_id, snapshot_id, print_revision_id "
            "FROM document_renditions WHERE rendition_id = 'drend-p9fix-1'"
        ).fetchone()
        assert row == (None, None, PRINT_A)

    def test_second_print_revision_does_not_hijack_first_row(self):
        """Латентный слой F-P9C1 устранён: печатные ревизии A и B с тем
        же format/profile -- ДВЕ строки; строка A не переписывается
        (rendition_id A сохраняется)."""
        monkeypatch = pytest.MonkeyPatch()
        try:
            registry, captured = _capturing_registry(monkeypatch)
            registry.register_rendition(
                _print_rendition_record(
                    rendition_id="drend-p9fix-a",
                    print_revision_id=PRINT_A,
                    job_id="djob-p9fix-a",
                    state="ready",
                )
            )
            registry.register_rendition(
                _print_rendition_record(
                    rendition_id="drend-p9fix-b",
                    print_revision_id=PRINT_B,
                    job_id="djob-p9fix-b",
                    state="ready",
                )
            )
            statements = [
                (sql.replace("%s", "?"), params)
                for conn in captured
                for (sql, params) in conn._log
            ]
        finally:
            monkeypatch.undo()
        conn = _mini_model()
        for sql, params in statements:
            conn.execute(sql, params)
        rows = conn.execute(
            "SELECT rendition_id, print_revision_id FROM document_renditions "
            "ORDER BY rendition_id"
        ).fetchall()
        assert rows == [
            ("drend-p9fix-a", PRINT_A),
            ("drend-p9fix-b", PRINT_B),
        ]

    def test_snapshot_path_renditions_coexist_across_snapshots(self):
        """Snapshot-путь: два РАЗНЫХ снимка, тот же format/profile --
        обе строки живут (print_revision_id NULL не занимает частичный
        индекс 0017); прежняя идемпотентность AC09 сохраняется."""
        monkeypatch = pytest.MonkeyPatch()
        try:
            registry, captured = _capturing_registry(monkeypatch)
            registry.register_rendition(
                _snapshot_rendition_record(
                    rendition_id="drend-p9fix-s1",
                    snapshot_id=SNAP_1,
                    revision_id=DREV_1,
                    job_id="djob-p9fix-s1",
                )
            )
            registry.register_rendition(
                _snapshot_rendition_record(
                    rendition_id="drend-p9fix-s2",
                    snapshot_id=SNAP_2,
                    revision_id=DREV_2,
                    job_id="djob-p9fix-s2",
                )
            )
            statements = [
                (sql.replace("%s", "?"), params)
                for conn in captured
                for (sql, params) in conn._log
            ]
        finally:
            monkeypatch.undo()
        conn = _mini_model()
        for sql, params in statements:
            conn.execute(sql, params)
        rows = conn.execute(
            "SELECT rendition_id, snapshot_id, print_revision_id "
            "FROM document_renditions ORDER BY rendition_id"
        ).fetchall()
        assert rows == [
            ("drend-p9fix-s1", SNAP_1, None),
            ("drend-p9fix-s2", SNAP_2, None),
        ]

    def test_print_idempotent_reregister_upserts_print_index(self):
        """Гонка двойного завершения печатной цели: повторный
        register_rendition той же (print_revision_id, format, profile)
        -- апсерт по частичному индексу 0017: ОДНА строка, rendition_id
        первой сохраняется, состояние обновляется."""
        monkeypatch = pytest.MonkeyPatch()
        try:
            registry, captured = _capturing_registry(monkeypatch)
            registry.register_rendition(
                _print_rendition_record(
                    rendition_id="drend-p9fix-r1",
                    print_revision_id=PRINT_A,
                    job_id="djob-p9fix-r1",
                    state="ready",
                )
            )
            registry.register_rendition(
                _print_rendition_record(
                    rendition_id="drend-p9fix-r2",
                    print_revision_id=PRINT_A,
                    job_id="djob-p9fix-r2",
                    state="failed",
                )
            )
            statements = [
                (sql.replace("%s", "?"), params)
                for conn in captured
                for (sql, params) in conn._log
            ]
        finally:
            monkeypatch.undo()
        conn = _mini_model()
        for sql, params in statements:
            conn.execute(sql, params)
        rows = conn.execute(
            "SELECT rendition_id, state, job_id FROM document_renditions"
        ).fetchall()
        assert rows == [("drend-p9fix-r1", "failed", "djob-p9fix-r2")]

    def test_snapshot_idempotent_reregister_keeps_legacy_upsert(self):
        """AC09 без регрессии: повторный register_rendition того же
        (snapshot_id, format, profile) -- прежний апсерт по UNIQUE 0010."""
        monkeypatch = pytest.MonkeyPatch()
        try:
            registry, captured = _capturing_registry(monkeypatch)
            registry.register_rendition(
                _snapshot_rendition_record(
                    rendition_id="drend-p9fix-u1",
                    snapshot_id=SNAP_1,
                    revision_id=DREV_1,
                    job_id="djob-p9fix-u1",
                    state="ready",
                )
            )
            registry.register_rendition(
                _snapshot_rendition_record(
                    rendition_id="drend-p9fix-u2",
                    snapshot_id=SNAP_1,
                    revision_id=DREV_1,
                    job_id="djob-p9fix-u2",
                    state="failed",
                )
            )
            statements = [
                (sql.replace("%s", "?"), params)
                for conn in captured
                for (sql, params) in conn._log
            ]
        finally:
            monkeypatch.undo()
        conn = _mini_model()
        for sql, params in statements:
            conn.execute(sql, params)
        rows = conn.execute(
            "SELECT rendition_id, state, revision_id FROM document_renditions"
        ).fetchall()
        assert rows == [("drend-p9fix-u1", "failed", DREV_1)]

    def test_adapter_normalizes_empty_markers_to_null(self):
        """Точка исправления прямо в адаптере: параметры register_job /
        register_rendition несут None (не '') для печатных ключей."""
        monkeypatch = pytest.MonkeyPatch()
        try:
            registry, captured = _capturing_registry(monkeypatch)
            registry.register_job(_print_job_record())
            _sql, job_params = _last_statement(captured)
            # (job_id, run_id, snapshot_id, ...) -- snapshot_id третий.
            assert job_params[2] is None
            # print_revision_id/basis_artifact_id -- последние два.
            assert job_params[17] == PRINT_A
            assert job_params[18] == "art-p9fix-basis"
            registry.register_rendition(
                _print_rendition_record(
                    rendition_id="drend-p9fix-n",
                    print_revision_id=PRINT_A,
                    job_id="djob-p9fix-1" + "1" * 23,
                )
            )
            _sql, rend_params = _last_statement(captured)
            assert rend_params[1] is None  # revision_id
            assert rend_params[2] is None  # snapshot_id
            assert rend_params[16] == PRINT_A  # print_revision_id
            registry.register_rendition(
                _snapshot_rendition_record(
                    rendition_id="drend-p9fix-m",
                    snapshot_id=SNAP_1,
                    revision_id=DREV_1,
                    job_id="djob-p9fix-m",
                )
            )
            _sql, snap_params = _last_statement(captured)
            assert snap_params[1] == DREV_1
            assert snap_params[2] == SNAP_1
            assert snap_params[16] is None  # print_revision_id -> NULL
        finally:
            monkeypatch.undo()

    def test_update_rendition_normalizes_print_revision_marker(self):
        """update_rendition (CAS-ветки complete_render/fail_render):
        пустой маркер print_revision_id snapshot-пути пишется NULL'ом --
        строка не занимает частичный индекс 0017, последующая печатная/
        snapshot-запись не коллодит."""
        monkeypatch = pytest.MonkeyPatch()
        try:
            registry, captured = _capturing_registry(monkeypatch)
            registry.register_rendition(
                _snapshot_rendition_record(
                    rendition_id="drend-p9fix-up1",
                    snapshot_id=SNAP_1,
                    revision_id=DREV_1,
                    job_id="djob-p9fix-up1",
                    state="ready",
                )
            )
            registry.update_rendition(
                _snapshot_rendition_record(
                    rendition_id="drend-p9fix-up1",
                    snapshot_id=SNAP_1,
                    revision_id=DREV_1,
                    job_id="djob-p9fix-up2",
                    state="failed",
                )
            )
            statements = [
                (sql.replace("%s", "?"), params)
                for conn in captured
                for (sql, params) in conn._log
            ]
            # И вторая snapshot-rendition ДРУГОГО снимка -- тот же
            # format/profile: не должна коллодить с обновлённой строкой.
            registry.register_rendition(
                _snapshot_rendition_record(
                    rendition_id="drend-p9fix-up2",
                    snapshot_id=SNAP_2,
                    revision_id=DREV_2,
                    job_id="djob-p9fix-up2",
                    state="ready",
                )
            )
            statements.append(_last_statement(captured))
        finally:
            monkeypatch.undo()
        conn = _mini_model()
        for sql, params in statements:
            conn.execute(sql, params)
        row = conn.execute(
            "SELECT print_revision_id, state FROM document_renditions "
            "WHERE rendition_id = 'drend-p9fix-up1'"
        ).fetchone()
        assert row == (None, "failed")
        count = conn.execute(
            "SELECT count(*) FROM document_renditions"
        ).fetchone()[0]
        assert count == 2


# ══════════════════════════════════════════════════════════════════════
# B. Чтение durable-строк: NULL -> '' (не "None")
# ══════════════════════════════════════════════════════════════════════


class TestF9C1ReadMapping:
    def test_job_row_null_snapshot_reads_as_empty_marker(self):
        from datetime import datetime as dt

        now = dt.now(timezone.utc)
        row = (
            "djob-p9fix-" + "1" * 24,  # job_id
            RUN_ID,  # run_id
            None,  # snapshot_id (durable NULL)
            "png",
            "owner-v1",
            PRINT_A,  # revision_id
            None,  # rendition_id
            "queued",
            None,  # error_code
            1,  # attempt
            "subj-p9fix",
            now,
            now,
            None,  # tenant_id
            None,  # claimed_at
            None,  # lease_expires_at
            "",  # org_profile_id
            PRINT_A,
            "art-p9fix-basis",
        )
        job = PostgresDocumentRegistry._job_from_row(row)
        assert job.snapshot_id == ""
        assert job.print_revision_id == PRINT_A
        assert job.revision_id == PRINT_A
        assert job.basis_artifact_id == "art-p9fix-basis"

    def test_rendition_row_null_keys_read_as_empty_marker(self):
        from datetime import datetime as dt

        now = dt.now(timezone.utc)
        row = (
            "drend-p9fix-1",  # rendition_id
            None,  # revision_id (durable NULL)
            None,  # snapshot_id (durable NULL)
            RUN_ID,
            "png",
            "owner-v1",
            "ready",
            "image/png",
            70,
            "f" * 64,
            "objects/p9fix",
            "djob-p9fix-" + "1" * 24,
            "subj-p9fix",
            now,
            "e" * 64,
            "",
            PRINT_A,
        )
        rendition = PostgresDocumentRegistry._rendition_from_row(row)
        assert rendition.revision_id == ""
        assert rendition.snapshot_id == ""
        assert rendition.print_revision_id == PRINT_A


# ══════════════════════════════════════════════════════════════════════
# C. Сервис (Memory): печатная rendition -- revision_id=''
# ══════════════════════════════════════════════════════════════════════


_PNG_FIX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082"
)


class _FakeFixRenderer:
    def __init__(self, png: bytes = _PNG_FIX, error: Exception | None = None):
        self.png = png
        self.error = error
        self.payloads: list[dict] = []

    def render_page(
        self, payload: dict, *, timeout_s: float | None = None
    ) -> bytes:
        self.payloads.append(payload)
        if self.error is not None:
            raise self.error
        return self.png


def _print_revision_pair():
    """Печатная ревизия V01 на МОИХ данных (паритет авторского харнеса)."""
    from apps.api.document_jobs import DocumentDeliveryService
    from apps.api.visual_artifacts import (
        freeze_visual_print_snapshot,
        freeze_visual_result,
    )

    _seed_run()
    data = {
        "row_headings": ["Строка 1", "Строка 2"],
        "column_headings": ["Колонка 1", "Колонка 2"],
        "cells": [[1, 2], [3, 4]],
    }
    from apps.api.artifact_store import (
        artifact_content_sha256,
        canonical_json_bytes,
    )
    from apps.api.print_schema import PRINT_RESULT_SCHEMA_VERSION

    result_payload = {
        "schema_version": PRINT_RESULT_SCHEMA_VERSION,
        "view_id": VIEW_HEATMAP,
        "payload": {
            "kind": "html_heatmap",
            "series_cap": None,
            "digest": artifact_content_sha256(canonical_json_bytes(data)),
            "digest_reason": None,
            "data": data,
        },
        "parameters": {
            "origin": "producer_freeze",
            "method": "missing_coverage",
            "parameters": {"bins": 4, "row_window": 100},
        },
        "units": [{"value": "ячеек", "reason": None}],
        "sampling": {
            "applicable": True,
            "mode": "full",
            "point_cap": None,
            "reason": None,
        },
        "warnings": [],
        "execution": {
            "execution_ref": "exec-p9fix-1",
            "result_ref": "session:preprocessing.missing:v11",
            "computed_at": "2026-10-30T12:00:00Z",
            "computed_at_reason": None,
        },
    }
    from apps.api.print_schema import (
        PRINT_SNAPSHOT_SCHEMA_VERSION,
        resolve_scope,
    )

    def _site_of(view_id: str) -> dict:
        from apps.api.print_schema import load_visual_registry

        return next(
            s
            for s in load_visual_registry()["sites"]
            if s["view_id"] == view_id
        )

    site = _site_of(VIEW_HEATMAP)
    scope = resolve_scope(site)
    refs = {ref: f"p9fix:{ref}" for ref in site["required_refs"]}
    refs.setdefault("context_id", "ctx-p9fix-1")
    refs.setdefault("data_revision", "11")
    section = {
        "section_id": "fix-heat-1",
        "renderer_kind": "html_heatmap",
        "title": "Матрица пропусков (fix)",
        "axes": [],
        "legend_ordering": [],
        "table_headings": None,
        "heatmap_scale": {
            "domain": [0, 5],
            "units": {"value": "ячеек", "reason": None},
        },
        "units": [{"value": "ячеек", "reason": None}],
    }
    snapshot_payload = {
        "schema_version": PRINT_SNAPSHOT_SCHEMA_VERSION,
        "view_id": VIEW_HEATMAP,
        "scope": scope,
        "refs": refs,
        "result": {
            "result_ref": "artifact:visual_result:p9fix",
            "result_schema_version": "pgv.visual_result/1",
            "result_digest": result_payload["payload"]["digest"],
            "result_digest_reason": None,
        },
        "data_artifact": {
            "artifact_id": "artifact:p9fix-data",
            "artifact_version": "v11",
            "source_hash": "d" * 64,
            "hash_algorithm": "sha256",
            "hash_reason": None,
        },
        "expected_context": {
            "context_id": "ctx-p9fix-1",
            "data_revision": "11",
            "expected_data_digest": None,
        },
        "dimensions": {
            "target_column": refs.get("target_column"),
            "date_column": refs.get("date_column"),
            "entity_column": refs.get("entity_column"),
            "entity_id": refs.get("entity"),
            "mode": "univariate",
        },
        "times": {
            "computed_at": "2026-10-30T12:00:00Z",
            "computed_at_reason": None,
            "captured_at": "2026-10-30T12:00:01Z",
            "captured_at_reason": None,
            "checkpoint_confirmed_at": None,
            "render_requested_at": "2026-10-30T12:00:02Z",
            "timezone": "UTC",
            "locale": "ru-RU",
        },
        "checkpoint": None,
        "display": {
            "title": "Матрица пропусков (fix)",
            "subtitle": None,
            "detail_level": "compact",
            "sections": [section],
        },
        "method": {
            "origin": "producer_freeze",
            "method": "missing_coverage",
            "parameters": {},
        },
        "selection": {
            "allowlist": list(site["view_params"]),
            "values": {"bins": 4, "row_window": 100},
        },
        "sampling": {
            "applicable": True,
            "mode": "full",
            "point_cap": None,
            "reason": None,
        },
        "annotations": {"revision": 0, "author": "p9fix-analyst", "text": None},
        "print": {
            "profile_id": "figure-landscape",
            "page_count": 1,
            "theme": "light-print",
        },
        "renderer_env": {
            "renderer_version": "print-renderer/1",
            "font_profile": "print-fonts-dejavu/1",
            "dependency_status": "available",
            "unavailable_reason": None,
        },
        "data_flow": {"before_revision": None, "after_revision": None},
        "sensitive": {
            "raw_data_included": False,
            "sensitive_fields_policy": "metadata_only",
        },
        "warnings": [],
    }
    subject = _owner_subject()
    result = freeze_visual_result(
        RUN_ID, subject, payload=result_payload
    )
    snapshot = freeze_visual_print_snapshot(
        RUN_ID,
        subject,
        payload=snapshot_payload,
        result_artifact_id=result.artifact_id,
    )
    service = DocumentDeliveryService.create_default()
    document, revision, _created = service.ensure_print_document_revision(
        RUN_ID,
        subject,
        session_id=SESSION_ID,
        print_kind="V01",
        basis_kind="visual_print_snapshot",
        basis_artifact_ids=[snapshot.artifact_id],
        profile_id="figure-landscape",
    )
    return service, document, revision, snapshot, result_payload


class TestF9C1ServicePrintBranch:
    def test_print_rendition_revision_id_is_empty_marker(self):
        """complete_render для печатной rendition НЕ переносит
        job.revision_id (print_revision_id) в rendition.revision_id:
        durable-слой пишет NULL (0018), связь цели -- print_revision_id
        (FK 0017)."""
        from apps.api.document_render_worker import DocumentRenderWorker

        service, _document, revision, _snapshot, _result = (
            _print_revision_pair()
        )
        job, _rendition = service.request_print_rendition(
            revision.print_revision_id,
            format="png",
            subject=_owner_subject(),
            session_id=SESSION_ID,
        )
        assert job.state == "queued"
        assert job.snapshot_id == ""  # in-process маркер (паритет автора)
        worker = DocumentRenderWorker(
            render_timeout=5.0, interval=None, png_renderer=_FakeFixRenderer()
        )
        assert worker.run_once()["ready"] == 1
        ready = service.registry.get_job(job.job_id)
        assert ready.state == "ready"
        rendition = service.registry.get_rendition(ready.rendition_id)
        assert rendition is not None
        assert rendition.state == "ready"
        # ИСПРАВЛЕНИЕ: не dprint-... (было: FK document_revisions).
        assert rendition.revision_id == ""
        assert rendition.print_revision_id == revision.print_revision_id
        assert rendition.snapshot_id == ""
        # Job сохраняет авторскую конвенцию цели (jobs.revision_id без
        # FK; durable NULL-нормализация не требуется).
        assert ready.revision_id == revision.print_revision_id


# ══════════════════════════════════════════════════════════════════════
# D. N-P9C2: непериализуемый payload -- terminal invalid_payload
# ══════════════════════════════════════════════════════════════════════


class TestNP9C2SerializationGate:
    def test_nan_payload_is_terminal_payload_invalid_before_network(self):
        """render_page: payload с NaN -- RendererPayloadInvalid ДО
        сетевого вызова (urlopen не вызывается вовсе); не raw ValueError
        и не transient."""
        from apps.api.png_renderer_client import (
            PngRendererClient,
            RendererPayloadInvalid,
        )

        calls: list = []

        def _no_network(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("сетевой вызов не должен выполняться")

        monkeypatch = pytest.MonkeyPatch()
        try:
            monkeypatch.setattr(
                "urllib.request.urlopen", _no_network
            )
            client = PngRendererClient(
                base_url="http://127.0.0.1:9", enabled=True
            )
            with pytest.raises(RendererPayloadInvalid):
                client.render_page(
                    {"sections": [{"cells": [[float("nan")]]}]}
                )
        finally:
            monkeypatch.undo()
        assert calls == []

    def test_non_serializable_payload_is_terminal_payload_invalid(self):
        """Непериализуемый тип (TypeError json.dumps) -- тот же честный
        terminal, а не transient."""
        from apps.api.png_renderer_client import (
            PngRendererClient,
            RendererPayloadInvalid,
        )

        monkeypatch = pytest.MonkeyPatch()
        try:
            monkeypatch.setattr(
                "urllib.request.urlopen",
                lambda *a, **k: (_ for _ in ()).throw(
                    AssertionError("no network")
                ),
            )
            client = PngRendererClient(
                base_url="http://127.0.0.1:9", enabled=True
            )
            with pytest.raises(RendererPayloadInvalid):
                client.render_page({"sections": [{"cells": object()}]})
        finally:
            monkeypatch.undo()

    def test_nan_payload_message_does_not_leak_payload(self):
        """AC21: сообщение об ошибке не содержит payload (только тип
        дефекта)."""
        from apps.api.png_renderer_client import (
            PngRendererClient,
            RendererPayloadInvalid,
        )

        monkeypatch = pytest.MonkeyPatch()
        try:
            monkeypatch.setattr(
                "urllib.request.urlopen",
                lambda *a, **k: (_ for _ in ()).throw(
                    AssertionError("no network")
                ),
            )
            client = PngRendererClient(
                base_url="http://127.0.0.1:9", enabled=True
            )
            try:
                client.render_page({"secret_marker_p9fix": float("nan")})
            except RendererPayloadInvalid as exc:
                assert "secret_marker_p9fix" not in str(exc)
            else:  # pragma: no cover
                pytest.fail("RendererPayloadInvalid не поднят")
        finally:
            monkeypatch.undo()

    def test_worker_nan_payload_is_terminal_invalid_payload(self):
        """D-класс: NaN в durable basis (обход канонического freeze --
        ячейки html_heatmap переносятся дословно) -> job terminal
        invalid_payload БЕЗ requeue-цикла и без rendition (реальный
        клиент, сеть не достигается: сериализация до urlopen)."""
        from apps.api.document_render_worker import DocumentRenderWorker
        from apps.api.png_renderer_client import PngRendererClient

        service, _document, revision, _snapshot, result_payload = (
            _print_revision_pair()
        )
        job, _rendition = service.request_print_rendition(
            revision.print_revision_id,
            format="png",
            subject=_owner_subject(),
            session_id=SESSION_ID,
        )
        # Обходной путь записи артефактов (риск из акта CERT): NaN в
        # cells durable-артефакта -- bridge переносит cells дословно.
        poisoned = {
            "snapshot": _snapshot_payload_with_nan_cells(),
            "visual_result": result_payload,
            "basis_sha256": "f" * 64,
        }
        poisoned["visual_result"]["payload"]["data"] = {
            "row_headings": ["Строка 1"],
            "column_headings": ["Колонка 1", "Колонка 2"],
            "cells": [[1.0, float("nan")]],
        }
        worker = DocumentRenderWorker(
            render_timeout=5.0,
            interval=None,
            png_renderer=PngRendererClient(
                base_url="http://127.0.0.1:9", enabled=True
            ),
        )
        worker._print_input_loader = lambda artifact_id: poisoned
        report = worker.run_once()
        assert report["failed"] == 1
        assert report["requeued"] == 0
        failed = service.registry.get_job(job.job_id)
        assert failed.state == "failed"
        # ИСПРАВЛЕНИЕ N-P9C2: terminal invalid_payload (было: transient
        # render_failed -> requeue-цикл до исчерпания попыток).
        assert failed.error_code == "invalid_payload"
        assert failed.attempt == job.attempt  # без прироста requeue
        assert (
            service.registry.find_print_rendition(
                revision.print_revision_id, "png", "owner-v1"
            )
            is None
        )

    def test_invalid_payload_is_not_transient_code(self):
        """Таксономия worker'а: invalid_payload -- terminal (вне
        TRANSIENT_ERROR_CODES); маппинг RendererPayloadInvalid -- код
        invalid_payload."""
        from apps.api.document_render_worker import (
            TRANSIENT_ERROR_CODES,
            DocumentRenderWorker,
        )
        from apps.api.png_renderer_client import RendererPayloadInvalid

        assert "invalid_payload" not in TRANSIENT_ERROR_CODES
        assert (
            DocumentRenderWorker._error_code(
                RendererPayloadInvalid("bad payload")
            )
            == "invalid_payload"
        )


def _snapshot_payload_with_nan_cells() -> dict:
    """Снапшот печатной теплокарты (форма p9fix, preflight-валидная);
    NaN добавляется в cells visual_result в тесте выше."""
    from apps.api.print_schema import PRINT_SNAPSHOT_SCHEMA_VERSION

    def _site_of(view_id: str) -> dict:
        from apps.api.print_schema import load_visual_registry

        return next(
            s
            for s in load_visual_registry()["sites"]
            if s["view_id"] == view_id
        )

    site = _site_of(VIEW_HEATMAP)
    from apps.api.print_schema import resolve_scope

    scope = resolve_scope(site)
    refs = {ref: f"p9fix:{ref}" for ref in site["required_refs"]}
    refs.setdefault("context_id", "ctx-p9fix-1")
    refs.setdefault("data_revision", "11")
    section = {
        "section_id": "fix-heat-nan",
        "renderer_kind": "html_heatmap",
        "title": "Матрица пропусков (fix, NaN)",
        "axes": [],
        "legend_ordering": [],
        "table_headings": None,
        "heatmap_scale": {
            "domain": [0, 5],
            "units": {"value": "ячеек", "reason": None},
        },
        "units": [{"value": "ячеек", "reason": None}],
    }
    return {
        "schema_version": PRINT_SNAPSHOT_SCHEMA_VERSION,
        "view_id": VIEW_HEATMAP,
        "scope": scope,
        "refs": refs,
        "result": {
            "result_ref": "artifact:visual_result:p9fix-nan",
            "result_schema_version": "pgv.visual_result/1",
            "result_digest": "b" * 64,
            "result_digest_reason": None,
        },
        "data_artifact": {
            "artifact_id": "artifact:p9fix-data-nan",
            "artifact_version": "v11",
            "source_hash": "d" * 64,
            "hash_algorithm": "sha256",
            "hash_reason": None,
        },
        "expected_context": {
            "context_id": "ctx-p9fix-1",
            "data_revision": "11",
            "expected_data_digest": None,
        },
        "dimensions": {
            "target_column": refs.get("target_column"),
            "date_column": refs.get("date_column"),
            "entity_column": refs.get("entity_column"),
            "entity_id": refs.get("entity"),
            "mode": "univariate",
        },
        "times": {
            "computed_at": "2026-10-30T12:00:00Z",
            "computed_at_reason": None,
            "captured_at": "2026-10-30T12:00:01Z",
            "captured_at_reason": None,
            "checkpoint_confirmed_at": None,
            "render_requested_at": "2026-10-30T12:00:02Z",
            "timezone": "UTC",
            "locale": "ru-RU",
        },
        "checkpoint": None,
        "display": {
            "title": "Матрица пропусков (fix, NaN)",
            "subtitle": None,
            "detail_level": "compact",
            "sections": [section],
        },
        "method": {
            "origin": "producer_freeze",
            "method": "missing_coverage",
            "parameters": {},
        },
        "selection": {
            "allowlist": list(site["view_params"]),
            "values": {"bins": 4, "row_window": 100},
        },
        "sampling": {
            "applicable": True,
            "mode": "full",
            "point_cap": None,
            "reason": None,
        },
        "annotations": {"revision": 0, "author": "p9fix-analyst", "text": None},
        "print": {
            "profile_id": "figure-landscape",
            "page_count": 1,
            "theme": "light-print",
        },
        "renderer_env": {
            "renderer_version": "print-renderer/1",
            "font_profile": "print-fonts-dejavu/1",
            "dependency_status": "available",
            "unavailable_reason": None,
        },
        "data_flow": {"before_revision": None, "after_revision": None},
        "sensitive": {
            "raw_data_included": False,
            "sensitive_fields_policy": "metadata_only",
        },
        "warnings": [],
    }


# ══════════════════════════════════════════════════════════════════════
# E. Миграция 0018: revision_id DROP NOT NULL (аддитивность, паритет)
# ══════════════════════════════════════════════════════════════════════


class TestMigration0018:
    MIGRATION_NAME = "0018_pgv9fix_print_rendition_keys.sql"

    def test_migration_file_exists_and_additive(self):
        sql = Path("apps/api/migrations") / self.MIGRATION_NAME
        text = sql.read_text("utf-8")
        assert "ALTER TABLE document_renditions" in text
        assert "revision_id" in text
        assert "DROP NOT NULL" in text
        # Только аддитивные формы: никаких DROP TABLE/DROP COLUMN.
        assert "DROP TABLE" not in text
        assert "DROP COLUMN" not in text

    def test_migration_catalog_contains_0018(self):
        from apps.api.research_runs import MIGRATION_FILES

        names = [name for name, _statements in MIGRATION_FILES]
        assert self.MIGRATION_NAME in names
        assert len(names) == 18

    def test_migration_statements_parity(self):
        """Паритет каталога и файла (паттерн PROGR-5.1, форма теста
        0017)."""
        from apps.api.research_runs import (
            MIGRATION_FILES,
            MIGRATION_STATEMENTS_0018,
        )

        sql = (Path("apps/api/migrations") / self.MIGRATION_NAME).read_text(
            "utf-8"
        )
        joined = "\n".join(MIGRATION_STATEMENTS_0018)
        for statement in MIGRATION_STATEMENTS_0018:
            compact = " ".join(statement.split())
            assert compact in " ".join(sql.split()), statement[:80]
        for line in sql.splitlines():
            stripped = line.strip().rstrip(";")
            if not stripped or stripped.startswith("--"):
                continue
            assert stripped in joined, f"строка файла вне каталога: {stripped!r}"
        assert (self.MIGRATION_NAME, MIGRATION_STATEMENTS_0018) in MIGRATION_FILES

    def test_full_statements_end_with_0018(self):
        from apps.api.research_runs import (
            MIGRATION_STATEMENTS,
            MIGRATION_STATEMENTS_0018,
        )

        tail = MIGRATION_STATEMENTS[-len(MIGRATION_STATEMENTS_0018):]
        assert tuple(tail) == tuple(MIGRATION_STATEMENTS_0018)
