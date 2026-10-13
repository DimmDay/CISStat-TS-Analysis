-- 0005_audit6b_delivery_outbox.sql -- AUDIT-6B (plan_progress_audit.md
-- §17): восстановимая доставка -- durable outbox обязательств доставки
-- проекции слоя 1 в том же устойчивом хранилище, что ledger.
--
-- Регистрируется В транзакции commit_event_batch (контракт
-- docs/progress_audit_contract.md аддендум v1.5-6B §25.2):
--   * crash до commit -- нет ни фактов, ни обязательства (атомарность);
--   * crash после commit -- обязательство переживает потерю
--     процесса/cache, recovery worker доставляет по operation_id.
-- state: pending | delivered | failed (исчерпан бюджет попыток).
-- FK ON DELETE CASCADE -- обязательство живёт вместе с запуском
-- (тот же паттерн, что run_commit_receipts, миграция 0002).
-- Миграция АДДИТИВНАЯ (0001..0004 не переписываются; старый корпус
-- таблицу просто не содержит).

CREATE TABLE IF NOT EXISTS progress_delivery_outbox (
    operation_id TEXT PRIMARY KEY,
    idempotency_key TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    kind TEXT NOT NULL DEFAULT 'layer1_mirror',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    state TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    next_attempt_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_progress_delivery_outbox_due
    ON progress_delivery_outbox (state, next_attempt_at);

CREATE INDEX IF NOT EXISTS idx_progress_delivery_outbox_run
    ON progress_delivery_outbox (run_id);
