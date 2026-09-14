# tests/unit/test_forecasting.py
# TDD RED: вычислительное ядро прогнозирования (spec_forecasting2.md §3-§5).
# Методы интервалов: аналитический (реальный statsmodels-фит + паритет-гейт),
# параметрическая симуляция (реальный фит), эмпирический OOF-квантиль,
# нативный адаптер (fake-реестр с детерминированным адаптером).
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.forecasting_contract import resolve_forecast_alpha
from apps.api.final_fit import build_final_fit
from apps.api.forecasting import (
    ForecastingError,
    compute_forecast,
    compute_forecast_coverage,
    empirical_step_quantiles,
    forecast_anomaly_flags,
    future_date_labels,
)


# ── Фикстуры ──────────────────────────────────────────────────────


def _frame(n: int = 96) -> pd.DataFrame:
    t = np.arange(n, dtype=float)
    return pd.DataFrame({
        "date": pd.date_range("2018-01-01", periods=n, freq="MS").astype(str),
        "value": 100 + 0.4 * t + 7 * np.sin(2 * np.pi * t / 12),
    })


class _FakeRegistry:
    """Детерминированный fake-адаптер: точка = последний уровень, интервал --
    симметричные границы в TRANSFORMED-пространстве (проверяется инверсия)."""

    def __init__(self, spread: float = 5.0) -> None:
        self.spread = spread
        self.requests: list[object] = []

    def execute(self, model_id, request):
        from apps.api.model_execution import ModelExecutionResult

        self.requests.append(request)
        point = [float(request.target[-1])] * int(request.horizon)
        lower = [float(request.target[-1]) - self.spread] * int(request.horizon)
        upper = [float(request.target[-1]) + self.spread] * int(request.horizon)
        return ModelExecutionResult(
            forecast=point, lower_interval=lower, upper_interval=upper,
            metadata={"adapter": "fake"},
        )


def _identity_fit(frame: pd.DataFrame):
    return build_final_fit(
        frame, target_column="value", date_column="date",
        transformations={}, scaling_recipe={},
    )


def _oof_predictions(residuals_by_step: dict[int, list[float]]) -> list[dict]:
    points = []
    for step, residuals in residuals_by_step.items():
        for fold, residual in enumerate(residuals):
            points.append({
                "fold": fold, "horizon_step": step, "index": step,
                "label": f"2025-{step:02d}", "actual": 100.0,
                "predicted": 100.0 - residual, "residual": residual,
            })
    return points


# ── Эмпирический метод (§4.2) ─────────────────────────────────────


def test_empirical_step_quantiles_group_by_horizon_step():
    oof = _oof_predictions({1: [-2.0, 2.0, 0.0, 1.0, -1.0], 2: [-6.0, 6.0, 0.0]})
    low, high = empirical_step_quantiles(oof, 0.05)
    assert set(low) == {1, 2}
    assert low[1] <= high[1]
    # Ширина интервала шага 2 больше шага 1 (неопределённость растёт с горизонтом).
    assert high[2] - low[2] > high[1] - low[1]


def test_empirical_interval_is_point_plus_step_quantile_in_original_scale():
    frame = _frame()
    fit = _identity_fit(frame)
    oof = _oof_predictions({1: [-2.0, 2.0, 0.5, -0.5], 2: [-4.0, 4.0, 1.0, -1.0], 3: [-6.0, 6.0, 1.5, -1.5]})
    registry = _FakeRegistry()
    computation = compute_forecast(
        model_id="naive", horizon=3,
        alpha_resolution=resolve_forecast_alpha("naive", 0.05, {}),
        final_fit=fit, seasonal_period=12, params={},
        registry=registry, history_values=fit.source_values,
        history_labels=fit.history_labels,
        future_labels=future_date_labels(pd.DatetimeIndex(frame["date"]), 3),
        oof_predictions=oof, validated_horizon=6,
    )
    assert computation.ci_method == "empirical_oof_quantile"
    assert computation.coverage is not None
    assert len(computation.points) == 3
    # Точка fake-реестра = последний уровень; границы = точка + квантиль шага.
    point = computation.points[0]["value"]
    assert computation.points[0]["ci_lower"] < point < computation.points[0]["ci_upper"]
    # Шаг 3 НЕ превышает validated_horizon=6 -- без warning'а экстраполяции.
    assert not any("консервативная" in warning for warning in computation.warnings)
    # Fake-реестр получил timestamps истории и будущего.
    request = registry.requests[0]
    assert len(request.train_timestamps) == len(frame)
    assert len(request.future_timestamps) == 3


def test_empirical_interval_beyond_validated_horizon_uses_last_step_with_warning():
    frame = _frame()
    fit = _identity_fit(frame)
    oof = _oof_predictions({1: [-2.0, 2.0], 2: [-4.0, 4.0]})
    computation = compute_forecast(
        model_id="naive", horizon=4,
        alpha_resolution=resolve_forecast_alpha("naive", 0.05, {}),
        final_fit=fit, seasonal_period=12, params={},
        registry=_FakeRegistry(), history_values=fit.source_values,
        history_labels=fit.history_labels,
        future_labels=future_date_labels(pd.DatetimeIndex(frame["date"]), 4),
        oof_predictions=oof, validated_horizon=2,
    )
    # Шаги 3..4 -- квантиль последнего валидированного шага (2).
    assert computation.points[2]["ci_lower"] == pytest.approx(computation.points[3]["ci_lower"])
    assert any(
        "консервативная оценка по последнему проверенному шагу" in warning
        for warning in computation.warnings
    )
    # §5.1: для empirical это функциональное ограничение, текст честный.
    assert any("не валидирован эмпирически" in warning for warning in computation.warnings)


def test_empirical_method_without_oof_history_fails_closed():
    frame = _frame()
    fit = _identity_fit(frame)
    with pytest.raises(ForecastingError, match="OOF"):
        compute_forecast(
            model_id="naive", horizon=3,
            alpha_resolution=resolve_forecast_alpha("naive", 0.05, {}),
            final_fit=fit, seasonal_period=12, params={},
            registry=_FakeRegistry(), history_values=fit.source_values,
            history_labels=fit.history_labels, future_labels=None,
            oof_predictions=[], validated_horizon=6,
        )


def test_empirical_coverage_is_share_of_oof_points_inside_interval():
    # Статистическое свойство: in-sample покрытие центрального (1-alpha)
    # квантильного интервала близко к номиналу на достаточной выборке;
    # добавленный выброс (1000.0) честно снижает покрытие ниже 1.0.
    rng = np.random.default_rng(20261)
    oof = []
    steps_residuals = {1: rng.normal(0, 2, 200), 2: rng.normal(0, 4, 200)}
    for step, residuals in steps_residuals.items():
        for fold, residual in enumerate(residuals):
            oof.append({
                "fold": fold, "horizon_step": step, "index": step,
                "label": f"2025-{step:02d}", "actual": 100.0,
                "predicted": 100.0 - residual, "residual": residual,
            })
    baseline = compute_forecast_coverage(oof, 0.05)
    assert baseline is not None and 0.90 <= baseline <= 1.0
    oof.append({
        "fold": 0, "horizon_step": 1, "index": 999, "label": "2025-12",
        "actual": 100.0, "predicted": 0.0, "residual": 1000.0,
    })
    spiked = compute_forecast_coverage(oof, 0.05)
    assert spiked is not None and spiked < baseline


# ── Аналитический метод (§4.1, реальные statsmodels-фиты) ────────


def test_analytic_arima_interval_honors_alpha_and_passes_parity_gate():
    frame = _frame()
    fit = _identity_fit(frame)
    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY

    computation = compute_forecast(
        model_id="arima", horizon=6,
        alpha_resolution=resolve_forecast_alpha("arima", 0.05, {}),
        final_fit=fit, seasonal_period=12, params={},
        registry=MODEL_EXECUTION_REGISTRY, history_values=fit.source_values,
        history_labels=fit.history_labels,
        future_labels=future_date_labels(pd.DatetimeIndex(frame["date"]), 6),
        oof_predictions=[], validated_horizon=6,
    )
    points = computation.points
    assert all(p["ci_lower"] < p["value"] < p["ci_upper"] for p in points)
    # alpha=0.05: интервал шире, чем при alpha=0.20 (та же модель/данные).
    wide = compute_forecast(
        model_id="arima", horizon=6,
        alpha_resolution=resolve_forecast_alpha("arima", 0.20, {}),
        final_fit=fit, seasonal_period=12, params={},
        registry=MODEL_EXECUTION_REGISTRY, history_values=fit.source_values,
        history_labels=fit.history_labels,
        future_labels=future_date_labels(pd.DatetimeIndex(frame["date"]), 6),
        oof_predictions=[], validated_horizon=6,
    )
    widths_05 = [p["ci_upper"] - p["ci_lower"] for p in points]
    widths_20 = [p["ci_upper"] - p["ci_lower"] for p in wide.points]
    assert all(w05 > w20 for w05, w20 in zip(widths_05, widths_20))
    assert computation.metadata["interval_provenance"]["method"] == "analytic"


def test_analytic_theta_uses_prediction_intervals_api():
    frame = _frame()
    fit = _identity_fit(frame)
    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY

    computation = compute_forecast(
        model_id="theta", horizon=4,
        alpha_resolution=resolve_forecast_alpha("theta", 0.05, {}),
        final_fit=fit, seasonal_period=12, params={},
        registry=MODEL_EXECUTION_REGISTRY, history_values=fit.source_values,
        history_labels=fit.history_labels,
        future_labels=future_date_labels(pd.DatetimeIndex(frame["date"]), 4),
        oof_predictions=[], validated_horizon=6,
    )
    assert all(p["ci_lower"] < p["value"] < p["ci_upper"] for p in computation.points)
    assert computation.metadata["interval_provenance"]["api"] == "prediction_intervals"


# ── Параметрическая симуляция (§4.1a) ────────────────────────────


@pytest.mark.parametrize("model_id", ["ets", "ets_damped"])
def test_ets_parametric_simulation_envelope_around_point(model_id: str):
    frame = _frame()
    fit = _identity_fit(frame)
    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY

    computation = compute_forecast(
        model_id=model_id, horizon=6,
        alpha_resolution=resolve_forecast_alpha(model_id, 0.05, {}),
        final_fit=fit, seasonal_period=12,
        params={"trend": "add", "seasonal": "add", "seasonal_periods": 12},
        registry=MODEL_EXECUTION_REGISTRY, history_values=fit.source_values,
        history_labels=fit.history_labels,
        future_labels=future_date_labels(pd.DatetimeIndex(frame["date"]), 6),
        oof_predictions=[], validated_horizon=6,
    )
    assert computation.ci_method == "parametric_simulation"
    assert all(p["ci_lower"] < p["value"] < p["ci_upper"] for p in computation.points)
    assert computation.metadata["interval_provenance"]["trajectories"] > 0


def test_ets_simulation_is_deterministic_for_fixed_seed():
    frame = _frame()
    fit = _identity_fit(frame)
    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY

    kwargs = dict(
        model_id="ets", horizon=4,
        alpha_resolution=resolve_forecast_alpha("ets", 0.05, {}),
        final_fit=fit, seasonal_period=12,
        params={"trend": "add", "seasonal": None},
        registry=MODEL_EXECUTION_REGISTRY, history_values=fit.source_values,
        history_labels=fit.history_labels,
        future_labels=future_date_labels(pd.DatetimeIndex(frame["date"]), 4),
        oof_predictions=[], validated_horizon=6, random_state=20261,
    )
    first = compute_forecast(**kwargs)
    second = compute_forecast(**kwargs)
    assert [p["ci_lower"] for p in first.points] == [p["ci_lower"] for p in second.points]


# ── Нативный адаптер (fake-реестр) + инверсия границ ─────────────


def test_native_adapter_boundaries_are_inverted_each_separately():
    # Лог-разностная цепочка: fake-адаптер отдаёт СИММЕТРИЧНЫЙ интервал в
    # transformed-пространстве; в исходной шкале границы обязаны
    # инвертироваться по отдельности (§3) и остаться в порядке lower<point<upper.
    frame = _frame(96)
    frame["value"] = frame["value"].abs() + 50
    transformations = {
        "value_logdiff": {
            "kind": "stationarity", "method": "log_difference",
            "seasonal_period": 12,
            "source_column": "value", "inverse_supported": True,
        },
    }
    fit = build_final_fit(
        frame, target_column="value_logdiff", date_column="date",
        transformations=transformations, scaling_recipe={},
    )
    registry = _FakeRegistry(spread=0.01)
    computation = compute_forecast(
        model_id="lstm", horizon=3,
        alpha_resolution=resolve_forecast_alpha("lstm", 0.05, {}),
        final_fit=fit, seasonal_period=12, params={},
        registry=registry, history_values=fit.source_values,
        history_labels=fit.history_labels,
        future_labels=future_date_labels(pd.DatetimeIndex(frame["date"]), 3),
        oof_predictions=[], validated_horizon=6,
    )
    assert computation.ci_method == "native_adapter"
    assert all(p["ci_lower"] < p["value"] < p["ci_upper"] for p in computation.points)
    assert computation.metadata["interval_provenance"]["source"] == "registry native adapter"


def test_native_adapter_without_registry_intervals_fails_closed():
    from apps.api.model_execution import ModelExecutionResult

    class _PointOnlyRegistry(_FakeRegistry):
        def execute(self, model_id, request):
            return ModelExecutionResult(
                forecast=[float(request.target[-1])] * int(request.horizon),
            )

    frame = _frame()
    fit = _identity_fit(frame)
    with pytest.raises(ForecastingError, match="без интервалов"):
        compute_forecast(
            model_id="prophet", horizon=3,
            alpha_resolution=resolve_forecast_alpha("prophet", 0.20, {}),
            final_fit=fit, seasonal_period=12, params={},
            registry=_PointOnlyRegistry(), history_values=fit.source_values,
            history_labels=fit.history_labels,
            future_labels=future_date_labels(pd.DatetimeIndex(frame["date"]), 3),
            oof_predictions=[], validated_horizon=6,
        )


def test_neural_alpha_is_injected_into_registry_params():
    frame = _frame()
    fit = _identity_fit(frame)
    registry = _FakeRegistry()
    compute_forecast(
        model_id="lstm", horizon=3,
        alpha_resolution=resolve_forecast_alpha("lstm", 0.01, {"alpha": 0.05}),
        final_fit=fit, seasonal_period=12, params={"alpha": 0.05},
        registry=registry, history_values=fit.source_values,
        history_labels=fit.history_labels,
        future_labels=future_date_labels(pd.DatetimeIndex(frame["date"]), 3),
        oof_predictions=[], validated_horizon=6,
    )
    assert registry.requests[0].params["alpha"] == 0.01


# ── Предупреждение о горизонте (§5.1) ────────────────────────────


def test_horizon_beyond_validated_range_warns_for_analytic_method():
    frame = _frame()
    fit = _identity_fit(frame)
    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY

    computation = compute_forecast(
        model_id="arima", horizon=10,
        alpha_resolution=resolve_forecast_alpha("arima", 0.05, {}),
        final_fit=fit, seasonal_period=12, params={},
        registry=MODEL_EXECUTION_REGISTRY, history_values=fit.source_values,
        history_labels=fit.history_labels,
        future_labels=future_date_labels(pd.DatetimeIndex(frame["date"]), 10),
        oof_predictions=[], validated_horizon=6,
    )
    assert any(
        "превышает проверенный бэктестом диапазон" in warning
        for warning in computation.warnings
    )


def test_prophet_requires_regular_calendar_grid():
    frame = _frame()
    fit = _identity_fit(frame)
    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY

    with pytest.raises(ForecastingError, match="регулярн"):
        compute_forecast(
            model_id="prophet", horizon=3,
            alpha_resolution=resolve_forecast_alpha("prophet", 0.20, {}),
            final_fit=fit, seasonal_period=12, params={},
            registry=MODEL_EXECUTION_REGISTRY, history_values=fit.source_values,
            history_labels=fit.history_labels,
            future_labels=None,  # нерегулярная сетка
            oof_predictions=[], validated_horizon=6,
        )


# ── Аномалии прогнозных точек (§5.8) ─────────────────────────────


def test_anomaly_flags_come_from_reused_outlier_detector_on_combined_series():
    history = list(np.linspace(90.0, 110.0, 44))
    forecast = [102.0, 500.0]  # вторая точка -- выброс относительно истории
    flags = forecast_anomaly_flags(history, forecast)
    assert flags == [False, True]


def test_forecast_points_carry_anomaly_flags_from_combined_detection():
    frame = _frame()
    fit = _identity_fit(frame)
    oof = _oof_predictions({1: [-2.0, 2.0], 2: [-4.0, 4.0]})
    class _SpikeRegistry(_FakeRegistry):
        def execute(self, model_id, request):
            from apps.api.model_execution import ModelExecutionResult

            point = [float(request.target[-1]), 10000.0, float(request.target[-1])]
            return ModelExecutionResult(forecast=point)
    computation = compute_forecast(
        model_id="naive", horizon=3,
        alpha_resolution=resolve_forecast_alpha("naive", 0.05, {}),
        final_fit=fit, seasonal_period=12, params={},
        registry=_SpikeRegistry(), history_values=fit.source_values,
        history_labels=fit.history_labels,
        future_labels=future_date_labels(pd.DatetimeIndex(frame["date"]), 3),
        oof_predictions=oof, validated_horizon=6,
    )
    assert [p["is_anomalous"] for p in computation.points] == [False, True, False]
