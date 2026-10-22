-- DOCLOG-3 (spec_documentation_logging.md §13, §14, §19, AC10/AC11):
-- telemetry/audit foundation -- durable-приёмники. Файл-дубль каталога
-- MIGRATION_STATEMENTS_0009 (apps/api/research_runs.py); паритет
-- источников DDL страхуется тестами (паттерн 0007/0008). АДДИТИВНАЯ
-- миграция: таблицы новые, legacy-корпус остаётся читаемым.
--
-- FK на research_runs НЕТ НАМЕРЕННО: telemetry (30 дней) и security
-- audit (365 дней, §16.1) переживают удаление run -- журнал действий
-- не может каскадно исчезнуть вместе с ресурсом.
-- Append-only по построению: INSERT-only контур, изменений/удалений
-- записей код контура не содержит (retention -- §16.1 политика).

CREATE TABLE IF NOT EXISTS telemetry_events (
    event_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'doclog.telemetry/1',
    event_name TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    severity_text TEXT NOT NULL,
    severity_number INTEGER NOT NULL,
    message_template TEXT,
    attributes JSONB,
    service TEXT,
    service_version TEXT,
    environment TEXT,
    instance TEXT,
    request_id TEXT,
    trace_id TEXT,
    span_id TEXT,
    operation_id TEXT,
    execution_id TEXT,
    research_run_id TEXT,
    context_id TEXT,
    subject_surrogate TEXT,
    tenant_id TEXT,
    outcome TEXT,
    method TEXT,
    error_code TEXT,
    error_fingerprint TEXT,
    duration_ms DOUBLE PRECISION,
    retry_attempt INTEGER,
    sampled BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_telemetry_events_time
ON telemetry_events (occurred_at);

CREATE INDEX IF NOT EXISTS idx_telemetry_events_name
ON telemetry_events (event_name, occurred_at);

CREATE INDEX IF NOT EXISTS idx_telemetry_events_request
ON telemetry_events (request_id);

-- Отдельный durable security audit (§14.1): НЕ смешивается с
-- sampling техлогов; обязательные классы пишутся fail-closed (AC11).
CREATE TABLE IF NOT EXISTS security_audit_records (
    audit_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'doclog.security_audit/1',
    occurred_at TIMESTAMPTZ NOT NULL,
    actor_subject TEXT,
    actor_via TEXT NOT NULL DEFAULT 'anonymous',
    tenant_id TEXT,
    action TEXT NOT NULL,
    decision TEXT NOT NULL,
    resource_kind TEXT,
    resource_id TEXT,
    resource_version TEXT,
    policy_basis TEXT,
    request_id TEXT,
    operation_id TEXT,
    run_id TEXT,
    details JSONB,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_security_audit_action
ON security_audit_records (action, occurred_at);

CREATE INDEX IF NOT EXISTS idx_security_audit_tenant
ON security_audit_records (tenant_id, occurred_at);

CREATE INDEX IF NOT EXISTS idx_security_audit_request
ON security_audit_records (request_id);
