# scripts/pgv02cert/test_p2cert_oracle_static.py
"""Class A static-оракулы: каталоги/migrations/pins/документация.

GREEN на цели 2f412d6; RED на родителе 0f8b9a0.
"""
from __future__ import annotations

import sys
from pathlib import Path

CERT_DIR = Path(__file__).resolve().parent
REPO_ROOT = CERT_DIR.parents[1]
sys.path.insert(0, str(CERT_DIR))

from pathlib import Path

from p2cases import REPO_ROOT


class TestKindsAndCatalogStatic:
    def test_s01_artifact_kinds_extended_legacy_pinned(self):
        from apps.api.artifact_store import ARTIFACT_KINDS

        kinds = list(ARTIFACT_KINDS)
        # spec §6/§8: новые kinds; legacy -- поимённо сохранены
        for legacy in (
            "passport", "oof_backtest", "model_card", "forecast",
            "data_frame", "validation_result", "correction_recipe",
        ):
            assert legacy in kinds, legacy
        for new in ("visual_result", "visual_print_snapshot", "passport_checkpoint"):
            assert new in kinds, new
        assert len(kinds) == 10

    def test_s02_schema_version_constants(self):
        from apps.api.visual_artifacts import (
            CHECKPOINT_SCHEMA_VERSION,
            VISUAL_ARTIFACT_SCHEMA_VERSIONS,
        )
        from apps.api.print_schema import (
            PRINT_RESULT_SCHEMA_VERSION,
            PRINT_SNAPSHOT_SCHEMA_VERSION,
        )

        assert VISUAL_ARTIFACT_SCHEMA_VERSIONS == {
            "visual_result": PRINT_RESULT_SCHEMA_VERSION,
            "visual_print_snapshot": PRINT_SNAPSHOT_SCHEMA_VERSION,
            "passport_checkpoint": CHECKPOINT_SCHEMA_VERSION,
        }
        assert PRINT_RESULT_SCHEMA_VERSION == "pgv.visual_result/1"
        assert PRINT_SNAPSHOT_SCHEMA_VERSION == "pgv.visual_print_snapshot/1"

    def test_s03_checkpoint_stages_catalog(self):
        from apps.api.visual_artifacts import CHECKPOINT_STAGES

        assert CHECKPOINT_STAGES == ("modeling_entry", "panel_entry")


class TestMigration0016Static:
    def test_s04_migration_files_catalog_16(self):
        from apps.api.research_runs import MIGRATION_FILES

        names = [name for name, _ in MIGRATION_FILES]
        assert len(names) == 16
        assert names[-1] == "0016_pgv2_print_documents.sql"
        assert "0015_doclog9_profiles.sql" in names

    def test_s05_migration_statements_sum_96(self):
        # Сумма групп == полный каталог (паритет PROGR-5.1)
        import apps.api.research_runs as rr

        total = len(rr.MIGRATION_STATEMENTS)
        assert total == 96
        groups_sum = sum(
            len(getattr(rr, name))
            for name in dir(rr)
            if name.startswith("MIGRATION_STATEMENTS_00")
        )
        assert groups_sum == total

    def test_s06_file_catalog_byte_parity(self):
        # Паритет файла-дубля и каталога (мой собственный разбор)
        from apps.api.research_runs import MIGRATION_FILES

        catalog = dict(MIGRATION_FILES)["0016_pgv2_print_documents.sql"]
        file_text = (REPO_ROOT / "apps/api/migrations/0016_pgv2_print_documents.sql").read_text()
        file_statements = [
            chunk.strip()
            for chunk in file_text.split(";")
            if chunk.strip() and not chunk.strip().startswith("--")
        ]
        # Сравнение содержательной части: каждый каталог-statement
        # встречается в файле (нормализуем пробелы)
        normalized_catalog = [" ".join(s.split()) for s in catalog]
        normalized_file = " ".join(file_text.split())
        for statement in normalized_catalog:
            assert statement in normalized_file, statement[:60]

    def test_s07_ddl_constraints_0016(self):
        from apps.api.research_runs import MIGRATION_STATEMENTS_0016

        ddl = " ".join(" ".join(s.split()) for s in MIGRATION_STATEMENTS_0016)
        assert "CREATE TABLE IF NOT EXISTS document_print_revisions" in ddl
        assert "UNIQUE (document_id, version_no)" in ddl
        assert "UNIQUE (document_id, basis_fingerprint)" in ddl
        assert "REFERENCES documents(document_id) ON DELETE CASCADE" in ddl
        assert "REFERENCES research_runs(run_id) ON DELETE CASCADE" in ddl
        # basis = frozen print inputs; snapshot_id -- ОПЦИОНАЛЬНЫЙ anchor
        assert "snapshot_id TEXT REFERENCES report_snapshots" in ddl
        assert "basis_fingerprint TEXT NOT NULL DEFAULT ''" in ddl
        assert "basis_artifact_ids JSONB NOT NULL DEFAULT '[]'::jsonb" in ddl
        # 0016 = 1 таблица + 2 индекса
        assert len(MIGRATION_STATEMENTS_0016) == 3

    def test_s08_legacy_document_revisions_ddl_untouched(self):
        # Критерий «legacy D01–12/readers работают»: document_revisions
        # сохраняет snapshot_id NOT NULL + UNIQUE(document_id, snapshot_id)
        import apps.api.research_runs as rr

        ddl_0010 = " ".join(" ".join(s.split()) for s in rr.MIGRATION_STATEMENTS_0010)
        assert "CREATE TABLE IF NOT EXISTS document_revisions" in ddl_0010
        assert "snapshot_id TEXT NOT NULL REFERENCES report_snapshots" in ddl_0010
        assert "UNIQUE (document_id, snapshot_id)" in ddl_0010
        assert "UNIQUE (document_id, version_no)" in ddl_0010

    def test_s09_migration_0016_is_additive(self):
        # Аддитивность (инвариант серии): только CREATE ... IF NOT EXISTS
        from apps.api.research_runs import MIGRATION_STATEMENTS_0016

        for statement in MIGRATION_STATEMENTS_0016:
            head = " ".join(statement.split()).upper()
            assert head.startswith("CREATE TABLE IF NOT EXISTS") or head.startswith(
                "CREATE INDEX IF NOT EXISTS"
            ), statement[:60]

    def test_s10_doclog_pin_tests_updated_honestly(self):
        # Честное обновление пинов 15→16 / 93→96 (прецедент DOCLOG-9).
        # Поимённый пин 0016 -- только в doclog4/5; doclog6/8 пинуют
        # счётчики (дифф поставки).
        for rel, with_name, expected_files, expected_stmts in (
            ("tests/api/test_doclog4_document_delivery.py", True, "len(names) == 16", None),
            ("tests/api/test_doclog5_formats_worker.py", True, "len(names) == 16", None),
            ("tests/api/test_doclog6_approvals_archive.py", False, "len(MIGRATION_FILES) == 16", "len(MIGRATION_STATEMENTS) == 96"),
            ("tests/api/test_doclog8_monitoring.py", False, "len(MIGRATION_FILES) == 16", "len(MIGRATION_STATEMENTS) == 96"),
        ):
            text = (REPO_ROOT / rel).read_text()
            if with_name:
                assert "0016_pgv2_print_documents.sql" in text, rel
            assert expected_files in text, rel
            if expected_stmts:
                assert expected_stmts in text, rel


class TestSpecAndDocsStatic:
    def test_s11_spec_row_pgv02_present(self):
        text = (REPO_ROOT / "spec_documentation_logging.md").read_text()
        assert "PGV-02 — durable inputs/V01/P01/P02" in text
        assert "pgv.document_catalog/2" in text
        assert "Дополнение PGV-02, 2026-10-28" in text
        assert "0016" in text

    def test_s12_delivery_document_exists_and_covers(self):
        text = (REPO_ROOT / "docs/pgv02_durable_inputs.md").read_text()
        for token in (
            "0016_pgv2_print_documents.sql",
            "pgv.passport_checkpoint/1",
            "PGV-AC07",
            "PGV-AC09",
            "PGV-AC11",
            "PGV-AC12",
            "PGV-AC14",
            "PGV-AC22",
            "basis_fingerprint",
        ):
            assert token in text, token

    def test_s13_worklog_record_present(self):
        text = (REPO_ROOT / "worklog/worklog11.md").read_text()
        assert "Task ID: PGV-02 (2026-10-28)" in text
        assert "51 тест" in text or "51/51" in text

    def test_s14_project_docguard_exists(self):
        guard = REPO_ROOT / "scripts/pgv02/check_documents.py"
        assert guard.exists()

    def test_s15_repo_corpus_exists_with_expected_classes(self):
        text = (REPO_ROOT / "tests/api/test_pgv02_durable_inputs.py").read_text()
        for token in (
            "TestVisualArtifactKinds",
            "TestCheckpointValidator",
            "TestFreezeVisualResult",
            "TestFreezeVisualPrintSnapshot",
            "TestPassportCheckpointFreeze",
            "TestDocumentCatalog",
            "TestPrintDocumentRevisions",
            "TestMigration0016",
            "TestSpecContract",
        ):
            assert token in text, token


class TestModuleStructureStatic:
    def test_s16_visual_artifacts_module_surface(self):
        import inspect

        import apps.api.visual_artifacts as va

        for name in (
            "validate_passport_checkpoint",
            "validate_visual_artifact_payload",
            "visual_result_producer_key",
            "print_snapshot_producer_key",
            "checkpoint_producer_key",
            "freeze_visual_result",
            "freeze_visual_print_snapshot",
            "register_passport_checkpoint",
            "list_visual_results",
            "list_visual_print_snapshots",
            "get_passport_checkpoint",
        ):
            assert hasattr(va, name), name
        src = inspect.getsource(va)
        # единая точка write -- PromotionService (R09); свой SQL запрещён
        assert "persist_visual_artifact" in src

    def test_s17_persist_gate_in_promotion_service(self):
        import inspect

        from apps.api.artifact_promotion import PromotionService

        src = inspect.getsource(PromotionService.persist_visual_artifact)
        assert "validate_visual_artifact_payload" in src
        assert "ArtifactConflictError" in src
        # контентная сверка §11
        assert "payload_sha256" in src

    def test_s18_legacy_document_revision_flow_source_untouched(self):
        # ensure_document_revision не использует печатный слой
        import inspect

        from apps.api.document_jobs import DocumentDeliveryService

        src = inspect.getsource(DocumentDeliveryService.ensure_document_revision)
        assert "print_revision" not in src
        assert "register_revision" in src

    def test_s19_no_new_http_routes(self):
        # PGV-02 -- durable-слой без роутеров (§13: роутеры PGV-13/15);
        # 221 маршрут, /v1/documentation/* -- прежние
        import apps.api.main as main

        paths = {getattr(r, "path", "") for r in main.app.routes}
        assert not any("/visual-sources" in p or "/passport-sources" in p for p in paths)
        assert not any("print" in p for p in paths)

    def test_s20_artifact_count_unchanged_after_read_helpers(self):
        # Durable read -- read-only: list/get не создают артефактов
        from apps.api.artifact_store import get_artifact_registry
        from apps.api.visual_artifacts import (
            get_passport_checkpoint,
            list_visual_print_snapshots,
            list_visual_results,
        )
        from p2cases import RUN_A, SESSION_A, seed_run

        seed_run(RUN_A, SESSION_A)
        assert list_visual_results(RUN_A) == []
        assert list_visual_print_snapshots(RUN_A) == []
        assert get_passport_checkpoint(RUN_A, "pck-none") is None
        assert get_artifact_registry().list_artifacts(RUN_A) == []
