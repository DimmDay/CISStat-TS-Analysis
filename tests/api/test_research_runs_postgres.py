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

MIGRATIONS_FILE = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "api"
    / "migrations"
    / "0001_research_runs.sql"
)

EXPECTED_TABLES = {"research_runs", "trace_events", "run_checkpoints"}
EXPECTED_INDEXES = {
    "idx_trace_events_run_seq",
    "idx_research_runs_session",
    "idx_research_runs_status",
}

DROP_SCHEMA_SQL = """
DROP TABLE IF EXISTS run_checkpoints CASCADE;
DROP TABLE IF EXISTS trace_events CASCADE;
DROP TABLE IF EXISTS research_runs CASCADE;
"""


def _apply_sql_file(conn) -> None:
    """Прогон DDL-ФАЙЛА ops-контуром: простой протокол (без параметров)
    исполняет весь файл целиком -- ровно как psql -f."""
    with conn.cursor() as cur:
        cur.execute(MIGRATIONS_FILE.read_text(encoding="utf-8"))
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


def _seed_run(run_id: str = "RUN-PGTEST01", session_id: str = "sess-pg") -> ResearchRun:
    return ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="a" * 64,
        dataset_name="demo_sales.csv (демо-датасет)",
        target_column=None,
        created_at=_now_iso(),
        last_active_at=_now_iso(),
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
        источников ловится на живом сервере, а не только сравнением текстов."""
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
        checkpoint = ResearchCheckpoint(
            checkpoint_id="cp-pg-1",
            run_id=run.run_id,
            event_id=event.event_id,
            label="Перед агрессивным сглаживанием",
        )
        store.add_checkpoint(run.run_id, checkpoint)
        loaded = store.list_checkpoints(run.run_id)
        assert len(loaded) == 1
        assert loaded[0].checkpoint_id == "cp-pg-1"
        assert loaded[0].event_id == event.event_id
        assert loaded[0].label == "Перед агрессивным сглаживанием"
        assert loaded[0].has_snapshot is False

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
