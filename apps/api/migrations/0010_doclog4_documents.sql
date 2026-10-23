-- Migration 0010: DOCLOG-4 -- UI и MVP выдачи поверх снимков 2+3
-- (spec_documentation_logging.md §9.1 адаптеры, §10.3, §11, §17, §19
-- строка DOCLOG-4). АДДИТИВНАЯ (reader раньше writer): слой документов
-- -- адаптер НАД существующими report_snapshots (DOCLOG-2), никакого
-- переписывания снимков.
--
-- documents / document_revisions: логический документ (run_id,
-- kind_code) с монотонными версиями; revision 1:1 snapshot
-- (UNIQUE(snapshot_id)) -- непереписываемая ссылка на frozen снимок.
-- document_renditions: готовые форматы (P0 §7) с content-addressed
-- байтами в object store; UNIQUE(snapshot_id, format,
-- redaction_profile) -- идемпотентность выдачи (AC09: повторный клик
-- не создаёт дубли).
-- document_jobs: задания генерации (§11: queued -> rendering -> ready;
-- failed/cancelled -- терминальные состояния попытки).
--
-- FK ON DELETE CASCADE на research_runs/report_snapshots -- паритет
-- 0007/0008: документный слой не переживает удаление научного слоя.

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    kind_code TEXT NOT NULL,
    current_revision_id TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, kind_code)
);

CREATE INDEX IF NOT EXISTS idx_documents_run
ON documents (run_id);

CREATE TABLE IF NOT EXISTS document_revisions (
    revision_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    snapshot_id TEXT NOT NULL REFERENCES report_snapshots(snapshot_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    version_no BIGINT NOT NULL,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, version_no),
    UNIQUE (document_id, snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_document_revisions_document
ON document_revisions (document_id, version_no);

CREATE TABLE IF NOT EXISTS document_renditions (
    rendition_id TEXT PRIMARY KEY,
    revision_id TEXT NOT NULL REFERENCES document_revisions(revision_id) ON DELETE CASCADE,
    snapshot_id TEXT NOT NULL REFERENCES report_snapshots(snapshot_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    format TEXT NOT NULL,
    redaction_profile TEXT NOT NULL DEFAULT 'owner-v1',
    state TEXT NOT NULL DEFAULT 'ready',
    media_type TEXT NOT NULL DEFAULT '',
    size_bytes BIGINT NOT NULL DEFAULT 0,
    content_sha256 TEXT NOT NULL DEFAULT '',
    storage_key TEXT NOT NULL DEFAULT '',
    job_id TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (snapshot_id, format, redaction_profile)
);

CREATE INDEX IF NOT EXISTS idx_document_renditions_snapshot
ON document_renditions (snapshot_id);

CREATE TABLE IF NOT EXISTS document_jobs (
    job_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    snapshot_id TEXT NOT NULL REFERENCES report_snapshots(snapshot_id) ON DELETE CASCADE,
    format TEXT NOT NULL,
    redaction_profile TEXT NOT NULL DEFAULT 'owner-v1',
    revision_id TEXT,
    rendition_id TEXT,
    state TEXT NOT NULL DEFAULT 'queued',
    error_code TEXT,
    attempt BIGINT NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_document_jobs_run
ON document_jobs (run_id, created_at);

CREATE INDEX IF NOT EXISTS idx_document_jobs_snapshot
ON document_jobs (snapshot_id);
