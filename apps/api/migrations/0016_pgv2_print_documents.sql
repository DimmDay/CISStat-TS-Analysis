-- Migration 0016: PGV-02 -- durable inputs/V01/P01/P02
-- (spec_passport_graphics_visual.md §6/§8/§10.2/§13, строка PGV-02).
-- Файл-дубль каталога MIGRATION_STATEMENTS_0016
-- (apps/api/research_runs.py); паритет источников DDL страхуется
-- тестами (паттерн PROGR-5.1). Аддитивная миграция: таблица новая,
-- legacy-корпус D01-D12 остаётся читаемым (читатели раньше писателей).
--
-- document_print_revisions: ревизии печатных документов V01/P01/P02
-- (каталог pgv.document_catalog/2, report_snapshot.PRINT_DOCUMENT_KINDS).
-- Basis -- frozen print inputs (артефакты visual_print_snapshot /
-- паспорта / сравнение), НЕ report snapshot: document_revisions
-- (0010) сохраняет snapshot_id NOT NULL и UNIQUE(snapshot_id) для
-- legacy читателей D01-D12 (критерий PGV-02 «legacy D01-12/readers
-- работают»). snapshot_id допускает NULL как опциональный паспортный
-- anchor (P01 из report_snapshots).
--
-- Идемпотентность выдачи (§11: payload digest): UNIQUE(document_id,
-- basis_fingerprint) -- повтор с тем же basis не плодит версии
-- (§12.2 «повторный клик не создаёт дубли»); монотонные версии --
-- UNIQUE(document_id, version_no) (паритет document_revisions).
--
-- FK ON DELETE CASCADE на research_runs/documents -- паритет 0010:
-- печатный слой не переживает удаление научного слоя/документа.

CREATE TABLE IF NOT EXISTS document_print_revisions (
    print_revision_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    print_kind TEXT NOT NULL,
    basis_kind TEXT NOT NULL,
    basis_artifact_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    snapshot_id TEXT REFERENCES report_snapshots(snapshot_id) ON DELETE CASCADE,
    profile_id TEXT NOT NULL DEFAULT 'figure-landscape',
    manifest_artifact_id TEXT,
    basis_fingerprint TEXT NOT NULL DEFAULT '',
    version_no BIGINT NOT NULL,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (document_id, version_no),
    UNIQUE (document_id, basis_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_document_print_revisions_run
ON document_print_revisions (run_id);

CREATE INDEX IF NOT EXISTS idx_document_print_revisions_document
ON document_print_revisions (document_id, version_no);
