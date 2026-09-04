"""Единый capability-контракт моделей для всех стадий Modeling.

Каталог ``rules/modeling.yaml`` описывает методологический охват платформы,
но наличие модели в каталоге не означает наличие production-реализации.
Этот набор намеренно отделён от статистической применимости.
"""

PRODUCTION_BACKTEST_MODEL_IDS = frozenset({
    "naive",
    "seasonal_naive",
    "drift",
    "mean",
    "ets",
    "ets_damped",
    "theta",
    "arima",
    "arima_auto",
})

PRODUCTION_TUNING_MODEL_IDS = frozenset({"ets", "ets_damped", "arima"})
# Session diagnostics consumes signed OOF residuals and is model-agnostic.
PRODUCTION_DIAGNOSTICS_MODEL_IDS = PRODUCTION_BACKTEST_MODEL_IDS

MODELING_CAPABILITY_CONTRACT_VERSION = "model-capabilities-v1"
MODELING_STAGE_IDS = (
    "problem_definition", "data_structure", "constraint_mapping",
    "candidate_generation", "baseline_estimation", "backtest", "tuning",
    "diagnostics", "comparison", "selection", "model_card",
)

_GLOBAL_STAGES = frozenset(MODELING_STAGE_IDS[:4])
_BACKTEST_DOWNSTREAM_STAGES = frozenset({
    "backtest", "diagnostics", "comparison", "selection", "model_card",
})


def _capability(status: str, *, required: bool, action: str | None, reason: str) -> dict:
    return {
        "status": status,
        "required": required,
        "action": action,
        "reason": reason,
    }


def model_stage_capabilities(
    model_id: str,
    family_id: str,
    *,
    included: bool = True,
    blocking_reason: str | None = None,
) -> dict[str, dict]:
    """Return a complete 11-stage matrix without claiming fake implementations."""
    production_ready = model_id in PRODUCTION_BACKTEST_MODEL_IDS
    blocked = production_ready and (not included or blocking_reason is not None)
    matrix: dict[str, dict] = {}
    for stage_id in MODELING_STAGE_IDS:
        if stage_id in _GLOBAL_STAGES:
            matrix[stage_id] = _capability(
                "available", required=True, action=None,
                reason="Общая стадия контекста и применимости.",
            )
        elif stage_id == "baseline_estimation":
            if family_id == "baselines" and blocked:
                matrix[stage_id] = _capability(
                    "blocked", required=True, action="backtest",
                    reason=blocking_reason or "Baseline заблокирован текущим профилем.",
                )
            elif family_id == "baselines":
                matrix[stage_id] = _capability(
                    "available", required=True, action="backtest",
                    reason="Baseline рассчитывается автоматически на точном OOF cohort.",
                )
            else:
                matrix[stage_id] = _capability(
                    "not_applicable", required=False, action=None,
                    reason="Стадия предназначена только для baseline-семейства.",
                )
        elif stage_id == "tuning":
            if model_id in PRODUCTION_TUNING_MODEL_IDS and blocked:
                matrix[stage_id] = _capability(
                    "blocked", required=False, action="tune",
                    reason=blocking_reason or "Tuning заблокирован текущим профилем.",
                )
            elif model_id in PRODUCTION_TUNING_MODEL_IDS:
                matrix[stage_id] = _capability(
                    "available", required=False, action="tune",
                    reason="Production tuning использует тот же EDA BacktestPlan.",
                )
            elif production_ready:
                matrix[stage_id] = _capability(
                    "not_applicable", required=False, action=None,
                    reason="Отдельный tuning для этой production-модели не требуется.",
                )
            else:
                matrix[stage_id] = _capability(
                    "not_implemented", required=False, action=None,
                    reason="Production-модель и tuning ещё не реализованы.",
                )
        elif stage_id in _BACKTEST_DOWNSTREAM_STAGES:
            action = "diagnostics" if stage_id == "diagnostics" else (
                "backtest" if stage_id == "backtest" else None
            )
            if blocked:
                matrix[stage_id] = _capability(
                    "blocked", required=stage_id == "backtest", action=action,
                    reason=blocking_reason or "Модель заблокирована текущим профилем.",
                )
            elif production_ready:
                matrix[stage_id] = _capability(
                    "available", required=stage_id == "backtest", action=action,
                    reason="Поддерживается подписанными OOF-артефактами session workflow.",
                )
            else:
                matrix[stage_id] = _capability(
                    "not_implemented", required=False, action=None,
                    reason="Production backtest отсутствует; downstream-артефакты недоступны.",
                )
    return matrix


def available_model_actions(model_id: str) -> list[str]:
    """Return only actions backed by a real production implementation."""
    actions: list[str] = []
    if model_id in PRODUCTION_BACKTEST_MODEL_IDS:
        actions.append("backtest")
    if model_id in PRODUCTION_TUNING_MODEL_IDS:
        actions.append("tune")
    if model_id in PRODUCTION_DIAGNOSTICS_MODEL_IDS:
        actions.append("diagnostics")
    return actions
