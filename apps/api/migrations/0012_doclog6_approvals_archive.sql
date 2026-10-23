-- Migration 0012: DOCLOG-6 -- согласование и архив
-- (spec_documentation_logging.md §11, §16, §17, §19 строка DOCLOG-6).
-- АДДИТИВНАЯ (§19: «миграции аддитивные; reader появляется раньше
-- writer»): таблицы lifecycle-контура поверх документов DOCLOG-4,
-- никакого переписывания существующих таблиц.
--
-- document_approvals: согласование, СВЯЗАННОЕ ТОЧНОЙ ревизией И хэшем
--   снимка (§9.1/AC07: approval bound hash); approval_manifest --
--   [{rendition_id, format, content_sha256}] утверждённых визуальных
--   форм на момент согласования. Append-only: записи не переписываются.
-- document_lifecycle: append-only записи оси содержания (§11):
--   approval_requested/approved/rejected/published/retracted/superseded;
--   состояние ревизии ВЫЧИСЛЯЕТСЯ из упорядоченных записей.
-- document_retention: hold/приоритет очистки (§16.1); hold -- приоритет
--   над sweep, published не очищается.
--
-- FK ON DELETE CASCADE -- паритет 0010: lifecycle-слой не переживает
-- удаление документов/запусков.

CREATE TABLE IF NOT EXISTS document_approvals (
    approval_id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL REFERENCES document_revisions(revision_id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    decision TEXT NOT NULL,
    actor_subject TEXT NOT NULL DEFAULT '',
    actor_via TEXT NOT NULL DEFAULT '',
    tenant_id TEXT,
    policy TEXT NOT NULL DEFAULT 'single',
    policy_version TEXT NOT NULL DEFAULT 'doclog6-approval-policy-v1',
    reason TEXT NOT NULL DEFAULT '',
    snapshot_payload_sha256 TEXT NOT NULL DEFAULT '',
    approval_manifest JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_document_approvals_revision
ON document_approvals (revision_id, created_at);

CREATE TABLE IF NOT EXISTS document_lifecycle (
    record_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    revision_id TEXT NOT NULL REFERENCES document_revisions(revision_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    event TEXT NOT NULL,
    actor_subject TEXT,
    reason TEXT NOT NULL DEFAULT '',
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_document_lifecycle_revision
ON document_lifecycle (revision_id, created_at);

CREATE INDEX IF NOT EXISTS idx_document_lifecycle_document
ON document_lifecycle (document_id);

CREATE TABLE IF NOT EXISTS document_retention (
    document_id TEXT PRIMARY KEY REFERENCES documents(document_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    hold BOOLEAN NOT NULL DEFAULT FALSE,
    hold_reason TEXT NOT NULL DEFAULT '',
    updated_by TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_document_retention_run
ON document_retention (run_id);
