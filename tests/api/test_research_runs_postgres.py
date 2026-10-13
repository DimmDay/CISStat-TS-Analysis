# tests/api/test_research_runs_postgres.py
"""Интеграционные тесты Task PROGR-5.1: долговременный слой PROGR-5
(research_runs/trace_events, spec_progress.md §12 п.1) на РЕАЛЬНОМ
Postgres-сервере + прогон DDL (apps/api/migrations/0001_research_runs.sql).

Затвор средой: модуль выполняется ТОЛЬКО при заданном CISSTAT_TEST_PG_DSN
(DSN доступного Postgres); иначе -- skip на уровне модуля (CI без Postgres
остаётся зелёным, базлайн PROGR-5 не меняется). Запуск on-prem:

    CISSTAT_TEST_PG_DSN='postgresql://user:pass@host:5432/db' \
        pytest tests/api/test_research_runs_postgres.py -v

Контуры (дополнение к test_research_runs.py, который в среде без Postgres
покрывает Memory-контракт и DDL-константы):

  1. DDL-файл создаёт все объекты схемы §12 п.1 (таблицы + индексы).
  2. Идемпотентность: повторный прогон DDL не падает и не меняет схему.
  3. Эквивалентность двух источников DDL: SQL-файл для ops и
     MIGRATION_STATEMENTS (Python, авто-миграция первого коннекта)
     приводят к ОДНОМУ множеству объектов (рассинхронизация -- находка).
  4. Поведенческий контракт PostgresResearchRunStore на живой БД:
     раундтрип запуска/событий (JSONB, юникод, node_id=None -- N-2),
     статусы pause/resume/supersede, чекпоинты, ON CONFLICT DO NOTHING.
  5. DDL-гарантии на сервере: UNIQUE (run_id, event_id), FK
     ON DELETE CASCADE.
  6. REST-смоук сквозь TestClient: CISSTAT_RUNS_BACKEND=postgres --
     demo-загрузка создаёт запуск в Postgres, пауза/resume/чекпоинт
     эндпоинтов PROGR-5 реально персистентны.
"""
from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

DSN = os.environ.get("CISSTAT_TEST_PG_DSN", "")
if not DSN:
    pytest.skip(
        "CISSTAT_TEST_PG_DSN не задан -- Postgres-интеграция пропущена "
        "(см. докстринг модуля)",
        allow_module_level=True,
    )

try:
    import psycopg
except ImportError:  # pragma: no cover - среда без драйвера
    pytest.skip(
        "psycopg не установлен -- Postgres-интеграция пропущена",
        allow_module_level=True,
    )

from apps.api.main import app
from apps.api.research_runs import (
    MIGRATION_STATEMENTS,
    PostgresResearchRunStore,
    ResearchCheckpoint,
    ResearchRun,
    run_migrations,
)
from apps.api.session_store import (
    AnalysisSession,
    get_session_store,
    reset_session_store_for_testing,
    SESSION_COOKIE_NAME,
)
from apps.api.trace_events import make_trace_event

MIGRATIONS_FILES = (
    # Каталог миграций (AUDIT-6A): 0001 -- базовая схема (НЕ переписывается),
    # 0002 -- атомарный ledger (аддитивно; план §7).
    # AUDIT-1A: 0003 -- происхождение цели (аддитивно; план §9).
    # AUDIT-6B: 0005 -- durable outbox доставки (аддитивно; план §17 п.4).
    "0001_research_runs.sql",
    "0002_audit6a_atomic_ledger.sql",
    "0003_audit1a_target_source.sql",
    "0005_audit6b_delivery_outbox.sql",
)
MIGRATIONS_FILE = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "api"
    / "migrations"
    / "0001_research_runs.sql"
)
MIGRATIONS_FILE_0002 = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "api"
    / "migrations"
    / "0002_audit6a_atomic_ledger.sql"
)
MIGRATIONS_FILE_0003 = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "api"
    / "migrations"
    / "0003_audit1a_target_source.sql"
)
MIGRATIONS_FILE_0005 = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "api"
    / "migrations"
    / "0005_audit6b_delivery_outbox.sql"
)

EXPECTED_TABLES = {
    "research_runs", "trace_events", "run_checkpoints", "run_commit_receipts",
    # AUDIT-6B: durable outbox обязательств доставки (план §17 п.4).
    "progress_delivery_outbox",
}
EXPECTED_INDEXES = {
    "idx_trace_events_run_seq",
    "idx_research_runs_session",
    "idx_research_runs_status",
    # AUDIT-6A: позиция ledger + receipts.
    "uq_trace_events_run_commit_seq",
    "idx_trace_events_run_commit_seq",
    "idx_run_commit_receipts_run",
    # AUDIT-6B: outbox доставки (due-выборка worker'а + реестр запуска).
    "idx_progress_delivery_outbox_due",
    "idx_progress_delivery_outbox_run",
}

DROP_SCHEMA_SQL = """
DROP TABLE IF EXISTS progress_delivery_outbox CASCADE;
DROP TABLE IF EXISTS run_commit_receipts CASCADE;
DROP TABLE IF EXISTS run_checkpoints CASCADE;
DROP TABLE IF EXISTS trace_events CASCADE;
DROP TABLE IF EXISTS research_runs CASCADE;
DROP TABLE IF EXISTS mentor_observations CASCADE;
"""


def _apply_sql_file(conn) -> None:
    """Прогон DDL-ФАЙЛОВ ops-контуром: простой протокол (без параметров)
    исполняет весь каталог целиком -- ровно как psql -f 0001... -f 0002...
    (AUDIT-6A: каталог аддитивен, 0001 не переписывается -- план §7)."""
    with conn.cursor() as cur:
        for name in MIGRATIONS_FILES:
            path = MIGRATIONS_FILE.parent / name
            cur.execute(path.read_text(encoding="utf-8"))
    conn.commit()


def _schema_objects(conn) -> tuple[set[str], set[str]]:
    """(таблицы public, индексы public) -- факт сервера, не теста."""
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    }
    indexes = {
        row[0]
        for row in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
        ).fetchall()
    }
    return tables, indexes


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fresh_schema():
    """Чистая схема + DDL-файл; возвращает соединение. Каждый тест --
    с нуля (объекты не протекают между тестами)."""
    conn = psycopg.connect(DSN, autocommit=False)
    with conn.cursor() as cur:
        cur.execute(DROP_SCHEMA_SQL)
    conn.commit()
    _apply_sql_file(conn)
    return conn


@pytest.fixture()
def pg_conn():
    conn = _fresh_schema()
    yield conn
    conn.close()


@pytest.fixture()
def store() -> PostgresResearchRunStore:
    """Хранилище на живой БД (схему гарантирует pg_conn-порядок теста;
    ensure_schema идемпотентен и повторных объектов не создаёт)."""
    return PostgresResearchRunStore(dsn=DSN)


def _seed_run(
    run_id: str = "RUN-PGTEST01", session_id: str = "sess-pg", **kwargs
) -> ResearchRun:
    return ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="a" * 64,
        dataset_name="demo_sales.csv (демо-датасет)",
        target_column=None,
        created_at=_now_iso(),
        last_active_at=_now_iso(),
        **kwargs,
    )


# ── Контур 1-3: DDL-файл, идемпотентность, эквивалентность источников ──


class TestDdlFile:
    def test_ddl_file_creates_all_objects(self, pg_conn):
        tables, indexes = _schema_objects(pg_conn)
        assert EXPECTED_TABLES <= tables
        assert EXPECTED_INDEXES <= indexes

    def test_ddl_file_is_idempotent(self, pg_conn):
        """Повторный прогон (ops-реалия: скрипт мог частично примениться)
        не падает и не меняет множество объектов."""
        before = _schema_objects(pg_conn)
        _apply_sql_file(pg_conn)
        _apply_sql_file(pg_conn)
        assert _schema_objects(pg_conn) == before

    def test_migration_statements_match_ddl_file_result(self, pg_conn):
        """Авто-миграция первого коннекта (MIGRATION_STATEMENTS) и SQL-файл
        ops-контура приводят к одному множеству объектов: рассинхронизация
        источников ловится на живом сервере, а не только сравнением текстов.

        Versioned-обновление (AUDIT-6A): каталог -- 0001 + 0002 (аддитивно,
        0001 не переписывается -- план §7). Versioned-обновление (AUDIT-1A):
        каталог -- 0001+0002+0003 (происхождение цели, аддитивно -- план §9);
        MIGRATION_STATEMENTS == 0001+0002+0003. Versioned-обновление
        (AUDIT-6B): каталог -- 0001+0002+0003+0005 (durable outbox
        доставки, аддитивно -- план §17 п.4)."""
        file_sql = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (MIGRATIONS_FILE, MIGRATIONS_FILE_0002, MIGRATIONS_FILE_0003,
                         MIGRATIONS_FILE_0005)
        )
        assert "run_commit_receipts" in file_sql
        assert "target_column_source" in file_sql
        assert "progress_delivery_outbox" in file_sql
        file_tables, file_indexes = _schema_objects(pg_conn)
        with pg_conn.cursor() as cur:
            cur.execute(DROP_SCHEMA_SQL)
        pg_conn.commit()
        conn2 = psycopg.connect(DSN)
        try:
            run_migrations(conn2)
        finally:
            conn2.close()
        py_tables, py_indexes = _schema_objects(pg_conn)
        assert py_tables == file_tables
        assert py_indexes == file_indexes


# ── Контур 4: поведенческий контракт хранилища на живой БД ────────────


class TestPostgresStoreBehavior:
    def test_run_roundtrip(self, pg_conn, store):
        run = _seed_run()
        store.upsert_run(run)
        loaded = store.get_run(run.run_id)
        assert loaded is not None
        assert loaded.run_id == run.run_id
        assert loaded.session_id == run.session_id
        assert loaded.dataset_fingerprint == run.dataset_fingerprint
        assert loaded.dataset_name == run.dataset_name
        # TS -- TIMESTAMPTZ: значение сохраняется с точностью до микросекунды
        assert abs(
            datetime.fromisoformat(loaded.created_at)
            - datetime.fromisoformat(run.created_at)
        ).total_seconds() < 1.0
        assert loaded.status == "active"

    def test_target_pair_roundtrip_and_reset(self, pg_conn, store):
        """AUDIT-1A (миграция 0003, план §9): пара (target, origin) --
        durable на живом PostgreSQL. "auto"/"user" сохраняются; None --
        осознанное значение пары (сброс) пишется напрямую (не
        COALESCE): прямой upsert с None стирает прежний origin.
        Legacy-строка (NULL) читается честным отсутствием."""
        # auto-выбор durable.
        from dataclasses import replace as dc_replace

        run = dc_replace(
            _seed_run(), target_column="rain", target_column_source="auto",
        )
        store.upsert_run(run)
        loaded = store.get_run(run.run_id)
        assert loaded.target_column == "rain"
        assert loaded.target_column_source == "auto"

        # Прямая запись None -- сброс пары (parity Memory/SQL).
        from dataclasses import replace as dc_replace

        store.upsert_run(
            dc_replace(loaded, target_column=None, target_column_source=None)
        )
        reset = store.get_run(run.run_id)
        assert reset.target_column is None
        assert reset.target_column_source is None

        # Legacy-строка без пары -- честное отсутствие.
        legacy = _seed_run(run_id="RUN-PGLEGACY01")
        store.upsert_run(legacy)
        loaded_legacy = store.get_run(legacy.run_id)
        assert loaded_legacy.target_column is None
        assert loaded_legacy.target_column_source is None

    def test_events_order_payload_and_unicode(self, pg_conn, store):
        run = _seed_run()
        store.upsert_run(run)
        payloads = [
            {"name": "demo_sales.csv (демо-датасет)", "rows": 120, "columns": 5},
            {"nested": {"deep": [1, 2, 3]}, "unit": "мин"},
            {},  # N-2: run-level событие с node_id=None и пустым payload
        ]
        types = ["upload_completed", "correction_applied", "run_paused"]
        nodes = ["structure_confirmed", "data_types", None]
        for i, (etype, payload, node) in enumerate(zip(types, payloads, nodes)):
            event = make_trace_event(
                etype,
                stage="upload" if i == 0 else "validation",
                node_id=node,
                run_id=run.run_id,
                **payload,
            )
            store.append_event(run.run_id, event)
        events = store.list_events(run.run_id)
        assert [e.event_type for e in events] == types
        assert [e.node_id for e in events] == nodes  # N-2: None не теряется
        assert events[0].payload["name"] == "demo_sales.csv (демо-датасет)"
        assert events[1].payload["nested"] == {"deep": [1, 2, 3]}
        assert events[1].payload["unit"] == "мин"
        # get_event -- по идентификатору (контракт чекпоинтов §5.1)
        assert store.get_event(run.run_id, events[1].event_id) is not None
        assert store.get_event(run.run_id, "missing") is None

    def test_duplicate_event_not_duplicated(self, pg_conn, store):
        """ON CONFLICT (run_id, event_id) DO NOTHING: повторная запись
        того же события не создаёт дубль (append-only журнал §5)."""
        run = _seed_run()
        store.upsert_run(run)
        event = make_trace_event(
            "upload_completed", stage="upload", node_id="structure_confirmed",
            run_id=run.run_id, name="x.csv",
        )
        store.append_event(run.run_id, event)
        store.append_event(run.run_id, event)
        assert len(store.list_events(run.run_id)) == 1

    def test_status_lifecycle_and_supersede(self, pg_conn, store):
        first = _seed_run("RUN-PGTEST02", session_id="sess-super")
        store.upsert_run(first)
        store.set_run_status(first.run_id, "paused")
        assert store.get_run(first.run_id).status == "paused"
        store.set_run_status(first.run_id, "active")

        # Новый датасет той же сессии: прежний запуск -- abandoned (§3.1)
        second = _seed_run("RUN-PGTEST03", session_id="sess-super")
        store.upsert_run(second)
        store.supersede_active_runs("sess-super", keep_run_id=second.run_id)
        assert store.get_run(first.run_id).status == "abandoned"
        assert store.get_run(second.run_id).status == "active"

    def test_checkpoints_roundtrip(self, pg_conn, store):
        run = _seed_run()
        store.upsert_run(run)
        event = make_trace_event(
            "upload_completed", stage="upload", node_id="structure_confirmed",
            run_id=run.run_id,
        )
        store.append_event(run.run_id, event)
        # PROGR-AUDIT-8 (план §14, контракт v1.2-8A §22): metadata
        # СОЗДАНИЯ снимка -- паритет I8 обоих хранилищ (миграция 0004).
        checkpoint = ResearchCheckpoint(
            checkpoint_id="cp-pg-1",
            run_id=run.run_id,
            event_id=event.event_id,
            label="Перед агрессивным сглаживанием",
            has_snapshot=True,
            context_id="ctx-roundtrip01",
            data_revision=2,
            watermark=7,
        )
        store.add_checkpoint(run.run_id, checkpoint)
        loaded = store.list_checkpoints(run.run_id)
        assert len(loaded) == 1
        assert loaded[0].checkpoint_id == "cp-pg-1"
        assert loaded[0].event_id == event.event_id
        assert loaded[0].label == "Перед агрессивным сглаживанием"
        assert loaded[0].has_snapshot is True
        # AUDIT-8: metadata создания на живом PG (roundtrip, I8).
        assert loaded[0].context_id == "ctx-roundtrip01"
        assert loaded[0].data_revision == 2
        assert loaded[0].watermark == 7

    def test_checkpoints_legacy_row_without_metadata(self, pg_conn, store):
        """Легаси-строка до миграции 0004 (NULL в новых колонках):
        читается с честным отсутствием, не 500 (§3.7, щит C-CERT)."""
        run = _seed_run("RUN-PGLEG01")
        store.upsert_run(run)
        event = make_trace_event(
            "upload_completed", stage="upload", node_id="structure_confirmed",
            run_id=run.run_id,
        )
        store.append_event(run.run_id, event)
        with pg_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO run_checkpoints (checkpoint_id, run_id, event_id, label) "
                "VALUES ('cp-legacy-1', %s, %s, 'легаси')",
                (run.run_id, event.event_id),
            )
        pg_conn.commit()
        loaded = store.list_checkpoints(run.run_id)
        assert len(loaded) == 1
        assert loaded[0].checkpoint_id == "cp-legacy-1"
        assert loaded[0].context_id is None
        assert loaded[0].data_revision is None
        assert loaded[0].watermark is None

    def test_foreign_key_cascade(self, pg_conn):
        """DDL-гарантия §12 п.1: события/чекпоинты не переживают запуск
        (ON DELETE CASCADE) -- сервер принуждает, не приложение."""
        with pg_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO research_runs (run_id) VALUES ('RUN-CASC01')"
            )
            cur.execute(
                "INSERT INTO trace_events (event_id, run_id, ts, stage, node_id, "
                "event_type) VALUES ('ev-1', 'RUN-CASC01', now(), 'upload', NULL, "
                "'upload_completed')"
            )
            cur.execute(
                "INSERT INTO run_checkpoints (checkpoint_id, run_id, event_id) "
                "VALUES ('cp-1', 'RUN-CASC01', 'ev-1')"
            )
            cur.execute("DELETE FROM research_runs WHERE run_id = 'RUN-CASC01'")
        pg_conn.commit()
        with pg_conn.cursor() as cur:
            assert cur.execute(
                "SELECT COUNT(*) FROM trace_events WHERE run_id = 'RUN-CASC01'"
            ).fetchone()[0] == 0
            assert cur.execute(
                "SELECT COUNT(*) FROM run_checkpoints WHERE run_id = 'RUN-CASC01'"
            ).fetchone()[0] == 0

    def test_unique_run_event_enforced_by_server(self, pg_conn):
        """UNIQUE (run_id, event_id) -- гарантия сервера (§12 п.1), а не
        только ON CONFLICT приложения: сырая вставка дубля падает.
        Базовая пара -- зафиксирована: после UniqueViolation/rollback
        проверяемый факт не зависит от состояния транзакции."""
        with pg_conn.cursor() as cur:
            cur.execute("INSERT INTO research_runs (run_id) VALUES ('RUN-UNIQ01')")
            cur.execute(
                "INSERT INTO trace_events (event_id, run_id, ts, stage, node_id, "
                "event_type) VALUES ('dup-1', 'RUN-UNIQ01', now(), 'upload', NULL, "
                "'upload_completed')"
            )
        pg_conn.commit()
        with pytest.raises(psycopg.errors.UniqueViolation):
            with pg_conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO trace_events (event_id, run_id, ts, stage, "
                    "node_id, event_type) VALUES ('dup-1', 'RUN-UNIQ01', now(), "
                    "'upload', NULL, 'upload_completed')"
                )
            pg_conn.commit()

    def test_unique_commit_seq_enforced_by_server(self, pg_conn):
        """AUDIT-6A: уникальность позиции ledger (run_id, commit_seq) --
        гарантия сервера (частичный уникальный индекс по НЕ-NULL позициям;
        legacy-строки с NULL не участвуют)."""
        with pg_conn.cursor() as cur:
            cur.execute("INSERT INTO research_runs (run_id) VALUES ('RUN-SEQUNIQ')")
            cur.execute(
                "INSERT INTO trace_events (event_id, run_id, ts, stage, event_type, "
                "commit_seq) VALUES ('s1', 'RUN-SEQUNIQ', now(), 'upload', "
                "'upload_completed', 1)"
            )
        pg_conn.commit()
        with pytest.raises(psycopg.errors.UniqueViolation):
            with pg_conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO trace_events (event_id, run_id, ts, stage, "
                    "event_type, commit_seq) VALUES ('s2', 'RUN-SEQUNIQ', now(), "
                    "'upload', 'upload_completed', 1)"
                )
            pg_conn.commit()
        # Откат ожидаемого нарушения: последующие проверки -- вне
        # абортированной транзакции (паттерн «базовая пара зафиксирована»).
        pg_conn.rollback()
        # NULL-позиции (legacy) -- не конкурируют.
        with pg_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trace_events (event_id, run_id, ts, stage, "
                "event_type) VALUES ('legacy-1', 'RUN-SEQUNIQ', now(), 'upload', "
                "'upload_completed')"
            )
        pg_conn.commit()


# ── Контур 4-6A: атомарный ledger на живой БД (AUDIT-6A) ──────────────


class TestAudit6ABatchLive:
    """Атомарный ledger (план §7) на ЖИВОМ Postgres: rollback атомарен,
    receipt идемпотентен, watermark непрерывен, конкурентные батчи
    сериализованы (Донастройка_2 п.1: mock-SQL не замена)."""

    def _store(self) -> PostgresResearchRunStore:
        return PostgresResearchRunStore(dsn=DSN)

    def _events(self, run_id: str, count: int, tag: str) -> tuple:
        from apps.api.research_runs import batch_body_fingerprint

        events = tuple(
            make_trace_event(
                "upload_stop_status", stage="upload",
                node_id="structure_confirmed", run_id=run_id,
                tag=tag, idx=i,
            )
            for i in range(count)
        )
        return events

    def test_batch_commit_receipt_and_watermark(self, store):
        from apps.api.research_runs import CommitEventBatch, batch_body_fingerprint

        run = _seed_run("RUN-BATCH6A")
        store.upsert_run(run)
        events = self._events(run.run_id, 3, "a")
        receipt = store.commit_event_batch(
            CommitEventBatch(
                run=run, events=events, idempotency_key="op-live-1",
                body_fingerprint=batch_body_fingerprint(run.run_id, events),
            )
        )
        assert receipt.committed_watermark == 3
        assert len(receipt.accepted_event_ids) == 3
        # Строки несут транзакционную позицию ledger.
        with psycopg.connect(DSN) as conn:
            seqs = [
                r[0]
                for r in conn.execute(
                    "SELECT commit_seq FROM trace_events WHERE run_id = %s "
                    "ORDER BY commit_seq",
                    (run.run_id,),
                ).fetchall()
            ]
        assert seqs == [1, 2, 3]
        # Receipt читается отдельным API (потерянный ответ).
        assert store.get_commit_receipt("op-live-1") == receipt

    def test_retry_same_key_no_duplicates(self, store):
        from apps.api.research_runs import (
            CommitConflictError,
            CommitEventBatch,
            IdempotencyConflictError,
            batch_body_fingerprint,
        )

        run = _seed_run("RUN-RETRY6A", context_id="ctx-base")
        store.upsert_run(run)
        events = self._events(run.run_id, 2, "a")
        batch = CommitEventBatch(
            run=run, events=events, idempotency_key="op-live-2",
            body_fingerprint=batch_body_fingerprint(run.run_id, events),
        )
        first = store.commit_event_batch(batch)
        second = store.commit_event_batch(batch)  # потерянный receipt
        assert second == first
        assert len(store.list_events(run.run_id)) == 2
        # Тот же ключ, другое тело -- конфликт без записи.
        other = self._events(run.run_id, 1, "other")
        with pytest.raises(IdempotencyConflictError):
            store.commit_event_batch(
                CommitEventBatch(
                    run=run, events=other, idempotency_key="op-live-2",
                    body_fingerprint=batch_body_fingerprint(run.run_id, other),
                )
            )
        assert len(store.list_events(run.run_id)) == 2
        # Stale context -- конфликт ДО записи (I3).
        with pytest.raises(CommitConflictError):
            store.commit_event_batch(
                CommitEventBatch(
                    run=run, events=self._events(run.run_id, 1, "stale"),
                    expected_context_id="ctx-stale",
                )
            )
        assert len(store.list_events(run.run_id)) == 2

    def test_mid_batch_failure_atomic_rollback(self, store, monkeypatch):
        """Падение на середине батча -- ROLLBACK живой транзакции: ноль
        событий, прежние метаданные (P08/P10 на настоящей БД)."""
        from apps.api import research_runs as rr

        run = _seed_run("RUN-ATOM6A")
        store.upsert_run(run)
        events = self._events(run.run_id, 3, "a")
        original = rr.PostgresResearchRunStore._prepare_stored_event
        calls = {"n": 0}

        def failing(self, event, seq):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("injected")
            return original(self, event, seq)

        monkeypatch.setattr(
            rr.PostgresResearchRunStore, "_prepare_stored_event", failing
        )
        with pytest.raises(RuntimeError, match="injected"):
            store.commit_event_batch(
                rr.CommitEventBatch(
                    run=replace(run, target_column="sales"), events=events
                )
            )
        # Ноль событий + прежние метаданные (rollback атомарен).
        assert store.list_events(run.run_id) == []
        assert store.get_run(run.run_id).target_column is None
        # Повтор (транзиентный отказ прошёл) -- полный батч с 1.
        receipt = store.commit_event_batch(
            rr.CommitEventBatch(run=run, events=events)
        )
        assert receipt.committed_watermark == 3

    def test_concurrent_batches_contiguous_sequence(self, store):
        """Два конкурентных батча одного запуска -- непрерывный префикс
        1..N без дублей и дыр (сериализация по run: FOR UPDATE)."""
        from concurrent.futures import ThreadPoolExecutor

        from apps.api.research_runs import CommitEventBatch, batch_body_fingerprint

        run = _seed_run("RUN-CONC6A")
        store.upsert_run(run)

        def commit(tag: str):
            events = self._events(run.run_id, 5, tag)
            return store.commit_event_batch(
                CommitEventBatch(
                    run=run, events=events, idempotency_key=f"conc-{tag}",
                    body_fingerprint=batch_body_fingerprint(run.run_id, events),
                )
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            receipts = list(pool.map(commit, ("A", "B")))
        with psycopg.connect(DSN) as conn:
            seqs = [
                r[0]
                for r in conn.execute(
                    "SELECT commit_seq FROM trace_events WHERE run_id = %s",
                    (run.run_id,),
                ).fetchall()
            ]
        assert sorted(seqs) == list(range(1, 11))
        assert len({r.committed_watermark for r in receipts}) == 2
        assert max(r.committed_watermark for r in receipts) == 10


# ── Контур 6: REST-смоук на Postgres-бэкенде ──────────────────────────


@pytest.fixture()
def pg_rest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """API с долговременным слоем на живом Postgres: CISSTAT_RUNS_BACKEND
    =postgres + DATABASE_URL=DSN; схема -- с нуля перед тестом."""
    monkeypatch.setenv("CISSTAT_TEST_PG_DSN", DSN)  # фиксация контекста прогона
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", DSN)
    reset_session_store_for_testing()
    from apps.api import research_runs

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()

    conn = _fresh_schema()
    conn.close()

    with TestClient(app) as test_client:
        yield test_client

    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()


class TestRestSmokeOnPostgres:
    def test_end_to_end_pause_checkpoint_resume(self, pg_rest: TestClient):
        """Сквозной сценарий панели (PROGR-5.1): demo-загрузка -> запуск
        в Postgres -> «Пауза» -> «Сохранить точку» -> «Продолжить».
        Всё персистентно в живой БД, не в Memory."""
        demo = pg_rest.post("/v1/session/demo")
        assert demo.status_code == 200

        # Запуск создан в Postgres зеркалом хука (§5)
        run_id = get_session_store().get(
            pg_rest.cookies.get(SESSION_COOKIE_NAME)
        ).run_id
        with psycopg.connect(DSN) as conn:
            row = conn.execute(
                "SELECT status, dataset_name FROM research_runs WHERE run_id = %s",
                (run_id,),
            ).fetchone()
        assert row is not None
        assert row[0] == "active"
        assert row[1] == "demo_sales.csv (демо-датасет)"

        # «Пауза» (§5.2): статус в Postgres + событие run_paused
        paused = pg_rest.post(f"/v1/progress/runs/{run_id}/pause")
        assert paused.status_code == 200
        assert paused.json()["status"] == "paused"
        with psycopg.connect(DSN) as conn:
            status = conn.execute(
                "SELECT status FROM research_runs WHERE run_id = %s", (run_id,)
            ).fetchone()[0]
            event_types = [
                r[0]
                for r in conn.execute(
                    "SELECT event_type FROM trace_events WHERE run_id = %s ORDER BY seq",
                    (run_id,),
                ).fetchall()
            ]
        assert status == "paused"
        assert event_types[-1] == "run_paused"

        # «Сохранить точку» (§5.1): якорь -- последнее событие запуска
        detail = pg_rest.get(f"/v1/progress/runs/{run_id}").json()
        last_event_id = detail["events"][-1]["event_id"]
        created = pg_rest.post(
            f"/v1/progress/runs/{run_id}/checkpoints",
            json={"event_id": last_event_id, "label": "Перед экспериментом"},
        )
        assert created.status_code == 201
        checkpoint = created.json()["checkpoint"]
        assert checkpoint["label"] == "Перед экспериментом"
        with psycopg.connect(DSN) as conn:
            cp_row = conn.execute(
                "SELECT label, has_snapshot FROM run_checkpoints "
                "WHERE checkpoint_id = %s",
                (checkpoint["checkpoint_id"],),
            ).fetchone()
        assert cp_row == ("Перед экспериментом", True)  # снимок сессии запуска

        # «Продолжить» (§5.2)
        resumed = pg_rest.post(f"/v1/progress/runs/{run_id}/resume")
        assert resumed.status_code == 200
        with psycopg.connect(DSN) as conn:
            status = conn.execute(
                "SELECT status FROM research_runs WHERE run_id = %s", (run_id,)
            ).fetchone()[0]
        assert status == "active"

        # Чекпоинт виден в детали запуска (источник полосы действий фронтенда)
        detail_after = pg_rest.get(f"/v1/progress/runs/{run_id}").json()
        assert len(detail_after["checkpoints"]) == 1
        assert detail_after["status"] == "active"

    def test_double_pause_conflict_from_real_status(self, pg_rest: TestClient):
        """Двойная пауза -- 409: статус читается из живого Postgres,
        не из состояния процесса."""
        pg_rest.post("/v1/session/demo")
        run_id = get_session_store().get(
            pg_rest.cookies.get(SESSION_COOKIE_NAME)
        ).run_id
        assert pg_rest.post(f"/v1/progress/runs/{run_id}/pause").status_code == 200
        second = pg_rest.post(f"/v1/progress/runs/{run_id}/pause")
        assert second.status_code == 409
        assert "paused" in second.json()["detail"]
