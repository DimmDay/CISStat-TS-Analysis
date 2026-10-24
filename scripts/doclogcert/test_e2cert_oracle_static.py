# scripts/doclogcert/test_e2cert_oracle_static.py
"""DOCLOG-CERT: статические оракулы сквозной приёмки (миграция,
каталоги, каркас прав, декларации зависимостей, пины классов дефектов).
Спека §19 DOCLOG-CERT: «...и миграция»; §20 AC10/AC16-каркас."""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text("utf-8")


# ══════════════════════════════════════════════════════════════════════
# Миграции (§19: аддитивные; reader раньше writer)
# ══════════════════════════════════════════════════════════════════════


class TestMigrations:
    def test_fifteen_migrations_doclog0_to_doclog9(self):
        from apps.api.research_runs import MIGRATION_FILES, MIGRATION_STATEMENTS

        assert len(MIGRATION_FILES) == 15
        assert len(MIGRATION_STATEMENTS) == 93
        assert MIGRATION_FILES[-1][0] == "0015_doclog9_profiles.sql"
        names = [name for name, _ in MIGRATION_FILES]
        assert "0006_doclog0_run_ownership.sql" in names
        assert "0013_doclog7_logs_support.sql" in names
        assert "0014_doclog8_monitoring.sql" in names

    def test_migration_files_additive_no_drop(self):
        migration_dir = REPO_ROOT / "apps" / "api" / "migrations"
        for path in sorted(migration_dir.glob("*.sql")):
            text = path.read_text("utf-8").upper()
            for token in ("DROP TABLE", "DROP COLUMN"):
                assert token not in text, f"{path.name}: {token} запрещён" 

    def test_doclog_migration_chain_0006_0015(self):
        expected = [
            "0006_doclog0_run_ownership.sql",
            "0007_doclog1_artifacts.sql",
            "0008_doclog2_snapshots.sql",
            "0009_doclog3_telemetry_audit.sql",
            "0010_doclog4_documents.sql",
            "0011_doclog5_render_formats.sql",
            "0012_doclog6_approvals_archive.sql",
            "0013_doclog7_logs_support.sql",
            "0014_doclog8_monitoring.sql",
            "0015_doclog9_profiles.sql",
        ]
        migration_dir = REPO_ROOT / "apps" / "api" / "migrations"
        present = {p.name for p in migration_dir.glob("*.sql")}
        for name in expected:
            assert name in present, f"миграция {name} отсутствует"


# ══════════════════════════════════════════════════════════════════════
# Каталоги контура (сводка §19/§20)
# ══════════════════════════════════════════════════════════════════════


class TestCatalogs:
    def test_document_kinds_twelve(self):
        from apps.api.report_snapshot import DOCUMENT_KINDS

        assert len(DOCUMENT_KINDS) == 12
        assert set(DOCUMENT_KINDS) == {f"D{n:02d}" for n in range(1, 13)}

    def test_audit_actions_catalog(self):
        from apps.api.security_audit import AUDIT_ACTIONS

        required = {
            "document_approved",
            "document_published",
            "document_revoked",
            "org_profile_created",
            "org_profile_retired",
            "grant_created",
            "grant_revoked",
            "audit_log_accessed",
            "monitoring_actual_registered",
            "monitoring_comparison_created",
            "monitoring_decision_recorded",
        }
        missing = required - set(AUDIT_ACTIONS)
        assert not missing, f"аудит-действия вне каталога: {missing}"
        assert len(AUDIT_ACTIONS) == 28

    def test_grant_catalog_and_ttl(self):
        from apps.api.admin_logs import GRANT_SCOPES, GRANT_TTL_MAX_HOURS

        assert GRANT_SCOPES == frozenset(
            {"audit.read", "logs.export", "logs.read"}
        )
        assert GRANT_TTL_MAX_HOURS == 168

    def test_rendition_formats_catalog(self):
        from apps.api.document_renditions import (
            HEAVY_RENDITION_FORMATS,
            RENDITION_FORMATS,
        )

        assert set(RENDITION_FORMATS) == {
            "json", "jsonl", "md", "html", "csv",
            "pdf", "xlsx", "parquet", "svg", "png", "zip",
            "docx", "pdfa",
        }
        assert HEAVY_RENDITION_FORMATS == frozenset(
            {"pdf", "xlsx", "parquet", "svg", "png", "zip", "docx", "pdfa"}
        )

    def test_profile_formats(self):
        from apps.api.doc_profiles import PROFILE_FORMATS

        assert PROFILE_FORMATS == frozenset({"docx", "pdfa"})


# ══════════════════════════════════════════════════════════════════════
# Каркас маршрутов и прав
# ══════════════════════════════════════════════════════════════════════


class TestRouteFramework:
    def test_main_imports_with_expected_routes(self):
        import apps.api.main as main_mod

        routes = [r for r in main_mod.app.routes if hasattr(r, "path")]
        paths = {r.path for r in routes}
        assert len(routes) == 221
        assert "/v1/documentation/runs/{run_id}/documents" in paths
        assert "/v1/documentation/runs/{run_id}/monitoring/actuals" in paths
        assert "/v1/documentation/org-profiles" in paths
        assert "/v1/logs/telemetry" in paths
        assert "/health/ops" in paths

    def test_every_documentation_route_authorizes(self):
        """Каркас uniform-404 (R09): каждый route-handler в
        routers/documentation.py ЛИБО вызывает объектную авторизацию
        сам (_authorized_run_or_404), ЛИБО делегирует сервису, чей
        первый шаг -- авторизация (закреплено repo-пинами DOCLOG-6:
        «резолв -> права -> действие» в каждом методе сервиса)."""
        source = _read("apps/api/routers/documentation.py")
        tree = ast.parse(source)
        authorized = 0
        handlers = 0
        missing = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            is_route = any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr in ("get", "post")
                for d in node.decorator_list
            )
            if not is_route or node.name.startswith("_"):
                continue
            handlers += 1
            body = ast.get_source_segment(source, node) or ""
            if (
                "_authorized_run_or_404" in body
                or "_delivery_service()" in body
                or "_lifecycle_service()" in body
            ):
                authorized += 1
            else:
                missing.append(node.name)
        assert handlers >= 17, handlers
        assert authorized == handlers, (
            f"без авторизации: {missing}"
        )

    def test_logs_router_flat_error_codes(self):
        source = _read("apps/api/routers/logs.py")
        assert "logs_access_denied" in source
        assert "logs_validation_error" in source
        assert "logs_backend_unavailable" in source
        assert "audit_unavailable" in source

    def test_key_header_only_no_query_key(self):
        source = _read("apps/api/routers/logs.py")
        assert 'Header(default=None)' in source
        assert 'Query(' not in source or 'x_api_key' not in source.split(
            'Query('
        )[0].split('def ')[0]


# ══════════════════════════════════════════════════════════════════════
# Пины классов дефектов (фикс-уроки сертификаций DOCLOG)
# ══════════════════════════════════════════════════════════════════════


class TestClassPins:
    def test_use_client_first_line_for_hook_components(self):
        """DOCLOG-8-UI-FIX: компоненты с хуками -- "use client" первой
        строкой (сборка embedded через barrel-экспорт)."""
        components_dir = REPO_ROOT / "packages" / "ui" / "components"
        hook_re = re.compile(r"use(State|Effect|Callback|Memo|Ref)\(")
        offenders = []
        for path in sorted(components_dir.glob("*.tsx")):
            text = path.read_text("utf-8")
            if hook_re.search(text):
                head = [line.strip() for line in text.splitlines()[:4]]
                if not any(
                    re.match(r'^["\']use client["\'];?$', line)
                    for line in head
                ):
                    offenders.append(path.name)
        assert not offenders, f"нет 'use client' первой строкой: {offenders}"

    def test_admin_logs_client_key_in_header_only(self):
        source = _read("packages/ui/lib/adminLogs.ts")
        assert "X-API-Key" in source or "x-api-key" in source
        import re as _re

        assert not _re.search(
            r"localStorage\.(setItem|getItem|removeItem)", source
        ), "ключ не должен храниться в localStorage"
        assert not _re.search(
            r"sessionStorage\.(setItem|getItem|removeItem)", source
        ), "ключ не должен храниться в sessionStorage"

    def test_requirements_declare_doclog_dependencies(self):
        source = _read("apps/api/requirements.txt")
        for token in (
            "psycopg",
            "reportlab",
            "pyarrow",
            "sqlalchemy",
            "PyMySQL",
            "pyodbc",
            "clickhouse-connect",
            "duckdb",
        ):
            assert token in source, f"{token} не объявлен (урок F14)"

    def test_auth_fail_closed_subject_not_key(self):
        source = _read("apps/api/auth.py")
        assert "subject_id == key" in source, (
            "T4-пин: субъект == значению ключа обязан отбрасываться"
        )

    def test_postgres_log_sinks_list_recent_implemented(self):
        """DOCLOG-7: отложенный гэп чтения durable-журналов закрыт."""
        for rel, cls in (
            ("apps/api/security_audit.py", "PostgresAuditSink"),
            ("apps/api/telemetry.py", "PostgresTelemetrySink"),
        ):
            source = _read(rel)
            match = re.search(
                rf"class {cls}\b.*?(?=\nclass |\Z)", source, re.S
            )
            assert match, f"{cls} не найден в {rel}"
            body = match.group(0)
            assert "def list_recent" in body, f"{cls}.list_recent отсутствует"
            impl = body.split("def list_recent", 1)[1]
            impl = impl.split("\n    def ", 1)[0]
            assert "NotImplementedError" not in impl, (
                f"{cls}.list_recent не реализован"
            )

    def test_fixed_zip_determinism(self):
        source_rend = _read("apps/api/document_renditions.py")
        assert re.search(
            r"_ZIP_FIXED_DATE_TIME\s*=\s*\(1980,\s*1,\s*1", source_rend
        ), "ZIP evidence обязан быть детерминированным (AC03-дух)"
        source_admin = _read("apps/api/admin_logs.py")
        assert re.search(
            r"BUNDLE_DATE_TIME\s*=\s*\((1980|2020),\s*1,\s*1", source_admin
        ), "диагностический пакет обязан быть детерминированным"

    def test_diagnostic_bundle_exclusions_declared(self):
        source = _read("apps/api/admin_logs.py")
        lowered = source.lower()
        for token in ("env", "cookie", "dsn", "api-key", "api_key"):
            assert token in lowered, (
                f"manifest пакета обязан явно исключать {token} (AC10/AC19)"
            )

    def test_documentation_ui_exports_barrel(self):
        source = _read("packages/ui/index.ts")
        for name in (
            "DocumentationWorkspace",
            "MonitoringComparisonPanel",
            "Doclog9ProfileControls",
            "AdminLogsDashboard",
        ):
            assert name in source, f"{name} не экспортирован из barrel"
