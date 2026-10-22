# apps/api/identity.py
"""
DOCLOG-0 (spec_documentation_logging.md §9.1, §15, §15.1, §19):
идентичность и контракт -- owner/tenant/scopes, политика legacy-владения,
threat model, схемы IDs/validity/completeness.

ПОСТАНОВКА-БЛОКЕР (§19, строка DOCLOG-0): «нельзя читать чужой
run/document/artifact/job во всех путях, существующий report учтён».

R09 (§15): любая metadata/preview/rendition/job/artifact-ссылка проходит
ОДНУ объектную авторизацию: аутентифицированный субъект -> tenant ->
membership/grant -> ресурс и его версия -> разрешённое действие.
ЗНАНИЕ run_id/document_id/hash НЕ является правом. Query-параметр
tenant не определяет границу доверия. Субъект -- стабильный безопасный
ID, НЕ значение API-key/cookie.

THREAT MODEL (контур DOCLOG-0; полный реестр -- docs/doclog0_identity_contract.md):

  T1. Держатель run_id (аноним/чужая сессия) читает исследование/отчёт
      по /v1/progress/runs/{id}[*/report] -- прежний report route не имел
      owner-проверки (F08 спеки). Закрыто: решающая таблица
      authorize_run_access на ВСЕХ run-маршрутах, uniform 404.
  T2. Чужая cookie-сессия пишет в чужой запуск (pause/resume/checkpoints/
      restore). Закрыто: тот же gate на write-действиях + гвард зеркала
      слоя 2 (record_run_event не пишет в bound-запуск чужого субъекта).
  T3. Restore назначает владельца тому, кто первым назвал run_id
      (§15.1 -- прямо запрещено). Закрыто: restore проверяет владение;
      новая сессия НАСЛЕДУЕТ субъект владельца (континуитет), не
      получает новое; легаси-run восстанавливает только создавшая
      cookie-сессия либо admin.
  T4. API-key/cookie используются как идентичность. Закрыто: субъект --
      псевдоним HMAC-SHA256 (subject_pseudonym), материал ключа/cookie
      не восстанавливаем и не дисклоужается; явный subject_id в реестре,
      равный значению ключа, отклоняется (fail-closed).
  T5. Tenant-граница снимается подменой параметров. Закрыто: tenant --
      серверное поле привязки, из запроса не читается; mismatch deny.
  T6. Секреты в операционных поверхностях. Закрыто в границах задачи:
      /health/ops identity-блок несёт режим и bool «реестр настроен»,
      БЕЗ значений ключей; AccessDecision/логи несут псевдонимы.

LEGACY OWNERSHIP POLICY (§15.1):
  - run без owner-полей (корпус до DOCLOG-0) -- состояние
    ownership=unresolved (ВЫЧИСЛЯЕТСЯ резолвером; данные не
    переписываются задним числом, §9.2);
  - незавершённые привязки не фабрикуются: привязка легаси-run --
    только административная миграция (будущий контур, §15.1) с
    записью основания и audit;
  - непрерывность чтения легаси: создавшая cookie-сессия
    (СЕРВЕРНАЯ запись run.session_id, не клиентское заявление) либо
    ADMIN; внешний share/publish/export через новый сервис для
    unresolved ЗАПРЕЩЕНЫ (контур DOCLOG-4+ обязан проверять
    ownership=="bound").

РЕЖИМЫ ИДЕНТИЧНОСТИ (CISSTAT_IDENTITY_MODE):
  - "session_scoped" (ДЕФОЛТ, enforced): каждая cookie-сессия -- свой
    субъект-суррогат; новые run'ы привязываются к субъекту создателя;
    чужой доступ отказывается. Это честный дефолт multi-посетительских
    развертываний (Render/Vercel);
  - "dev_single_user": ЯВНО объявленная изоляция одного аналитика --
    cross-session доступ разрешён и помечен reason'ом
    dev_single_user_isolated (§15.1: «не выдаётся за multi-tenant
    production»); /health/ops показывает режим честно;
  - "scoped": производственный контракт (субъекты из API-ключей/
    portal assertion). Структура готова; полный адаптер portal
    assertion -- будущая задача; поведение в этой задаче =
    session_scoped (честно помечено).

НЕ входит в DOCLOG-0 (спека §19): durable-артефакты (DOCLOG-1),
ReportSnapshot (DOCLOG-2), телеметрия/audit-поток (DOCLOG-3), UI
выдачи (DOCLOG-4). Здесь -- контракт идентичности и его применение к
существующему run-контуру.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Пространства имён и дефолты (схемы IDs, §9.1) ────────────────────

DEFAULT_TENANT_ID = "tenant-default"
SUBJECT_PREFIX = "subj-"
RUN_ID_PATTERN = re.compile(r"^RUN-[0-9A-Z]{8}$")
SUBJECT_ID_PATTERN = re.compile(r"^subj-[0-9a-f]{16}$")
TENANT_ID_PATTERN = re.compile(r"^tenant-[a-z0-9][a-z0-9-]{0,31}$")

IDENTITY_MODE_ENV = "CISSTAT_IDENTITY_MODE"
IDENTITY_SALT_ENV = "CISSTAT_IDENTITY_SALT"
MODE_SESSION_SCOPED = "session_scoped"
MODE_DEV_SINGLE_USER = "dev_single_user"
MODE_SCOPED = "scoped"
_KNOWN_MODES = (MODE_SESSION_SCOPED, MODE_DEV_SINGLE_USER, MODE_SCOPED)

# Dev-соль по умолчанию: ЧЕСТНО документированная константа разработки.
# Продакшен обязан задать CISSTAT_IDENTITY_SALT (политика, §22: решения
# оформляются versioned ADR, не молчаливыми значениями).
_DEV_SALT = "cisstat-identity-dev-salt-v1"


def get_identity_mode() -> str:
    """Активный режим идентичности; незнакомое значение -- fail-closed
    к session_scoped (ослабления молчанием не бывает, warning журналу)."""
    raw = (os.environ.get(IDENTITY_MODE_ENV) or "").strip()
    if not raw:
        return MODE_SESSION_SCOPED
    if raw not in _KNOWN_MODES:
        logger.warning(
            "Identity: незнакомый CISSTAT_IDENTITY_MODE=%r -- fail-closed к %s",
            raw, MODE_SESSION_SCOPED,
        )
        return MODE_SESSION_SCOPED
    return raw


def is_key_registry_configured() -> bool:
    """bool «реестр ключей настроен» -- БЕЗ значений (T6)."""
    return bool(os.environ.get("CISSTAT_API_KEYS", "").strip())


# ── Псевдонимизация субъекта (T4) ────────────────────────────────────


def subject_pseudonym(material: str, salt: Optional[str] = None) -> str:
    """Стабильный безопасный ID субъекта: subj-<hex16> = HMAC-SHA256
    (соль, материал)[:16]. Материал (значение ключа/cookie) не
    восстанавливаем из псевдонима и не содержится в нём. Один и тот же
    материал -- один и тот же субъект (стабильность); смена соли меняет
    все псевдонимы (ротация -- часть политики, не пер-запрос)."""
    if not isinstance(material, str) or not material:
        raise ValueError("Материал псевдонима обязателен (пустой субъект не фабрикуется)")
    effective_salt = (
        salt
        if salt is not None
        else (os.environ.get(IDENTITY_SALT_ENV) or _DEV_SALT)
    )
    digest = hmac.new(
        effective_salt.encode("utf-8"), material.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:16]
    return SUBJECT_PREFIX + digest


# ── Validity-схемы ───────────────────────────────────────────────────


def is_valid_run_id(value: str) -> bool:
    """Канон RUN-XXXXXXXX (существующий контракт ensure_run_id)."""
    return bool(isinstance(value, str) and RUN_ID_PATTERN.match(value))


def is_valid_subject_id(value: str) -> bool:
    """Субъект -- псевдоним subj-<hex16> (серверные суррогаты) либо
    непустой безопасный явный ID без пробелов (реестр/портал).
    Префикс subj- -- ЗАРЕЗЕРВИРОВАННОЕ пространство имён серверных
    суррогатов: subj- вне hex-шаблона невалиден (подделку формы не
    выдаём за субъект)."""
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        return False
    if value.startswith(SUBJECT_PREFIX):
        return bool(SUBJECT_ID_PATTERN.match(value))
    # Явный ID из реестра/портала: непустой, без пробелов/управляющих.
    if re.search(r"\s", value):
        return False
    return True


def is_valid_tenant_id(value: str) -> bool:
    """Tenant -- слаг tenant-<a-z0-9->; query-параметром не задаётся."""
    return bool(isinstance(value, str) and TENANT_ID_PATTERN.match(value))


# ── Каталог scopes (§15, таблица обязательных прав) ──────────────────


class Scope(str, Enum):
    """Обязательные права §15. reviewer/support -- permission sets
    (scopes), не новые enum-роли (§15, точный текст)."""

    DOCUMENTATION_READ = "documentation.read"
    DOCUMENTATION_WRITE = "documentation.write"
    DOCUMENTATION_EXPORT = "documentation.export"
    DOCUMENTATION_APPROVE = "documentation.approve"
    DOCUMENTATION_PUBLISH = "documentation.publish"
    ARTIFACT_DATA_READ = "artifact.data.read"
    LOGS_READ = "logs.read"
    LOGS_EXPORT = "logs.export"
    AUDIT_READ = "audit.read"
    SUPPORT_GRANT = "support.grant"
    POLICY_ADMIN = "policy.admin"


ALL_SCOPES: frozenset[str] = frozenset(s.value for s in Scope)


def default_scopes_for_role(role: Any) -> frozenset[str]:
    """Базовая выдача scopes по роли. ADMIN -- полный каталог (контракт
    §15.1: «новые admin endpoints сохраняют текущую ADMIN-проверку»).
    Аналитики/внешние -- ПУСТО: documentation.* приходит с DOCLOG-4+
    через policy layer, до тех пор не фантазируется."""
    from apps.api.plans import Role

    if role == Role.ADMIN or getattr(role, "value", role) == "admin":
        return ALL_SCOPES
    return frozenset()


# ── Субъект запроса ──────────────────────────────────────────────────


@dataclass(frozen=True)
class SubjectRef:
    """Аутентифицированный (или анонимный) субъект запроса.
    completeness (§9.1): via -- происхождение идентичности; role --
    только у key-субъектов; суррогаты анонимны (роль None)."""

    subject_id: str = ""
    tenant_id: str = DEFAULT_TENANT_ID
    via: str = "anonymous"  # api_key | session_surrogate | anonymous
    role: Optional[str] = None
    scopes: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_anonymous(self) -> bool:
        return not self.subject_id

    @classmethod
    def anonymous(cls) -> "SubjectRef":
        return cls(subject_id="", tenant_id=DEFAULT_TENANT_ID, via="anonymous")

    @classmethod
    def from_session(cls, session_id: str) -> "SubjectRef":
        """Субъект-суррогат cookie-сессии (dev/транзитный контракт §19.1:
        «Permissions/subject surrogate»); значение cookie НЕ является
        идентичностью -- только материал псевдонима."""
        if not session_id:
            return cls.anonymous()
        return cls(
            subject_id=subject_pseudonym(session_id),
            tenant_id=DEFAULT_TENANT_ID,
            via="session_surrogate",
        )

    @classmethod
    def from_principal(cls, principal: Any) -> "SubjectRef":
        """Субъект API-ключа: явный subject_id реестра либо псевдоним
        ключа. Значение ключа никогда не становится subject_id."""
        subject_id = getattr(principal, "subject_id", None) or subject_pseudonym(
            getattr(principal, "principal_id", "")
        )
        role = getattr(principal, "role", None)
        return cls(
            subject_id=subject_id,
            tenant_id=getattr(principal, "tenant_id", None) or DEFAULT_TENANT_ID,
            via="api_key",
            role=getattr(role, "value", role),
            scopes=frozenset(getattr(principal, "scopes", ()) or ()),
        )


def resolve_request_subject(request: Any) -> SubjectRef:
    """Единая точка резолва субъекта запроса (R09): валидный API-ключ
    приоритетен; иначе -- субъект cookie-сессии; иначе -- аноним.
    tenant/subject из НЕподписанных браузерных заголовков не
    принимаются (§15) -- их просто не существует в контракте.

    DOCLOG-0 (§15.1, restore-континуитет): для cookie-сессии замороженный
    владелец СЕРВЕРНОЙ записи (AnalysisSession.owner_subject,
    first-write-wins/restore-наследование) приоритетен суррогату сырого
    cookie: восстановленная сессия несёт НОВЫЙ cookie и УНАСЛЕДОВАННОГО
    владельца -- идентичность продолжает владелец, а не новый носитель.
    Субъект всегда серверная запись, не клиентское заявление; сбой
    lookup-а -- деградация к детерминированному суррогату без 500."""
    api_key = request.headers.get("x-api-key") if request is not None else None
    if api_key:
        from apps.api.auth import resolve_principal_for_key

        principal = resolve_principal_for_key(api_key)
        if principal is not None:
            return SubjectRef.from_principal(principal)
    # Ленивый импорт -- разрыв цикла (session_store импортирует identity).
    from apps.api.session_store import (
        SESSION_COOKIE_NAME,
        get_or_create_session_id,
        peek_session_store,
    )

    session_id = ""
    if request is not None:
        session_id = request.cookies.get(SESSION_COOKIE_NAME) or ""
    if not session_id:
        return SubjectRef.anonymous()
    store = peek_session_store()
    if store is not None:
        try:
            session = store.get(session_id)
        except Exception:  # pragma: no cover -- lookup не роняет резолв
            session = None
        if session is not None and getattr(session, "owner_subject", None):
            return SubjectRef(
                subject_id=str(session.owner_subject),
                tenant_id=(
                    str(session.tenant_id)
                    if getattr(session, "tenant_id", None)
                    else DEFAULT_TENANT_ID
                ),
                via="session_surrogate",
            )
    return SubjectRef.from_session(session_id)


# ── Владение run и решающая таблица (одна объектная авторизация) ─────

OWNERSHIP_BOUND = "bound"
OWNERSHIP_UNRESOLVED = "unresolved"

_ACTION_READ = "read"
_ACTION_WRITE = "write"


@dataclass(frozen=True)
class AccessDecision:
    """Результат объектной авторизации. completeness (§9.1): carries
    requester/run/action/reason -- достаточен для серверного audit-потока
    DOCLOG-3; в HTTP-ответы reason НЕ попадает (uniform 404)."""

    allowed: bool = False
    reason: str = ""
    run_id: str = ""
    action: str = ""
    requester_subject: str = ""
    requester_via: str = ""

    def audit_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "run_id": self.run_id,
            "action": self.action,
            "requester_subject": self.requester_subject or "anonymous",
            "requester_via": self.requester_via,
        }


def effective_ownership(run: Any) -> str:
    """Состояние владения: явное 'bound' либо unresolved для legacy
    (полей нет = честное отсутствие, состояние вычисляет резолвер)."""
    if getattr(run, "ownership", None) == OWNERSHIP_BOUND and getattr(
        run, "owner_subject", None
    ):
        return OWNERSHIP_BOUND
    return OWNERSHIP_UNRESOLVED


def _audit_access_decision(decision: "AccessDecision") -> None:
    """DOCLOG-3 (§14.1/§19.1): решения решающей таблицы -- в durable
    security audit (record_run_access_decision). best-effort по
    построению record_standard: сбой записи НЕ меняет решение
    (AC11-инвариант: deny остаётся deny, allow -- allow)."""
    try:
        from apps.api.security_audit import record_run_access_decision

        record_run_access_decision(decision)
    except Exception:  # pragma: no cover -- audit не роняет авторизацию
        pass


def authorize_run_access(
    run: Any,
    subject: SubjectRef,
    *,
    session_id: str = "",
    action: str = _ACTION_READ,
) -> AccessDecision:
    """Решающая таблица доступа к run (R09; §15.1). Fail-closed:
    неизвестная комбинация -- отказ. Deny НЕ различает «нет запуска» и
    «чужой запуск» на уровне HTTP (uniform 404 -- существование не
    дисклоужается); причина живёт в AccessDecision (серверный аудит).

    Таблица (первый совпавший строкец побеждает):
      1. anonymous-субъект                          -> deny anonymous
      2. роль ADMIN (key-субъект)                   -> allow admin
      3. mode dev_single_user                       -> allow dev_single_user_isolated
      4. bound && subject==owner && tenant==run     -> allow owner
      5. bound && (не совпало)                      -> deny foreign_session
      6. unresolved && session_id==run.session_id   -> allow creator_continuity
      7. unresolved && (иначе)                      -> deny unresolved_foreign
    """
    run_id = str(getattr(run, "run_id", "") or "")

    def _finish(allowed: bool, reason: str, *, log_warning: bool = False) -> AccessDecision:
        result = AccessDecision(
            allowed=allowed, reason=reason,
            run_id=run_id, action=action,
            requester_subject=subject.subject_id, requester_via=subject.via,
        )
        # Аудит решений (серверный; псевдонимы, без cookie/ключей):
        # отказы -- warning (их поиск -- первичный инцидент-сигнал),
        # разрешения -- info. DOCLOG-3 (выполнено): durable-поток
        # security_audit добавлен РЯДОМ с logger; сбой записи НЕ меняет
        # уже принятое решение (AC11-инвариант).
        (logger.warning if (log_warning or not allowed) else logger.info)(
            "Run access: %s run=%s action=%s subject=%s via=%s reason=%s",
            "ALLOW" if allowed else "DENY", run_id, action,
            subject.subject_id or "anonymous", subject.via, reason,
        )
        _audit_access_decision(result)
        return result

    # 1. Аноним (нет cookie/ключа): знания run_id недостаточно (R09).
    if subject.is_anonymous:
        return _finish(False, "anonymous", log_warning=True)

    # 2. ADMIN-роль сохраняет текущий контракт (§15.1): предметный
    #    доступ администратора фиксируется решением явно.
    if (subject.role or "") == "admin":
        return _finish(True, "admin")

    # 3. Явно объявленный single-user dev (§15.1): cross-session
    #    разрешён и честно помечен.
    if get_identity_mode() == MODE_DEV_SINGLE_USER:
        return _finish(True, "dev_single_user_isolated")

    # 4-7. Собственно владение. Tenant -- часть границы доверия (R09/T5):
    # mismatch запрещает ЛЮБОЙ непривилегированный исход, включая
    # серверный континуитет создателя.
    run_tenant = getattr(run, "tenant_id", None) or DEFAULT_TENANT_ID
    if effective_ownership(run) == OWNERSHIP_BOUND:
        if (
            subject.subject_id == getattr(run, "owner_subject", None)
            and subject.tenant_id == run_tenant
        ):
            return _finish(True, "owner")
        # 6'. Создавшая сессия bound-запуска (restore-наследование уже
        # кладёт owner в сессию; страховой континуитет по session_id --
        # только для СЕРВЕРНО записанного создателя и ЕГО tenant, не
        # для чужих).
        if (
            session_id
            and session_id == getattr(run, "session_id", "")
            and subject.tenant_id == run_tenant
        ):
            return _finish(True, "creator_continuity")
        return _finish(False, "foreign_session", log_warning=True)

    # unresolved (legacy): непрерывность создавшей cookie-сессии (в
    # пределах tenant-границы) либо отказ; привязка -- только
    # административная миграция (§15.1).
    if (
        session_id
        and session_id == getattr(run, "session_id", "")
        and subject.tenant_id == run_tenant
    ):
        return _finish(True, "creator_continuity")
    return _finish(False, "unresolved_foreign", log_warning=True)
