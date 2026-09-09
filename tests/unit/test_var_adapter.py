# tests/unit/test_var_adapter.py
"""Task 132 -- VAR: RED-контур тестов нативного адаптера.

Постановка docs/modeling_task_list.md::Task 132 (общая нота серии):
- порядок лага VAR выбирается fold-local (только на переданном train-срезе);
- нативный многомерный прогноз statsmodels с интервалами -- НЕ цикл
  одномерных ARIMA (связь между уравнениями обязана работать);
- fail-closed: никаких Naive-fallback, никаких синтетических метрик.

Все сиды детерминированы; oracle-привязки -- к официальному statsmodels.
"""
from __future__ import annotations

import numpy as np
import pytest
from statsmodels.tsa.vector_ar.var_model import VAR

from apps.api.model_impls.var import (
    DEFAULT_PARAMS,
    IC_OPTIONS,
    PARAM_BOUNDS,
    VAR_ADAPTER_ID,
    _var_fit_predict,
    run_var_backtest,
    validate_var_params,
)
from apps.api.multivariate_contract import companion_stability


def _var1_system(n: int = 120, seed: int = 7, phi: float = 0.6):
    """Стационарная VAR(1)-система с НАСТОЯЩЕЙ перекрёстной связью:
    y1(t) = 0.6*y1(t-1) + 0.4*y2(t-1) + eps; y2(t) = -0.3*y1(t-1) + 0.5*y2(t-1) + eps."""
    rng = np.random.default_rng(seed)
    eps = rng.normal(size=(n, 2))
    out = np.zeros((n, 2))
    out[0] = eps[0]
    for t in range(1, n):
        out[t, 0] = phi * out[t - 1, 0] + 0.4 * out[t - 1, 1] + eps[t, 0]
        out[t, 1] = -0.3 * out[t - 1, 0] + 0.5 * out[t - 1, 1] + eps[t, 1]
    return out


def _fit_payload(matrix: np.ndarray, horizon: int = 6, params: dict | None = None):
    return _var_fit_predict(
        [float(v) for v in matrix[:, 0]],
        horizon,
        related_series={
            "b": [float(v) for v in matrix[:, 1]],
        },
        params=params,
    )


# ---------------------------------------------------------------------------
# Bounded params (fail-closed)
# ---------------------------------------------------------------------------

def test_default_params_are_normalized() -> None:
    normalized = validate_var_params(None)
    assert normalized == DEFAULT_PARAMS
    assert normalized["maxlags"] >= 1


def test_unknown_params_are_ignored() -> None:
    # Соглашение платформы: в params приходят чужие ключи (tbats_seasonal_periods).
    normalized = validate_var_params({"tbats_seasonal_periods": [7], "maxlags": 4})
    assert normalized["maxlags"] == 4
    assert "tbats_seasonal_periods" not in normalized


def test_maxlags_outside_bounds_fail_closed() -> None:
    low, high = PARAM_BOUNDS["maxlags"]
    assert low == 1 and high >= 8
    with pytest.raises(ValueError, match="maxlags"):
        validate_var_params({"maxlags": low - 1})
    with pytest.raises(ValueError, match="maxlags"):
        validate_var_params({"maxlags": high + 1})


def test_ic_whitelist_fail_closed() -> None:
    assert IC_OPTIONS <= {"aic", "bic", "hqic", "fpe"}
    with pytest.raises(ValueError, match="ic"):
        validate_var_params({"ic": "best-ever"})


def test_ic_none_means_explicit_lag_order() -> None:
    # ic=None -- допустимая конвенция: maxlags становится фиксированным p.
    normalized = validate_var_params({"ic": None, "maxlags": 3})
    assert normalized["ic"] is None


def test_trend_whitelist_fail_closed() -> None:
    with pytest.raises(ValueError, match="trend"):
        validate_var_params({"trend": "quadratic"})


def test_interval_alpha_whitelist_fail_closed() -> None:
    with pytest.raises(ValueError, match="alpha"):
        validate_var_params({"alpha": 0.42})


def test_non_integer_maxlags_fail_closed() -> None:
    with pytest.raises(ValueError, match="maxlags"):
        validate_var_params({"maxlags": 2.5})


# ---------------------------------------------------------------------------
# Нативная многомерность (не цикл одномерных ARIMA)
# ---------------------------------------------------------------------------

def test_forecast_is_multivariate_coupled_not_arima_loop() -> None:
    # Перекрёстная связь: изменение ДИНАМИКИ хвоста ряда b перед прогнозной
    # точкой ДОЛЖНО менять прогноз ряда a (в цикле одномерных ARIMA прогноз a
    # от b не зависел бы вообще).  (Равномерный level-shift всей истории b
    # инвариантен -- интерцепт OLS его поглощает, поэтому меняем хвост.)
    matrix = _var1_system(seed=7)
    base = _fit_payload(matrix, horizon=5)
    shifted = matrix.copy()
    shifted[-2:, 1] += 25.0  # меняем только хвост истории ряда b
    other = _fit_payload(shifted, horizon=5)
    assert base["forecast"][0, 0] != pytest.approx(other["forecast"][0, 0])
    # А влияние в обратную сторону тоже работает (a -> b).
    base_b = base["forecast"][0, 1]
    assert base_b != pytest.approx(other["forecast"][0, 1])


def test_forecast_matrix_shape_covers_full_horizon() -> None:
    payload = _fit_payload(_var1_system(), horizon=8)
    assert payload["forecast"].shape == (8, 2)
    assert payload["lower"].shape == (8, 2)
    assert payload["upper"].shape == (8, 2)


def test_series_names_preserve_declaration_order_target_first() -> None:
    matrix = _var1_system()
    # Третья колонка с НЕЗАВИСИМЫМ шумом (level-shift b был бы вырожденным:
    # интерцепт OLS поглощает константу -> ковариация не положительно
    # определена, library-native отказ).
    noise = np.random.default_rng(3).normal(size=len(matrix))
    third = [float(v) + float(e) for v, e in zip(matrix[:, 1], noise)]
    payload = _var_fit_predict(
        [float(v) for v in matrix[:, 0]], 3,
        related_series={"b": [float(v) for v in matrix[:, 1]],
                        "c": third},
        params={},
    )
    assert payload["series_names"][0] == "__target__"
    assert payload["series_names"][1:] == ("b", "c")


# ---------------------------------------------------------------------------
# Нативные интервалы statsmodels (VARResults.forecast_interval)
# ---------------------------------------------------------------------------

def test_native_intervals_bracket_the_point_forecast() -> None:
    payload = _fit_payload(_var1_system(), horizon=6)
    assert (payload["lower"] <= payload["forecast"]).all()
    assert (payload["forecast"] <= payload["upper"]).all()


def test_smaller_alpha_gives_wider_intervals() -> None:
    # Семантика statsmodels: alpha -- уровень значимости (0.05 = 95%-интервал;
    # меньше alpha -- шире интервал).  Платформа сохраняет нативную семантику.
    matrix = _var1_system()
    wide = _fit_payload(matrix, horizon=5, params={"alpha": 0.01})
    narrow = _fit_payload(matrix, horizon=5, params={"alpha": 0.10})
    wide_width = (wide["upper"] - wide["lower"]).sum()
    narrow_width = (narrow["upper"] - narrow["lower"]).sum()
    assert wide_width > narrow_width


def test_intervals_bind_to_statsmodels_oracle() -> None:
    # Независимая привязка: forecast_interval statsmodels на ТОЙ ЖЕ матрице.
    matrix = _var1_system(seed=11)
    params = validate_var_params({"maxlags": 2, "ic": "aic", "trend": "c"})
    payload = _var_fit_predict(
        [float(v) for v in matrix[:, 0]], 4,
        related_series={"b": [float(v) for v in matrix[:, 1]]},
        params=params,
    )
    fitted = VAR(matrix).fit(maxlags=2, ic="aic", trend="c")
    point, lower, upper = fitted.forecast_interval(matrix[-fitted.k_ar:], steps=4)
    assert np.allclose(payload["forecast"], point, rtol=1e-12, atol=1e-12)
    assert np.allclose(payload["lower"], lower, rtol=1e-12, atol=1e-12)
    assert np.allclose(payload["upper"], upper, rtol=1e-12, atol=1e-12)


# ---------------------------------------------------------------------------
# Fold-local порядок лага
# ---------------------------------------------------------------------------

def test_lag_order_selected_on_provided_slice_only() -> None:
    # Оракул: выбранный порядок == select_order на переданной матрице.
    matrix = _var1_system(seed=13, n=150)
    payload = _fit_payload(matrix, horizon=4, params={"maxlags": 8, "ic": "aic"})
    reference = VAR(matrix).fit(maxlags=8, ic="aic")
    assert payload["lag_order"] == reference.k_ar


def test_lag_selection_table_is_bound_to_statsmodels() -> None:
    matrix = _var1_system(seed=13, n=150)
    payload = _fit_payload(matrix, horizon=4, params={"maxlags": 6, "ic": "bic"})
    selection = payload["lag_selection"]
    assert selection["ic"] == "bic"
    assert selection["selected_order"] == payload["lag_order"]
    reference = VAR(matrix).fit(maxlags=6, ic="bic")
    assert selection["selected_order"] == reference.k_ar
    # Таблица критериев привязана к официальному select_order.
    criteria = VAR(matrix).select_order(maxlags=6, trend="c").selected_orders
    assert selection["criteria"]["bic"] == criteria["bic"]


def test_explicit_lag_order_bypasses_selection() -> None:
    matrix = _var1_system(seed=13)
    payload = _fit_payload(matrix, horizon=4, params={"maxlags": 3, "ic": None})
    assert payload["lag_order"] == 3


# ---------------------------------------------------------------------------
# Детерминизм и диагностика
# ---------------------------------------------------------------------------

def test_adapter_is_deterministic() -> None:
    matrix = _var1_system(seed=21)
    first = _fit_payload(matrix, horizon=5)
    second = _fit_payload(matrix, horizon=5)
    assert np.array_equal(first["forecast"], second["forecast"])
    assert np.array_equal(first["lower"], second["lower"])
    assert first["lag_order"] == second["lag_order"]


def test_coefficient_matrices_bind_to_companion_stability() -> None:
    matrix = _var1_system(seed=7)
    payload = _fit_payload(matrix, horizon=5)
    phis = payload["coefficient_matrices"]
    assert len(phis) == payload["lag_order"]
    assert all(block.shape == (2, 2) for block in phis)
    stability = companion_stability(phis)
    # Oracle: companion-модуль согласован с официальной проверкой устойчивости.
    reference = VAR(matrix).fit(maxlags=payload["lag_order"], trend="c")
    assert stability["is_stable"] == bool(reference.is_stable(verbose=False))


def test_in_sample_residuals_bind_to_statsmodels() -> None:
    matrix = _var1_system(seed=7)
    payload = _fit_payload(matrix, horizon=5)
    reference = VAR(matrix).fit(maxlags=payload["lag_order"], trend="c")
    residuals = np.asarray(payload["in_sample_residuals"], dtype=float)
    assert residuals.shape == reference.resid.shape
    assert np.allclose(residuals, np.asarray(reference.resid), rtol=1e-10, atol=1e-12)


# ---------------------------------------------------------------------------
# Fail-closed (никаких Naive-fallback)
# ---------------------------------------------------------------------------

def test_missing_related_series_fail_closed() -> None:
    with pytest.raises(ValueError, match="2 endogenous"):
        _var_fit_predict([1.0] * 60, 4, related_series={}, params={})


def test_length_mismatch_fail_closed() -> None:
    with pytest.raises(ValueError, match="длин"):
        _var_fit_predict([1.0] * 60, 4, related_series={"b": [1.0] * 59}, params={})


def test_nonfinite_input_fail_closed() -> None:
    matrix = _var1_system()
    matrix[3, 1] = np.nan
    with pytest.raises(ValueError, match="NaN/Inf"):
        _fit_payload(matrix, horizon=4)


def test_non_numeric_related_series_fail_closed() -> None:
    with pytest.raises(ValueError):
        _var_fit_predict(
            [1.0] * 60, 4, related_series={"b": ["x"] * 60}, params={},
        )


def test_too_short_history_fail_closed() -> None:
    with pytest.raises(ValueError, match="коротк"):
        _fit_payload(_var1_system(n=12), horizon=4)


def test_horizon_must_be_positive() -> None:
    with pytest.raises(ValueError, match="horizon"):
        _fit_payload(_var1_system(), horizon=0)


# ---------------------------------------------------------------------------
# Legacy synthetic-эндпоинт: честный отказ
# ---------------------------------------------------------------------------

def test_run_var_backtest_rejects_single_series_honestly() -> None:
    # Никаких синтетических многомерных демо и Naive-подмен: VAR требует систему.
    with pytest.raises(ValueError, match="2 endogenous"):
        run_var_backtest([1.0 + 0.01 * i for i in range(200)], 0.7, 1)


def test_adapter_id_is_stable() -> None:
    assert VAR_ADAPTER_ID == "statsmodels-var"
