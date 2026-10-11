-- apps/api/migrations/0002_audit6a_atomic_ledger.sql
-- Task AUDIT-6A (plan_progress_audit.md §7): атомарный ledger «Прогресса»
-- и одинаковые store-контракты. АДДИТИВНАЯ миграция -- существующая
-- 0001_research_runs.sql НЕ переписывается (план §7; контракт §7
-- «читатели раньше писателей»: legacy-корпус остаётся читаемым, новые
-- колонки -- честное отсутствие для старых строк).
--
-- Канонический источник истины: apps/api/research_runs.py
-- ::MIGRATION_STATEMENTS (run_migrations(conn) исполняет те же
-- утверждения автоматически на первом коннекте; файл -- дубль для
-- ops-контура, рассинхронизация -- находка, сравнение в тестах).
--
-- Состав:
--   1. run-метаданные контекста расчёта (граница AUDIT-C, контракт
--      §14.5 «durable-хранение ... run-метаданных ревизии -- миграция
--      AUDIT-6A»): context_id/data_revision/data_digest. NULL --
--      честное отсутствие (старый корпус, §3.7).
--   2. Durable envelope v2 слоя 2 (та же граница AUDIT-C): поля
--      schema_version/evidence_level/operation_id/causation_id/
--      context_id/result_ref/method/time_quality на trace_events.
--   3. commit_seq -- авторитетная позиция ledger (контракт §3.3
--      УТВЕРЖДЕНО-AUDIT-0): назначается store'ом ТРАНЗАКЦИОННО с
--      сериализацией по run (SELECT ... FOR UPDATE на строку запуска),
--      поэтому НЕ BIGSERIAL: серийный счётчик не удостоверяет порядок
--      commit конкурентных транзакций и не гарантирует непрерывный
--      committed prefix (план §7 п.3). NULL у legacy-строк -- стабильный
--      исходный store-order (столбец seq 0001).
--   4. run_commit_receipts -- receipts атомарных батчей (план §7 п.4):
--      idempotency key (PK), run/context, принятые event ids, committed
--      watermark, отпечаток тела (детекция «тот же ключ с другим телом»).

ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS context_id TEXT;
ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS data_revision BIGINT;
ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS data_digest TEXT;

ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS commit_seq BIGINT;
ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS schema_version INTEGER;
ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS evidence_level TEXT;
ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS operation_id TEXT;
ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS causation_id TEXT;
ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS context_id TEXT;
ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS result_ref JSONB;
ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS method JSONB;
ALTER TABLE trace_events ADD COLUMN IF NOT EXISTS time_quality JSONB;

-- Уникальность позиции ledger в пределах запуска (только назначенные
-- commit_seq; legacy-строки с NULL не участвуют).
CREATE UNIQUE INDEX IF NOT EXISTS uq_trace_events_run_commit_seq
    ON trace_events (run_id, commit_seq) WHERE commit_seq IS NOT NULL;
-- Чтение канонического порядка: legacy-first (NULL), затем commit_seq.
CREATE INDEX IF NOT EXISTS idx_trace_events_run_commit_seq
    ON trace_events (run_id, commit_seq NULLS FIRST, seq);

-- Receipts атомарных батчей. FK ON DELETE CASCADE -- receipts живут
-- вместе с запуском (повтор в удалённый запуск невозможен).
CREATE TABLE IF NOT EXISTS run_commit_receipts (
    idempotency_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    context_id TEXT,
    body_fingerprint TEXT NOT NULL DEFAULT '',
    accepted_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    committed_watermark BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_run_commit_receipts_run
    ON run_commit_receipts (run_id);
