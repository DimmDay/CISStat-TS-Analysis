"""Единый реестр реально запускаемых backend-бэктестов.

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
PRODUCTION_DIAGNOSTICS_MODEL_IDS = frozenset({"ets", "ets_damped", "arima"})


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
