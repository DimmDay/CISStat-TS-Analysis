-- apps/api/migrations/0004_audit8_checkpoint_metadata.sql
-- Task AUDIT-8 (plan_progress_audit.md §14): raw restore и checkpoint
-- metadata. АДДИТИВНАЯ миграция -- существующие 0001/0002/0003 НЕ
-- переписываются (план §7; контракт §7 «читатели раньше писателей»:
-- legacy-корпус остаётся читаемым, новая колонка -- честное отсутствие
-- (NULL) для старых строк).
--
-- Канонический источник истины: apps/api/research_runs.py
-- ::MIGRATION_STATEMENTS (run_migrations(conn) исполняет те же
-- утверждения автоматически на первом коннекте; файл -- дубль для
-- ops-контура, рассинхронизация -- находка, сравнение в тестах).
--
-- Состав -- metadata СОЗДАНИЯ снимка чекпоинта (контракт аддендум
-- v1.2-8A §22; чекпоинт связывает снимок с РЕАЛЬНЫМ current контекстом
-- и watermark'ом ЕГО СОЗДАНИЯ; ссылка на event_id -- именованный якорь,
-- НЕ «DataFrame в момент того события»):
--   context_id    -- реальный контекст расчёта сессии в момент
--                    создания снимка (I3; NULL -- снимка нет / сессия
--                    чужая / контекст невычислим: честное отсутствие,
--                    не выдумка);
--   data_revision -- ревизия данных сессии в момент создания;
--   watermark     -- позиция durable-истории запуска (число фактов
--                    ledger слоя 2) на момент создания, ДО факта
--                    checkpoint_saved; позиция привязана к
--                    durable-корпусу, не к волатильному хвосту слоя 1
--                    (P15).
-- NULL -- честное отсутствие (легаси-чекпоинты до миграции, §3.7;
-- чекпоинты без снимка контекстные метаданные не фабрикуют).
-- Паритет Memory-хранилища страхуется контракт-тестами (I8).

ALTER TABLE run_checkpoints ADD COLUMN IF NOT EXISTS context_id TEXT;
ALTER TABLE run_checkpoints ADD COLUMN IF NOT EXISTS data_revision BIGINT;
ALTER TABLE run_checkpoints ADD COLUMN IF NOT EXISTS watermark BIGINT;
