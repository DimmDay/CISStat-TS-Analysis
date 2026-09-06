# apps/api/model_impls/prophet.py
"""
Prophet — аддитивная декомпозируемая модель Facebook/Meta:
y(t) = g(t) (тренд) + s(t) (Fourier-сезонность) + h(t) (праздники) + ε(t).

Контракт этого модуля отличается от остальных model_impls тем, что Prophet
работает с реальными календарными датами (``ds``), а не с положением в
массиве. Даты для точного EDA BacktestPlan уже доступны как
``ModelExecutionRequest.train_timestamps``/``future_timestamps`` (Task 122)
и передаются сюда как есть -- это и есть "строгий future-known contract" из
Task 124: прогнозные даты не переизобретаются (не infer_freq, не
make_future_dataframe), а берутся из уже зафиксированного EDA-плана.

Праздники подключаются через ``Prophet.add_country_holidays`` -- это
календарная функция (даты праздников заданной страны известны заранее на
любой горизонт), поэтому она не создаёт утечки будущего в train. Модель
создаётся заново на каждый fold (см. apps/api/backtesting.py::run_backtest_plan
-- fit_policy="per_train_fold"), поэтому holidays всегда fold-local: нет
переиспользования объекта Prophet между train fold'ами.

Произвольные пользовательские регрессоры (train_features/future_features)
сознательно НЕ подключены в Task 124: platform-уровня fold-local FeaturePlan
для экзогенных признаков появится в Task 126. Сейчас единственный
поддерживаемый "regressor" -- встроенный календарь праздников Prophet.

Bounded tuning (Task 124): changepoint_prior_scale, seasonality_prior_scale,
seasonality_mode -- см. rules/modeling.yaml::structural.prophet.param_space.
Никакого собственного prophet.diagnostics.cross_validation второго CV-контура
здесь нет -- ровно один fit + один predict на fold, который передаёт платформа.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence

import pandas as pd

from apps.api.schemas import BacktestMetrics
from apps.api.model_impls._common import safe_backtest, train_test_split
from apps.api.model_impls._metrics import compute_metrics


logger = logging.getLogger(__name__)


# Страны, для которых Prophet/holidays поставляют календарь "из коробки".
# Намеренно ограниченный bounded набор (а не произвольная строка) -- как и
# param_space тюнинга, это защита от неисполнимых/опечатанных значений.
SUPPORTED_COUNTRY_HOLIDAYS = frozenset({
    "RU", "US", "GB", "DE", "FR", "CN", "UA", "KZ", "BY", "IT", "ES", "BR", "IN",
})

_DEFAULT_SEASONAL_FREQ = {7: "D", 52: "W", 12: "MS", 4: "QS", 1: "YS"}


def _quiet_cmdstanpy() -> None:
    """cmdstanpy пишет INFO 'Chain [1] start/done processing' на каждый fit.

    При десятках fold*trial это заметно засоряет тестовый вывод; это чисто
    логирование, не влияет на результат -- глушим один раз до уровня WARNING.
    """
    logging.getLogger("cmdstanpy").setLevel(logging.WARNING)


def _prophet_fit_predict(
    y_train: List[float],
    horizon: int,
    train_timestamps: Sequence[str],
    future_timestamps: Sequence[str],
    changepoint_prior_scale: float = 0.05,
    seasonality_prior_scale: float = 10.0,
    seasonality_mode: str = "additive",
    country_holidays: Optional[str] = None,
) -> tuple[List[float], List[float], List[float]]:
    """Обучить Prophet на y_train с реальными train_timestamps, предсказать
    ровно те даты, что перечислены в future_timestamps (длина == horizon).

    Возвращает (forecast, lower80, upper80) -- Prophet's default interval_width
    (0.80) не тюнится в Task 124 (bounded scope: только 3 параметра из
    modeling.yaml). Строгий future-known contract: ``future_timestamps``
    передаются платформой (уже зафиксированы EDA BacktestPlan), а не
    переоцениваются здесь через infer_freq/make_future_dataframe.
    """
    if seasonality_mode not in {"additive", "multiplicative"}:
        raise ValueError(f"Unsupported Prophet seasonality_mode: {seasonality_mode!r}")
    if seasonality_mode == "multiplicative" and any(value <= 0 for value in y_train):
        raise ValueError("multiplicative Prophet seasonality requires strictly positive data")
    if country_holidays is not None and country_holidays not in SUPPORTED_COUNTRY_HOLIDAYS:
        raise ValueError(f"Unsupported Prophet country_holidays: {country_holidays!r}")
    if len(train_timestamps) != len(y_train):
        raise ValueError(
            "Prophet requires one train_timestamp per target observation "
            f"(got {len(train_timestamps)} timestamps for {len(y_train)} points)"
        )
    if len(future_timestamps) != horizon:
        raise ValueError(
            f"Prophet requires exactly horizon={horizon} future_timestamps "
            f"(got {len(future_timestamps)})"
        )
    if not y_train:
        raise ValueError("Prophet requires at least one training observation")

    _quiet_cmdstanpy()
    from prophet import Prophet

    train_ds = pd.to_datetime(list(train_timestamps))
    future_ds = pd.to_datetime(list(future_timestamps))
    frame = pd.DataFrame({"ds": train_ds, "y": [float(value) for value in y_train]})

    model = Prophet(
        changepoint_prior_scale=float(changepoint_prior_scale),
        seasonality_prior_scale=float(seasonality_prior_scale),
        seasonality_mode=seasonality_mode,
    )
    if country_holidays is not None:
        # Календарная функция праздников: даты известны заранее на любой
        # горизонт, поэтому fold-local вызов не создаёт утечки будущего.
        model.add_country_holidays(country_name=country_holidays)
    model.fit(frame)

    forecast = model.predict(pd.DataFrame({"ds": future_ds}))
    yhat = forecast["yhat"].astype(float).tolist()
    lower = forecast["yhat_lower"].astype(float).tolist()
    upper = forecast["yhat_upper"].astype(float).tolist()
    return yhat, lower, upper


def _prophet_backtest_impl(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """Чистая реализация для legacy synthetic-demo эндпоинта
    (POST /v1/models/backtest, без реальных дат в profile) -- та же
    сигнатура, что и у остальных model_impls. Даты здесь синтетические
    (данные и так сгенерированы), реальный fold-local контракт с
    платформенными train_timestamps/future_timestamps используется в
    сессионном workflow через _prophet_executor в model_execution.py.
    """
    y_train, y_test = train_test_split(series, train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)

    freq = _DEFAULT_SEASONAL_FREQ.get(int(seasonal_period), "D")
    dates = pd.date_range("2000-01-01", periods=len(series), freq=freq)
    train_timestamps = [value.isoformat() for value in dates[: len(y_train)]]
    future_timestamps = [value.isoformat() for value in dates[len(y_train): len(series)]]

    y_pred, _lower, _upper = _prophet_fit_predict(
        y_train=y_train, horizon=len(y_test),
        train_timestamps=train_timestamps, future_timestamps=future_timestamps,
    )
    return compute_metrics(y_test, y_pred, y_train)


def run_prophet_backtest(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """Prophet: аддитивный тренд + Fourier-сезонность + fold-local holidays."""
    return safe_backtest(
        _prophet_backtest_impl,
        series, train_ratio, seasonal_period, "prophet",
    )
