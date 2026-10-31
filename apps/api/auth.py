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
    """Legacy lookup, authoritative for durable bindings, None for unknown key."""
    if not key or key not in _parse_key_registry():
        return None
    return get_current_principal(x_api_key=key)


def get_current_principal(
    request: Request = None,
    x_api_key: Optional[str] = Header(default=None),
) -> AuthenticatedPrincipal:
    """Key-protected legacy dependency, projected from the shared context.

    Direct Python callers may still supply x_api_key. HTTP requests always
    use their real headers, so a manual caller cannot replace an HTTP key.
    Research surrogates never satisfy this dependency. AUTH-07 owns migration
    of key-only admin endpoints to named sessions with fresh MFA.
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
    if context.auth_method not in ("api_key", "legacy_api_key"):
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
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> AuthenticatedPrincipal:
    """Admin-эндпоинты микросервиса «Прогресс» (spec_progress.md §10,
    Task PROGR-8): «должны требовать API-ключ с ролью ADMIN, а не cookie
    -- админ заходит другим путём, чем обычный аналитик».

    НЕ новая система прав: та же ролевая модель (Role + фабрика
    зависимостей -- паттерн require_capability). Проверяется РОЛЬ, а не
    capability: доступ к админке определяется ИДЕНТИЧНОСТЬЮ (кто вы),
    не тарифом -- полные capabilities internal_analyst админку не
    открывают."""
    if principal.role != Role.ADMIN:
        # DOCLOG-3 (§14.1): авторизационный отказ -- durable audit
        # (псевдоним субъекта, НЕ значение ключа principal_id).
        try:
            from apps.api.identity import subject_pseudonym
            from apps.api.security_audit import record_standard

            record_standard(
                "authz_denied",
                "denied",
                actor_subject=(
                    getattr(principal, "subject_id", None)
                    or subject_pseudonym(getattr(principal, "principal_id", ""))
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
    return principal
