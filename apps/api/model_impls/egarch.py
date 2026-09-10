# apps/api/model_impls/egarch.py
"""
EGARCH -- нативная модель условной дисперсии пакета arch с параметризацией
leverage/asymmetry (Task 136, family=volatility).

Второй исполнитель volatility-контракта Task 134 (прецедент пары var/vecm
в одном движке): volatility-движок Task 135 (run_volatility_backtest_plan)
переиспользуется бит-в-бит, адаптер поставляет новый executor реестра v2.
Постановка docs/modeling_task_list.md::Task 136 + требования Task 134:

1. **Target -- условная дисперсия, а не уровень ряда**: адаптер получает
   ТОЛЬКО train-срез ДОХОДНОСТЕЙ (преобразование цены в returns выполняет
   контракт Task 134 с ЯВНЫМ method={log, simple}; полная история в адаптер
   недостижима по построению).  Рекурсия EGARCH(p,o,q) -- log-дисперсия:
   ln sigma2_t = omega + sum_i alpha_i(|e_{t-i}| - sqrt(2/pi))
                 + sum_j gamma_j e_{t-j} + sum_k beta_k ln sigma2_{t-k},
   где e_t = eps_t / sigma_t.  Асимметрия (leverage) -- gamma-члены:
   отрицательный шок e<0 при gamma<0 поднимает ln sigma2 сильнее, чем
   положительный того же масштаба (классический «leverage effect»); знак
   и значимость fitted gamma честно репортуются в asymmetry-блоке.

2. **Точечный прогноз -- официальный симуляционный контур arch**.
   EGARCH в arch 8.0 НЕ имеет analytic-прогноза за горизонтом 1 (жёсткий
   gate: «Analytic forecasts not available for horizon > 1», проверено
   probe'ом scripts/task136_probe.py); официальный контур для EGARCH --
   method="simulation": variance.values == среднее симуляционных путей
   дисперсии (probe fact 5), т.е. честная MC-оценка условного ожидания
   E[sigma2_{T+h} | F_T] -- оптимального точечного прогноза под QLIKE.
   На шаге h=1 пути вырождены (не зависят от симулируемых инноваций),
   поэтому симуляционное среднее h=1 бит-точно совпадает с analytic h=1
   и ручной рекурсией из фильтрованного состояния (оракул-тест).

3. **rescale=False -- без скрытого выбора**: arch умеет «молча»
   масштабировать вход (rescale=None по умолчанию); адаптер фиксирует
   rescale=False явно -- параметры MLE остаются на шкале входных
   returns (привязано тестом на бит-паритет с прямым arch-фитом).

4. **Fail-closed**: никаких Naive-fallback, clamp-подмен и синтетических
   метрик.  Несошедшийся MLE (convergence_flag != 0), прогноз sigma2 <= 0,
   нечисловой/вырожденный вход -- ошибка fold'а (BacktestExecutionError на
   движке).  Стандартизованные остатки обязаны быть конечными -- иначе
   диагностика контракта неинтерпретируема и fold отклоняется.

5. **Интервалы**: квантили ТЕХ ЖЕ симуляционных путей дисперсии
   (alpha 0.01/0.05/0.10, сидированный rng-callable -- arch использует
   global-RNG только через distribution.simulate; determinism привязан
   оракул-тестом: одинаковый seed => бит-идентичные пути и интервалы).

6. **Бюджет сходимости MLE -- ЯВНЫЙ** (EGARCH-специфика, честное
   отличие от GARCH): scipy SLSQP в arch по умолчанию имеет maxiter=100,
   что для лог-рекурсии EGARCH недостаточно -- на реальных срезах
   встречаются срезы, где оптимизатор упирается в лимит
   (convergence_flag=9, «Iteration limit reached») при ДОСТИЖИМОМ
   лучшем оптимуме (probe: срез-207 смоук-серии -- флаг 9 при
   llf=-228.90 => флаг 0 при llf=-222.58, runtime ~0.08с).  Адаптер
   декларирует явный бюджет EGARCH_MAXITER=1000 через ОФИЦИАЛЬНЫЙ
   fit-options arch -- это тот же MLE, а не подмена модели: достигается
   лучший (или равный) loglikelihood; несошедшийся даже при бюджете фит
   -- честный отказ fold'а (fail-closed без исключений).  Привязано
   оракул-тестом на фиксированном патологическом срезе.

Bounded params (fail-closed, см. PARAM_BOUNDS и rules/modeling.yaml):
p (1..3), o (1..3), q (1..3), mean (Constant/Zero), dist (normal/t),
alpha (0.01/0.05/0.10).  o -- порядок асимметричных членов: o >= 1
обязателен (суть Task 136 -- модель параметризует leverage; симметричный
o=0 вне bounded-пространства).  mean="Zero" опускает константу среднего
уравнения; dist="t" добавляет хвостовой параметр nu.

Стационарность: для EGARCH стационарность log-дисперсии (AR(q) с i.i.d.
инновациями alpha(|e|-c)+gamma*e нулевого среднего) эквивалентна
sum(beta) < 1; sigma2 = exp(ln sigma2) наследует строгую стационарность.
Честный аналог persistence GARCH -- сумма beta-коэффициентов (arch НЕ
предоставляет fitted.persistence для EGARCH -- проверено probe'ом),
is_covariance_stationary := sum(beta) < 1.

Детерминизм: MLE (SLSQP) arch детерминирован; симуляция -- сидированный
rng-callable; random_state принят по контракту реестра и управляет
симуляцией (точечный прогноз -- MC-оценка среднего путей -- законно
зависит от seed на h >= 2; h=1 точен; MLE-параметры от seed НЕ зависят).
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import numpy as np

EGARCH_ADAPTER_ID = "arch-egarch"

#: Минимальная длина train-среза returns (согласовано с
#: MIN_RETURNS_OBSERVATIONS контракта Task 134).
EGARCH_MIN_TRAIN = 20

#: Нормализованные дефолты + строгие границы (bounded param_space вне
#: тюнинга тоже не может выйти за границы -- fail-closed).
DEFAULT_PARAMS: dict[str, Any] = {
    "p": 1,
    "o": 1,
    "q": 1,
    "mean": "Constant",
    "dist": "normal",
    "alpha": 0.05,
}
PARAM_BOUNDS: dict[str, tuple[int, int]] = {
    "p": (1, 3),
    "o": (1, 3),
    "q": (1, 3),
}
MEAN_OPTIONS = {"Constant", "Zero"}
DIST_OPTIONS = {"normal", "t"}
ALPHA_OPTIONS = {0.01, 0.05, 0.10}

#: Число симуляционных путей официального контура (точечный прогноз --
#: среднее путей = variance.values arch; интервалы -- квантили тех же
#: путей).  MC-ошибка среднего на h>=2 при 4000 путях < 0.6% для
#: персистентных процессов (probe scripts/task136_probe.py); runtime
#: пренебрежим (доли секунды на fold).
INTERVAL_SIMULATIONS = 4000

#: Явный бюджет итераций оптимизатора MLE (scipy SLSQP; дефолт scipy 100
#: недостаточен для лог-рекурсии EGARCH -- см. пункт 6 докстринга).
EGARCH_MAXITER = 1000

#: Порог значимости p-value gamma-членов (Wald, pvalues официального
#: фита arch) в asymmetry-блоке.
ASYMMETRY_SIGNIFICANCE_LEVEL = 0.05

_PARAM_KEYS = ("p", "o", "q", "mean", "dist", "alpha")


def validate_egarch_params(params: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Нормализовать и провалидировать гиперпараметры EGARCH (fail-closed).

    Неизвестные ключи игнорируются -- соглашение платформы (в params всегда
    приходят чужие ключи вроде tbats_seasonal_periods, см.
    backtesting.py::run_backtest_plan).
    """
    merged = {
        **DEFAULT_PARAMS,
        **{k: v for k, v in dict(params or {}).items() if k in _PARAM_KEYS},
    }
    normalized: dict[str, Any] = {}
    for key in ("p", "o", "q"):
        value = merged[key]
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise ValueError(
                f"EGARCH param '{key}': ожидался целочисленный аргумент, "
                f"получено {value!r}"
            )
        low, high = PARAM_BOUNDS[key]
        number = int(value)
        if not low <= number <= high:
            raise ValueError(
                f"EGARCH param '{key}'={number} вне bounded диапазона "
                f"[{low}, {high}]"
            )
        normalized[key] = number
    mean = merged["mean"]
    if mean not in MEAN_OPTIONS:
        raise ValueError(
            f"EGARCH param 'mean'={mean!r} вне допустимого набора "
            f"{sorted(MEAN_OPTIONS)}"
        )
    normalized["mean"] = str(mean)
    dist = merged["dist"]
    if dist not in DIST_OPTIONS:
        raise ValueError(
            f"EGARCH param 'dist'={dist!r} вне допустимого набора "
            f"{sorted(DIST_OPTIONS)}"
        )
    normalized["dist"] = str(dist)
    alpha = merged["alpha"]
    try:
        alpha_value = float(alpha)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"EGARCH param 'alpha'={alpha!r} не числовой") from exc
    if alpha_value not in ALPHA_OPTIONS:
        raise ValueError(
            f"EGARCH param 'alpha'={alpha_value} вне допустимого набора "
            f"{sorted(ALPHA_OPTIONS)}"
        )
    normalized["alpha"] = alpha_value
    return normalized


def _validated_returns(returns: Sequence[float]) -> np.ndarray:
    vector = np.asarray([float(value) for value in returns], dtype=float)
    if vector.size == 0:
        raise ValueError("EGARCH: train fold returns пуст")
    if not np.isfinite(vector).all():
        raise ValueError(
            "EGARCH: returns содержат NaN/Inf -- импутация запрещена "
            "(fail-closed)"
        )
    return vector


def _asymmetry_block(fitted: Any, order: int) -> dict[str, Any]:
    """Честная asymmetry-статистика официального фита arch (ядро Task 136).

    gamma-коэффициенты, их стандартные ошибки и Wald p-value берутся из
    fitted.params/std_err/pvalues (ничего не пересчитывается и не
    выдумывается); leverage_direction -- из знаковой структуры gamma;
    asymmetry_significant -- есть ли gamma-член значимый на уровне
    ASYMMETRY_SIGNIFICANCE_LEVEL.  o >= 1 гарантирован validate'ором.
    """
    fit_params = {str(key): float(value) for key, value in fitted.params.items()}
    std_errors = {
        str(key): float(value) for key, value in fitted.std_err.items()
    }
    pvalues = {str(key): float(value) for key, value in fitted.pvalues.items()}
    gamma_keys = sorted(
        (key for key in fit_params if key.startswith("gamma[")),
        key=lambda name: int(name.split("[")[1].rstrip("]")),
    )
    gamma_params = {key: fit_params[key] for key in gamma_keys}
    gamma_std_errors = {key: std_errors[key] for key in gamma_keys}
    gamma_pvalues = {key: pvalues[key] for key in gamma_keys}
    signs = {np.sign(gamma_params[key]) for key in gamma_keys}
    if not signs:
        direction: Optional[str] = None
    elif signs == {-1.0}:
        direction = "negative"
    elif signs == {1.0}:
        direction = "positive"
    else:
        direction = "mixed"
    significant = (
        bool(any(gamma_pvalues[key] < ASYMMETRY_SIGNIFICANCE_LEVEL
                 for key in gamma_keys))
        if gamma_keys
        else None
    )
    return {
        "order": int(order),
        "gamma_params": gamma_params,
        "gamma_std_errors": gamma_std_errors,
        "gamma_pvalues": gamma_pvalues,
        "leverage_direction": direction,
        "asymmetry_significant": significant,
        "significance_level": ASYMMETRY_SIGNIFICANCE_LEVEL,
        "note": (
            "gamma < 0 -- классический leverage: отрицательные шоки "
            "повышают условную дисперсию сильнее положительных того же "
            "масштаба; значимость -- Wald p-values официального фита arch"
        ),
    }


def _egarch_fit_predict(
    returns: Sequence[float],
    horizon: int,
    *,
    params: Optional[Mapping[str, Any]] = None,
    random_state: int = 42,
) -> dict[str, Any]:
    """Нативный EGARCH fit/forecast на переданном train-срезе returns.

    Возвращает payload: ``variance_forecast`` -- официальный прогноз
    условной дисперсии arch (method="simulation", variance.values ==
    среднее путей; horizon,); ``lower``/``upper`` -- квантили тех же
    путей на уровне ``alpha`` (детерминизм -- сидированный rng-callable);
    ``asymmetry`` -- leverage/asymmetry-блок ядра Task 136;
    ``params``/``persistence``/``convergence_flag``/``std_residuals``/
    ``conditional_volatility`` -- вход диагностики движка
    (standardized_residual_diagnostics, volatility-блок fold'а).
    random_state принят по контракту реестра: управляет симуляцией
    (MLE-параметры от seed не зависят).
    """
    if int(horizon) < 1:
        raise ValueError("EGARCH: horizon должен быть положительным")
    normalized = validate_egarch_params(params)
    vector = _validated_returns(returns)
    nobs = vector.size
    if nobs < EGARCH_MIN_TRAIN:
        raise ValueError(
            f"EGARCH: история слишком короткая ({nobs} returns); минимум "
            f"{EGARCH_MIN_TRAIN} (MIN_RETURNS_OBSERVATIONS контракта Task 134)"
        )

    from arch import arch_model

    try:
        model = arch_model(
            vector, mean=normalized["mean"], vol="EGARCH",
            p=normalized["p"], o=normalized["o"], q=normalized["q"],
            dist=normalized["dist"],
            rescale=False,  # БЕЗ скрытого масштабирования входа
        )
        fitted = model.fit(
            disp="off", show_warning=False,
            options={"maxiter": EGARCH_MAXITER},  # явный бюджет сходимости
        )
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 -- library-native отказ = ошибка fold'а
        raise ValueError(
            f"EGARCH: fit недоступен на переданном train-срезе: {exc}"
        ) from exc

    convergence_flag = int(fitted.convergence_flag)
    if convergence_flag != 0:
        raise ValueError(
            f"EGARCH: MLE не сошелся (convergence_flag={convergence_flag}); "
            "несошедшийся фит не является честным прогнозом дисперсии "
            "(fail-closed)"
        )

    # Точечный прогноз и интервалы -- один официальный симуляционный
    # контур: variance.values == среднее путей (probe fact 5), квантили
    # -- по тем же путям.  rng-callable -- сидированный numpy-генератор
    # (параметр random_state у arch отвечает только за method="bootstrap").
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
        variance_forecast = np.asarray(
            simulated.variance.values[-1], dtype=float,
        )
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            f"EGARCH: симуляционный прогноз дисперсии недоступен: {exc}"
        ) from exc
    if paths.shape != (INTERVAL_SIMULATIONS, int(horizon)):
        raise ValueError(
            f"EGARCH: форма симуляционных путей {paths.shape} не "
            f"соответствует ({INTERVAL_SIMULATIONS}, {int(horizon)})"
        )
    if variance_forecast.shape != (int(horizon),):
        raise ValueError(
            f"EGARCH: arch вернул прогноз формы {variance_forecast.shape}, "
            f"ожидалось ({int(horizon)},)"
        )
    if not np.isfinite(variance_forecast).all() or (variance_forecast <= 0).any():
        raise ValueError(
            "EGARCH: прогноз дисперсии должен быть строго положительным "
            "(sigma2 <= 0 -- отказ без clamp-подмен)"
        )

    quantiles = (alpha_level / 2.0, 1.0 - alpha_level / 2.0)
    lower = np.quantile(paths, quantiles[0], axis=0)
    upper = np.quantile(paths, quantiles[1], axis=0)
    # Инвариант lower <= point <= upper обязан держаться нативно (среднее
    # путей внутри их квантильного коридора); численная защита от
    # вырожденного квантиля (не меняет честный прогноз).
    lower = np.minimum(lower, variance_forecast)
    upper = np.maximum(upper, variance_forecast)

    fit_params = {str(key): float(value) for key, value in fitted.params.items()}
    # Честный аналог persistence GARCH: EGARCH -- AR(q) по log-дисперсии,
    # mean-reversion управляется суммой beta (arch НЕ предоставляет
    # fitted.persistence для EGARCH -- probe fact 10).
    beta_keys = [key for key in fit_params if key.startswith("beta[")]
    persistence = float(sum(fit_params[key] for key in beta_keys))
    std_residuals = np.asarray(fitted.std_resid, dtype=float)
    if not np.isfinite(std_residuals).all():
        raise ValueError(
            "EGARCH: стандартизованные остатки содержат NaN/Inf -- "
            "диагностика контракта неинтерпретируема (fail-closed)"
        )
    conditional_volatility = np.asarray(
        fitted.conditional_volatility, dtype=float,
    )

    return {
        "adapter_id": EGARCH_ADAPTER_ID,
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
        "asymmetry": _asymmetry_block(fitted, normalized["o"]),
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


def run_egarch_backtest(
    series: Sequence[float],
    train_ratio: float,
    seasonal_period: int,
) -> None:
    """Legacy synthetic-demo эндпоинт (POST /v1/models/backtest), сигнатура
    как у остальных model_impls.  Task 136: target EGARCH -- условная
    дисперсия ДОХОДНОСТЕЙ; преобразование цены в returns -- ЯВНЫЙ выбор
    volatility-контракта Task 134 (method=log/simple), а не скрытое
    решение однорядного synthetic-эндпоинта.  Никаких синтетических демо и
    Naive-fallback: честный отказ (ValueError), как у GARCH/VAR/VECM/ML."""
    raise ValueError(
        "EGARCH прогнозирует условную дисперсию доходностей: преобразование "
        "цены в returns должно быть явным (volatility-контракт Task 134, "
        "method=log/simple); однорядный synthetic-эндпоинт не применим -- "
        "исполняйте EGARCH через session backtest volatility-движка "
        "(run_volatility_backtest_plan)"
    )


__all__ = [
    "ALPHA_OPTIONS",
    "ASYMMETRY_SIGNIFICANCE_LEVEL",
    "DEFAULT_PARAMS",
    "DIST_OPTIONS",
    "EGARCH_ADAPTER_ID",
    "EGARCH_MAXITER",
    "EGARCH_MIN_TRAIN",
    "INTERVAL_SIMULATIONS",
    "MEAN_OPTIONS",
    "PARAM_BOUNDS",
    "_egarch_fit_predict",
    "run_egarch_backtest",
    "validate_egarch_params",
]
