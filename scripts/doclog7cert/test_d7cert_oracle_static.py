# scripts/doclog7cert/test_d7cert_oracle_static.py
"""DOCLOG-7-CERT: статические оракулы (s01–s12).

Каталоги/контракты без исполнения продукта: миграция 0013 (аддитивность,
файл↔каталог), маршруты /v1/logs, константы, whitelist-проекции,
параметризация SQL, структурный паритет Memory/Postgres, safe-подмножество
manifest'а, uniform-ошибки роутера.
"""
from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

from apps.api import admin_logs, research_runs
from apps.api.admin_logs import (
    BUNDLE_EXCLUDED,
    BUNDLE_PREFIX,
    BUNDLE_SCHEMA,
    GRANT_SCOPES,
    GRANT_SCHEMA_VERSION,
    GRANT_TTL_MAX_HOURS,
    STREAM_AUDIT,
    STREAM_DELIVERY,
    STREAM_TELEMETRY,
)
from apps.api.document_jobs import PostgresDocumentRegistry
from apps.api.security_audit import (
    ACTION_DOWNLOAD_REQUESTED,
    ACTION_RESPONSE_STREAM_FINISHED,
    ACTION_RESPONSE_STREAM_STARTED,
    AUDIT_ACTIONS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_FILE = (
    REPO_ROOT / "apps/api/migrations/0013_doclog7_logs_support.sql"
)


def _norm_sql(text: str) -> list[str]:
    """Разбиение SQL-файла на statement'ы по ';' (без комментариев)."""
    cleaned = re.sub(r"--[^\n]*", "", text)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


def test_s01_migration_file_catalog_parity_13_78():
    """Файл-дубль 0013 == каталог MIGRATION_STATEMENTS_0013; 13 файлов/78."""
    from apps.api.research_runs import (
        MIGRATION_FILES,
        MIGRATION_STATEMENTS,
        MIGRATION_STATEMENTS_0013,
    )

    assert MIGRATION_FILE.exists()
    file_statements = _norm_sql(MIGRATION_FILE.read_text(encoding="utf-8"))
    catalog = [s.strip() for s in MIGRATION_STATEMENTS_0013]
    assert len(file_statements) == len(catalog)
    for got, want in zip(file_statements, catalog):
        assert " ".join(got.split()) == " ".join(want.split())
    assert len(MIGRATION_FILES) == 13
    assert MIGRATION_FILES[-1] == (
        "0013_doclog7_logs_support.sql", MIGRATION_STATEMENTS_0013)
    assert len(MIGRATION_STATEMENTS) == 78


def test_s02_migration_0013_additive_only():
    text = MIGRATION_FILE.read_text(encoding="utf-8")
    statements = _norm_sql(text)
    assert len(statements) == 4  # 1 таблица + 3 индекса
    for statement in statements:
        head = " ".join(statement.split())
        assert head.startswith("CREATE TABLE IF NOT EXISTS") or head.startswith(
            "CREATE INDEX IF NOT EXISTS"), head[:60]
    for forbidden in ("DROP ", "DELETE ", "UPDATE ", "ALTER ", "TRUNCATE "):
        assert forbidden not in text.upper().replace("IF NOT EXISTS", "")


def test_s03_support_grants_ddl_fail_closed_shape():
    text = MIGRATION_FILE.read_text(encoding="utf-8")
    # tenant_id NOT NULL -- ГЛОБАЛЬНЫХ грантов нет (§15)
    assert re.search(r"tenant_id TEXT NOT NULL", text)
    assert re.search(r"expires_at TIMESTAMPTZ NOT NULL", text)
    assert re.search(r"grant_id TEXT PRIMARY KEY", text)
    assert "revoked_at TIMESTAMPTZ" in text  # nullable -- append-only отзыв
    assert "FOREIGN KEY" not in text.upper()  # намеренно без FK (грант переживает run)
    for index in ("idx_support_grants_subject", "idx_support_grants_tenant",
                  "idx_support_grants_ticket"):
        assert index in text


def test_s04_seven_routes_registered():
    from apps.api.main import app

    logs_routes: dict[str, set] = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/v1/logs"):
            methods = set(getattr(route, "methods", set())) - {"HEAD", "OPTIONS"}
            logs_routes.setdefault(path, set()).update(methods)
    assert len(logs_routes) == 7
    assert logs_routes["/v1/logs/access"] == {"GET"}
    assert logs_routes["/v1/logs/telemetry"] == {"GET"}
    assert logs_routes["/v1/logs/audit"] == {"GET"}
    assert logs_routes["/v1/logs/delivery"] == {"GET"}
    assert logs_routes["/v1/logs/export"] == {"POST"}
    assert logs_routes["/v1/logs/grants"] == {"GET", "POST"}
    assert logs_routes["/v1/logs/grants/{grant_id}/revoke"] == {"POST"}


def test_s05_constants_catalog():
    assert GRANT_SCOPES == frozenset({"logs.read", "audit.read", "logs.export"})
    assert GRANT_TTL_MAX_HOURS == 168
    assert admin_logs.WINDOW_MAX_DAYS == 31
    assert admin_logs.QUERY_LIMIT_DEFAULT == 50
    assert admin_logs.QUERY_LIMIT_MAX == 200
    assert admin_logs.EXPORT_LIMIT == 2000
    assert admin_logs.TELEMETRY_RETENTION_DAYS == 30
    assert admin_logs.AUDIT_RETENTION_DAYS == 365
    assert BUNDLE_SCHEMA == "doclog.diagbundle/1"
    assert BUNDLE_PREFIX == "diagb-"
    assert GRANT_SCHEMA_VERSION == "doclog.support_grant/1"
    assert admin_logs.BUNDLE_DATE_TIME == (2020, 1, 1, 0, 0, 0)
    assert admin_logs.ALL_STREAMS == frozenset(
        {"telemetry", "audit", "delivery"})


def test_s06_bundle_excluded_catalog_explicit():
    assert len(BUNDLE_EXCLUDED) == 5
    joined = " ".join(BUNDLE_EXCLUDED)
    for keyword in ("датасетов", "cookies", "env values", "API-ключ", "пути"):
        assert keyword in joined
    # каталог иммутабелен (tuple)
    assert isinstance(BUNDLE_EXCLUDED, tuple)


def test_s07_whitelist_filter_catalogs():
    """Каталог whitelist-полей per-stream -- единственный источник истины
    в коде (§14.2: без произвольного SQL/regex от браузера)."""
    assert _wl_telemetry() == {
        "severity", "outcome", "event_name", "request_id", "run_id", "tenant_id"}
    assert _wl_audit() == {
        "action", "decision", "actor_subject", "request_id", "run_id", "tenant_id"}
    assert _wl_delivery() == {"state", "format", "run_id", "tenant_id"}


def _wl_telemetry():
    from apps.api.admin_logs import (
        STREAM_TELEMETRY as ST,
        LogsValidationError,
        _validate_filters,
    )

    whitelist = None
    # извлекаем каталог напрямую из сорца (единственный источник истины)
    source = inspect.getsource(_validate_filters)
    match = re.search(
        r"STREAM_TELEMETRY:\s*\{([^}]*)\}", source)
    assert match
    return {x.strip().strip('"') for x in match.group(1).split(",") if x.strip()}


def _wl_audit():
    source = inspect.getsource(admin_logs._validate_filters)
    match = re.search(r"STREAM_AUDIT:\s*\{([^}]*)\}", source)
    assert match
    return {x.strip().strip('"') for x in match.group(1).split(",") if x.strip()}


def _wl_delivery():
    source = inspect.getsource(admin_logs._validate_filters)
    match = re.search(r"STREAM_DELIVERY:\s*\{([^}]*)\}", source)
    assert match
    return {x.strip().strip('"') for x in match.group(1).split(",") if x.strip()}


def test_s08_sql_values_parameterized_never_interpolated():
    """Whitelist-значения фильтров идут ТОЛЬКО через %s-параметры."""
    for fn_name in ("_pg_query_telemetry", "_pg_query_audit"):
        source = inspect.getsource(getattr(admin_logs, fn_name))
        assert "params.extend" in source or "params.append" in source
        # значение фильтра не форматается в SQL-строку
        assert re.search(r"\{filters\[", source) is None
    field_filters = inspect.getsource(admin_logs._pg_field_filters)
    assert "= %s" in field_filters
    assert "params.append(filters[name])" in field_filters
    # narrow -- IN (%s...) с параметрами, не интерполяция значений
    narrow = inspect.getsource(admin_logs._pg_narrow)
    assert "IN ({placeholders})" in narrow
    assert "params.extend(sorted" in narrow


def _select_columns_from_source(source: str) -> set[str]:
    """Извлечение колонок SELECT из SQL-литерала в сорце (статически)."""
    match = re.search(r"SELECT (.*?) FROM", source, re.DOTALL)
    assert match, "SELECT ... FROM не найден"
    raw = match.group(1)
    raw = re.sub(r"[\"\',\n]", " ", raw)
    return {token.strip() for token in raw.split() if token.strip()}


def _projection_tuple_from_source(source: str) -> set[str]:
    match = re.search(r"columns = \((.*?)\)", source, re.DOTALL)
    assert match, "кортеж columns не найден"
    return set(re.findall(r'"([a-z_]+)"', match.group(1)))


def test_s09_list_recent_whitelist_projection_bounded():
    """Безопасная проекция: SELECT-колонки == кортежу проекции == каталогу
    (статическая сверка -- kill-канал для мутантов SELECT-списка)."""
    from apps.api.security_audit import PostgresAuditSink
    from apps.api.telemetry import PostgresTelemetrySink

    audit_src = inspect.getsource(PostgresAuditSink.list_recent)
    assert "SELECT *" not in audit_src
    assert "LIMIT %s" in audit_src
    audit_select = _select_columns_from_source(audit_src)
    audit_tuple = _projection_tuple_from_source(audit_src)
    assert audit_select == audit_tuple  # паритет чтения и проекции
    for column in ("audit_id", "occurred_at", "actor_subject", "action",
                   "decision", "tenant_id", "run_id", "details"):
        assert column in audit_select
    telemetry_src = inspect.getsource(PostgresTelemetrySink.list_recent)
    assert "SELECT *" not in telemetry_src
    assert "LIMIT %s" in telemetry_src
    telemetry_select = _select_columns_from_source(telemetry_src)
    telemetry_tuple = _projection_tuple_from_source(telemetry_src)
    assert telemetry_select == telemetry_tuple
    assert "attributes" in telemetry_select


def test_s10_bundle_builder_reads_no_env():
    source = inspect.getsource(admin_logs.build_diagnostic_bundle)
    assert "os.environ" not in source
    assert "getenv" not in source
    # окружение читается ТОЛЬКО в фабриках бекендов/выборе адаптера
    module_source = inspect.getsource(admin_logs)
    env_reads = [
        line.strip() for line in module_source.splitlines()
        if "os.environ" in line or "getenv" in line
    ]
    assert env_reads, "ожидается конечный список точек чтения env"
    for line in env_reads:
        # каждая точка -- backend-выбор/DSN фабрики, не запись/чтение данных
        assert any(
            token in line
            for token in ("GRANTS_BACKEND_ENV", "DATABASE_URL",
                          "CISSTAT_TELEMETRY_BACKEND", "CISSTAT_AUDIT_BACKEND")
        ), line


def test_s11_router_uniform_errors_and_headers():
    from apps.api.routers import logs as logs_router

    denied = inspect.getsource(logs_router._denied)
    assert '"logs_access_denied"' in denied
    assert "request_id" in denied
    backend = inspect.getsource(logs_router._backend_error)
    assert '"logs_backend_unavailable"' in backend
    validation = inspect.getsource(logs_router._validation_error)
    assert '"logs_validation_error"' in validation
    export_src = inspect.getsource(logs_router.export_logs_bundle)
    assert "nosniff" in export_src
    assert "private, no-store" in export_src
    assert "attachment" in export_src
    # 401 различим на уровне заголовка (не 422 FastAPI)
    assert "401" in inspect.getsource(logs_router._principal_or_401)


def test_s12_structural_parity_and_audit_catalog():
    """Memory/Postgres паритет (урок F-D2C1) и каталог audit."""
    for cls_name in ("MemorySupportGrantRegistry", "PostgresSupportGrantRegistry"):
        cls = getattr(admin_logs, cls_name)
        for method in ("create_grant", "get_grant", "list_grants", "update_grant"):
            impl = getattr(cls, method, None)
            assert impl is not None, (cls_name, method)
            assert "raise NotImplementedError" not in inspect.getsource(impl)
    for cls in (
        admin_logs.MemorySupportGrantRegistry,
        admin_logs.PostgresSupportGrantRegistry,
    ):
        src = inspect.getsource(cls)
        assert "NotImplementedError" not in src, cls.__name__
    # delivery summary в обоих бекендах реестра документов
    from apps.api.document_jobs import MemoryDocumentRegistry

    assert "raise NotImplementedError" not in inspect.getsource(
        MemoryDocumentRegistry.list_delivery_summary)
    assert "raise NotImplementedError" not in inspect.getsource(
        PostgresDocumentRegistry.list_delivery_summary)
    # контент в проекцию НЕ входит
    from apps.api.document_jobs import _DELIVERY_SUMMARY_COLUMNS

    assert "content_bytes" not in _DELIVERY_SUMMARY_COLUMNS
    assert "payload" not in _DELIVERY_SUMMARY_COLUMNS
    # каталог audit-действий DOCLOG-3 не расширялся (21), тройка из него
    assert len(AUDIT_ACTIONS) == 21
    assert {"grant_created", "grant_revoked", "audit_log_accessed"} <= set(
        AUDIT_ACTIONS)
    assert ACTION_DOWNLOAD_REQUESTED in AUDIT_ACTIONS
    assert ACTION_RESPONSE_STREAM_STARTED in AUDIT_ACTIONS
    assert ACTION_RESPONSE_STREAM_FINISHED in AUDIT_ACTIONS
