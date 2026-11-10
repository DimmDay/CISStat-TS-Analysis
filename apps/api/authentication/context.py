"""AUTH-03: one immutable request context and projections for legacy consumers.

Credential verifiers are server-installed adapters, never identity headers.
This module authenticates/resolves context, not object/capability/CU policy.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID, uuid4

from fastapi import HTTPException
from apps.api.plans import AuthenticatedPrincipal, Capabilities, PlanName, Role
from .errors import AuthSchemaNotReady, AuthStoreUnavailable


@dataclass(frozen=True)
class VerifiedCredential:
    """Server verifier output AFTER credential validity/revocation verification.

    IDs are safe references; no bearer token, raw API key or password belongs
    here. AUTH-04 supplies the AuthSession verifier; AUTH-10 replaces ENV keys.
    """

    subject_id: str
    credential_id: str
    auth_method: str
    account_id: str | None = None
    scopes: frozenset[str] = field(default_factory=frozenset)
    auth_session_id: str | None = None
    auth_time: datetime | None = None
    mfa_verified_at: datetime | None = None
    legacy_principal: AuthenticatedPrincipal | None = field(default=None, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "scopes", frozenset(self.scopes))


class CredentialVerifier(Protocol):
    def api_key(self, key: str) -> VerifiedCredential | None: ...
    def session(self, request) -> VerifiedCredential | None: ...


@dataclass(frozen=True)
class RequestContext:
    subject_id: str = ""
    tenant_id: str = "tenant-default"
    auth_method: str = "anonymous"
    credential_id: str | None = None
    auth_session_id: str | None = None
    account_id: str | None = None
    membership_role: str | None = None
    subject_version: int | None = None
    entitlement_version: int | None = None
    role: Role | None = None
    plan: PlanName | None = None
    account_plan: str | None = None
    account_type: str | None = None
    plan_expires_at: datetime | None = None
    account_capabilities: Capabilities | None = field(default=None, repr=False, compare=False)
    scopes: frozenset[str] = field(default_factory=frozenset)
    platform_permissions: frozenset[str] = field(default_factory=frozenset)
    auth_time: datetime | None = None
    mfa_verified_at: datetime | None = None
    demo_grant_id: str | None = None
    request_id: str = ""
    context_version: str = "auth.request_context/1"

    @property
    def is_authenticated(self):
        return bool(
            self.subject_id
            and self.auth_method not in ("anonymous", "session_surrogate")
        )

    def as_subject(self):
        from apps.api.identity import SubjectRef

        return SubjectRef(
            subject_id=self.subject_id,
            tenant_id=self.tenant_id,
            via=(
                "api_key"
                if self.auth_method in ("api_key", "legacy_api_key")
                else self.auth_method
            ),
            role=self.role.value if self.role else None,
            scopes=self.scopes,
            account_id=self.account_id,
            credential_id=self.credential_id,
            auth_method=self.auth_method,
            is_authenticated=self.is_authenticated,
        )

    def as_principal(self):
        if not self.is_authenticated or self.role is None:
            auth_error(401, "authentication_required", self.request_id)
        return AuthenticatedPrincipal(
            principal_id=self.subject_id,
            subject_id=self.subject_id,
            tenant_id=self.tenant_id,
            role=self.role,
            plan=self.plan,
            scopes=tuple(sorted(self.scopes)),
            account_id=self.account_id,
            credential_id=self.credential_id,
            auth_method=self.auth_method,
            entitlement_version=self.entitlement_version,
            account_capabilities=self.account_capabilities.model_copy(deep=True)
            if self.account_capabilities is not None else None,
        )


_MESSAGES = {
    "billing_not_configured": "Оплата ещё не настроена",
    "billing_unavailable": "Оплата недоступна для этого аккаунта",
    "billing_cycle_unavailable": "Платёжный цикл недоступен; обратитесь к оператору",
    "billing_order_exists": "По заявке уже создан заказ",
    "billing_reduction_not_approved": "Условия уменьшения мест ещё не утверждены",
    "billing_quote_not_found": "Предложение не найдено",
    "billing_quote_changed": "Предложение изменилось; обновите данные",
    "billing_quote_expired": "Предложение устарело; запросите новое",
    "billing_quote_limit": "Лимит предложений по заявке исчерпан",
    "account_not_found":"Аккаунт не найден",
    "invalid_request":"Некорректные параметры запроса",
    'invitation_unavailable': 'Приглашение недоступно, истекло или предназначено другому пользователю',
    'team_unavailable': 'Командный доступ недоступен для этого аккаунта',
    'owner_required': 'Действие доступно владельцу аккаунта',
    'recent_login_required': 'Войдите заново и подтвердите MFA, если он настроен',
    'account_version_conflict': 'Состав или параметры аккаунта изменились; обновите страницу',
    'multi_required': 'Сначала включите командный доступ',
    'invitation_limit': 'Лимит действующих приглашений исчерпан',
    'already_member': 'Пользователь уже состоит в команде',
    'invitation_consumed': 'Приглашение уже использовано; запросите новое у владельца',
    'seat_capacity_exhausted': 'Нет свободного подтверждённого места',
    'account_obligations': 'Переход невозможен: проверьте участников, места и незавершённые операции',
    'owner_transfer_required': 'Сначала передайте владение другому участнику',
    'member_not_found': 'Участник не найден',
    'seat_request_pending': 'Заявка на изменение мест уже ожидает подтверждения',
    'seat_request_not_found': 'Заявка не найдена',
    'seat_request_unavailable': 'Заявка уже закрыта или больше недействительна',
    "admission_consumed": "Код участника уже использован; для продолжения нужен свой браузерный доступ",
    "demo_request_limit": "Лимит запросов демо исчерпан; обратитесь на стенд",
    "demo_upload_limit": "Файл превышает допустимый размер демо",
    "demo_request_incomplete": "Предыдущий запрос не завершён; повторное исполнение не запущено",

    "demo_expired": "Демо-доступ завершён; войдите в личный аккаунт или обратитесь на стенд",
    "campaign_inactive": "Демо-кампания ещё не началась, приостановлена или недоступна в этой оболочке",
    "campaign_not_found": "Демо-кампания не найдена",
    "campaign_policy_conflict": "Версия или состояние кампании изменились; обновите список",
    "campaign_capacity_exhausted": "Лимит демо-кампании исчерпан; обратитесь на стенд",
    "invalid_campaign_policy": "Некорректная или неконечная политика кампании",

    "compute_result_unavailable":"Результат вычисления временно недоступен; повторный расчёт не запущен",
    'compute_profile_unavailable':'Сервис вычислений временно недоступен',
    'compute_work_not_calibrated':'Выбранные параметры вычисления пока не поддерживаются сервером',
    'compute_capacity_exceeded':'Вычислительные мощности заняты; повторите позже',
    'compute_route_required':'Защищённый вычислительный контур недоступен',
    "worker_service_unavailable": "Служебная авторизация worker недоступна",
    "worker_not_found": "Задание worker не найдено",
    "worker_fenced": "Попытка задания больше не действительна",
    "worker_uncertain": "Результат исполнения требует сверки; резерв удерживается",
    "worker_expired": "Время исполнения задания истекло",
    "worker_stopped": "Вычисление остановлено до публикации результата",
    "worker_managed_reservation": "Резерв управляется worker coordinator",
    "budget_not_configured": "Ресурсный бюджет ещё не настроен",
    "budget_scope_inactive": "Ресурсная политика приостановлена или истекла",
    "budget_overflow": "Превышен диапазон ресурсного учёта",
    "quota_exceeded": "Ресурсная квота исчерпана",
    "concurrency_exceeded": "Достигнут предел одновременных операций",
    "cu_reserve_exceeded": "Требуется дополнительный резерв до продолжения работы",
    "idempotency_conflict": "Этот ключ уже использован для другого запроса",
    "invalid_analysis_claim": "Некорректный контекст нового исследования",
    "reservation_expired": "Срок допуска операции истёк",
    "reservation_not_found": "Резервирование не найдено",
    "reservation_conflict": "Состояние или версия резервирования изменились",
    "unknown_entry": "Неизвестная защищённая операция",
    "unknown_operation": "Неизвестная операция",
    "operation_unavailable": "Операция недоступна в защищённом режиме",
    "external_policy_required": "Требуется отдельная проверка полномочий",
    "stage_restricted": "Прикладной модуль недоступен в текущем тарифе",
    "unknown_stage": "Неизвестный этап исследования",
    "capability_not_included": "Возможность не включена в текущий тариф Account",
    "baseline_limit_exceeded": "Нагрузка превышает пределы baseline текущего тарифа",
    "dataset_limit_exceeded": "Датасет превышает пределы текущего тарифа",
    "model_context_required": "Проверенный контекст модели недоступен",
    "registry_version_mismatch": "Версия политики доступа несовместима",
    "api_not_included": "Программный API недоступен в текущем тарифе",
    "api_key_required": "Для программного API требуется ключ",
    "scientific_credential_not_allowed": "Этот credential не разрешён на browser маршруте",
    "scientific_object_not_found": "Объект исследования не найден",
    "invalid_scientific_request": "Некорректный запрос научной операции",

    "authentication_required": "Требуется аутентификация",
    "invalid_credential": "Недействительные учётные данные",
    "auth_ambiguous": "Предъявлены несовместимые контексты доступа",
    "auth_authority_unavailable": "Сервис аутентификации недоступен",
    "oidc_unavailable": "Вход через корпоративный SSO не настроен",
    "oidc_already_linked": "Этот корпоративный вход уже привязан к другой учётной записи",
    "email_unavailable": "Вход по email не настроен",
    "email_delivery_unavailable": "Отправка письма недоступна; попробуйте позже",
    "email_already_bound": "Этот адрес уже привязан к другой учётной записи",
    "durable_binding_required": "Требуется подтверждённая привязка учётных данных",
    "account_required": "Требуется привязка к аккаунту",
    "account_access_denied": "Доступ к аккаунту запрещён",
    "account_expired": "Срок доступа аккаунта истёк; обратитесь к владельцу или администратору",
    "api_not_allowed": "Текущий аккаунт не включает программный API",
    "api_scope_denied": "Scope ключа не разрешает эту операцию",
    "api_key_management_denied": "Управление ключами недоступно",
    "api_key_not_found": "Ключ не найден",
    "api_key_conflict": "Версия ключа изменилась",
    "api_key_inactive": "Ключ отозван или истёк",
    "api_key_limit": "Достигнут предел активных ключей",
    "api_key_invalid_request": "Некорректные параметры ключа",
    "reauthentication_required": "Повторите личный вход перед выдачей или ротацией ключа",
    "password_policy": "Пароль: от 15 символов, до 1024 байт; распространённые пароли запрещены",
    "too_many_attempts": "Слишком много попыток; повторите позже",
    "csrf_invalid": "Проверка источника запроса не пройдена",
    "mfa_required": "Требуется подтверждение MFA",
    "admin_role_required": "Требуется роль администратора платформы",
    "session_not_found": "Сессия не найдена",
    "auth_version_conflict": "Учётные данные изменились; повторите вход",
}


class AuthHTTPException(HTTPException):
    """Only locally constructed safe DTOs may cross the verifier boundary."""


def auth_error(status, code, request_id=""):
    # FastAPI's existing HTTPException envelope stays compatible: detail carries
    # the versioned safe error payload. No driver error or credential material.
    raise AuthHTTPException(
        status_code=status,
        headers={"Cache-Control": "no-store"},
        detail={
            "code": code,
            "message": _MESSAGES[code],
            "request_id": request_id,
        },
    ) from None


def _request_id(request):
    # Reuse the existing telemetry correlation, including its validated header.
    # A separate UUID would break body/header/audit correlation in real ASGI.
    from apps.api.telemetry import current_request_id

    value = current_request_id()
    if isinstance(value, str) and value:
        return value
    value = getattr(getattr(request, "state", None), "request_id", None)
    return value if isinstance(value, str) and value else str(uuid4())


def _research_binding(request):
    from apps.api.session_store import SESSION_COOKIE_NAME, peek_session_store

    pointer = request.cookies.get(SESSION_COOKIE_NAME)
    if not pointer:
        return None
    store = peek_session_store()
    if store is None:
        return None
    try:
        session = store.get(pointer)
    except Exception:
        # An unavailable owner lookup cannot be replaced by a different identity.
        auth_error(503, "auth_authority_unavailable")
    if session is not None and getattr(session, "owner_subject", None):
        return str(session.owner_subject), str(session.tenant_id or "tenant-default")
    return None


def _validate_evidence(evidence, request_id):
    from apps.api.identity import ALL_SCOPES

    if (
        not isinstance(evidence, VerifiedCredential)
        or evidence.auth_method
        not in ("api_key", "legacy_api_key", "auth_session", "service", "oidc")
        or not evidence.subject_id
        or not evidence.credential_id
        or not evidence.scopes <= ALL_SCOPES
    ):
        auth_error(401, "invalid_credential", request_id)
    for value in (evidence.auth_time, evidence.mfa_verified_at):
        if value is not None and (
            not isinstance(value, datetime) or value.tzinfo is None
        ):
            auth_error(401, "invalid_credential", request_id)


def resolve_verified_context(evidence, *, store=None, request_id=""):
    """Reload AUTH-02 Identity/Account/Membership in one readonly transaction.

    Trusted verifier output is necessary; client-supplied subject/account IDs
    must never be passed here as evidence. No auto-selection or email merge.
    """
    _validate_evidence(evidence, request_id)
    if evidence.account_id is None:
        auth_error(403, "account_required", request_id)
    try:
        subject_id = UUID(evidence.subject_id)
        account_id = UUID(evidence.account_id)
    except (ValueError, TypeError, AttributeError):
        auth_error(401, "invalid_credential", request_id)
    try:
        if store is None:
            from .storage import PostgresAccessStore

            store = PostgresAccessStore.from_env()
        with store.transaction(readonly=True) as tx:
            identity = tx.identities.get(subject_id)
            if identity is None or identity.status != "active":
                auth_error(401, "invalid_credential", request_id)
            account = tx.accounts.get(account_id)
            if account is None or account.status != "active":
                auth_error(403, "account_access_denied", request_id)
            membership = next(
                (
                    m
                    for m in tx.accounts.memberships(account_id)
                    if str(m.subject_id) == str(subject_id) and m.status == "active"
                ),
                None,
            )
            if membership is None:
                auth_error(403, "account_access_denied", request_id)
            from apps.api.accounts.entitlements import account_is_active, account_capabilities

            now = datetime.now(timezone.utc)
            if not account_is_active(account, now=now):
                auth_error(403, "account_expired", request_id)
            role = Role(identity.platform_role)
            # INTERNAL is Account authority, not a role-based upgrade.
            plan = PlanName(account.plan) if account.plan != "internal" else None
            from .demo import restrict_capabilities
            effective_caps, demo_grant_id = restrict_capabilities(
                tx.connection, account, account_capabilities(account, now=now), now
            )
            return RequestContext(
                demo_grant_id=demo_grant_id,
                subject_id=str(subject_id),
                tenant_id=str(account.tenant_id),
                account_id=str(account_id),
                membership_role=membership.account_role,
                subject_version=identity.subject_version,
                entitlement_version=account.entitlement_version,
                role=role,
                plan=plan,
                account_plan=account.plan,
                account_type=account.account_type,
                plan_expires_at=account.plan_expires_at,
                account_capabilities=effective_caps,
                scopes=evidence.scopes,
                platform_permissions=frozenset({"platform.admin", "platform.demo.manage"})
                if role == Role.ADMIN
                else frozenset(),
                auth_method=evidence.auth_method,
                credential_id=evidence.credential_id,
                auth_session_id=evidence.auth_session_id,
                auth_time=evidence.auth_time,
                mfa_verified_at=evidence.mfa_verified_at,
                request_id=request_id,
            )
    except (AuthStoreUnavailable, AuthSchemaNotReady):
        auth_error(503, "auth_authority_unavailable", request_id)


def _verify(verifier, method, value, request_id):
    """Normalize adapter errors; an upstream HTTPException is not a safe DTO."""
    try:
        return getattr(verifier, method)(value)
    except AuthHTTPException:
        raise
    except HTTPException as exc:
        if exc.status_code == 401:
            auth_error(401, "invalid_credential", request_id)
        auth_error(503, "auth_authority_unavailable", request_id)
    except Exception:
        auth_error(503, "auth_authority_unavailable", request_id)


def _resolve_context(request, request_id):
    from apps.api.identity import get_identity_mode, MODE_SCOPED, SubjectRef
    from .sessions import SessionCredentialVerifier

    app = getattr(request, "scope", {}).get("app")
    if app is None and not hasattr(request, "scope"):
        app = getattr(request, "app", None)
    state = getattr(app, "state", None)
    verifier = getattr(state, "auth_credential_verifier", None)
    if verifier is None:
        verifier = SessionCredentialVerifier(request)
    # Headers.getlist preserves empty and duplicate credentials. Some existing
    # producer adapters pass a tiny request object with a plain headers dict.
    headers = request.headers
    keys = (
        headers.getlist("x-api-key")
        if hasattr(headers, "getlist")
        else ([headers["x-api-key"]] if "x-api-key" in headers else [])
    )
    if len(keys) > 1:
        auth_error(400, "auth_ambiguous", request_id)
    if "authorization" in headers:
        auth_error(401, "invalid_credential", request_id)
    key_evidence = None
    if keys:
        if not keys[0]:
            auth_error(401, "invalid_credential", request_id)
        key_evidence = _verify(verifier, "api_key", keys[0], request_id)
        if key_evidence is None:
            auth_error(401, "invalid_credential", request_id)
        _validate_evidence(key_evidence, request_id)
    session_evidence = _verify(verifier, "session", request, request_id)
    if session_evidence is not None:
        _validate_evidence(session_evidence, request_id)
    if (
        key_evidence
        and session_evidence
        and (
            key_evidence.subject_id != session_evidence.subject_id
            or key_evidence.account_id != session_evidence.account_id
        )
    ):
        auth_error(400, "auth_ambiguous", request_id)
    evidence = key_evidence or session_evidence
    mode = get_identity_mode()
    if evidence:
        if evidence.auth_method == "legacy_api_key":
            if mode == MODE_SCOPED or evidence.legacy_principal is None:
                auth_error(401, "durable_binding_required", request_id)
            p = evidence.legacy_principal
            ctx = RequestContext(
                subject_id=p.subject_id,
                tenant_id=p.tenant_id,
                auth_method="legacy_api_key",
                credential_id=evidence.credential_id,
                role=p.role,
                plan=p.plan,
                scopes=evidence.scopes,
                request_id=request_id,
                platform_permissions=frozenset({"platform.admin", "platform.demo.manage"})
                if p.role == Role.ADMIN
                else frozenset(),
            )
        else:
            ctx = resolve_verified_context(
                evidence,
                store=getattr(state, "auth_access_store", None),
                request_id=request_id,
            )
        binding = _research_binding(request)
        if ctx.account_id is None and binding and binding != (ctx.subject_id, ctx.tenant_id):
            auth_error(400, "auth_ambiguous", request_id)
        return ctx
    if mode == MODE_SCOPED:
        return RequestContext(request_id=request_id)
    binding = _research_binding(request)
    if binding:
        return RequestContext(
            subject_id=binding[0],
            tenant_id=binding[1],
            auth_method="session_surrogate",
            request_id=request_id,
        )
    pointer = request.cookies.get("cisstat_session_id")
    if pointer:
        surrogate = SubjectRef.from_session(pointer)
        return RequestContext(
            subject_id=surrogate.subject_id,
            tenant_id=surrogate.tenant_id,
            auth_method="session_surrogate",
            request_id=request_id,
        )
    return RequestContext(request_id=request_id)


def resolve_request_context(request):
    """One resolution per request, shared by all compatibility projections.

    No positive authority cache across requests. Never fall through a presented
    bad credential or authority outage to legacy browser identity.
    """
    state = getattr(request, "state", None)
    cached = getattr(state, "_auth03_context", None)
    if isinstance(cached, RequestContext):
        return cached
    request_id = _request_id(request)
    try:
        context = _resolve_context(request, request_id)
    except HTTPException as exc:
        if isinstance(exc.detail, dict):
            exc.detail["request_id"] = request_id
        _audit_denial(request, exc)
        raise
    except Exception:
        # Server adapter/DB failures are never turned into authentication or
        # exposed as exception messages. This also covers a missing DB driver.
        auth_error(503, "auth_authority_unavailable", request_id)
    if state is not None:
        state._auth03_context = context
    return context


def _audit_denial(request, exc):
    try:
        from apps.api.identity import subject_pseudonym
        from apps.api.security_audit import record_standard

        record_standard(
            "authn_denied",
            "denied",
            actor_subject=subject_pseudonym(
                request.headers.get("x-api-key") or "missing-credential"
            ),
            actor_via="request_context",
            resource_kind="principal",
            policy_basis="AUTH-03 unified context",
            details={"reason_code": exc.detail.get("code", "invalid_credential")},
        )
    except Exception:
        pass
