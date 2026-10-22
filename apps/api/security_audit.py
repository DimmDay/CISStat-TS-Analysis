# apps/api/security_audit.py
"""
DOCLOG-3 (spec_documentation_logging.md §14, §19 строка DOCLOG-3,
§19.1, §20 AC10/AC11): durable security audit foundation -- отдельный
append-only журнал действий с защищёнными ресурсами.

ПРЕДМЕТ АУДИТА (§14.1): аутентификационные/авторизационные отказы,
создание/изменение прав и support grants, просмотр защищённого
документа, запрос/выдача выгрузки, approval/publication/revocation,
смена шаблона/retention policy, административный доступ к журналу,
запуск cleanup/restore и integrity verification. Каждая запись --
кто (псевдоним субъекта), когда, tenant/resource/version, действие,
разрешено/отказано/прервано, основание политики и correlation refs.

КЛЮЧЕВЫЕ РАЗЛИЧЕНИЯ:
  - download_requested / response_stream_started /
    response_stream_finished -- разные события; сервер не удостоверяет
    чтение файла пользователем: действия human_read_confirmed НЕ
    существует (явное подтверждение прочтения -- отдельное действие
    будущего контура);
  - в аудит НЕ копируются body документа и значение API-key
    (details проходят redaction R08);
  - run_id в audit-записи РАЗРЕШЁН (серверный контекст аудита; это
    не HTTP-ответ и не метрика: uniform-404 не ослабляется).

КЛАССЫ ОБЯЗАТЕЛЬНОСТИ (§14.1, AC11):
  - mandatory (fail-closed): publication/approval/выдача защищённых
    данных/grants -- невозможность зафиксировать запись = отказ ДО
    выполнения действия (MandatoryAuditFailure);
  - standard (durable, best-effort): отказы доступа и иные события --
    решение уже принято/действие уже безопасно; сбой записи виден
    счётчиком audit_write_failures_total и degraded в audit_status(),
    НО не меняет поведение (отказ доступа не превращается в пропуск).

НАДЁЖНОСТЬ (§14.1): durable sink (Postgres, миграция 0009) отдельно от
sampling техлогов; memory-приёмник -- dev/auto, переполнение НЕ молчаливое
(счётчик + degraded). Append-only по построению: в контуре не существует
операций изменения/удаления записей (срок хранения -- retention-политика
организации, §16.1 пилот 365 дней).

Граница задачи: чтение журнала/UI -- DOCLOG-7; поддержка/grants --
DOCLOG-6/7. Здесь -- поток записей, фабрики и интеграции identity/auth.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA_VERSION = "doclog.security_audit/1"

AUDIT_BACKEND_ENV = "CISSTAT_AUDIT_BACKEND"

MEMORY_SINK_MAX = 10000

# ── Каталог действий (§14.1 предмет аудита) ──────────────────────────

ACTION_AUTHN_DENIED = "authn_denied"
ACTION_AUTHZ_DENIED = "authz_denied"
ACTION_RUN_ACCESS_ALLOWED = "run_access_allowed"
ACTION_RUN_ACCESS_DENIED = "run_access_denied"
ACTION_GRANT_CREATED = "grant_created"
ACTION_GRANT_REVOKED = "grant_revoked"
ACTION_PROTECTED_DOCUMENT_VIEWED = "protected_document_viewed"
ACTION_DOWNLOAD_REQUESTED = "download_requested"
ACTION_RESPONSE_STREAM_STARTED = "response_stream_started"
ACTION_RESPONSE_STREAM_FINISHED = "response_stream_finished"
ACTION_DOCUMENT_APPROVED = "document_approved"
ACTION_DOCUMENT_PUBLISHED = "document_published"
ACTION_DOCUMENT_REVOKED = "document_revoked"
ACTION_TEMPLATE_CHANGED = "template_changed"
ACTION_RETENTION_POLICY_CHANGED = "retention_policy_changed"
ACTION_AUDIT_LOG_ACCESSED = "audit_log_accessed"
ACTION_CLEANUP_STARTED = "cleanup_started"
ACTION_RESTORE_STARTED = "restore_started"
ACTION_INTEGRITY_VERIFIED = "integrity_verified"
ACTION_INTEGRITY_FAILED = "integrity_failed"

AUDIT_ACTIONS: frozenset[str] = frozenset({
    ACTION_AUTHN_DENIED,
    ACTION_AUTHZ_DENIED,
    ACTION_RUN_ACCESS_ALLOWED,
    ACTION_RUN_ACCESS_DENIED,
    ACTION_GRANT_CREATED,
    ACTION_GRANT_REVOKED,
    ACTION_PROTECTED_DOCUMENT_VIEWED,
    ACTION_DOWNLOAD_REQUESTED,
    ACTION_RESPONSE_STREAM_STARTED,
    ACTION_RESPONSE_STREAM_FINISHED,
    ACTION_DOCUMENT_APPROVED,
    ACTION_DOCUMENT_PUBLISHED,
    ACTION_DOCUMENT_REVOKED,
    ACTION_TEMPLATE_CHANGED,
    ACTION_RETENTION_POLICY_CHANGED,
    ACTION_AUDIT_LOG_ACCESSED,
    ACTION_CLEANUP_STARTED,
    ACTION_RESTORE_STARTED,
    ACTION_INTEGRITY_VERIFIED,
    ACTION_INTEGRITY_FAILED,
})

# Классы обязательности: mandatory -- fail-closed (AC11: publication/
# approval/выдача защищённых данных), standard -- durable best-effort.
AUDIT_REQUIREMENTS: dict[str, str] = {
    ACTION_DOCUMENT_PUBLISHED: "mandatory",
    ACTION_DOCUMENT_APPROVED: "mandatory",
    ACTION_DOCUMENT_REVOKED: "mandatory",
    ACTION_PROTECTED_DOCUMENT_VIEWED: "mandatory",
    ACTION_DOWNLOAD_REQUESTED: "mandatory",
    ACTION_RESPONSE_STREAM_STARTED: "mandatory",
    ACTION_RESPONSE_STREAM_FINISHED: "mandatory",
    ACTION_GRANT_CREATED: "mandatory",
    ACTION_GRANT_REVOKED: "mandatory",
    ACTION_AUTHN_DENIED: "standard",
    ACTION_AUTHZ_DENIED: "standard",
    ACTION_RUN_ACCESS_ALLOWED: "standard",
    ACTION_RUN_ACCESS_DENIED: "standard",
    ACTION_TEMPLATE_CHANGED: "standard",
    ACTION_RETENTION_POLICY_CHANGED: "standard",
    ACTION_AUDIT_LOG_ACCESSED: "standard",
    ACTION_CLEANUP_STARTED: "standard",
    ACTION_RESTORE_STARTED: "standard",
    ACTION_INTEGRITY_VERIFIED: "standard",
    ACTION_INTEGRITY_FAILED: "standard",
}

# Допустимые решения (§14.1: разрешено/отказано/прервано).
DECISIONS: frozenset[str] = frozenset({"allowed", "denied", "aborted"})


class MandatoryAuditFailure(Exception):
    """AC11 fail-closed: обязательная audit-запись не зафиксирована --
    защищённое действие НЕ выполняется (отказ ДО раскрытия)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_details(details: Optional[dict[str, Any]]) -> dict[str, Any]:
    """details проходят тот же redaction (§14.1: без body документа и
    значения API-key); ключи не фильтруются allowlist'ом техлога --
    это серверный журнал, но ЗНАЧЕНИЯ всегда очищаются (R08)."""
    from apps.api.telemetry import _redact_structured

    if not details:
        return {}
    if not isinstance(details, dict):
        return {"value": _redact_structured(details)}
    cleaned: dict[str, Any] = {}
    for key, value in list(details.items())[:32]:
        cleaned[str(key)[:80]] = _redact_structured(value)
    return cleaned


def build_audit_record(
    action: str,
    decision: str,
    *,
    actor_subject: str = "",
    actor_via: str = "anonymous",
    tenant_id: Optional[str] = None,
    resource_kind: Optional[str] = None,
    resource_id: Optional[str] = None,
    resource_version: Optional[str] = None,
    policy_basis: str = "",
    request_id: Optional[str] = None,
    operation_id: Optional[str] = None,
    run_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    occurred_at: Optional[str] = None,
) -> dict[str, Any]:
    """Сборка записи по §14.1 (кто/когда/tenant/resource/version/
    действие/решение/основание/корреляция). Не бросает на данных:
    details/строки проходят redaction."""
    if action not in AUDIT_ACTIONS:
        raise ValueError(f"Неизвестное audit-действие: {action!r}")
    if decision not in DECISIONS:
        raise ValueError(f"Недопустимое решение: {decision!r}")
    from apps.api.telemetry import current_request_id, redact_text

    return {
        "schema_version": SCHEMA_VERSION,
        "audit_id": "aud-" + uuid.uuid4().hex,
        "occurred_at": occurred_at or _now_iso(),
        "actor_subject": redact_text(actor_subject or "", limit=80),
        "actor_via": redact_text(actor_via or "anonymous", limit=40),
        "tenant_id": redact_text(tenant_id or "", limit=80) or None,
        "action": action,
        "decision": decision,
        "resource_kind": redact_text(resource_kind or "", limit=60) or None,
        "resource_id": redact_text(resource_id or "", limit=120) or None,
        "resource_version": redact_text(resource_version or "", limit=80) or None,
        "policy_basis": redact_text(policy_basis or "", limit=160),
        "request_id": request_id or current_request_id() or None,
        "operation_id": operation_id,
        "run_id": redact_text(run_id or "", limit=40) or None,
        "details": _redact_details(details),
    }


# ── Sinks (durable отдельно от техлогов, §14.1) ──────────────────────


class AuditSink:
    """Приёмник audit-записей. append -> bool; изменение/удаление
    записей контрактом не существует (append-only §14.1)."""

    def append(self, record: dict[str, Any]) -> bool:  # pragma: no cover
        raise NotImplementedError

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError

    def readiness_probe(self) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError


class MemoryAuditSink(AuditSink):
    """Memory-приёмник (dev/тесты/auto). Переполнение -- НЕ молчаливое:
    append -> False, счётчик ведёт контур, degraded в статусе."""

    def __init__(self, maxsize: int = MEMORY_SINK_MAX) -> None:
        self._lock = threading.Lock()
        self._records: deque[dict[str, Any]] = deque(maxlen=maxsize)
        self._maxsize = maxsize

    def append(self, record: dict[str, Any]) -> bool:
        with self._lock:
            if len(self._records) >= self._maxsize:
                return False
            self._records.append(dict(record))
        return True

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            records = list(self._records)
        return [dict(record) for record in records[-limit:]]

    def readiness_probe(self) -> dict[str, Any]:
        return {"ok": True, "backend": "memory"}


class PostgresAuditSink(AuditSink):
    """Durable-приёмник (миграция 0009 на первом коннекте; ленивый
    psycopg -- паритет durable-контуров). Только INSERT: политика
    хранения/очистки -- retention-контур (§16.1), не этот модуль."""

    _INSERT_SQL = (
        "INSERT INTO security_audit_records (audit_id, schema_version,"
        " occurred_at, actor_subject, actor_via, tenant_id, action, decision,"
        " resource_kind, resource_id, resource_version, policy_basis,"
        " request_id, operation_id, run_id, details)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
        " %s, %s)"
        " ON CONFLICT (audit_id) DO NOTHING"
    )

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._schema_ready = False
        self._lock = threading.Lock()

    @staticmethod
    def from_env() -> "PostgresAuditSink":
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL env var is required for PostgresAuditSink."
            )
        return PostgresAuditSink(dsn=dsn)

    def _connect(self):
        import psycopg  # late import

        conn = psycopg.connect(self._dsn, autocommit=False)
        if not self._schema_ready:
            with self._lock:
                if not self._schema_ready:
                    from apps.api.research_runs import run_migrations

                    run_migrations(conn)
                    self._schema_ready = True
        return conn

    def append(self, record: dict[str, Any]) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._INSERT_SQL,
                (
                    record.get("audit_id"),
                    record.get("schema_version"),
                    record.get("occurred_at"),
                    record.get("actor_subject"),
                    record.get("actor_via"),
                    record.get("tenant_id"),
                    record.get("action"),
                    record.get("decision"),
                    record.get("resource_kind"),
                    record.get("resource_id"),
                    record.get("resource_version"),
                    record.get("policy_basis"),
                    record.get("request_id"),
                    record.get("operation_id"),
                    record.get("run_id"),
                    json.dumps(
                        record.get("details") or {},
                        ensure_ascii=False, default=str,
                    ),
                ),
            )
            conn.commit()
        return True

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        raise NotImplementedError(
            "Чтение durable-журнала -- контур DOCLOG-7 (admin logs UI); "
            "в этой поставке durable-записи через health не выдаются (T6)."
        )

    def readiness_probe(self) -> dict[str, Any]:
        import psycopg

        from apps.api.storage_diagnostics import safe_error

        try:
            with psycopg.connect(
                self._dsn, autocommit=True, connect_timeout=3
            ) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.execute(
                    "SELECT to_regclass('public.security_audit_records')"
                )
                if cur.fetchone()[0] is None:
                    return {
                        "ok": False,
                        "backend": "postgres",
                        "error": "миграция 0009 не применена",
                    }
            return {"ok": True, "backend": "postgres"}
        except Exception as exc:  # pragma: no cover -- средовой путь
            return {"ok": False, "backend": "postgres", "error": safe_error(exc)}


# ── Контур записи (record_standard / record_mandatory) ───────────────

_sink: Optional[AuditSink] = None
_sink_lock = threading.Lock()
_counters: dict[str, int] = {}
_counters_lock = threading.Lock()


def _inc(name: str, amount: int = 1) -> None:
    with _counters_lock:
        _counters[name] = _counters.get(name, 0) + amount


def _counters_snapshot() -> dict[str, int]:
    with _counters_lock:
        return dict(sorted(_counters.items()))


def _choose_sink() -> AuditSink:
    from apps.api.storage_diagnostics import (
        COMPONENT_AUDIT,
        get_storage_mode,
        record_backend_fallback,
        record_backend_selected,
        safe_error,
    )

    mode = get_storage_mode()
    backend_explicit = os.environ.get(AUDIT_BACKEND_ENV, "").lower()
    database_url = os.environ.get("DATABASE_URL", "")
    if backend_explicit == "memory":
        sink: AuditSink = MemoryAuditSink()
        record_backend_selected(COMPONENT_AUDIT, "memory", "memory")
        return sink
    if backend_explicit == "postgres" or database_url:
        record_backend_selected(COMPONENT_AUDIT, "postgres", "initializing")
        try:
            candidate: AuditSink = PostgresAuditSink.from_env()
            if mode == "required":
                probe = candidate.readiness_probe()
                if not probe.get("ok"):
                    raise RuntimeError(
                        "Postgres audit backend required, но недоступен: "
                        + str(probe.get("error") or "probe failed")
                    )
            record_backend_selected(COMPONENT_AUDIT, "postgres", "postgres")
            return candidate
        except Exception as exc:
            reason = safe_error(exc)
            if mode == "required":
                record_backend_selected(
                    COMPONENT_AUDIT, "postgres", "unavailable",
                    reason=reason, degraded=True,
                )
                raise RuntimeError(
                    "Postgres audit backend required, но инициализация "
                    f"не удалась (fail-closed, P21/F14): {reason}"
                ) from exc
            record_backend_fallback(
                COMPONENT_AUDIT, "postgres", reason, effective="memory"
            )
            return MemoryAuditSink()
    sink = MemoryAuditSink()
    record_backend_selected(COMPONENT_AUDIT, "auto", "memory")
    return sink


def get_audit_sink() -> AuditSink:
    global _sink
    with _sink_lock:
        if _sink is not None:
            return _sink
    chosen = _choose_sink()
    with _sink_lock:
        if _sink is None:
            _sink = chosen
        return _sink


def peek_audit_sink() -> Optional[AuditSink]:
    """Чтение singleton БЕЗ инициализации (паритет peek_* фабрик)."""
    with _sink_lock:
        return _sink


def set_audit_sink_for_testing(sink: Optional[AuditSink]) -> None:
    global _sink
    with _sink_lock:
        _sink = sink


def reset_audit_for_testing() -> None:
    global _sink
    with _sink_lock:
        _sink = None
    with _counters_lock:
        _counters.clear()


def audit_status() -> dict[str, Any]:
    """Facts-only статус (для /health/ops): backend/degraded/счётчики;
    содержимое записей НЕ выдаётся (T6)."""
    with _sink_lock:
        sink = _sink
    counters = _counters_snapshot()
    return {
        "backend": type(sink).__name__.replace("AuditSink", "").lower()
        if sink is not None
        else "not_initialized",
        "degraded": bool(
            counters.get("audit_write_failures_total")
            or counters.get("audit_dropped_total")
        ),
        "counters": counters,
    }


def audit_records() -> list[dict[str, Any]]:
    """Записи активного memory-приёмника (тесты/диагностика); для
    durable backend -- пусто (чтение журнала -- DOCLOG-7, T6)."""
    with _sink_lock:
        sink = _sink
    if isinstance(sink, MemoryAuditSink):
        return sink.list_recent(limit=MEMORY_SINK_MAX)
    return []


def _append_or_count(record: dict[str, Any]) -> bool:
    """Append с честным подсчётом сбоев (False/исключение -- счётчик)."""
    try:
        delivered = bool(get_audit_sink().append(record))
    except Exception:
        _inc("audit_write_failures_total")
        return False
    if not delivered:
        _inc("audit_dropped_total")
        return False
    return True


def record_mandatory(
    action: str,
    decision: str,
    *,
    actor_subject: str = "",
    actor_via: str = "anonymous",
    tenant_id: Optional[str] = None,
    resource_kind: Optional[str] = None,
    resource_id: Optional[str] = None,
    resource_version: Optional[str] = None,
    policy_basis: str = "",
    request_id: Optional[str] = None,
    operation_id: Optional[str] = None,
    run_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> str:
    """Обязательная audit-запись (AC11, fail-closed): невозможность
    зафиксировать запись -> MandatoryAuditFailure ДО выполнения
    защищённого действия. Вызывающий контур обязан прервать операцию."""
    record = build_audit_record(
        action, decision,
        actor_subject=actor_subject, actor_via=actor_via,
        tenant_id=tenant_id, resource_kind=resource_kind,
        resource_id=resource_id, resource_version=resource_version,
        policy_basis=policy_basis, request_id=request_id,
        operation_id=operation_id, run_id=run_id, details=details,
    )
    try:
        delivered = bool(get_audit_sink().append(record))
    except Exception as exc:
        _inc("audit_write_failures_total")
        raise MandatoryAuditFailure(
            "Обязательный security audit не зафиксирован; защищённое "
            f"действие {action} не выполняется (AC11 fail-closed). "
            f"Причина: {type(exc).__name__}"
        ) from None
    if not delivered:
        _inc("audit_dropped_total")
        raise MandatoryAuditFailure(
            "Обязательный security audit не зафиксирован (sink отказал); "
            f"защищённое действие {action} не выполняется (AC11 fail-closed)."
        )
    return str(record["audit_id"])


def record_standard(
    action: str,
    decision: str,
    *,
    actor_subject: str = "",
    actor_via: str = "anonymous",
    tenant_id: Optional[str] = None,
    resource_kind: Optional[str] = None,
    resource_id: Optional[str] = None,
    resource_version: Optional[str] = None,
    policy_basis: str = "",
    request_id: Optional[str] = None,
    operation_id: Optional[str] = None,
    run_id: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """Стандартная durable-запись: сбой приёмника НЕ меняет уже принятого
    решения (AC11-инвариант) и НЕ ломает поток -- сбой виден счётчиком
    и degraded в audit_status(). Никогда не бросает."""
    try:
        record = build_audit_record(
            action, decision,
            actor_subject=actor_subject, actor_via=actor_via,
            tenant_id=tenant_id, resource_kind=resource_kind,
            resource_id=resource_id, resource_version=resource_version,
            policy_basis=policy_basis, request_id=request_id,
            operation_id=operation_id, run_id=run_id, details=details,
        )
    except ValueError:
        # Некорректное действие/решение -- ошибка вызывающего кода:
        # фиксируется счётчиком, расчёт не роняется.
        _inc("audit_invalid_record_total")
        return None
    if _append_or_count(record):
        return str(record["audit_id"])
    return None


def record_run_access_decision(
    decision: Any,
    *,
    request_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> Optional[str]:
    """Интеграция решающей таблицы DOCLOG-0 с durable-потоком (замена
    logger-only контура из DOCLOG-0). AccessDecision -- серверный
    результат; в запись идут псевдонимы, причина и run_id (audit --
    не HTTP: uniform-404 не ослабляется)."""
    allowed = bool(getattr(decision, "allowed", False))
    action = ACTION_RUN_ACCESS_ALLOWED if allowed else ACTION_RUN_ACCESS_DENIED
    run_id = str(getattr(decision, "run_id", "") or "")
    return record_standard(
        action,
        "allowed" if allowed else "denied",
        actor_subject=str(getattr(decision, "requester_subject", "") or ""),
        actor_via=str(getattr(decision, "requester_via", "") or "anonymous"),
        tenant_id=tenant_id,
        resource_kind="run",
        resource_id=run_id or None,
        run_id=run_id or None,
        policy_basis="R09 object authorization",
        request_id=request_id,
        details={
            "reason_code": str(getattr(decision, "reason", "") or ""),
            "action": str(getattr(decision, "action", "") or ""),
        },
    )
