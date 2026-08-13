# apps/api/model_impls/arima.py
"""
ARIMA и Auto-ARIMA — авторегрессия + интеграция + скользящее среднее.

Две реализации:
- run_arima_backtest: фиксированный порядок (1, 1, 1) — стандартный
  «обычный» ARIMA, разумный дефолт для большинства бизнес-рядов.
- run_auto_arima_backtest: grid search по (p, d, q) с AIC-критерием.
  Реализован через statsmodels (НЕ pmdarima) — grid over
  p in {0,1,2}, d in {0,1}, q in {0,1,2} = 18 моделей. Выбираем
  модель с минимальным AIC, затем forecast.

Контракт: на входе list[float], на выходе BacktestMetrics.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import pandas as pd

from apps.api.schemas import BacktestMetrics
from apps.api.model_impls._common import safe_backtest, train_test_split
from apps.api.model_impls._metrics import compute_metrics


logger = logging.getLogger(__name__)


# Дефолтный порядок ARIMA — (p=1, d=1, q=1). Стандартный «обычный» ARIMA:
# 1 авторегрессионный член, 1 differencing, 1 скользящее среднее. Подходит
# для большинства бизнес-рядов с трендом и слабой автокорреляцией остатков.
DEFAULT_ARIMA_ORDER: Tuple[int, int, int] = (1, 1, 1)


# Grid для Auto-ARIMA: 18 комбинаций (3 * 2 * 3). Большая часть рядов
# даёт сходимость за 1-2 секунды на 20-50 точках. Если ряд короче —
# часть порядков упадёт с ValueError, что нормально (пропускаем).
AUTO_ARIMA_GRID: List[Tuple[int, int, int]] = [
    (p, d, q)
    for p in (0, 1, 2)
    for d in (0, 1)
    for q in (0, 1, 2)
]


def _arima_fit_predict(
    y_train: List[float],
    n_test: int,
    order: Tuple[int, int, int],
) -> List[float]:
    """Обучить ARIMA(y_train, order=order), forecast n_test шагов.

    Использует statsmodels.tsa.arima.model.ARIMA (новый API с 0.12+,
    заменяет statsmodels.tsa.arima_model.ARMA — deprecated).
    """
    from statsmodels.tsa.arima.model import ARIMA

    # ARIMA требует индекс с частотой. Создаём RangeIndex — ARIMA его примет.
    idx = pd.RangeIndex(start=0, stop=len(y_train))
    train = pd.Series(y_train, index=idx)

    model = ARIMA(train, order=order)
    fitted = model.fit()
    forecast = fitted.forecast(steps=n_test)
    return list(forecast)


def _arima_backtest_impl(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,  # ignored for non-seasonal ARIMA
    order: Tuple[int, int, int] = DEFAULT_ARIMA_ORDER,
) -> BacktestMetrics:
    """Чистая реализация ARIMA. seasonal_period игнорируется
    (для SARIMA нужна statsmodels.tsa.statespace.SARIMAX — Phase 6-P1)."""
    y_train, y_test = train_test_split(series, train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)

    y_pred = _arima_fit_predict(
        y_train=y_train,
        n_test=len(y_test),
        order=order,
    )
    return compute_metrics(y_test, y_pred, y_train)


def _auto_arima_select_order(
    y_train: List[float],
) -> Tuple[int, int, int]:
    """Выбрать оптимальный (p, d, q) по AIC.

    Перебирает AUTO_ARIMA_GRID, обучает ARIMA для каждого порядка,
    берёт с минимальным AIC. Если ВСЕ порядки упали (короткий ряд,
    константные данные) — fallback на DEFAULT_ARIMA_ORDER.

    Логирует выбранный порядок для отладки (DEBUG level).
    """
    from statsmodels.tsa.arima.model import ARIMA

    best_aic: Optional[float] = None
    best_order: Tuple[int, int, int] = DEFAULT_ARIMA_ORDER

    idx = pd.RangeIndex(start=0, stop=len(y_train))
    train = pd.Series(y_train, index=idx)

    for order in AUTO_ARIMA_GRID:
        try:
            model = ARIMA(train, order=order)
            fitted = model.fit()
            aic = fitted.aic
            if best_aic is None or aic < best_aic:
                best_aic = aic
                best_order = order
        except Exception as exc:
            # Этот порядок не сошёлся — пропускаем, пробуем следующий.
            logger.debug("ARIMA order %s failed (%s), skipping", order, exc.__class__.__name__)
            continue

    logger.debug(
        "Auto-ARIMA selected order %s (AIC=%s, train_len=%d)",
        best_order, best_aic, len(y_train),
    )
    return best_order


def _auto_arima_backtest_impl(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,  # ignored — non-seasonal Auto-ARIMA
) -> BacktestMetrics:
    """Чистая реализация Auto-ARIMA: grid search по (p,d,q) с AIC."""
    y_train, y_test = train_test_split(series, train_ratio)
    if not y_train or not y_test:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)

    best_order = _auto_arima_select_order(y_train)
    y_pred = _arima_fit_predict(
        y_train=y_train,
        n_test=len(y_test),
        order=best_order,
    )
    return compute_metrics(y_test, y_pred, y_train)


def run_arima_backtest(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """ARIMA(1,1,1): фиксированный порядок.

    Сезонность НЕ учитывается (это SARIMA — Phase 6-P1). Если ряд
    явным образом сезонный, ARIMA(1,1,1) будет работать хуже Seasonal
    Naive, но это валидный baseline для P0.

    Edge cases, обрабатываемые safe_backtest:
    - Ряд с длиной <= order[1] (после differencing не остаётся точек) →
      ValueError → Naive fallback.
    - Константный ряд → LinAlgError → Naive fallback.
    """
    return safe_backtest(
        _arima_backtest_impl,
        series, train_ratio, seasonal_period, "arima",
    )


def run_auto_arima_backtest(
    series: List[float],
    train_ratio: float,
    seasonal_period: int,
) -> BacktestMetrics:
    """Auto-ARIMA: grid search по (p,d,q) ∈ {0,1,2} × {0,1} × {0,1,2} = 18 моделей.

    Использует AIC для выбора лучшего порядка. Реализован через statsmodels
    (НЕ pmdarima), чтобы не добавлять тяжёлую зависимость в Docker образ.
    По качеству — уступает pmdarima на сложных рядах, но для Phase 6-P0
    (демонстрация реальной ARIMA-модели) — достаточно.

    Время: ~1-2 сек на 24-72 точках (18 fit'ов). На больших рядах grid
    search может занять 10+ секунд — для Phase 6-P1+ оптимизация: skip
    не-стационарных порядков, parallel fit, etc.
    """
    return safe_backtest(
        _auto_arima_backtest_impl,
        series, train_ratio, seasonal_period, "arima_auto",
    )
