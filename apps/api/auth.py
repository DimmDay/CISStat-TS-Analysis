# apps/api/auth.py
"""
Авторизация: API-ключ -> AuthenticatedPrincipal (роль + план) -> Capabilities.

ЗАМЕНА для прежней версии, где ключ был просто "валиден/невалиден" без
привязки к плану. Теперь каждый ключ резолвится в конкретного клиента
с ролью и (для внешних) тарифным планом -- это то, что реально позволяет
проверять "can_train_models" и т.п., а не просто пускать/не пускать.

ЗАГЛУШКА: сопоставление ключ -> principal сейчас статичное (переменная
окружения в формате "ключ:роль:план,ключ:роль:план"). Для продакшена --
таблица клиентов в БД (нужна ради биллинга/лимитов использования,
см. открытый вопрос "Биллинг/лимиты для публичного API" в
docs/MIGRATION_ARCHITECTURE.md), но контракт зависимостей
(Depends(get_current_principal), Depends(require_capability(...)))
не изменится при переходе на неё.
"""
import os

from fastapi import Depends, Header, HTTPException, status

from apps.api.plans import AuthenticatedPrincipal, Capabilities, PlanName, Role


def _parse_key_registry() -> dict[str, AuthenticatedPrincipal]:
    """
    Формат переменной окружения CISSTAT_API_KEYS:
    "key1:external_user:starter,key2:external_user:demo,key3:internal_analyst:"
    (план пуст для admin/internal_analyst -- у них capabilities не тарифные).
    """
    raw = os.environ.get("CISSTAT_API_KEYS", "")
    registry: dict[str, AuthenticatedPrincipal] = {}
    for entry in filter(None, raw.split(",")):
        parts = entry.split(":")
        if len(parts) != 3:
            continue
        key, role_str, plan_str = parts
        try:
            role = Role(role_str)
            plan = PlanName(plan_str) if plan_str else None
            registry[key] = AuthenticatedPrincipal(principal_id=key, role=role, plan=plan)
        except ValueError:
            # Некорректная запись в конфиге -- пропускаем, а не роняем весь сервис.
            continue
    return registry


def get_current_principal(x_api_key: str = Header(...)) -> AuthenticatedPrincipal:
    """Резолвит API-ключ в аутентифицированного принципала (роль + план)."""
    registry = _parse_key_registry()
    if not registry:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CISSTAT_API_KEYS не настроены на сервере",
        )
    principal = registry.get(x_api_key)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный API-ключ")
    return principal


def require_capability(capability_name: str):
    """
    Фабрика зависимостей для защиты конкретных эндпоинтов по возможности,
    а не по роли/плану напрямую -- например:

        @router.post("/models/train", dependencies=[Depends(require_capability("can_train_models"))])

    Если новый тариф получит can_train_models=True -- эндпоинт станет
    доступен ему автоматически, без правки роутера.
    """
    def _checker(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> AuthenticatedPrincipal:
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
def require_api_key(principal: AuthenticatedPrincipal = Depends(get_current_principal)) -> str:
    return principal.principal_id
