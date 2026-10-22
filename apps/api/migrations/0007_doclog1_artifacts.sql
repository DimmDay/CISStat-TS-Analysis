-- DOCLOG-1 (spec_documentation_logging.md §9.1, §16, §19, AC04/AC08/AC09):
-- устойчивые артефакты -- metadata tables durable-слоя. Файл-дубль
-- каталога MIGRATION_STATEMENTS_0007 (apps/api/research_runs.py);
-- паритет источников DDL страхуется тестами (паттерн PROGR-5.1).
-- Аддитивная миграция: таблицы новые, legacy-корпус без артефактов
-- остаётся читаемым (читатели раньше писателей).

CREATE TABLE IF NOT EXISTS research_artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'doclog.artifact/1',
    producer_key TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'application/json',
    size_bytes BIGINT NOT NULL DEFAULT 0,
    payload_sha256 TEXT NOT NULL DEFAULT '',
    data_digest_algorithm TEXT,
    data_digest_value TEXT,
    source_bytes_sha256 TEXT,
    storage_key TEXT NOT NULL DEFAULT '',
    context_id TEXT,
    data_revision BIGINT,
    input_kind TEXT,
    panel JSONB,
    dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
    refs JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, producer_key)
);

CREATE INDEX IF NOT EXISTS idx_research_artifacts_run
ON research_artifacts (run_id, kind);

-- Pins: защита зависимостей независимо от keeper «последних пяти»
-- checkpoint (AC04/T11); идемпотентные пины с ПРИЧИНОЙ (§16:
-- «metadata graph хранит причины ссылок»). ref_kind: checkpoint |
-- artifact; unpin -- отдельное действие.
CREATE TABLE IF NOT EXISTS research_artifact_pins (
    pin_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    ref_kind TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, ref_kind, ref_id)
);

CREATE INDEX IF NOT EXISTS idx_research_artifact_pins_run
ON research_artifact_pins (run_id, ref_kind);
