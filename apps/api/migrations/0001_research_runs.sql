-- apps/api/migrations/0001_research_runs.sql
-- Task PROGR-5: долговременный слой «Прогресса» (spec_progress.md §5
-- слой 2, §12 п.1). Идемпотентный DDL -- канонический источник истины
-- apps/api/research_runs.py::MIGRATION_STATEMENTS (run_migrations(conn)
-- исполняет те же утверждения автоматически на первом коннекте); файл
-- существует для ops-контура (review перед ручным прогоном на on-prem
-- Postgres), рассинхронизация файла и Python-констант -- находка для
-- сертификации (сравнение текстов в tests/api/test_research_runs.py).

CREATE TABLE IF NOT EXISTS research_runs (
    run_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT '',
    dataset_fingerprint TEXT NOT NULL DEFAULT '',
    dataset_name TEXT NOT NULL DEFAULT '',
    target_column TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS trace_events (
    seq BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    stage TEXT NOT NULL,
    node_id TEXT,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor TEXT NOT NULL DEFAULT 'user',
    UNIQUE (run_id, event_id)
);

CREATE TABLE IF NOT EXISTS run_checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    event_id TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    has_snapshot BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_trace_events_run_seq ON trace_events (run_id, seq);
CREATE INDEX IF NOT EXISTS idx_research_runs_session ON research_runs (session_id);
CREATE INDEX IF NOT EXISTS idx_research_runs_status ON research_runs (status);

-- PROGR-8 (spec_progress.md §10): журнал наблюдений Наставника.
-- Append-only телеметрия срабатываний правил §7.1 (next_step) и
-- §7.2 (sanity_warning) для агрегатов Admin-панели. БЕЗ FK на
-- research_runs: телеметрия переживает удаление запуска, агрегаты
-- частот корпусные (дубль MIGRATION_STATEMENTS research_runs.py).
CREATE TABLE IF NOT EXISTS mentor_observations (
    seq BIGSERIAL PRIMARY KEY,
    obs_id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    obs_kind TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    node_id TEXT,
    severity TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_mentor_observations_run ON mentor_observations (run_id, seq);
CREATE INDEX IF NOT EXISTS idx_mentor_observations_rule ON mentor_observations (obs_kind, rule_id);
