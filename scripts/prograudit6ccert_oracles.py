# -*- coding: utf-8 -*-
"""Независимая сертификация PROGR-AUDIT-6C (backend, health и операционные
логи) -- оракулы сертификатора НА СВОИХ данных.

Дизъюнктность от корпуса исполнителя (tests/api/test_progress_audit_6c.py):
  * НАСТОЯЩИЕ отказы вместо monkeypatch-инъекций: фабрики получают реальные
    недостижимые DSN (TEST-NET-3 203.0.113.6 с честным 3-секундным probe-
    таймаутом; порт 1 на loopback -- мгновенный ECONNREFUSED) и реальную
    ошибку конфигурации (CISSTAT_RUNS_BACKEND=postgres при ПУСТОМ
    DATABASE_URL) -- код падает сам, без подмены from_env/readiness_probe;
  * свой DSN/секретный корпус: pg-cert6c.internal.east / cisstat_cert6c /
    Qx7vLp%21 / t0ken-6cc-777 / CERT-Bearer eyJ6cc (vs db-host-6c.invalid /
    supersecret / redispass исполнителя);
  * свои run/operation/report/session ids: RUN-CERT6C-*, op-cert6c-*,
    cert6c-report-77, sid-cert6c-* (vs R6C / op-6c-* / report-6c-* / S-6C*);
  * свой датасет: hydrogen_plant_monthly.csv, 150 месяцев, давление/частота
    (vs forecast_monitor_synthetic_n150.csv исполнителя);
  * свой метод наблюдения: собственный logging.Handler (не caplog), СВЕЖИЕ
    интерпретаторы subprocess для лёгкой среды (подмена find_spec по
    НАСТОЯЩЕЙ причине -- отсутствие пакетных спеков) и для драйвера (не
    importlib.reload и не sys.modules[...]=None); живой PG в СВОЕМ tempdir
    (cisstat6ccert-pg-*) с РЕАЛЬНЫМ оракулом миграций (не-мигрированная БД
    обязана честно ok=False) вместо подмены readiness_probe;
  * свои acceptance-группы G6CC-* и своё расхождение dispatch (theta, а не
    ets).

Контракт: docs/progress_audit_contract.md аддендум v1.6-6C §26;
план plan_progress_audit.md §18.

Запуск (cwd=корень репозитория):
  PYTHONPATH=. python scripts/prograudit6ccert_oracles.py            # всё, вкл. живой PG
  PYTHONPATH=. python scripts/prograudit6ccert_oracles.py --no-pg    # без живого PG
  PYTHONPATH=. python scripts/prograudit6ccert_oracles.py --cert     # канал kill'а мутаций
Exit 0 -- все оракулы PASS (на HEAD после реализации); на базе 8b309eb
часть оракулов обязана падать (RED-протокол сертификации).
"""
from __future__ import annotations

import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import traceback
from datetime import datetime, timedelta, timezone

RESULTS: list[tuple[str, bool, str]] = []
ORACLES: list[tuple[str, object]] = []


def oracle(name: str):
    """Декоратор-регистратор оракула (свои наблюдательные методы)."""

    def _wrap(fn):
        ORACLES.append((name, fn))
        return fn

    return _wrap


# ── свои данные/маркеры сертификатора ────────────────────────────────

CERT_DSN_SECRET = (
    "postgresql://cert6c_svc:Qx7vLp%21@"
    "pg-cert6c.internal.east:5433/cisstat_cert6c"
)
CERT_REDIS_SECRET = (
    "rediss://cert6c_cache:t0ken-6cc-777@redis-cert6c.internal.west:6380/2"
)
# Мгновенный отказ (порт 1 на loopback -- ничего не слушает).
CERT_REFUSED_PG = "postgresql://cert6c@127.0.0.1:1/cert6c"
CERT_REFUSED_REDIS = "redis://127.0.0.1:1/0"
# TEST-NET-3 (RFC 5737): маршрутизацию никто не обещает -- реальная
# «недоступная БД» для честного probe-таймаута (connect_timeout=3).
CERT_UNROUTABLE_PG = (
    "postgresql://cert6c_svc@203.0.113.6:5432/cisstat_cert6c"
)

RUN_CERT = "RUN-CERT6C-A"
SESSION_CERT = "sid-cert6c-a"
RUN_CERT_PG = "RUN-CERT6C-PG"
SESSION_CERT_PG = "sid-cert6c-pg"
REPORT_CERT = "cert6c-report-77"

_SECRET_MARKERS = (
    "Qx7vLp",            # пароль DSN
    "pg-cert6c.internal.east",
    "t0ken-6cc-777",
    "redis-cert6c.internal.west",
    "postgresql://",
    "postgres://",
    "rediss://",
)
# Строгий уровень -- для каналов, обещающих ТОЛЬКО класс исключения
# (safe_health_error): там не имеет права выжить даже голый маркер.
_STRICT_MARKERS = _SECRET_MARKERS + ("CERT-SEC-42", "cert-key-9")


def _no_secrets(text: str) -> bool:
    return all(marker not in (text or "") for marker in _SECRET_MARKERS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── собственный перехват логов (не caplog) ───────────────────────────


class ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.messages.append(record.getMessage())
        except Exception:  # pragma: no cover - защитный контур
            pass


class LogTap:
    """Свой перехватчик: вешает ListHandler на указанные логгеры."""

    def __init__(self, *logger_names: str, level: int = logging.DEBUG) -> None:
        self.handler = ListHandler()
        self.names = logger_names
        self.level = level
        self._attached: list[logging.Logger] = []

    def __enter__(self) -> ListHandler:
        for name in self.names:
            logger = logging.getLogger(name)
            logger.addHandler(self.handler)
            self._attached.append(logger)
        self.handler.setLevel(self.level)
        return self.handler

    def __exit__(self, *exc) -> None:
        for logger in self._attached:
            logger.removeHandler(self.handler)
        self._attached.clear()


# ── песочница окружения (без pytest.monkeypatch) ─────────────────────

_ISOLATED_ENV_VARS = (
    "CISSTAT_STORAGE_MODE",
    "DATABASE_URL",
    "CISSTAT_RUNS_BACKEND",
    "REDIS_URL",
    "CISSTAT_SESSION_BACKEND",
    "CISSTAT_DELIVERY_WORKER_ENABLED",
    "CISSTAT_DELIVERY_WORKER_INTERVAL",
)


class EnvSandbox:
    """Сохраняет/восстанавливает env + сбрасывает singleton'ы 6C."""

    def __init__(self) -> None:
        self._saved: dict[str, str | None] = {}

    def set(self, key: str, value: str) -> None:
        if key not in self._saved:
            self._saved[key] = os.environ.get(key)
        os.environ[key] = value

    def unset(self, key: str) -> None:
        if key not in self._saved:
            self._saved[key] = os.environ.get(key)
        os.environ.pop(key, None)

    def _reset_singletons(self) -> None:
        from apps.api import research_runs, session_store

        research_runs.reset_research_run_store_for_testing()
        session_store.reset_session_store_for_testing()
        research_runs.reset_dataset_file_store_for_testing()
        try:
            # RED-база (8b309eb): модуля 6C ещё нет -- честный guard
            from apps.api import storage_diagnostics

            storage_diagnostics.reset_storage_diagnostics_for_testing()
        except ImportError:
            pass
        try:
            from apps.api import delivery_worker

            delivery_worker.reset_delivery_worker_for_testing()
        except ImportError:  # RED-база: модуля ещё нет
            pass

    def __enter__(self) -> "EnvSandbox":
        for key in _ISOLATED_ENV_VARS:
            self.unset(key)
        self._reset_singletons()
        return self

    def __exit__(self, *exc) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._saved.clear()
        self._reset_singletons()


# ── свой CSV и сиды через живой API ──────────────────────────────────


def _cert_csv() -> str:
    """СВОЙ датасет сертификатора: 150 месяцев давления/частоты водородной
    станции (дизъюнктен с датасетом исполнителя)."""
    import pandas as pd

    idx = [datetime(2024, 1, 1) + timedelta(days=30 * i) for i in range(150)]
    frame = pd.DataFrame(
        {
            "date": [d.strftime("%Y-%m-%d") for d in idx],
            "pressure_bar": [70.0 + (i % 11) * 0.7 for i in range(150)],
            "freq_hz": [50.0 + ((i * 13) % 5) * 0.05 for i in range(150)],
        }
    )
    return frame.to_csv(index=False)


def _seed_upload_run(client) -> tuple[str, str]:
    """Загрузка СВОЕГО CSV -> (run_id, context_id) из /trace."""
    response = client.post(
        "/v1/internal/upload",
        files={"file": (
            "hydrogen_plant_monthly_n150.csv",
            io.BytesIO(_cert_csv().encode()),
            "text/csv",
        )},
    )
    assert response.status_code == 200, response.text
    trace = client.get("/v1/progress/trace").json()
    run_id = trace.get("run_id") or ""
    context_id = trace.get("context_id") or ""
    assert run_id and context_id, "seed: загрузка обязана фиксировать запуск"
    return run_id, context_id


class OneShotSaveFailure:
    """Одноразовый отказ save() слоя 1 (класс MemorySessionStore --
    тот же честный паттерн обязателства 6B, своя реализация)."""

    def __init__(self, times: int = 1) -> None:
        from apps.api.session_store import MemorySessionStore

        self._cls = MemorySessionStore
        self._original_save = MemorySessionStore.save
        self._left = times

    def __enter__(self) -> "OneShotSaveFailure":
        original = self._original_save
        state = self

        def failing_save(store_self, session):
            if state._left > 0:
                state._left -= 1
                raise RuntimeError(
                    f"injected cert6c cache outage ({CERT_DSN_SECRET})"
                )
            return original(store_self, session)

        self._cls.save = failing_save
        return self

    def __exit__(self, *exc) -> None:
        self._cls.save = self._original_save


# ════════════════════════════════════════════════════════════════════
# G6CC-MODE: режимы хранения (§26.1; P21/F14) -- НАСТОЯЩИЕ отказы
# ════════════════════════════════════════════════════════════════════


@oracle("G6CC-MODE-1 required + реальная ошибка конфигурации -> fail-closed")
def _mode_required_config_error() -> str:
    from apps.api import research_runs, storage_diagnostics

    with EnvSandbox() as env:
        env.set("CISSTAT_STORAGE_MODE", "required")
        # РЕАЛЬНАЯ конфигурационная ошибка: backend объявлен, URL не задан
        env.set("CISSTAT_RUNS_BACKEND", "postgres")
        env.unset("DATABASE_URL")
        try:
            research_runs.get_research_run_store()
        except RuntimeError as exc:
            message = str(exc)
            assert "required" in message.lower(), message
            assert _no_secrets(message), message
        else:
            raise AssertionError("required + нет URL обязан fail-closed")
        # Memory-подмена НЕ создана; singleton остался пустым
        assert research_runs.peek_research_run_store() is None
        snapshot = storage_diagnostics.storage_backend_snapshot()
        runs = snapshot["runs_backend"]
        assert runs["configured"] == "postgres", runs
        assert runs["effective"] == "unavailable", runs
        assert runs["degraded"] is True, runs
    return "RuntimeError, singleton не создан, configured=postgres/unavailable"


@oracle("G6CC-MODE-2 required + недостижимая БД (TEST-NET-3) -> fail-closed")
def _mode_required_unreachable() -> str:
    from apps.api import research_runs

    with EnvSandbox() as env:
        env.set("CISSTAT_STORAGE_MODE", "required")
        env.set("DATABASE_URL", CERT_UNROUTABLE_PG)
        try:
            research_runs.get_research_run_store()
        except RuntimeError as exc:
            message = str(exc)
            assert "required" in message.lower(), message
            assert _no_secrets(message), message
        else:
            raise AssertionError("недостижимая БД в required обязан уронить фабрику")
        assert research_runs.peek_research_run_store() is None
    return "RuntimeError по реальному probe (3s timeout), Memory не подменён"


@oracle("G6CC-MODE-3 advisory + реальная ошибка конфигурации Postgres -> ЯВНАЯ деградация")
def _mode_advisory_explicit() -> str:
    from apps.api import research_runs, storage_diagnostics

    with EnvSandbox() as env:
        # РЕАЛЬНАЯ ошибка конфигурации: backend объявлен, URL не задан --
        # конструктор from_env падает сам (без monkeypatch).
        env.set("CISSTAT_RUNS_BACKEND", "postgres")
        env.unset("DATABASE_URL")
        with LogTap("apps.api.research_runs") as tap:
            store = research_runs.get_research_run_store()
        from apps.api.research_runs import MemoryResearchRunStore

        assert isinstance(store, MemoryResearchRunStore)
        snapshot = storage_diagnostics.storage_backend_snapshot()
        runs = snapshot["runs_backend"]
        assert runs["configured"] == "postgres", runs
        assert runs["effective"] == "memory", runs
        assert runs["degraded"] is True, runs
        assert _no_secrets(runs["reason"] or ""), runs
        assert snapshot["degraded"] is True
        assert snapshot["fallback_events"], "событие fallback зафиксировано"
        event = snapshot["fallback_events"][-1]
        assert event["component"] == "runs" and event["storage_mode"] == "advisory"
        assert _no_secrets(event["reason"]), event
        assert tap.messages, "отказ обязан попасть в operational-лог"
        assert _no_secrets("\n".join(tap.messages)), tap.messages
    return "Memory + degraded=True + fallback_events; лог без DSN"


@oracle("G6CC-MODE-3b advisory + недоступная БД: ленивый Postgres выбран, недоступность видна в /health/ops")
def _mode_advisory_lazy_unreachable() -> str:
    """Advisory сохраняет ленивый контракт конструирования (пин
    test_database_url_selects_postgres_lazily): недостижимая БД НЕ роняет
    фабрику, а наблюдаема через readiness в /health/ops (§26.1)."""
    from fastapi.testclient import TestClient

    from apps.api import research_runs
    from apps.api.main import app
    from apps.api.research_runs import PostgresResearchRunStore

    with EnvSandbox() as env:
        env.set("DATABASE_URL", CERT_REFUSED_PG)  # мгновенный ECONNREFUSED
        store = research_runs.get_research_run_store()
        assert isinstance(store, PostgresResearchRunStore), type(store)
        body = TestClient(app).get("/health/ops").json()
        readiness = body["readiness"]["runs"]
        assert readiness["ok"] is False, readiness
        assert _no_secrets(readiness.get("error") or ""), readiness
        # класс исключения -- и ничего больше (safe_health_error)
        assert "OperationalError" in readiness.get("error", ""), readiness
        assert body["status"] == "degraded", body["status"]
    return "Postgres выбран лениво; readiness.runs ok=False + класс ошибки в health"


@oracle("G6CC-MODE-4 explicit memory observable (не silent-fallback)")
def _mode_explicit_memory() -> str:
    from apps.api import research_runs, storage_diagnostics

    with EnvSandbox() as env:
        env.set("DATABASE_URL", CERT_REFUSED_PG)
        env.set("CISSTAT_RUNS_BACKEND", "memory")
        research_runs.get_research_run_store()
        runs = storage_diagnostics.storage_backend_snapshot()["runs_backend"]
        assert runs["configured"] == "memory", runs
        assert runs["effective"] == "memory", runs
        assert runs["degraded"] is False, runs
        snap = storage_diagnostics.storage_backend_snapshot()
        assert snap["degraded"] is False, snap
        assert snap["fallback_events"] == [], snap
    return "configured=memory, degraded=False, событий fallback нет"


@oracle("G6CC-MODE-5 auto без конфигурации -> честный memory")
def _mode_auto() -> str:
    from apps.api import research_runs, storage_diagnostics

    with EnvSandbox():
        store = research_runs.get_research_run_store()
        from apps.api.research_runs import MemoryResearchRunStore

        assert isinstance(store, MemoryResearchRunStore)
        runs = storage_diagnostics.storage_backend_snapshot()["runs_backend"]
        assert runs["configured"] == "auto" and runs["effective"] == "memory"
        assert runs["degraded"] is False
    return "configured=auto, effective=memory, degraded=False"


@oracle("G6CC-MODE-6 опечатка в режиме хранения -> fail fast")
def _mode_invalid_fail_fast() -> str:
    from apps.api import research_runs, storage_diagnostics

    with EnvSandbox() as env:
        env.set("CISSTAT_STORAGE_MODE", "prod-6ccert")
        try:
            storage_diagnostics.get_storage_mode()
        except RuntimeError as exc:
            assert "CISSTAT_STORAGE_MODE" in str(exc), str(exc)
        else:
            raise AssertionError("неизвестный режим обязан fail fast")
        try:
            research_runs.get_research_run_store()
        except RuntimeError:
            pass
        else:
            raise AssertionError("фабрика обязана пробросить fail fast")
    return "RuntimeError на get_storage_mode и на фабрике"


@oracle("G6CC-MODE-7 Redis required: реальная ошибка конфигурации -> fail-closed")
def _mode_redis_config_error() -> str:
    from apps.api import session_store, storage_diagnostics

    with EnvSandbox() as env:
        env.set("CISSTAT_STORAGE_MODE", "required")
        # РЕАЛЬНАЯ ошибка: backend redis объявлен, REDIS_URL не задан
        env.set("CISSTAT_SESSION_BACKEND", "redis")
        try:
            session_store.get_session_store()
        except RuntimeError as exc:
            assert "required" in str(exc).lower(), str(exc)
            assert _no_secrets(str(exc)), str(exc)
        else:
            raise AssertionError("required Redis без URL обязан fail-closed")
        assert session_store.peek_session_store() is None
        runs = storage_diagnostics.storage_backend_snapshot()["session_backend"]
        assert runs["configured"] == "redis" and runs["degraded"] is True, runs
    return "RuntimeError, singleton не создан, configured=redis/unavailable"


@oracle("G6CC-MODE-8 Redis advisory: реальная ошибка конфигурации -> ЯВНАЯ деградация")
def _mode_redis_advisory() -> str:
    from apps.api import session_store, storage_diagnostics

    with EnvSandbox() as env:
        # РЕАЛЬНАЯ ошибка: backend redis объявлен, REDIS_URL не задан
        env.set("CISSTAT_SESSION_BACKEND", "redis")
        store = session_store.get_session_store()
        from apps.api.session_store import MemorySessionStore

        assert isinstance(store, MemorySessionStore)
        snap = storage_diagnostics.storage_backend_snapshot()
        session_backend = snap["session_backend"]
        assert session_backend["configured"] == "redis", session_backend
        assert session_backend["effective"] == "memory", session_backend
        assert session_backend["degraded"] is True, session_backend
        assert _no_secrets(session_backend["reason"] or ""), session_backend
        assert snap["fallback_events"], "fallback-событие зафиксировано"
    return "Memory + configured=redis/degraded=True, причина без секрета"


@oracle("G6CC-MODE-8b Redis advisory + недоступный PING: Redis выбран лениво, readiness видна в /health/ops")
def _mode_redis_lazy_unreachable() -> str:
    from fastapi.testclient import TestClient

    from apps.api import session_store
    from apps.api.main import app
    from apps.api.session_store import RedisSessionStore

    with EnvSandbox() as env:
        env.set("REDIS_URL", CERT_REFUSED_REDIS)
        store = session_store.get_session_store()
        assert isinstance(store, RedisSessionStore), type(store)
        body = TestClient(app).get("/health/ops").json()
        readiness = body["readiness"]["session"]
        assert readiness["ok"] is False, readiness
        assert _no_secrets(readiness.get("error") or ""), readiness
        assert body["status"] == "degraded", body["status"]
    return "Redis выбран лениво; readiness.session ok=False в health"


@oracle("G6CC-MODE-9 Redis required: недоступный PING -> fail-closed")
def _mode_redis_required_unreachable() -> str:
    from apps.api import session_store

    with EnvSandbox() as env:
        env.set("CISSTAT_STORAGE_MODE", "required")
        env.set("REDIS_URL", CERT_REFUSED_REDIS)
        try:
            session_store.get_session_store()
        except RuntimeError as exc:
            assert "required" in str(exc).lower(), str(exc)
            assert _no_secrets(str(exc)), str(exc)
        else:
            raise AssertionError("недоступный Redis в required обязан уронить фабрику")
        assert session_store.peek_session_store() is None
    return "RuntimeError по реальному PING, Memory не подменён"


# ════════════════════════════════════════════════════════════════════
# G6CC-SAFE: safe_error / safe_health_error на СВОЁМ враждебном корпусе
# ════════════════════════════════════════════════════════════════════


@oracle("G6CC-SAFE-1 DSN/URL целиком редактируются")
def _safe_urls() -> str:
    from apps.api.storage_diagnostics import safe_error

    corpus = (
        RuntimeError(f"connect: {CERT_DSN_SECRET} refused"),
        RuntimeError(f"mirror drop redis {CERT_REDIS_SECRET} timeout"),
        "plain string postgres://user:pw@h.example/x?password=zzz tail",
    )
    for value in corpus:
        text = safe_error(value)
        assert "postgresql://" not in text, text
        assert "postgres://" not in text, text
        assert "rediss://" not in text, text
        assert "Qx7vLp" not in text and "t0ken-6cc-777" not in text, text
        assert "<redacted-url>" in text or "<redacted>" in text, text
        assert "refused" in text or "timeout" in text or "tail" in text, (
            "содержательная часть обязана сохраниться"
        )
    return "3 схемы редактированы, содержательная часть сохранена"


@oracle("G6CC-SAFE-2 password=/token=/Bearer редактируются")
def _safe_kv_bearer() -> str:
    from apps.api.storage_diagnostics import safe_error

    text = safe_error(
        RuntimeError(
            "auth failed: password=CERT-SEC-42 token=t0ken-6cc-777 "
            "Authorization: Bearer eyJ6ccHeader.sig api_key=cert-key-9 "
            "host=pg-cert6c.internal.east"
        )
    )
    assert "CERT-SEC-42" not in text, text
    assert "t0ken-6cc-777" not in text, text
    assert "eyJ6ccHeader" not in text, text
    assert "cert-key-9" not in text, text
    assert "password=" in text and "<redacted>" in text, text
    assert "pg-cert6c.internal.east" in text, (
        "голый хост вне URL-схемы не обещан редакцией в safe_error -- "
        "для тела health есть safe_health_error"
    )
    return "значения секретов редактированы, ключи сохранены"


@oracle("G6CC-SAFE-3 клип 300 и схлопывание переносов")
def _safe_clip() -> str:
    from apps.api.storage_diagnostics import safe_error

    long_text = " ".join(["cert6c-diagnostic-token"] * 120)
    clipped = safe_error(long_text)
    assert len(clipped) <= 300, len(clipped)
    assert clipped.endswith("..."), clipped
    multiline = safe_error(RuntimeError("line1\nline2\n  frame boom"))
    assert "\n" not in multiline, multiline
    return "клип 300 + '...'; переносы схлопнуты (одна строка)"


@oracle("G6CC-SAFE-4 None/пустой BaseException/не-исключение")
def _safe_edges() -> str:
    from apps.api.storage_diagnostics import safe_error

    assert safe_error(None) == "unknown error"
    assert safe_error(RuntimeError("")) == "RuntimeError"
    assert safe_error(12345) == "12345"
    assert isinstance(safe_error(ValueError("x")), str)
    return "None->unknown error; пустой->класс; не-исключение->str"


@oracle("G6CC-SAFE-5 safe_health_error -- только класс исключения")
def _safe_health_error() -> str:
    from apps.api.storage_diagnostics import safe_health_error

    text = safe_health_error(
        RuntimeError(f"connection refused for {CERT_DSN_SECRET} token=t0ken-6cc-777 CERT-SEC-42")
    )
    assert text.startswith("RuntimeError"), text
    assert all(m not in text for m in _STRICT_MARKERS), text
    assert "operational" in text.lower(), text
    non_exc = safe_health_error("plain reason")
    assert "plain reason" in non_exc
    return "класс + отсылка в логи; ни DSN, ни голого токена (строгий уровень)"


# ════════════════════════════════════════════════════════════════════
# G6CC-PROBE: readiness-пробы и возраст backlog (§26.3)
# ════════════════════════════════════════════════════════════════════


@oracle("G6CC-PROBE-1 probe_store: Memory ok / None -> not_initialized")
def _probe_basic() -> str:
    from apps.api.research_runs import MemoryResearchRunStore
    from apps.api.session_store import MemorySessionStore
    from apps.api.storage_diagnostics import probe_store

    runs = probe_store(MemoryResearchRunStore(), component="runs")
    assert runs["ok"] is True and runs["backend"] == "memory", runs
    assert "latency_ms" in runs, runs
    session = probe_store(MemorySessionStore(), component="session")
    assert session["ok"] is True, session
    absent = probe_store(None, component="runs")
    assert absent["ok"] is None and absent["detail"] == "not_initialized", absent
    return "ok=True с latency; честное not_initialized"


@oracle("G6CC-PROBE-2 probe_store: врун и бросок -- защитный контур")
def _probe_lying_store() -> str:
    from apps.api.storage_diagnostics import probe_store

    class LyingStore:
        def readiness_probe(self):
            return {"ok": False, "error": f"pg down {CERT_DSN_SECRET}"}

    class ThrowingStore:
        def readiness_probe(self):
            raise RuntimeError(f"probe exploded for {CERT_DSN_SECRET}")

    class GarbageStore:
        def readiness_probe(self):
            return "not a dict"

    lying = probe_store(LyingStore(), component="runs")
    assert lying["ok"] is False and _no_secrets(lying["error"]), lying
    thrown = probe_store(ThrowingStore(), component="runs")
    assert thrown["ok"] is False, thrown
    assert _no_secrets(thrown["error"]), thrown
    assert "RuntimeError" in thrown["error"], thrown
    garbage = probe_store(GarbageStore(), component="runs")
    assert garbage["ok"] is False, garbage
    return "ok=False + безопасная причина на трёх формах вранья"


@oracle("G6CC-PROBE-3 backlog_age_seconds: СВОИ обязательства на Memory")
def _backlog_age_memory() -> str:
    from apps.api.delivery_outbox import DeliveryTask, bind_idempotency_key
    from apps.api.research_runs import MemoryResearchRunStore

    store = MemoryResearchRunStore()
    outbox = store.delivery_outbox
    old_iso = (
        datetime.now(timezone.utc) - timedelta(seconds=90)
    ).isoformat()
    task = bind_idempotency_key(
        DeliveryTask(
            operation_id="op-cert6c-age-1",
            idempotency_key="report:RUN-CERT6C-A:op-cert6c-age-1",
            run_id=RUN_CERT,
            payload={"session_id": SESSION_CERT, "events": []},
            created_at=old_iso,
            updated_at=old_iso,
        ),
        "report:RUN-CERT6C-A:op-cert6c-age-1",
    )
    outbox.register(task)
    assert outbox.get_task("op-cert6c-age-1").state == "pending"
    age = outbox.backlog_age_seconds(_now_iso())
    assert age is not None and 60 <= age <= 200, age
    outbox.mark_delivered("op-cert6c-age-1", delivered_at=_now_iso())
    assert outbox.backlog_age_seconds(_now_iso()) is None
    return f"возраст ~90с наблюдаем; после доставки -- честный None ({age:.1f}s)"


# ════════════════════════════════════════════════════════════════════
# G6CC-OPS: /health (liveness) и /health/ops (§26.3)
# ════════════════════════════════════════════════════════════════════


@oracle("G6CC-OPS-1 liveness /health: тело сохранено, не зависит от БД")
def _ops_liveness() -> str:
    from fastapi.testclient import TestClient

    from apps.api.main import app

    with EnvSandbox() as env:
        env.set("DATABASE_URL", CERT_REFUSED_PG)  # отказ БД не должен
        # влиять на liveness (фабрика ленивая, /health её не зовёт)
        client = TestClient(app)
        response = client.get("/health")
        assert response.status_code == 200, response.status_code
        assert response.json() == {"status": "ok"}, response.json()
    return "ровно {'status': 'ok'} при недоступной БД"


@oracle("G6CC-OPS-2 peek-семантика: GET /health/ops НЕ инициализирует фабрики")
def _ops_peek_semantics() -> str:
    from fastapi.testclient import TestClient

    from apps.api.main import app
    from apps.api import research_runs, session_store

    with EnvSandbox():
        client = TestClient(app)
        response = client.get("/health/ops")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["runs_backend"]["effective"] == "not_initialized", body
        assert body["session_backend"]["effective"] == "not_initialized", body
        assert body["readiness"]["runs"]["ok"] is None, body
        assert body["delivery"]["detail"] == "not_initialized", body
        # фабрика НЕ создана фактом запроса health
        assert research_runs.peek_research_run_store() is None
        assert session_store.peek_session_store() is None
    return "not_initialized честно; singleton'ы пусты после запроса"


@oracle("G6CC-OPS-3 форма /health/ops и отсутствие секретов при деградации")
def _ops_shape_no_secrets() -> str:
    from fastapi.testclient import TestClient

    from apps.api import storage_diagnostics
    from apps.api.main import app

    with EnvSandbox() as env:
        env.set("CISSTAT_RUNS_BACKEND", "memory")
        # ЯВНАЯ деградация с ВРАЖДЕБНОЙ причиной в снимке
        storage_diagnostics.record_backend_fallback(
            "runs", "postgres",
            f"boom {CERT_DSN_SECRET} token=t0ken-6cc-777 CERT-SEC-42",
            effective="memory",
        )
        client = TestClient(app)
        body = client.get("/health/ops").json()
        for key in (
            "status", "generated_at", "storage_mode", "runs_backend",
            "session_backend", "fallback_events", "readiness", "delivery",
            "worker", "models_dispatch",
        ):
            assert key in body, key
        assert body["status"] == "degraded", body["status"]
        assert body["storage_mode"] in {"advisory", "required"}
        for backend_key in ("configured", "effective", "degraded", "reason"):
            assert backend_key in body["runs_backend"], backend_key
        serialized = json.dumps(body, ensure_ascii=False)
        assert _no_secrets(serialized), (
            "тело /health/ops обязано быть без DSN/tokens"
        )
    return "все секции §26.3; degraded=True; секретов в теле нет"


@oracle("G6CC-OPS-4 degraded-агрегация: worker errors и dispatch")
def _ops_degraded_aggregation() -> str:
    from apps.api.research_runs import MemoryResearchRunStore
    from apps.api.session_store import MemorySessionStore
    from apps.api.storage_diagnostics import build_ops_health

    with EnvSandbox():
        healthy = build_ops_health(
            run_store=MemoryResearchRunStore(),
            session_store=MemorySessionStore(),
            worker_status={"consecutive_errors": 0, "running": True},
            models_dispatch={"ready": True},
        )
        assert healthy["status"] == "ok", healthy["status"]

        worker_bad = build_ops_health(
            run_store=MemoryResearchRunStore(),
            session_store=MemorySessionStore(),
            worker_status={
                "consecutive_errors": 3,
                "last_error": "cycle boom",
                "running": True,
            },
            models_dispatch={"ready": True},
        )
        assert worker_bad["status"] == "degraded", worker_bad["status"]

        dispatch_bad = build_ops_health(
            run_store=MemoryResearchRunStore(),
            session_store=MemorySessionStore(),
            worker_status={"consecutive_errors": 0},
            models_dispatch={
                "ready": False,
                "missing": ["cert6c-ghost"],
                "unexpected": ["cert6c-stray"],
            },
        )
        assert dispatch_bad["status"] == "degraded"

        readiness_bad = build_ops_health(
            run_store=None,  # readiness ok=None не деградирует
            session_store=MemorySessionStore(),
            worker_status={"consecutive_errors": 0},
            models_dispatch={"ready": True},
        )
        assert readiness_bad["status"] == "ok"
    return "ok-базлайн; degraded по worker/dispatch; ok=None не деградирует"


@oracle("G6CC-OPS-5 backlog/возраст/projection lag по СВОИМ обязательствам")
def _ops_backlog_lag() -> str:
    from apps.api.delivery_outbox import (
        DeliveryTask,
        bind_idempotency_key,
    )
    from apps.api.research_runs import MemoryResearchRunStore
    from apps.api.session_store import MemorySessionStore
    from apps.api.storage_diagnostics import build_ops_health

    with EnvSandbox():
        store = MemoryResearchRunStore()
        outbox = store.delivery_outbox
        old_iso = (
            datetime.now(timezone.utc) - timedelta(seconds=120)
        ).isoformat()

        def _task(op: str, created: str | None = None) -> DeliveryTask:
            return bind_idempotency_key(
                DeliveryTask(
                    operation_id=op,
                    idempotency_key=f"report:{RUN_CERT}:{op}",
                    run_id=RUN_CERT,
                    payload={"session_id": SESSION_CERT, "events": []},
                    created_at=created,
                    updated_at=created,
                ),
                f"report:{RUN_CERT}:{op}",
            )

        outbox.register(_task("op-cert6c-lag-p1", old_iso))
        outbox.register(_task("op-cert6c-lag-p2"))
        # f1: бюджет повторов исчерпывается честно (контракт backoff 6B):
        # 5 mark_failed -> state=failed (одиночный mark_failed держит
        # pending с attempts=1 -- задача на повторе).
        outbox.register(_task("op-cert6c-lag-f1"))
        from apps.api.delivery_outbox import DEFAULT_MAX_ATTEMPTS

        for _ in range(DEFAULT_MAX_ATTEMPTS):
            outbox.mark_failed(
                "op-cert6c-lag-f1",
                error="injected cert6c outage",
                next_attempt_at=old_iso,
                at=_now_iso(),
            )
        outbox.register(_task("op-cert6c-lag-d1"))
        outbox.mark_delivered("op-cert6c-lag-d1", delivered_at=_now_iso())

        body = build_ops_health(
            run_store=store,
            session_store=MemorySessionStore(),
            worker_status={"consecutive_errors": 0},
            models_dispatch={"ready": True},
        )
        delivery = body["delivery"]
        assert delivery["detail"] == "ok", delivery
        assert delivery["backlog"]["pending"] == 2, delivery
        assert delivery["backlog"]["failed"] == 1, delivery
        assert delivery["backlog"]["delivered"] == 1, delivery
        lag = delivery["projection_lag"]
        assert lag["pending_obligations"] == 2, lag
        assert lag["failed_obligations"] == 1, lag
        age = delivery["oldest_pending_age_seconds"]
        assert age is not None and 90 <= age <= 300, age
    return "backlog 2/1/1; lag=pending+failed=3; возраст старейшего ~120с"


# ════════════════════════════════════════════════════════════════════
# G6CC-WORKER: in-process worker восстановления (§26.5)
# ════════════════════════════════════════════════════════════════════


def _pending_obligation_from_map(report_id: str):
    """REQUIRED-карта с одноразовым отказом cache -> pending-обязательство
    (честный паттерн 6B на СВОИХ данных)."""
    from fastapi.testclient import TestClient

    from apps.api import research_runs
    from apps.api.routers.progress import EDA_CHECK_STATUS_VALUES
    from app.core.pipeline_graph import STAGE_NODES

    client = TestClient(research_runs_apps_app())
    run_id, context_id = _seed_upload_run(client)
    with OneShotSaveFailure(times=1):
        checks = {
            node_id: list(EDA_CHECK_STATUS_VALUES)[i % len(EDA_CHECK_STATUS_VALUES)]
            for i, node_id in enumerate(STAGE_NODES["eda"])
        }
        response = client.post(
            "/v1/progress/eda-checks",
            json={
                "checks": checks,
                "schema_version": 2,
                "run_id": run_id,
                "context_id": context_id,
                "report_id": report_id,
            },
        )
    assert response.status_code == 500, response.text
    run_store = research_runs.get_research_run_store()
    task = run_store.delivery_outbox.get_task(report_id)
    assert task is not None and task.state == "pending", task
    session_id = client.cookies.get("cisstat_session_id") or ""
    return run_store, session_id, report_id


def research_runs_apps_app():
    from apps.api.main import app

    return app


@oracle("G6CC-WORKER-1 run_once доставляет СВОЁ pending-обязательство")
def _worker_delivers() -> str:
    from apps.api import delivery_worker
    from apps.api.session_store import get_session_store

    with EnvSandbox() as env:
        env.set("CISSTAT_RUNS_BACKEND", "memory")
        run_store, session_id, report_id = _pending_obligation_from_map(
            REPORT_CERT
        )
        worker = delivery_worker.DeliveryWorker(
            run_store, interval=3600, session_store=get_session_store()
        )
        report = worker.run_once()
        assert report["delivery"]["delivered"] >= 1, report
        task = run_store.delivery_outbox.get_task(report_id)
        assert task is not None and task.state == "delivered", task
        session = get_session_store().get(session_id)
        assert session is not None
        assert any(
            item.get("event_type") == "eda_check_status"
            for item in session.pipeline_trace
        ), "проекция слоя 1 обязана быть восстановленной worker'ом"
        status = worker.status()
        assert status["consecutive_errors"] == 0, status
        assert status["last_summary"]["delivery"]["delivered"] >= 1
    return f"{REPORT_CERT}: pending -> delivered, слой 1 восстановлен"


@oracle("G6CC-WORKER-2 повторный run_once идемпотентен")
def _worker_idempotent() -> str:
    from apps.api import delivery_worker
    from apps.api.session_store import get_session_store

    with EnvSandbox() as env:
        env.set("CISSTAT_RUNS_BACKEND", "memory")
        run_store, _session_id, report_id = _pending_obligation_from_map(
            "cert6c-report-78"
        )
        worker = delivery_worker.DeliveryWorker(
            run_store, interval=3600, session_store=get_session_store()
        )
        first = worker.run_once()
        second = worker.run_once()
        assert first["delivery"]["delivered"] >= 1, first
        assert second["delivery"]["delivered"] == 0, second
        assert second["delivery"]["due"] == 0, second
        assert run_store.delivery_outbox.get_task(report_id).state == (
            "delivered"
        )
    return "первый доставляет, второй -- due=0/delivered=0"


@oracle("G6CC-WORKER-3 устойчивость: сбой цикла растит consecutive_errors, успех сбрасывает")
def _worker_resilience() -> str:
    import apps.api.delivery_worker as delivery_worker
    from apps.api import research_runs
    from apps.api.storage_diagnostics import safe_error  # noqa: F401

    with EnvSandbox() as env:
        env.set("CISSTAT_RUNS_BACKEND", "memory")
        run_store = research_runs.get_research_run_store()
        original_recovery = delivery_worker.run_delivery_recovery

        def _boom(*args, **kwargs):
            raise RuntimeError(f"pg down {CERT_DSN_SECRET} CERT-SEC-42")

        try:
            delivery_worker.run_delivery_recovery = _boom
            worker = delivery_worker.DeliveryWorker(run_store, interval=3600)
            worker.run_once()
            status = worker.status()
            assert status["consecutive_errors"] == 1, status
            assert _no_secrets(status["last_error"] or ""), status
        finally:
            delivery_worker.run_delivery_recovery = original_recovery
        worker.run_once()
        status = worker.status()
        assert status["consecutive_errors"] == 0, status
        assert status["last_error"] is None, status
    return "1 -> безопасный last_error -> успех сбрасывает в 0/None"


@oracle("G6CC-WORKER-4 env-выключатели: ENABLED и INTERVAL (клип/мусор)")
def _worker_env() -> str:
    import apps.api.delivery_worker as delivery_worker

    with EnvSandbox() as env:
        env.set("CISSTAT_DELIVERY_WORKER_ENABLED", "0")
        assert delivery_worker.start_delivery_worker() is None
        status = delivery_worker.delivery_worker_status()
        assert status["enabled"] is False and status["running"] is False
        env.set("CISSTAT_DELIVERY_WORKER_ENABLED", "false")
        assert delivery_worker.worker_enabled_from_env() is False
        env.set("CISSTAT_DELIVERY_WORKER_ENABLED", "NO")
        assert delivery_worker.worker_enabled_from_env() is False
        env.set("CISSTAT_DELIVERY_WORKER_ENABLED", "1")

        env.set("CISSTAT_DELIVERY_WORKER_INTERVAL", "0")
        assert delivery_worker.worker_interval_from_env() is None
        env.set("CISSTAT_DELIVERY_WORKER_INTERVAL", "3")
        assert delivery_worker.worker_interval_from_env() == (
            delivery_worker.MIN_INTERVAL_SECONDS
        )
        env.set("CISSTAT_DELIVERY_WORKER_INTERVAL", "seventy")
        with LogTap("apps.api.delivery_worker") as tap:
            value = delivery_worker.worker_interval_from_env()
        assert value == delivery_worker.DEFAULT_INTERVAL_SECONDS, value
        assert tap.messages and "seventy" in tap.messages[-1], tap.messages
    return "0/false/NO выкл; 0->None; 3->5; мусор->дефолт+warning"


@oracle("G6CC-WORKER-5 singleton идемпотентен, stop останавливает")
def _worker_singleton() -> str:
    import apps.api.delivery_worker as delivery_worker

    with EnvSandbox() as env:
        env.set("CISSTAT_DELIVERY_WORKER_INTERVAL", "3600")
        first = delivery_worker.start_delivery_worker()
        assert first is not None
        second = delivery_worker.start_delivery_worker()
        assert second is first, "повторный старт обязан вернуть тот же worker"
        assert delivery_worker.delivery_worker_status()["running"] is True
        delivery_worker.stop_delivery_worker()
        status = delivery_worker.delivery_worker_status()
        assert status["running"] is False, status
        assert delivery_worker._worker is None
    return "тот же экземпляр; после stop running=False"


@oracle("G6CC-WORKER-6 lifespan: авто-старт и остановка worker'а")
def _worker_lifespan() -> str:
    import apps.api.delivery_worker as delivery_worker
    from fastapi.testclient import TestClient

    from apps.api.main import app

    with EnvSandbox() as env:
        env.set("CISSTAT_DELIVERY_WORKER_ENABLED", "1")
        env.set("CISSTAT_DELIVERY_WORKER_INTERVAL", "3600")
        with TestClient(app):
            status = delivery_worker.delivery_worker_status()
            assert status["enabled"] is True and status["running"] is True, status
        status = delivery_worker.delivery_worker_status()
        assert status["running"] is False, status
    return "TestClient lifespan: running True внутри, False после выхода"


@oracle("G6CC-WORKER-7 статус worker'а виден в /health/ops")
def _worker_in_ops() -> str:
    from fastapi.testclient import TestClient

    from apps.api import research_runs
    from apps.api.main import app

    with EnvSandbox() as env:
        env.set("CISSTAT_RUNS_BACKEND", "memory")
        research_runs.get_research_run_store()
        body = TestClient(app).get("/health/ops").json()
        for key in (
            "enabled", "running", "interval_seconds",
            "consecutive_errors", "last_error",
        ):
            assert key in body["worker"], key
    return "worker-секция /health/ops несёт наблюдаемые поля"


# ════════════════════════════════════════════════════════════════════
# G6CC-DISPATCH: деградация Modeling dispatch (§26.2; Донастройка_2 п.2)
# ════════════════════════════════════════════════════════════════════


@oracle("G6CC-DISPATCH-1 полная среда: dispatch ready, множества согласованы")
def _dispatch_full_env() -> str:
    from apps.api.routers.models import models_dispatch_state

    state = models_dispatch_state()
    assert state["ready"] is True, state
    assert state["missing"] == [] and state["unexpected"] == [], state
    assert state["production_model_count"] > 0, state
    assert state["dispatch_model_count"] > 0, state
    assert isinstance(state.get("dropped_by_registry", []), list)
    return f"ready; production={state['production_model_count']}, dispatch={state['dispatch_model_count']}"


@oracle("G6CC-DISPATCH-2 лёгкая среда в СВЕЖЕМ интерпретаторе: импорт apps.api.main работает")
def _dispatch_light_env_subprocess() -> str:
    """НАСТОЯЩАЯ причина лёгкой среды -- отсутствие пакетных спеков:
    подмена importlib.util.find_spec для prophet/statsforecast в новом
    процессе (не importlib.reload и не подмена реестра)."""
    repo = os.getcwd()
    driver = (
        "import importlib.util, sys, json\n"
        "_orig = importlib.util.find_spec\n"
        "_BLOCK = {'prophet', 'statsforecast'}\n"
        "def _patched(name, *a, **k):\n"
        "    if name.split('.')[0] in _BLOCK:\n"
        "        return None\n"
        "    return _orig(name, *a, **k)\n"
        "importlib.util.find_spec = _patched\n"
        f"sys.path.insert(0, {repo!r})\n"
        "from apps.api.main import app\n"
        "routes = {getattr(r, 'path', '') for r in app.routes}\n"
        "from apps.api.routers.models import models_dispatch_state\n"
        "st = models_dispatch_state()\n"
        "print('RESULT', json.dumps({'import_ok': True,\n"
        "  'health': '/health' in routes, 'ops': '/health/ops' in routes,\n"
        "  'ready': st['ready'], 'dropped': sorted(st['dropped_by_registry']),\n"
        "  'missing': st['missing'], 'unexpected': st['unexpected']}))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", driver],
        capture_output=True, text=True, timeout=300, cwd=repo,
    )
    assert proc.returncode == 0, (
        f"импорт apps.api.main в лёгкой среде обязан работать\n"
        f"stdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}"
    )
    payload = None
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            payload = json.loads(line[len("RESULT "):])
            break
    assert payload is not None, proc.stdout
    assert payload["import_ok"] is True
    assert payload["health"] and payload["ops"], payload
    assert payload["ready"] is True, payload
    assert payload["missing"] == [], payload
    assert {"prophet", "tbats"} <= set(payload["dropped"]), payload
    return f"импорт OK, /health+/health/ops есть, честно dropped: {payload['dropped']}"


@oracle("G6CC-DISPATCH-3 runtime-дрейф theta -> 503 fail-closed В ТОЧКЕ ИСПОЛНЕНИЯ")
def _dispatch_execution_gate() -> str:
    from fastapi import HTTPException

    from apps.api.routers import models as models_module

    assert "theta" in models_module._BACKTEST_IMPLEMENTATIONS
    saved_impl = models_module._BACKTEST_IMPLEMENTATIONS.pop("theta")
    try:
        state = models_module.models_dispatch_state()
        assert state["ready"] is False, state
        assert "theta" in state["missing"], state
        own_series = [501.0, 498.5, 503.25, 499.75, 502.1, 500.0, 497.3]
        try:
            models_module._run_backtest_with_series(
                "theta", ("Theta", "statsmodels"),
                own_series, 0.6, 12,
            )
        except HTTPException as exc:
            assert exc.status_code == 503, exc.status_code
            assert "theta" in str(exc.detail), exc.detail
        else:
            raise AssertionError("дрейф обязан блокировать исполнение 503")
    finally:
        models_module._BACKTEST_IMPLEMENTATIONS["theta"] = saved_impl
    state = models_module.models_dispatch_state()
    assert state["ready"] is True, "после восстановления dispatch ready"
    return "state not ready + 'theta' in missing; исполнение -> 503"


@oracle("G6CC-DISPATCH-4 состояние dispatch видно в /health/ops")
def _dispatch_in_ops() -> str:
    from fastapi.testclient import TestClient

    from apps.api.main import app

    body = TestClient(app).get("/health/ops").json()
    md = body["models_dispatch"]
    assert md["ready"] is True, md
    for key in ("missing", "unexpected", "dropped_by_registry"):
        assert key in md, key
    return "models_dispatch.ready=True + missing/unexpected/dropped в health"


# ════════════════════════════════════════════════════════════════════
# G6CC-LOGS: операционные логи (§26.4) -- свой Handler
# ════════════════════════════════════════════════════════════════════


@oracle("G6CC-LOGS-1 отказ зеркала хука: ids + advisory-маркер + безопасная причина")
def _logs_hook_mirror() -> str:
    import asyncio

    from fastapi.testclient import TestClient

    from apps.api import trace_hook as th
    from apps.api.main import app
    from apps.api.session_store import get_session_store

    with EnvSandbox() as env:
        env.set("CISSTAT_RUNS_BACKEND", "memory")
        client = TestClient(app)
        run_id, _context = _seed_upload_run(client)
        session_id = client.cookies.get("cisstat_session_id") or ""
        assert session_id

        spec = th.resolve_trace_route("POST", "/v1/session/target-column")
        assert spec is not None

        store = get_session_store()
        session = store.get(session_id)
        assert session is not None

        captured: dict[str, str] = {}

        def _boom(session_obj, event_obj):
            # СВОЙ способ захватить event_id: событие уже в слое 1
            tail = session_obj.pipeline_trace[-1]
            if isinstance(tail, dict):
                captured["event_id"] = tail.get("event_id") or ""
                captured["run_id"] = tail.get("run_id") or ""
            else:
                captured["event_id"] = getattr(tail, "event_id", "")
                captured["run_id"] = getattr(tail, "run_id", "")
            raise RuntimeError(f"layer2 down for {CERT_DSN_SECRET} CERT-SEC-42")

        original_record_run_event = th.record_run_event
        th.record_run_event = _boom
        try:
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
            with LogTap("apps.api.trace_hook", level=logging.WARNING) as tap:
                asyncio.run(
                    middleware._record(
                        scope, spec, {"status": 200}, [],
                        [b'{"target_column": "pressure"}'],
                    )
                )
        finally:
            th.record_run_event = original_record_run_event

        assert captured.get("event_id"), "событие слоя 1 создано до отказа"
        messages = [m for m in tap.messages if "не записано" in m]
        assert messages, tap.messages
        message = messages[-1]
        assert captured["event_id"] in message, message
        assert run_id in message, message
        assert session_id in message, message
        assert "trace_hook_mirror" in message, message
        assert "advisory" in message.lower(), message
        assert _no_secrets(message), message
        assert "Traceback" not in message and "\n" not in message, message
    return "event/run/session ids + producer/advisory + safe reason, одна строка"


@oracle("G6CC-LOGS-2 отказ задачи доставки: operation/run/kind + попытка + safe reason")
def _logs_delivery_failure() -> str:
    from apps.api import research_runs
    from apps.api.delivery_outbox import (
        DEFAULT_MAX_ATTEMPTS,
        DeliveryTask,
        bind_idempotency_key,
        run_delivery_recovery,
    )

    class AlwaysFailingStore:
        def get(self, session_id):
            raise RuntimeError(f"redis gone {CERT_REDIS_SECRET}")

        def save(self, session):
            raise RuntimeError(f"redis gone {CERT_REDIS_SECRET}")

    with EnvSandbox() as env:
        env.set("CISSTAT_RUNS_BACKEND", "memory")
        run_store = research_runs.get_research_run_store()
        task = bind_idempotency_key(
            DeliveryTask(
                operation_id="op-cert6c-log-1",
                idempotency_key=f"report:{RUN_CERT}:op-cert6c-log-1",
                run_id=RUN_CERT,
                payload={"session_id": SESSION_CERT, "events": []},
            ),
            f"report:{RUN_CERT}:op-cert6c-log-1",
        )
        run_store.delivery_outbox.register(task)
        with LogTap("apps.api.delivery_outbox", level=logging.WARNING) as tap:
            # Бюджет повторов исчерпывается по РЕАЛЬНОМУ backoff-контракту:
            # после отказа задача НЕ due до next_attempt_at (гейт проверяем),
            # затем время продвигается за backoff -- следующая попытка.
            moment = datetime.now(timezone.utc)
            gate_check_done = False
            for _ in range(DEFAULT_MAX_ATTEMPTS + 1):
                summary = run_delivery_recovery(
                    run_store,
                    session_store=AlwaysFailingStore(),
                    now=moment,
                )
                current = run_store.delivery_outbox.get_task("op-cert6c-log-1")
                if current.state == "failed":
                    break
                if not gate_check_done:
                    # СРАЗУ после отказа задача не должна быть due (backoff)
                    gate = run_delivery_recovery(
                        run_store,
                        session_store=AlwaysFailingStore(),
                        now=moment,
                    )
                    assert gate["due"] == 0, gate
                    gate_check_done = True
                next_at = current.next_attempt_at
                assert next_at, "после отказа обязан быть назначен backoff"
                moment = datetime.fromisoformat(next_at) + timedelta(seconds=1)
            failed = run_store.delivery_outbox.get_task("op-cert6c-log-1")
        assert failed.state == "failed", (failed.state, failed.attempts)
        assert failed.attempts == DEFAULT_MAX_ATTEMPTS, failed.attempts
        assert gate_check_done, "гейт backoff обязан быть проверен"
        messages = [m for m in tap.messages if "op-cert6c-log-1" in m]
        assert len(messages) == DEFAULT_MAX_ATTEMPTS, messages
        message = messages[-1]
        assert RUN_CERT in message, message
        assert "layer1_mirror" in message, message
        assert f"{DEFAULT_MAX_ATTEMPTS}/" in message, message
        assert _no_secrets(message), message
        assert "\n" not in message and "Traceback" not in message, message
    return (
        f"бюджет {DEFAULT_MAX_ATTEMPTS} попыток по честному backoff -> "
        "state=failed; каждый отказ в логе с operation/run/kind/попыткой; "
        "между попытками задача не due"
    )


@oracle("G6CC-LOGS-3 отказ фабрики advisory: компонент/configured/effective в логе")
def _logs_factory_fallback() -> str:
    from apps.api import research_runs

    with EnvSandbox() as env:
        # РЕАЛЬНАЯ ошибка конфигурации (backend объявлен, URL нет):
        # конструктор падает -- advisory обязан ЯВНО деградировать и логировать.
        env.set("CISSTAT_RUNS_BACKEND", "postgres")
        env.unset("DATABASE_URL")
        with LogTap("apps.api.research_runs", level=logging.ERROR) as tap:
            store = research_runs.get_research_run_store()
        from apps.api.research_runs import MemoryResearchRunStore

        assert isinstance(store, MemoryResearchRunStore)
        assert tap.messages, "fallback обязан логироваться"
        message = "\n".join(tap.messages)
        lowered = message.lower()
        assert "postgres" in lowered and "memory" in lowered, message
        assert _no_secrets(message), message
    return "компонент и оба backend'а в логе; DSN/пароля нет"


# ════════════════════════════════════════════════════════════════════
# G6CC-DECL: драйвер/сборка (§26.2; F14/H29 -- декларации и их действие)
# ════════════════════════════════════════════════════════════════════


@oracle("G6CC-DECL-1 requirements.txt объявляет psycopg[binary]>=3.1.0")
def _decl_requirements() -> str:
    from pathlib import Path

    text = (
        Path("apps/api") / "requirements.txt"
    ).read_text(encoding="utf-8")
    assert "psycopg[binary]>=3.1.0" in text, (
        "драйвер обязан быть объявлен (F14/H29)"
    )
    assert "AUDIT-6C" in text, "декларация обязана быть помечена задачей"
    return "psycopg[binary]>=3.1.0 + пометка AUDIT-6C присутствуют"


@oracle("G6CC-DECL-2 Dockerfile проверяет драйвер и полный API startup")
def _decl_dockerfile() -> str:
    from pathlib import Path

    text = (Path("apps/api") / "Dockerfile").read_text(encoding="utf-8")
    assert "import psycopg" in text, "build-проверка драйвера обязательна"
    assert "from apps.api.main import app" in text, (
        "полный импорт apps.api.main на сборке обязателен"
    )
    assert "'/health/ops'" in text and "'/health'" in text, (
        "ассерты маршрутов /health и /health/ops обязательны"
    )
    return "3 build-гейта Dockerfile на месте"


@oracle("G6CC-DECL-3 Docker-эквивалент команды выполняется ЗДЕСЬ и сейчас")
def _decl_docker_equivalent() -> str:
    driver = (
        "import psycopg\n"
        "from apps.api.main import app\n"
        "routes = {getattr(r, 'path', '') for r in app.routes}\n"
        "assert '/health' in routes and '/health/ops' in routes, routes\n"
        "print('psycopg + full API startup OK:', psycopg.__version__)\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", driver],
        capture_output=True, text=True, timeout=300, cwd=os.getcwd(),
    )
    assert proc.returncode == 0, (
        f"Docker-эквивалент обязан проходить\nstderr={proc.stderr[-1500:]}"
    )
    assert "psycopg + full API startup OK" in proc.stdout, proc.stdout
    return proc.stdout.strip().splitlines()[-1]


# ════════════════════════════════════════════════════════════════════
# G6CC-PG: живой PostgreSQL (pgserver, СВОЙ tempdir) -- фактическая
# долговечность наблюдаема (§26.6)
# ════════════════════════════════════════════════════════════════════


_PG_DSN_CACHE: str | None = None


def _live_pg_dsn() -> str | None:
    """СВОЙ живой сервер (кэшируется на прогон -- один pgserver на все
    PG-оракулы; tempdir с префиксом cisstat6ccert-pg-*)."""
    global _PG_DSN_CACHE
    if _PG_DSN_CACHE is not None:
        return _PG_DSN_CACHE
    try:
        import pgserver
    except ImportError:
        return None
    import tempfile

    d = tempfile.mkdtemp(prefix="cisstat6ccert-pg-")
    server = pgserver.get_server(d, cleanup_mode="delete")
    _PG_DSN_CACHE = server.get_uri()
    return _PG_DSN_CACHE


def _pg_clean_schema(dsn: str) -> None:
    import psycopg

    conn = psycopg.connect(dsn, autocommit=False)
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
    conn.close()


def _pg_migrate(dsn: str) -> None:
    """Штатные миграции (0001-0005) -- НЕ probe'ом, честный путь схемы."""
    import psycopg

    from apps.api.research_runs import run_migrations

    conn = psycopg.connect(dsn, autocommit=False)
    run_migrations(conn)
    conn.commit()
    conn.close()


@oracle("G6CC-PG-1 required на ЖИВОЙ БД: фабрика выбирает настоящий Postgres")
def _pg_required_selected() -> str:
    from apps.api import research_runs, storage_diagnostics

    dsn = _live_pg_dsn()
    if dsn is None:
        return "SKIP: pgserver недоступен в этой среде (честный skip)"
    _pg_clean_schema(dsn)
    _pg_migrate(dsn)  # совместимая схема -- probe обязан быть зелёным
    with EnvSandbox() as env:
        env.set("CISSTAT_STORAGE_MODE", "required")
        env.set("DATABASE_URL", dsn)
        store = research_runs.get_research_run_store()  # БЕЗ подмены probe
        from apps.api.research_runs import PostgresResearchRunStore

        assert isinstance(store, PostgresResearchRunStore), type(store)
        runs = storage_diagnostics.storage_backend_snapshot()["runs_backend"]
        assert runs["configured"] == "postgres", runs
        assert runs["effective"] == "postgres", runs
        assert runs["degraded"] is False, runs
    return "живой Postgres выбран fail-closed-путём с реальным probe"


@oracle("G6CC-PG-2 probe живой БД ok с латентностью; НЕ-мигрированная БД честно ok=False")
def _pg_probe_migration_states() -> str:
    from apps.api.research_runs import PostgresResearchRunStore

    dsn = _live_pg_dsn()
    if dsn is None:
        return "SKIP: pgserver недоступен в этой среде (честный skip)"
    _pg_clean_schema(dsn)
    store = PostgresResearchRunStore(dsn=dsn)
    fresh = store.readiness_probe()
    assert fresh["ok"] is False, (
        "не-мигрированная БД обязана быть честно не готова"
    )
    assert fresh["backend"] == "postgres", fresh
    assert fresh.get("error"), fresh
    # Схема создаётся штатной операцией записи (не probe'ом) --
    # после неё probe зелёный: состояние миграции НАБЛЮДАЕМО.
    from apps.api.research_runs import ResearchRun

    store.upsert_run(
        ResearchRun(
            run_id=RUN_CERT_PG,
            session_id=SESSION_CERT_PG,
            dataset_fingerprint="fp-cert6c-pg",
            dataset_name="hydrogen-ops",
        )
    )
    ready = store.readiness_probe()
    assert ready["ok"] is True, ready
    assert isinstance(ready.get("latency_ms"), (int, float)), ready
    return f"ok=False на пустой схеме -> ok=True после миграций ({ready['latency_ms']}ms)"


@oracle("G6CC-PG-3 backlog age: паритет Memory и живого Postgres")
def _pg_backlog_parity() -> str:
    from apps.api.delivery_outbox import DeliveryTask, bind_idempotency_key
    from apps.api.research_runs import (
        MemoryResearchRunStore,
        PostgresResearchRunStore,
        ResearchRun,
    )

    dsn = _live_pg_dsn()
    if dsn is None:
        return "SKIP: pgserver недоступен в этой среде (честный skip)"
    _pg_clean_schema(dsn)
    _pg_migrate(dsn)
    pg_store = PostgresResearchRunStore(dsn=dsn)
    # FK миграции 0005: обязательство ссылается на СУЩЕСТВУЮЩИЙ run.
    pg_store.upsert_run(
        ResearchRun(
            run_id=RUN_CERT,
            session_id=SESSION_CERT,
            dataset_fingerprint="fp-cert6c",
            dataset_name="ops-age-parity",
        )
    )
    created = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    memory_store = MemoryResearchRunStore()
    for store, op in (
        (memory_store, "op-cert6c-parity-m"),
        (pg_store, "op-cert6c-parity-pg"),
    ):
        task = bind_idempotency_key(
            DeliveryTask(
                operation_id=op,
                idempotency_key=f"report:{RUN_CERT}:{op}",
                run_id=RUN_CERT,
                payload={"session_id": SESSION_CERT, "events": []},
                created_at=created,
                updated_at=created,
            ),
            f"report:{RUN_CERT}:{op}",
        )
        store.delivery_outbox.register(task)
        age = store.delivery_outbox.backlog_age_seconds(_now_iso())
        assert age is not None and 30 <= age <= 180, (op, age)
        store.delivery_outbox.mark_delivered(op, delivered_at=_now_iso())
        assert store.delivery_outbox.backlog_age_seconds(_now_iso()) is None
    return "возраст ~60с и честный None на ОБОИХ backend'ах"


@oracle("G6CC-PG-4 worker доставляет СВОЁ обязательство на живом PG")
def _pg_worker_delivers() -> str:
    from apps.api import delivery_worker
    from apps.api.delivery_outbox import DeliveryTask, bind_idempotency_key
    from apps.api.research_runs import (
        PostgresResearchRunStore,
        ResearchRun,
    )
    from apps.api.session_store import AnalysisSession, MemorySessionStore
    from apps.api.trace_events import make_trace_event
    from app.core.pipeline_graph import STAGE_NODES

    dsn = _live_pg_dsn()
    if dsn is None:
        return "SKIP: pgserver недоступен в этой среде (честный skip)"
    _pg_clean_schema(dsn)
    pg_store = PostgresResearchRunStore(dsn=dsn)
    pg_store.upsert_run(
        ResearchRun(
            run_id=RUN_CERT_PG,
            session_id=SESSION_CERT_PG,
            dataset_fingerprint="fp-cert6c-pg",
            dataset_name="ops-worker",
        )
    )
    session_store_obj = MemorySessionStore()
    session = AnalysisSession(session_id=SESSION_CERT_PG)
    event = make_trace_event(
        "eda_check_status",
        stage="eda",
        node_id=next(iter(STAGE_NODES["eda"])),
        run_id=RUN_CERT_PG,
        check="stationarity",
        status="done",
    )
    session.append_trace_event(event)
    session_store_obj.save(session)
    task = bind_idempotency_key(
        DeliveryTask(
            operation_id="op-cert6c-pg-worker-1",
            idempotency_key=f"report:{RUN_CERT_PG}:op-cert6c-pg-worker-1",
            run_id=RUN_CERT_PG,
            payload={
                "session_id": SESSION_CERT_PG,
                "events": [event.to_dict()],
            },
        ),
        f"report:{RUN_CERT_PG}:op-cert6c-pg-worker-1",
    )
    pg_store.delivery_outbox.register(task)
    worker = delivery_worker.DeliveryWorker(
        pg_store, interval=3600, session_store=session_store_obj
    )
    report = worker.run_once()
    assert report["delivery"]["delivered"] == 1, report
    delivered = pg_store.delivery_outbox.get_task("op-cert6c-pg-worker-1")
    assert delivered.state == "delivered", delivered.state
    fresh = session_store_obj.get(SESSION_CERT_PG)
    event_ids = {
        item.get("event_id")
        for item in fresh.pipeline_trace
        if isinstance(item, dict)
    }
    assert event.event_id in event_ids
    return f"{RUN_CERT_PG}: pending -> delivered, событие {event.event_id} в слое 1"


# ════════════════════════════════════════════════════════════════════
# Runner
# ════════════════════════════════════════════════════════════════════


def main(argv: list[str]) -> int:
    include_pg = "--no-pg" not in argv
    for name, fn in ORACLES:
        if not include_pg and name.startswith("G6CC-PG"):
            RESULTS.append((name, True, "SKIP: --no-pg"))
            continue
        try:
            detail = fn()
            RESULTS.append((name, True, detail or "OK"))
        except AssertionError as exc:
            RESULTS.append((name, False, f"ASSERT: {exc}"))
        except Exception as exc:  # noqa: BLE001 -- оракул обязан продолжать
            RESULTS.append((
                name, False, f"ERROR {type(exc).__name__}: {exc}",
            ))
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = len(RESULTS) - passed
    print("=" * 74)
    print("PROGR-AUDIT-6C-CERT: оракулы сертификатора (свои данные)")
    print(f"Итог: {passed} PASS / {failed} FAIL из {len(RESULTS)}")
    for name, ok, detail in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name} -- {detail}")
    print("=" * 74)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

