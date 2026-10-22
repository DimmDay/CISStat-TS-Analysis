-- apps/api/migrations/0006_doclog0_run_ownership.sql
-- Task DOCLOG-0 (spec_documentation_logging.md §9.1, §15.1, §19):
-- идентичность и контракт -- owner/tenant binding на создание run.
-- АДДИТИВНАЯ миграция -- существующие 0001..0005 НЕ переписываются
-- (план §7; «читатели раньше писателей»: legacy-корпус остаётся
-- читаемым, новая колонка -- честное отсутствие (NULL) для старых
-- строк).
--
-- Канонический источник истины: apps/api/research_runs.py
-- ::MIGRATION_STATEMENTS (run_migrations(conn) исполняет те же
-- утверждения автоматически на первом коннекте; файл -- дубль для
-- ops-контура, рассинхронизация -- находка, сравнение в тестах).
--
-- Состав:
--   owner_subject -- стабильный безопасный ID субъекта-владельца
--   (псевдоним HMAC-SHA256, apps/api/identity.py::subject_pseudonym;
--   НЕ значение API-key/cookie, §15/T4).
--   tenant_id -- серверная граница доверия (R09: query-параметр
--   tenant границей не является; из запроса не читается).
--   ownership -- явное "bound" у запусков, созданных после DOCLOG-0;
--   NULL у legacy -- честное отсутствие: состояние unresolved
--   ВЫЧИСЛЯЕТСЯ резолвером (identity.effective_ownership), данные не
--   переписываются задним числом (§9.2). Привязка легаси-run -- только
--   административная миграция по проверенному реестру с записью
--   основания и audit (§15.1); нельзя назначать владельца тому, кто
--   первым назвал run_id.
--   Индексы owner/tenant -- будущие выборки «запуски субъекта/тенанта»
--   (админ-миграция, support grant) на текущих объёмах не критичны,
--   создаются сразу (дешевле, чем догонять после роста корпуса).
--   Запись: COALESCE(EXCLUDED.x, stored.x) в upsert_run -- батч без
--   owner не стирает привязку (паритет _merge_run_additive Memory).

ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS owner_subject TEXT;
ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS tenant_id TEXT;
ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS ownership TEXT;
CREATE INDEX IF NOT EXISTS idx_research_runs_owner ON research_runs (owner_subject);
CREATE INDEX IF NOT EXISTS idx_research_runs_tenant ON research_runs (tenant_id);
