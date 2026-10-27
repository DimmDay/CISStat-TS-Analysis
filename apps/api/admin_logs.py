# apps/api/admin_logs.py
"""
DOCLOG-7 (spec_documentation_logging.md §14.2, §15, §19 строка
DOCLOG-7): журналы и поддержка -- чтение durable-журналов, support
grants, диагностический пакет.

Критерий завершения (§19): «нет данных/секретов вне grant, все
действия учитываются».

СОСТАВ:
  * Чтение журналов по WHITELIST-фильтрам (§14.2: «Без произвольного
    SQL/регулярных выражений от браузера к backend; whitelist фильтров
    и лимиты запроса»): telemetry (migration 0009), audit (0009),
    delivery/documents (0010+0011). Cursor pagination (keyset по
    (occurred_at, id) DESC), временной cutoff (окно <= 31 день),
    лимиты, честный retention horizon (§16.1: telemetry 30 дней,
    audit 365 дней).
  * Support grants (§14.2/§15): ticket/purpose обязательны,
    ограничение по tenant/run/времени (TTL <= 168 часов), scopes из
    WHITELIST {logs.read, audit.read, logs.export} -- выдача
    data/publish-прав через support-grant запрещена («Разрешён пакет
    „без данных"»). Создание/отзыв -- mandatory audit fail-closed
    (§14.1 «создание/изменение прав и support grants»; AC11).
  * Диагностический пакет (§14.2): redacted JSONL + manifest; версии
    сервисов и ops status; НИКОГДА env values/DSN/API-key/cookies/
    строки данных (AC10/AC19). ZIP детерминирован (урок DOCLOG-5).
  * Саможурналирование (§14.2): просмотр/экспорт журнала пишется
    в audit (audit_log_accessed, standard) -- каждая операция РОВНО
    одна запись, без бесконечной рекурсии.
  * Авторизация (§15.1): ADMIN-проверка сохраняется (роли); scopes
    реестра ключей и support grants сужают область. Запрос с явным
    фильтром ВНЕ grant -- отказ (данных вне grant нет); запрос без
    фильтра -- честное сужение с раскрытием effective_scope в meta.

Бекенды чтения -- паритет durable-контуров (ленивый psycopg,
run_migrations на первом коннекте): memory-адаптеры поверх
telemetry.memory_records()/security_audit.audit_records() и
DocumentRegistry.list_delivery_summary(); Postgres-адаптеры -- SQL c
whitelist-колонками и keyset-пагинацией.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import threading
import uuid
import zipfile
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

# ── Константы (§14.2, §16.1) ─────────────────────────────────────────

GRANTS_BACKEND_ENV = "CISSTAT_GRANTS_BACKEND"

WINDOW_MAX_DAYS = 31          # временной cutoff для стабильной выборки
QUERY_LIMIT_DEFAULT = 50
QUERY_LIMIT_MAX = 200         # лимит страницы (§14.2 «лимиты запроса»)
EXPORT_LIMIT = 2000           # лимит строк потока в пакете
BUNDLE_DATE_TIME = (2020, 1, 1, 0, 0, 0)  # детерминизм ZIP (DOCLOG-5)
BUNDLE_SCHEMA = "doclog.diagbundle/1"
BUNDLE_PREFIX = "diagb-"

TELEMETRY_RETENTION_DAYS = 30  # §16.1
AUDIT_RETENTION_DAYS = 365     # §16.1

GRANT_SCOPES: frozenset[str] = frozenset(
    {"logs.read", "audit.read", "logs.export"}
)
GRANT_TTL_MAX_HOURS = 168      # <= 7 дней
GRANT_SCHEMA_VERSION = "doclog.support_grant/1"

STREAM_TELEMETRY = "telemetry"
STREAM_AUDIT = "audit"
STREAM_DELIVERY = "delivery"
ALL_STREAMS: frozenset[str] = frozenset(
    {STREAM_TELEMETRY, STREAM_AUDIT, STREAM_DELIVERY}
)

# Исключённые из пакета категории (§14.2/AC10/AC19) -- фиксируются
# в manifest, чтобы получатель видел честную границу.
BUNDLE_EXCLUDED = (
    "содержимое датасетов и payload документов",
    "cookies, session identifiers и заголовки браузера",
    "значения переменных окружения (env values) и DSN",
    "значения API-ключей и учётные данные",
    "сырые файловые пути вне redacted-атрибутов",
)


# ── Исключения ────────────────────────────────────────────────────────


class GrantValidationError(ValueError):
    """Некорректный запрос гранта (422)."""


class LogsValidationError(ValueError):
    """Некорректные параметры запроса журнала (422)."""


class LogsAccessDenied(RuntimeError):
    """Отказ в доступе к журналу/операции (403, §15)."""


class LogsBackendError(RuntimeError):
    """Durable-слой журналов недоступен (503)."""


class GrantNotFoundError(LookupError):
    """Грант не найден (uniform 404)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


# ── Записи грантов ────────────────────────────────────────────────────


@dataclass(frozen=True)
class SupportGrantRecord:
    grant_id: str
    ticket: str
    purpose: str
    subject_id: str
    tenant_id: str
    scopes: tuple[str, ...]
    created_by: str
    created_at: str
    expires_at: str
    run_id: Optional[str] = None
    revoked_at: Optional[str] = None
    revoked_by: Optional[str] = None
    revoke_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "schema_version": GRANT_SCHEMA_VERSION,
            "ticket": self.ticket,
            "purpose": self.purpose,
            "subject_id": self.subject_id,
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "scopes": list(self.scopes),
            "created_by": self.created_by,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "revoked_at": self.revoked_at,
            "revoked_by": self.revoked_by,
            "revoke_reason": self.revoke_reason,
        }


def replace_grant_record(record: SupportGrantRecord, **changes: Any) -> SupportGrantRecord:
    """Иммутабельная замена (без алиасинга полей; урок DOCLOG-0)."""
    return replace(record, **changes)


def _parse_grant_scopes(raw: Any) -> tuple[str, ...]:
    scopes: tuple[str, ...]
    if isinstance(raw, str):
        scopes = tuple(s for s in raw.split("+") if s)
    elif isinstance(raw, (list, tuple)):
        scopes = tuple(str(s) for s in raw)
    else:
        scopes = ()
    return scopes


def _row_to_grant(row: Any) -> SupportGrantRecord:
    keys = (
        "grant_id", "ticket", "purpose", "subject_id", "tenant_id",
        "run_id", "scopes", "created_by", "created_at", "expires_at",
        "revoked_at", "revoked_by", "revoke_reason",
    )
    data = dict(zip(keys, row))
    return SupportGrantRecord(
        grant_id=data["grant_id"],
        ticket=data["ticket"],
        purpose=data["purpose"] or "",
        subject_id=data["subject_id"],
        tenant_id=data["tenant_id"],
        run_id=data["run_id"],
        scopes=_parse_grant_scopes(data["scopes"]),
        created_by=data["created_by"],
        created_at=_iso_or_raw(data["created_at"]),
        expires_at=_iso_or_raw(data["expires_at"]),
        revoked_at=_iso_or_raw(data["revoked_at"]),
        revoked_by=data["revoked_by"],
        revoke_reason=data["revoke_reason"] or "",
    )


def _iso_or_raw(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


# ── Реестр грантов (ABC + Memory + Postgres, структурный паритет) ────


class SupportGrantRegistry:
    """Хранилище support grants (append + revoke-замена)."""

    def create_grant(self, record: SupportGrantRecord) -> SupportGrantRecord:  # pragma: no cover
        raise NotImplementedError

    def get_grant(self, grant_id: str) -> Optional[SupportGrantRecord]:  # pragma: no cover
        raise NotImplementedError

    def list_grants(
        self,
        subject_id: Optional[str] = None,
        include_revoked: bool = False,
        limit: int = 200,
    ) -> list[SupportGrantRecord]:  # pragma: no cover
        raise NotImplementedError

    def update_grant(self, record: SupportGrantRecord) -> SupportGrantRecord:  # pragma: no cover
        raise NotImplementedError


class MemorySupportGrantRegistry(SupportGrantRegistry):
    def __init__(self, maxsize: int = 10000) -> None:
        self._lock = threading.RLock()
        self._grants: dict[str, SupportGrantRecord] = {}
        self._maxsize = maxsize

    def create_grant(self, record: SupportGrantRecord) -> SupportGrantRecord:
        with self._lock:
            if len(self._grants) >= self._maxsize:
                raise LogsBackendError("реестр грантов переполнен")
            self._grants[record.grant_id] = record
            return record

    def get_grant(self, grant_id: str) -> Optional[SupportGrantRecord]:
        with self._lock:
            record = self._grants.get(grant_id)
            return record

    def list_grants(
        self,
        subject_id: Optional[str] = None,
        include_revoked: bool = False,
        limit: int = 200,
    ) -> list[SupportGrantRecord]:
        with self._lock:
            records = list(self._grants.values())
        if subject_id is not None:
            records = [r for r in records if r.subject_id == subject_id]
        if not include_revoked:
            records = [r for r in records if r.revoked_at is None]
        records.sort(key=lambda r: (r.created_at, r.grant_id), reverse=True)
        return [replace_grant_record(r) for r in records[: max(0, limit)]]

    def update_grant(self, record: SupportGrantRecord) -> SupportGrantRecord:
        with self._lock:
            if record.grant_id not in self._grants:
                raise GrantNotFoundError(record.grant_id)
            self._grants[record.grant_id] = record
            return record


class PostgresSupportGrantRegistry(SupportGrantRegistry):
    """Durable-реестр (миграция 0013 на первом коннекте; ленивый
    psycopg -- паритет durable-контуров DOCLOG-1/2/4/6)."""

    _INSERT_SQL = (
        "INSERT INTO support_grants (grant_id, schema_version, ticket,"
        " purpose, subject_id, tenant_id, run_id, scopes, created_by,"
        " created_at, expires_at, revoked_at, revoked_by, revoke_reason)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
        " ON CONFLICT (grant_id) DO NOTHING"
    )

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._schema_ready = False
        self._lock = threading.Lock()

    @staticmethod
    def from_env() -> "PostgresSupportGrantRegistry":
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            raise RuntimeError(
                "DATABASE_URL env var is required for"
                " PostgresSupportGrantRegistry."
            )
        return PostgresSupportGrantRegistry(dsn=dsn)

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

    def create_grant(self, record: SupportGrantRecord) -> SupportGrantRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._INSERT_SQL,
                (
                    record.grant_id,
                    GRANT_SCHEMA_VERSION,
                    record.ticket,
                    record.purpose,
                    record.subject_id,
                    record.tenant_id,
                    record.run_id,
                    "+".join(record.scopes),
                    record.created_by,
                    record.created_at,
                    record.expires_at,
                    record.revoked_at,
                    record.revoked_by,
                    record.revoke_reason,
                ),
            )
            conn.commit()
        return record

    def get_grant(self, grant_id: str) -> Optional[SupportGrantRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT grant_id, ticket, purpose, subject_id, tenant_id,"
                " run_id, scopes, created_by, created_at, expires_at,"
                " revoked_at, revoked_by, revoke_reason"
                " FROM support_grants WHERE grant_id = %s",
                (grant_id,),
            )
            row = cur.fetchone()
        return _row_to_grant(row) if row is not None else None

    def list_grants(
        self,
        subject_id: Optional[str] = None,
        include_revoked: bool = False,
        limit: int = 200,
    ) -> list[SupportGrantRecord]:
        sql = (
            "SELECT grant_id, ticket, purpose, subject_id, tenant_id,"
            " run_id, scopes, created_by, created_at, expires_at,"
            " revoked_at, revoked_by, revoke_reason FROM support_grants"
        )
        clauses: list[str] = []
        params: list[Any] = []
        if subject_id is not None:
            clauses.append("subject_id = %s")
            params.append(subject_id)
        if not include_revoked:
            clauses.append("revoked_at IS NULL")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC, grant_id DESC LIMIT %s"
        params.append(max(0, int(limit)))
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [_row_to_grant(row) for row in rows]

    def update_grant(self, record: SupportGrantRecord) -> SupportGrantRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE support_grants SET revoked_at = %s, revoked_by = %s,"
                " revoke_reason = %s WHERE grant_id = %s",
                (
                    record.revoked_at,
                    record.revoked_by,
                    record.revoke_reason,
                    record.grant_id,
                ),
            )
            if cur.rowcount == 0:
                conn.rollback()
                raise GrantNotFoundError(record.grant_id)
            conn.commit()
        return record


_registry: Optional[SupportGrantRegistry] = None
_registry_lock = threading.Lock()


def _choose_grant_registry() -> SupportGrantRegistry:
    backend = (os.environ.get(GRANTS_BACKEND_ENV) or "memory").strip().lower()
    if backend == "postgres":
        return PostgresSupportGrantRegistry.from_env()
    if backend in ("", "memory"):
        return MemorySupportGrantRegistry()
    raise RuntimeError(f"Неизвестный CISSTAT_GRANTS_BACKEND: {backend!r}")


def get_support_grant_registry() -> SupportGrantRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = _choose_grant_registry()
        return _registry


def peek_support_grant_registry() -> Optional[SupportGrantRegistry]:
    with _registry_lock:
        return _registry


def reset_support_grant_registry_for_testing() -> None:
    global _registry
    with _registry_lock:
        _registry = None


# ── Сервис грантов (валидация + mandatory audit, §14.1/AC11) ─────────


class SupportGrantService:
    def __init__(self, registry: Optional[SupportGrantRegistry] = None) -> None:
        self.registry = registry or get_support_grant_registry()

    # ── валидация (fail-closed) ──
    @staticmethod
    def _validate(
        ticket: str,
        subject_id: str,
        tenant_id: str,
        scopes: tuple[str, ...],
        ttl_hours: float,
        run_id: Optional[str],
    ) -> None:
        from apps.api.identity import is_valid_subject_id, is_valid_tenant_id

        if not isinstance(ticket, str) or not ticket.strip():
            raise GrantValidationError("ticket обязателен (§14.2)")
        if not subject_id or not is_valid_subject_id(subject_id):
            raise GrantValidationError("subject_id получателя обязателен")
        if not tenant_id or not is_valid_tenant_id(tenant_id):
            raise GrantValidationError("tenant_id границы гранта обязателен")
        if run_id is not None and not isinstance(run_id, str):
            raise GrantValidationError("run_id должен быть строкой или null")
        unknown = [s for s in scopes if s not in GRANT_SCOPES]
        if unknown:
            raise GrantValidationError(
                "scopes вне whitelist support-grant: "
                + ", ".join(sorted(unknown))
            )
        if not scopes:
            raise GrantValidationError("нужен хотя бы один scope")
        try:
            ttl = float(ttl_hours)
        except (TypeError, ValueError):
            raise GrantValidationError("ttl_hours должен быть числом")
        if ttl <= 0 or ttl > GRANT_TTL_MAX_HOURS:
            raise GrantValidationError(
                f"ttl_hours вне диапазона (0, {GRANT_TTL_MAX_HOURS}]"
            )

    def create_grant(
        self,
        *,
        ticket: str,
        purpose: str,
        subject_id: str,
        tenant_id: str,
        scopes: tuple[str, ...],
        ttl_hours: float,
        created_by: str,
        run_id: Optional[str] = None,
    ) -> SupportGrantRecord:
        self._validate(ticket, subject_id, tenant_id, tuple(scopes), ttl_hours, run_id)
        now = datetime.now(timezone.utc)
        record = SupportGrantRecord(
            grant_id=_new_id("d7grant"),
            ticket=ticket.strip(),
            purpose=(purpose or "").strip(),
            subject_id=subject_id,
            tenant_id=tenant_id,
            run_id=run_id or None,
            scopes=tuple(dict.fromkeys(scopes)),
            created_by=created_by,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(hours=float(ttl_hours))).isoformat(),
        )
        # Mandatory audit ПЕРВЫМ шагом (AC11 fail-closed): невозможность
        # зафиксировать создание прав -- отказ ДО создания.
        from apps.api.security_audit import record_mandatory

        record_mandatory(
            "grant_created",
            "allowed",
            actor_subject=created_by,
            actor_via="api_key",
            tenant_id=tenant_id,
            resource_kind="support_grant",
            resource_id=record.grant_id,
            policy_basis=f"ticket:{record.ticket}",
            run_id=run_id,
            details={
                "grantee_subject": subject_id,
                "scopes": list(record.scopes),
                "ttl_hours": float(ttl_hours),
                "purpose": record.purpose,
            },
        )
        return self.registry.create_grant(record)

    def revoke_grant(
        self, grant_id: str, *, revoked_by: str, reason: str = ""
    ) -> SupportGrantRecord:
        record = self.registry.get_grant(grant_id)
        if record is None:
            raise GrantNotFoundError(grant_id)
        if record.revoked_at is not None:
            return record  # идемпотентный повторный отзыв
        revoked = replace_grant_record(
            record,
            revoked_at=_now_iso(),
            revoked_by=revoked_by,
            revoke_reason=(reason or "").strip(),
        )
        from apps.api.security_audit import record_mandatory

        record_mandatory(
            "grant_revoked",
            "allowed",
            actor_subject=revoked_by,
            actor_via="api_key",
            tenant_id=record.tenant_id,
            resource_kind="support_grant",
            resource_id=record.grant_id,
            policy_basis=f"ticket:{record.ticket}",
            run_id=record.run_id,
            details={"grantee_subject": record.subject_id},
        )
        return self.registry.update_grant(revoked)

    def list_grants(
        self, *, include_revoked: bool = False
    ) -> list[SupportGrantRecord]:
        return self.registry.list_grants(include_revoked=include_revoked)


# ── Эффективный доступ (§15: ADMIN + scopes + grants) ────────────────


@dataclass(frozen=True)
class EffectiveLogAccess:
    telemetry: bool
    audit: bool
    delivery: bool
    export: bool
    grants_management: bool
    tenants: frozenset[str] = frozenset()  # пусто = unrestricted (admin)
    runs: frozenset[str] = frozenset()

    @property
    def unrestricted(self) -> bool:
        return not self.tenants and not self.runs

    def scope_meta(self) -> Any:
        if self.unrestricted:
            return "unrestricted"
        return {
            "tenants": sorted(self.tenants),
            "runs": sorted(self.runs),
        }


def resolve_effective_log_access(
    principal: Any,
    registry: Optional[SupportGrantRegistry] = None,
) -> EffectiveLogAccess:
    """ADMIN (§15.1 «сохраняют текущую ADMIN-проверку») -- полный
    каталог. Иначе -- scopes принципала + активные (не отозванные,
    не истёкшие) support grants его субъекта; область -- пересечение
    границ грантов (tenant/run)."""
    from apps.api.plans import Role

    role_value = getattr(getattr(principal, "role", None), "value", None) or getattr(
        principal, "role", None
    )
    is_admin = role_value == Role.ADMIN or role_value == "admin"
    scopes = set(getattr(principal, "scopes", None) or ())
    subject_id = getattr(principal, "subject_id", None) or ""
    if is_admin:
        return EffectiveLogAccess(
            telemetry=True,
            audit=True,
            delivery=True,
            export=True,
            grants_management=True,
        )
    grants: list[SupportGrantRecord] = []
    if subject_id:
        store = registry or get_support_grant_registry()
        grants = [
            g for g in store.list_grants(subject_id=subject_id)
            if not _is_expired(g)
        ]
    tenants: set[str] = set()
    runs: set[str] = set()
    grant_scopes: set[str] = set()
    for grant in grants:
        grant_scopes.update(grant.scopes)
        tenants.add(grant.tenant_id)
        if grant.run_id:
            runs.add(grant.run_id)
    effective = scopes | grant_scopes
    return EffectiveLogAccess(
        telemetry="logs.read" in effective,
        audit="audit.read" in effective,
        delivery="logs.read" in effective,
        export="logs.export" in effective,
        grants_management="support.grant" in effective,
        tenants=frozenset(tenants),
        runs=frozenset(runs),
    )


def _is_expired(grant: SupportGrantRecord, now: Optional[datetime] = None) -> bool:
    moment = now or datetime.now(timezone.utc)
    expires = _parse_iso(grant.expires_at)
    if expires is None:
        return True  # невалидная дата -- fail-closed
    return expires <= moment


def _parse_iso(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


# ── Запрос журнала: валидация + cursor (§14.2) ───────────────────────


@dataclass(frozen=True)
class LogQuery:
    stream: str
    from_ts: datetime
    to_ts: datetime
    limit: int
    cursor: Optional[dict[str, Any]] = None
    filters: dict[str, Any] = field(default_factory=dict)


def parse_query(
    stream: str,
    *,
    from_raw: Any,
    to_raw: Any,
    limit_raw: Any,
    cursor_raw: Any,
    filters: Optional[dict[str, Any]] = None,
) -> LogQuery:
    if stream not in ALL_STREAMS:
        raise LogsValidationError(f"неизвестный поток: {stream!r}")
    to_ts = _parse_iso(to_raw) if to_raw else datetime.now(timezone.utc)
    if to_raw and to_ts is None:
        raise LogsValidationError("некорректная дата to (ISO 8601)")
    from_ts = (
        _parse_iso(from_raw)
        if from_raw
        else to_ts - timedelta(hours=24)
    )
    if from_raw and from_ts is None:
        raise LogsValidationError("некорректная дата from (ISO 8601)")
    if from_ts is None or to_ts is None or from_ts >= to_ts:
        raise LogsValidationError("окно пустое: from должен быть меньше to")
    if to_ts - from_ts > timedelta(days=WINDOW_MAX_DAYS):
        raise LogsValidationError(
            f"окно больше {WINDOW_MAX_DAYS} дней (временной cutoff §14.2)"
        )
    limit = QUERY_LIMIT_DEFAULT if limit_raw is None else _to_int(limit_raw)
    if limit < 1 or limit > QUERY_LIMIT_MAX:
        raise LogsValidationError(
            f"limit вне диапазона 1..{QUERY_LIMIT_MAX}"
        )
    cursor = None
    if cursor_raw:
        cursor = _decode_cursor(cursor_raw)
    clean_filters: dict[str, Any] = {}
    for key, value in (filters or {}).items():
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise LogsValidationError(f"фильтр {key} должен быть строкой")
        clean_filters[key] = value
    return LogQuery(
        stream=stream,
        from_ts=from_ts,
        to_ts=to_ts,
        limit=limit,
        cursor=cursor,
        filters=clean_filters,
    )


def _to_int(raw: Any) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise LogsValidationError("limit должен быть целым числом")


def _encode_cursor(key: tuple[str, str]) -> str:
    payload = json.dumps({"t": key[0], "id": key[1]}, ensure_ascii=False)
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_cursor(raw: str) -> dict[str, Any]:
    try:
        payload = base64.urlsafe_b64decode(raw.encode("ascii"))
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict) or "t" not in data or "id" not in data:
            raise ValueError
        return data
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise LogsValidationError("некорректный cursor")


def _validate_filters(stream: str, filters: dict[str, Any]) -> dict[str, Any]:
    """Whitelist фильтров (§14.2). Значения -- точные строки."""
    whitelist = {
        STREAM_TELEMETRY: {
            "severity", "outcome", "event_name", "request_id",
            "run_id", "tenant_id",
        },
        STREAM_AUDIT: {
            "action", "decision", "actor_subject", "request_id",
            "run_id", "tenant_id",
        },
        STREAM_DELIVERY: {"state", "format", "run_id", "tenant_id"},
    }[stream]
    unknown = set(filters) - whitelist
    if unknown:
        raise LogsValidationError(
            "фильтры вне whitelist: " + ", ".join(sorted(unknown))
        )
    return filters


def _retention_meta(stream: str, from_ts: datetime) -> dict[str, Any]:
    horizon = {
        STREAM_TELEMETRY: TELEMETRY_RETENTION_DAYS,
        STREAM_AUDIT: AUDIT_RETENTION_DAYS,
        STREAM_DELIVERY: None,
    }[stream]
    meta: dict[str, Any] = {"retention_horizon_days": horizon}
    if horizon is not None:
        edge = datetime.now(timezone.utc) - timedelta(days=horizon)
        if from_ts < edge:
            meta["retention_note"] = (
                "запрошенный период старше retention horizon; "
                "данные могут отсутствовать (§16.1)"
            )
    return meta


# ── Чтение telemetry (memory + postgres) ─────────────────────────────


_TELEMETRY_COLUMNS = (
    "event_id", "event_name", "occurred_at", "severity_text",
    "message_template", "service", "service_version", "request_id",
    "trace_id", "operation_id", "research_run_id", "tenant_id",
    "outcome", "error_code", "duration_ms", "retry_attempt",
)


def _check_explicit_scope(query: LogQuery, access: EffectiveLogAccess) -> None:
    """Явный фильтр ВНЕ границы гранта -- отказ (403), не пустой список:
    «нет данных вне grant» (§19); непрозрачное сужение маскировало бы
    ошибку границы."""
    if access.unrestricted:
        return
    tenant = query.filters.get("tenant_id")
    if tenant is not None and access.tenants and tenant not in access.tenants:
        raise LogsAccessDenied("tenant_id вне границы support grant")
    run = query.filters.get("run_id")
    if run is not None and access.runs and run not in access.runs:
        raise LogsAccessDenied("run_id вне границы support grant")


def query_telemetry(query: LogQuery, access: EffectiveLogAccess) -> dict[str, Any]:
    if not access.telemetry:
        raise LogsAccessDenied("logs.read отсутствует")
    filters = _validate_filters(STREAM_TELEMETRY, query.filters)
    _check_explicit_scope(query, access)
    backend = (os.environ.get("CISSTAT_TELEMETRY_BACKEND") or "memory").lower()
    if backend == "postgres":
        records, next_cursor = _pg_query_telemetry(query, access, filters)
    else:
        records, next_cursor = _memory_query_telemetry(query, access, filters)
    return _wrap_response(STREAM_TELEMETRY, records, next_cursor, query, access)


def _memory_query_telemetry(
    query: LogQuery, access: EffectiveLogAccess, filters: dict[str, Any]
) -> tuple[list[dict[str, Any]], Optional[str]]:
    from apps.api.telemetry import memory_records

    rows = []
    for record in memory_records():
        occurred = _parse_iso(record.get("occurred_at"))
        if occurred is None or not (query.from_ts <= occurred < query.to_ts):
            continue
        if not _match_filters(record, filters, ("severity", "severity_text")):
            continue
        if not _match_filters(record, filters, ("outcome",)):
            continue
        if not _match_filters(record, filters, ("event_name",)):
            continue
        if not _match_filters(record, filters, ("request_id",)):
            continue
        if not _narrow(record, access, run_key="research_run_id"):
            continue
        rows.append(record)
    rows.sort(key=lambda r: (str(r.get("occurred_at")), str(r.get("event_id"))), reverse=True)
    return _apply_cursor(rows, query, key_fields=("occurred_at", "event_id"))


def _pg_query_telemetry(
    query: LogQuery, access: EffectiveLogAccess, filters: dict[str, Any]
) -> tuple[list[dict[str, Any]], Optional[str]]:
    clauses, params = _pg_window("occurred_at", query)
    _pg_field_filters(clauses, params, filters, {
        "severity": "severity_text",
        "outcome": "outcome",
        "event_name": "event_name",
        "request_id": "request_id",
        "run_id": "research_run_id",
        "tenant_id": "tenant_id",
    })
    _pg_narrow(clauses, params, access, run_col="research_run_id")
    if query.cursor:
        clauses.append("(occurred_at, event_id) < (%s, %s)")
        params.extend([query.cursor["t"], query.cursor["id"]])
    sql = (
        f"SELECT {', '.join(_TELEMETRY_COLUMNS)} FROM telemetry_events"
        + (" WHERE " + " AND ".join(clauses) if clauses else "")
        + " ORDER BY occurred_at DESC, event_id DESC LIMIT %s"
    )
    params.append(query.limit + 1)
    rows = _pg_fetch_all(sql, tuple(params))
    return _pg_page(rows, query, key_fields=("occurred_at", "event_id"))


# ── Чтение audit (memory + postgres) ─────────────────────────────────


_AUDIT_COLUMNS = (
    "audit_id", "occurred_at", "actor_subject", "actor_via", "tenant_id",
    "action", "decision", "resource_kind", "resource_id",
    "resource_version", "policy_basis", "request_id", "run_id",
    # H29-UIH (DOCLOG-H29-UIHONEST-AUDITVIEW, 2026-10-27): details в
    # чтении -- admin-вью audit-причин (reason_code по run). reason_code
    # живёт в details (record_run_access_decision), колонка есть в
    # миграции 0009; содержимое уже redacted на записи (_redact_details,
    # §14.1) и отдаётся только в границе audit.read/ADMIN + grants.
    "details",
)


def query_audit(query: LogQuery, access: EffectiveLogAccess) -> dict[str, Any]:
    if not access.audit:
        raise LogsAccessDenied("audit.read отсутствует")
    filters = _validate_filters(STREAM_AUDIT, query.filters)
    _check_explicit_scope(query, access)
    backend = (os.environ.get("CISSTAT_AUDIT_BACKEND") or "memory").lower()
    if backend == "postgres":
        records, next_cursor = _pg_query_audit(query, access, filters)
    else:
        records, next_cursor = _memory_query_audit(query, access, filters)
    return _wrap_response(STREAM_AUDIT, records, next_cursor, query, access)


def _memory_query_audit(
    query: LogQuery, access: EffectiveLogAccess, filters: dict[str, Any]
) -> tuple[list[dict[str, Any]], Optional[str]]:
    from apps.api.security_audit import audit_records

    rows = []
    for record in audit_records():
        occurred = _parse_iso(record.get("occurred_at"))
        if occurred is None or not (query.from_ts <= occurred < query.to_ts):
            continue
        if not _match_filters(record, filters, ("action",)):
            continue
        if not _match_filters(record, filters, ("decision",)):
            continue
        if not _match_filters(record, filters, ("actor_subject",)):
            continue
        if not _match_filters(record, filters, ("request_id",)):
            continue
        # H29-UIH (2026-10-27): whitelist-фильтры run_id/tenant_id
        # применяются и в memory (паритет _pg_query_audit, который их
        # уже применял) -- «причины отказов по run» работают в обоих
        # бекендах; прежнее молчаливое игнорирование -- разрыв контракта
        # whitelist (фильтр объявлен, но не применён).
        if not _match_filters(record, filters, ("run_id",)):
            continue
        if not _match_filters(record, filters, ("tenant_id",)):
            continue
        if not _narrow(record, access, run_key="run_id"):
            continue
        rows.append(record)
    rows.sort(key=lambda r: (str(r.get("occurred_at")), str(r.get("audit_id"))), reverse=True)
    return _apply_cursor(rows, query, key_fields=("occurred_at", "audit_id"))


def _pg_query_audit(
    query: LogQuery, access: EffectiveLogAccess, filters: dict[str, Any]
) -> tuple[list[dict[str, Any]], Optional[str]]:
    clauses, params = _pg_window("occurred_at", query)
    _pg_field_filters(clauses, params, filters, {
        "action": "action",
        "decision": "decision",
        "actor_subject": "actor_subject",
        "request_id": "request_id",
        "run_id": "run_id",
        "tenant_id": "tenant_id",
    })
    _pg_narrow(clauses, params, access, run_col="run_id")
    if query.cursor:
        clauses.append("(occurred_at, audit_id) < (%s, %s)")
        params.extend([query.cursor["t"], query.cursor["id"]])
    sql = (
        f"SELECT {', '.join(_AUDIT_COLUMNS)} FROM security_audit_records"
        + (" WHERE " + " AND ".join(clauses) if clauses else "")
        + " ORDER BY occurred_at DESC, audit_id DESC LIMIT %s"
    )
    params.append(query.limit + 1)
    rows = _pg_fetch_all(sql, tuple(params))
    # H29-UIH (2026-10-27): psycopg возвращает JSONB строкой -- приводим
    # к dict (паритет memory-пути, где details уже dict); битое значение
    # не отдаётся (честный None, не мусор).
    rows = [_pg_audit_details(row) for row in rows]
    return _pg_page(rows, query, key_fields=("occurred_at", "audit_id"))


def _pg_audit_details(row: dict[str, Any]) -> dict[str, Any]:
    details = row.get("details")
    if isinstance(details, str):
        try:
            row["details"] = json.loads(details)
        except ValueError:
            row["details"] = None
    return row


# ── Чтение delivery/documents (реестр документов) ────────────────────

_DELIVERY_KEYS = (
    "job_id", "run_id", "tenant_id", "snapshot_id", "format",
    "redaction_profile", "state", "error_code", "attempt",
    "created_at", "updated_at", "revision_id", "rendition_id",
    "document_id", "kind_code",
)


def query_delivery(query: LogQuery, access: EffectiveLogAccess) -> dict[str, Any]:
    if not access.delivery:
        raise LogsAccessDenied("logs.read отсутствует")
    filters = _validate_filters(STREAM_DELIVERY, query.filters)
    _check_explicit_scope(query, access)
    from apps.api.document_jobs import get_document_registry

    registry = get_document_registry()
    rows = registry.list_delivery_summary(
        from_ts=query.from_ts.isoformat(),
        to_ts=query.to_ts.isoformat(),
        state=filters.get("state"),
        format_filter=filters.get("format"),
        run_id=filters.get("run_id"),
        tenant_id=filters.get("tenant_id"),
    )
    # Сужение по гранту (registry-фильтры могли отсутствовать).
    narrowed = [
        r for r in rows
        if _narrow_delivery(r, access)
        and (access.unrestricted or _delivery_in_scope(r, access))
    ]
    narrowed.sort(key=lambda r: (str(r.get("created_at")), str(r.get("job_id"))), reverse=True)
    records, next_cursor = _apply_cursor(
        narrowed, query, key_fields=("created_at", "job_id")
    )
    return _wrap_response(STREAM_DELIVERY, records, next_cursor, query, access)


def _delivery_in_scope(row: dict[str, Any], access: EffectiveLogAccess) -> bool:
    if access.tenants and row.get("tenant_id") not in access.tenants:
        return False
    if access.runs and row.get("run_id") not in access.runs:
        return False
    return True


def _narrow_delivery(row: dict[str, Any], access: EffectiveLogAccess) -> bool:
    # Для unrestricted не применяется; для скоупа -- та же логика.
    return _delivery_in_scope(row, access)


# ── Общие хелперы фильтрации ─────────────────────────────────────────


def _match_filters(
    record: dict[str, Any], filters: dict[str, Any], keys: tuple[str, ...]
) -> bool:
    """filters использует каноническое имя; keys -- варианты полей
    записи (severity->severity_text и т.п.)."""
    canonical = keys[0]
    value = filters.get(canonical)
    if value is None:
        return True
    for key in keys:
        if str(record.get(key, "")) == value:
            return True
    return False


def _narrow(
    record: dict[str, Any], access: EffectiveLogAccess, *, run_key: str
) -> bool:
    """Сужение по границе гранта (§19: «нет данных вне grant»):
    unrestricted -- без изменений; иначе запись должна попадать в
    границу tenants/runs (пустой tenant записи в скоуп-режиме
    не отдаётся -- fail-closed)."""
    if access.unrestricted:
        return True
    tenant = record.get("tenant_id")
    if access.tenants and tenant not in access.tenants:
        return False
    if access.tenants and not tenant:
        return False
    run = record.get(run_key)
    if access.runs and run not in access.runs:
        return False
    return True


def _apply_cursor(
    rows: list[dict[str, Any]],
    query: LogQuery,
    *,
    key_fields: tuple[str, str],
) -> tuple[list[dict[str, Any]], Optional[str]]:
    if query.cursor:
        cursor_t = str(query.cursor.get("t", ""))
        cursor_id = str(query.cursor.get("id", ""))
        rows = [
            r for r in rows
            if (str(r.get(key_fields[0], "")), str(r.get(key_fields[1], "")))
            < (cursor_t, cursor_id)
        ]
    page = rows[: query.limit]
    next_cursor = None
    if len(rows) > query.limit and page:
        last = page[-1]
        next_cursor = _encode_cursor(
            (str(last.get(key_fields[0], "")), str(last.get(key_fields[1], "")))
        )
    return page, next_cursor


def _wrap_response(
    stream: str,
    records: list[dict[str, Any]],
    next_cursor: Optional[str],
    query: LogQuery,
    access: EffectiveLogAccess,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "stream": stream,
        "count": len(records),
        "limit": query.limit,
        "window": {"from": query.from_ts.isoformat(), "to": query.to_ts.isoformat()},
        "order": "occurred_at DESC, id DESC",
        "effective_scope": access.scope_meta(),
    }
    meta.update(_retention_meta(stream, query.from_ts))
    return {"records": records, "next_cursor": next_cursor, "meta": meta}


# ── Postgres-хелперы (ленивый psycopg, паритет durable-контуров) ─────


_pg_schema_ready = False
_pg_schema_lock = threading.Lock()


def _pg_connect():
    import psycopg

    global _pg_schema_ready
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise LogsBackendError("DATABASE_URL не настроен (postgres backend)")
    conn = psycopg.connect(dsn, autocommit=False)
    if not _pg_schema_ready:
        with _pg_schema_lock:
            if not _pg_schema_ready:
                from apps.api.research_runs import run_migrations

                run_migrations(conn)
                _pg_schema_ready = True
    return conn


def _pg_fetch_all(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    try:
        with _pg_connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            columns = [d.name for d in cur.description]
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]
            conn.rollback()  # read-only контур
        return [_iso_dates(r) for r in rows]
    except LogsBackendError:
        raise
    except Exception as exc:
        raise LogsBackendError(f"durable-слой журналов недоступен: {exc}")


def _iso_dates(record: dict[str, Any]) -> dict[str, Any]:
    for key, value in list(record.items()):
        if isinstance(value, datetime):
            record[key] = value.isoformat()
    return record


def _pg_window(column: str, query: LogQuery) -> tuple[list[str], list[Any]]:
    return (
        [f"{column} >= %s", f"{column} < %s"],
        [query.from_ts, query.to_ts],
    )


def _pg_field_filters(
    clauses: list[str],
    params: list[Any],
    filters: dict[str, Any],
    mapping: dict[str, str],
) -> None:
    for name, column in mapping.items():
        if name in filters:
            clauses.append(f"{column} = %s")
            params.append(filters[name])


def _pg_narrow(
    clauses: list[str],
    params: list[Any],
    access: EffectiveLogAccess,
    *,
    run_col: str,
) -> None:
    if access.unrestricted:
        return
    if access.tenants:
        placeholders = ", ".join(["%s"] * len(access.tenants))
        clauses.append(f"tenant_id IN ({placeholders})")
        params.extend(sorted(access.tenants))
    if access.runs:
        placeholders = ", ".join(["%s"] * len(access.runs))
        clauses.append(f"{run_col} IN ({placeholders})")
        params.extend(sorted(access.runs))


def _pg_page(
    rows: list[dict[str, Any]],
    query: LogQuery,
    *,
    key_fields: tuple[str, str],
) -> tuple[list[dict[str, Any]], Optional[str]]:
    page = rows[: query.limit]
    next_cursor = None
    if len(rows) > query.limit and page:
        last = page[-1]
        next_cursor = _encode_cursor(
            (str(last.get(key_fields[0], "")), str(last.get(key_fields[1], "")))
        )
    return page, next_cursor


# ── Диагностический пакет (§14.2, AC10/AC19) ─────────────────────────


def build_diagnostic_bundle(
    query: LogQuery,
    access: EffectiveLogAccess,
    *,
    streams: Optional[tuple[str, ...]] = None,
) -> tuple[bytes, str, str]:
    """ZIP: manifest.json + <stream>.jsonl. Данные -- только
    redacted-записи журналов; env/DSN/API-key/cookies/данные НЕ
    включаются (AC10/AC19). Возврат: (zip_bytes, bundle_id, filename)."""
    import io

    requested = tuple(streams) if streams else tuple(sorted(ALL_STREAMS))
    unknown = set(requested) - ALL_STREAMS
    if unknown:
        raise LogsValidationError(
            "потоки вне каталога: " + ", ".join(sorted(unknown))
        )
    if not access.export:
        raise LogsAccessDenied("logs.export отсутствует")

    from apps.api.telemetry import SERVICE_NAME, SERVICE_VERSION, to_jsonl

    members: list[tuple[str, bytes]] = []
    counts: dict[str, int] = {}
    for stream in requested:
        stream_query = replace(query, limit=EXPORT_LIMIT, cursor=None)
        if stream == STREAM_TELEMETRY:
            payload = query_telemetry(stream_query, access)
        elif stream == STREAM_AUDIT:
            payload = query_audit(stream_query, access)
        else:
            payload = query_delivery(stream_query, access)
        lines = "".join(
            to_jsonl(record) for record in payload["records"]
        ).encode("utf-8")
        counts[f"{stream}.jsonl"] = len(payload["records"])
        members.append((f"{stream}.jsonl", lines))

    manifest: dict[str, Any] = {
        "schema_version": BUNDLE_SCHEMA,
        "bundle_id": _new_id(BUNDLE_PREFIX),
        "created_at": _now_iso(),
        "requested": {
            "from": query.from_ts.isoformat(),
            "to": query.to_ts.isoformat(),
            "streams": list(requested),
        },
        "filters": dict(query.filters),
        "service": {"name": SERVICE_NAME, "version": SERVICE_VERSION},
        "ops": {
            "telemetry": _safe_ops("telemetry"),
            "audit": _safe_ops("audit"),
        },
        "counts": counts,
        "limits": {"per_stream_rows": EXPORT_LIMIT},
        "retention": {
            "telemetry_days": TELEMETRY_RETENTION_DAYS,
            "audit_days": AUDIT_RETENTION_DAYS,
        },
        "effective_scope": access.scope_meta(),
        "members_sha256": {
            name: hashlib.sha256(content).hexdigest()
            for name, content in members
        },
        "excluded": list(BUNDLE_EXCLUDED),
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    members.append(("manifest.json", manifest_bytes))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members:
            info = zipfile.ZipInfo(name, date_time=BUNDLE_DATE_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, content)
    zip_bytes = buffer.getvalue()
    filename = f"{manifest['bundle_id']}.zip"
    return zip_bytes, manifest["bundle_id"], filename


def _safe_ops(kind: str) -> dict[str, Any]:
    """ops status -- уже safe-подмножество (CERT DOCLOG-3, AC10):
    backend/счётчики/ok, без env/DSN. Сбой сборки статуса не срывает
    пакет (пакет -- diagnostic, не защищаемая операция науки)."""
    try:
        if kind == "telemetry":
            from apps.api.telemetry import telemetry_status

            return telemetry_status()
        from apps.api.security_audit import audit_status

        return audit_status()
    except Exception:
        return {"ok": False, "error": "status_unavailable"}
