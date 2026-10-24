-- DOCLOG-8 (spec_documentation_logging.md §6 D12, §6.1, §19 строка
-- DOCLOG-8): мониторинг -- D12 «Сверка прогноза с фактом»: actual
-- vintages (иммутабельные партии факта с датой поступления/единицами,
-- B07), frozen сверки (выравнивание, зрелые горизонты, честные метрики
-- AC12/AC15), append-only решения (§6.1: автопереобучение НЕ следует
-- из порога). Файл-дубль каталога MIGRATION_STATEMENTS_0014
-- (apps/api/research_runs.py); паритет источников DDL страхуется
-- тестами (паттерн 0007..0013). АДДИТИВНАЯ миграция: таблицы новые,
-- legacy-корпус остаётся читаемым (читатели раньше писателей).
--
-- FK на research_runs ЕСТЬ (ON DELETE CASCADE): партии/сверки/решения
-- -- научные данные run (в отличие от журналов 0009 и грантов 0013,
-- которые переживают run намеренно). Прогноз и его артефакт сверка НЕ
-- изменяет (§6 D08: «никогда не заменять старый выпуск новым») --
-- ссылка по forecast_artifact_id без каскада на артефакты.
-- UNIQUE(run_id, idempotency_key) -- идемпотентность §10.3/AC09.

CREATE TABLE IF NOT EXISTS monitoring_actual_batches (
    batch_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL DEFAULT 'doclog.actual_vintage/1',
    target_name TEXT NOT NULL,
    entity_id TEXT,
    units TEXT NOT NULL,
    as_of TIMESTAMPTZ NOT NULL,
    source_kind TEXT NOT NULL DEFAULT 'manual',
    source_ref TEXT,
    notes TEXT NOT NULL DEFAULT '',
    point_count INTEGER NOT NULL DEFAULT 0,
    actual_values JSONB NOT NULL DEFAULT '[]'::jsonb,
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL DEFAULT '',
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_mon_batches_run
ON monitoring_actual_batches (run_id, created_at);

CREATE TABLE IF NOT EXISTS monitoring_comparisons (
    comparison_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL DEFAULT 'doclog.monitoring_comparison/1',
    forecast_artifact_id TEXT NOT NULL,
    forecast_sha256 TEXT NOT NULL DEFAULT '',
    actual_batch_id TEXT NOT NULL REFERENCES monitoring_actual_batches(batch_id) ON DELETE CASCADE,
    target_name TEXT NOT NULL DEFAULT '',
    entity_id TEXT,
    units_check TEXT NOT NULL DEFAULT 'unknown',
    units_note TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ready',
    matured_count INTEGER NOT NULL DEFAULT 0,
    excluded_count INTEGER NOT NULL DEFAULT 0,
    out_of_horizon_count INTEGER NOT NULL DEFAULT 0,
    result JSONB NOT NULL DEFAULT '{}'::jsonb,
    payload_sha256 TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL DEFAULT '',
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_mon_comparisons_run
ON monitoring_comparisons (run_id, created_at);

CREATE INDEX IF NOT EXISTS idx_mon_comparisons_batch
ON monitoring_comparisons (actual_batch_id);

CREATE TABLE IF NOT EXISTS monitoring_decisions (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    comparison_id TEXT NOT NULL REFERENCES monitoring_comparisons(comparison_id) ON DELETE CASCADE,
    schema_version TEXT NOT NULL DEFAULT 'doclog.monitoring_decision/1',
    action TEXT NOT NULL,
    rationale TEXT NOT NULL,
    decided_by TEXT,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_mon_decisions_comparison
ON monitoring_decisions (comparison_id, decided_at);
