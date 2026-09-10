# apps/api/model_impls/garch.py
"""
GARCH -- нативная модель условной дисперсии пакета arch (Task 135, family=volatility).

Первый исполнитель volatility-контракта Task 134 (прецедент Task 131->132).
Постановка docs/modeling_task_list.md::Task 135 + требования Task 134:

1. **Target -- условная дисперсия, а не уровень ряда**: адаптер получает
   ТОЛЬКО train-срез ДОХОДНОСТЕЙ (преобразование цены в returns выполняет
   контракт Task 134 с ЯВНЫМ method={log, simple}; полная история в адаптер
   недостижима по построению).  Прогноз -- аналитическая рекурсия
   условной дисперсии официального arch-контура (ARCHModelResult.forecast,
   method="analytic"): sigma2_{T+1} = omega + alpha*eps^2_T + beta*sigma2_T,
   sigma2_{T+h} = omega + (alpha+beta)*sigma2_{T+h-1} (ожидание
   ненаблюдаемого eps^2 замещается условной дисперсией) -- паритет
   рекурсии связан оракул-тестом.

2. **rescale=False -- без скрытого выбора**: arch умеет «молча»
   масштабировать вход (rescale=None по умолчанию); адаптер фиксирует
   rescale=False явно -- параметры MLE остаются на шкале входных
   returns (привязано тестом на бит-паритет с прямым arch-фитом).

3. **Fail-closed**: никаких Naive-fallback, clamp-подмен и синтетических
   метрик.  Несошедшийся MLE (convergence_flag != 0), прогноз sigma2 <= 0,
   нечисловой/вырожденный вход -- ошибка fold'а (BacktestExecutionError на
   движке).  Стандартизованные остатки обязаны быть конечными -- иначе
   диагностика контракта неинтерпретируема и fold отклоняется.

4. **Интервалы**: симуляционные квантили путей условной дисперсии
   (ARCHModelResult.forecast, method="simulation", rng = сидированный
   numpy-генератор -- arch использует global-RNG только через
   distribution.simulate; determinism привязан оракул-тестом:
   одинаковый seed => бит-идентичные интервалы).  Уровень alpha
   {0.01, 0.05, 0.10} -- как у VAR (Task 132).

Bounded params (fail-closed, см. PARAM_BOUNDS и rules/modeling.yaml):
p (1..3), q (1..3), mean (Constant/Zero), dist (normal/t),
alpha (0.01/0.05/0.10).  p/q -- порядки GARCH(p, q); mean="Zero" опускает
константу среднего уравнения; dist="t" добавляет хвостовой параметр nu.

Детерминизм: MLE (SLSQP) arch детерминирован; симуляционные интервалы --
сидированный rng-callable; random_state принят по контракту реестра и
управляет ТОЛЬКО симуляцией интервалов (точечный прогноз не зависит от
seed -- привязано тестом).
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import numpy as np

GARCH_ADAPTER_ID = "arch-garch"

#: Минимальная длина train-среза returns (согласовано с
#: MIN_RETURNS_OBSERVATIONS контракта Task 134).
GARCH_MIN_TRAIN = 20

#: Нормализованные дефолты + строгие границы (bounded param_space вне
#: тюнинга тоже не может выйти за границы -- fail-closed).
DEFAULT_PARAMS: dict[str, Any] = {
    "p": 1,
    "q": 1,
    "mean": "Constant",
    "dist": "normal",
    "alpha": 0.05,
}
PARAM_BOUNDS: dict[str, tuple[int, int]] = {
    "p": (1, 3),
    "q": (1, 3),
}
MEAN_OPTIONS = {"Constant", "Zero"}
DIST_OPTIONS = {"normal", "t"}
ALPHA_OPTIONS = {0.01, 0.05, 0.10}

#: Число симуляционных путей для интервалов дисперсии (конвенция arch).
INTERVAL_SIMULATIONS = 1000

_PARAM_KEYS = ("p", "q", "mean", "dist", "alpha")


def validate_garch_params(params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Нормализовать и провалидировать гиперпараметры GARCH (fail-closed).

    Неизвестные ключи игнорируются -- соглашение платформы (в params всегда
    приходят чужие ключи вроде tbats_seasonal_periods, см.
    backtesting.py::run_backtest_plan).
    """
    merged = {
        **DEFAULT_PARAMS,
        **{k: v for k, v in dict(params or {}).items() if k in _PARAM_KEYS},
    }
    normalized: dict[str, Any] = {}
    for key in ("p", "q"):
        value = merged[key]
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise ValueError(
                f"GARCH param '{key}': ожидался целочисленный аргумент, "
                f"получено {value!r}"
            )
        low, high = PARAM_BOUNDS[key]
        number = int(value)
        if not low <= number <= high:
            raise ValueError(
                f"GARCH param '{key}'={number} вне bounded диапазона "
                f"[{low}, {high}]"
            )
        normalized[key] = number
    mean = merged["mean"]
    if mean not in MEAN_OPTIONS:
        raise ValueError(
            f"GARCH param 'mean'={mean!r} вне допустимого набора "
            f"{sorted(MEAN_OPTIONS)}"
        )
    normalized["mean"] = str(mean)
    dist = merged["dist"]
    if dist not in DIST_OPTIONS:
        raise ValueError(
            f"GARCH param 'dist'={dist!r} вне допустимого набора "
            f"{sorted(DIST_OPTIONS)}"
        )
    normalized["dist"] = str(dist)
    alpha = merged["alpha"]
    try:
        alpha_value = float(alpha)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"GARCH param 'alpha'={alpha!r} не числовой") from exc
    if alpha_value not in ALPHA_OPTIONS:
        raise ValueError(
            f"GARCH param 'alpha'={alpha_value} вне допустимого набора "
            f"{sorted(ALPHA_OPTIONS)}"
        )
    normalized["alpha"] = alpha_value
    return normalized


def _validated_returns(returns: Sequence[float]) -> np.ndarray:
    vector = np.asarray([float(value) for value in returns], dtype=float)
    if vector.size == 0:
        raise ValueError("GARCH: train fold returns пуст")
    if not np.isfinite(vector).all():
        raise ValueError(
            "GARCH: returns содержат NaN/Inf -- импутация запрещена "
            "(fail-closed)"
        )
    return vector


def _garch_fit_predict(
    returns: Sequence[float],
    horizon: int,
    *,
    params: Optional[Mapping[str, Any]] = None,
    random_state: int = 42,
) -> dict[str, Any]:
    """Нативный GARCH fit/forecast на переданном train-срезе returns.

    Возвращает payload: ``variance_forecast`` -- аналитический прогноз
    условной дисперсии (horizon,); ``lower``/``upper`` -- симуляционные
    квантили путей дисперсии на уровне ``alpha`` (детерминизм -- сиди-
    рованный rng-callable); ``params``/``persistence``/``convergence_flag``/
    ``std_residuals``/``conditional_volatility`` -- вход диагностики
    движка (standardized_residual_diagnostics, volatility-блок fold'а).
    random_state принят по контракту реестра: влияет только на симуляцию
    интервалов (точечный прогноз детерминирован).
    """
    if int(horizon) < 1:
        raise ValueError("GARCH: horizon должен быть положительным")
    normalized = validate_garch_params(params)
    vector = _validated_returns(returns)
    nobs = vector.size
    if nobs < GARCH_MIN_TRAIN:
        raise ValueError(
            f"GARCH: история слишком короткая ({nobs} returns); минимум "
            f"{GARCH_MIN_TRAIN} (MIN_RETURNS_OBSERVATIONS контракта Task 134)"
        )

    from arch import arch_model

    try:
        model = arch_model(
            vector, mean=normalized["mean"], vol="GARCH",
            p=normalized["p"], q=normalized["q"], dist=normalized["dist"],
            rescale=False,  # БЕЗ скрытого масштабирования входа
        )
        fitted = model.fit(disp="off", show_warning=False)
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 -- library-native отказ = ошибка fold'а
        raise ValueError(
            f"GARCH: fit недоступен на переданном train-срезе: {exc}"
        ) from exc

    convergence_flag = int(fitted.convergence_flag)
    if convergence_flag != 0:
        raise ValueError(
            f"GARCH: MLE не сошелся (convergence_flag={convergence_flag}); "
            "несошедшийся фит не является честным прогнозом дисперсии "
            "(fail-closed)"
        )

    try:
        analytic = fitted.forecast(
            horizon=int(horizon), method="analytic", reindex=False,
        )
        variance_forecast = np.asarray(
            analytic.variance.values[-1], dtype=float,
        )
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"GARCH: прогноз дисперсии недоступен: {exc}"
        ) from exc
    if variance_forecast.shape != (int(horizon),):
        raise ValueError(
            f"GARCH: arch вернул прогноз формы {variance_forecast.shape}, "
            f"ожидалось ({int(horizon)},)"
        )
    if not np.isfinite(variance_forecast).all() or (variance_forecast <= 0).any():
        raise ValueError(
            "GARCH: прогноз дисперсии должен быть строго положительным "
            "(sigma2 <= 0 -- отказ без clamp-подмен)"
        )

    # Интервалы: симуляционные квантили путей дисперсии.  rng-callable --
    # сидированный numpy-генератор (параметр random_state у arch отвечает
    # только за method="bootstrap").
    alpha_level = normalized["alpha"]
    generator = np.random.default_rng(int(random_state))

    def _rng(size: tuple[int, int]) -> np.ndarray:
        return generator.standard_normal(size)

    try:
        simulated = fitted.forecast(
            horizon=int(horizon), method="simulation",
            simulations=INTERVAL_SIMULATIONS, rng=_rng, reindex=False,
        )
        paths = np.asarray(simulated.simulations.variances[-1], dtype=float)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"GARCH: симуляционные пути дисперсии недоступны: {exc}"
        ) from exc
    if paths.shape != (INTERVAL_SIMULATIONS, int(horizon)):
        raise ValueError(
            f"GARCH: форма симуляционных путей {paths.shape} не "
            f"соответствует ({INTERVAL_SIMULATIONS}, {int(horizon)})"
        )
    quantiles = (alpha_level / 2.0, 1.0 - alpha_level / 2.0)
    lower = np.quantile(paths, quantiles[0], axis=0)
    upper = np.quantile(paths, quantiles[1], axis=0)
    # Инвариант lower <= point <= upper обязан держаться нативно; численная
    # защита от вырожденного квантиля (не меняет честный прогноз).
    lower = np.minimum(lower, variance_forecast)
    upper = np.maximum(upper, variance_forecast)

    fit_params = {str(key): float(value) for key, value in fitted.params.items()}
    alpha_keys = [key for key in fit_params if key.startswith("alpha[")]
    beta_keys = [key for key in fit_params if key.startswith("beta[")]
    persistence = float(sum(fit_params[key] for key in alpha_keys + beta_keys))
    std_residuals = np.asarray(fitted.std_resid, dtype=float)
    if not np.isfinite(std_residuals).all():
        raise ValueError(
            "GARCH: стандартизованные остатки содержат NaN/Inf -- "
            "диагностика контракта неинтерпретируема (fail-closed)"
        )
    conditional_volatility = np.asarray(
        fitted.conditional_volatility, dtype=float,
    )

    return {
        "adapter_id": GARCH_ADAPTER_ID,
        "variance_forecast": variance_forecast,
        "lower": lower,
        "upper": upper,
        "params": fit_params,
        "persistence": persistence,
        "is_covariance_stationary": bool(persistence < 1.0),
        "convergence_flag": convergence_flag,
        "nobs": int(fitted.nobs),
        "loglikelihood": float(fitted.loglikelihood),
        "aic": float(fitted.aic),
        "bic": float(fitted.bic),
        "std_residuals": std_residuals,
        "conditional_volatility": conditional_volatility,
        "mean_model": normalized["mean"],
        "dist": normalized["dist"],
        "intervals": {
            "method": "simulation",
            "simulations": INTERVAL_SIMULATIONS,
            "alpha": alpha_level,
        },
        "random_state": int(random_state),
        "deterministic": True,
    }


def run_garch_backtest(
    series: Sequence[float],
    train_ratio: float,
    seasonal_period: int,
) -> None:
    """Legacy synthetic-demo эндпоинт (POST /v1/models/backtest), сигнатура
    как у остальных model_impls.  Task 135: target GARCH -- условная
    дисперсия ДОХОДНОСТЕЙ; преобразование цены в returns -- ЯВНЫЙ выбор
    volatility-контракта Task 134 (method=log/simple), а не скрытое
    решение однорядного synthetic-эндпоинта.  Никаких синтетических демо и
    Naive-fallback: честный отказ (ValueError), как у VAR/VECM/ML-адаптеров."""
    raise ValueError(
        "GARCH прогнозирует условную дисперсию доходностей: преобразование "
        "цены в returns должно быть явным (volatility-контракт Task 134, "
        "method=log/simple); однорядный synthetic-эндпоинт не применим -- "
        "исполняйте GARCH через session backtest volatility-движка "
        "(run_volatility_backtest_plan)"
    )


__all__ = [
    "ALPHA_OPTIONS",
    "DEFAULT_PARAMS",
    "DIST_OPTIONS",
    "GARCH_ADAPTER_ID",
    "GARCH_MIN_TRAIN",
    "INTERVAL_SIMULATIONS",
    "MEAN_OPTIONS",
    "PARAM_BOUNDS",
    "_garch_fit_predict",
    "run_garch_backtest",
    "validate_garch_params",
]
