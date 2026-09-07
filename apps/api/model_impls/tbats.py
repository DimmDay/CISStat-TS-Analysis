# apps/api/model_impls/tbats.py
"""
TBATS (Trigonometric, Box-Cox transform, ARMA errors, Trend, Seasonal
components) через Nixtla StatsForecast -- зафиксированная версия/API
(Task 125, п.1): ``statsforecast==2.1.1``, класс ``statsforecast.models.TBATS``.

Мы намеренно используем явный ``TBATS`` (а не ``AutoTBATS``): AutoTBATS
запускает СВОЙ внутренний AIC-перебор структурных спецификаций (Box-Cox
вкл/выкл, trend, damped trend, ARMA errors) на каждый fit -- непредсказуемое
по времени исполнение внутри уже подконтрольного bounded tuning grid платформы
("Бюджетированное обучение и tuning без proxy timeout" -- Task 125, п.3).
Явный ``TBATS`` с конкретными флагами даёт один детерминированный fit на
комбинацию параметров -- ровно то же свойство, что и у остальных моделей
registry (ETS/ARIMA с явными order/trend, а не двойной auto-поиск поверх
auto-поиска). Bounded tuning grid (``use_boxcox`` × ``trend_spec``) сам
реализует то структурное решение, которое иначе делал бы AutoTBATS -- но
детерминированно и в рамках уже существующего платформенного grid-движка.

Множественные сезонные периоды (Task 125, п.2, спектральный hand-off):
``season_length`` в statsforecast нативно принимает ``List[int]``
(например [7, 365] для daily+yearly) -- ``request.params["seasonal_periods"]``
(см. apps/api/backtesting.py::run_backtest_plan) передаётся сюда как есть.
Если платформа не передала множественный список (params пуст), используется
единственный ``request.seasonal_period`` -- совместимо с остальными моделями.

Box-Cox только внутри train-fold (Task 125, п.4): TBATS создаётся заново на
каждый fold (fit_policy="per_train_fold", как и у всех моделей registry) и
Box-Cox lambda оценивается статsforecast'ом внутри ``.fit(y_train)`` -- по
конструкции не видит test/future данные.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from apps.api.schemas import BacktestMetrics
from apps.api.model_impls._common import safe_backtest, train_test_split
from apps.api.model_impls._metrics import compute_metrics


# "damped trend без trend" -- структурно невозможная комбинация в TBATS
# (statsforecast сам бросает ValueError). Вместо двух заведомо провальных
# ячеек в bounded tuning grid комбинация trend/damped закодирована одним
# полем -- каждая точка grid соответствует реальной, различной TBATS-модели.
_TREND_SPECS = {
    "none": {"use_trend": False, "use_damped_trend": False},
    "trend": {"use_trend": True, "use_damped_trend": False},
    "damped_trend": {"use_trend": True, "use_damped_trend": True},
}


def _resolve_seasonal_periods(
    seasonal_period: int, seasonal_periods: Optional[Sequence[int]],
) -> List[int]:
    if seasonal_periods:
        periods = [int(value) for value in seasonal_periods]
    else:
        periods = [int(seasonal_period)]
    if not periods or any(value < 1 for value in periods):
        raise ValueError(f"TBATS seasonal_periods должны быть положительными: {periods}")
    return periods


def _tbats_fit_predict(
    y_train: List[float],
    horizon: int,
    seasonal_period: int,
    seasonal_periods: Optional[Sequence[int]] = None,
    use_boxcox: bool = True,
    trend_spec: str = "damped_trend",
    use_arma_errors: bool = False,
) -> tuple[List[float], List[float], List[float]]:
    """Обучить TBATS на y_train, предсказать ровно horizon шагов вперёд.

    Возвращает (forecast, lower80, upper80) -- statsforecast TBATS.predict
    поддерживает произвольный `level`; здесь фиксирован 80% (тот же default
    interval_width, что и у Prophet в Task 124, для единообразия Model Card).
    """
    if trend_spec not in _TREND_SPECS:
        raise ValueError(f"Unsupported TBATS trend_spec: {trend_spec!r}")
    if not y_train:
        raise ValueError("TBATS requires at least one training observation")
    periods = _resolve_seasonal_periods(seasonal_period, seasonal_periods)

    from statsforecast.models import TBATS

    model = TBATS(
        season_length=periods if len(periods) > 1 else periods[0],
        use_boxcox=use_boxcox,
        use_arma_errors=use_arma_errors,
        **_TREND_SPECS[trend_spec],
    )
    import numpy as np

    model.fit(np.asarray(y_train, dtype=float))
    forecast = model.predict(h=horizon, level=[80])
    yhat = [float(value) for value in forecast["mean"]]
    lower = [float(value) for value in forecast["lo-80"]]
    upper = [float(value) for value in forecast["hi-80"]]
    return yhat, lower, upper


def _tbats_backtest_impl(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """Legacy synthetic-demo эндпоинт (POST /v1/models/backtest) -- одиночный
    период (профиль без multi-period spectral hand-off), та же сигнатура,
    что и у остальных model_impls."""
    y_train, y_test = train_test_split(series, train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)

    y_pred, _lower, _upper = _tbats_fit_predict(
        y_train=y_train, horizon=len(y_test), seasonal_period=seasonal_period,
    )
    return compute_metrics(y_test, y_pred, y_train)


def run_tbats_backtest(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """TBATS: Box-Cox + тригонометрическая сезонность + (damped) тренд + ARMA errors."""
    return safe_backtest(
        _tbats_backtest_impl,
        series, train_ratio, seasonal_period, "tbats",
    )
