-- DOCLOG-2 (spec_documentation_logging.md §10, §8.1, §19, AC02/AC09):
-- ReportSnapshot -- metadata tables durable-слоя. Файл-дубль каталога
-- MIGRATION_STATEMENTS_0008 (apps/api/research_runs.py); паритет
-- источников DDL страхуется тестами (паттерн 0007). Аддитивная
-- миграция: таблицы новые, legacy-корпус без снимков остаётся
-- читаемым (читатели раньше писателей). Байты снимка -- в object
-- store (content-addressed), метаданные -- здесь.

CREATE TABLE IF NOT EXISTS report_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL DEFAULT 'doclog.report_snapshot/1',
    kinds JSONB NOT NULL DEFAULT '[]'::jsonb,
    template_id TEXT NOT NULL DEFAULT 'research-report',
    template_version TEXT NOT NULL DEFAULT '1.0',
    locale TEXT NOT NULL DEFAULT 'ru-RU',
    display_timezone TEXT NOT NULL DEFAULT 'Europe/Moscow',
    classification TEXT NOT NULL DEFAULT 'private',
    redaction_profile TEXT NOT NULL DEFAULT 'owner-v1',
    knowledge_version TEXT,
    cutoff_last_sequence BIGINT NOT NULL DEFAULT 0,
    cutoff_event_count BIGINT NOT NULL DEFAULT 0,
    ordering_quality TEXT NOT NULL DEFAULT 'canonical',
    context_id TEXT,
    data_revision BIGINT,
    data_ref TEXT,
    data_digest_algorithm TEXT,
    data_digest_value TEXT,
    payload_sha256 TEXT NOT NULL DEFAULT '',
    size_bytes BIGINT NOT NULL DEFAULT 0,
    storage_key TEXT NOT NULL DEFAULT '',
    completeness_status TEXT NOT NULL DEFAULT 'partial',
    completeness_missing_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    reproducibility_status TEXT NOT NULL DEFAULT 'limited',
    reproducibility_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    dependencies JSONB NOT NULL DEFAULT '[]'::jsonb,
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL DEFAULT '',
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_report_snapshots_run
ON report_snapshots (run_id, created_at);

-- Dependency manifest снимка (§10.2 п.4): ref_kind artifact|checkpoint|
-- event; ПРИЧИНА ссылки (§16: «metadata graph хранит причины ссылок»).
CREATE TABLE IF NOT EXISTS report_snapshot_dependencies (
    dep_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES report_snapshots(snapshot_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    ref_kind TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    UNIQUE (snapshot_id, ref_kind, ref_id)
);

CREATE INDEX IF NOT EXISTS idx_report_snapshot_deps_snapshot
ON report_snapshot_dependencies (snapshot_id);
