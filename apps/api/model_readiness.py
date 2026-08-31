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

