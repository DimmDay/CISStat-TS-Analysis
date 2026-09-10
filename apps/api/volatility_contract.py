# apps/api/volatility_contract.py
"""Task 134 -- Volatility Objective Contract (каркас GARCH/EGARCH, Tasks 135-136).

Инфраструктурный контракт волатильности, независимый от HTTP/session-кода
(тот же уровень, что multivariate_contract.py Task 131).  Постановка
docs/modeling_task_list.md::Task 134 и точки реализации:

1. **Явное преобразование цены в returns без скрытого выбора** --
   ``price_to_returns``: ``method`` -- ОБЯЗАТЕЛЬНЫЙ keyword-аргумент
   ({``"log"``, ``"simple"``}); вызов без него невозможен by construction,
   неизвестный метод отклоняется.  ``VolatilityTarget`` (зеркало
   EndogenousSystem Task 131) хранит цены, returns и ЗАЯВЛЕННЫЙ метод;
   внутренняя согласованность защищена анти-тампер проверкой: returns
   обязаны воспроизводиться из цен заявленным методом бит-в-бит.
2. **Цель -- условная дисперсия, а не уровень исходного ряда** --
   ``realized_variance_proxy``: proxy объявляется явно (обязательный
   keyword, {"squared_returns"}); ``volatility_cohort_contract``
   декларирует target_kind="conditional_variance" и возвращает схему
   OOF-точки движка, где ``actual`` = realized proxy (squared return
   тест-окна), ``predicted`` = прогноз дисперсии.
3. **Primary metric: QLIKE; дополнительные ошибки по realized proxy** --
   ``compute_volatility_metrics``: QLIKE в robust-форме Паттона (2011)
   mean(log(sigma2_hat) + sigma2/sigma2_hat) -- ранжирование-эквивалентна
   классической форме sigma2/sigma2_hat - log(sigma2/sigma2_hat) - 1
   (оракул-тест связывает эквивалентность); форма robust устойчива к
   зашумлённому proxy и допускает нулевой realized (sigma2=0), но
   ТРЕБУЕТ строго положительный прогноз дисперсии -- fail-closed без
   clamp-подмен.  Дополнительно RMSE/MAE в шкале дисперсии.
   ``aggregate_volatility_metrics`` -- взвешивание по n_test (конвенция
   движка): qlike/mae -- пул точек, rmse -- корень из взвешенного MSE.
4. **Собственный volatility baseline** -- ``volatility_naive_baseline``:
   EWMA (RiskMetrics), fold-local (аргумент -- train-префикс returns),
   seed = train-дисперсия (ddof=1), рекурсия sigma2_{t+1} =
   lambda*sigma2_t + (1-lambda)*r_t^2, плоское продление горизонта
   (конвенция RiskMetrics, без скрытой реверсии к среднему); decay
   валидируется в (0, 1) и фиксируется в cohort-контракте; вырожденный
   train (все returns нулевые) -- честный отказ.
5. **Диагностика standardized residuals и squared residuals** --
   ``standardized_residual_diagnostics``: Ljung-Box на z (белый шум
   среднего уравнения) + Ljung-Box на z^2 (McLeod-Li: остатки ARCH) +
   ARCH-LM (Engle 1982).  ARCH-LM реализован вручную (LM = T_tilde*R^2
   из регрессии z^2 на лаги 1..q с константой) и связан оракул-тестом с
   официальной statsmodels het_arch (бит-в-бит).  Смысл стандартизации
   связан тестом: на стандартизованных остатках корректной GARCH-модели
   все три теста НЕ отвергают H0.
   ``volatility_clustering_evidence`` -- тот же ARCH-LM на самих
   returns: a priori-свидетельство кластеризации (источник честного
   значения data.has_volatility_clustering при подключении GARCH,
   Task 135 -- в этой задаче профиль НЕ меняется).
6. **Полностью отдельный cohort** -- ``volatility_cohort_contract``:
   objective="volatility", metric_policy primary="qlike", метрики
   [qlike, rmse, mae]; cohort_id отличается от level-cohort тех же
   данных (привязано тестом через build_backtest_plan).  Разделение
   подкреплено структурными гейтами: реестр v2 требует
   request.objective == definition.objective, comparison
   (aligned_oof) отвергает смешение objective, а одномерный движок
   run_backtest_plan fail-closed отвергает volatility-планы --
   level-метрики (MAE/RMSE/MASE) на условной дисперсии запрещены.

Модуль НЕ импортирует backtesting.py (движок будет импортировать
контракт в Tasks 135-136 -- встречный импорт создал бы цикл).
validate_regular_grid переиспользован из сертифицированного контракта
Task 131 (единый источник истины регулярной сетки).  Fail-closed:
NaN/Inf, несовпадение длин, вырожденные данные поднимают
VolatilityContractError -- никаких синтетических метрик и подмен.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd
from scipy.stats import chi2
from statsmodels.stats.diagnostic import acorr_ljungbox

from apps.api.multivariate_contract import validate_regular_grid


VOLATILITY_CONTRACT_VERSION = "volatility-contract-v1"

#: Минимальное число returns (цен -- на единицу больше); согласовано с
#: MIN_SYSTEM_OBSERVATIONS=20 контракта Task 131 и MIN_TRAIN_OBSERVATIONS EDA.
MIN_RETURNS_OBSERVATIONS = 20

#: Допустимые явные методы преобразования цены в доходность.
RETURNS_METHODS = ("log", "simple")

#: Допустимые realized proxy условной дисперсии (объявляются явно).
REALIZED_PROXIES = ("squared_returns",)

#: Схема OOF-точки volatility-движка: сертифицированная схема движка,
#: где для objective="volatility" ``actual`` -- realized proxy (квадрат
#: доходности тест-окна), ``predicted`` -- прогноз условной дисперсии.
VOLATILITY_OOF_POINT_KEYS = (
    "fold", "horizon_step", "index", "label",
    "actual", "predicted", "residual",
)

#: Конвенция RiskMetrics для EWMA-baseline (дневные данные).
DEFAULT_EWMA_DECAY = 0.94

_EPS = float(np.finfo(float).eps)


class VolatilityContractError(ValueError):
    """Вход/результат нарушает volatility-контракт Task 134."""


def _finite_vector(values: Sequence[float], *, argument: str) -> np.ndarray:
    vector = np.asarray(list(values), dtype=float)
    if vector.size == 0:
        raise VolatilityContractError(f"{argument} пуст")
    if not np.isfinite(vector).all():
        raise VolatilityContractError(f"{argument} содержит NaN/Inf")
    return vector


# ---------------------------------------------------------------------------
# 1. Явное преобразование цены в returns без скрытого выбора
# ---------------------------------------------------------------------------

def price_to_returns(prices: Sequence[float], *, method: str) -> np.ndarray:
    """Преобразование цен в доходности с ЯВНЫМ выбором метода.

    ``method`` -- обязательный keyword: {"log"} -- log(P_t/P_{t-1}),
    {"simple"} -- P_t/P_{t-1} - 1.  Скрытого выбора нет: вызов без
    method невозможен by construction (TypeError), неизвестный метод
    отклоняется с перечислением допустимых.  Fail-closed: цены конечны,
    строго положительны (log требует P_t > 0; simple -- деление), их
    не менее 2.  Преобразование параметров не оценивает -- это точечно
    каузальная функция пары (P_{t-1}, P_t), поэтому однократный расчёт
    на полной истории с последующей fold-нарезкой leakage-safe
    (в отличие от Box-Cox lambda, который обязан оцениваться per-fold).
    """
    method = str(method).strip() if method is not None else ""
    if method not in RETURNS_METHODS:
        raise VolatilityContractError(
            f"Неизвестный метод доходностей {method!r}: допустимы "
            f"{RETURNS_METHODS}. Выбор метода должен быть явным -- "
            "скрытая конвертация цен запрещена контрактом."
        )
    vector = _finite_vector(prices, argument="prices")
    if vector.size < 2:
        raise VolatilityContractError(
            f"Преобразование цены в returns требует не менее 2 цен, "
            f"получено {vector.size}"
        )
    if (vector <= 0).any():
        raise VolatilityContractError(
            "Цены должны быть строго положительными: и log-доходности "
            "(P_t > 0), и simple (деление) не определены на неположительных."
        )
    if method == "log":
        returns = np.diff(np.log(vector))
    else:
        returns = vector[1:] / vector[:-1] - 1.0
    if not np.isfinite(returns).all():
        raise VolatilityContractError(
            "Преобразование цены в returns породило NaN/Inf (переполнение?)"
        )
    return returns


@dataclass(frozen=True)
class VolatilityTarget:
    """Валидированный target волатильности: цены + returns + заявленный метод.

    Зеркало EndogenousSystem Task 131.  Анти-тампер: stored ``returns``
    обязаны воспроизводиться из ``prices`` заявленным методом бит-в-бит --
    контейнер не может нести returns, не соответствующие его методу.
    ``timestamps`` (если переданы) выровнены с ЦЕНАМИ (n_prices меток):
    returns[i] реализуется между timestamps[i] и timestamps[i+1], метка
    OOF-точки return с индексом i -- timestamps[i+1].
    """

    prices: tuple[float, ...]
    returns: tuple[float, ...]
    method: str
    timestamps: Optional[tuple[str, ...]] = None
    grid: Optional[dict[str, Any]] = None

    def __post_init__(self) -> None:
        method = str(self.method).strip()
        if method not in RETURNS_METHODS:
            raise VolatilityContractError(
                f"method {self.method!r} недопустим: {RETURNS_METHODS} "
                "(явный выбор обязателен)"
            )
        object.__setattr__(self, "method", method)
        prices = _finite_vector(self.prices, argument="prices")
        if (prices <= 0).any():
            raise VolatilityContractError(
                "Цены должны быть строго положительными"
            )
        object.__setattr__(self, "prices", tuple(float(v) for v in prices))
        returns = _finite_vector(self.returns, argument="returns")
        if returns.size != prices.size - 1:
            raise VolatilityContractError(
                f"длина returns ({returns.size}) не равна len(prices)-1 "
                f"({prices.size - 1})"
            )
        recomputed = price_to_returns(prices, method=method)
        if not np.array_equal(recomputed, returns):
            raise VolatilityContractError(
                f"returns не воспроизводятся из цен методом {method!r} "
                "бит-в-бит: контейнер не может нести чужие доходности"
            )
        object.__setattr__(self, "returns", tuple(float(v) for v in returns))
        if returns.size < MIN_RETURNS_OBSERVATIONS:
            raise VolatilityContractError(
                f"VolatilityTarget требует не менее "
                f"{MIN_RETURNS_OBSERVATIONS} returns, получено {returns.size}"
            )
        if self.timestamps:
            if len(self.timestamps) != prices.size:
                raise VolatilityContractError(
                    f"длина временной оси ({len(self.timestamps)}) не "
                    f"совпадает с длиной цен ({prices.size})"
                )
            grid = validate_regular_grid(self.timestamps)
            object.__setattr__(self, "grid", grid)
            object.__setattr__(
                self, "timestamps",
                tuple(str(value) for value in self.timestamps),
            )
        else:
            object.__setattr__(self, "timestamps", None)
            object.__setattr__(self, "grid", None)

    @property
    def n_prices(self) -> int:
        return len(self.prices)

    @property
    def n_returns(self) -> int:
        return len(self.returns)

    @property
    def prices_array(self) -> np.ndarray:
        return np.asarray(self.prices, dtype=float)

    @property
    def returns_array(self) -> np.ndarray:
        return np.asarray(self.returns, dtype=float)

    def train_slice(self, stop: int) -> np.ndarray:
        """Train-срез returns [0, stop) -- fold-local по построению."""
        return self.returns_array[:stop]

    def test_slice(self, start: int, stop: int) -> np.ndarray:
        """Test-срез returns [start, stop)."""
        return self.returns_array[start:stop]

    def head(self, stop: int) -> "VolatilityTarget":
        """Префикс [0, stop) (fold-local построение baseline/evidence)."""
        if not 0 < stop <= self.n_returns:
            raise VolatilityContractError(
                f"head: stop={stop} вне диапазона (0, {self.n_returns}]"
            )
        timestamps = self.timestamps[: stop + 1] if self.timestamps else None
        return VolatilityTarget(
            prices=self.prices[: stop + 1],
            returns=self.returns[:stop],
            method=self.method,
            timestamps=timestamps,
        )


def build_volatility_target(
    prices: Sequence[float],
    *,
    method: str,
    timestamps: Optional[Sequence[str]] = None,
) -> VolatilityTarget:
    """Фабрика target с ЯВНЫМ преобразованием цены в returns.

    Преобразование выполняется здесь (единственная точка); класс
    повторно валидирует согласованность.  ``method`` -- обязательный
    keyword: без него вызов невозможен (скрытый выбор исключён).
    """
    returns = price_to_returns(prices, method=method)
    stamps = tuple(str(value) for value in timestamps) if timestamps else None
    return VolatilityTarget(
        prices=tuple(float(value) for value in prices),
        returns=tuple(float(value) for value in returns),
        method=method,
        timestamps=stamps,
    )


# ---------------------------------------------------------------------------
# 2. Realized proxy условной дисперсии (объявляется явно)
# ---------------------------------------------------------------------------

def realized_variance_proxy(
    returns: Sequence[float], *, proxy: str,
) -> np.ndarray:
    """Realized proxy условной дисперсии с ЯВНЫМ объявлением.

    ``proxy`` -- обязательный keyword; {"squared_returns"} -- квадрат
    доходности тест-окна (стандартный прокси; Patton 2011 показал
    robustness QLIKE к зашумлённому proxy).  Скрытой подмены proxy нет:
    вызов без него невозможен by construction.
    """
    if proxy not in REALIZED_PROXIES:
        raise VolatilityContractError(
            f"Неизвестный realized proxy {proxy!r}: допустим "
            f"{REALIZED_PROXIES}. Proxy должен быть объявлен явно."
        )
    vector = _finite_vector(returns, argument="returns")
    return vector**2


# ---------------------------------------------------------------------------
# 3. Primary metric: QLIKE; дополнительные ошибки по realized proxy
# ---------------------------------------------------------------------------

def compute_volatility_metrics(
    realized: Sequence[float],
    predicted: Sequence[float],
    *,
    proxy: str,
) -> dict[str, Any]:
    """QLIKE (primary) + RMSE/MAE по realized proxy, fail-closed.

    QLIKE в robust-форме Паттона (2011): mean(log(sv) + rv/sv), где
    rv -- realized proxy, sv -- прогноз условной дисперсии.  Форма
    ранжирование-эквивалентна классической mean(rv/sv - log(rv/sv) - 1)
    (разность = mean(log rv) + 1 -- константа, не зависящая от прогноза;
    связана оракул-тестом) и устойчива к зашумлённому proxy.  Нулевой
    realized (rv=0) допустим; прогноз дисперсии sv <= 0 отклоняется
    fail-closed (log не определён, clamp-подмена запрещена): честный
    отказ лучше фиктивной метрики.  ``proxy`` -- обязательный keyword:
    proxy декларируется в каждой точке вычисления метрики, тихая
    подмена прокси между моделями невозможна.
    """
    if proxy not in REALIZED_PROXIES:
        raise VolatilityContractError(
            f"Неизвестный realized proxy {proxy!r}: допустим "
            f"{REALIZED_PROXIES}."
        )
    actual = _finite_vector(realized, argument="realized proxy")
    forecast = _finite_vector(predicted, argument="predicted variance")
    if actual.size != forecast.size:
        raise VolatilityContractError(
            f"длины realized ({actual.size}) и predicted ({forecast.size}) "
            "должны совпадать"
        )
    if (actual < 0).any():
        raise VolatilityContractError(
            "realized proxy должен быть неотрицательным: нарушен контракт "
            "proxy (squared returns >= 0)"
        )
    if (forecast <= 0).any():
        raise VolatilityContractError(
            "Прогноз условной дисперсии должен быть строго положительным: "
            "QLIKE не определён на sv <= 0; clamp-подмена запрещена -- "
            "честный отказ вместо фиктивной метрики."
        )
    qlike = float(np.mean(np.log(forecast) + actual / forecast))
    errors = actual - forecast
    rmse = float(np.sqrt(np.mean(np.square(errors))))
    mae = float(np.mean(np.abs(errors)))
    return {
        "qlike": round(qlike, 6),
        "rmse": round(rmse, 6),
        "mae": round(mae, 6),
        "n_points": int(actual.size),
        "primary": "qlike",
        "realized_proxy": proxy,
    }


def aggregate_volatility_metrics(
    folds: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Агрегация volatility-метрик по folds (конвенция движка).

    qlike/mae -- пул точек (среднее точечной потери = взвешенное среднее
    fold-значений по n_test); rmse -- корень из взвешенного среднего MSE
    (НЕ среднее RMSE).  Realized proxy обязан быть согласован по всем
    folds (all-or-none: появление разных proxy -- нарушение cohort).
    """
    if not folds:
        raise VolatilityContractError("агрегация по пустому списку folds")
    total = 0
    weighted_qlike = 0.0
    weighted_mae = 0.0
    weighted_mse = 0.0
    proxy_values: list[Any] = []
    for position, fold in enumerate(folds, 1):
        metrics = fold.get("metrics") if isinstance(fold, Mapping) else None
        if not isinstance(metrics, Mapping):
            raise VolatilityContractError(
                f"fold {position}: отсутствует блок metrics"
            )
        n_test = int(fold.get("n_test") or 0)
        if n_test < 1:
            raise VolatilityContractError(
                f"fold {position}: n_test={n_test} должен быть положительным"
            )
        values: dict[str, float] = {}
        for key in ("qlike", "rmse", "mae"):
            raw = metrics.get(key)
            if raw is None:
                raise VolatilityContractError(
                    f"fold {position}: метрика '{key}' отсутствует -- "
                    "частичная агрегация запрещена"
                )
            value = float(raw)
            if not np.isfinite(value):
                raise VolatilityContractError(
                    f"fold {position}: метрика '{key}' не конечна"
                )
            values[key] = value
        total += n_test
        weighted_qlike += values["qlike"] * n_test
        weighted_mae += values["mae"] * n_test
        weighted_mse += values["rmse"] ** 2 * n_test
        proxy_values.append(metrics.get("realized_proxy"))
    declared = [value for value in proxy_values if value is not None]
    if declared and len(declared) != len(proxy_values):
        raise VolatilityContractError(
            "realized_proxy объявлен не во всех folds: согласованность "
            "proxy внутри cohort обязательна (all-or-none)"
        )
    if declared and len(set(declared)) != 1:
        raise VolatilityContractError(
            "realized_proxy расходится между folds: подмена proxy внутри "
            "cohort запрещена"
        )
    common_proxy = declared[0] if declared else None
    return {
        "qlike": round(weighted_qlike / total, 6),
        "rmse": round(float(np.sqrt(weighted_mse / total)), 6),
        "mae": round(weighted_mae / total, 6),
        "n_points": int(total),
        "primary": "qlike",
        "realized_proxy": common_proxy,
        "aggregation": "test_size_weighted_folds",
    }


# ---------------------------------------------------------------------------
# 4. Собственный volatility baseline: EWMA (RiskMetrics), fold-local
# ---------------------------------------------------------------------------

def volatility_naive_baseline(
    returns: Sequence[float],
    horizon: int,
    *,
    decay: float = DEFAULT_EWMA_DECAY,
) -> tuple[float, ...]:
    """EWMA-baseline волатильности (RiskMetrics), fold-local.

    Аргумент ``returns`` -- ТОЛЬКО train-префикс доходностей (leakage-
    safety по построению, как vector_naive_baseline Task 131).  Seed --
    train-дисперсия (ddof=1, допускает ненулевое среднее), далее
    рекурсия sigma2_{t+1} = decay*sigma2_t + (1-decay)*r_t^2.  Прогноз
    на горизонт -- плоское продление последнего значения (конвенция
    RiskMetrics; реверсия к долгосрочному среднему вводила бы скрытый
    гиперпараметр).  ``decay`` валидируется в (0, 1) и фиксируется в
    cohort-контракте.  Вырожденный train (все returns нулевые) --
    честный отказ: baseline обязан выдать положительный прогноз
    дисперсии, иначе он неоценим QLIKE.
    """
    horizon = int(horizon)
    if horizon < 1:
        raise VolatilityContractError("horizon должен быть положительным")
    decay = float(decay)
    if not 0.0 < decay < 1.0:
        raise VolatilityContractError(
            f"decay={decay} должен быть в интервале (0, 1) "
            f"(конвенция RiskMetrics: {DEFAULT_EWMA_DECAY})"
        )
    vector = _finite_vector(returns, argument="returns")
    if vector.size < 2:
        raise VolatilityContractError(
            "EWMA-baseline требует не менее 2 returns для train-дисперсии"
        )
    sigma2 = float(np.var(vector, ddof=1))
    one_minus = 1.0 - decay
    for value in vector:
        sigma2 = decay * sigma2 + one_minus * float(value) ** 2
    if sigma2 <= 0.0:
        raise VolatilityContractError(
            "Вырожденный train: нулевая волатильность (все returns равны "
            "нулю); baseline не может выдать положительный прогноз дисперсии"
        )
    return (float(sigma2),) * horizon


# ---------------------------------------------------------------------------
# 5. Диагностика standardized residuals и squared residuals
# ---------------------------------------------------------------------------

def _arch_lm_statistic(
    residuals: np.ndarray, nlags: int,
) -> tuple[float, int]:
    """ARCH-LM (Engle 1982): T_tilde * R^2 из регрессии z^2 на лаги 1..q.

    Дизайн-матрица: константа + q лагов квадрата остатка; LM-статистика
    = T_tilde * R^2 (T_tilde = T - q -- эффективная длина регрессии),
    асимптотика chi2(q).  Формула сверена с официальной statsmodels
    het_arch -- оракул-тест связывает паритет бит-в-бит (rtol 1e-10).
    """
    values = np.asarray(residuals, dtype=float)
    nobs = values.size
    squared = values**2
    target = squared[nlags:]
    columns = [np.ones(nobs - nlags)]
    for lag in range(1, nlags + 1):
        columns.append(squared[nlags - lag: nobs - lag])
    design = np.column_stack(columns)
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    fitted = design @ coefficients
    residuals_reg = target - fitted
    total_ss = float(np.sum((target - target.mean()) ** 2))
    residual_ss = float(np.sum(residuals_reg**2))
    r_squared = 1.0 - residual_ss / total_ss if total_ss > 0.0 else 0.0
    return float((nobs - nlags) * r_squared), int(nlags)


def _ljung_box_block(
    values: np.ndarray, nlags: int, *, alpha: float,
) -> dict[str, Any]:
    """Пер-серия Ljung-Box (model_df=0): статистика/p-value/решение."""
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        table = acorr_ljungbox(values, lags=[nlags], model_df=0, return_df=True)
    statistic = float(table["lb_stat"].iloc[-1])
    p_value = float(table["lb_pvalue"].iloc[-1])
    return {
        "statistic": statistic,
        "p_value": p_value,
        "reject_null": bool(p_value < alpha),
    }


def standardized_residual_diagnostics(
    std_residuals: Sequence[float],
    *,
    nlags: int,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Диагностика standardized и squared standardized residuals.

    Три блока (зеркалят system_white_noise_diagnostics Task 131):
    - ``ljung_box``: Ljung-Box на z -- белый шум среднего уравнения;
    - ``ljung_box_squared``: Ljung-Box на z^2 (McLeod-Li) -- не осталось
      ли ARCH в квадратах;
    - ``arch_lm``: ARCH-LM (Engle 1982), паритет с het_arch связан
      оракул-тестом.
    На стандартизованных остатках корректной GARCH-модели все три теста
    НЕ отвергают H0 (связано тестом на симулированном процессе).
    Fail-closed: вырожденные остатки (нулевая дисперсия) -- отказ, а не
    фиктивный «идеальный фит».
    """
    nlags = int(nlags)
    if nlags < 1:
        raise VolatilityContractError("nlags должен быть положительным")
    alpha = float(alpha)
    if not 0.0 < alpha < 1.0:
        raise VolatilityContractError(
            f"alpha={alpha} должен быть в интервале (0, 1)"
        )
    values = _finite_vector(std_residuals, argument="standardized residuals")
    if values.size <= nlags:
        raise VolatilityContractError(
            f"длина residuals ({values.size}) должна превышать nlags={nlags}"
        )
    if float(np.var(values, ddof=1)) <= _EPS:
        raise VolatilityContractError(
            "Стандартизованные остатки вырождены (нулевая дисперсия): "
            "диагностика не интерпретируема, отказ вместо фиктивного "
            "«идеального фита»"
        )
    statistic, df = _arch_lm_statistic(values, nlags)
    arch_p_value = float(chi2.sf(statistic, df))
    return {
        "available": True,
        "ljung_box": _ljung_box_block(values, nlags, alpha=alpha),
        "ljung_box_squared": _ljung_box_block(
            values**2, nlags, alpha=alpha,
        ),
        "arch_lm": {
            "statistic": statistic,
            "df": df,
            "p_value": arch_p_value,
            "reject_null": bool(arch_p_value < alpha),
        },
        "n_observations": int(values.size),
        "nlags": nlags,
        "alpha": alpha,
    }


def volatility_clustering_evidence(
    returns: Sequence[float],
    *,
    nlags: int,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """A priori evidence кластеризации волатильности: ARCH-LM на returns.

    Тот же тест Engle, применённый к самим доходностям train-среза:
    H0 -- ARCH-эффект отсутствует; reject при p < alpha означает
    кластеризацию волатильности.  Источник честного значения
    ``data.has_volatility_clustering`` (modeling.yaml::P04) при
    подключении GARCH (Task 135); в Task 134 профиль данных не меняется.
    """
    nlags = int(nlags)
    if nlags < 1:
        raise VolatilityContractError("nlags должен быть положительным")
    alpha = float(alpha)
    if not 0.0 < alpha < 1.0:
        raise VolatilityContractError(
            f"alpha={alpha} должен быть в интервале (0, 1)"
        )
    values = _finite_vector(returns, argument="returns")
    if values.size <= nlags + 1:
        raise VolatilityContractError(
            f"длина returns ({values.size}) недостаточна для ARCH-LM "
            f"с nlags={nlags}"
        )
    if float(np.var(values, ddof=1)) <= _EPS:
        raise VolatilityContractError(
            "Returns вырождены (нулевая дисперсия): evidence кластеризации "
            "не интерпретируема"
        )
    statistic, df = _arch_lm_statistic(values, nlags)
    p_value = float(chi2.sf(statistic, df))
    return {
        "available": True,
        "statistic": statistic,
        "df": df,
        "p_value": p_value,
        "reject_null": bool(p_value < alpha),
        "nlags": nlags,
        "alpha": alpha,
    }


# ---------------------------------------------------------------------------
# 6. Полностью отдельный cohort: objective="volatility", primary=qlike
# ---------------------------------------------------------------------------

def volatility_cohort_contract(
    *,
    target_column: str,
    fingerprint: str,
    returns_method: str,
    n_returns: int,
    seasonal_period: int = 1,
    decay: float = DEFAULT_EWMA_DECAY,
) -> dict[str, Any]:
    """Cohort-контракт волатильности (зеркало multivariate_cohort_contract).

    Схема ключей верхнего уровня идентична backtesting.build_backtest_plan
    (objective / series_fingerprints / feature_contract / metric_policy);
    добавлены блоки ``metric_policy.volatility`` (target_kind, returns
    method, realized proxy, baseline) и ``target`` (версия контракта,
    исходная колонка цен, число returns).  ``returns_method`` --
    обязательный keyword: cohort фиксирует ЯВНЫЙ выбор преобразования;
    cohort_id такого плана отличается от level-cohort тех же данных,
    а comparison (aligned_oof) отвергает смешение objective.
    """
    target_column = str(target_column).strip()
    if not target_column:
        raise VolatilityContractError(
            "target_column не может быть пустым"
        )
    fingerprint = str(fingerprint).strip()
    if not fingerprint:
        raise VolatilityContractError("fingerprint не может быть пустым")
    method = str(returns_method).strip()
    if method not in RETURNS_METHODS:
        raise VolatilityContractError(
            f"returns_method {returns_method!r} недопустим: допустимы "
            f"{RETURNS_METHODS}. Выбор преобразования цены в returns "
            "должен быть явным и фиксируется в cohort-контракте."
        )
    n_returns = int(n_returns)
    if n_returns < 1:
        raise VolatilityContractError(
            f"n_returns={n_returns} должен быть положительным"
        )
    seasonal_period = int(seasonal_period)
    if seasonal_period < 1:
        raise VolatilityContractError(
            "seasonal_period должен быть положительным"
        )
    decay = float(decay)
    if not 0.0 < decay < 1.0:
        raise VolatilityContractError(
            f"decay={decay} должен быть в интервале (0, 1)"
        )
    return {
        "objective": "volatility",
        "series_fingerprints": {target_column: fingerprint},
        "feature_contract": {
            "historic": [], "future_known": [], "static": [],
            "policy": "none",
        },
        "metric_policy": {
            "metrics": ["qlike", "rmse", "mae"],
            "primary": "qlike",
            "aggregation": "test_size_weighted_folds",
            "seasonal_period": seasonal_period,
            "volatility": {
                "contract_version": VOLATILITY_CONTRACT_VERSION,
                "target_kind": "conditional_variance",
                "returns_method": method,
                "realized_proxy": REALIZED_PROXIES[0],
                "oof_point_keys": list(VOLATILITY_OOF_POINT_KEYS),
                "baseline": {"type": "ewma_riskmetrics", "decay": decay},
            },
        },
        "target": {
            "contract_version": VOLATILITY_CONTRACT_VERSION,
            "kind": "conditional_variance",
            "source_column": target_column,
            "returns_method": method,
            "realized_proxy": REALIZED_PROXIES[0],
            "n_returns_observations": n_returns,
        },
    }
