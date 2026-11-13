"""F-CERT-H1 (AUTH-CERT, 13.11.2026): прогрев durable-слоёв ДО начала
обслуживания.

Находка F-CERT-H1: lazy-миграция durable-слоёв внутри первого запроса
самодедлочится -- каждый Postgres-слой лениво гоняет полный ops-каталог
``research_runs.run_migrations`` на первом коннекте процесса, каталог
содержит ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` (trace_events и
др.), который берёт ACCESS EXCLUSIVE на таблицу даже как no-op. Первый
запрос, который держит незакрытую транзакцию на conn A (trace-событие,
bound-транзакция AUTH-16) и синхронно обращается ко второму слою на
conn B (mandatory audit), получает клиентский дедлок: conn B ждёт
ACCESS EXCLUSIVE у транзакции conn A, поток запроса ждёт conn B.
Воспроизведено на приёмке AUTH-CERT и первом CI-прогоне (pg_stat_activity:
AccessExclusive/ShareLock цикл); тестовый harness устранял прогревом
синглтонов до обслуживания -- эта поставка переносит тот порядок в
продовый код.

Контракт (docs/authcert/h1fix.md):
- ``warmup_durable_layers()`` вызывается в ``_lifespan`` ПОСЛЕ
  ``verify_required_storage_backends()`` (фабрики fail-closed раньше) и
  ДО worker-credential bootstrap, телеметрии и старта воркеров;
- required-режим: каждый слой реестра получает ``ensure_schema()``
  (идемпотентный DDL-прогон каталога, один на слой за процесс); отказ
  обязательного слоя -> RuntimeError (fail-closed AUDIT-6C); отказ
  telemetry проглатывается (AC11 -- телеметрия никогда не роняет старт);
- advisory/auto: честный no-op -- ленивый контракт dev/тестов сохранён
  (фабрики не создаются, соединения не открываются);
- статус последнего прогона -- peek-семантика для /health/ops
  (``last_warmup_status()``), без DSN/секретов (safe_error).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger("uvicorn.error")

# ── Реестр слоёв (D5) ──────────────────────────────────────────────────
# (имя, критичность). Новый durable-слой с lazy-DDL присоединяется
# сознательно: строка здесь + ensure_schema на классе + пин
# EXPECTED_LAYERS в tests/unit/test_warmup_fcert_h1.py. Критичность
# False только у телеметрии (контракт AC11: сбой телеметрии не влияет
# на старт).
_LAYERS: Tuple[Tuple[str, bool], ...] = (
    ("audit", True),
    ("telemetry", False),
    ("session", True),
    ("runs", True),
    ("artifacts", True),
    ("snapshots", True),
    ("documents", True),
    ("lifecycle", True),
    ("support_grants", True),
    ("admin_logs", True),
    ("monitoring", True),
    ("org_profiles", True),
)


def _access_audit() -> Any:
    from apps.api.security_audit import get_audit_sink

    return get_audit_sink()


def _access_telemetry() -> Any:
    from apps.api.telemetry import _pipeline

    return _pipeline.sink()


def _access_session() -> Any:
    from apps.api.session_store import get_session_store

    return get_session_store()


def _access_runs() -> Any:
    from apps.api.research_runs import get_research_run_store

    return get_research_run_store()


def _access_artifacts() -> Any:
    from apps.api.artifact_store import get_artifact_registry

    return get_artifact_registry()


def _access_snapshots() -> Any:
    from apps.api.report_snapshot import get_snapshot_registry

    return get_snapshot_registry()


def _access_documents() -> Any:
    from apps.api.document_jobs import get_document_registry

    return get_document_registry()


def _access_lifecycle() -> Any:
    from apps.api.document_lifecycle import get_document_lifecycle_registry

    return get_document_lifecycle_registry()


def _access_support_grants() -> Any:
    from apps.api.admin_logs import get_support_grant_registry

    return get_support_grant_registry()


def _access_admin_logs() -> Any:
    """Module-global lazy-DDL слой admin_logs (_pg_connect):
    публичный прайм -- ensure_logs_schema() модуля. Возвращается
    адаптер с ensure_schema-поверхностью для единого контракта."""
    from apps.api import admin_logs

    class _ModuleLogsPrime:
        def ensure_schema(self) -> None:
            admin_logs.ensure_logs_schema()

    return _ModuleLogsPrime()


def _access_monitoring() -> Any:
    from apps.api.monitoring import get_monitoring_registry

    return get_monitoring_registry()


def _access_org_profiles() -> Any:
    from apps.api.doc_profiles import get_org_profile_registry

    return get_org_profile_registry()


# Аксессоры отдельным словарём: unit-тесты патчат их по имени
# (storage_warmup._LAYER_ACCESSORS.<name>), реестр _LAYERS пинит
# состав и критичность.
_LAYER_ACCESSORS: Dict[str, Callable[[], Any]] = {
    "audit": _access_audit,
    "telemetry": _access_telemetry,
    "session": _access_session,
    "runs": _access_runs,
    "artifacts": _access_artifacts,
    "snapshots": _access_snapshots,
    "documents": _access_documents,
    "lifecycle": _access_lifecycle,
    "support_grants": _access_support_grants,
    "admin_logs": _access_admin_logs,
    "monitoring": _access_monitoring,
    "org_profiles": _access_org_profiles,
}

# ── Статус последнего прогона (peek для /health/ops, D7) ──────────────

_status_lock = threading.Lock()
_last_status: Optional[Dict[str, Any]] = None


def last_warmup_status() -> Optional[Dict[str, Any]]:
    """Чтение статуса последнего прогона прогрева (peek-семантика
    /health/ops: не инициализирует фабрики, не роняет health). None --
    прогрев ещё не выполнялся (до старта/в advisory после сброса)."""
    with _status_lock:
        return _last_status


def reset_warmup_status_for_testing() -> None:
    global _last_status
    with _status_lock:
        _last_status = None


# ── Прогрев ────────────────────────────────────────────────────────────


def _prime_layer(accessor: Callable[[], Any]) -> str:
    """Прогрев одного слоя. Backend с ensure_schema (Postgres) --
    идемпотентный DDL-прогон; Memory/Redis (без ensure_schema) --
    честный skipped: DDL-каталог к такому backend неприменим."""
    instance = accessor()
    ensure = getattr(instance, "ensure_schema", None)
    if not callable(ensure):
        return "skipped"
    ensure()
    return "primed"


def warmup_durable_layers() -> Dict[str, Any]:
    """Прогрев всех durable-слоёв реестра ДО начала обслуживания.

    required: каждый слой получает ensure_schema() -- после этого ни
    один запрос не выполняет lazy-DDL (класс дедлока F-CERT-H1 закрыт).
    Отказ обязательного слоя -> RuntimeError (safe_error, старт роняется
    по доктрине fail-closed); статус фиксируется ДО подъёма исключения,
    чтобы /health/ops (или лог) видел честную причину. advisory/auto:
    no-op без открытия соединений.

    Возвращаемое значение -- статус для лога/health: {state, mode, ts,
    layers?}: state -- primed | degraded | error | skipped.
    """
    global _last_status
    from apps.api.storage_diagnostics import get_storage_mode, safe_error

    mode = get_storage_mode()
    status: Dict[str, Any] = {
        "state": "skipped",
        "mode": mode,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if mode != "required":
        # Ленивый контракт dev/тестов (AUDIT-6C): advisory-старт не
        # открывает соединений и не создаёт фабрик.
        with _status_lock:
            _last_status = dict(status)
        logger.info("Storage warmup: skipped (mode=%s, advisory-lazy)", mode)
        return status

    layers: Dict[str, str] = {}
    failures: Dict[str, str] = {}
    for name, critical in _LAYERS:
        try:
            layers[name] = _prime_layer(_LAYER_ACCESSORS[name])
        except Exception as exc:  # noqa: BLE001 -- safe_error ниже
            layers[name] = "error"
            failures[name] = safe_error(exc)
            if not critical:
                # AC11: телеметрия никогда не роняет старт.
                logger.warning(
                    "Storage warmup: telemetry layer failed (некритично): %s",
                    failures[name],
                )
            else:
                logger.error(
                    "Storage warmup: layer %s failed (fail-closed): %s",
                    name,
                    failures[name],
                )
    status["layers"] = layers
    if failures:
        status["state"] = "degraded" if all(
            name == "telemetry" for name in failures
        ) else "error"
        status["failures"] = dict(failures)
    else:
        status["state"] = "primed"
    with _status_lock:
        _last_status = dict(status)
    if status["state"] == "error":
        # Fail-closed (AUDIT-6C, P21/F14): обязательный слой с
        # неготовой схемой не начинает обслуживать запросы.
        raise RuntimeError(
            "Storage warmup: обязательные durable-слои не прогреты "
            f"(fail-closed, F-CERT-H1): {sorted(failures)}"
        )
    logger.info("Storage warmup: %s (mode=%s)", status["state"], mode)
    return status
