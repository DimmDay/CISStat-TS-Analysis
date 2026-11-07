# apps/api/auth.py
"""
Авторизация: API-ключ -> AuthenticatedPrincipal (роль + план) -> Capabilities.

ЗАМЕНА для прежней версии, где ключ был просто "валиден/невалиден" без
привязки к плану. Теперь каждый ключ резолвится в конкретного клиента
с ролью и (для внешних) тарифным планом -- это то, что реально позволяет
проверять "can_train_models" и т.п., а не просто пускать/не пускать.

AUTH-03: единый immutable RequestContext проецируется в безопасный principal.
Legacy сопоставление ключ -> principal пока статичное (переменная
окружения в формате "ключ:роль:план,ключ:роль:план"). Для продакшена --
таблица клиентов в БД (нужна ради биллинга/лимитов использования,
см. открытый вопрос "Биллинг/лимиты для публичного API" в
docs/MIGRATION_ARCHITECTURE.md), но контракт зависимостей
(Depends(get_current_principal), Depends(require_capability(...)))
не изменится при переходе на неё.
"""

from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status

from apps.api.plans import AuthenticatedPrincipal, Capabilities, Role


def _parse_key_registry() -> dict[str, AuthenticatedPrincipal]:
    """Compatibility facade; the ENV adapter never exposes key material."""
    from apps.api.authentication.legacy import parse_key_registry

    return parse_key_registry()


def resolve_principal_for_key(key: str) -> Optional[AuthenticatedPrincipal]:
    """Identity-only lookup. HTTP admission is checked on the real request."""
    if not key:
        return None
    from apps.api.authentication.api_keys import key_mode
    if not key.startswith("csk_") and key_mode() == "legacy_dev" and key not in _parse_key_registry():
        return None
    try:
        return get_current_principal(x_api_key=key)
    except HTTPException as exc:
        if exc.status_code == 401:
            return None
        raise


def get_current_principal(
    request: Request = None,
    x_api_key: Optional[str] = Header(default=None),
) -> AuthenticatedPrincipal:
    """Key-protected legacy dependency, projected from the shared context.

    Direct Python callers may still supply x_api_key. HTTP requests always
    use their real headers, so a manual caller cannot replace an HTTP key.
    Research surrogates never satisfy this dependency.
    """
    from apps.api.authentication.context import resolve_request_context, auth_error

    if request is None:
        from starlette.requests import Request as HTTPRequest

        headers = (
            [(b"x-api-key", x_api_key.encode("utf-8"))]
            if isinstance(x_api_key, str)
            else []
        )
        request = HTTPRequest(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "query_string": b"",
                "headers": headers,
            }
        )
        request.state._auth10_principal_lookup = True
    context = resolve_request_context(request)
    if context.auth_method not in ("api_key", "legacy_api_key"):
        auth_error(401, "authentication_required", context.request_id)
    return context.as_principal()


def resolve_request_principal(
    request: Request = None,
    x_api_key: Optional[str] = Header(default=None),
) -> AuthenticatedPrincipal:
    """AUTH-07 shared projection for named-session OR key principals.

    Единственная точка входа админ-области после миграции: named-сессия
    (auth_session, AUTH-04/05) и API-ключ (программный канал до AUTH-10)
    образуют один principal-контракт; research-суррогаты и аноним --
    401 authentication_required. Роль/капабилити проверяются выше по
    стеку (require_admin_role / resolve_effective_log_access).
    """
    from apps.api.authentication.context import resolve_request_context, auth_error

    if request is None:
        from starlette.requests import Request as HTTPRequest

        headers = (
            [(b"x-api-key", x_api_key.encode("utf-8"))]
            if isinstance(x_api_key, str)
            else []
        )
        request = HTTPRequest(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "query_string": b"",
                "headers": headers,
            }
        )
    context = resolve_request_context(request)
    if context.auth_method not in ("api_key", "legacy_api_key", "auth_session"):
        auth_error(401, "authentication_required", context.request_id)
    return context.as_principal()


def require_capability(capability_name: str):
    """
    Фабрика зависимостей для защиты конкретных эндпоинтов по возможности,
    а не по роли/плану напрямую -- например:

        @router.post("/models/train", dependencies=[Depends(require_capability("can_train_models"))])

    Если новый тариф получит can_train_models=True -- эндпоинт станет
    доступен ему автоматически, без правки роутера.
    """

    def _checker(
        principal: AuthenticatedPrincipal = Depends(get_current_principal),
    ) -> AuthenticatedPrincipal:
        caps: Capabilities = principal.capabilities
        if not getattr(caps, capability_name, False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Текущий план не включает возможность '{capability_name}'",
            )
        return principal

    return _checker


# Обратная совместимость с уже написанными роутерами (public.py, internal.py),
# которые используют Depends(require_api_key) без учёта плана -- просто
# проверка подлинности ключа, без проверки конкретной возможности.
def require_api_key(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> str:
    return principal.principal_id


def require_admin_role(
    request: Request = None,
    x_api_key: Optional[str] = Header(default=None),
) -> AuthenticatedPrincipal:
    """Admin-гвард платформы после миграции AUTH-07 (spec_auth_architecture.md
    строка 196: «Named ADMIN+MFA управляет реальными API standalone/embedded;
    analyst/OWNER получают отказ»).

    Named-сессия (auth_session): требует роль ADMIN (identity.platform_role)
    И верифицированное MFA-подтверждение сессии (mfa_verified_at;
    defense-in-depth -- sessions._load уже принуждает MFA для admin, гвард
    проверяет проекцию контекста явно). account-OWNER/analyst -- 403.

    API-ключ (программный канал, до AUTH-10): прежний контракт -- роль
    ADMIN реестра ключей; cookie-сессия аналитика ключ не заменяет.

    НЕ новая система прав: та же ролевая модель (Role). Проверяется РОЛЬ,
    а не capability: доступ к админке определяется ИДЕНТИЧНОСТЬЮ (кто вы),
    не тарифом -- полные capabilities internal_analyst админку не открывают.
    """
    from apps.api.authentication.context import resolve_request_context, auth_error

    if request is None:
        from starlette.requests import Request as HTTPRequest

        request = HTTPRequest(
            {
                "type": "http",
                "method": "GET",
                "path": "/",
                "query_string": b"",
                "headers": (
                    [(b"x-api-key", x_api_key.encode("utf-8"))]
                    if isinstance(x_api_key, str)
                    else []
                ),
            }
        )
    context = resolve_request_context(request)
    if context.auth_method == "auth_session":
        if context.role != Role.ADMIN:
            try:
                from apps.api.security_audit import record_standard

                record_standard(
                    "authz_denied",
                    "denied",
                    actor_subject=context.subject_id or "",
                    actor_via="auth_session",
                    resource_kind="admin_endpoint",
                    policy_basis="AUTH-07 named admin session",
                    details={"reason_code": "role_insufficient"},
                )
            except Exception:  # pragma: no cover -- audit не роняет auth
                pass
            auth_error(403, "admin_role_required", context.request_id)
        if context.mfa_verified_at is None:
            auth_error(403, "mfa_required", context.request_id)
        return context.as_principal()
    if context.auth_method in ("api_key", "legacy_api_key"):
        if context.role != Role.ADMIN:
            # DOCLOG-3 (§14.1): авторизационный отказ -- durable audit
            # (псевдоним субъекта, НЕ значение ключа principal_id).
            try:
                from apps.api.identity import subject_pseudonym
                from apps.api.security_audit import record_standard

                record_standard(
                    "authz_denied",
                    "denied",
                    actor_subject=(
                        context.subject_id
                        or subject_pseudonym(getattr(context, "subject_id", "") or "")
                    ),
                    actor_via="api_key",
                    resource_kind="admin_endpoint",
                    policy_basis="ADMIN role required",
                    details={"reason_code": "role_insufficient"},
                )
            except Exception:  # pragma: no cover -- audit не роняет auth
                pass
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Требуется роль ADMIN (API-ключ администратора платформы)",
            )
        return context.as_principal()
    auth_error(401, "authentication_required", context.request_id)
