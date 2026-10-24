# scripts/doclog8cert/test_d8cert_oracle_static.py
"""DOCLOG-8-CERT: статические оракулы (s01–s12).

Миграция 0014 (файл↔каталог, DDL fail-closed), поверхность маршрутов,
каталоги аудита/действий/порогов, чистота compute, паритет Memory/
Postgres, whitelist SELECT-колонок, каталог видов D12, publish-политика,
UI-контракт (включая регрессионный пин "use client" первой строкой --
урок DOCLOG-8-UI-FIX).
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

MIGRATION = Path("apps/api/migrations/0014_doclog8_monitoring.sql")
ROUTER = Path("apps/api/routers/monitoring.py")
SERVICE = Path("apps/api/monitoring.py")


def _sql() -> str:
    return MIGRATION.read_text("utf-8")


def _stmts(sql: str) -> list[str]:
    body = re.sub(r"--[^\n]*", "", sql)
    return [s.strip() for s in body.split(";") if s.strip()]


class TestMigration0014:
    def test_s01_file_catalog_parity(self):
        from apps.api.research_runs import MIGRATION_FILES

        names = [name for name, _ in MIGRATION_FILES]
        assert names[-1] == "0014_doclog8_monitoring.sql"
        catalog = dict(MIGRATION_FILES)["0014_doclog8_monitoring.sql"]
        file_stmts = _stmts(_sql())
        assert len(file_stmts) == len(catalog) == 7  # 3 таблицы + 4 индекса
        for statement in catalog:
            compact = " ".join(statement.split())
            assert compact in " ".join(_sql().split()), statement[:60]

    def test_s02_ddl_fail_closed(self):
        sql = _sql()
        # Три таблицы, каждая с FK на research_runs ON DELETE CASCADE.
        for table in ("monitoring_actual_batches",
                      "monitoring_comparisons",
                      "monitoring_decisions"):
            assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
        assert sql.count("REFERENCES research_runs(run_id) "
                         "ON DELETE CASCADE") == 3
        # Идемпотентность (§10.3/AC09) -- ровно на партиях и сверках.
        assert sql.count("UNIQUE (run_id, idempotency_key)") == 2
        # Решения append-only: много решений на сверку допустимо.
        decisions_ddl = sql.split("monitoring_decisions")[1]
        assert "idempotency" not in decisions_ddl
        # Честные типы: JSONB для значений/результатов.
        assert "actual_values JSONB" in sql
        assert "result JSONB" in sql
        # Аддитивность: только CREATE (читатели раньше писателей).
        for statement in _stmts(sql):
            assert statement.upper().startswith("CREATE "), statement[:50]

    def test_s03_indexes(self):
        sql = _sql()
        for fragment in (
            "idx_mon_batches_run",
            "idx_mon_comparisons_run",
            "idx_mon_comparisons_batch",
            "idx_mon_decisions_comparison",
        ):
            assert f"CREATE INDEX IF NOT EXISTS {fragment}" in sql, fragment


class TestRouterSurface:
    def test_s04_exactly_seven_routes(self):
        from apps.api.main import app

        routes = [
            r for r in app.routes
            if hasattr(r, "path") and "/monitoring/" in r.path
        ]
        assert len(routes) == 7
        methods = {}
        for route in routes:
            key = route.path.replace("/v1/documentation/runs/{run_id}/"
                                     "monitoring/", "")
            methods.setdefault(key, set()).update(route.methods - {"HEAD"})
        assert methods == {
            "actuals": {"POST", "GET"},
            "comparisons": {"POST", "GET"},
            "comparisons/{comparison_id}": {"GET"},
            "comparisons/{comparison_id}/decisions": {"POST", "GET"},
        }

    def test_s05_error_mapping_source(self):
        source = ROUTER.read_text("utf-8")
        # Порядок isinstance-цепочки фиксирует семантику §17:
        # AccessDenied -> uniform 404 (существование не дисклоужается);
        # валидация 422; units mismatch 422 отдельным кодом; конфликт 409;
        # прогноз недоступен 404; not found 404.
        assert "MonitoringValidationError" in source
        assert '"monitoring_validation_error"' in source
        assert '"monitoring_units_mismatch"' in source
        assert '"monitoring_idempotency_conflict"' in source
        assert '"monitoring_forecast_unavailable"' in source
        assert '"monitoring_not_found"' in source
        assert "_RUN_NOT_FOUND_DETAIL" in source
        # Плоское тело без detail-обёртки FastAPI.
        assert "JSONResponse" in source
        assert "current_request_id()" in source


class TestCatalogs:
    def test_s06_decision_and_threshold_catalogs(self):
        from apps.api import monitoring

        assert monitoring.DECISION_ACTIONS == frozenset(
            {"none", "accept", "investigate", "retrain_requested"}
        )
        assert monitoring.THRESHOLD_METRICS == frozenset(
            {"mae", "mape", "bias_abs", "mase"}
        )
        assert monitoring.THRESHOLD_OPERATORS == frozenset({">", ">="})
        assert monitoring.SOURCE_KINDS == frozenset({"manual", "artifact"})
        assert monitoring.DEFAULT_LIST_LIMIT == 100  # §18 пилотный предел

    def test_s07_schema_versions(self):
        from apps.api import monitoring

        assert monitoring.MONITORING_SCHEMA_VERSION == "doclog.monitoring/1"
        assert monitoring.ACTUAL_VINTAGE_SCHEMA_VERSION == \
            "doclog.actual_vintage/1"
        assert monitoring.COMPARISON_SCHEMA_VERSION == \
            "doclog.monitoring_comparison/1"
        assert monitoring.DECISION_SCHEMA_VERSION == \
            "doclog.monitoring_decision/1"
        assert monitoring.RESULT_SCHEMA_VERSION == \
            "doclog.monitoring_result/1"

    def test_s08_audit_actions_24_standard_only(self):
        from apps.api import security_audit

        for action in (
            "monitoring_actual_registered",
            "monitoring_comparison_created",
            "monitoring_decision_recorded",
        ):
            assert action in security_audit.AUDIT_ACTIONS, action
        assert len(security_audit.AUDIT_ACTIONS) == 24
        # §8: monitoring_* -- standard-класс (не mandatory): сервис
        # вызывает record_standard, record_mandatory не используется.
        source = SERVICE.read_text("utf-8")
        assert "record_standard(" in source
        assert "record_mandatory" not in source

    def test_s09_document_kinds_12(self):
        from apps.api.report_snapshot import DOCUMENT_KINDS, resolve_kinds

        assert DOCUMENT_KINDS["D12"] == (
            "forecast_vs_actual", "Сверка прогноза с фактом", None
        )
        assert len(DOCUMENT_KINDS) == 12
        assert resolve_kinds(["D12"]) == ["D12"]
        assert resolve_kinds(["forecast_vs_actual"]) == ["D12"]

    def test_s10_publish_policy_partial_d12(self):
        source = Path("apps/api/document_lifecycle.py").read_text("utf-8")
        # partial допустим для D01-D10 и D12 (поздний факт -- незрелые
        # горизонты не блокируют выпуск итогового отчёта).
        assert "partial допустим для D01-D10 и D12" in source


class TestPurityAndParity:
    def test_s11_compute_is_pure(self):
        from apps.api.monitoring import compute_comparison_result

        source = inspect.getsource(compute_comparison_result)
        for forbidden in ("os.environ", "get_artifact_registry",
                          "get_artifact_object_store", "get_monitoring_",
                          "psycopg", "open(", "requests.", "print(",
                          "datetime.now"):
            assert forbidden not in source, forbidden
        # Возвращает НОВЫЙ dict; входные payload/values не мутируются.
        payload = {"points": [{"date": "2026-09-01", "value": 5.0,
                               "ci_lower": 4.0, "ci_upper": 6.0}]}
        values = [{"period": "2026-09-01", "value": 4.8}]
        payload_copy = {"points": [dict(payload["points"][0])]}
        values_copy = [dict(values[0])]
        compute_comparison_result(payload, values)
        assert payload == payload_copy
        assert values == values_copy

    def test_s12_registry_structural_parity(self):
        from apps.api.monitoring import (
            MemoryMonitoringRegistry,
            MonitoringRegistry,
            PostgresMonitoringRegistry,
        )

        abstract = {
            name for name, _ in inspect.getmembers(
                MonitoringRegistry, predicate=inspect.isfunction
            )
        }
        assert abstract == {
            "save_actual_batch", "get_actual_batch", "list_actual_batches",
            "find_actual_batch_idempotent",
            "save_comparison", "get_comparison", "list_comparisons",
            "find_comparison_idempotent",
            "save_decision", "list_decisions",
        }
        for impl in (MemoryMonitoringRegistry, PostgresMonitoringRegistry):
            missing = abstract - {
                name for name, _ in inspect.getmembers(
                    impl, predicate=inspect.isfunction
                )
            }
            assert not missing, (impl.__name__, missing)

    def test_s13_postgres_whitelist_and_parameterization(self):
        source = SERVICE.read_text("utf-8")
        # SELECT-проекции без «SELECT *» (паритет DOCLOG-7 s09).
        assert "SELECT *" not in source
        # Сохранения -- insert-only (append-only контур), без
        # UPDATE/DELETE: старые vintages не переписываются (AC15).
        for forbidden in ("UPDATE ", "DELETE FROM", "DROP "):
            assert forbidden not in source, forbidden
        # SQL -- статические строки без f-интерполяции значений.
        assert not re.search(r'f"SELECT', source)
        assert not re.search(r"f\"INSERT", source)
        # ON CONFLICT DO NOTHING -- идемпотентная посадка.
        assert source.count("ON CONFLICT") == 3
        assert source.count("DO NOTHING") == 3


class TestUIContract:
    def test_s14_ui_client_readonly_paths_and_use_client(self):
        lib = Path("packages/ui/lib/monitoring.ts").read_text("utf-8")
        # UI-клиент read-only по дизайну (панель читает frozen сверки):
        # ровно два запроса -- список и детализация сверок.
        for fragment in ("/monitoring/comparisons",
                         "comparisons/${encodeURIComponent(comparisonId)}"):
            assert fragment in lib, fragment
        assert lib.count("documentationApiUrl(") == 2
        # Ключ/сессия не в URL: cookie-credentials, не query-параметр.
        assert 'credentials: "include"' in lib
        assert "X-API-Key" not in lib
        # Регрессионный пин DOCLOG-8-UI-FIX: "use client" -- первая
        # строка панели (сборка embedded next build).
        panel = Path(
            "packages/ui/components/MonitoringComparisonPanel.tsx"
        ).read_text("utf-8")
        assert panel.splitlines()[0].strip().rstrip(";") == '"use client"'
