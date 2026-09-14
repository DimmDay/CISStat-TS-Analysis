# apps/api/forecasting.py
"""Вычислительное ядро этапа Прогнозирование (spec_forecasting2.md §3-§5).

Потребляет Model Card (model_id, замороженные hyperparameters, training
preprocessing, performance.backtest_metrics/oof_predictions) и строит
реальный прогноз вперёд:

1. Финальный рефит: forward-цепочка target-препроцессинга ОДИН раз на
   полной истории (apps/api/final_fit.py) -- переобучение на всех доступных
   данных с замороженными гиперпараметрами (FPP3 гл. 5.9), без повторного
   тюнинга.
2. Точечный прогноз -- ЕДИНСТВЕННАЯ сертифицированная точка исполнения:
   MODEL_EXECUTION_REGISTRY.execute (Model Execution Contract v2, Task 122+).
   Спецификация v3 писалась против compatibility-facade PRODUCTION_PREDICTORS
   (backtesting.py) -- фасад сам построен поверх реестра; финальный рефит
   обязан идти напрямую через реестр с полным lineage-контрактом.
3. Интервалы -- методологический выбор по семейству модели (§4), НО каждая
   граница инвертируется отдельным вызовом restore() (§3).
4. Для analytic/parametric_simulation интервалы требуют объект фита:
   модуль делает СОПРЯЖЁННЫЙ фит тем же классом модели на тех же данных и
   с теми же параметрами, что и реестровый executor, и прижимает честность
   паритет-гейтом точечного прогноза (расхождение реестра и интервального
   фита -- ошибка, а не молчаливая подмена).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from app.preprocessing.outliers import detect_outlier_mask
from apps.api.final_fit import FinalFitResult
from apps.api.forecasting_contract import (
    CI_METHODS,
    NEURAL_ALPHA_MODELS,
    interval_method_for_model,
)
from apps.api.model_impls.arima import DEFAULT_ARIMA_ORDER, _auto_arima_select_order


class ForecastingError(ValueError):
    """Честный отказ контура прогнозирования (маппится в 422)."""


# Модели, чей контракт исполнения требует реальных будущих дат
# (проверка registry: _prophet_executor отклоняет пустой future_timestamps).
MODELS_REQUIRING_FUTURE_DATES = {"prophet"}

# Дискретизация паритет-гейта: реестровый executor и интервальный фит
# исполняют один и тот же детерминированный MLE на одинаковых данных.
_PARITY_RTOL = 1e-6
_PARITY_ATOL = 1e-9

DEFAULT_SIMULATION_TRAJECTORIES = 500


@dataclass
class ForecastComputation:
    """Результат вычисления прогноза до сборки ForecastRun."""

    points: list[dict[str, Any]]
    ci_method: str
    alpha_effective: float
    alpha_source: str
    warnings: list[str] = field(default_factory=list)
    coverage: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def future_date_labels(index: pd.DatetimeIndex, horizon: int) -> list[str] | None:
    """Продолжить регулярную календарную сетку на horizon шагов вперёд.

    Возвращает None для нерегулярной сетки: у прогноза с реальными датами
    нет честной оси. Потребители, требующие дат (Prophet), отказывают
    fail-closed; остальные получают позиционную ось.
    """
    if len(index) < 3:
        return None
    try:
        freq = pd.infer_freq(index)
    except (ValueError, TypeError):
        return None
    if freq is None:
        return None
    future = pd.date_range(start=index[-1], periods=horizon + 1, freq=freq)[1:]
    return [stamp.isoformat() for stamp in future]


# ── Эмпирический метод (§4.2) ─────────────────────────────────────


def empirical_step_quantiles(
    oof_predictions: Sequence[Mapping[str, Any]], alpha: float,
) -> tuple[dict[int, float], dict[int, float]]:
    """Квантили OOF-остатков по каждому horizon_step.

    Остатки хранятся бэктестом по точкам (fold, horizon_step, ...) в шкале
    evaluation (исходной для обратимой цепочки) -- тот же масштаб, в котором
    отдаётся прогноз, поэтому интервал строится ПРЯМО в исходной шкале:
    interval(h) = forecast(h) + quantile(residuals[h], [alpha/2, 1-alpha/2]).
    """
    residuals_by_step: dict[int, list[float]] = {}
    for point in oof_predictions:
        step = int(point["horizon_step"])
        residual = float(point["residual"])
        if not np.isfinite(residual):
            raise ForecastingError(
                "OOF-остатки содержат нечисловые значения; эмпирический "
                "интервал построить нельзя"
            )
        residuals_by_step.setdefault(step, []).append(residual)
    if not residuals_by_step:
        raise ForecastingError(
            "OOF-остатки бэктеста отсутствуют: эмпирический интервал строить "
            "не из чего (модель должна пройти backtest до прогноза)"
        )
    low: dict[int, float] = {}
    high: dict[int, float] = {}
    for step, residuals in residuals_by_step.items():
        low[step] = float(np.quantile(residuals, alpha / 2))
        high[step] = float(np.quantile(residuals, 1 - alpha / 2))
    return low, high


def compute_forecast_coverage(
    oof_predictions: Sequence[Mapping[str, Any]], alpha: float,
) -> float | None:
    """Фактическое покрытие OOF-точек ретроспективными интервалами (§4.3).

    In-sample по OOF-остаткам той же модели: доля точек, попавших в
    интервал, построенный из квантилей остатков СВОЕГО horizon_step.
    Заполняется ТОЛЬКО для empirical_oof_quantile (интервалы других методов
    нельзя задним числом посчитать по OOF без переобучения на каждом
    train-фолде).
    """
    if not oof_predictions:
        return None
    low, high = empirical_step_quantiles(oof_predictions, alpha)
    covered = 0
    total = 0
    for point in oof_predictions:
        step = int(point["horizon_step"])
        actual = float(point["actual"])
        total += 1
        if low[step] <= actual - float(point["predicted"]) <= high[step]:
            covered += 1
    return covered / total if total else None


def _empirical_bounds(
    point_orig: np.ndarray, oof_predictions: Sequence[Mapping[str, Any]],
    alpha: float, horizon: int, warnings: list[str],
) -> tuple[np.ndarray, np.ndarray]:
    low_by_step, high_by_step = empirical_step_quantiles(oof_predictions, alpha)
    last_validated = max(low_by_step)
    lower = np.empty(horizon, dtype=float)
    upper = np.empty(horizon, dtype=float)
    for step in range(1, horizon + 1):
        if step in low_by_step:
            lower[step - 1] = low_by_step[step]
            upper[step - 1] = high_by_step[step]
        else:
            # §5.1: за границей training.horizon квантиль считать не из чего;
            # используется квантиль последнего валидированного шага + честный
            # warning (интервал НЕ экстраполируется молча).
            lower[step - 1] = low_by_step[last_validated]
            upper[step - 1] = high_by_step[last_validated]
    if horizon > last_validated:
        warnings.append(
            f"Интервал для шагов {last_validated + 1}–{horizon} — консервативная "
            f"оценка по последнему проверенному шагу (horizon_step={last_validated}), "
            "не валидирован эмпирически"
        )
    return point_orig + lower, point_orig + upper


# ── Аналитический метод (§4.1) ────────────────────────────────────


def _arima_params(params: Mapping[str, Any]) -> tuple[int, int, int]:
    order = tuple(
        int(params.get(key, DEFAULT_ARIMA_ORDER[index]))
        for index, key in enumerate(("p", "d", "q"))
    )
    return order  # type: ignore[return-value]


def _analytic_interval(
    model_id: str, model_train: np.ndarray, horizon: int, alpha: float,
    params: Mapping[str, Any], seasonal_period: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Сопряжённый fit тем же классом модели -> точка + границы (transformed).

    ARIMA/Auto-ARIMA: get_forecast(steps).summary_frame(alpha) (§4.1);
    Theta: ThetaModelResults.prediction_intervals(steps, theta, alpha) --
    другой API, get_forecast на ThetaModelResults не существует (§10.3).
    Конструкторная логика зеркалит сертифицированные адаптеры
    (apps/api/model_impls/{arima,theta}.py); дрейф зеркала ловит
    паритет-гейт, а не пользователь.
    """
    if model_id in {"arima", "auto_arima"}:
        from statsmodels.tsa.arima.model import ARIMA

        order = (
            _auto_arima_select_order(model_train)
            if model_id == "auto_arima"
            else _arima_params(params)
        )
        api = "get_forecast().summary_frame"
    else:  # theta
        from statsmodels.tsa.forecasting.theta import ThetaModel

        order = None
        api = "prediction_intervals"

    if model_id in {"arima", "auto_arima"}:
        fitted = ARIMA(np.asarray(model_train, dtype=float), order=order).fit()
        frame = fitted.get_forecast(steps=horizon).summary_frame(alpha=alpha)
        point = frame["mean"].to_numpy(dtype=float)
        lower = frame["mean_ci_lower"].to_numpy(dtype=float)
        upper = frame["mean_ci_upper"].to_numpy(dtype=float)
    else:
        # Зеркало _theta_fit_predict: константный ряд -> naive-прогноз без
        # распределения (интервал вырожден честно), период -- как в адаптере.
        values = np.asarray(model_train, dtype=float)
        if len(np.unique(values)) == 1:
            point = np.full(horizon, float(values[-1]))
            return point, point.copy(), point.copy(), {"api": api, "degenerate": "constant_series"}
        use_seasonal = seasonal_period > 1 and len(values) >= 2 * seasonal_period
        series = pd.Series(values, index=pd.RangeIndex(start=0, stop=len(values)))
        kwargs: dict[str, Any] = {}
        if use_seasonal:
            kwargs["period"] = int(seasonal_period)
            kwargs["deseasonalize"] = True
        else:
            kwargs["deseasonalize"] = False
        fitted = ThetaModel(series, method="auto", **kwargs).fit()
        point = np.asarray(fitted.forecast(steps=horizon), dtype=float)
        intervals = fitted.prediction_intervals(steps=horizon, alpha=alpha)
        lower = intervals["lower"].to_numpy(dtype=float)
        upper = intervals["upper"].to_numpy(dtype=float)
    return point, lower, upper, {"api": api, "order": list(order) if order else None}


# ── Параметрическая симуляция (§4.1a) ─────────────────────────────


def _simulation_interval(
    model_id: str, model_train: np.ndarray, horizon: int, alpha: float,
    seasonal_period: int, params: Mapping[str, Any],
    trajectories: int, random_state: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """HoltWintersResults.simulate -- параметрическая (Monte-Carlo) симуляция
    на основе дисперсии подобранных инноваций; интервал -- эмпирические
    квантили по траекториям ОДНОЙ подобранной модели (не OOF-остатки, §4.1a)."""
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    force_damped = model_id == "ets_damped"
    period = int(params.get("seasonal_periods", seasonal_period))
    trend = params.get("trend", "add")
    seasonal = params.get("seasonal", "add")
    damped = True if force_damped else bool(params.get("damped_trend", False))
    # Зеркало валидации _ets_fit_predict: мультипликативные варианты требуют
    # строго положительный ряд; сезонность -- не менее 2 полных периодов.
    if trend not in {"add", "mul", None}:
        raise ForecastingError(f"Недопустимый trend ETS: {trend!r}")
    if seasonal not in {"add", "mul", None}:
        raise ForecastingError(f"Недопустимый seasonal ETS: {seasonal!r}")
    if trend == "mul" and any(value <= 0 for value in model_train):
        raise ForecastingError("multiplicative ETS trend requires strictly positive data")
    if seasonal == "mul" and any(value <= 0 for value in model_train):
        raise ForecastingError("multiplicative ETS seasonality requires strictly positive data")
    use_seasonal = (
        seasonal is not None
        and period > 1
        and len(model_train) >= 2 * period
    )
    kwargs: dict[str, Any] = dict(
        trend=trend,
        damped_trend=damped,
        seasonal=seasonal if use_seasonal else None,
        seasonal_periods=period if use_seasonal else None,
        initialization_method="estimated",
    )
    kwargs = {key: value for key, value in kwargs.items() if value is not None}
    fitted = ExponentialSmoothing(
        pd.Series(model_train, index=pd.RangeIndex(start=0, stop=len(model_train))),
        **kwargs,
    ).fit()
    point = np.asarray(fitted.forecast(steps=horizon), dtype=float)
    try:
        simulated = fitted.simulate(
            nsimulations=horizon, repetitions=int(trajectories), anchor="end",
            rng=np.random.default_rng(random_state),
        )
    except TypeError as exc:
        # F-1 (аудит FORECAST-1a): API `rng=` появился в statsmodels 0.15;
        # на 0.14.x simulate() падает сырым TypeError'ом, который не
        # перехватывается роутером (кроме ForecastingError/ValueError) ->
        # 500 вместо честного 422. Fail-closed: честная ошибка с указанием
        # требуемого пола зависимости.
        import statsmodels

        raise ForecastingError(
            "Параметрическая симуляция требует statsmodels>=0.15.0 "
            f"(API simulate(rng=...)), установлена {statsmodels.__version__}: "
            f"{exc}. Поднимите пол зависимости в requirements.txt"
        ) from exc
    trajectories_arr = np.asarray(simulated, dtype=float)
    if trajectories_arr.shape[0] != horizon:
        trajectories_arr = trajectories_arr.T
    lower = np.quantile(trajectories_arr, alpha / 2, axis=1)
    upper = np.quantile(trajectories_arr, 1 - alpha / 2, axis=1)
    details = {
        "api": "HoltWintersResults.simulate",
        "trajectories": int(trajectories),
        "random_state": int(random_state),
        "kwargs": {key: value for key, value in kwargs.items()},
    }
    return point, lower, upper, details


def _assert_parity(
    refit_point: np.ndarray, registry_point: np.ndarray, model_id: str,
) -> None:
    """Паритет-гейт: интервальный фит обязан воспроизводить реестровый прогноз.

    Реестр -- единственная сертифицированная точка исполнения; сопряжённый
    фит существует ТОЛЬКО ради интервала. Расхождение означает дрейф зеркала
    параметров/конструктора -- честная ошибка вместо молчаливой подмены
    источника точечного прогноза.
    """
    if not np.allclose(refit_point, registry_point, rtol=_PARITY_RTOL, atol=_PARITY_ATOL):
        max_diff = float(np.max(np.abs(refit_point - registry_point)))
        raise ForecastingError(
            f"Паритет точечного прогноза нарушен для '{model_id}': реестр и "
            f"интервальный фит разошлись на {max_diff:g}. Честный отказ вместо "
            "прогноза с несогласованной точкой/границами"
        )


# ── Аномалии прогнозных точек (§5.8) ──────────────────────────────


def forecast_anomaly_flags(
    history_values: Sequence[float], point_values: Sequence[float],
    method: str = "iqr", param: Any = 1.5,
) -> list[bool]:
    """Переиспользование detect_outlier_mask (Task 60) на объединении
    «история + прогноз»: прогнозная точка-выброс относительно статистики
    объединённого ряда -- сигнал о неустойчивой экстраполяции (предупреждение,
    не запрет -- тот же принцип, что sanity-правила Наставника)."""
    combined = pd.Series(
        np.concatenate([
            np.asarray(history_values, dtype=float),
            np.asarray(point_values, dtype=float),
        ])
    )
    mask = detect_outlier_mask(combined, method, param)
    return [bool(flag) for flag in mask.to_numpy()[len(history_values):]]


# ── Главная точка входа ───────────────────────────────────────────


def compute_forecast(
    *,
    model_id: str,
    horizon: int,
    alpha_resolution: Any,
    final_fit: FinalFitResult,
    seasonal_period: int,
    params: Mapping[str, Any],
    registry: Any,
    history_values: Sequence[float],
    history_labels: Sequence[str],
    future_labels: Sequence[str] | None,
    oof_predictions: Sequence[Mapping[str, Any]],
    validated_horizon: int | None = None,
    simulation_trajectories: int = DEFAULT_SIMULATION_TRAJECTORIES,
    random_state: int = 42,
) -> ForecastComputation:
    """Строить прогноз: реестровый точечный прогноз + метод-зависимые интервалы.

    Точка ВСЕГДА из реестра (сертифицированный контракт исполнения);
    интервалы -- по ci_method контракта; каждая граница инвертируется
    отдельно; аномалии и предупреждения -- честные производные слои.
    """
    if int(horizon) < 1:
        raise ForecastingError("Горизонт прогноза должен быть положительным")
    ci_method = interval_method_for_model(model_id)
    if ci_method not in CI_METHODS:  # defense-in-depth
        raise ForecastingError(f"Неизвестный метод интервалов: {ci_method}")

    warnings: list[str] = list(alpha_resolution.warnings)
    alpha = float(alpha_resolution.effective_alpha)

    if future_labels is None and model_id in MODELS_REQUIRING_FUTURE_DATES:
        raise ForecastingError(
            "Ряд не имеет регулярной календарной сетки: прогноз модели "
            f"'{model_id}' требует реальных будущих дат; честный отказ вместо "
            "прогноза по вымышленной оси"
        )

    model_params = dict(params)
    if model_id in NEURAL_ALPHA_MODELS:
        # Запрошенная alpha -- сертифицированная ручка нейро-адаптера
        # (whitelist проверен в resolve_forecast_alpha).
        model_params["alpha"] = alpha

    train_timestamps = list(final_fit.model_train_labels)
    future_timestamps = list(future_labels or ())
    result = registry.execute(
        model_id,
        _build_execution_request(
            model_id=model_id, final_fit=final_fit, horizon=horizon,
            seasonal_period=seasonal_period, params=model_params,
            train_timestamps=train_timestamps,
            future_timestamps=future_timestamps,
            random_state=random_state,
        ),
    )
    point_transformed = np.asarray(result.forecast, dtype=float)
    point_orig = final_fit.restore(point_transformed)

    provenance: dict[str, Any] = {}
    parity_checked = False
    if ci_method == "native_adapter":
        lower_transformed = result.lower_interval
        upper_transformed = result.upper_interval
        if lower_transformed is None or upper_transformed is None:
            raise ForecastingError(
                f"Адаптер модели '{model_id}' вернул прогноз без интервалов; "
                "нативный метод неприменим и фиктивные границы запрещены"
            )
        lower = final_fit.restore(np.asarray(lower_transformed, dtype=float))
        upper = final_fit.restore(np.asarray(upper_transformed, dtype=float))
        provenance = {
            "source": "registry native adapter",
            "adapter_alpha": alpha,
        }
    elif ci_method == "analytic":
        refit_point, lower_t, upper_t, details = _analytic_interval(
            model_id, final_fit.model_train, horizon, alpha, model_params,
            seasonal_period,
        )
        _assert_parity(refit_point, point_transformed, model_id)
        lower = final_fit.restore(lower_t)
        upper = final_fit.restore(upper_t)
        provenance = {"source": "conjugate statsmodels fit", "method": "analytic", **details}
        parity_checked = True
    elif ci_method == "parametric_simulation":
        refit_point, lower_t, upper_t, details = _simulation_interval(
            model_id, final_fit.model_train, horizon, alpha, seasonal_period,
            model_params, simulation_trajectories, random_state,
        )
        _assert_parity(refit_point, point_transformed, model_id)
        lower = final_fit.restore(lower_t)
        upper = final_fit.restore(upper_t)
        provenance = {"source": "parametric simulation", "method": "parametric_simulation", **details}
        parity_checked = True
    else:  # empirical_oof_quantile
        lower, upper = _empirical_bounds(
            point_orig, oof_predictions, alpha, horizon, warnings,
        )
        provenance = {"source": "backtest OOF residual quantiles", "method": "empirical_oof_quantile"}

    if (
        validated_horizon is not None
        and horizon > int(validated_horizon)
        and ci_method != "empirical_oof_quantile"
    ):
        warnings.append(
            f"Горизонт {horizon} превышает проверенный бэктестом диапазон "
            f"({int(validated_horizon)}): интервал экстраполирует модельную "
            "структуру за пределы проверенного диапазона"
        )

    flags = forecast_anomaly_flags(history_values, point_orig)
    dates = (
        list(future_labels)
        if future_labels is not None
        else [str(len(history_values) + step) for step in range(1, horizon + 1)]
    )
    if len(dates) < horizon:
        raise ForecastingError(
            "Число будущих меток меньше горизонта; прогноз по неполной оси запрещён"
        )
    points = [
        {
            "step": step,
            "date": dates[step - 1],
            "value": float(point_orig[step - 1]),
            "ci_lower": float(lower[step - 1]),
            "ci_upper": float(upper[step - 1]),
            "is_anomalous": flags[step - 1],
        }
        for step in range(1, horizon + 1)
    ]

    coverage = (
        compute_forecast_coverage(oof_predictions, alpha)
        if ci_method == "empirical_oof_quantile"
        else None
    )

    metadata: dict[str, Any] = {
        "interval_provenance": provenance,
        "n_history": len(history_values),
        "seasonal_period": int(seasonal_period),
        "params": dict(model_params),
        "adapter_warnings": list(result.warnings),
        "adapter_metadata": dict(result.metadata),
        "random_state": int(random_state),
    }
    if parity_checked:
        metadata["parity_gate"] = "ok"
    return ForecastComputation(
        points=points, ci_method=ci_method,
        alpha_effective=alpha, alpha_source=alpha_resolution.alpha_source,
        warnings=warnings, coverage=coverage, metadata=metadata,
    )


def _build_execution_request(
    *, model_id: str, final_fit: FinalFitResult, horizon: int,
    seasonal_period: int, params: Mapping[str, Any],
    train_timestamps: Sequence[str], future_timestamps: Sequence[str],
    random_state: int,
):
    from apps.api.model_execution import ModelExecutionRequest

    return ModelExecutionRequest(
        target=[float(value) for value in final_fit.model_train],
        horizon=int(horizon),
        seasonal_period=int(seasonal_period),
        params=dict(params),
        train_timestamps=tuple(train_timestamps),
        future_timestamps=tuple(future_timestamps),
        random_state=int(random_state),
    )
