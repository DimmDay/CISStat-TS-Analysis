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
