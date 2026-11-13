"""F-CERT-H1 (AUTH-CERT, 13.11.2026): unit-контракты прогрева durable-слоёв.

Находка F-CERT-H1: lazy-миграция durable-слоёв внутри первого запроса
самодедлочится (conn A держит незакрытую транзакцию на trace_events,
conn B лениво гоняет ops-каталог с ACCESS EXCLUSIVE ALTER'ами против
неё, поток запроса ждёт conn B). Фикс: обязательный прогрев
``warmup_durable_layers()`` в ``_lifespan`` ДО начала обслуживания
(порядок «миграция до старта api», как в проде и как в harness AUTH-CERT).

Границы unit-уровня: без реальной БД -- фабрики/аксессоры патчатся;
native-оракулы (реальный дедлок-класс, coexistence, /health/ops через
настоящий lifespan) -- tests/integration/test_warmup_fcert_h1.py.
"""

import asyncio
import os
import unittest
from contextlib import ExitStack
from unittest import mock

from apps.api import storage_warmup


# Полный реестр прогрева: новый durable-слой присоединяется сознательно,
# вместе с обновлением этого пина (D5 design).
EXPECTED_LAYERS = (
    "audit",
    "telemetry",
    "session",
    "runs",
    "artifacts",
    "snapshots",
    "documents",
    "lifecycle",
    "support_grants",
    "admin_logs",
    "monitoring",
    "org_profiles",
)


def _required_env(dsn: str) -> dict:
    return {
        "CISSTAT_STORAGE_MODE": "required",
        "DATABASE_URL": dsn,
        "CISSTAT_SESSION_BACKEND": "postgres",
        "CISSTAT_RUNS_BACKEND": "postgres",
    }


def _patch_accessors(stack: ExitStack, replacements: dict) -> None:
    """Подмена аксессоров реестра по имени (patch.dict: ключи dict не
    патчатся атрибутным mock.patch)."""
    stack.enter_context(
        mock.patch.dict(
            "apps.api.storage_warmup._LAYER_ACCESSORS",
            replacements,
            clear=True,
        )
    )


class WarmupModuleContract(unittest.TestCase):
    """Контракт входной точки и реестра слоёв (D3/D5)."""

    def test_01_entrypoints_exist(self) -> None:
        self.assertTrue(callable(storage_warmup.warmup_durable_layers))
        self.assertTrue(callable(storage_warmup.last_warmup_status))

    def test_02_registry_is_complete(self) -> None:
        entries = dict(storage_warmup._LAYERS)
        self.assertEqual(tuple(entries), EXPECTED_LAYERS)
        # Критичность: все слои fail-closed, кроме телеметрии (AC11).
        critical = {name for name, is_critical in entries.items() if is_critical}
        self.assertNotIn("telemetry", critical)
        self.assertEqual(critical, set(EXPECTED_LAYERS) - {"telemetry"})

    def test_03_advisory_mode_is_honest_noop(self) -> None:
        """advisory/auto: ленивый контракт dev/тестов -- фабрики не
        трогаются, соединения не открываются (пин «конструирование
        Postgres-бэкенда не открывает соединение»)."""
        storage_warmup.reset_warmup_status_for_testing()
        env = {
            "CISSTAT_STORAGE_MODE": "advisory",
            "DATABASE_URL": "postgresql://warmup:test@127.0.0.1:5432/db",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            status = storage_warmup.warmup_durable_layers()
        self.assertEqual(status["state"], "skipped")
        self.assertNotIn("layers", status)  # ни один слой не создавался
        recorded = storage_warmup.last_warmup_status()
        self.assertEqual(recorded["state"], "skipped")

    def test_04_memory_env_without_dsn_is_noop(self) -> None:
        """Без DATABASE_URL (чистый dev) прогрев -- no-op без исключений."""
        storage_warmup.reset_warmup_status_for_testing()
        env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
        with mock.patch.dict(os.environ, env, clear=True):
            status = storage_warmup.warmup_durable_layers()
        self.assertEqual(status["state"], "skipped")


class WarmupRequiredModeContract(unittest.TestCase):
    """required-режим: реестр прогревается целиком, отказ -- fail-closed."""

    def _run_required(self, patches: dict) -> dict:
        env = _required_env("postgresql://warmup:test@127.0.0.1:5432/db")
        with mock.patch.dict(os.environ, env, clear=False):
            with ExitStack() as stack:
                _patch_accessors(stack, patches)
                return storage_warmup.warmup_durable_layers()
        raise AssertionError("unreachable")

    def test_05_required_primes_all_layers(self) -> None:
        """Каждый слой реестра получает ensure_schema; статус -- primed."""
        storage_warmup.reset_warmup_status_for_testing()
        calls: list[str] = []

        def make_accessor(name: str):
            def accessor():
                calls.append(name)
                return type(f"Fake{name}", (), {"ensure_schema": lambda self: None})()
            return accessor

        patches = {
            name: make_accessor(name)
            for name in EXPECTED_LAYERS
        }
        status = self._run_required(patches)
        self.assertEqual(status["state"], "primed")
        self.assertEqual(set(status["layers"]), set(EXPECTED_LAYERS))
        self.assertTrue(all(v == "primed" for v in status["layers"].values()))
        self.assertEqual(calls, list(EXPECTED_LAYERS))

    def test_06_memory_backend_layer_is_honest_skip(self) -> None:
        """Слой с backend без ensure_schema (Memory/Redis) -- честный
        skipped, а не подмена статуса."""
        storage_warmup.reset_warmup_status_for_testing()

        def accessor():
            return object()  # ни ensure_schema, ни DDL

        patches = {
            name: accessor
            for name in EXPECTED_LAYERS
        }
        status = self._run_required(patches)
        self.assertEqual(status["state"], "primed")
        self.assertTrue(all(v == "skipped" for v in status["layers"].values()))

    def test_07_critical_layer_failure_fails_closed(self) -> None:
        """Отказ обязательного слоя в required -> RuntimeError (доктрина
        AUDIT-6C: «неверная ... миграция ... роняет старт»), сообщение
        safe_error -- без DSN/секрета."""
        storage_warmup.reset_warmup_status_for_testing()

        def broken_accessor():
            raise ConnectionError("connection refused dsn postgresql://u:secret@h/db")

        patches = {
            "apps.api.storage_warmup._LAYER_ACCESSORS.audit": broken_accessor,
            **{
                name: lambda: None
                for name in EXPECTED_LAYERS
                if name != "audit"
            },
        }
        with self.assertRaises(RuntimeError) as ctx:
            self._run_required(patches)
        message = str(ctx.exception)
        self.assertIn("audit", message)
        self.assertNotIn("postgresql://", message)
        self.assertNotIn("secret", message)
        # Статус зафиксирован ДО подъёма исключения -- /health/ops видит
        # честную причину смерти старта.
        recorded = storage_warmup.last_warmup_status()
        self.assertEqual(recorded["state"], "error")
        self.assertEqual(recorded["layers"]["audit"], "error")

    def test_08_telemetry_failure_is_swallowed_ac11(self) -> None:
        """Контракт AC11: телеметрия никогда не роняет старт; отказ
        прогрева telemetry -- состояние error слоя, общий state
        degraded, warmup завершается штатно."""
        storage_warmup.reset_warmup_status_for_testing()

        def broken_telemetry():
            raise ConnectionError("telemetry down postgresql://u:secret@h/db")

        patches = {
            "apps.api.storage_warmup._LAYER_ACCESSORS.telemetry": broken_telemetry,
            **{
                name: lambda: type(
                    "Fake", (), {"ensure_schema": lambda self: None}
                )()
                for name in EXPECTED_LAYERS
                if name != "telemetry"
            },
        }
        status = self._run_required(patches)
        self.assertEqual(status["state"], "degraded")
        self.assertEqual(status["layers"]["telemetry"], "error")
        self.assertNotIn("secret", str(status))

    def test_09_idempotent_rerun_is_primed(self) -> None:
        """Повторный прогрев (рестарт lifespan/тест) -- идемпотентен:
        ensure_schema каждого слоя вызывается на каждом прогреве (сами
        методы идемпотентны), статус снова primed."""
        storage_warmup.reset_warmup_status_for_testing()
        counters: dict[str, int] = {}

        def make_accessor(name: str):
            class Fake:
                def ensure_schema(self) -> None:
                    counters[name] = counters.get(name, 0) + 1

            return Fake

        patches = {
            name: make_accessor(name)
            for name in EXPECTED_LAYERS
        }
        first = self._run_required(patches)
        second = self._run_required(patches)
        self.assertEqual(first["state"], "primed")
        self.assertEqual(second["state"], "primed")
        self.assertEqual(set(counters.values()), {2})


class EnsureSchemaContract(unittest.TestCase):
    """Контракт ensure_schema на каждом Postgres-слое (D4, эталон --
    PostgresSessionStore.ensure_schema): идемпотентность -- второй вызов
    без DDL; собственное соединение закрывается."""

    def test_10_all_postgres_layers_have_ensure_schema(self) -> None:
        from apps.api.admin_logs import PostgresSupportGrantRegistry
        from apps.api.artifact_store import PostgresArtifactRegistry
        from apps.api.document_jobs import PostgresDocumentRegistry
        from apps.api.document_lifecycle import (
            PostgresDocumentLifecycleRegistry,
        )
        from apps.api.doc_profiles import PostgresOrgProfileRegistry
        from apps.api.monitoring import PostgresMonitoringRegistry
        from apps.api.report_snapshot import PostgresSnapshotRegistry
        from apps.api.research_runs import PostgresResearchRunStore
        from apps.api.security_audit import PostgresAuditSink
        from apps.api.session_store import PostgresSessionStore
        from apps.api.telemetry import PostgresTelemetrySink

        for cls in (
            PostgresSessionStore,
            PostgresAuditSink,
            PostgresTelemetrySink,
            PostgresResearchRunStore,
            PostgresArtifactRegistry,
            PostgresSnapshotRegistry,
            PostgresDocumentRegistry,
            PostgresDocumentLifecycleRegistry,
            PostgresSupportGrantRegistry,
            PostgresMonitoringRegistry,
            PostgresOrgProfileRegistry,
        ):
            self.assertTrue(
                hasattr(cls, "ensure_schema"),
                f"{cls.__name__} lacks ensure_schema",
            )
        # Module-global lazy-DDL слой admin_logs тоже имеет публичный
        # прайм (D5: реестр 12 слоёв).
        from apps.api import admin_logs

        self.assertTrue(callable(admin_logs.ensure_logs_schema))

    def test_11_ensure_schema_second_call_skips_ddl(self) -> None:
        """Эталонная семантика сессии: double-checked флаг -- повторный
        ensure_schema не выполняет run_migrations; отказ не кэшируется."""
        from apps.api.security_audit import PostgresAuditSink

        sink = PostgresAuditSink(dsn="postgresql://u:p@127.0.0.1:5/db")
        fake_conn = mock.MagicMock()
        with (
            mock.patch("psycopg.connect", return_value=fake_conn) as connect,
            mock.patch(
                "apps.api.research_runs.run_migrations", return_value=5
            ) as migrations,
        ):
            sink.ensure_schema()
            sink.ensure_schema()
        self.assertEqual(migrations.call_count, 1)
        self.assertEqual(connect.call_count, 1)
        fake_conn.close.assert_called_once()

    def test_12_ensure_schema_failure_is_not_cached(self) -> None:
        """Отказ миграции НЕ кэшируется (паритет сессии): следующий
        ensure_schema снова пытается прогнать каталог."""
        from apps.api.security_audit import PostgresAuditSink

        sink = PostgresAuditSink(dsn="postgresql://u:p@127.0.0.1:5/db")
        fake_conn = mock.MagicMock()
        with (
            mock.patch("psycopg.connect", return_value=fake_conn),
            mock.patch(
                "apps.api.research_runs.run_migrations",
                side_effect=RuntimeError("ddl boom"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                sink.ensure_schema()
            self.assertFalse(sink._schema_ready)
        with (
            mock.patch("psycopg.connect", return_value=fake_conn),
            mock.patch(
                "apps.api.research_runs.run_migrations", return_value=5
            ) as migrations,
        ):
            sink.ensure_schema()
        self.assertEqual(migrations.call_count, 1)
        self.assertTrue(sink._schema_ready)


class LifespanOrderingContract(unittest.TestCase):
    """Пин порядка старта (D3): фабрики -> прогрев (F-CERT-H1) ->
    worker-credential bootstrap -> телеметрия -> воркеры. Прогрев ДО
    телеметрии/воркеров -- иначе первый telemetry_emit/письмо воркера
    сам выполняет lazy-DDL."""

    def test_13_lifespan_warms_before_telemetry_and_workers(self) -> None:
        import apps.api.main as main_module

        order: list[str] = []

        def record(label, fn):
            def wrapper(*args, **kwargs):
                order.append(label)
                if fn is not None:
                    return fn(*args, **kwargs)

            return wrapper

        async def drive() -> None:
            # required-режим обязателен: ветка прогрева исполняется
            # только в нём (advisory -- честный no-op).
            env = _required_env("postgresql://warmup:test@127.0.0.1:5432/db")
            with mock.patch.dict(os.environ, env, clear=False):
                with (
                mock.patch.object(
                    main_module,
                    "verify_required_storage_backends",
                    record("factories", None),
                ),
                mock.patch(
                    "apps.api.storage_warmup.warmup_durable_layers",
                    record("warmup", None),
                ),
                mock.patch.object(
                    main_module.worker_bootstrap,
                    "startup_check",
                    record("worker_bootstrap", None),
                ),
                mock.patch.object(
                    main_module,
                    "telemetry_emit",
                    record("telemetry", None),
                ),
                mock.patch.object(
                    main_module.delivery_worker,
                    "start_delivery_worker",
                    record("delivery_worker", None),
                ),
                mock.patch.object(
                    main_module.delivery_worker,
                    "stop_delivery_worker",
                    record("delivery_worker_stop", None),
                ),
                mock.patch.object(
                    main_module.document_render_worker,
                    "start_document_render_worker",
                    record("render_worker", None),
                ),
                mock.patch.object(
                    main_module.document_render_worker,
                    "stop_document_render_worker",
                    record("render_worker_stop", None),
                ),
                mock.patch(
                    "apps.api.authentication.demo_sweeper.start",
                    record("demo_sweeper", None),
                ),
                mock.patch(
                    "apps.api.authentication.demo_sweeper.stop",
                    record("demo_sweeper_stop", None),
                ),
                mock.patch(
                    "apps.api.authentication.ops_sweeper.start",
                    record("ops_sweeper", None),
                ),
                mock.patch(
                    "apps.api.authentication.ops_sweeper.stop",
                    record("ops_sweeper_stop", None),
                ),
            ):
                    async with main_module._lifespan(main_module.app):
                        pass

        asyncio.run(drive())
        self.assertIn("factories", order)
        self.assertIn("warmup", order)
        warmup_at = order.index("warmup")
        self.assertGreater(
            warmup_at,
            order.index("factories"),
            "прогрев обязан идти ПОСЛЕ фабрик (fail-closed probes раньше)",
        )
        for label in ("worker_bootstrap", "telemetry", "delivery_worker", "render_worker"):
            self.assertIn(label, order)
            self.assertLess(
                warmup_at,
                order.index(label),
                f"{label} обязан идти ПОСЛЕ прогрева (F-CERT-H1)",
            )


class HealthPeekContract(unittest.TestCase):
    """Peek-семантика статуса для /health/ops (D7): до старта --
    None; секретов нет; reset для тестов."""

    def test_14_peek_before_run_is_none(self) -> None:
        storage_warmup.reset_warmup_status_for_testing()
        self.assertIsNone(storage_warmup.last_warmup_status())

    def test_15_health_payload_has_no_secrets(self) -> None:
        storage_warmup.reset_warmup_status_for_testing()

        def broken_accessor():
            raise ConnectionError(
                "dsn postgresql://u:supersecret@h:5432/db unreachable"
            )

        env = _required_env("postgresql://u:supersecret@h:5432/db")
        with mock.patch.dict(os.environ, env, clear=False):
            with ExitStack() as stack:
                _patch_accessors(
                    stack, {name: broken_accessor for name in EXPECTED_LAYERS}
                )
                with self.assertRaises(RuntimeError):
                    # Отказ первого обязательного слоя -> fail-closed;
                    # статус всё равно зафиксирован для /health/ops.
                    storage_warmup.warmup_durable_layers()
        payload = storage_warmup.last_warmup_status()
        serialized = repr(payload)
        self.assertNotIn("supersecret", serialized)
        self.assertNotIn("postgresql://", serialized)


if __name__ == "__main__":
    unittest.main()
