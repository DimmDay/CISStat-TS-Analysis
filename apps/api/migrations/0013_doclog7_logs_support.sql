-- DOCLOG-7 (spec_documentation_logging.md §14.2, §15, §19 строка
-- DOCLOG-7): журналы и поддержка -- support grants. Файл-дубль каталога
-- MIGRATION_STATEMENTS_0013 (apps/api/research_runs.py); паритет
-- источников DDL страхуется тестами (паттерн 0007..0012). АДДИТИВНАЯ
-- миграция: таблица новая, legacy-корпус остаётся читаемым.
--
-- Support grants (§14.2): «Поддержка получает ticket/purpose и
-- ограничение по run/tenant/времени. Разрешён пакет „без данных";
-- для дополнительного доступа -- отдельный grant владельца/
-- уполномоченного лица с TTL и отзывом.»
--
-- FK на research_runs НЕТ НАМЕРЕННО: грант переживает удаление run и
-- журналы его действия не каскадно исчезают; журналы (0009) тоже без FK
-- на run. tenant_id NOT NULL -- fail-closed: ГЛОБАЛЬНЫХ грантов нет
-- (§15: знание run_id не является правом; граница -- tenant/run/time).

CREATE TABLE IF NOT EXISTS support_grants (
    grant_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'doclog.support_grant/1',
    ticket TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT '',
    subject_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    run_id TEXT,
    scopes TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    revoked_by TEXT,
    revoke_reason TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_support_grants_subject
ON support_grants (subject_id, expires_at);

CREATE INDEX IF NOT EXISTS idx_support_grants_tenant
ON support_grants (tenant_id, created_at);

CREATE INDEX IF NOT EXISTS idx_support_grants_ticket
ON support_grants (ticket);
