# apps/api/storage_diagnostics.py
"""
Операционная диагностика хранилищ, health и операционные логи
(AUDIT-6C, plan_progress_audit.md §18; контракт
docs/progress_audit_contract.md аддендум v1.6-6C §26;
spec_progress_audit.md §7/§8.3/§8.4).

Три опоры контура:

1. **Режимы хранения (п.1; P21/F14).** CISSTAT_STORAGE_MODE:
   - ``required`` -- explicit durable-контур: неверная конфигурация /
     отсутствие драйвера / несовместимая миграция / недоступная БД
     ЗАПРЕЩАЮТ тихий Memory fallback (RuntimeError на первом обращении
     к фабрике -- fail-closed; «required не деградирует незаметно»);
   - ``advisory`` (default) -- dev/мягкий режим: fallback в Memory
     ДОПУСТИМ, но effective backend ЯВЕН: фабрика фиксирует
     configured/effective/degraded + безопасную причину отказа, а
     /health/ops и логи её показывают («тихий» запрещён даже здесь).

2. **Безопасные причины (п.4).** safe_error(): операционные логи и
   health НЕ выдают URL БД, tokens, пароли и сырые exception payload'ы
   -- DSN-схемы (postgres://, rediss://...), password=/Bearer
   редактируются, длина клипируется. Содержательная причина при этом
   сохраняется (диагностика не превращается в «unknown error»).

3. **Наблюдаемость (п.3).** Снимок фабрик хранилищ (configured /
   effective / degraded / события fallback) + readiness-пробы по
   требованию + сборка тела /health/ops. Научные факты не заменяются
   operational-снимками: здесь нет состояния трассы, только состояние ИНФРА-
   структуры доставки.

Модуль не импортирует ничего из apps.api (кроме ленивых импортов в
build_ops_health) -- его импортируют research_runs/session_store/
delivery_outbox/delivery_worker/trace_hook, циклы исключены.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Режимы хранения (п.1; P21/F14) ───────────────────────────────────

STORAGE_MODE_ENV = "CISSTAT_STORAGE_MODE"
STORAGE_MODE_ADVISORY = "advisory"
STORAGE_MODE_REQUIRED = "required"
_VALID_MODES = (STORAGE_MODE_ADVISORY, STORAGE_MODE_REQUIRED)

# Компоненты хранения (фабрики фиксируют выбор по этим ключам).
COMPONENT_RUNS = "runs"        # ResearchRunStore (+ durable outbox)
COMPONENT_SESSION = "session"  # SessionStore (cache слоя 1)


def get_storage_mode() -> str:
    """Действующий режим хранения. Неизвестное значение -- fail fast
    (опечатка в конфигурации не должна тихо означать advisory: в
    required-окружении это скрыло бы fail-closed контракт)."""
    raw = os.environ.get(STORAGE_MODE_ENV, "").strip().lower()
    if not raw:
        return STORAGE_MODE_ADVISORY
    if raw not in _VALID_MODES:
        raise RuntimeError(
            f"{STORAGE_MODE_ENV}={raw!r} не поддерживается; "
            f"допустимо: {'|'.join(_VALID_MODES)} (AUDIT-6C)"
        )
    return raw


# ── Безопасная причина (п.4) ─────────────────────────────────────────

_SAFE_ERROR_LIMIT = 300

# DSN/URL со схемой (учётные данные внутри) редактируются ЦЕЛИКОМ до
# конца токена -- в строке ошибки не остаётся ни хоста, ни пароля.
_URL_RE = re.compile(
    r"\b(?:postgres(?:ql)?|redis|rediss|mysql|mongodb(?:\+srv)?|amqps?|"
    r"https?)://\S+",
    re.IGNORECASE,
)
# key=value-секреты и Bearer-токены: значение редактируется, ключ остаётся.
_KV_SECRET_RE = re.compile(
    r"\b(password|passwd|pwd|token|secret|api[_-]?key|authorization)\s*[=:]\s*\S+",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/-]+=*", re.IGNORECASE)


def safe_error(value: Any, limit: int = _SAFE_ERROR_LIMIT) -> str:
    """Безопасная причина отказа для operational-логов и health (п.4):
    URL/DSN целиком, password=/token=/Bearer-значения -- редактируются;
    длина клипируется; содержательная часть сохраняется. Никогда не
    бросает: любой вход -> строка."""
    if value is None:
        return "unknown error"
    if isinstance(value, BaseException):
        text = str(value) or type(value).__name__
    else:
        text = str(value)
    text = _URL_RE.sub("<redacted-url>", text)
    text = _BEARER_RE.sub("<redacted-credentials>", text)
    text = _KV_SECRET_RE.sub(lambda m: f"{m.group(1)}=<redacted>", text)
    text = " ".join(text.split())  # схлопывание переводов строк трейсов
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text or "unknown error"


def safe_health_error(value: Any) -> str:
    """Причина отказа для ТЕЛА /health/ops (п.3: «не выдавать URL БД,
    tokens или сырые exception payload"). Сообщения драйверов
    (psycopg/redis) содержат голые hostname/порты даже вне URL-схемы,
    поэтому health несёт только КЛАСС исключения; содержательная
    диагностика -- в operational-логи (safe_error, без секретов)."""
    if isinstance(value, BaseException):
        return f"{type(value).__name__} (детали в operational-логах)"
    return safe_error(value, limit=120)


# ── Состояние фабрик (configured/effective/degraded) ─────────────────

_BACKEND_STATE_LOCK = threading.Lock()
_backend_state: dict[str, dict[str, Any]] = {}
_fallback_events: list[dict[str, Any]] = []
_FALLBACK_EVENTS_MAX = 50


def _honest_backend(component: str) -> dict[str, Any]:
    """Честное отсутствие решения: фабрика ещё не выбирала backend."""
    return {
        "configured": "unknown",
        "effective": "not_initialized",
        "degraded": False,
        "reason": None,
    }


def record_backend_selected(
    component: str,
    configured: str,
    effective: str,
    *,
    reason: Optional[str] = None,
    degraded: bool = False,
) -> None:
    """Фабрика фиксирует выбор backend (в т.ч. auto -> memory)."""
    with _BACKEND_STATE_LOCK:
        _backend_state[component] = {
            "configured": configured,
            "effective": effective,
            "degraded": bool(degraded),
            "reason": reason,
        }


def record_backend_fallback(
    component: str,
    configured: str,
    reason: str,
    *,
    effective: str = "memory",
) -> None:
    """Явная деградация (advisory): выбор effective + событие fallback
    с безопасной причиной. В required-режиме фабрика этот путь не
    проходит (fail-closed RuntimeError вместо fallback)."""
    event = {
        "component": component,
        "configured": configured,
        "effective": effective,
        "reason": safe_error(reason),
        "storage_mode": get_storage_mode(),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    with _BACKEND_STATE_LOCK:
        _backend_state[component] = {
            "configured": configured,
            "effective": effective,
            "degraded": True,
            "reason": event["reason"],
        }
        _fallback_events.append(event)
        if len(_fallback_events) > _FALLBACK_EVENTS_MAX:
            del _fallback_events[: len(_fallback_events) - _FALLBACK_EVENTS_MAX]


def describe_backend(component: str) -> dict[str, Any]:
    with _BACKEND_STATE_LOCK:
        state = _backend_state.get(component)
        if state is not None:
            return dict(state)
    return _honest_backend(component)


def storage_backend_snapshot() -> dict[str, Any]:
    """Снимок фабрик: configured/effective/degraded + события fallback.
    Basis /health/ops и тестов деградации; НЕ состояние фактов."""
    with _BACKEND_STATE_LOCK:
        events = list(_fallback_events)
        states = {key: dict(value) for key, value in _backend_state.items()}
    runs_backend = states.get(COMPONENT_RUNS, _honest_backend(COMPONENT_RUNS))
    session_backend = states.get(
        COMPONENT_SESSION, _honest_backend(COMPONENT_SESSION)
    )
    degraded = bool(
        runs_backend.get("degraded") or session_backend.get("degraded")
    )
    return {
        "storage_mode": get_storage_mode(),
        "degraded": degraded,
        "runs_backend": runs_backend,
        "session_backend": session_backend,
        "fallback_events": events,
    }


def reset_storage_diagnostics_for_testing() -> None:
    """Сброс операционного состояния. ТОЛЬКО для тестов."""
    with _BACKEND_STATE_LOCK:
        _backend_state.clear()
        _fallback_events.clear()


# ── Readiness-пробы (по требованию, без side-эффектов) ───────────────


def probe_store(store: Any, *, component: str) -> dict[str, Any]:
    """Readiness-проба хранилища по требованию (п.3): store обязателен
    методом readiness_probe() (ABC-дефолт: ok/unknown). Latency
    замеряется; причина отказа -- safe_error (без DSN). Проба НЕ
    инициализирует фабрики и не пишет факты."""
    if store is None:
        return {"ok": None, "component": component, "detail": "not_initialized"}
    start = time.monotonic()
    try:
        result = store.readiness_probe()
    except Exception as exc:  # защитный контур: проба не роняет health
        return {
            "ok": False,
            "component": component,
            "latency_ms": round((time.monotonic() - start) * 1000, 2),
            "error": safe_health_error(exc),
        }
    if not isinstance(result, dict) or "ok" not in result:
        return {
            "ok": False,
            "component": component,
            "latency_ms": round((time.monotonic() - start) * 1000, 2),
            "error": "readiness_probe вернул некорректный результат",
        }
    result = dict(result)
    result.setdefault("component", component)
    result["latency_ms"] = round((time.monotonic() - start) * 1000, 2)
    if result.get("error"):
        result["error"] = safe_error(result["error"])
    return result


# ── Тело /health/ops (п.3) ───────────────────────────────────────────


def build_identity_health() -> dict[str, Any]:
    """DOCLOG-0 (§19.1): identity-блок /health/ops -- режим идентичности,
    факт применения owner-гейта к run-контуру, серверный дефолт-tenant и
    факт конфигурации реестра ключей. НИКАКИХ значений ключей/субъектов
    (T6: секреты не попадают в операционные поверхности)."""
    from apps.api.identity import (
        DEFAULT_TENANT_ID,
        get_identity_mode,
        is_key_registry_configured,
    )

    return {
        "mode": get_identity_mode(),
        "run_ownership_enforcement": "owner_bound",
        "default_tenant": DEFAULT_TENANT_ID,
        "api_key_registry_configured": is_key_registry_configured(),
    }


def build_ops_health(
    *,
    run_store: Any = None,
    session_store: Any = None,
    worker_status: Optional[dict[str, Any]] = None,
    models_dispatch: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Собирает operational-диагностику (п.3): backend фабрик, storage
    readiness, delivery backlog/возраст, projection lag, degraded mode,
    worker, models dispatch. НЕ выдаёт URL БД/tokens/сырые exceptions;
    НЕ заменяет научные факты (это состояние инфраструктуры, не трасса).

    projection lag (определение контракта §26.3): committed-обязательства
    проекции слоя 1, ещё не доставленные в навигационный слой --
    pending + failed outbox (дельта между ledger и проекцией, N фактов).
    """
    from apps.api.delivery_outbox import (
        STATE_FAILED,
        STATE_PENDING,
        STATE_DELIVERED,
    )

    snapshot = storage_backend_snapshot()
    readiness = {
        "runs": probe_store(run_store, component=COMPONENT_RUNS),
        "session": probe_store(session_store, component=COMPONENT_SESSION),
    }

    delivery: dict[str, Any] = {
        "backlog": None,
        "oldest_pending_age_seconds": None,
        "projection_lag": None,
        "detail": "not_initialized",
    }
    if run_store is not None:
        outbox = getattr(run_store, "delivery_outbox", None)
        if outbox is not None:
            now_iso = datetime.now(timezone.utc).isoformat()
            try:
                backlog = dict(outbox.backlog())
                pending = int(backlog.get(STATE_PENDING, 0))
                failed = int(backlog.get(STATE_FAILED, 0))
                delivered = int(backlog.get(STATE_DELIVERED, 0))
                age = outbox.backlog_age_seconds(now_iso)
                delivery = {
                    "backlog": {
                        STATE_PENDING: pending,
                        STATE_DELIVERED: delivered,
                        STATE_FAILED: failed,
                    },
                    "oldest_pending_age_seconds": (
                        round(float(age), 2) if age is not None else None
                    ),
                    "projection_lag": {
                        # «Ledger committed, навигационный слой ещё не знает»:
                        # pending + failed обязательства проекции (§26.3).
                        "pending_obligations": pending,
                        "failed_obligations": failed,
                    },
                    "detail": "ok",
                }
            except Exception as exc:  # проба доставки не роняет health
                delivery = {
                    "backlog": None,
                    "oldest_pending_age_seconds": None,
                    "projection_lag": None,
                    "detail": safe_health_error(exc),
                }

    if worker_status is None:
        try:
            from apps.api.delivery_worker import delivery_worker_status

            worker_status = delivery_worker_status()
        except Exception:  # pragma: no cover - защитный контур
            worker_status = {"enabled": False, "running": False}

    degraded = bool(
        snapshot["degraded"]
        or readiness["runs"].get("ok") is False
        or readiness["session"].get("ok") is False
        or (worker_status or {}).get("consecutive_errors", 0)
        or not (models_dispatch or {}).get("ready", True)
    )

    return {
        "status": "degraded" if degraded else "ok",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "storage_mode": snapshot["storage_mode"],
        "runs_backend": snapshot["runs_backend"],
        "session_backend": snapshot["session_backend"],
        "fallback_events": snapshot["fallback_events"],
        "readiness": readiness,
        "delivery": delivery,
        "worker": worker_status,
        "models_dispatch": models_dispatch or {"ready": True},
        # DOCLOG-0 (§19.1, operational counters): честный режим
        # идентичности и факт конфигурации реестра ключей (bool, БЕЗ
        # значений/DSN -- T6). enforcement -- факт применения
        # объектной авторизации к run-контуру.
        "identity": build_identity_health(),
    }
