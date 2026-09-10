# tests/unit/test_garch_adapter.py
"""Task 135 -- GARCH: нативный arch-адаптер волатильности.

Первый исполнитель volatility-контракта Task 134 (прецедент Task 131->132):
- fold-local: адаптер получает ТОЛЬКО train-срез returns; полная история
  недостижима по построению;
- target -- условная дисперсия (НЕ уровень ряда): аналитический прогноз
  официального arch-контура;
- rescale=False -- скрытое масштабирование входа запрещено (зеркало
  «без скрытого выбора» контракта Task 134);
- fail-closed: несошедшийся MLE, sigma2 <= 0, нечисловой вход -- честный
  отказ fold'а, без clamp-подмен и Naive-fallback;
- детерминизм: MLE детерминирован; интервалы -- симуляция с сидированным
  rng-callable (оракул probe: bit-identical при равном seed).
"""
from __future__ import annotations

import numpy as np
import pytest
from arch import arch_model

from apps.api.model_impls.garch import (
    ALPHA_OPTIONS,
    DEFAULT_PARAMS,
    DIST_OPTIONS,
    GARCH_ADAPTER_ID,
    GARCH_MIN_TRAIN,
    MEAN_OPTIONS,
    PARAM_BOUNDS,
    _garch_fit_predict,
    run_garch_backtest,
    validate_garch_params,
)


def _sample_returns(n: int = 260, seed: int = 7) -> np.ndarray:
    """Симулированный GARCH(1,1) процесс (probe-генератор)."""
    rng = np.random.default_rng(seed)
    omega, alpha, beta = 1e-6, 0.10, 0.85
    sigma2 = omega / (1.0 - alpha - beta)
    out = np.empty(n)
    for t in range(n):
        eps = rng.standard_normal() * np.sqrt(sigma2)
        out[t] = eps
        sigma2 = omega + alpha * eps**2 + beta * sigma2
    return out


# ---------------------------------------------------------------------------
# Параметры: нормализация и fail-closed границы
# ---------------------------------------------------------------------------

class TestGarchParams:
    def test_defaults_are_bounded_and_declared(self) -> None:
        normalized = validate_garch_params(None)
        assert normalized == {
            "p": 1, "q": 1, "mean": "Constant", "dist": "normal", "alpha": 0.05,
        }
        for key in ("p", "q"):
            low, high = PARAM_BOUNDS[key]
            assert low <= normalized[key] <= high

    def test_unknown_keys_ignored_platform_convention(self) -> None:
        normalized = validate_garch_params({"tbats_seasonal_periods": [7, 365]})
        assert "tbats_seasonal_periods" not in normalized
        assert normalized == validate_garch_params(None)

    def test_p_q_outside_bounds_fail_closed(self) -> None:
        for key in ("p", "q"):
            with pytest.raises(ValueError, match=key):
                validate_garch_params({key: 0})
            with pytest.raises(ValueError, match=key):
                validate_garch_params({key: 4})

    def test_p_q_must_be_integer(self) -> None:
        with pytest.raises(ValueError, match="p"):
            validate_garch_params({"p": 1.5})
        with pytest.raises(ValueError, match="q"):
            validate_garch_params({"q": "one"})

    def test_mean_option_fail_closed(self) -> None:
        assert MEAN_OPTIONS == {"Constant", "Zero"}
        with pytest.raises(ValueError, match="mean"):
            validate_garch_params({"mean": "LS"})

    def test_dist_option_fail_closed(self) -> None:
        assert DIST_OPTIONS == {"normal", "t"}
        with pytest.raises(ValueError, match="dist"):
            validate_garch_params({"dist": "skewt"})

    def test_alpha_option_fail_closed(self) -> None:
        assert ALPHA_OPTIONS == {0.01, 0.05, 0.10}
        with pytest.raises(ValueError, match="alpha"):
            validate_garch_params({"alpha": 0.2})


# ---------------------------------------------------------------------------
# Fit/predict: payload, оракул-паритет, детерминизм
# ---------------------------------------------------------------------------

class TestGarchFitPredict:
    def test_payload_shape_and_contract(self) -> None:
        payload = _garch_fit_predict(list(_sample_returns()), 5)
        forecast = np.asarray(payload["variance_forecast"], dtype=float)
        lower = np.asarray(payload["lower"], dtype=float)
        upper = np.asarray(payload["upper"], dtype=float)
        assert forecast.shape == (5,)
        assert lower.shape == (5,) and upper.shape == (5,)
        assert (forecast > 0).all()  # fail-closed positivity уже в адаптере
        assert (lower <= forecast).all() and (forecast <= upper).all()
        assert payload["adapter_id"] == GARCH_ADAPTER_ID
        assert payload["deterministic"] is True
        assert payload["random_state"] == 42

    def test_metadata_carries_mle_and_diagnostics_state(self) -> None:
        payload = _garch_fit_predict(list(_sample_returns()), 3)
        assert payload["convergence_flag"] == 0
        assert payload["nobs"] >= GARCH_MIN_TRAIN
        params = payload["params"]
        for key in ("mu", "omega", "alpha[1]", "beta[1]"):
            assert key in params
        persistence = payload["persistence"]
        expected = sum(
            value for key, value in params.items()
            if key.startswith("alpha[") or key.startswith("beta[")
        )
        assert persistence == pytest.approx(expected, abs=1e-12)
        assert payload["is_covariance_stationary"] == (persistence < 1.0)
        z = np.asarray(payload["std_residuals"], dtype=float)
        assert np.isfinite(z).all()
        cv = np.asarray(payload["conditional_volatility"], dtype=float)
        returns = np.asarray(_sample_returns(), dtype=float)
        assert np.allclose(z * cv, returns - params["mu"], atol=1e-10)
        for key in ("aic", "bic", "loglikelihood"):
            assert np.isfinite(payload[key])

    def test_oracle_parity_manual_garch_recursion(self) -> None:
        """fc[0] = omega + a*eps^2_T + b*sigma2_T (фильтрованное состояние
        arch); fc[h] = omega + (a+b)*fc[h-1] для h >= 2 -- ожидание
        ненаблюдаемого eps^2 замещается условной дисперсией."""
        returns = _sample_returns()
        payload = _garch_fit_predict(list(returns), 5)
        forecast = np.asarray(payload["variance_forecast"], dtype=float)
        params = payload["params"]
        mu, omega = params["mu"], params["omega"]
        alpha1, beta1 = params["alpha[1]"], params["beta[1]"]
        sigma2_t = float(
            np.asarray(payload["conditional_volatility"], dtype=float)[-1] ** 2
        )
        eps_t = float(returns[-1]) - mu
        values = [omega + alpha1 * eps_t**2 + beta1 * sigma2_t]
        for _ in range(4):
            values.append(omega + (alpha1 + beta1) * values[-1])
        assert np.allclose(forecast, np.asarray(values), rtol=1e-8)

    def test_determinism_bit_identical_including_intervals(self) -> None:
        returns = list(_sample_returns())
        first = _garch_fit_predict(returns, 6, random_state=42)
        second = _garch_fit_predict(returns, 6, random_state=42)
        assert np.array_equal(first["variance_forecast"], second["variance_forecast"])
        assert np.array_equal(first["lower"], second["lower"])
        assert np.array_equal(first["upper"], second["upper"])
        assert first["params"] == second["params"]

    def test_interval_seed_changes_paths_not_point_forecast(self) -> None:
        returns = list(_sample_returns())
        first = _garch_fit_predict(returns, 6, random_state=42)
        second = _garch_fit_predict(returns, 6, random_state=43)
        assert np.array_equal(
            first["variance_forecast"], second["variance_forecast"],
        )
        assert not np.array_equal(first["lower"], second["lower"])

    def test_interval_confidence_level_widens(self) -> None:
        returns = list(_sample_returns())
        wide = _garch_fit_predict(returns, 4, params={"alpha": 0.01})
        narrow = _garch_fit_predict(returns, 4, params={"alpha": 0.10})
        assert min(wide["upper"]) >= max(narrow["upper"]) or (
            np.asarray(wide["upper"]) >= np.asarray(narrow["upper"])
        ).all()
        assert (
            np.asarray(wide["lower"]) <= np.asarray(narrow["lower"])
        ).all()

    def test_rescale_false_no_hidden_transform(self) -> None:
        """Адаптер обязан фитировать на шкале входа: params бит-в-бит равны
        прямому arch-фиту с rescale=False на том же срезе, и arch НЕ выдаёт
        DataScaleWarning (скрытый rescale разрешал бы arch при
        rescale=None -- «без скрытого выбора» контракта Task 134)."""
        import warnings

        from arch.univariate.base import DataScaleWarning

        returns = _sample_returns()
        with warnings.catch_warnings():
            warnings.simplefilter("error", DataScaleWarning)
            payload = _garch_fit_predict(list(returns), 3)
        direct = arch_model(
            returns, mean="Constant", vol="GARCH", p=1, q=1,
            dist="normal", rescale=False,
        ).fit(disp="off", show_warning=False)
        assert payload["params"]["omega"] == float(direct.params["omega"])
        assert payload["params"]["alpha[1]"] == float(direct.params["alpha[1]"])
        assert payload["params"]["beta[1]"] == float(direct.params["beta[1]"])
        assert payload["params"]["mu"] == float(direct.params["mu"])

    def test_mean_zero_drops_constant(self) -> None:
        payload = _garch_fit_predict(
            list(_sample_returns()), 3, params={"mean": "Zero"},
        )
        assert "mu" not in payload["params"]

    def test_dist_t_carries_nu(self) -> None:
        payload = _garch_fit_predict(
            list(_sample_returns(200)), 3, params={"dist": "t"},
        )
        assert "nu" in payload["params"]
        assert payload["params"]["nu"] > 2.0

    def test_residuals_and_metadata_fail_closed_on_degenerate_input(self) -> None:
        """Нулевая дисперсия: arch возвращает conv!=0 / sigma2=0 / NaN-z --
        адаптер обязан отказать на ЛЮБОМ из этих признаков."""
        degenerate = [0.0] * 60
        with pytest.raises(ValueError):
            _garch_fit_predict(degenerate, 3)

    def test_short_history_fail_closed(self) -> None:
        returns = list(_sample_returns(GARCH_MIN_TRAIN - 1))
        with pytest.raises(ValueError, match=str(GARCH_MIN_TRAIN)):
            _garch_fit_predict(returns, 3)

    def test_min_history_accepted(self) -> None:
        payload = _garch_fit_predict(list(_sample_returns(GARCH_MIN_TRAIN + 40)), 2)
        assert len(payload["variance_forecast"]) == 2

    def test_nonfinite_input_fail_closed(self) -> None:
        returns = [float(v) for v in _sample_returns(40)]
        returns[7] = float("nan")
        with pytest.raises(ValueError):
            _garch_fit_predict(returns, 3)
        returns[7] = float("inf")
        with pytest.raises(ValueError):
            _garch_fit_predict(returns, 3)

    def test_horizon_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            _garch_fit_predict(list(_sample_returns()), 0)

    def test_tuned_bigger_model_executes(self) -> None:
        payload = _garch_fit_predict(
            list(_sample_returns(200)), 4,
            params={"p": 2, "q": 2, "dist": "t"},
        )
        assert len(payload["variance_forecast"]) == 4
        assert "alpha[2]" in payload["params"]
        assert "beta[2]" in payload["params"]
        assert "nu" in payload["params"]


# ---------------------------------------------------------------------------
# Legacy synthetic-эндпоинт: честный отказ
# ---------------------------------------------------------------------------

def test_run_garch_backtest_rejects_single_series_endpoint() -> None:
    """GARCH исполняется ТОЛЬКО через volatility-контракт (явное
    price->returns); однорядный synthetic-эндпоинт не применим."""
    with pytest.raises(ValueError, match="volatility"):
        run_garch_backtest([float(v) for v in range(1, 130)], 0.8, 1)


def test_default_params_documented_contract() -> None:
    assert DEFAULT_PARAMS["p"] == 1 and DEFAULT_PARAMS["q"] == 1
    assert DEFAULT_PARAMS["dist"] in DIST_OPTIONS
    assert DEFAULT_PARAMS["mean"] in MEAN_OPTIONS
    assert DEFAULT_PARAMS["alpha"] in ALPHA_OPTIONS


def test_min_train_aligns_with_contract_minimum() -> None:
    """Минимум адаптера обязан совпадать с MIN_RETURNS_OBSERVATIONS
    контракта Task 134 (20 returns) -- тихое ослабление минимума
    недопустимо."""
    from apps.api.volatility_contract import MIN_RETURNS_OBSERVATIONS

    assert GARCH_MIN_TRAIN == MIN_RETURNS_OBSERVATIONS == 20
