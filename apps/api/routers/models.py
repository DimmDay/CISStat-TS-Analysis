# apps/api/routers/models.py
"""
Роутер модуля «Моделирование».

Эндпоинты:
  POST /v1/models/candidates  — пул кандидатов (движок применимости)
  POST /v1/models/train       — обучение модели (заглушка)
"""
import logging
from collections import Counter
from fastapi import APIRouter, Depends, HTTPException

from apps.api.auth import require_capability, get_current_principal
from apps.api.plans import AuthenticatedPrincipal
from apps.api.schemas import (
    CandidatesRequest,
    CandidatesResponse,
    ModelCandidate,
    CandidatesStatistics,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Загрузка спецификации modeling.yaml (один раз при старте) ──────────────
# Ленивая загрузка: спецификация парсится при первом обращении,
# затем кэшируется в модуле. При ошибке — 500 с понятным сообщением.

_spec_cache = None
_SPEC_YAML_PATH = "rules/modeling.yaml"


def _get_spec():
    """Получить спецификацию моделирования (с кэшем)."""
    global _spec_cache
    if _spec_cache is not None:
        return _spec_cache
    try:
        from src.catalog.modeling_spec_loader import ModelingSpec
        _spec_cache = ModelingSpec.from_yaml(_SPEC_YAML_PATH)
        logger.info("Modeling spec loaded: %s", repr(_spec_cache))
        return _spec_cache
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"Спецификация моделирования не найдена: {_SPEC_YAML_PATH}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка загрузки спецификации моделирования: {e}",
        )


def _reset_spec_cache():
    """Сбросить кэш (для тестов)."""
    global _spec_cache
    _spec_cache = None


# ═══════════════════════════════════════════════════════════
# POST /v1/models/candidates
# ═══════════════════════════════════════════════════════════

@router.post(
    "/candidates",
    response_model=CandidatesResponse,
    dependencies=[Depends(require_capability("can_train_models"))],
)
def get_candidates(
    payload: CandidatesRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """
    Получить пул кандидатов для моделирования на основе профиля данных.

    Применяет движок применимости (23 правила, 4 уровня) ко всем 24 моделям
    из 8 семейств. Возвращает модели с уровнем ≥ min_level, исключая
    NOT_APPLICABLE. Baseline-модели включаются всегда.

    Доступно только принципалам с can_train_models=True
    (professional, enterprise, admin, internal_analyst).
    """
    spec = _get_spec()

    # Конвертируем request-схему в DataProfile (Pydantic → Pydantic)
    from src.catalog.modeling_spec_loader import DataProfile

    profile = DataProfile(
        n_observations=payload.profile.n_observations,
        n_series=payload.profile.n_series,
        n_exogenous=payload.profile.n_exogenous,
        is_regular=payload.profile.is_regular,
        frequency=payload.profile.frequency,
        has_seasonality=payload.profile.has_seasonality,
        seasonal_periods=payload.profile.seasonal_periods,
        is_stationary_or_diffable=payload.profile.is_stationary_or_diffable,
        is_cointegrated=payload.profile.is_cointegrated,
        has_negative_values=payload.profile.has_negative_values,
        has_volatility_clustering=payload.profile.has_volatility_clustering,
        domain=payload.profile.domain,
        missing_ratio=payload.profile.missing_ratio,
        outlier_ratio=payload.profile.outlier_ratio,
        has_holidays=payload.profile.has_holidays,
        gpu_available=payload.profile.gpu_available,
        feature_engineering_applied=payload.profile.feature_engineering_applied,
    )

    # Валидация min_level
    valid_levels = {"RECOMMENDED", "CONDITIONALLY_APPLICABLE",
                    "NOT_RECOMMENDED", "NOT_APPLICABLE"}
    min_level = payload.min_level or "CONDITIONALLY_APPLICABLE"
    if min_level not in valid_levels:
        raise HTTPException(
            status_code=422,
            detail=f"Некорректный min_level: '{min_level}'. Допустимые: {valid_levels}",
        )

    # Получаем пул кандидатов
    candidate_results = spec.get_candidate_pool(profile, min_level=min_level)

    # Конвертируем в response-схему
    candidates = [
        ModelCandidate(
            model_id=r.model_id,
            model_name=r.model_name,
            family_id=r.family_id,
            level=r.level,
            rule_id=r.rule_id,
            message=r.message,
            rank=r.rank,
        )
        for r in candidate_results
    ]

    # Статистика
    level_counts = Counter(c.level for c in candidates)
    statistics = CandidatesStatistics(
        total_candidates=len(candidates),
        by_level=dict(level_counts),
        total_models_in_spec=spec.total_model_count(),
    )

    return CandidatesResponse(
        candidates=candidates,
        statistics=statistics,
        spec_version=spec.metadata.version,
    )


# ═══════════════════════════════════════════════════════════
# POST /v1/models/train  (заглушка — из предыдущей версии)
# ═══════════════════════════════════════════════════════════

@router.post(
    "/train",
    dependencies=[Depends(require_capability("can_train_models"))],
)
def train_model(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
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
