# apps/api/plans.py
"""
Контракт "Роль / План / Возможности" (Role / Plan / Capability).

Разделяет три оси, которые в текущем Streamlit-приложении смешаны в
одном плоском enum (admin/user/partner):

1. Role       -- платформенные полномочия; не выбирается оболочкой.
2. Plan       -- ТАРИФ. За что заплачено (или не заплачено). Меняется часто,
                 новый план добавляется без изменения кода авторизации.
3. Capability -- ВОЗМОЖНОСТИ. Производится из Plan. Это то, что реально
                 проверяют эндпоинты (Depends(require_capability(...))),
                 а не сама роль или само имя плана.

PLAN_DEFINITIONS -- источник аналитических возможностей; access_registry.py
проверяет известную операцию/этап. Accounts/grants/object/budget enforcement
подключаются отдельно (AUTH-08/11/12). can_train_models -- legacy v1 adapter.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer


# ─────────────────────────────────────────────────────────────
# 1. РОЛЬ -- идентичность/контекст
# ─────────────────────────────────────────────────────────────
class Role(str, Enum):
    ADMIN = "admin"                  # platform role; обе оболочки, MFA в AUTH-05/07
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
REGISTRY_VERSION = "authz-registry/1"
CAPABILITIES_VERSION = 2


class BaselineLimits(BaseModel):
    """Finite policy ceilings, NOT measured capacity/CU pricing (AUTH-14)."""
    model_config = ConfigDict(frozen=True, extra="forbid", json_schema_serialization_defaults_required=True)
    max_rows: int = Field(default=50_000, gt=0, strict=True)
    max_folds: int = Field(default=5, gt=0, strict=True)
    max_horizon: int = Field(default=48, gt=0, strict=True)
    max_seasonal_period: int = Field(default=366, gt=0, strict=True)
    max_models: int = Field(default=3, gt=0, strict=True)


class Capabilities(BaseModel):
    """
    Набор возможностей плана. Именно ЭТИ поля проверяются в коде
    (require_capability("can_train_models")), а не PlanName и не Role --
    так новый тариф с тем же набором прав не требует правки кода.
    """
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    registry_version: Literal["authz-registry/1"] = REGISTRY_VERSION
    capabilities_version: Literal[2] = CAPABILITIES_VERSION
    can_run_baseline_models: bool = Field(False, description="Bounded baseline allowlist; не tuning/custom fit")
    can_tune_models: bool = Field(False, description="Advanced hyperparameter search")
    can_train_custom_models: bool = Field(False, description="Non-baseline/custom fit; не platform-admin permission")
    restricted_stage_ids: frozenset[Literal["scenario", "causal", "decision", "monitoring"]] = frozenset()
    baseline_limits: BaselineLimits = Field(default_factory=BaselineLimits)
    can_train_models: bool = Field(..., description="DEPRECATED v1 advanced API adapter; не baseline permission", deprecated=True)
    can_use_api: bool = Field(..., description="Доступ к публичному API (не только веб)")
    can_save_history: bool = Field(..., description="Сохранение анализов между сессиями")
    can_upload_own_data: bool = Field(..., description="Загрузка собственных файлов (не только демо-датасеты)")
    max_dataset_rows: Optional[int] = Field(None, description="Лимит строк на датасет; None = без лимита")
    max_api_calls_per_month: Optional[int] = Field(None, description="Лимит вызовов API/мес; None = без лимита")
    max_analyses_total: Optional[int] = Field(None, description="Лимит числа анализов за всё время плана (для demo/trial)")
    trial_days: Optional[int] = Field(None, description="Срок действия плана в днях; None = бессрочно")
    watermark_exports: bool = Field(False, description="Добавлять водяной знак на экспортируемые отчёты")

    @field_serializer("restricted_stage_ids")
    def sorted_restrictions(self, value):
        return sorted(value)


# ─────────────────────────────────────────────────────────────
# ИСТОЧНИК ИСТИНЫ: план -> возможности
# ─────────────────────────────────────────────────────────────
PLAN_DEFINITIONS: dict[PlanName, Capabilities] = {
    PlanName.DEMO: Capabilities(
        can_run_baseline_models=True,
        restricted_stage_ids=frozenset({"scenario", "causal", "decision", "monitoring"}),
        baseline_limits=BaselineLimits(max_rows=5_000, max_folds=3, max_horizon=24),
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
        can_run_baseline_models=True,
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
        can_run_baseline_models=True, can_tune_models=True, can_train_custom_models=True,
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
        can_run_baseline_models=True, can_tune_models=True, can_train_custom_models=True,
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


# Explicit legacy staff adapter. Account INTERNAL entitlement moves to AUTH-08;
# this is analytical capability only, never admin/object/tenant authorization.
INTERNAL_CAPABILITIES = Capabilities(
    can_run_baseline_models=True, can_tune_models=True, can_train_custom_models=True,
    can_train_models=True, can_use_api=True, can_save_history=True, can_upload_own_data=True,
)


# ─────────────────────────────────────────────────────────────
# КЛИЕНТ/ПОЛЬЗОВАТЕЛЬ, РЕЗОЛВИТСЯ ИЗ API-КЛЮЧА ИЛИ СЕССИИ ПОРТАЛА
# ─────────────────────────────────────────────────────────────
class AuthenticatedPrincipal(BaseModel):
    """
    Результат резолва API-ключа (/v1/public) или сессии портала (/v1/internal).
    ЗАМЕНА для плоской проверки "ключ валиден/невалиден" в старом auth.py.

    DOCLOG-0 (spec_documentation_logging.md §15): аддитивные поля
    идентичности -- субъект должен иметь СТАБИЛЬНЫЙ БЕЗОПАСНЫЙ ID, НЕ
    значение API-key. AUTH-03: principal_id — безопасный subject_id;
    совместимые маршруты больше не получают секрет. None -- честное отсутствие (старые
    записи реестра без явного subject/tenant -- суррогат вычисляет
    auth.resolve_principal_for_key); scopes -- выданные права policy
    layer'а (каталог apps/api/identity.py::Scope), у ролей без явной
    выдачи -- пусто, не фантазируется.
    """
    principal_id: str
    role: Role
    plan: Optional[PlanName] = None  # None для admin/internal_analyst -- у них нет тарифа как такового
    # ── DOCLOG-0: аддитивная идентичность (None = честное отсутствие) ──
    subject_id: Optional[str] = None
    tenant_id: Optional[str] = None
    scopes: tuple[str, ...] = ()
    # AUTH-03: additive safe context projection, not entitlement authority.
    account_id: Optional[str] = None
    credential_id: Optional[str] = None
    auth_method: Optional[str] = None
    entitlement_version: Optional[int] = None

    @property
    def capabilities(self) -> Capabilities:
        if self.role in (Role.ADMIN, Role.INTERNAL_ANALYST):
            return INTERNAL_CAPABILITIES.model_copy(deep=True)
        if self.plan is None:
            raise ValueError(f"У роли {self.role} нет плана, но capabilities запрошены без явного плана")
        return PLAN_DEFINITIONS[self.plan].model_copy(deep=True)
