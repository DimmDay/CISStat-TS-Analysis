-- Migration 0018: PGV-09-FIX -- печатные rendition-ключи
-- (docs/cert_pgv09_2026-10-30.md, находка F-P9C1; recovery-план акта
-- §7 п.2). Файл-дубль каталога MIGRATION_STATEMENTS_0018
-- (apps/api/research_runs.py); паритет источников DDL страхуется
-- тестами (паттерн PROGR-5.1). АДДИТИВНАЯ миграция (§19): только
-- DROP NOT NULL; никакого переписывания таблиц/данных DOCLOG-4/
-- PGV-2/PGV-09.
--
-- document_renditions.revision_id: печатная rendition (PGV-09) не
-- имеет строки в document_revisions -- её цель живёт в
-- document_print_revisions (0016) и связана колонкой
-- print_revision_id с FK (0017). Прежний NOT NULL (0010) вынуждал
-- write-путь PGV-09 писать в revision_id идентификатор печатной
-- ревизии (dprint-...) -- FK document_renditions.revision_id ->
-- document_revisions нарушался с первой же печатной rendition на
-- Postgres-бэкенде. DROP NOT NULL снимает запрет; FK СОХРАНЯЕТСЯ --
-- NULL проходит проверку внешнего ключа (паритет комментария 0017
-- для snapshot_id), legacy-корпус D01-D12 (snapshot-путь, реально
-- существующие revision_id) остаётся защищён. Адаптер
-- (PostgresDocumentRegistry) пишет печатные ключи NULL'ом
-- (_pg_nullable_text) и читает NULL как пустой маркер.
--
-- Согласованность: document_jobs.snapshot_id / document_renditions.
-- snapshot_id -- NOT NULL снят 0017; document_jobs.revision_id не
-- имеет FK (0010) и не требует изменения.

ALTER TABLE document_renditions
    ALTER COLUMN revision_id DROP NOT NULL;
