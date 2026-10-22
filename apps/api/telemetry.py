# apps/api/telemetry.py
"""
DOCLOG-3 (spec_documentation_logging.md §13, §19 строка DOCLOG-3, §19.1,
§20 AC10/AC11): technical telemetry foundation -- структурированное
техническое логирование, redaction/ошибочная корреляция, ops-счётчики.

КОНТРАКТ ЗАПИСИ (§13.1, схема ``doclog.telemetry/1``; OTel-модель [S3]):
schema_version, event_name, occurred_at/observed_at (время события vs
время наблюдения), severity_text/number (OTel numbers: TRACE=1,
DEBUG=5, INFO=9, WARN=13, ERROR=17, FATAL=21), message_template +
allowlist-attributes, service/version/environment/instance, request_id,
trace_id/span_id (W3C traceparent [S4] -- вход ПРОВЕРЯЕТСЯ, доверие к
внешнему caller не предполагается), operation_id/execution_id,
research_run_id/context_id (только серверные), outcome, method,
error_code/error_fingerprint, duration_ms, retry_attempt, subject
surrogate (псевдоним, НЕ материал ключа/cookie), tenant_id (из
аутентификации), sampled. Точная OTLP-передача -- адаптер (to_jsonl).

ЗАЩИТА СОДЕРЖИМОГО (R08, §13.3):
  1. ПЕРВЫЙ барьер -- allowlist структурированных атрибутов
     (ALLOWED_ATTRIBUTE_KEYS): неизвестный ключ отбрасывается целиком
     (счётчик telemetry_attr_dropped_total), SQL-literals/env-dump/
     DataFrame-строки физически не проходят;
  2. ВТОРОЙ барьер -- redact_text() на каждом строковом значении:
     URL/DSN целиком, Bearer/Basic, key=value-секреты (password/token/
     api-key/cookie/session...), URL-Encoded формы (unquote -> redact),
     многострочные (построчный прогон), CR/LF/control-символы
     нейтрализуются (anti log-injection), длина клипируется;
  3. Stack traces очищаются: только module/function/lineno, БЕЗ
     locals/аргументов/исходников; error_code, stack fingerprint
     (sha256), exception chain -- тот же фильтр (§13.3);
  4. Сбой самого redaction pipeline -- P0 (§13.4): событие заменяется
     минимальным безопасным telemetry.redaction_failed, сырой контент
     не появляется НИГДЕ (счётчик telemetry_redaction_failures_total).

УРОВНИ (§13.1 таблица): DEBUG -- выключен по умолчанию (env
CISSTAT_TELEMETRY_DEBUG); частые успешные read -- sampling
(sample_class="noisy_read", детерминированный, env
CISSTAT_TELEMETRY_SAMPLE_RATE, по умолчанию 1.0); WARN/ERROR/FATAL и
essential=True -- НЕ сэмплируются никогда; HTTP 422 -- ожидаемый
validation outcome (INFO), не ERROR.

ОТКАЗОУСТОЙЧИВОСТЬ (§13.2, AC11): недоступность collector НЕ ломает
успешный расчёт -- emit() никогда не бросает: сбой sink -> bounded
local spool (SPOOL_MAX) + счётчики telemetry_sink_failures_total /
telemetry_dropped_total (переполнение очереди видимо через dropped) +
degraded в telemetry_status(); исключение при dispatch -- дополнительно
bounded emergency fallback (EMERGENCY_MAX) + telemetry_emergency_total
(рекурсивный «ошибка записи лога» ограничен). flush_spool() -- повторная
доставка после восстановления.

МЕТРИКИ (§13.4): счётчики с НЕвысококардинальными метками (route
template/status class/method/outcome); run_id/tenant/user/SQL в
метрики НЕ попадают. Экспозиция -- facts-only в /health/ops
(build_telemetry_health в storage_diagnostics).

Граница задачи: HTTP-маршруты чтения журналов -- DOCLOG-7; UI --
DOCLOG-4; OTel SDK/exporter -- адаптер будущей поставки.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

# ── Контракт (§13.1) ─────────────────────────────────────────────────

SCHEMA_VERSION = "doclog.telemetry/1"

SERVICE_NAME = "cisstat-api"
SERVICE_VERSION = "1.0.0"

SEVERITY_NUMBERS: dict[str, int] = {
    "trace": 1,
    "debug": 5,
    "info": 9,
    "warn": 13,
    "warning": 13,
    "error": 17,
    "fatal": 21,
}
SEVERITY_TEXT: dict[int, str] = {
    1: "TRACE", 5: "DEBUG", 9: "INFO", 13: "WARN", 17: "ERROR", 21: "FATAL",
}

# R08 (первый барьер): allowlist ключей структурированных атрибутов.
ALLOWED_ATTRIBUTE_KEYS: frozenset[str] = frozenset({
    "route", "method", "status_class", "stage", "kind", "outcome",
    "reason_code", "service", "job_kind", "delivery_class",
    "checkpoint_label", "component", "backend", "mode", "count",
    "detail_kind", "adapter", "schema_version", "action",
})

# env-имена (политика §22: ADR, не молчаливые значения; дефолты -- честные)
DEBUG_ENV = "CISSTAT_TELEMETRY_DEBUG"
SAMPLE_RATE_ENV = "CISSTAT_TELEMETRY_SAMPLE_RATE"
TELEMETRY_BACKEND_ENV = "CISSTAT_TELEMETRY_BACKEND"

SPOOL_MAX = 500          # bounded local spool при недоступном collector
EMERGENCY_MAX = 20       # рекурсивный fallback ограничен (§13.2)
MEMORY_SINK_MAX = 2000   # memory-приёмник по умолчанию
MESSAGE_LIMIT = 300      # клип текстовых полей (anti-DoS §13.3)

EVENT_ATTR_LIMIT = 16    # максимум атрибутов на событие

# Пути, НЕ наблюдаемые request-контуром (liveness-шум §13.2).
_PATH_EXCLUDES: frozenset[str] = frozenset({"/health"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(value: str, limit: int = MESSAGE_LIMIT) -> str:
    if len(value) > limit:
        return value[: limit - 3] + "..."
    return value


# ── Redaction (R08, второй барьер; §13.3, AC10) ──────────────────────

# URL/DSN со схемой -- редактируются ЦЕЛИКОМ (включая signed URLs:
# учётные данные/подписи не должны оставаться частично).
_URL_RE = re.compile(
    r"\b(?:postgres(?:ql)?|redis|rediss|mysql|mongodb(?:\+srv)?|amqps?|"
    r"https?|wss?)://\S+",
    re.IGNORECASE,
)
# key=value-секреты: значение редактируется, ключ остаётся (OWASP S5).
_KV_SECRET_RE = re.compile(
    r"\b(password|passwd|pwd|token|secret|api[_-]?key|authorization|auth|"
    r"session[_-]?id|cookie|set[-_]cookie|credential[s]?|key)\s*[=:]\s*[^\s&;]+",
    re.IGNORECASE,
)
# Bearer/Basic-схемы аутентификации.
_BEARER_RE = re.compile(
    r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE
)

# Control-символы (log injection, §13.3): CR/LF -> экранированные формы,
# прочие C0/C1 -> \xNN (диагностируемо и безопасно).
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _neutralize_controls(text: str) -> str:
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    return _CONTROL_RE.sub(lambda m: f"\\x{ord(m.group(0)):02x}", text)


def redact_text(value: Any, limit: int = MESSAGE_LIMIT) -> str:
    """Единая точка очистки текста (второй барьер R08). Никогда не
    бросает; любой вход -> безопасная строка. URL-encoded секреты
    ловятся прогоном по percent-decoded копии (выход -- decoded,
    представление для логов эквивалентно)."""
    try:
        if value is None:
            return ""
        if isinstance(value, BaseException):
            text = str(value) or type(value).__name__
        else:
            text = str(value)
        # URL-encoded секреты (§13.3: юнит-тесты включают URL-encoded):
        from urllib.parse import unquote

        text = unquote(text)
        text = _URL_RE.sub("<redacted-url>", text)
        text = _BEARER_RE.sub("<redacted-credentials>", text)
        text = _KV_SECRET_RE.sub(lambda m: f"{m.group(1)}=<redacted>", text)
        text = _neutralize_controls(text)
        return _clip(text, limit)
    except Exception:  # pragma: no cover -- redactor не бросает
        return "<redaction-error>"


def _redact_structured(value: Any, depth: int = 0) -> Any:
    """Рекурсивная очистка значения allowlist-атрибута (dict/list/str)."""
    if depth > 4:
        return "<clipped>"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, bool) or value is None or isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {
            str(key): _redact_structured(item, depth + 1)
            for key, item in list(value.items())[:EVENT_ATTR_LIMIT]
        }
    if isinstance(value, (list, tuple)):
        return [_redact_structured(item, depth + 1) for item in list(value)[:EVENT_ATTR_LIMIT]]
    # Прочие типы (объекты домена) не сериализуем вслепую.
    return redact_text(str(value))


# ── Stack cleanup / error correlation (§13.3) ────────────────────────


def clean_exception(exc: BaseException, *, depth: int = 0) -> dict[str, Any]:
    """Очищенный stack (§13.3): БЕЗ locals/аргументов/сообщений/URL
    (raw exception.args не логируются -- сообщение исключения часто
    несёт чувствительные данные; сохраняются error_code (тип),
    module/function/lineno кадров, стабильный stack fingerprint и
    exception chain -- тот же фильтр)."""
    import traceback

    error_code = type(exc).__name__
    stack: list[dict[str, Any]] = []
    try:
        for frame in traceback.extract_tb(exc.__traceback__)[-12:]:
            stack.append({
                "module": os.path.basename(str(frame.filename)),
                "function": str(frame.name)[:80],
                "lineno": int(frame.lineno or 0),
            })
    except Exception:  # pragma: no cover -- защитный контур
        stack = []
    fingerprint_src = error_code + "|" + "|".join(
        f"{f['module']}:{f['function']}:{f['lineno']}" for f in stack
    )
    fingerprint = hashlib.sha256(fingerprint_src.encode("utf-8")).hexdigest()[:32]
    chain: list[dict[str, Any]] = [{"error_code": error_code}]
    if depth < 6:
        cause = exc.__cause__ or exc.__context__
        if cause is not None and cause is not exc:
            chain.extend(clean_exception(cause, depth=depth + 1)["chain"])
    return {
        "error_code": error_code,
        "stack": stack,
        "error_fingerprint": fingerprint,
        "chain": chain,
    }


# ── Корреляция запросов (W3C trace context [S4], §13.1) ─────────────

import contextvars

_TRACEPARENT_RE = re.compile(
    r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$"
)
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# request-контур: request_id текущего запроса (correlation identity ->
# audit -> response header без протаскивания параметра через слои).
_REQUEST_ID_VAR: "contextvars.ContextVar[str]" = contextvars.ContextVar(
    "cisstat_request_id", default=""
)


def current_request_id() -> str:
    """request_id текущего HTTP-запроса (контекст middleware); вне
    запроса -- пустая строка (correlation честно отсутствует)."""
    return _REQUEST_ID_VAR.get()


def parse_traceparent(value: str) -> Optional[tuple[str, str]]:
    """W3C traceparent [S4]: (trace_id, span_id) или None. Доверие к
    внешнему caller не предполагается: неверный формат/версия игнорируются."""
    if not isinstance(value, str):
        return None
    match = _TRACEPARENT_RE.match(value.strip())
    if match is None:
        return None
    version, trace_id, span_id, _flags = match.groups()
    if version == "ff" or trace_id == "0" * 32 or span_id == "0" * 16:
        return None
    return trace_id, span_id


def new_request_id() -> str:
    return "req-" + uuid.uuid4().hex[:12]


def accept_request_id(value: Any) -> Optional[str]:
    """Внешний request_id принимается ТОЛЬКО в безопасной форме
    ([A-Za-z0-9_-]{8,64}); инъекция/мусор -> None (сгенерируем свой)."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if _REQUEST_ID_RE.match(value):
        return value
    return None


# ── Sinks (§13.2: collector-модель; §14.1: отдельный durable audit) ──


class TelemetrySink:
    """Приёмник тех-событий. write возвращает bool доставки; сбой --
    исключение или False, но НЕ влияние на бизнес-поток (AC11)."""

    def write(self, record: dict[str, Any]) -> bool:  # pragma: no cover
        raise NotImplementedError

    def readiness_probe(self) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError


class MemoryTelemetrySink(TelemetrySink):
    """Bounded memory-приёмник (dev/тесты/auto). Переполнение --
    НЕ молчаливое: write -> False, счётчик dropped ведёт pipeline."""

    def __init__(self, maxsize: int = MEMORY_SINK_MAX) -> None:
        self._lock = threading.Lock()
        self._records: deque[dict[str, Any]] = deque(maxlen=maxsize)
        self._maxsize = maxsize

    def write(self, record: dict[str, Any]) -> bool:
        with self._lock:
            if len(self._records) >= self._maxsize:
                return False
            self._records.append(dict(record))
        return True

    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(record) for record in self._records]

    def readiness_probe(self) -> dict[str, Any]:
        return {"ok": True, "backend": "memory"}


class PostgresTelemetrySink(TelemetrySink):
    """Durable-приёмник тех-событий (retention-класс 30 дней, §16.1 --
    политика очистки вне этой задачи). Ленивый psycopg, миграция 0009
    на первом коннекте -- паритет durable-контуров DOCLOG-1/2."""

    _INSERT_SQL = (
        "INSERT INTO telemetry_events (event_id, schema_version, event_name,"
        " occurred_at, observed_at, severity_text, severity_number,"
        " message_template, attributes, service, service_version, environment,"
        " instance, request_id, trace_id, span_id, operation_id, execution_id,"
        " research_run_id, context_id, subject_surrogate, tenant_id, outcome,"
        " method, error_code, error_fingerprint, duration_ms, retry_attempt,"
        " sampled)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
        " %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (event_id) DO NOTHING"
    )

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._schema_ready = False
        self._lock = threading.Lock()

    @staticmethod
    def from_env() -> "PostgresTelemetrySink":
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL env var is required for PostgresTelemetrySink."
            )
        return PostgresTelemetrySink(dsn=dsn)

    def _connect(self):
        import psycopg  # late import -- паритет durable-контуров

        conn = psycopg.connect(self._dsn, autocommit=False)
        if not self._schema_ready:
            with self._lock:
                if not self._schema_ready:
                    from apps.api.research_runs import run_migrations

                    run_migrations(conn)
                    self._schema_ready = True
        return conn

    def write(self, record: dict[str, Any]) -> bool:
        attributes = record.get("attributes") or {}
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._INSERT_SQL,
                (
                    record.get("event_id"),
                    record.get("schema_version"),
                    record.get("event_name"),
                    record.get("occurred_at"),
                    record.get("observed_at"),
                    record.get("severity_text"),
                    record.get("severity_number"),
                    record.get("message_template"),
                    json.dumps(attributes, ensure_ascii=False, default=str),
                    record.get("service"),
                    record.get("service_version"),
                    record.get("environment"),
                    record.get("instance"),
                    record.get("request_id"),
                    record.get("trace_id"),
                    record.get("span_id"),
                    record.get("operation_id"),
                    record.get("execution_id"),
                    record.get("research_run_id"),
                    record.get("context_id"),
                    record.get("subject_surrogate"),
                    record.get("tenant_id"),
                    record.get("outcome"),
                    record.get("method"),
                    record.get("error_code"),
                    record.get("error_fingerprint"),
                    record.get("duration_ms"),
                    record.get("retry_attempt"),
                    bool(record.get("sampled")),
                ),
            )
            conn.commit()
        return True

    def readiness_probe(self) -> dict[str, Any]:
        import psycopg

        from apps.api.storage_diagnostics import safe_error

        try:
            with psycopg.connect(
                self._dsn, autocommit=True, connect_timeout=3
            ) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.execute("SELECT to_regclass('public.telemetry_events')")
                if cur.fetchone()[0] is None:
                    return {
                        "ok": False,
                        "backend": "postgres",
                        "error": "миграция 0009 не применена",
                    }
            return {"ok": True, "backend": "postgres"}
        except Exception as exc:  # pragma: no cover -- средовой путь
            return {"ok": False, "backend": "postgres", "error": safe_error(exc)}


# ── Pipeline: counters/spool/emergency (§13.2, AC11) ─────────────────


class _TelemetryPipeline:
    """Синглтон-конвейер: allowlist/redaction -> dispatch -> при сбое
    bounded spool + счётчики; исключение dispatch -> дополнительно
    bounded emergency fallback. Никогда не бросает наружу."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sink: Optional[TelemetrySink] = None
        self._spool: deque[dict[str, Any]] = deque(maxlen=SPOOL_MAX)
        self._emergency: deque[dict[str, Any]] = deque(maxlen=EMERGENCY_MAX)
        self._counters: dict[str, int] = {}

    # -- счётчики -------------------------------------------------------
    def inc(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def counters(self) -> dict[str, int]:
        with self._lock:
            return dict(sorted(self._counters.items()))

    # -- sink -----------------------------------------------------------
    def sink(self) -> TelemetrySink:
        with self._lock:
            if self._sink is not None:
                return self._sink
        chosen = _choose_sink()
        with self._lock:
            if self._sink is None:
                self._sink = chosen
            return self._sink

    def set_sink(self, sink: Optional[TelemetrySink]) -> None:
        """None -- возврат к env-выбору (spool/счётчики сохраняются:
        восстановление collector не теряет буфер)."""
        chosen = sink if sink is not None else _choose_sink()
        with self._lock:
            self._sink = chosen

    # -- dispatch (модульная функция -- патчится в тестах) --------------
    def dispatch(self, record: dict[str, Any]) -> bool:
        return _dispatch_to_sink(self.sink(), record)

    # -- fallback-контур ------------------------------------------------
    def on_sink_failure(self, record: dict[str, Any], *, raised: bool) -> None:
        # ВНИМАНИЕ: self._lock НЕ реентерабельный -- inc() под внешним
        # захватом вызывает взаимоблокировку; счётчики только ВНЕ блока.
        # Семантика: честный False от sink (переполнение memory-приёмника)
        # = запись ПОТЕРЯНА -> dropped (§13.2); исключение = collector
        # недоступен -> bounded spool (+ emergency при raised).
        self.inc("telemetry_sink_failures_total")
        if not raised:
            self.inc("telemetry_dropped_total")
            return
        with self._lock:
            spool_full = len(self._spool) >= (self._spool.maxlen or 0)
            if not spool_full:
                self._spool.append(dict(record))
        if spool_full:
            self.inc("telemetry_dropped_total")
        with self._lock:
            self._emergency.append({
                "schema_version": SCHEMA_VERSION,
                "event_name": "telemetry.emergency_fallback",
                "at": _now_iso(),
            })
        self.inc("telemetry_emergency_total")

    def flush_spool(self) -> int:
        """Повторная доставка после восстановления collector. Возвращает
        число доставленных записей; недоставленные остаются в spool."""
        flushed = 0
        with self._lock:
            pending = list(self._spool)
        remaining: list[dict[str, Any]] = []
        for record in pending:
            try:
                ok = _dispatch_to_sink(self.sink(), record)
            except Exception:
                ok = False
            if ok:
                flushed += 1
            else:
                remaining.append(record)
        if remaining:
            with self._lock:
                self._spool.clear()
                self._spool.extend(remaining)
        else:
            with self._lock:
                self._spool.clear()
        return flushed

    # -- статус ---------------------------------------------------------
    def status(self) -> dict[str, Any]:
        with self._lock:
            spool_size = len(self._spool)
            emergency_size = len(self._emergency)
            counters = dict(sorted(self._counters.items()))
            sink = self._sink
        counters_map = counters
        degraded = bool(
            counters_map.get("telemetry_sink_failures_total")
            or counters_map.get("telemetry_dropped_total")
            or counters_map.get("telemetry_emergency_total")
            or counters_map.get("telemetry_redaction_failures_total")
        )
        return {
            "backend": type(sink).__name__.replace("TelemetrySink", "").lower()
            if sink is not None
            else "not_initialized",
            "degraded": degraded,
            "spool_size": spool_size,
            "emergency_size": emergency_size,
            "counters": counters_map,
            "config": {
                "debug_enabled": _debug_enabled(),
                "sample_rate": _sample_rate(),
            },
        }

    def reset(self) -> None:
        with self._lock:
            self._sink = None
            self._spool.clear()
            self._emergency.clear()
            self._counters.clear()


def _debug_enabled() -> bool:
    return (os.environ.get(DEBUG_ENV) or "").strip() not in ("", "0", "false")


def _sample_rate() -> float:
    raw = (os.environ.get(SAMPLE_RATE_ENV) or "").strip()
    if not raw:
        return 1.0
    try:
        value = float(raw)
    except ValueError:
        return 1.0
    return min(max(value, 0.0), 1.0)


def _choose_sink() -> TelemetrySink:
    """Выбор backend (паритет snapshot-фабрики): explicit memory ->
    Memory; postgres/DATABASE_URL -> Postgres; иначе Memory (auto).
    Required-режим -- fail-closed (тихий Memory fallback запрещён)."""
    from apps.api.storage_diagnostics import (
        COMPONENT_TELEMETRY,
        get_storage_mode,
        record_backend_fallback,
        record_backend_selected,
        safe_error,
    )

    mode = get_storage_mode()
    backend_explicit = os.environ.get(TELEMETRY_BACKEND_ENV, "").lower()
    database_url = os.environ.get("DATABASE_URL", "")
    if backend_explicit == "memory":
        sink: TelemetrySink = MemoryTelemetrySink()
        record_backend_selected(COMPONENT_TELEMETRY, "memory", "memory")
        return sink
    if backend_explicit == "postgres" or database_url:
        record_backend_selected(COMPONENT_TELEMETRY, "postgres", "initializing")
        try:
            candidate: TelemetrySink = PostgresTelemetrySink.from_env()
            if mode == "required":
                probe = candidate.readiness_probe()
                if not probe.get("ok"):
                    raise RuntimeError(
                        "Postgres telemetry backend required, но недоступен: "
                        + str(probe.get("error") or "probe failed")
                    )
            record_backend_selected(COMPONENT_TELEMETRY, "postgres", "postgres")
            return candidate
        except Exception as exc:
            reason = safe_error(exc)
            if mode == "required":
                record_backend_selected(
                    COMPONENT_TELEMETRY, "postgres", "unavailable",
                    reason=reason, degraded=True,
                )
                raise RuntimeError(
                    "Postgres telemetry backend required, но инициализация "
                    f"не удалась (fail-closed, P21/F14): {reason}"
                ) from exc
            record_backend_fallback(
                COMPONENT_TELEMETRY, "postgres", reason, effective="memory"
            )
            return MemoryTelemetrySink()
    sink = MemoryTelemetrySink()
    record_backend_selected(COMPONENT_TELEMETRY, "auto", "memory")
    return sink


_pipeline = _TelemetryPipeline()


def _dispatch_to_sink(sink: TelemetrySink, record: dict[str, Any]) -> bool:
    """Точка dispatch (модульная -- патчится fault-injection тестами).
    Исключение пробрасывается: решение spool/emergency принимает
    pipeline (единый контур AC11)."""
    return bool(sink.write(record))


# ── Публичный API эмиттера ───────────────────────────────────────────


def get_telemetry_sink() -> TelemetrySink:
    return _pipeline.sink()


def peek_telemetry_sink() -> Optional[TelemetrySink]:
    """Чтение singleton БЕЗ инициализации (паритет peek_* фабрик)."""
    with _pipeline._lock:
        return _pipeline._sink


def set_telemetry_sink_for_testing(sink: Optional[TelemetrySink]) -> None:
    _pipeline.set_sink(sink)


def reset_telemetry_for_testing() -> None:
    _pipeline.reset()


def telemetry_status() -> dict[str, Any]:
    return _pipeline.status()


def flush_spool() -> int:
    return _pipeline.flush_spool()


def memory_records() -> list[dict[str, Any]]:
    """Записи активного memory-приёмника (тесты/диагностика); для
    не-memory backend -- пусто (содержимое durable-приёмника через
    health НЕ выдаётся, T6)."""
    with _pipeline._lock:
        sink = _pipeline._sink
    if isinstance(sink, MemoryTelemetrySink):
        return sink.records()
    return []


def to_jsonl(record: dict[str, Any]) -> str:
    """JSONL-адаптер (§13.1: платформенный адаптер/OTLP -- за границей
    задачи). Штатный encoder, allow_nan=False, одна запись = строка."""
    try:
        return json.dumps(
            record, ensure_ascii=False, sort_keys=True, allow_nan=False, default=str
        )
    except (TypeError, ValueError):
        return json.dumps(
            {"schema_version": SCHEMA_VERSION,
             "event_name": record.get("event_name", "unknown"),
             "serialize_error": True},
            ensure_ascii=False, sort_keys=True,
        )


def emit(
    event_name: str,
    severity: str = "info",
    *,
    message_template: Optional[str] = None,
    attributes: Optional[dict[str, Any]] = None,
    outcome: Optional[str] = None,
    error: Optional[BaseException] = None,
    error_code: Optional[str] = None,
    request_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    span_id: Optional[str] = None,
    traceparent: Optional[str] = None,
    operation_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    research_run_id: Optional[str] = None,
    context_id: Optional[str] = None,
    duration_ms: Optional[float] = None,
    retry_attempt: Optional[int] = None,
    subject_material: Optional[str] = None,
    tenant_id: Optional[str] = None,
    method: Optional[str] = None,
    sample_class: Optional[str] = None,
    essential: bool = False,
    occurred_at: Optional[str] = None,
) -> bool:
    """Единая точка тех-событий (§13.1). НИКОГДА не бросает; возврат --
    факт доставки. Атрибуты -- ТОЛЬКО allowlist (R08); значения проходят
    redaction; сбой redaction -- P0-подмена минимальным событием.
    traceparent (W3C [S4]) проверяется: невалидный -- игнорируется."""
    if traceparent and (trace_id is None or span_id is None):
        parsed = parse_traceparent(traceparent)
        if parsed is not None:
            trace_id = trace_id or parsed[0]
            span_id = span_id or parsed[1]
    try:
        return _emit_impl(
            event_name, severity,
            message_template=message_template, attributes=attributes,
            outcome=outcome, error=error, error_code=error_code,
            request_id=request_id, trace_id=trace_id, span_id=span_id,
            operation_id=operation_id, execution_id=execution_id,
            research_run_id=research_run_id, context_id=context_id,
            duration_ms=duration_ms, retry_attempt=retry_attempt,
            subject_material=subject_material, tenant_id=tenant_id,
            method=method, sample_class=sample_class, essential=essential,
            occurred_at=occurred_at,
        )
    except Exception:
        # Последний контур: даже сбой сборки события не роняет расчёт.
        _pipeline.inc("telemetry_emergency_total")
        with _pipeline._lock:
            _pipeline._emergency.append({
                "schema_version": SCHEMA_VERSION,
                "event_name": "telemetry.emit_failure",
                "target": redact_text(str(event_name))[:80],
                "at": _now_iso(),
            })
        return False


def _emit_impl(
    event_name: str,
    severity: str,
    *,
    message_template: Optional[str],
    attributes: Optional[dict[str, Any]],
    outcome: Optional[str],
    error: Optional[BaseException],
    error_code: Optional[str],
    request_id: Optional[str],
    trace_id: Optional[str],
    span_id: Optional[str],
    operation_id: Optional[str],
    execution_id: Optional[str],
    research_run_id: Optional[str],
    context_id: Optional[str],
    duration_ms: Optional[float],
    retry_attempt: Optional[int],
    subject_material: Optional[str],
    tenant_id: Optional[str],
    method: Optional[str],
    sample_class: Optional[str],
    essential: bool,
    occurred_at: Optional[str],
) -> bool:
    try:
        return _build_and_dispatch(
            event_name, severity,
            message_template=message_template, attributes=attributes,
            outcome=outcome, error=error, error_code=error_code,
            request_id=request_id, trace_id=trace_id, span_id=span_id,
            operation_id=operation_id, execution_id=execution_id,
            research_run_id=research_run_id, context_id=context_id,
            duration_ms=duration_ms, retry_attempt=retry_attempt,
            subject_material=subject_material, tenant_id=tenant_id,
            method=method, sample_class=sample_class, essential=essential,
            occurred_at=occurred_at,
        )
    except Exception:
        # Сбой сборки (redaction pipeline P0, §13.4): минимальное
        # безопасное событие, сырой контент не появляется нигде.
        _pipeline.inc("telemetry_redaction_failures_total")
        fallback = {
            "schema_version": SCHEMA_VERSION,
            "event_id": "evt-" + uuid.uuid4().hex,
            "event_name": "telemetry.redaction_failed",
            "occurred_at": _now_iso(),
            "observed_at": _now_iso(),
            "severity_text": "ERROR",
            "severity_number": 17,
            "message_template": None,
            "attributes": {},
            "service": SERVICE_NAME,
            "request_id": request_id or current_request_id() or None,
            "outcome": outcome,
        }
        return _dispatch_with_fallback(fallback)


def _build_and_dispatch(event_name: Any, severity: Any, **kwargs: Any) -> bool:
    event_name = str(event_name or "unknown")
    severity_raw = str(severity or "info").lower()
    severity_number = SEVERITY_NUMBERS.get(severity_raw)
    if severity_number is None:
        # Неизвестный уровень -- fail-safe к INFO (событие не теряется).
        _pipeline.inc("telemetry_invalid_severity_total")
        severity_number = SEVERITY_NUMBERS["info"]
    severity_text = SEVERITY_TEXT[severity_number]

    # DEBUG-гейтинг (§13.1: production off по умолчанию).
    if severity_number <= SEVERITY_NUMBERS["debug"] and not _debug_enabled():
        _pipeline.inc("telemetry_debug_suppressed_total")
        return False

    # Sampling (§13.1/§13.2): только шумные успешные read; WARN+ и
    # essential не сэмплируются никогда.
    if (
        kwargs.get("sample_class") == "noisy_read"
        and not kwargs.get("essential")
        and severity_number < SEVERITY_NUMBERS["warn"]
    ):
        rate = _sample_rate()
        draw_source = f"{event_name}|{kwargs.get('request_id') or ''}"
        draw = int(
            hashlib.sha256(draw_source.encode("utf-8")).hexdigest()[:8], 16
        ) / float(0xFFFFFFFF)
        if draw >= rate:
            _pipeline.inc("telemetry_sampled_out_total")
            return False

    occurred_at = kwargs.get("occurred_at") or _now_iso()
    observed_at = _now_iso()
    effective_request_id = (
        kwargs.get("request_id") or current_request_id() or None
    )

    error = kwargs.get("error")
    cleaned_error: Optional[dict[str, Any]] = None
    if error is not None:
        cleaned_error = clean_exception(error)

    message = None
    if kwargs.get("message_template") is not None:
        message = redact_text(str(kwargs["message_template"]))
    # Сообщения исключений НЕ логируются (§13.3: raw exception.args не
    # проходят; сохраняются error_code/fingerprint/кадры).

    attributes: dict[str, Any] = {}
    raw_attributes = kwargs.get("attributes") or {}
    if isinstance(raw_attributes, dict):
        dropped = 0
        for key, value in list(raw_attributes.items())[:EVENT_ATTR_LIMIT]:
            if str(key) in ALLOWED_ATTRIBUTE_KEYS:
                attributes[str(key)] = _redact_structured(value)
            else:
                dropped += 1
        dropped += max(0, len(raw_attributes) - EVENT_ATTR_LIMIT)
        if dropped:
            _pipeline.inc("telemetry_attr_dropped_total", dropped)

    duration = kwargs.get("duration_ms")
    if duration is not None and not math.isfinite(float(duration)):
        duration = None

    subject_surrogate = None
    if kwargs.get("subject_material"):
        from apps.api.identity import subject_pseudonym

        subject_surrogate = subject_pseudonym(str(kwargs["subject_material"]))

    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "event_id": "evt-" + uuid.uuid4().hex,
        "event_name": str(event_name)[:120],
        "occurred_at": occurred_at,
        "observed_at": observed_at,
        "severity_text": severity_text,
        "severity_number": severity_number,
        "message_template": message,
        "attributes": attributes,
        "service": SERVICE_NAME,
        "service_version": SERVICE_VERSION,
        "environment": (os.environ.get("CISSTAT_ENVIRONMENT") or "production"),
        "instance": (os.environ.get("CISSTAT_INSTANCE") or "api"),
        "request_id": effective_request_id,
        "trace_id": kwargs.get("trace_id"),
        "span_id": kwargs.get("span_id"),
        "operation_id": kwargs.get("operation_id"),
        "execution_id": kwargs.get("execution_id"),
        "research_run_id": kwargs.get("research_run_id"),
        "context_id": kwargs.get("context_id"),
        "subject_surrogate": subject_surrogate,
        "tenant_id": kwargs.get("tenant_id"),
        "outcome": kwargs.get("outcome"),
        "method": kwargs.get("method"),
        "error_code": (
            kwargs.get("error_code")
            or (cleaned_error["error_code"] if cleaned_error else None)
        ),
        "error_fingerprint": (
            cleaned_error["error_fingerprint"] if cleaned_error else None
        ),
        "duration_ms": duration,
        "retry_attempt": kwargs.get("retry_attempt"),
        "sampled": False,
    }
    return _dispatch_with_fallback(record)


def _dispatch_with_fallback(record: dict[str, Any]) -> bool:
    """Dispatch + fail-open fallback (AC11): сбой sink (исключение ИЛИ
    честный False -- переполнение memory-приёмника) -- spool + счётчики,
    решение о бизнес-операции не меняется."""
    try:
        delivered = _pipeline.dispatch(record)
    except Exception:
        _pipeline.on_sink_failure(record, raised=True)
        return False
    if not delivered:
        _pipeline.on_sink_failure(record, raised=False)
        return False
    return True


# ── Request-контур (§13.2: API ingress; §19.1 точка изменения) ───────

_STATUS_CLASS_UNKNOWN = "0xx"


class TelemetryContextMiddleware:
    """Чистый ASGI (паритет TraceHookMiddleware): request-корреляция и
    наблюдаемость ingress.

    - request_id: валидный внешний принимается (accept_request_id),
      иначе генерируется свой; ВСЕГДА возвращается клиенту заголовком
      ``X-Request-ID`` (§13.1: request_id выдаётся и в безопасном HTTP
      error response для обращения в поддержку);
    - traceparent проверяется (parse_traceparent) -- доверие к внешнему
      caller не предполагается;
    - request_id публикуется через ContextVar: identity/auth/audit
      коррелируют durable-записи с ответом без протаскивания параметров;
    - api.request: route template (не высокая кардинальность §13.4),
      status_class, outcome, duration_ms; успешные GET -- noisy_read
      sampling, ошибки 5xx/исключения -- ERROR с clean_exception;
    - OPTIONS и liveness (/health) не наблюдаются; тело запроса не
      читается вовсе (§13.3: raw bodies не логируются).
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = str(scope.get("method") or "GET").upper()
        path = str(scope.get("path") or "")
        # §13.1: request_id в КАЖДОМ ответе (корреляция поддержки) --
        # включая /health/OPTIONS; событие api.request -- только для
        # наблюдаемых путей (liveness-шум не emitted, §13.2).
        observed = method != "OPTIONS" and path not in _PATH_EXCLUDES

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in (scope.get("headers") or [])
        }
        request_id = (
            accept_request_id(headers.get("x-request-id")) or new_request_id()
        )
        trace_ctx = parse_traceparent(headers.get("traceparent") or "")
        trace_id = trace_ctx[0] if trace_ctx else None
        span_id = trace_ctx[1] if trace_ctx else None
        token = _REQUEST_ID_VAR.set(request_id)

        start = time.perf_counter()
        status_holder: dict[str, int] = {}

        async def send_wrapper(message: Any) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = int(message.get("status") or 0)
                message_headers = list(message.get("headers") or [])
                message_headers.append(
                    (b"x-request-id", request_id.encode("latin-1"))
                )
                message = {**message, "headers": message_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            if observed:
                self._emit_request_event(
                    scope=scope, method=method, status=None,
                    duration_ms=(time.perf_counter() - start) * 1000.0,
                    request_id=request_id, trace_id=trace_id, span_id=span_id,
                    error=exc,
                )
            _REQUEST_ID_VAR.reset(token)
            raise
        _REQUEST_ID_VAR.reset(token)
        if observed:
            self._emit_request_event(
                scope=scope, method=method,
                status=status_holder.get("status") or 0,
                duration_ms=(time.perf_counter() - start) * 1000.0,
                request_id=request_id, trace_id=trace_id, span_id=span_id,
                error=None,
            )

    def _emit_request_event(
        self,
        *,
        scope: Any,
        method: str,
        status: Optional[int],
        duration_ms: float,
        request_id: str,
        trace_id: Optional[str],
        span_id: Optional[str],
        error: Optional[BaseException],
    ) -> None:
        try:
            # Route template ставит роутер в scope ПОСЛЕ матчинга; сам
            # path с ID в метки не идёт (низкая кардинальность §13.4).
            route_template = getattr(scope.get("route"), "path", None)
            route_label = str(route_template) if route_template else "unmatched"
            status_class = (
                f"{status // 100}xx" if status and status >= 100
                else _STATUS_CLASS_UNKNOWN
            )
            if error is not None or (status or 0) >= 500:
                severity = "error"
                outcome = "server_error"
            elif (status or 0) >= 400:
                # 4xx -- ожидаемые validation/auth outcome (422 не ERROR).
                severity = "info"
                outcome = "client_error"
            else:
                severity = "info"
                outcome = "success"
            emit(
                "api.request",
                severity=severity,
                outcome=outcome,
                error=error,
                request_id=request_id,
                trace_id=trace_id,
                span_id=span_id,
                duration_ms=round(duration_ms, 2),
                method=method,
                # успешные GET -- единственный сэмплируемый класс
                sample_class=(
                    "noisy_read"
                    if method == "GET" and outcome == "success"
                    else None
                ),
                attributes={
                    "route": route_label,
                    "status_class": status_class,
                    "method": method,
                },
            )
        except Exception:  # pragma: no cover -- наблюдаемость не роняет
            pass