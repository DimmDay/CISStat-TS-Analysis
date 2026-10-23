-- Migration 0011: DOCLOG-5 -- форматы и worker
-- (spec_documentation_logging.md §7 очередь P1, §11, §18, §19 строка
-- DOCLOG-5, §20 AC08/AC09). АДДИТИВНАЯ (§19: «миграции аддитивные;
-- reader появляется раньше writer»): только ADD COLUMN IF NOT EXISTS,
-- никакого переписывания таблиц/данных DOCLOG-4.
--
-- document_renditions.snapshot_payload_sha256 -- критерий завершения
--   §19 «все rendition имеют один snapshot hash»: каждая rendition
--   несёт registry-метаданные payload_sha256 исходного frozen-снимка.
-- document_jobs.tenant_id -- per-tenant concurrency/quota (§18).
-- document_jobs.claimed_at / lease_expires_at -- lease захвата job'а
--   worker'ом (§11/§18); просрочка -- честный реклейм (AC08: crash
--   не теряет результат, чужой живой lease не перехватывается -- AC09).

ALTER TABLE document_renditions
    ADD COLUMN IF NOT EXISTS snapshot_payload_sha256 TEXT NOT NULL DEFAULT '';

ALTER TABLE document_jobs
    ADD COLUMN IF NOT EXISTS tenant_id TEXT;

ALTER TABLE document_jobs
    ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;

ALTER TABLE document_jobs
    ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_document_jobs_state
ON document_jobs (state, created_at);
