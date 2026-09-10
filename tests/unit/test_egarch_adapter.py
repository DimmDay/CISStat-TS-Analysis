# tests/unit/test_egarch_adapter.py
"""Task 136 -- EGARCH: нативный arch-адаптер волатильности с leverage/asymmetry.

Второй исполнитель volatility-контракта Task 134 (прецедент пары var/vecm
в одном векторном движке): volatility-движок Task 135 переиспользуется
бит-в-бит, адаптер поставляет новый executor.
- fold-local: адаптер получает ТОЛЬКО train-срез returns; полная история
  недостижима по построению;
- target -- условная дисперсия (НЕ уровень ряда); EGARCH специфицирует
  асимметрию (leverage): gamma-члены E[ln sigma2] реагируют на ЗНАК шока;
- точечный прогноз -- официальный симуляционный контур arch (EGARCH не
  имеет analytic-прогноза за горизонтом 1 -- hard gate arch 8.0, проверено
  probe'ом scripts/task136_probe.py); среднее путей == variance.values
  самого arch;
- rescale=False -- скрытое масштабирование входа запрещено;
- fail-closed: несошедшийся MLE, sigma2 <= 0, нечисловой вход -- честный
  отказ fold'а, без clamp-подмен и Naive-fallback;
- детерминизм: MLE детерминирован; симуляция -- сидированный rng-callable
  (bit-identical при равном seed, привязано probe'ом).
"""
from __future__ import annotations

import numpy as np
import pytest
from arch import arch_model

from apps.api.model_impls.egarch import (
    ALPHA_OPTIONS,
    DEFAULT_PARAMS,
    DIST_OPTIONS,
    EGARCH_ADAPTER_ID,
    EGARCH_MIN_TRAIN,
    INTERVAL_SIMULATIONS,
    MEAN_OPTIONS,
    PARAM_BOUNDS,
    _egarch_fit_predict,
    run_egarch_backtest,
    validate_egarch_params,
)


def _leverage_returns(n: int = 600, seed: int = 2026) -> np.ndarray:
    """Симулированный EGARCH(1,1,1) с классическим leverage (gamma<0):
    генератор probe'а scripts/task136_probe.py (gamma[1] восстанавливается
    знаком на seed 1/2/3 -- зафиксировано)."""
    rng = np.random.default_rng(seed)
    omega, alpha, gamma, beta = -0.05, 0.12, -0.15, 0.90
    norm_const = np.sqrt(2.0 / np.pi)
    ln_s2 = omega / (1.0 - beta)
    s2 = float(np.exp(ln_s2))
    out = np.empty(n)
    for t in range(n):
        eps = float(np.sqrt(s2) * rng.standard_normal())
        out[t] = eps
        e = eps / np.sqrt(s2)
        ln_s2 = omega + alpha * (abs(e) - norm_const) + gamma * e + beta * ln_s2
        s2 = float(np.exp(ln_s2))
    return out


def _smoke_returns_prefix(n: int, seed: int = 33) -> np.ndarray:
    """Префикс лог-доходностей смоук-серии Task 136, реплицирующий
    полный контур контракта: EGARCH-цены с leverage (seed=33,
    scripts/task136_e2e_smoke.py::egarch_prices) -> price_to_returns
    (np.diff(np.log(prices)) -- round-trip exp/log воспроизводит
    побайтово те же floats; префикс 207 -- патологический срез для
    дефолтного поведения SLSQP, оракул-тест бюджета сходимости)."""
    rng = np.random.default_rng(seed)
    omega, alpha, gamma, beta = -0.05, 0.12, -0.15, 0.90
    norm_const = np.sqrt(2.0 / np.pi)
    ln_s2 = omega / (1.0 - beta)
    s2 = float(np.exp(ln_s2))
    log_price = [np.log(100.0)]
    for _ in range(n):
        eps = float(np.sqrt(s2) * rng.standard_normal())
        log_price.append(log_price[-1] + eps)
        e = eps / np.sqrt(s2)
        ln_s2 = omega + alpha * (abs(e) - norm_const) + gamma * e + beta * ln_s2
        s2 = float(np.exp(ln_s2))
    prices = np.exp(np.asarray(log_price))
    return np.diff(np.log(prices))


# ---------------------------------------------------------------------------
# Параметры: нормализация и fail-closed границы
# ---------------------------------------------------------------------------

class TestEgarchParams:
    def test_defaults_are_bounded_and_declared(self) -> None:
        normalized = validate_egarch_params(None)
        assert normalized == {
            "p": 1, "o": 1, "q": 1,
            "mean": "Constant", "dist": "normal", "alpha": 0.05,
        }
        for key in ("p", "o", "q"):
            low, high = PARAM_BOUNDS[key]
            assert low <= normalized[key] <= high

    def test_unknown_keys_ignored_platform_convention(self) -> None:
        normalized = validate_egarch_params({"tbats_seasonal_periods": [7, 365]})
        assert "tbats_seasonal_periods" not in normalized
        assert normalized == validate_egarch_params(None)

    def test_p_o_q_outside_bounds_fail_closed(self) -> None:
        for key in ("p", "o", "q"):
            with pytest.raises(ValueError, match=key):
                validate_egarch_params({key: 0})
            with pytest.raises(ValueError, match=key):
                validate_egarch_params({key: 4})

    def test_o_must_be_strictly_positive_asymmetry_mandate(self) -> None:
        """o >= 1 -- суть Task 136: модель ОБЯЗАНА параметризовать
        асимметрию; o=0 (симметричный экспоненциальный GARCH) вне
        bounded-пространства."""
        with pytest.raises(ValueError, match="o"):
            validate_egarch_params({"o": 0})

    def test_p_o_q_must_be_integer(self) -> None:
        with pytest.raises(ValueError, match="o"):
            validate_egarch_params({"o": 1.5})
        with pytest.raises(ValueError, match="p"):
            validate_egarch_params({"p": "one"})
        with pytest.raises(ValueError, match="q"):
            validate_egarch_params({"q": 2.5})

    def test_mean_option_fail_closed(self) -> None:
        assert MEAN_OPTIONS == {"Constant", "Zero"}
        with pytest.raises(ValueError, match="mean"):
            validate_egarch_params({"mean": "LS"})

    def test_dist_option_fail_closed(self) -> None:
        assert DIST_OPTIONS == {"normal", "t"}
        with pytest.raises(ValueError, match="dist"):
            validate_egarch_params({"dist": "skewt"})

    def test_alpha_option_fail_closed(self) -> None:
        assert ALPHA_OPTIONS == {0.01, 0.05, 0.10}
        with pytest.raises(ValueError, match="alpha"):
            validate_egarch_params({"alpha": 0.2})


# ---------------------------------------------------------------------------
# Fit/predict: payload, оракул-паритет, детерминизм
# ---------------------------------------------------------------------------

class TestEgarchFitPredict:
    def test_payload_shape_and_contract(self) -> None:
        payload = _egarch_fit_predict(list(_leverage_returns(260)), 5)
        forecast = np.asarray(payload["variance_forecast"], dtype=float)
        lower = np.asarray(payload["lower"], dtype=float)
        upper = np.asarray(payload["upper"], dtype=float)
        assert forecast.shape == (5,)
        assert lower.shape == (5,) and upper.shape == (5,)
        assert (forecast > 0).all()
        assert (lower <= forecast).all() and (forecast <= upper).all()
        assert payload["adapter_id"] == EGARCH_ADAPTER_ID
        assert payload["deterministic"] is True
        assert payload["random_state"] == 42

    def test_metadata_carries_mle_and_diagnostics_state(self) -> None:
        payload = _egarch_fit_predict(list(_leverage_returns(260)), 3)
        assert payload["convergence_flag"] == 0
        assert payload["nobs"] >= EGARCH_MIN_TRAIN
        params = payload["params"]
        for key in ("mu", "omega", "alpha[1]", "gamma[1]", "beta[1]"):
            assert key in params
        persistence = payload["persistence"]
        expected = sum(
            value for key, value in params.items()
            if key.startswith("beta[")
        )
        assert persistence == pytest.approx(expected, abs=1e-12)
        assert payload["is_covariance_stationary"] == (persistence < 1.0)
        z = np.asarray(payload["std_residuals"], dtype=float)
        assert np.isfinite(z).all()
        cv = np.asarray(payload["conditional_volatility"], dtype=float)
        returns = np.asarray(_leverage_returns(260), dtype=float)
        assert np.allclose(z * cv, returns - params["mu"], atol=1e-10)
        for key in ("aic", "bic", "loglikelihood"):
            assert np.isfinite(payload[key])

    def test_oracle_parity_h1_manual_egarch_recursion(self) -> None:
        """Оракул probe: h=1 симуляционных путей ВЫРОЖДЕН (не зависят от
        симулируемых инноваций) => симуляционное среднее h=1 бит-точно
        равно analytic h=1; analytic h=1 == ручная рекурсия EGARCH(1,1,1)
        из фильтрованного состояния arch (rtol 1e-8)."""
        returns = _leverage_returns(260)
        payload = _egarch_fit_predict(list(returns), 3)
        forecast = np.asarray(payload["variance_forecast"], dtype=float)
        params = payload["params"]
        mu, omega = params["mu"], params["omega"]
        alpha1 = params["alpha[1]"]
        gamma1 = params["gamma[1]"]
        beta1 = params["beta[1]"]
        sigma2_t = float(
            np.asarray(payload["conditional_volatility"], dtype=float)[-1] ** 2
        )
        e_t = (float(returns[-1]) - mu) / np.sqrt(sigma2_t)
        norm_const = np.sqrt(2.0 / np.pi)
        expected_h1 = float(np.exp(
            omega
            + alpha1 * (abs(e_t) - norm_const)
            + gamma1 * e_t
            + beta1 * np.log(sigma2_t)
        ))
        assert forecast[0] == pytest.approx(expected_h1, rel=1e-8)

    def test_point_forecast_is_arch_official_simulation_mean(self) -> None:
        """Точечный прогноз -- variance.values официального
        симуляционного контура arch (среднее путей -- probe fact 5),
        а не самодельная агрегация."""
        returns = list(_leverage_returns(260))
        payload = _egarch_fit_predict(returns, 4, random_state=42)
        direct = arch_model(
            np.asarray(returns), mean="Constant", vol="EGARCH",
            p=1, o=1, q=1, dist="normal", rescale=False,
        ).fit(disp="off", show_warning=False)
        gen = np.random.default_rng(42)
        sim = direct.forecast(
            horizon=4, method="simulation",
            simulations=INTERVAL_SIMULATIONS,
            rng=lambda size: gen.standard_normal(size), reindex=False,
        )
        assert np.allclose(
            np.asarray(payload["variance_forecast"], dtype=float),
            np.asarray(sim.variance.values[-1], dtype=float),
            rtol=1e-12,
        )

    def test_determinism_bit_identical_including_intervals(self) -> None:
        returns = list(_leverage_returns(260))
        first = _egarch_fit_predict(returns, 6, random_state=42)
        second = _egarch_fit_predict(returns, 6, random_state=42)
        assert np.array_equal(first["variance_forecast"], second["variance_forecast"])
        assert np.array_equal(first["lower"], second["lower"])
        assert np.array_equal(first["upper"], second["upper"])
        assert first["params"] == second["params"]
        assert first["asymmetry"] == second["asymmetry"]

    def test_seed_changes_simulation_not_mle(self) -> None:
        """Сидированный rng управляет симуляцией (точечный прогноз --
        среднее путей -- законно зависит от seed при MC-оценке h>=2);
        MLE-параметры и диагностика остатков от seed НЕ зависят."""
        returns = list(_leverage_returns(260))
        first = _egarch_fit_predict(returns, 6, random_state=42)
        second = _egarch_fit_predict(returns, 6, random_state=43)
        assert first["params"] == second["params"]
        assert np.array_equal(
            np.asarray(first["std_residuals"], dtype=float),
            np.asarray(second["std_residuals"], dtype=float),
        )
        assert not np.array_equal(first["lower"], second["lower"])

    def test_interval_confidence_level_widens(self) -> None:
        returns = list(_leverage_returns(260))
        wide = _egarch_fit_predict(returns, 4, params={"alpha": 0.01})
        narrow = _egarch_fit_predict(returns, 4, params={"alpha": 0.10})
        assert (np.asarray(wide["upper"]) >= np.asarray(narrow["upper"])).all()
        assert (np.asarray(wide["lower"]) <= np.asarray(narrow["lower"])).all()

    def test_rescale_false_no_hidden_transform(self) -> None:
        """Params бит-в-бит равны прямому arch-фиту с rescale=False;
        DataScaleWarning запрещён (скрытый rescale разрешался бы arch при
        rescale=None -- «без скрытого выбора» контракта Task 134)."""
        import warnings

        from arch.univariate.base import DataScaleWarning

        returns = _leverage_returns(260)
        with warnings.catch_warnings():
            warnings.simplefilter("error", DataScaleWarning)
            payload = _egarch_fit_predict(list(returns), 3)
        direct = arch_model(
            returns, mean="Constant", vol="EGARCH", p=1, o=1, q=1,
            dist="normal", rescale=False,
        ).fit(disp="off", show_warning=False)
        assert payload["params"]["omega"] == float(direct.params["omega"])
        assert payload["params"]["alpha[1]"] == float(direct.params["alpha[1]"])
        assert payload["params"]["gamma[1]"] == float(direct.params["gamma[1]"])
        assert payload["params"]["beta[1]"] == float(direct.params["beta[1]"])
        assert payload["params"]["mu"] == float(direct.params["mu"])

    def test_mean_zero_drops_constant(self) -> None:
        payload = _egarch_fit_predict(
            list(_leverage_returns(260)), 3, params={"mean": "Zero"},
        )
        assert "mu" not in payload["params"]

    def test_dist_t_carries_nu(self) -> None:
        payload = _egarch_fit_predict(
            list(_leverage_returns(260)), 3, params={"dist": "t"},
        )
        assert "nu" in payload["params"]
        assert payload["params"]["nu"] > 2.0

    def test_tuned_bigger_model_executes(self) -> None:
        payload = _egarch_fit_predict(
            list(_leverage_returns(260)), 4,
            params={"p": 2, "o": 2, "q": 2, "dist": "t"},
        )
        assert len(payload["variance_forecast"]) == 4
        for key in ("alpha[2]", "gamma[2]", "beta[2]", "nu"):
            assert key in payload["params"]


# ---------------------------------------------------------------------------
# Leverage / asymmetry: ядро Task 136
# ---------------------------------------------------------------------------

class TestEgarchAsymmetry:
    def test_asymmetry_block_declares_gamma_metadata(self) -> None:
        payload = _egarch_fit_predict(list(_leverage_returns(260)), 3)
        asymmetry = payload["asymmetry"]
        assert asymmetry["order"] == 1
        assert set(asymmetry["gamma_params"]) == {"gamma[1]"}
        assert set(asymmetry["gamma_std_errors"]) == {"gamma[1]"}
        assert set(asymmetry["gamma_pvalues"]) == {"gamma[1]"}
        assert 0.0 <= asymmetry["gamma_pvalues"]["gamma[1]"] <= 1.0
        assert asymmetry["significance_level"] == 0.05
        assert asymmetry["note"]

    def test_leverage_recovered_negative_on_simulated_series(self) -> None:
        """Ядро постановки: на серии с классическим leverage (gamma<0)
        фит восстанавливает отрицательный gamma -- leverage_direction
        честно 'negative'; асимметрия статистически значима."""
        payload = _egarch_fit_predict(list(_leverage_returns(600)), 3)
        asymmetry = payload["asymmetry"]
        assert asymmetry["gamma_params"]["gamma[1]"] < 0
        assert asymmetry["leverage_direction"] == "negative"
        assert asymmetry["asymmetry_significant"] is True

    def test_positive_gamma_declares_positive_direction(self) -> None:
        """Обратный полюс: серии с обратной асимметрией соответствуют
        положительный gamma (направление -- из знака фита, не выдумка)."""
        rng = np.random.default_rng(2026)
        omega, alpha, gamma, beta = -0.05, 0.12, 0.15, 0.90
        norm_const = np.sqrt(2.0 / np.pi)
        ln_s2 = omega / (1.0 - beta)
        s2 = float(np.exp(ln_s2))
        out = np.empty(600)
        for t in range(600):
            eps = float(np.sqrt(s2) * rng.standard_normal())
            out[t] = eps
            e = eps / np.sqrt(s2)
            ln_s2 = omega + alpha * (abs(e) - norm_const) + gamma * e + beta * ln_s2
            s2 = float(np.exp(ln_s2))
        payload = _egarch_fit_predict(list(out), 3)
        assert payload["asymmetry"]["gamma_params"]["gamma[1]"] > 0
        assert payload["asymmetry"]["leverage_direction"] == "positive"

    def test_higher_order_carries_all_gamma_terms(self) -> None:
        payload = _egarch_fit_predict(
            list(_leverage_returns(600)), 3, params={"o": 2},
        )
        asymmetry = payload["asymmetry"]
        assert asymmetry["order"] == 2
        assert set(asymmetry["gamma_params"]) == {"gamma[1]", "gamma[2]"}


# ---------------------------------------------------------------------------
# Fail-closed: честный отказ
# ---------------------------------------------------------------------------

class TestEgarchFailClosed:
    def test_degenerate_zero_variance_input_refused(self) -> None:
        """Нулевая дисперсия: arch возвращает conv!=0 / NaN-z --
        адаптер обязан отказать (без clamp-подмен)."""
        with pytest.raises(ValueError):
            _egarch_fit_predict([0.0] * 60, 3)

    def test_short_history_fail_closed(self) -> None:
        returns = list(_leverage_returns(EGARCH_MIN_TRAIN - 1, seed=5))
        with pytest.raises(ValueError, match=str(EGARCH_MIN_TRAIN)):
            _egarch_fit_predict(returns, 3)

    def test_min_history_accepted(self) -> None:
        payload = _egarch_fit_predict(
            list(_leverage_returns(EGARCH_MIN_TRAIN + 60, seed=5)), 2,
        )
        assert len(payload["variance_forecast"]) == 2

    def test_nonfinite_input_fail_closed(self) -> None:
        returns = [float(v) for v in _leverage_returns(60, seed=5)]
        returns[7] = float("nan")
        with pytest.raises(ValueError):
            _egarch_fit_predict(returns, 3)
        returns[7] = float("inf")
        with pytest.raises(ValueError):
            _egarch_fit_predict(returns, 3)

    def test_horizon_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            _egarch_fit_predict(list(_leverage_returns(260)), 0)

    def test_explicit_optimizer_budget_converges_pathological_slice(self) -> None:
        """Оракул сходимости: срез-207 смоук-серии (фиксированный seed)
        не сходится при дефолтном бюджете/поведении scipy SLSQP в arch
        (knife-edge срез: flag=9 «Iteration limit reached» или flag=4
        «Inequality constraints incompatible» -- при достижимом лучшем
        оптимуме).  Адаптер декларирует ЯВНЫЙ бюджет EGARCH_MAXITER --
        тот же MLE, но флаг 0 и loglikelihood не хуже несошедшегося;
        сходимость не зависит от seed (fit детерминирован)."""
        from arch import arch_model as _am

        from apps.api.model_impls.egarch import EGARCH_MAXITER

        assert EGARCH_MAXITER == 1000
        hard_slice = _smoke_returns_prefix(207)
        premise = _am(
            hard_slice, mean="Constant", vol="EGARCH", p=1, o=1, q=1,
            dist="normal", rescale=False,
        ).fit(disp="off", show_warning=False)
        # Дефолтный фит на срезе НЕ сходится (любой flag != 0).
        assert premise.convergence_flag != 0
        payload = _egarch_fit_predict(list(hard_slice), 4, random_state=7)
        assert payload["convergence_flag"] == 0
        assert payload["loglikelihood"] >= float(premise.loglikelihood) - 1e-8
        # Детерминизм сходимости: любой seed -- тот же фит.
        again = _egarch_fit_predict(list(hard_slice), 4, random_state=99)
        assert again["params"] == payload["params"]
        assert again["loglikelihood"] == payload["loglikelihood"]


# ---------------------------------------------------------------------------
# Legacy synthetic-эндпоинт: честный отказ
# ---------------------------------------------------------------------------

def test_run_egarch_backtest_rejects_single_series_endpoint() -> None:
    """EGARCH исполняется ТОЛЬКО через volatility-контракт (явное
    price->returns); однорядный synthetic-эндпоинт не применим."""
    with pytest.raises(ValueError, match="volatility"):
        run_egarch_backtest([float(v) for v in range(1, 130)], 0.8, 1)


def test_default_params_documented_contract() -> None:
    assert DEFAULT_PARAMS["p"] == 1 and DEFAULT_PARAMS["o"] == 1
    assert DEFAULT_PARAMS["q"] == 1
    assert DEFAULT_PARAMS["dist"] in DIST_OPTIONS
    assert DEFAULT_PARAMS["mean"] in MEAN_OPTIONS
    assert DEFAULT_PARAMS["alpha"] in ALPHA_OPTIONS


def test_min_train_aligns_with_contract_minimum() -> None:
    """Минимум адаптера обязан совпадать с MIN_RETURNS_OBSERVATIONS
    контракта Task 134 (20 returns) -- тихое ослабление минимума
    недопустимо (прецедент мутации rescale Task 135)."""
    from apps.api.volatility_contract import MIN_RETURNS_OBSERVATIONS

    assert EGARCH_MIN_TRAIN == MIN_RETURNS_OBSERVATIONS == 20
