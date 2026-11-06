# tests/api/test_session_store_postgres.py
"""Session backend Postgres (V2.3): behavioral контракт
PostgresSessionStore на РЕАЛЬНОМ Postgres-сервере + миграция 0022.

Затвор средой: модуль выполняется ТОЛЬКО при заданном CISSTAT_TEST_PG_DSN
(DSN доступного Postgres); иначе -- skip на уровне модуля (CI без
Postgres остаётся зелёным, паритет test_research_runs_postgres.py).
Запуск on-prem:

    CISSTAT_TEST_PG_DSN='postgresql://user:pass@host:5432/db' \
        pytest tests/api/test_session_store_postgres.py -v

Доктрина: spec_auth_architecture.md §63 («PostgreSQL -- authoritative
durable store; In-memory только тест/dev, не production fallback»);
кандидат v2.3 из worklog11 (session_backend effective=memory в
/health/ops закрыт).

Контуры:
  1. DDL 0022: таблица analysis_sessions + индекс expires_at;
     идемпотентность повторного прогона.
  2. Поведенческий контракт (паритет Memory/Redis из
     test_session_store.py): get/get_or_create/save/delete, roundtrip
     датасета/DataFrame, optimistic CAS-ревизия.
  3. TTL-семантика Redis-паритета: протухшая строка логически
     отсутствует (get -> None, get_or_create -> свежая сессия), save()
     протухшего снимка -- SessionConflictError (паритет Redis: ключ
     истёк -> current_revision=0 -> конфликт).
  4. Prune-on-save: строки с истёкшим expires_at удаляются сохранением
     активной сессии (паритет авто-expiry Redis).
  5. readiness_probe: SELECT 1 + COUNT(*) с connect_timeout=3.
  6. ensure_schema: первый _connect() на БД без таблицы поднимает схему
     (самомиграция; без обязательного bootstrap-контейнера для 0022).
  7. REST-смоук сквозь TestClient: CISSTAT_SESSION_BACKEND=postgres --
     demo-загрузка пишет сессию в analysis_sessions, /health/ops
     показывает session_backend effective=postgres.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pytest

DSN = os.environ.get("CISSTAT_TEST_PG_DSN", "")
if not DSN:
    pytest.skip(
        "CISSTAT_TEST_PG_DSN не задан -- Postgres-интеграция сессий "
        "пропущена (см. докстринг модуля)",
        allow_module_level=True,
    )

try:
    import psycopg
except ImportError:  # pragma: no cover - среда без драйвера
    pytest.skip(
        "psycopg не установлен -- Postgres-интеграция сессий пропущена",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import (
    AnalysisSession,
    DatasetInfo,
    PostgresSessionStore,
    SessionConflictError,
    get_session_store,
    reset_session_store_for_testing,
    SESSION_COOKIE_NAME,
)
from apps.api.research_runs import MIGRATION_STATEMENTS_0022

TABLE = "analysis_sessions"


def _fresh_session_schema(conn) -> None:
    """Изоляция теста: DROP analysis_sessions + прогон statement'ов 0022
    (idempotent DDL). Остальная ops-схема не трогается."""
    with conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {TABLE} CASCADE")
        for statement in MIGRATION_STATEMENTS_0022:
            cur.execute(statement)
    conn.commit()


@pytest.fixture
def pg_conn():
    conn = psycopg.connect(DSN, autocommit=False)
    _fresh_session_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def store():
    """Свежий PostgresSessionStore на каждый тест (schema_ready сброшен)."""
    return PostgresSessionStore(dsn=DSN)


@pytest.fixture
def sample_dataset_info() -> DatasetInfo:
    return DatasetInfo(
        dataset_id="ds-pg-001",
        name="pg_session.csv",
        rows=10,
        columns=3,
        size_label="1.23 KB",
    )


@pytest.fixture
def sample_dataframe() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=10, freq="D"),
        "value": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5],
        "category": ["A", "B"] * 5,
    })


# ── 1. DDL 0022 ──────────────────────────────────────────────────────


class TestDdl0022:
    def test_table_and_index_created(self, pg_conn):
        names = {
            row[0]
            for row in pg_conn.execute(
                "SELECT tablename FROM pg_tables WHERE tablename=%s", (TABLE,)
            ).fetchall()
        }
        assert TABLE in names
        indexes = {
            row[0]
            for row in pg_conn.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename=%s", (TABLE,)
            ).fetchall()
        }
        assert "idx_analysis_sessions_expires" in indexes

    def test_ddl_idempotent(self, pg_conn):
        # Повторный прогон statement'ов не падает (IF NOT EXISTS).
        with pg_conn.cursor() as cur:
            for statement in MIGRATION_STATEMENTS_0022:
                cur.execute(statement)
        pg_conn.commit()


# ── 2. Поведенческий контракт ────────────────────────────────────────


class TestPostgresStoreBehavior:
    def test_get_returns_none_for_unknown_id(self, store):
        assert store.get("no-such-pg-session") is None

    def test_get_or_create_creates_empty_session(self, store):
        session = store.get_or_create("pg-new-001")
        assert session.session_id == "pg-new-001"
        assert session.dataset is None
        assert all(status == "pending" for status in session.stages.values())
        # Пустая сессия не пишется до первого save() (паритет Redis).
        assert store.get("pg-new-001") is None

    def test_save_get_roundtrip(self, store, sample_dataset_info, sample_dataframe):
        session = store.get_or_create("pg-roundtrip-002")
        session.set_dataset(sample_dataset_info, sample_dataframe)
        session.set_stage("upload", "done")
        store.save(session)
        assert session.storage_revision == 1

        loaded = store.get("pg-roundtrip-002")
        assert loaded is not None
        assert loaded.stages["upload"] == "done"
        assert loaded.dataset is not None
        assert loaded.dataset.name == "pg_session.csv"
        assert loaded.dataframe is not None
        pd.testing.assert_frame_equal(
            loaded.dataframe[["value"]], sample_dataframe[["value"]]
        )
        assert loaded.storage_revision == 1

    def test_save_bumps_revision_monotonically(self, store):
        session = store.get_or_create("pg-rev-003")
        store.save(session)
        rev1 = session.storage_revision
        session.set_stage("validation", "in_progress")
        store.save(session)
        assert session.storage_revision == rev1 + 1

    def test_stale_snapshot_conflicts(self, store):
        session = store.get_or_create("pg-cas-004")
        store.save(session)  # revision 1
        stale = store.get("pg-cas-004")
        session.set_stage("eda", "done")
        store.save(session)  # revision 2 (кто-то опередил)
        with pytest.raises(SessionConflictError):
            stale.set_stage("modeling", "done")
            store.save(stale)  # revision 1 против 2 -- CAS-конфликт

    def test_delete_returns_true_and_removes(self, store, sample_dataset_info):
        session = store.get_or_create("pg-del-005")
        session.set_stage("upload", "done")
        store.save(session)
        assert store.delete("pg-del-005") is True
        assert store.get("pg-del-005") is None
        assert store.delete("pg-del-005") is False


# ── 3. TTL-семантика (паритет Redis) ─────────────────────────────────


class TestTtlSemantics:
    def test_expired_row_is_logically_absent(self, store):
        session = store.get_or_create("pg-ttl-001")
        store.save(session)
        with psycopg.connect(DSN) as conn:
            conn.execute(
                f"UPDATE {TABLE} SET expires_at = now() - interval '1 second' "
                "WHERE session_id = %s",
                ("pg-ttl-001",),
            )
            conn.commit()
        assert store.get("pg-ttl-001") is None
        fresh = store.get_or_create("pg-ttl-001")
        assert fresh.storage_revision == 0
        assert fresh.stages["upload"] == "pending"

    def test_save_of_stale_expired_snapshot_conflicts(self, store):
        """Протухшая строка не может быть «свежей»: save() снимка,
        прочитанного до истечения TTL, -- SessionConflictError (паритет
        Redis: ключ истёк -> current_revision=0)."""
        session = store.get_or_create("pg-ttl-002")
        session.set_stage("upload", "done")
        store.save(session)  # revision 1
        with psycopg.connect(DSN) as conn:
            conn.execute(
                f"UPDATE {TABLE} SET expires_at = now() - interval '1 second' "
                "WHERE session_id = %s",
                ("pg-ttl-002",),
            )
            conn.commit()
        session.set_stage("validation", "done")
        with pytest.raises(SessionConflictError):
            store.save(session)

    def test_save_sets_sliding_ttl_30_days(self, store):
        session = store.get_or_create("pg-ttl-003")
        store.save(session)
        with psycopg.connect(DSN) as conn:
            row = conn.execute(
                f"SELECT created_at, updated_at, expires_at FROM {TABLE} "
                "WHERE session_id = %s",
                ("pg-ttl-003",),
            ).fetchone()
        ttl_seconds = (row[2] - row[1]).total_seconds()
        assert 60 * 60 * 24 * 30 - 5 <= ttl_seconds <= 60 * 60 * 24 * 30
        assert row[1] >= row[0]

    def test_prune_on_save_removes_expired_rows(self, store):
        for sid in ("pg-prune-a", "pg-prune-b"):
            session = store.get_or_create(sid)
            store.save(session)
        with psycopg.connect(DSN) as conn:
            conn.execute(
                f"UPDATE {TABLE} SET expires_at = now() - interval '1 second' "
                "WHERE session_id IN (%s, %s)",
                ("pg-prune-a", "pg-prune-b"),
            )
            conn.commit()
        # Сохранение АКТИВНОЙ сессии подчищает протухшие (паритет
        # авто-expiry Redis: мёртвые сессии не копятся вечно).
        active = store.get_or_create("pg-prune-active")
        active.set_stage("upload", "done")
        store.save(active)
        with psycopg.connect(DSN) as conn:
            count = conn.execute(
                f"SELECT COUNT(*) FROM {TABLE} WHERE session_id IN (%s, %s)",
                ("pg-prune-a", "pg-prune-b"),
            ).fetchone()[0]
        assert count == 0


# ── 4/5. readiness_probe и ensure_schema ─────────────────────────────


class TestReadinessAndSchema:
    def test_readiness_probe_ok(self, store):
        probe = store.readiness_probe()
        assert probe["ok"] is True
        assert probe["backend"] == "postgres"
        assert "latency_ms" in probe

    def test_probe_never_raises_on_bad_dsn(self):
        broken = PostgresSessionStore(dsn="postgresql://nobody:x@127.0.0.1:1/none")
        probe = broken.readiness_probe()
        assert probe["ok"] is False
        assert probe["backend"] == "postgres"
        assert "error" in probe

    def test_ensure_schema_self_migrates_missing_table(self):
        """Первый _connect() на БД без analysis_sessions сам применяет
        миграцию 0022 (без обязательного bootstrap-контейнера)."""
        with psycopg.connect(DSN) as conn:
            conn.execute(f"DROP TABLE IF EXISTS {TABLE} CASCADE")
            conn.commit()
        store = PostgresSessionStore(dsn=DSN)
        session = store.get_or_create("pg-selfmig-001")
        session.set_stage("upload", "done")
        store.save(session)  # до фикса: UndefinedTable
        assert store.get("pg-selfmig-001").stages["upload"] == "done"


# ── 6. REST-смоук ────────────────────────────────────────────────────


@pytest.fixture
def pg_rest(monkeypatch, tmp_path):
    monkeypatch.setenv("CISSTAT_SESSION_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", DSN)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("CISSTAT_STORAGE_MODE", raising=False)
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    reset_session_store_for_testing()
    with psycopg.connect(DSN) as conn:
        _fresh_session_schema(conn)
    with TestClient(app) as test_client:
        yield test_client
    reset_session_store_for_testing()


class TestRestSmokeOnPostgres:
    def test_demo_session_persists_and_health_reports_postgres(self, pg_rest):
        demo = pg_rest.post("/v1/session/demo")
        assert demo.status_code == 200

        cookie = pg_rest.cookies.get(SESSION_COOKIE_NAME)
        assert cookie
        with psycopg.connect(DSN) as conn:
            row = conn.execute(
                f"SELECT storage_revision, payload->>'run_id' FROM {TABLE} "
                "WHERE session_id = %s",
                (cookie,),
            ).fetchone()
        assert row is not None, "demo-сессия обязана быть в analysis_sessions"
        assert row[0] >= 1
        assert row[1]  # run_id непуст в payload

        # Перезапуск хранилища в процессе (эмуляция рестарта api):
        # сессия переживает -- durable, не memory.
        reset_session_store_for_testing()
        assert get_session_store().get(cookie) is not None

    def test_health_ops_reports_effective_postgres(self, pg_rest):
        pg_rest.post("/v1/session/demo")
        health = pg_rest.get("/health/ops")
        assert health.status_code == 200
        body = health.json()
        state = body["session_backend"]
        assert state["configured"] == "postgres"
        assert state["effective"] == "postgres"
        assert state["degraded"] is False
        readiness = body["readiness"]["session"]
        assert readiness["ok"] is True
        assert readiness["backend"] == "postgres"
