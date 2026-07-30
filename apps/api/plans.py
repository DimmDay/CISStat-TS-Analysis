# apps/api/plans.py
"""
Контракт "Роль / План / Возможности" (Role / Plan / Capability).

Разделяет три оси, которые в текущем Streamlit-приложении смешаны в
одном плоском enum (admin/user/partner):

1. Role       -- ИДЕНТИЧНОСТЬ. Кто вы. Меняется редко, определяет КОНТЕКСТ
                 (embedded-портал vs standalone), не конкретные лимиты.
2. Plan       -- ТАРИФ. За что заплачено (или не заплачено). Меняется часто,
                 новый план добавляется без изменения кода авторизации.
3. Capability -- ВОЗМОЖНОСТИ. Производится из Plan. Это то, что реально
                 проверяют эндпоинты (Depends(require_capability(...))),
                 а не сама роль или само имя плана.

ВАЖНО: словарь PLAN_DEFINITIONS -- источник истины. Добавление нового
тарифа = новая запись в этом словаре, без изменений в auth.py или роутерах.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────
# 1. РОЛЬ -- идентичность/контекст
# ─────────────────────────────────────────────────────────────
class Role(str, Enum):
    ADMIN = "admin"                  # администратор платформы CISStat (embedded)
    INTERNAL_ANALYST = "internal_analyst"  # сотрудник CISStat (embedded), было "user"
    EXTERNAL_USER = "external_user"  # любой внешний клиент (standalone) -- ОДНА роль,
                                      # тариф определяется отдельно через Plan


# ─────────────────────────────────────────────────────────────
# 2. ТАРИФНЫЙ ПЛАН -- коммерческая сущность, применяется к EXTERNAL_USER
# ─────────────────────────────────────────────────────────────
class PlanName(str, Enum):
    DEMO = "demo"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


# ─────────────────────────────────────────────────────────────
# 3. ВОЗМОЖНОСТИ -- то, что реально проверяют эндпоинты
# ─────────────────────────────────────────────────────────────
class Capabilities(BaseModel):
    """
    Набор возможностей плана. Именно ЭТИ поля проверяются в коде
    (require_capability("can_train_models")), а не PlanName и не Role --
    так новый тариф с тем же набором прав не требует правки кода.
    """
    can_train_models: bool = Field(..., description="Доступ к обучению моделей прогнозирования")
    can_use_api: bool = Field(..., description="Доступ к публичному API (не только веб)")
    can_save_history: bool = Field(..., description="Сохранение анализов между сессиями")
    can_upload_own_data: bool = Field(..., description="Загрузка собственных файлов (не только демо-датасеты)")
    max_dataset_rows: Optional[int] = Field(None, description="Лимит строк на датасет; None = без лимита")
    max_api_calls_per_month: Optional[int] = Field(None, description="Лимит вызовов API/мес; None = без лимита")
    max_analyses_total: Optional[int] = Field(None, description="Лимит числа анализов за всё время плана (для demo/trial)")
    trial_days: Optional[int] = Field(None, description="Срок действия плана в днях; None = бессрочно")
    watermark_exports: bool = Field(False, description="Добавлять водяной знак на экспортируемые отчёты")


# ─────────────────────────────────────────────────────────────
# ИСТОЧНИК ИСТИНЫ: план -> возможности
# ─────────────────────────────────────────────────────────────
PLAN_DEFINITIONS: dict[PlanName, Capabilities] = {
    PlanName.DEMO: Capabilities(
        can_train_models=False,
        can_use_api=False,
        can_save_history=False,
        can_upload_own_data=True,
        max_dataset_rows=5_000,
        max_api_calls_per_month=0,
        max_analyses_total=10,
        trial_days=14,
        watermark_exports=True,
    ),
    PlanName.STARTER: Capabilities(
        can_train_models=False,
        can_use_api=True,
        can_save_history=True,
        can_upload_own_data=True,
        max_dataset_rows=50_000,
        max_api_calls_per_month=1_000,
        max_analyses_total=None,
        trial_days=None,
        watermark_exports=False,
    ),
    PlanName.PROFESSIONAL: Capabilities(
        can_train_models=True,
        can_use_api=True,
        can_save_history=True,
        can_upload_own_data=True,
        max_dataset_rows=None,
        max_api_calls_per_month=50_000,
        max_analyses_total=None,
        trial_days=None,
        watermark_exports=False,
    ),
    PlanName.ENTERPRISE: Capabilities(
        can_train_models=True,
        can_use_api=True,
        can_save_history=True,
        can_upload_own_data=True,
        max_dataset_rows=None,
        max_api_calls_per_month=None,  # индивидуальные условия/SLA
        max_analyses_total=None,
        trial_days=None,
        watermark_exports=False,
    ),
}


# ─────────────────────────────────────────────────────────────
# КЛИЕНТ/ПОЛЬЗОВАТЕЛЬ, РЕЗОЛВИТСЯ ИЗ API-КЛЮЧА ИЛИ СЕССИИ ПОРТАЛА
# ─────────────────────────────────────────────────────────────
class AuthenticatedPrincipal(BaseModel):
    """
    Результат резолва API-ключа (/v1/public) или сессии портала (/v1/internal).
    ЗАМЕНА для плоской проверки "ключ валиден/невалиден" в старом auth.py.
    """
    principal_id: str
    role: Role
    plan: Optional[PlanName] = None  # None для admin/internal_analyst -- у них нет тарифа как такового

    @property
    def capabilities(self) -> Capabilities:
        if self.role in (Role.ADMIN, Role.INTERNAL_ANALYST):
            # Сотрудники CISStat: полные возможности без тарифных ограничений.
            return Capabilities(
                can_train_models=True,
                can_use_api=True,
                can_save_history=True,
                can_upload_own_data=True,
                max_dataset_rows=None,
                max_api_calls_per_month=None,
                max_analyses_total=None,
                trial_days=None,
                watermark_exports=False,
            )
        if self.plan is None:
            raise ValueError(f"У роли {self.role} нет плана, но capabilities запрошены без явного плана")
        return PLAN_DEFINITIONS[self.plan]
