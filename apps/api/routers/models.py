# apps/api/routers/models.py
"""
ПРИМЕР: как защищать эндпоинт по ВОЗМОЖНОСТИ, а не по роли/тарифу напрямую.

Это иллюстрация контракта -- реального обучения моделей пока нет
(модуль "Моделирование" ещё не построен, см. docs/MIGRATION_ARCHITECTURE.md,
раздел 9). Когда модуль появится, этот роутер станет реальным, а не
демонстрационным.
"""
from fastapi import APIRouter, Depends

from apps.api.auth import require_capability, get_current_principal
from apps.api.plans import AuthenticatedPrincipal

router = APIRouter()


@router.post(
    "/train",
    dependencies=[Depends(require_capability("can_train_models"))],
)
def train_model(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    """
    Доступно только принципалам, чей план/роль даёт can_train_models=True
    (internal_analyst, admin, тарифы professional/enterprise) -- НЕ demo
    и НЕ starter (см. PLAN_DEFINITIONS в plans.py).
    """
    return {
        "status": "accepted",
        "principal_id": principal.principal_id,
        "message": "Обучение модели запущено (заглушка -- реальный запуск не реализован)",
    }
