-- apps/api/migrations/0022_session_backend_postgres.sql
-- V2.3 (2026-11-06): session_backend memory -> Postgres.
--
-- Слой 1 сессии анализа (AnalysisSession, cookie cisstat_session_id)
-- переезжает с in-memory/Redis на PostgreSQL по доктрине durable-контура
-- (spec_auth_architecture.md §63: PostgreSQL -- authoritative durable
-- store; In-memory только тест/dev, не production fallback). Кандидат
-- v2.3 из worklog11 закрыт: /health/ops session_backend effective=
-- postgres в проде (CISSTAT_SESSION_BACKEND=postgres в compose api).
--
-- ДУБЛЬ каталога ops-контура (паттерн PROGR-5.1): statement'ы этой
-- миграции продублированы в apps/api/research_runs.py
-- (MIGRATION_STATEMENTS_0022) и исполняются автоматически первым
-- коннектом любого Postgres-стора через run_migrations(). Эквивалентность
-- источников страхуется тестами (test_session_store.py /
-- test_session_store_postgres.py).
--
-- Модель хранения: ОДНА строка на сессию браузера.
--   session_id        -- cookie cisstat_session_id (uuid4().hex).
--   storage_revision  -- optimistic CAS: save() читает SELECT ... FOR
--                        UPDATE и сравнивает с ожидаемой ревизией
--                        снимка (паритет Redis WatchError ->
--                        SessionConflictError).
--   payload           -- session_to_dict(session) как JSONB
--                        (включая dataframe_json; штамп
--                        session_schema_version=4).
--   created_at/updated_at/expires_at -- скользящий TTL 30 дней
--                        (SESSION_TTL_SECONDS = cookie max_age);
--                        expires_at обновляется каждым save()
--                        (паритет Redis EX при каждом SET); строки с
--                        expires_at <= now() логически отсутствуют и
--                        подчищаются ленивым delete + prune-on-save.

CREATE TABLE IF NOT EXISTS analysis_sessions (
    session_id TEXT PRIMARY KEY,
    storage_revision BIGINT NOT NULL DEFAULT 0,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
)
;

CREATE INDEX IF NOT EXISTS idx_analysis_sessions_expires
ON analysis_sessions (expires_at)
;
