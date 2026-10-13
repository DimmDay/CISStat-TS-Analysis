# tests/api/test_progress_audit_6c.py
"""Acceptance-тесты задачи AUDIT-6C (plan_progress_audit.md §18):
backend, health и операционные логи контура «Прогресс».

Контракт (docs/progress_audit_contract.md, аддендум v1.6-6C §26; план
§18; spec_progress_audit.md §7/§8.3/§8.4, F14/P21, F15/P22, H29/H30):

  R1 (п.1).  Режимы хранения: CISSTAT_STORAGE_MODE=required|advisory
             (default advisory). При explicit required Postgres
             неверная конфигурация / отсутствие драйвера / несовместимая
             миграция / недоступная БД ЗАПРЕЩАЮТ тихий Memory fallback
             (P21/F14: fail-closed RuntimeError). Dev/advisory fallback
             допустим, но effective backend ЯВЕН: snapshot фабрик
             несёт configured/effective/degraded + безопасную причину.
  R2 (п.2).  Драйвер Postgres (psycopg) объявлен в requirements и
             проверяется сборкой (см. Dockerfile; здесь -- честная
             деградация диспетчера моделей при отсутствии dependency-
             групп: import apps.api.main работает в облегчённой среде,
             fail-closed перенесён в точку исполнения -- Донастройка_2
             п.2, разблокировка интеграционной приёмки AUDIT-CERT).
  R3 (п.3).  Health разделён: /health -- liveness (тело прежнее);
             GET /health/ops -- operational diagnostics: backend
             (configured/effective), storage readiness, delivery
             backlog/возраст, projection lag, degraded mode, worker,
             models dispatch. НЕ выдаёт URL БД, tokens, сырые
             exception payload'ы.
  R4 (п.4).  Операционные логи несут request/operation/event/run/
             context ids, результат попытки и безопасную причину
             отказа (safe_error: DSN/пароли/tokens редактируются).
             Научные факты не заменяются sampled-логами (хук --
             advisory-маркер сохраняется).
  R5 (п.5).  In-process worker восстановления (AUDIT-6B остаток):
             авто-старт в lifespan, идемпотентный singleton,
             env-выключатель, состояние в /health/ops; ручной runner
             6B сохраняется.
  R6 (п.6).  H29/H30: доступ к deployment-логам/БД Render в этой
             сессии не предоставлен -- остаются незакрытыми
             operational acceptance-пунктами (контракт §26.6), без
             «production certified».

Живой Postgres (pgserver, тот же контракт CISSTAT_TEST_PG_DSN, что
6A/6B): required-режим на живой БД, probe, backlog age, worker.
Без DSN -- честный skip живой половины паритета.
"""
from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.research_runs import (
    MemoryResearchRunStore,
    PostgresResearchRunStore,
    reset_dataset_file_store_for_testing,
    reset_research_run_store_for_testing,
)
from apps.api.session_store import (
    AnalysisSession,
    MemorySessionStore,
    get_session_store,
    reset_session_store_for_testing,
)

client = TestClient(app)

PG_DSN = os.environ.get("CISSTAT_TEST_PG_DSN", "")

_SECRET_DSN = (
    "postgresql://ci_user:supersecret@db-host-6c.invalid:5432/cisstat"
)
_REDIS_SECRET_URL = "redis://cache_user:redispass@redis-host-6c.invalid:6379/0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── изоляция окружения фабрик (каждый тест -- чистый контекст) ───────


@pytest.fixture(autouse=True)
def _isolate_factories(monkeypatch):
    for name in (
        "CISSTAT_STORAGE_MODE",
        "DATABASE_URL",
        "CISSTAT_RUNS_BACKEND",
        "REDIS_URL",
        "CISSTAT_SESSION_BACKEND",
        "CISSTAT_DELIVERY_WORKER_ENABLED",
        "CISSTAT_DELIVERY_WORKER_INTERVAL",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_research_run_store_for_testing()
    reset_session_store_for_testing()
    reset_dataset_file_store_for_testing()
    try:
        from apps.api import storage_diagnostics

        storage_diagnostics.reset_storage_diagnostics_for_testing()
    except ImportError:  # RED: модуль ещё не реализован
        pass
    try:
        from apps.api import delivery_worker

        delivery_worker.reset_delivery_worker_for_testing()
    except ImportError:  # RED: модуль ещё не реализован
        pass
    yield
    reset_research_run_store_for_testing()
    reset_session_store_for_testing()


# ── сиды (паттерн AUDIT-6B: upload -> run/context) ───────────────────


def _monitor_csv() -> str:
    import pandas as pd

    idx = [datetime(2026, 2, 1) + timedelta(days=i) for i in range(150)]
    frame = pd.DataFrame(
        {
            "date": [d.strftime("%Y-%m-%d") for d in idx],
            "value": [120.0 + i for i in range(150)],
            "humidity": [40.0 + (i % 7) * 0.5 for i in range(150)],
        }
    )
    return frame.to_csv(index=False)


def _upload() -> None:
    response = client.post(
        "/v1/internal/upload",
        files={"file": (
            "forecast_monitor_synthetic_n150.csv",
            io.BytesIO(_monitor_csv().encode()),
            "text/csv",
        )},
    )
    assert response.status_code == 200, response.text


def _seed() -> tuple[str, str]:
    _upload()
    trace = client.get("/v1/progress/trace").json()
    run_id = trace.get("run_id") or ""
    context_id = trace.get("context_id") or ""
    assert run_id and context_id, "seed: загрузка должна фиксировать запуск"
    return run_id, context_id


def _post_map(run_id: str, context_id: str, report_id: str):
    from apps.api.routers.progress import EDA_CHECK_STATUS_VALUES
    from app.core.pipeline_graph import STAGE_NODES

    checks = {
        node_id: list(EDA_CHECK_STATUS_VALUES)[i % len(EDA_CHECK_STATUS_VALUES)]
        for i, node_id in enumerate(STAGE_NODES["eda"])
    }
    return client.post(
        "/v1/progress/eda-checks",
        json={
            "checks": checks,
            "schema_version": 2,
            "run_id": run_id,
            "context_id": context_id,
            "report_id": report_id,
        },
    )


def _inject_cache_save_failure(monkeypatch, times: int = 1) -> None:
    """Одноразовый отказ сохранения слоя 1 (Redis-семантика копий --
    тот же честный паттерн, что AUDIT-6B)."""
    from copy import deepcopy

    original_save = MemorySessionStore.save
    original_get = MemorySessionStore.get
    state = {"left": times}

    def failing_save(self, session):
        if state["left"] > 0:
            state["left"] -= 1
            raise RuntimeError("injected cache failure")
        return original_save(self, session)

    def copy_get(self, session_id):
        stored = original_get(self, session_id)
        return deepcopy(stored) if stored is not None else None

    monkeypatch.setattr(MemorySessionStore, "save", failing_save)
    monkeypatch.setattr(MemorySessionStore, "get", copy_get)


# ════════════════════════════════════════════════════════════════════
# R1: режимы хранения (P21/F14 fail-closed required)
# ════════════════════════════════════════════════════════════════════


class TestStorageMode:
    def test_required_constructor_failure_is_fail_closed(self, monkeypatch):
        """P21 в required: Postgres не инициализируется -> RuntimeError,
        тихий Memory fallback ЗАПРЕЩЁН; сообщение без DSN/секрета."""
        from apps.api import research_runs, storage_diagnostics

        monkeypatch.setenv("CISSTAT_STORAGE_MODE", "required")
        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)

        def _boom():
            raise RuntimeError(f"connection refused for {_SECRET_DSN}")

        monkeypatch.setattr(
            research_runs.PostgresResearchRunStore, "from_env", staticmethod(_boom)
        )
        with pytest.raises(RuntimeError) as excinfo:
            research_runs.get_research_run_store()
        message = str(excinfo.value)
        assert "required" in message.lower()
        assert "supersecret" not in message
        assert "postgresql://" not in message
        # состояние фабрики честно фиксирует отказ до выброса
        snapshot = storage_diagnostics.storage_backend_snapshot()
        assert snapshot["storage_mode"] == "required"
        assert snapshot["runs_backend"]["configured"] == "postgres"

    def test_required_unreachable_db_fails_closed(self, monkeypatch):
        """БД недоступна после startup (probe fail) в required ->
        RuntimeError (fail-closed), а не деградация в Memory."""
        from apps.api import research_runs

        monkeypatch.setenv("CISSTAT_STORAGE_MODE", "required")
        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)
        monkeypatch.setattr(
            PostgresResearchRunStore,
            "readiness_probe",
            lambda self: {
                "ok": False,
                "backend": "postgres",
                "error": "connection refused (safe reason)",
            },
        )
        with pytest.raises(RuntimeError) as excinfo:
            research_runs.get_research_run_store()
        assert "required" in str(excinfo.value).lower()
        assert "supersecret" not in str(excinfo.value)

    def test_required_missing_driver_fails_closed(self, monkeypatch):
        """«Нет драйвера» в required: import psycopg невозможен ->
        fail-closed RuntimeError (никакого Memory fallback)."""
        from apps.api import research_runs

        monkeypatch.setenv("CISSTAT_STORAGE_MODE", "required")
        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)
        monkeypatch.setitem(sys.modules, "psycopg", None)
        with pytest.raises(RuntimeError) as excinfo:
            research_runs.get_research_run_store()
        message = str(excinfo.value).lower()
        assert "required" in message
        assert "psycopg" in message or "driver" in message or "import" in message

    def test_required_incompatible_migration_fails_closed(self, monkeypatch):
        """«Несовместимая миграция» в required: probe видит отсутствие
        таблиц outbox (несовместимая схема) -> fail-closed."""
        from apps.api import research_runs

        monkeypatch.setenv("CISSTAT_STORAGE_MODE", "required")
        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)
        monkeypatch.setattr(
            PostgresResearchRunStore,
            "readiness_probe",
            lambda self: {
                "ok": False,
                "backend": "postgres",
                "error": 'relation "progress_delivery_outbox" does not exist',
            },
        )
        with pytest.raises(RuntimeError):
            research_runs.get_research_run_store()

    def test_advisory_postgres_failure_degrades_explicitly(self, monkeypatch):
        """Dev/advisory fallback ДОПУСТИМ, но effective backend ЯВЕН:
        Memory + configured=postgres + degraded=True + безопасная
        причина (P21/F14: «тихий» запрещён даже в advisory)."""
        from apps.api import research_runs, storage_diagnostics

        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)

        def _boom():
            raise RuntimeError(f"connection refused for {_SECRET_DSN}")

        monkeypatch.setattr(
            research_runs.PostgresResearchRunStore, "from_env", staticmethod(_boom)
        )
        store = research_runs.get_research_run_store()
        assert isinstance(store, research_runs.MemoryResearchRunStore)
        snapshot = storage_diagnostics.storage_backend_snapshot()
        runs_backend = snapshot["runs_backend"]
        assert runs_backend["configured"] == "postgres"
        assert runs_backend["effective"] == "memory"
        assert runs_backend["degraded"] is True
        assert "supersecret" not in runs_backend["reason"]
        assert "postgresql://" not in runs_backend["reason"]
        assert snapshot["degraded"] is True
        assert snapshot["fallback_events"], "событие fallback зафиксировано"

    def test_explicit_memory_is_visible_not_silent(self, monkeypatch):
        """CISSTAT_RUNS_BACKEND=memory при заданном DATABASE_URL -- это
        ВЫБРАННЫЙ memory (документированный приоритет), observable в
        snapshot: configured=memory, degraded=False (не silent-fallback)."""
        from apps.api import research_runs, storage_diagnostics

        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)
        monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
        research_runs.get_research_run_store()
        snapshot = storage_diagnostics.storage_backend_snapshot()
        assert snapshot["runs_backend"]["configured"] == "memory"
        assert snapshot["runs_backend"]["effective"] == "memory"
        assert snapshot["runs_backend"]["degraded"] is False

    def test_auto_without_config_is_memory(self, monkeypatch):
        from apps.api import research_runs, storage_diagnostics

        store = research_runs.get_research_run_store()
        assert isinstance(store, research_runs.MemoryResearchRunStore)
        snapshot = storage_diagnostics.storage_backend_snapshot()
        assert snapshot["runs_backend"]["configured"] == "auto"
        assert snapshot["runs_backend"]["effective"] == "memory"
        assert snapshot["runs_backend"]["degraded"] is False

    def test_invalid_storage_mode_fails_fast(self, monkeypatch):
        from apps.api import research_runs

        monkeypatch.setenv("CISSTAT_STORAGE_MODE", "prod-please")
        with pytest.raises(RuntimeError):
            research_runs.get_research_run_store()

    def test_factory_fallback_log_has_no_secrets(self, caplog, monkeypatch):
        """Операционный лог фабрики: безопасная причина, без DSN/секрета."""
        import logging as _logging

        from apps.api import research_runs

        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)

        def _boom():
            raise RuntimeError(f"connection refused for {_SECRET_DSN}")

        monkeypatch.setattr(
            research_runs.PostgresResearchRunStore, "from_env", staticmethod(_boom)
        )
        with caplog.at_level(_logging.ERROR, logger="apps.api.research_runs"):
            research_runs.get_research_run_store()
        texts = [record.getMessage() for record in caplog.records]
        assert texts, "fallback должен попадать в operational log"
        joined = "\n".join(texts)
        assert "supersecret" not in joined
        assert "postgresql://" not in joined


# ════════════════════════════════════════════════════════════════════
# R1: session store (тот же контракт режимов для Redis)
# ════════════════════════════════════════════════════════════════════


class TestSessionStoreMode:
    def test_required_redis_failure_fails_closed(self, monkeypatch):
        from apps.api import session_store, storage_diagnostics

        monkeypatch.setenv("CISSTAT_STORAGE_MODE", "required")
        monkeypatch.setenv("REDIS_URL", _REDIS_SECRET_URL)

        def _boom():
            raise RuntimeError(f"cannot connect to {_REDIS_SECRET_URL}")

        monkeypatch.setattr(
            session_store.RedisSessionStore, "from_env", staticmethod(_boom)
        )
        with pytest.raises(RuntimeError) as excinfo:
            session_store.get_session_store()
        message = str(excinfo.value)
        assert "required" in message.lower()
        assert "redispass" not in message
        assert "redis://" not in message
        snapshot = storage_diagnostics.storage_backend_snapshot()
        assert snapshot["session_backend"]["configured"] == "redis"

    def test_advisory_redis_failure_degrades_explicitly(self, monkeypatch):
        from apps.api import session_store, storage_diagnostics

        monkeypatch.setenv("REDIS_URL", _REDIS_SECRET_URL)

        def _boom():
            raise RuntimeError(f"cannot connect to {_REDIS_SECRET_URL}")

        monkeypatch.setattr(
            session_store.RedisSessionStore, "from_env", staticmethod(_boom)
        )
        store = session_store.get_session_store()
        assert isinstance(store, MemorySessionStore)
        snapshot = storage_diagnostics.storage_backend_snapshot()
        session_backend = snapshot["session_backend"]
        assert session_backend["configured"] == "redis"
        assert session_backend["effective"] == "memory"
        assert session_backend["degraded"] is True
        assert "redispass" not in session_backend["reason"]
        assert snapshot["degraded"] is True

    def test_memory_default_is_not_degraded(self, monkeypatch):
        from apps.api import session_store, storage_diagnostics

        session_store.get_session_store()
        snapshot = storage_diagnostics.storage_backend_snapshot()
        assert snapshot["session_backend"]["configured"] == "auto"
        assert snapshot["session_backend"]["effective"] == "memory"
        assert snapshot["session_backend"]["degraded"] is False


# ════════════════════════════════════════════════════════════════════
# R3/R4: safe_error (безопасная причина без секретов)
# ════════════════════════════════════════════════════════════════════


class TestSafeError:
    def test_redacts_urls_passwords_tokens(self):
        from apps.api.storage_diagnostics import safe_error

        raw = (
            "connection failed for postgresql://admin:p@ssw0rd@db.internal:5432/db; "
            "also redis://user:secret@cache:6379 and password=topsecret "
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9"
        )
        safe = safe_error(raw)
        assert "db.internal" not in safe
        assert "p@ssw0rd" not in safe
        assert "secret@cache" not in safe
        assert "topsecret" not in safe
        assert "eyJhbGciOiJIUzI1NiJ9" not in safe
        assert safe, "причина остаётся содержательной (не пустая)"

    def test_clips_length(self):
        from apps.api.storage_diagnostics import safe_error

        safe = safe_error("x" * 5000)
        assert len(safe) <= 320

    def test_non_exception_input(self):
        from apps.api.storage_diagnostics import safe_error

        assert safe_error(None) == "unknown error"
        assert safe_error(Exception("boom")) == "boom"


# ════════════════════════════════════════════════════════════════════
# R3: readiness probes хранилищ (по требованию, без side-эффектов)
# ════════════════════════════════════════════════════════════════════


class TestReadinessProbe:
    def test_memory_run_store_probe_ok(self):
        probe = MemoryResearchRunStore().readiness_probe()
        assert probe["ok"] is True
        assert probe["backend"] == "memory"

    def test_memory_session_probe_ok(self):
        probe = MemorySessionStore().readiness_probe()
        assert probe["ok"] is True
        assert probe["backend"] == "memory"

    def test_postgres_probe_failure_is_safe(self, monkeypatch):
        """БД недоступна: probe честно ok=False, причина безопасная
        (без DSN), латентность замерена."""
        import psycopg

        from apps.api.storage_diagnostics import safe_error  # noqa: F401

        def _boom(*args, **kwargs):
            raise RuntimeError(f"connect to {_SECRET_DSN} refused")

        monkeypatch.setattr(psycopg, "connect", _boom)
        store = PostgresResearchRunStore(dsn=_SECRET_DSN)
        probe = store.readiness_probe()
        assert probe["ok"] is False
        assert probe["backend"] == "postgres"
        assert "supersecret" not in probe["error"]
        assert "postgresql://" not in probe["error"]
        assert "latency_ms" in probe

    def test_postgres_probe_live_ok(self, pg_store):
        probe = pg_store.readiness_probe()
        assert probe["ok"] is True
        assert probe["backend"] == "postgres"

    def test_backlog_age_seconds_memory(self):
        """Возраст старейшего pending-обязательства -- основа
        delivery backlog age в health (паритет Memory/Postgres)."""
        from apps.api.delivery_outbox import (
            DeliveryTask,
            STATE_PENDING,
            bind_idempotency_key,
        )

        store = MemoryResearchRunStore()
        outbox = store.delivery_outbox
        old_iso = (
            datetime.now(timezone.utc) - timedelta(minutes=5)
        ).isoformat()
        task = bind_idempotency_key(
            DeliveryTask(
                operation_id="op-6c-age",
                idempotency_key="report:R6C:op-6c-age",
                run_id="R6C",
                payload={"session_id": "S-6C", "events": []},
                created_at=old_iso,
                updated_at=old_iso,
            ),
            "report:R6C:op-6c-age",
        )
        outbox.register(task)
        assert outbox.get_task("op-6c-age").state == STATE_PENDING
        age = outbox.backlog_age_seconds(_now_iso())
        assert age is not None
        assert 290 <= age <= 400
        outbox.mark_delivered("op-6c-age", delivered_at=_now_iso())
        assert outbox.backlog_age_seconds(_now_iso()) is None

    def test_backlog_age_seconds_live_parity(self, pg_store):
        from apps.api.delivery_outbox import (
            DeliveryTask,
            bind_idempotency_key,
        )
        from apps.api.research_runs import ResearchRun

        # FK миграции 0005: обязательство ссылается на существующий run.
        pg_store.upsert_run(
            ResearchRun(
                run_id="R6C",
                session_id="S-6C",
                dataset_fingerprint="fp-6c",
                dataset_name="ops-age",
            )
        )
        outbox = pg_store.delivery_outbox
        task = bind_idempotency_key(
            DeliveryTask(
                operation_id="op-6c-pg-age",
                idempotency_key="report:R6C:op-6c-pg-age",
                run_id="R6C",
                payload={"session_id": "S-6C", "events": []},
            ),
            "report:R6C:op-6c-pg-age",
        )
        outbox.register(task)
        age = outbox.backlog_age_seconds(_now_iso())
        assert age is not None and age >= 0
        outbox.mark_delivered("op-6c-pg-age", delivered_at=_now_iso())
        assert outbox.backlog_age_seconds(_now_iso()) is None


# ════════════════════════════════════════════════════════════════════
# R3: health endpoints (liveness прежний; ops -- operational)
# ════════════════════════════════════════════════════════════════════


class TestOpsHealthEndpoint:
    def test_liveness_body_unchanged(self):
        """Render healthCheckPath: тело /health сохранено (совместимость
        деплой-контракта; liveness не зависит от состояния БД)."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_ops_health_shape(self, monkeypatch):
        monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
        from apps.api import research_runs

        research_runs.get_research_run_store()
        resp = client.get("/health/ops")
        assert resp.status_code == 200
        body = resp.json()
        for key in (
            "status",
            "generated_at",
            "storage_mode",
            "runs_backend",
            "session_backend",
            "readiness",
            "delivery",
            "worker",
            "models_dispatch",
        ):
            assert key in body, key
        assert body["status"] in {"ok", "degraded"}
        assert body["storage_mode"] in {"advisory", "required"}
        for backend_key in ("configured", "effective", "degraded"):
            assert backend_key in body["runs_backend"]
        assert "runs" in body["readiness"] and "session" in body["readiness"]
        assert "backlog" in body["delivery"]
        assert "ready" in body["models_dispatch"]
        assert body["models_dispatch"]["ready"] is True

    def test_ops_health_no_secrets(self, monkeypatch):
        """Health не выдаёт URL БД/tokens: даже при настроенном Postgres
        с секретом в ответе нет ни DSN, ни хоста, ни секрета."""
        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)
        from apps.api import research_runs

        research_runs.get_research_run_store()
        resp = client.get("/health/ops")
        assert resp.status_code == 200
        text = resp.text
        assert "supersecret" not in text
        assert "postgresql://" not in text
        assert "db-host-6c.invalid" not in text

    def test_ops_health_reports_degraded_after_fallback(self, monkeypatch):
        from apps.api import research_runs

        monkeypatch.setenv("DATABASE_URL", _SECRET_DSN)

        def _boom():
            raise RuntimeError(f"connection refused for {_SECRET_DSN}")

        monkeypatch.setattr(
            research_runs.PostgresResearchRunStore, "from_env", staticmethod(_boom)
        )
        research_runs.get_research_run_store()  # advisory fallback -> Memory
        body = client.get("/health/ops").json()
        assert body["status"] == "degraded"
        assert body["runs_backend"]["degraded"] is True
        assert body["runs_backend"]["effective"] == "memory"
        assert body["fallback_events"], "события fallback видны в health"

    def test_ops_health_backlog_and_projection_lag_visible(self, monkeypatch):
        """Backlog/возраст/projection lag видны в health (план §18 RED:
        «backlog/lag видны»)."""
        from apps.api import research_runs
        from apps.api.delivery_outbox import DeliveryTask, bind_idempotency_key

        monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
        store = research_runs.get_research_run_store()
        old_iso = (
            datetime.now(timezone.utc) - timedelta(minutes=2)
        ).isoformat()
        store.delivery_outbox.register(
            bind_idempotency_key(
                DeliveryTask(
                    operation_id="op-health-1",
                    idempotency_key="report:RH:op-health-1",
                    run_id="RH",
                    payload={"session_id": "SH", "events": []},
                    created_at=old_iso,
                    updated_at=old_iso,
                ),
                "report:RH:op-health-1",
            )
        )
        body = client.get("/health/ops").json()
        backlog = body["delivery"]["backlog"]
        assert backlog["pending"] == 1
        assert backlog["delivered"] == 0
        lag = body["delivery"]["projection_lag"]
        assert lag["pending_obligations"] == 1
        age = body["delivery"]["oldest_pending_age_seconds"]
        assert age is not None and age >= 100


# ════════════════════════════════════════════════════════════════════
# R5: in-process worker восстановления (остаток AUDIT-6B)
# ════════════════════════════════════════════════════════════════════


class TestDeliveryWorker:
    def _pending_task_from_map(self, monkeypatch):
        """Required-карта с отказом cache -> pending-обязательство в
        outbox (тот же honest-паттерн, что AUDIT-6B)."""
        run_id, context_id = _seed()
        _inject_cache_save_failure(monkeypatch, times=1)
        resp = _post_map(run_id, context_id, "report-6c-worker")
        assert resp.status_code == 500, resp.text
        return run_id, "report-6c-worker"

    def test_run_once_delivers_pending_task(self, monkeypatch):
        from apps.api import delivery_worker, research_runs

        run_id, report_id = self._pending_task_from_map(monkeypatch)
        run_store = research_runs.get_research_run_store()
        task = run_store.delivery_outbox.get_task(report_id)
        assert task is not None and task.state == "pending"

        worker = delivery_worker.DeliveryWorker(
            run_store, interval=3600, session_store=get_session_store()
        )
        report = worker.run_once()
        assert report["delivery"]["delivered"] >= 1
        assert (
            run_store.delivery_outbox.get_task(report_id).state == "delivered"
        )
        # проекция слоя 1 восстановлена worker'ом (не повторная операция)
        session_id = client.cookies.get("cisstat_session_id") or ""
        session = get_session_store().get(session_id)
        assert session is not None
        assert any(
            item.get("event_type") == "eda_check_status"
            for item in session.pipeline_trace
        )
        status = worker.status()
        assert status["last_summary"]["delivery"]["delivered"] >= 1
        assert status["consecutive_errors"] == 0

    def test_run_once_twice_idempotent(self, monkeypatch):
        from apps.api import delivery_worker, research_runs

        run_id, report_id = self._pending_task_from_map(monkeypatch)
        run_store = research_runs.get_research_run_store()
        worker = delivery_worker.DeliveryWorker(
            run_store, interval=3600, session_store=get_session_store()
        )
        first = worker.run_once()
        second = worker.run_once()
        assert first["delivery"]["delivered"] >= 1
        assert second["delivery"]["delivered"] == 0
        assert second["delivery"]["due"] == 0

    def test_error_resilience_and_recovery(self, monkeypatch):
        """Сбой цикла не убивает worker: consecutive_errors растёт,
        причина безопасная; успешный цикл сбрасывает счётчик."""
        from apps.api import delivery_worker, research_runs

        run_store = research_runs.get_research_run_store()

        def _boom(*args, **kwargs):
            raise RuntimeError(
                f"pg down {_SECRET_DSN}"
            )

        monkeypatch.setattr(
            delivery_worker, "run_delivery_recovery", _boom
        )
        worker = delivery_worker.DeliveryWorker(run_store, interval=3600)
        worker.run_once()
        status = worker.status()
        assert status["consecutive_errors"] == 1
        assert "supersecret" not in (status["last_error"] or "")
        assert "postgresql://" not in (status["last_error"] or "")
        monkeypatch.undo()
        worker.run_once()
        assert worker.status()["consecutive_errors"] == 0
        assert worker.status()["last_error"] is None

    def test_env_disable(self, monkeypatch):
        from apps.api import delivery_worker

        monkeypatch.setenv("CISSTAT_DELIVERY_WORKER_ENABLED", "0")
        assert delivery_worker.start_delivery_worker() is None
        status = delivery_worker.delivery_worker_status()
        assert status["enabled"] is False
        assert status["running"] is False

    def test_env_interval_clamped(self, monkeypatch):
        from apps.api import delivery_worker

        monkeypatch.setenv("CISSTAT_DELIVERY_WORKER_INTERVAL", "1")
        assert delivery_worker.worker_interval_from_env() == (
            delivery_worker.MIN_INTERVAL_SECONDS
        )
        monkeypatch.setenv("CISSTAT_DELIVERY_WORKER_INTERVAL", "0")
        assert delivery_worker.worker_interval_from_env() is None
        monkeypatch.setenv("CISSTAT_DELIVERY_WORKER_INTERVAL", "junk")
        assert delivery_worker.worker_interval_from_env() == (
            delivery_worker.DEFAULT_INTERVAL_SECONDS
        )

    def test_singleton_idempotent_and_stop(self, monkeypatch):
        from apps.api import delivery_worker

        first = delivery_worker.start_delivery_worker(interval=3600)
        assert first is not None
        second = delivery_worker.start_delivery_worker(interval=3600)
        assert second is first
        assert delivery_worker.delivery_worker_status()["running"] is True
        delivery_worker.stop_delivery_worker()
        status = delivery_worker.delivery_worker_status()
        assert status["running"] is False

    def test_lifespan_starts_and_stops_worker(self, monkeypatch):
        """Авто-старт в lifespan API (остаток AUDIT-6B: «in-process
        авто-старт и health -- AUDIT-6C»); shutdown останавливает."""
        from apps.api import delivery_worker

        monkeypatch.setenv("CISSTAT_DELIVERY_WORKER_ENABLED", "1")
        monkeypatch.setenv("CISSTAT_DELIVERY_WORKER_INTERVAL", "3600")
        with TestClient(app):
            status = delivery_worker.delivery_worker_status()
            assert status["enabled"] is True
            assert status["running"] is True
        status = delivery_worker.delivery_worker_status()
        assert status["running"] is False

    def test_worker_in_ops_health(self, monkeypatch):
        from apps.api import delivery_worker, research_runs

        monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
        research_runs.get_research_run_store()
        body = client.get("/health/ops").json()
        assert "enabled" in body["worker"]
        assert "running" in body["worker"]
        assert "interval_seconds" in body["worker"]


# ════════════════════════════════════════════════════════════════════
# R2: деградация Modeling dispatch (импортируемость apps.api.main в
# облегчённой среде; fail-closed в точке исполнения)
# ════════════════════════════════════════════════════════════════════


_HEAVY_MODELS = (
    "prophet",
    "tbats",
    "xgboost",
    "lightgbm",
    "catboost",
    "var",
    "vecm",
    "garch",
    "egarch",
)


class TestModelsDispatchDegradation:
    def test_full_env_dispatch_ready(self):
        from apps.api.routers.models import models_dispatch_state

        state = models_dispatch_state()
        assert state["ready"] is True
        assert state["missing"] == []
        assert state["unexpected"] == []
        assert state["production_model_count"] > 0
        assert state["dispatch_model_count"] > 0

    def test_light_env_reload_imports_and_degrades_honestly(self, monkeypatch):
        """Донастройка_2 п.2: в облегчённой среде (heavy-зависимости
        отсутствуют) import apps.api.main РАБОТАЕТ: dispatch содержит
        только registry-available модели, деградация честна. На текущем
        коде reload падает import-time RuntimeError (RED)."""
        import importlib

        from apps.api import model_readiness
        from apps.api.routers import models as models_module

        original = set(model_readiness.PRODUCTION_BACKTEST_MODEL_IDS)
        dropped = {model for model in _HEAVY_MODELS if model in original}
        assert dropped, "в полной среде heavy-модели должны быть в реестре"
        monkeypatch.setattr(
            model_readiness,
            "PRODUCTION_BACKTEST_MODEL_IDS",
            frozenset(original - dropped),
        )
        try:
            importlib.reload(models_module)
            state = models_module.models_dispatch_state()
            assert state["ready"] is True
            assert set(state["dropped_by_registry"]) == dropped
            assert "prophet" not in models_module._BACKTEST_IMPLEMENTATIONS
            assert "naive" in models_module._BACKTEST_IMPLEMENTATIONS
        finally:
            monkeypatch.undo()
            importlib.reload(models_module)

    def test_execution_gate_fail_closed_on_divergence(self, monkeypatch):
        """Runtime-дрейф dispatch (запись исчезла) -- исполнение
        заблокировано 503 fail-closed ДО запуска модели; фиктивные
        метрики невозможны."""
        from fastapi import HTTPException

        from apps.api.routers import models as models_module

        assert "ets" in models_module._BACKTEST_IMPLEMENTATIONS
        monkeypatch.delitem(models_module._BACKTEST_IMPLEMENTATIONS, "ets")
        state = models_module.models_dispatch_state()
        assert state["ready"] is False
        assert "ets" in state["missing"]
        with pytest.raises(HTTPException) as excinfo:
            models_module._run_backtest_with_series(
                "ets", ("ETS", "statsmodels"), [1.0, 2.0, 3.0], 0.6, 12
            )
        assert excinfo.value.status_code == 503

    def test_dispatch_state_in_ops_health(self):
        body = client.get("/health/ops").json()
        md = body["models_dispatch"]
        assert md["ready"] is True
        assert "missing" in md and "unexpected" in md
        assert "dropped_by_registry" in md


# ════════════════════════════════════════════════════════════════════
# R4: операционные логи (ids + безопасная причина, без секретов)
# ════════════════════════════════════════════════════════════════════


class TestOperationalLogs:
    def test_hook_mirror_failure_log_carries_ids_and_safe_reason(
        self, caplog, monkeypatch
    ):
        """Отказ advisory-зеркала хука (P22/P09): operational log несёт
        event_id/run_id/session_id и безопасную причину -- без DSN и
        сырого трейса (план §18: «логи несут request/operation/event/
        run/context ids ... и безопасную причину отказа»)."""
        import asyncio
        import logging as _logging

        from apps.api import trace_hook as th
        from apps.api.trace_events import make_trace_event

        run_id, context_id = _seed()
        session_id = client.cookies.get("cisstat_session_id") or ""
        assert session_id

        spec = th.resolve_trace_route("POST", "/v1/session/target-column")
        assert spec is not None

        store = get_session_store()
        session = store.get(session_id)

        # Перехват реального события, созданного внутри _record: контракт
        # «лог несёт event_id» проверяется на фактическом событии.
        original_record_trace_event = th.record_trace_event
        captured: dict[str, Any] = {}

        def _capturing_record(session_obj, spec_obj, *, response_body, **kwargs):
            event_obj = original_record_trace_event(
                session_obj, spec_obj, response_body=response_body, **kwargs
            )
            captured["event"] = event_obj
            return event_obj

        monkeypatch.setattr(th, "record_trace_event", _capturing_record)

        def _boom(session_obj, event_obj):
            raise RuntimeError(f"layer2 down for {_SECRET_DSN}")

        monkeypatch.setattr(th, "record_run_event", _boom)

        middleware = th.TraceHookMiddleware(app=None)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/v1/session/target-column",
            "headers": [
                (b"cookie", f"cisstat_session_id={session_id}".encode())
            ],
            "query_string": b"",
        }
        with caplog.at_level(_logging.WARNING, logger="apps.api.trace_hook"):
            asyncio.run(
                middleware._record(
                    scope,
                    spec,
                    {"status": 200},
                    [],
                    [b'{"target_column": "value"}'],
                )
            )
        records = [
            r for r in caplog.records if r.name == "apps.api.trace_hook"
        ]
        assert records, "отказ зеркала должен попасть в operational log"
        message = records[-1].getMessage()
        actual_event = captured.get("event")
        assert actual_event is not None, "событие слоя 1 создано до отказа слоя 2"
        assert actual_event.event_id in message
        assert run_id in message
        assert session_id in message
        assert "supersecret" not in message
        assert "postgresql://" not in message
        assert "Traceback" not in message

    def test_advisory_marker_in_hook_log(self, caplog, monkeypatch):
        """Хук остаётся ЯВНО advisory (v1.5-6B §25.1): operational log
        помечает путь advisory (гарантия не заявляется)."""
        import asyncio
        import logging as _logging

        from apps.api import trace_hook as th

        run_id, _context = _seed()
        session_id = client.cookies.get("cisstat_session_id") or ""
        spec = th.resolve_trace_route("POST", "/v1/session/target-column")

        def _boom(session_obj, event_obj):
            raise RuntimeError("injected")

        monkeypatch.setattr(th, "record_run_event", _boom)
        middleware = th.TraceHookMiddleware(app=None)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/v1/session/target-column",
            "headers": [
                (b"cookie", f"cisstat_session_id={session_id}".encode())
            ],
            "query_string": b"",
        }
        with caplog.at_level(_logging.WARNING, logger="apps.api.trace_hook"):
            asyncio.run(
                middleware._record(scope, spec, {"status": 200}, [], [b"{}"])
            )
        records = [r for r in caplog.records if r.name == "apps.api.trace_hook"]
        assert records, "operational log отказа зеркала обязателен"
        assert "advisory" in records[-1].getMessage().lower()


# ════════════════════════════════════════════════════════════════════
# Живой Postgres (pgserver): required-режим, probe, worker
# ════════════════════════════════════════════════════════════════════


@pytest.fixture()
def pg_store() -> PostgresResearchRunStore:
    """Живой Postgres: чистая схема на каждый тест. Без
    CISSTAT_TEST_PG_DSN -- честный skip живой половины паритета."""
    if not PG_DSN:
        pytest.skip("CISSTAT_TEST_PG_DSN не задан -- живой PG недоступен")
    try:
        import psycopg
    except ImportError:  # pragma: no cover - среда без драйвера
        pytest.skip("psycopg не установлен")
    conn = psycopg.connect(PG_DSN, autocommit=False)
    with conn.cursor() as cur:
        cur.execute(
            "DROP TABLE IF EXISTS progress_delivery_outbox CASCADE;"
            "DROP TABLE IF EXISTS run_commit_receipts CASCADE;"
            "DROP TABLE IF EXISTS run_checkpoints CASCADE;"
            "DROP TABLE IF EXISTS trace_events CASCADE;"
            "DROP TABLE IF EXISTS research_runs CASCADE;"
            "DROP TABLE IF EXISTS mentor_observations CASCADE;"
        )
    conn.commit()
    from apps.api.research_runs import run_migrations

    run_migrations(conn)
    conn.close()
    return PostgresResearchRunStore(dsn=PG_DSN)


class TestPostgresParity:
    def test_required_mode_live_pg_selected(self, monkeypatch, pg_store):
        """required + живая БД: фабрика выбирает Postgres (не Memory),
        startup-probe зелёный."""
        from apps.api import research_runs

        monkeypatch.setenv("CISSTAT_STORAGE_MODE", "required")
        monkeypatch.setenv("DATABASE_URL", PG_DSN)
        monkeypatch.setattr(
            research_runs.PostgresResearchRunStore,
            "readiness_probe",
            lambda self: {"ok": True, "backend": "postgres"},
        )
        store = research_runs.get_research_run_store()
        assert isinstance(store, research_runs.PostgresResearchRunStore)

    def test_worker_delivers_live(self, monkeypatch, pg_store):
        """Worker восстановления на живом PG: pending-обязательство
        доставляется в слой 1, outbox закрывается delivered."""
        from apps.api import delivery_worker
        from apps.api.delivery_outbox import DeliveryTask, bind_idempotency_key
        from apps.api.trace_events import make_trace_event

        from app.core.pipeline_graph import STAGE_NODES as _STAGE_NODES

        session_store_obj = MemorySessionStore()
        session = AnalysisSession(session_id="S-6C-PG")
        # FK миграции 0005: run должен существовать в research_runs.
        from apps.api.research_runs import ResearchRun as _ResearchRun

        pg_store.upsert_run(
            _ResearchRun(
                run_id="RUN-6C-PG",
                session_id="S-6C-PG",
                dataset_fingerprint="fp-6c-pg",
                dataset_name="ops-worker",
            )
        )
        event = make_trace_event(
            "eda_check_status",
            stage="eda",
            node_id=next(iter(_STAGE_NODES["eda"])),
            run_id="RUN-6C-PG",
            check="stationarity",
            status="done",
        )
        session.append_trace_event(event)
        session_store_obj.save(session)
        task = bind_idempotency_key(
            DeliveryTask(
                operation_id="op-6c-pg-worker",
                idempotency_key="report:RUN-6C-PG:op-6c-pg-worker",
                run_id="RUN-6C-PG",
                payload={
                    "session_id": "S-6C-PG",
                    "events": [event.to_dict()],
                },
            ),
            "report:RUN-6C-PG:op-6c-pg-worker",
        )
        pg_store.delivery_outbox.register(task)
        worker = delivery_worker.DeliveryWorker(
            pg_store, interval=3600, session_store=session_store_obj
        )
        report = worker.run_once()
        assert report["delivery"]["delivered"] == 1
        delivered = pg_store.delivery_outbox.get_task("op-6c-pg-worker")
        assert delivered.state == "delivered"
        fresh = session_store_obj.get("S-6C-PG")
        event_ids = {
            item.get("event_id")
            for item in fresh.pipeline_trace
            if isinstance(item, dict)
        }
        assert event.event_id in event_ids
