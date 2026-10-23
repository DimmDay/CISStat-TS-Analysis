# scripts/doclog6cert/test_d6cert_oracle_static.py
"""DOCLOG-6-CERT: статические/каталожные оракулы (s01–s12).

DDL-гигиена миграции 0012 (аддитивность §19), паритет файл↔каталог,
структурный паритет Memory/Postgres реестров, каталоги контрактов
(DOCUMENT_KINDS/AUDIT_ACTIONS/LIFECYCLE_EVENTS/_PROTECTED_STATES),
маршруты /v1/documentation DOCLOG-6, честный 410-контракт purged.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from apps.api import document_lifecycle as dl
from apps.api import security_audit

MIGRATION_0012 = Path("apps/api/migrations/0012_doclog6_approvals_archive.sql")


def _statements() -> list[str]:
    """SQL-команды миграции без комментариев (шапка -- не statement)."""
    body = "\n".join(
        line for line in MIGRATION_0012.read_text("utf-8").splitlines()
        if not line.strip().startswith("--")
    )
    return [chunk.strip() for chunk in body.split(";") if chunk.strip()]


def test_s01_migration_additive_only():
    """§19: «миграции аддитивные» -- только CREATE TABLE/INDEX IF NOT
    EXISTS; никакого переписывания существующих таблиц."""
    statements = _statements()
    assert statements, "миграция пуста"
    for statement in statements:
        head = " ".join(statement.split())[:64].upper()
        assert head.startswith(
            ("CREATE TABLE IF NOT EXISTS", "CREATE INDEX IF NOT EXISTS")
        ), head
        assert "DROP " not in head and "DELETE" not in head and "UPDATE " not in head


def test_s02_migration_fk_cascade_and_tables():
    sql = " ".join(MIGRATION_0012.read_text("utf-8").split())
    for table in ("document_approvals", "document_lifecycle", "document_retention"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
    for index in (
        "idx_document_approvals_revision",
        "idx_document_lifecycle_revision",
        "idx_document_lifecycle_document",
        "idx_document_retention_run",
    ):
        assert f"CREATE INDEX IF NOT EXISTS {index}" in sql
    # FK CASCADE: approvals (3 связи) + lifecycle (3 связи) + retention
    # (PK document_id и run_id) -- каждый файл DDL связывает ВСЕ оси.
    assert sql.count("REFERENCES document_revisions(revision_id) ON DELETE CASCADE") == 2
    assert sql.count("REFERENCES documents(document_id) ON DELETE CASCADE") == 3
    assert sql.count("REFERENCES research_runs(run_id) ON DELETE CASCADE") == 3


def test_s03_catalog_counts_and_0012_parity():
    from apps.api.research_runs import MIGRATION_FILES, MIGRATION_STATEMENTS

    assert len(MIGRATION_FILES) == 12
    assert MIGRATION_FILES[-1][0] == "0012_doclog6_approvals_archive.sql"
    assert len(MIGRATION_STATEMENTS) == 74
    name, statements = MIGRATION_FILES[-1]
    sql = " ".join(MIGRATION_0012.read_text("utf-8").split())
    for statement in statements:
        compact = " ".join(statement.split())
        assert compact in sql, statement[:80]


def test_s04_registry_method_parity_memory_postgres():
    """Структурный паритет Memory/Postgres (урок F-D2C1: расхождение
    ридеров/писателей ловится гвардом; PG-прогон -- durable-срез)."""
    methods = (
        "append_approval", "list_approvals", "latest_approval",
        "append_lifecycle", "list_lifecycle",
        "get_retention", "upsert_retention", "list_retention",
        "readiness_probe",
    )
    for name in methods:
        assert hasattr(dl.MemoryDocumentLifecycleRegistry, name), name
        assert hasattr(dl.PostgresDocumentLifecycleRegistry, name), name
        memory_source = inspect.getsource(
            getattr(dl.MemoryDocumentLifecycleRegistry, name)
        )
        postgres_source = inspect.getsource(
            getattr(dl.PostgresDocumentLifecycleRegistry, name)
        )
        assert "NotImplementedError" not in memory_source
        assert "NotImplementedError" not in postgres_source


def test_s05_document_kinds_catalog_eleven():
    from apps.api.report_snapshot import DOCUMENT_KINDS, resolve_kinds

    assert set(DOCUMENT_KINDS) == {f"D{index:02d}" for index in range(1, 12)}
    assert DOCUMENT_KINDS["D10"][0] == "recommendations_limits"
    assert DOCUMENT_KINDS["D11"][0] == "final_report"
    assert resolve_kinds(["D10", "D11"]) == ["D10", "D11"]


def test_s06_audit_actions_and_requirements():
    assert len(security_audit.AUDIT_ACTIONS) == 21
    for action in (
        "document_approved", "document_published", "document_revoked",
        "archive_bundle_created",
    ):
        assert action in security_audit.AUDIT_ACTIONS
    # Mandatory-класс fail-closed (AC11) для трёх решений согласования.
    assert security_audit.AUDIT_REQUIREMENTS["document_approved"] == "mandatory"
    assert security_audit.AUDIT_REQUIREMENTS["document_published"] == "mandatory"
    assert security_audit.AUDIT_REQUIREMENTS["document_revoked"] == "mandatory"
    # Стандартные (best-effort): retention/archive/drill -- в каталоге
    # REQUIREMENTS либо честный дефолт standard вне его (контракт
    # record_standard: незнакомое действие не ломает операцию).
    for action in (
        "retention_policy_changed", "cleanup_started", "restore_started",
        "integrity_verified", "integrity_failed",
    ):
        assert security_audit.AUDIT_REQUIREMENTS.get(action) == "standard"
    assert security_audit.AUDIT_REQUIREMENTS.get(
        "archive_bundle_created", "standard"
    ) == "standard"


def test_s07_lifecycle_event_vocabulary():
    assert dl.LIFECYCLE_EVENTS == frozenset(
        {
            "approval_requested", "approved", "rejected",
            "published", "retracted", "superseded",
        }
    )
    # Защищённые от sweep состояния (§16.1: published/approved/
    # retracted/superseded никогда не очищаются).
    assert dl._PROTECTED_STATES == frozenset(
        {"approved", "published", "retracted", "superseded"}
    )


def test_s08_documentation_routes_nine_new():
    from apps.api.main import app

    paths = {getattr(route, "path", "") for route in app.routes}
    for path in (
        "/v1/documentation/revisions/{revision_id}/approvals",
        "/v1/documentation/revisions/{revision_id}/publish",
        "/v1/documentation/revisions/{revision_id}/retract",
        "/v1/documentation/revisions/{revision_id}/lifecycle",
        "/v1/documentation/revisions/{revision_id}/diff",
        "/v1/documentation/documents/{document_id}/retention",
        "/v1/documentation/runs/{run_id}/retention/sweep",
        "/v1/documentation/runs/{run_id}/archive",
        "/v1/documentation/runs/{run_id}/archive/verify",
    ):
        assert path in paths, path


def test_s09_purged_contract_honest_410():
    """Tombstone-контракт: purged-запись жива, чтение контента --
    RenditionPurgedError (роутер маппит в 410, проверено API-оракулом
    a28); RENDITION_PURGED == 'purged'. Проверка после авторизации
    (порядок fail-closed)."""
    from apps.api.document_jobs import (
        RENDITION_PURGED,
        DocumentDeliveryService,
        DocumentRenditionRecord,
        RenditionPurgedError,
        replace_dataclass,
    )

    assert RENDITION_PURGED == "purged" == dl.RENDITION_PURGED
    from .conftest import cert_subject, seed_cert_run

    seed_cert_run()
    delivery = DocumentDeliveryService.create_default()
    rendition = delivery.registry.register_rendition(
        DocumentRenditionRecord(
            rendition_id="rend-d6cert-s09",
            revision_id="rev-d6cert-s09",
            snapshot_id="rs-" + "0" * 32,
            run_id="RUN-D6C00001",
            format="md",
            content_sha256="c" * 64,
        )
    )
    purged = replace_dataclass(
        rendition, state=RENDITION_PURGED, content_bytes=None
    )
    delivery.registry.update_rendition(purged)
    with pytest.raises(RenditionPurgedError):
        delivery.read_rendition_content(
            purged, cert_subject(), session_id="d6cert-session-a"
        )


def test_s10_postgres_registry_writes_bound_hash_columns():
    """Bound-hash обязаны писать/читать ОБА бекенда (урок F-D2C1 --
    раундтрип registry-полей): snapshot_payload_sha256/approval_manifest
    в SQL обоих направлений."""
    postgres_source = inspect.getsource(dl.PostgresDocumentLifecycleRegistry)
    assert postgres_source.count("snapshot_payload_sha256") >= 2  # INSERT+SELECT
    assert "approval_manifest" in postgres_source
    memory_source = inspect.getsource(dl.MemoryDocumentLifecycleRegistry)
    assert "approval_id" in memory_source


def test_s11_service_authorization_first():
    """Порядок fail-closed (R09/урок GREEN-находки DOCLOG-6): резолв
    ресурса до валидации тела/прав; для изменяющих методов права
    (lifecycle_rights) следуют за резолвом."""
    resolving = (
        ("request_approval", "_resolve_revision", True),
        ("decide_approval", "_resolve_revision", True),
        ("publish", "_resolve_revision", True),
        ("retract", "_resolve_revision", True),
        ("set_retention", "_resolve_document", True),
        ("sweep_retention", "_resolve_run", True),
        ("build_archive_bundle", "_resolve_run", True),
        ("verify_archive_bundle", "_resolve_run", False),
        ("diff_revisions", "_resolve_revision", False),
    )
    for method_name, resolver, needs_rights in resolving:
        source = inspect.getsource(
            getattr(dl.DocumentLifecycleService, method_name)
        )
        assert resolver in source, method_name
        if needs_rights:
            assert "lifecycle_rights" in source, method_name
            assert source.index(resolver) < source.index(
                "lifecycle_rights"
            ), method_name


def test_s12_service_default_factories():
    service = dl.DocumentLifecycleService.create_default()
    assert isinstance(service.registry, dl.DocumentLifecycleRegistry)
    assert service.delivery is not None
