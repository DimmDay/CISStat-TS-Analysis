# tests/api/test_h29_documents_durable.py
#
# Task ID: DOCLOG-H29-UIHONEST-AUDITVIEW (2026-10-27).
#
# H29 (рекомендация платформе из AUTH-SCENARIO-ANALYST-DOCS §6, база
# a4277b9): довести durable-миграцию до конца -- CISSTAT_STORAGE_MODE
# согласованно для runs/sessions/ДОКУМЕНТОВ. Фабрика
# get_document_registry -- единственный оставшийся компонент БЕЗ
# контракта AUDIT-6C (план §18 п.1; P21/F14):
#
#   1. required: неверная конфигурация/драйвер/недоступная БД ->
#      fail-closed RuntimeError, ТИХИЙ Memory fallback ЗАПРЕЩЁН
#      («required не деградирует незаметно»); сообщение БЕЗ DSN/секрета;
#   2. advisory (default): fallback в Memory допустим, но НЕ тихий --
#      configured/effective/degraded + безопасная причина в snapshot;
#   3. storage_backend_snapshot() честно включает ДОКУМЕНТЫ (и паритет
#      artifacts/snapshots) -- «Документы этого исследования недоступны
#      вашему субъекту» класса S4/S5 больше не прячут memory-контур;
#   4. startup (lifespan) в required-режиме проверяет ВСЕ фабрики
#      durable-контура (runs/session/artifacts/snapshots/documents) ДО
#      начала обслуживания.
#
# Класс S4/S5 (аналитический сценарий 2026-10-27): run потерян при
# живой сессии после рестарта free-tier инстанса -- при durable
# documents-слое это состояние не воспроизводится для документов.

import pytest

from apps.api.document_jobs import (
    MemoryDocumentRegistry,
    PostgresDocumentRegistry,
    get_document_registry,
    reset_document_registry_for_testing,
)

_SECRET_DSN = "postgresql://ci_user:supersecret@db-h29.invalid:5432/cisstat"


@pytest.fixture(autouse=True)
def _isolate_document_factory(monkeypatch):
    """Чистый контекст фабрики документов и диагностики на каждый тест."""
    for name in (
        "CISSTAT_STORAGE_MODE",
        "DATABASE_URL",
        "CISSTAT_DOCUMENTS_BACKEND",
        "CISSTAT_ARTIFACTS_BACKEND",
        "CISSTAT_SNAPSHOTS_BACKEND",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_document_registry_for_testing()
    from apps.api import storage_diagnostics

    storage_diagnostics.reset_storage_diagnostics_for_testing()
    yield
    reset_document_registry_for_testing()
    storage_diagnostics.reset_storage_diagnostics_for_testing()


def _boom_from_env():
    raise RuntimeError(f"connection refused for {_SECRET_DSN}")


class TestRequiredFailClosed:
    def test_required_constructor_failure_is_fail_closed(self, monkeypatch):
        """required + отказ инициализации Postgres -> RuntimeError,
        тихий Memory fallback ЗАПРЕЩЁН; сообщение без DSN/секрета
        (паритет test_progress_audit_6c.TestStorageMode)."""
        from apps.api import document_jobs, storage_diagnostics

        monkeypatch.setenv("CISSTAT_STORAGE_MODE", "required")
        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)
        monkeypatch.setattr(
            document_jobs.PostgresDocumentRegistry, "from_env",
            staticmethod(_boom_from_env),
        )
        with pytest.raises(RuntimeError) as excinfo:
            get_document_registry()
        message = str(excinfo.value)
        assert "required" in message.lower()
        assert "supersecret" not in message
        assert "postgresql://" not in message
        # Состояние фабрики честно фиксирует отказ ДО выброса.
        snapshot = storage_diagnostics.storage_backend_snapshot()
        documents = snapshot["documents_backend"]
        assert documents["configured"] == "postgres"
        assert documents["effective"] == "unavailable"
        assert documents["degraded"] is True
        assert "supersecret" not in str(documents["reason"])

    def test_required_unreachable_db_fails_closed(self, monkeypatch):
        """required + readiness_probe не ok (БД недоступна) ->
        RuntimeError, а не деградация в Memory (P21: probe на выборе)."""
        from apps.api import document_jobs

        monkeypatch.setenv("CISSTAT_STORAGE_MODE", "required")
        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)

        def _probe_fail(self):
            return {"ok": False, "backend": "postgres"}

        monkeypatch.setattr(
            document_jobs.PostgresDocumentRegistry, "from_env",
            staticmethod(lambda: PostgresDocumentRegistry(_SECRET_DSN)),
        )
        monkeypatch.setattr(
            document_jobs.PostgresDocumentRegistry,
            "readiness_probe", _probe_fail,
        )
        with pytest.raises(RuntimeError) as excinfo:
            get_document_registry()
        assert "required" in str(excinfo.value).lower()

    def test_required_never_returns_memory(self, monkeypatch):
        """Инвариант «required не подменяется памятью» даже если Memory
        класс доступен: отказ есть отказ."""
        from apps.api import document_jobs

        monkeypatch.setenv("CISSTAT_STORAGE_MODE", "required")
        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)
        monkeypatch.setattr(
            document_jobs.PostgresDocumentRegistry, "from_env",
            staticmethod(_boom_from_env),
        )
        with pytest.raises(RuntimeError):
            get_document_registry()
        # Singleton НЕ создан: следующий вызов тоже fail-closed.
        with pytest.raises(RuntimeError):
            get_document_registry()


class TestAdvisoryExplicitDegradation:
    def test_advisory_fallback_is_explicit_not_silent(self, monkeypatch):
        """advisory + отказ Postgres -> Memory ДОПУСТИМ, но состояние
        честное: configured=postgres, effective=memory, degraded=True,
        причина без DSN + событие fallback в snapshot."""
        from apps.api import document_jobs, storage_diagnostics

        monkeypatch.delenv("CISSTAT_STORAGE_MODE", raising=False)
        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)
        monkeypatch.setattr(
            document_jobs.PostgresDocumentRegistry, "from_env",
            staticmethod(_boom_from_env),
        )
        registry = get_document_registry()
        assert isinstance(registry, MemoryDocumentRegistry)
        snapshot = storage_diagnostics.storage_backend_snapshot()
        documents = snapshot["documents_backend"]
        assert documents["configured"] == "postgres"
        assert documents["effective"] == "memory"
        assert documents["degraded"] is True
        assert "supersecret" not in str(documents["reason"])
        assert "postgresql://" not in str(documents["reason"])
        assert snapshot["degraded"] is True
        assert snapshot["fallback_events"], "событие fallback зафиксировано"
        assert snapshot["fallback_events"][-1]["component"] == "documents"

    def test_explicit_memory_is_chosen_not_fallback(self, monkeypatch):
        """CISSTAT_DOCUMENTS_BACKEND=memory при заданном DATABASE_URL --
        ВЫБРАННЫЙ backend (документированный приоритет), НЕ деградация:
        configured=memory, degraded=False."""
        from apps.api import storage_diagnostics

        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)
        monkeypatch.setenv("CISSTAT_DOCUMENTS_BACKEND", "memory")
        get_document_registry()
        snapshot = storage_diagnostics.storage_backend_snapshot()
        documents = snapshot["documents_backend"]
        assert documents["configured"] == "memory"
        assert documents["effective"] == "memory"
        assert documents["degraded"] is False

    def test_auto_without_config_is_memory(self, monkeypatch):
        """Без DATABASE_URL и backend -- auto -> Memory, не деградация."""
        from apps.api import storage_diagnostics

        get_document_registry()
        snapshot = storage_diagnostics.storage_backend_snapshot()
        documents = snapshot["documents_backend"]
        assert documents["configured"] == "auto"
        assert documents["effective"] == "memory"
        assert documents["degraded"] is False

    def test_advisory_probe_fail_still_selects_postgres_lazily(self, monkeypatch):
        """advisory сохраняет ленивый контракт (паритет runs): выбор
        Postgres при живом from_env НЕ деградирует из-за probe -- probe
        в advisory не выполняется, недоступность видна в /health/ops
        readiness (сертифицированный контракт ленивого конструирования)."""
        from apps.api import document_jobs

        monkeypatch.delenv("CISSTAT_STORAGE_MODE", raising=False)
        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)

        def _probe_fail(self):
            return {"ok": False, "backend": "postgres"}

        monkeypatch.setattr(
            document_jobs.PostgresDocumentRegistry, "from_env",
            staticmethod(lambda: PostgresDocumentRegistry(_SECRET_DSN)),
        )
        monkeypatch.setattr(
            document_jobs.PostgresDocumentRegistry,
            "readiness_probe", _probe_fail,
        )
        registry = get_document_registry()
        assert isinstance(registry, PostgresDocumentRegistry)


class TestSnapshotParity:
    def test_snapshot_includes_documents_component(self, monkeypatch):
        """storage_backend_snapshot честно включает documents_backend
        (класс S4/S5 не прячется за runs/session)."""
        from apps.api import storage_diagnostics

        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)
        monkeypatch.setenv("CISSTAT_DOCUMENTS_BACKEND", "memory")
        get_document_registry()
        snapshot = storage_diagnostics.storage_backend_snapshot()
        assert "documents_backend" in snapshot
        assert snapshot["documents_backend"]["configured"] == "memory"

    def test_snapshot_includes_artifacts_and_snapshots(self, monkeypatch):
        """Паритет durable-слоя: snapshot включает artifacts_backend и
        snapshots_backend (фабрики уже имеют AUDIT-6C контракт)."""
        from apps.api import storage_diagnostics

        snapshot = storage_diagnostics.storage_backend_snapshot()
        assert "artifacts_backend" in snapshot
        assert "snapshots_backend" in snapshot
        assert snapshot["artifacts_backend"]["configured"] == "unknown"
        assert snapshot["snapshots_backend"]["effective"] == "not_initialized"

    def test_invalid_documents_backend_value_fails_fast(self, monkeypatch):
        """Опечатка в CISSTAT_DOCUMENTS_BACKEND -- fail fast, не тихий
        auto->memory (паритет get_storage_mode)."""
        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)
        monkeypatch.setenv("CISSTAT_DOCUMENTS_BACKEND", "postgers")
        with pytest.raises(RuntimeError):
            get_document_registry()


class TestRequiredStartupCheck:
    def test_startup_verifier_checks_documents_factory(self, monkeypatch):
        """Startup-проверка required-режима вызывает фабрику ДОКУМЕНТОВ:
        отказ documents роняет старт (fail-closed), а не обнаруживается
        на первом запросе «Документов»."""
        from apps.api import main as api_main

        monkeypatch.setenv("CISSTAT_STORAGE_MODE", "required")
        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)
        calls = []

        def _ok():
            calls.append("ok")

        def _boom():
            calls.append("documents")
            raise RuntimeError("documents required backend unavailable")

        monkeypatch.setattr(api_main, "_startup_factory_runs", _ok)
        monkeypatch.setattr(api_main, "_startup_factory_session", _ok)
        monkeypatch.setattr(api_main, "_startup_factory_artifacts", _ok)
        monkeypatch.setattr(api_main, "_startup_factory_snapshots", _ok)
        monkeypatch.setattr(api_main, "_startup_factory_documents", _boom)
        with pytest.raises(RuntimeError):
            api_main.verify_required_storage_backends()
        assert calls == ["ok", "ok", "ok", "ok", "documents"]

    def test_startup_verifier_covers_all_durable_components(self, monkeypatch):
        """Контракт startup: runs, session, artifacts, snapshots,
        documents -- все пять фабрик проверяются в required-режиме
        (H29: «согласованно», документный слой не исключение)."""
        from apps.api import main as api_main

        monkeypatch.setenv("CISSTAT_STORAGE_MODE", "required")
        names = tuple(api_main._startup_required_factories)
        assert {"runs", "session", "artifacts", "snapshots", "documents"} == set(names)

    def test_startup_verifier_noop_in_advisory(self, monkeypatch):
        """advisory: startup-проверка не провоцирует фабрики (ленивый
        контракт dev/тестов сохранён)."""
        from apps.api import main as api_main

        monkeypatch.delenv("CISSTAT_STORAGE_MODE", raising=False)

        def _unexpected():
            raise AssertionError("advisory не должен провоцировать фабрики")

        for name in ("runs", "session", "artifacts", "snapshots", "documents"):
            monkeypatch.setattr(
                api_main, f"_startup_factory_{name}", _unexpected, raising=False,
            )
        assert api_main.verify_required_storage_backends() is None
