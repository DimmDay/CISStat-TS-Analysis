-- Migration 0017: PGV-09 -- Jobs/PNG renderer integration
-- (spec_passport_graphics_visual.md §4/§10.2/§11/§13, строка PGV-09).
-- Файл-дубль каталога MIGRATION_STATEMENTS_0017
-- (apps/api/research_runs.py); паритет источников DDL страхуется
-- тестами (паттерн PROGR-5.1). АДДИТИВНАЯ миграция (§19: «миграции
-- аддитивные; reader появляется раньше writer»): только ADD COLUMN
-- IF NOT EXISTS / DROP NOT NULL / новые индексы-ограничения; никакого
-- переписывания таблиц/данных DOCLOG-4/DOCLOG-5/PGV-2.
--
-- Печатные jobs/renditions (§10.2: «lifecycle/API -- существующие
-- document jobs/renditions, один job store»): рендер PNG печатной
-- ревизии (V01, basis visual_print_snapshot) живёт в ТЕХ ЖЕ таблицах.
-- snapshot_id печатных записей пуст: печатные ревизии не ссылаются на
-- report snapshot (0016: их basis -- артефакты); DROP NOT NULL
-- снимает запрет вставки, FK на report_snapshots СОХРАНЯЕТСЯ (NULL
-- проходит проверку внешнего ключа; legacy-корпус D01-D12 остаётся
-- защищён).
--
-- document_jobs.print_revision_id / basis_artifact_id -- печатное
--   задание: цель и самодостаточный замороженный вход renderer-
--   контейнера PGV-08 (§4: «Новый worker получает разрешённую PNG job
--   через service interface/lease»).
-- document_renditions.print_revision_id -- печатная rendition;
--   идемпотентность печатной цели -- частичный UNIQUE
--   (print_revision_id, format, redaction_profile): NULL-ключи
--   (snapshot-путь) остаются под прежним UNIQUE(snapshot_id, format,
--   redaction_profile) 0010 (NULLS DISTINCT не смешивает семантики).
-- FK print_revision_id -> document_print_revisions (0016) с
--   ON DELETE CASCADE -- паритет 0010/0016: печатный слой не переживает
--   удаление печатной ревизии/документа; DO $$ IF NOT EXISTS -- форма
--   идемпотентного повторного прогона каталога.

ALTER TABLE document_jobs
    ADD COLUMN IF NOT EXISTS print_revision_id TEXT;

ALTER TABLE document_jobs
    ADD COLUMN IF NOT EXISTS basis_artifact_id TEXT;

ALTER TABLE document_renditions
    ADD COLUMN IF NOT EXISTS print_revision_id TEXT;

ALTER TABLE document_jobs
    ALTER COLUMN snapshot_id DROP NOT NULL;

ALTER TABLE document_renditions
    ALTER COLUMN snapshot_id DROP NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_document_renditions_print
ON document_renditions (print_revision_id, format, redaction_profile)
WHERE print_revision_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_document_jobs_print_revision
ON document_jobs (print_revision_id);

CREATE INDEX IF NOT EXISTS idx_document_renditions_print_revision
ON document_renditions (print_revision_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_document_jobs_print_revision'
    ) THEN
        ALTER TABLE document_jobs
            ADD CONSTRAINT fk_document_jobs_print_revision
            FOREIGN KEY (print_revision_id)
            REFERENCES document_print_revisions(print_revision_id)
            ON DELETE CASCADE;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_document_renditions_print_revision'
    ) THEN
        ALTER TABLE document_renditions
            ADD CONSTRAINT fk_document_renditions_print_revision
            FOREIGN KEY (print_revision_id)
            REFERENCES document_print_revisions(print_revision_id)
            ON DELETE CASCADE;
    END IF;
END $$;
