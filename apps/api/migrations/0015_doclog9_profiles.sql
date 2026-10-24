-- Migration 0015: DOCLOG-9 -- профили организации
-- (spec_documentation_logging.md §7 P2, §11, §15, §16, §19 строка
-- DOCLOG-9, §20 AC08/AC09). АДДИТИВНАЯ миграция (§19: «миграции
-- аддитивные; reader появляется раньше writer»): только новые таблицы
-- и ADD COLUMN IF NOT EXISTS -- паттерн 0011; legacy-корпус DOCLOG-4/5
-- остаётся читаемым, исторические события/записи не переписываются.
--
-- doc_profiles -- организационная сущность tenant-уровня: БЕЗ FK на
--   research_runs (паритет грантов 0013: переживает run намеренно);
--   версии профилей -- UNIQUE(name, version_no); retire -- статусная
--   запись (append-семантика), содержимое иммутабельно.
-- doc_rendition_validations -- доказательства «профиль подтверждён
--   ВАЛИДАТОРОМ, не названием файла» (§19): запись пишется даже при
--   passed; failed -- честный failed-выпуск (AC08 по построению).
-- doc_anchor_records -- append-only якорь (INSERT-only API; локальный
--   срез внешнего anchoring §16).
-- document_renditions/document_jobs.org_profile_id -- профиль
--   фиксируется в метаданных выпуска (ADD COLUMN, дефолт '' --
--   legacy-строки читаются как безпрофильные).

ALTER TABLE document_renditions
    ADD COLUMN IF NOT EXISTS org_profile_id TEXT NOT NULL DEFAULT '';

ALTER TABLE document_jobs
    ADD COLUMN IF NOT EXISTS org_profile_id TEXT NOT NULL DEFAULT '';

CREATE TABLE IF NOT EXISTS doc_profiles (
    profile_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL DEFAULT 'doclog.org_profile/1',
    name TEXT NOT NULL,
    version_no INTEGER NOT NULL,
    format TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    language TEXT NOT NULL DEFAULT 'ru',
    title_prefix TEXT NOT NULL DEFAULT '',
    footer_text TEXT NOT NULL DEFAULT '',
    organization TEXT NOT NULL DEFAULT '',
    validate_conformance BOOLEAN NOT NULL DEFAULT TRUE,
    sign_contents BOOLEAN NOT NULL DEFAULT FALSE,
    anchor_registry BOOLEAN NOT NULL DEFAULT FALSE,
    worm_lock BOOLEAN NOT NULL DEFAULT FALSE,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    retired_by TEXT,
    retired_at TIMESTAMPTZ,
    UNIQUE (name, version_no)
);

CREATE TABLE IF NOT EXISTS doc_rendition_validations (
    validation_id TEXT PRIMARY KEY,
    rendition_id TEXT NOT NULL,
    job_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    profile_id TEXT NOT NULL,
    profile_version_no INTEGER NOT NULL DEFAULT 1,
    format TEXT NOT NULL,
    validator TEXT NOT NULL,
    result TEXT NOT NULL,
    findings JSONB NOT NULL DEFAULT '[]'::jsonb,
    signature_manifest JSONB,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS doc_anchor_records (
    anchor_id TEXT PRIMARY KEY,
    rendition_id TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    profile_id TEXT NOT NULL,
    anchored_by TEXT,
    anchored_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_doc_profiles_format
ON doc_profiles (format, status);

CREATE INDEX IF NOT EXISTS idx_doc_validations_rendition
ON doc_rendition_validations (rendition_id, checked_at);

CREATE INDEX IF NOT EXISTS idx_doc_anchors_rendition
ON doc_anchor_records (rendition_id, anchored_at);
