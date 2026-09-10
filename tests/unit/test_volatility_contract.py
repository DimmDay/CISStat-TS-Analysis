# tests/unit/test_volatility_contract.py
"""Task 134 -- Volatility Objective Contract (каркас GARCH/EGARCH, Tasks 135-136).

Постановка docs/modeling_task_list.md::Task 134:
- **Явное преобразование цены в returns без скрытого выбора**: ``method`` --
  обязательный keyword-аргумент ({"log", "simple"}); вызов без него
  невозможен by construction; выбор фиксируется в cohort-контракте.
- **Цель -- условная дисперсия, а не уровень исходного ряда**: realized
  proxy объявляется явно (``proxy`` -- обязательный keyword); в
  cohort-контракте target_kind="conditional_variance".
- **Primary metric: QLIKE** (Patton 2011 robust form,
  mean(log sigma2_hat + r2/sigma2_hat)); дополнительные ошибки (RMSE/MAE)
  по realized proxy.  Fail-closed: прогноз дисперсии <= 0 отклоняется
  (никаких clamp-подмен); QLIKE ранжирование-эквивалентно классической
  форме sigma2/sigma2_hat - log(sigma2/sigma2_hat) - 1 (оракул-тест).
- **Собственный volatility baseline**: EWMA (RiskMetrics), fold-local
  (только train-префикс), seed = train-дисперсия (ddof=1), плоское
  продление горизонта; детерминирован.
- **Диагностика standardized residuals и squared residuals**: Ljung-Box
  на z и на z^2 (McLeod-Li) + ARCH-LM (Engle 1982); ручная реализация
  ARCH-LM связана оракул-тестом с официальной statsmodels het_arch
  (бит-в-бит).
- **Полностью отдельный cohort**: objective="volatility" с metric_policy
  primary="qlike"; cohort_id отличается от level-cohort тех же данных;
  одномерный движок fail-closed отвергает volatility-планы (level-метрики
  на условной дисперсии запрещены); aligned_oof/registry-гейты
  разделения привязаны regression-тестами.
"""
from __future__ import annotations

import json

import numpy as np
import pytest
from scipy.stats import chi2
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox


def _garch_process(
    n: int = 600, seed: int = 7, omega: float = 0.05,
    alpha: float = 0.15, beta: float = 0.80,
) -> tuple[np.ndarray, np.ndarray]:
    """GARCH(1,1)-процесс (детерминированный при фиксированном seed).

    Возвращает (eps, sigma2_true): кластеризация волатильности присутствует
    (ARCH-LM отвергает на eps) и исчезает на стандартизованных остатках.
    """
    rng = np.random.default_rng(seed)
    eps = np.empty(n)
    sigma2 = np.empty(n)
    sigma2[0] = omega / (1 - alpha - beta)
    eps[0] = np.sqrt(sigma2[0]) * rng.standard_normal()
    for t in range(1, n):
        sigma2[t] = omega + alpha * eps[t - 1] ** 2 + beta * sigma2[t - 1]
        eps[t] = np.sqrt(sigma2[t]) * rng.standard_normal()
    return eps, sigma2


def _prices_from_returns(returns: np.ndarray, p0: float = 100.0) -> np.ndarray:
    """Цены из лог-доходностей (обратная операция для фиксtures price->returns)."""
    return np.concatenate([[p0], p0 * np.exp(np.cumsum(returns))])


# ---------------------------------------------------------------------------
# 1. Явное преобразование цены в returns без скрытого выбора
# ---------------------------------------------------------------------------

from apps.api.volatility_contract import (  # noqa: E402
    MIN_RETURNS_OBSERVATIONS,
    REALIZED_PROXIES,
    RETURNS_METHODS,
    VOLATILITY_CONTRACT_VERSION,
    VOLATILITY_OOF_POINT_KEYS,
    VolatilityContractError,
    aggregate_volatility_metrics,
    build_volatility_target,
    compute_volatility_metrics,
    price_to_returns,
    realized_variance_proxy,
    standardized_residual_diagnostics,
    volatility_clustering_evidence,
    volatility_cohort_contract,
    volatility_naive_baseline,
)


class TestPriceToReturns:
    """price_to_returns: method -- обязательный явный выбор, fail-closed."""

    def test_log_returns_exact_oracle(self) -> None:
        prices = [100.0, 110.0, 99.0, 103.95]
        returns = price_to_returns(prices, method="log")
        expected = np.log(np.asarray(prices)[1:] / np.asarray(prices)[:-1])
        np.testing.assert_allclose(returns, expected, rtol=0, atol=1e-15)
        assert len(returns) == 3

    def test_simple_returns_exact_oracle(self) -> None:
        prices = [100.0, 110.0, 99.0, 103.95]
        returns = price_to_returns(prices, method="simple")
        expected = np.asarray(prices)[1:] / np.asarray(prices)[:-1] - 1.0
        np.testing.assert_allclose(returns, expected, rtol=0, atol=1e-15)

    def test_method_is_required_no_hidden_choice(self) -> None:
        """«Без скрытого выбора»: вызов без method невозможен by construction."""
        with pytest.raises(TypeError):
            price_to_returns([100.0, 101.0, 102.0])

    def test_unknown_method_rejected(self) -> None:
        with pytest.raises(VolatilityContractError, match="log.*simple|simple.*log"):
            price_to_returns([100.0, 101.0], method="pct_change")

    def test_log_and_simple_genuinely_differ(self) -> None:
        """Методы не алиасятся: одна цена -- разные доходности."""
        prices = [100.0, 120.0, 90.0]
        log_r = price_to_returns(prices, method="log")
        simple_r = price_to_returns(prices, method="simple")
        assert not np.allclose(log_r, simple_r)
        # Связь log = log(1 + simple) -- обе шкалы честные, но разные.
        np.testing.assert_allclose(log_r, np.log1p(simple_r), atol=1e-15)

    def test_non_positive_prices_rejected(self) -> None:
        for bad in ([0.0, 1.0, 2.0], [-1.0, 2.0, 3.0]):
            with pytest.raises(VolatilityContractError, match="положительн"):
                price_to_returns(bad, method="log")
            with pytest.raises(VolatilityContractError, match="положительн"):
                price_to_returns(bad, method="simple")

    def test_nan_inf_prices_rejected(self) -> None:
        with pytest.raises(VolatilityContractError, match="NaN|Inf|конечн"):
            price_to_returns([100.0, float("nan"), 101.0], method="log")
        with pytest.raises(VolatilityContractError, match="NaN|Inf|конечн"):
            price_to_returns([100.0, float("inf"), 101.0], method="simple")

    def test_too_short_price_series_rejected(self) -> None:
        with pytest.raises(VolatilityContractError, match="2"):
            price_to_returns([100.0], method="log")
        with pytest.raises(VolatilityContractError):
            price_to_returns([], method="log")

    def test_deterministic_bitwise(self) -> None:
        prices = list(100.0 * np.exp(np.linspace(0, 0.3, 40)))
        first = price_to_returns(prices, method="log")
        second = price_to_returns(prices, method="log")
        assert np.array_equal(first, second)


class TestReturnsMethodConstants:
    """Декларативные константы контракта: методы и proxy не «магия»."""

    def test_returns_methods_declared(self) -> None:
        assert set(RETURNS_METHODS) == {"log", "simple"}

    def test_realized_proxies_declared(self) -> None:
        assert REALIZED_PROXIES == ("squared_returns",)

    def test_contract_version(self) -> None:
        assert VOLATILITY_CONTRACT_VERSION == "volatility-contract-v1"


# ---------------------------------------------------------------------------
# 2. VolatilityTarget: валидированный контейнер (зеркало EndogenousSystem)
# ---------------------------------------------------------------------------

class TestVolatilityTarget:
    """build_volatility_target: цены -> валидированный target с returns."""

    def test_factory_construction_and_method_recorded(self) -> None:
        returns, _ = _garch_process(60, seed=11)
        prices = _prices_from_returns(returns)
        target = build_volatility_target(prices.tolist(), method="log")
        assert target.method == "log"
        assert target.n_returns == 60
        assert target.n_prices == 61
        np.testing.assert_allclose(target.returns_array, returns, atol=1e-12)

    def test_method_required_no_default(self) -> None:
        returns, _ = _garch_process(30, seed=5)
        prices = _prices_from_returns(returns)
        with pytest.raises(TypeError):
            build_volatility_target(prices.tolist())  # type: ignore[call-arg]

    def test_min_observations_enforced(self) -> None:
        returns, _ = _garch_process(MIN_RETURNS_OBSERVATIONS - 1, seed=5)
        short = _prices_from_returns(returns)
        with pytest.raises(VolatilityContractError, match=str(MIN_RETURNS_OBSERVATIONS)):
            build_volatility_target(short.tolist(), method="log")

    def test_head_prefix_consistency(self) -> None:
        returns, _ = _garch_process(50, seed=13)
        prices = _prices_from_returns(returns)
        target = build_volatility_target(prices.tolist(), method="log")
        head = target.head(21)
        assert head.n_returns == 21
        assert head.n_prices == 22
        np.testing.assert_allclose(
            head.returns_array, target.returns_array[:21], atol=1e-15,
        )
        np.testing.assert_allclose(head.prices_array, prices[:22], atol=1e-15)

    def test_train_and_test_slices(self) -> None:
        returns, _ = _garch_process(40, seed=17)
        prices = _prices_from_returns(returns)
        target = build_volatility_target(prices.tolist(), method="log")
        np.testing.assert_allclose(target.train_slice(20), returns[:20], atol=1e-12)
        np.testing.assert_allclose(
            target.test_slice(20, 28), returns[20:28], atol=1e-12,
        )

    def test_timestamps_grid_validated(self) -> None:
        returns, _ = _garch_process(30, seed=19)
        prices = _prices_from_returns(returns)
        stamps = pd_range(len(prices))
        target = build_volatility_target(
            prices.tolist(), method="log", timestamps=stamps,
        )
        assert target.grid is not None
        assert target.grid["regular"] is True
        assert len(target.timestamps) == len(prices)

    def test_timestamps_wrong_length_rejected(self) -> None:
        returns, _ = _garch_process(30, seed=19)
        prices = _prices_from_returns(returns)
        with pytest.raises(VolatilityContractError, match="временной оси|длин"):
            build_volatility_target(
                prices.tolist(), method="log",
                timestamps=[f"2026-01-{d:02d}" for d in range(1, len(prices))],
            )

    def test_head_out_of_range_rejected(self) -> None:
        returns, _ = _garch_process(30, seed=23)
        prices = _prices_from_returns(returns)
        target = build_volatility_target(prices.tolist(), method="log")
        with pytest.raises(VolatilityContractError, match="head"):
            target.head(0)
        with pytest.raises(VolatilityContractError, match="head"):
            target.head(target.n_returns + 1)


def pd_range(n: int) -> list[str]:
    """Дата-метки по дням (регулярная сетка для fixtures)."""
    return [f"2026-01-{day:02d}" for day in range(1, n + 1)]


# ---------------------------------------------------------------------------
# 3. Realized proxy: объявляется явно, никакого скрытого выбора
# ---------------------------------------------------------------------------

class TestRealizedVarianceProxy:
    """realized_variance_proxy: proxy -- обязательный keyword."""

    def test_squared_returns_oracle(self) -> None:
        returns = np.array([0.01, -0.02, 0.0, 0.03])
        proxy = realized_variance_proxy(returns, proxy="squared_returns")
        np.testing.assert_allclose(proxy, returns**2, rtol=0, atol=0)

    def test_proxy_required_no_hidden_choice(self) -> None:
        with pytest.raises(TypeError):
            realized_variance_proxy(np.array([0.01, -0.02]))

    def test_unknown_proxy_rejected(self) -> None:
        with pytest.raises(VolatilityContractError, match="squared_returns"):
            realized_variance_proxy(
                np.array([0.01, -0.02]), proxy="realized_kernel_5min",
            )

    def test_nan_rejected_empty_rejected(self) -> None:
        with pytest.raises(VolatilityContractError, match="NaN|Inf"):
            realized_variance_proxy(np.array([0.01, np.nan]), proxy="squared_returns")
        with pytest.raises(VolatilityContractError):
            realized_variance_proxy(np.array([], dtype=float), proxy="squared_returns")


# ---------------------------------------------------------------------------
# 4. QLIKE primary + дополнительные ошибки по realized proxy
# ---------------------------------------------------------------------------

class TestComputeVolatilityMetrics:
    """compute_volatility_metrics: QLIKE primary, fail-closed на sv<=0."""

    def test_qlike_exact_oracle(self) -> None:
        realized = np.array([0.5, 1.0, 2.0, 4.0])
        predicted = np.array([0.55, 1.1, 2.1, 3.9])
        payload = compute_volatility_metrics(
            realized, predicted, proxy="squared_returns",
        )
        expected = float(np.mean(np.log(predicted) + realized / predicted))
        assert payload["qlike"] == round(expected, 6)
        assert payload["primary"] == "qlike"
        assert payload["realized_proxy"] == "squared_returns"
        assert payload["n_points"] == 4

    def test_qlike_ranking_equivalent_to_classical_form(self) -> None:
        """Patton 2011: robust-форма отличается от классической на константу.

        A = mean(log sv + rv/sv); B = mean(rv/sv - log(rv/sv) - 1);
        A - B = mean(log rv) + 1 -- константа, не зависящая от прогноза.
        Ранжирование моделей обязано совпадать.
        """
        rng = np.random.default_rng(2026)
        realized = rng.integers(1, 50, size=40) / 100.0
        forecast_a = realized * rng.uniform(0.8, 1.2, size=40)
        forecast_b = np.full(40, float(np.mean(realized)))
        offset = float(np.mean(np.log(realized)) + 1.0)
        for predicted in (forecast_a, forecast_b):
            ours = compute_volatility_metrics(
                realized, predicted, proxy="squared_returns",
            )["qlike"]
            classical = float(np.mean(
                realized / predicted - np.log(realized / predicted) - 1.0,
            ))
            assert abs(ours - round(classical + offset, 6)) <= 1e-6

    def test_qlike_direction_better_forecast_lower(self) -> None:
        realized = np.array([0.5, 1.0, 2.0, 4.0])
        good = compute_volatility_metrics(
            realized, np.array([0.55, 1.1, 2.1, 3.9]), proxy="squared_returns",
        )
        bad = compute_volatility_metrics(
            realized, np.array([1.0, 1.0, 1.0, 1.0]), proxy="squared_returns",
        )
        assert good["qlike"] < bad["qlike"]

    def test_rmse_mae_oracle(self) -> None:
        realized = np.array([1.0, 4.0, 9.0])
        predicted = np.array([2.0, 2.0, 2.0])
        payload = compute_volatility_metrics(
            realized, predicted, proxy="squared_returns",
        )
        errors = realized - predicted
        assert payload["rmse"] == round(float(np.sqrt(np.mean(errors**2))), 6)
        assert payload["mae"] == round(float(np.mean(np.abs(errors))), 6)

    def test_zero_predicted_variance_rejected_no_clamping(self) -> None:
        """Прогноз 0 => log(0) = -inf: fail-closed, никакой clamp-подмены."""
        with pytest.raises(VolatilityContractError, match="положительн|> 0|нул"):
            compute_volatility_metrics(
                np.array([0.5, 1.0]), np.array([0.0, 1.0]), proxy="squared_returns",
            )

    def test_negative_predicted_variance_rejected(self) -> None:
        with pytest.raises(VolatilityContractError, match="положительн"):
            compute_volatility_metrics(
                np.array([0.5, 1.0]), np.array([1.0, -0.1]), proxy="squared_returns",
            )

    def test_negative_realized_rejected(self) -> None:
        """Отрицательный «realized» -- нарушение контракта proxy."""
        with pytest.raises(VolatilityContractError, match="неотрицательн"):
            compute_volatility_metrics(
                np.array([0.5, -1.0]), np.array([1.0, 1.0]), proxy="squared_returns",
            )

    def test_nan_inf_and_length_mismatch_rejected(self) -> None:
        with pytest.raises(VolatilityContractError, match="NaN|Inf"):
            compute_volatility_metrics(
                np.array([0.5, np.nan]), np.array([1.0, 1.0]), proxy="squared_returns",
            )
        with pytest.raises(VolatilityContractError, match="одинаков|длин"):
            compute_volatility_metrics(
                np.array([0.5, 1.0, 2.0]), np.array([1.0, 1.0]), proxy="squared_returns",
            )
        with pytest.raises(VolatilityContractError):
            compute_volatility_metrics(
                np.array([], dtype=float), np.array([], dtype=float),
                proxy="squared_returns",
            )


# ---------------------------------------------------------------------------
# 5. Агрегация метрик по folds (взвешивание n_test, конвенция движка)
# ---------------------------------------------------------------------------

class TestAggregateVolatilityMetrics:
    """aggregate_volatility_metrics: пул точек = взвешенное среднее по n_test."""

    def test_qlike_mae_weighted_mean_oracle(self) -> None:
        folds = [
            {"metrics": {"qlike": 1.0, "rmse": 2.0, "mae": 1.5}, "n_test": 3},
            {"metrics": {"qlike": 2.0, "rmse": 4.0, "mae": 2.5}, "n_test": 1},
        ]
        payload = aggregate_volatility_metrics(folds)
        assert payload["qlike"] == round((1.0 * 3 + 2.0 * 1) / 4, 6)
        assert payload["mae"] == round((1.5 * 3 + 2.5 * 1) / 4, 6)
        assert payload["n_points"] == 4

    def test_rmse_pooled_from_mse_oracle(self) -> None:
        """RMSE пула = корень из взвешенного среднего MSE (НЕ среднее RMSE)."""
        folds = [
            {"metrics": {"qlike": 1.0, "rmse": 1.0, "mae": 1.0}, "n_test": 1},
            {"metrics": {"qlike": 1.0, "rmse": 3.0, "mae": 1.0}, "n_test": 1},
        ]
        payload = aggregate_volatility_metrics(folds)
        expected = float(np.sqrt((1.0**2 + 3.0**2) / 2))
        assert payload["rmse"] == round(expected, 6)
        assert payload["rmse"] != round(float(np.mean([1.0, 3.0])), 6)

    def test_proxy_consistency_all_or_none(self) -> None:
        """Разные proxy в folds -- нарушение cohort: fail-closed."""
        folds = [
            {"metrics": {"qlike": 1.0, "rmse": 1.0, "mae": 1.0,
                         "realized_proxy": "squared_returns"}, "n_test": 2},
            {"metrics": {"qlike": 1.0, "rmse": 1.0, "mae": 1.0,
                         "realized_proxy": "other"}, "n_test": 2},
        ]
        with pytest.raises(VolatilityContractError, match="proxy"):
            aggregate_volatility_metrics(folds)

    def test_empty_or_invalid_folds_rejected(self) -> None:
        with pytest.raises(VolatilityContractError):
            aggregate_volatility_metrics([])
        with pytest.raises(VolatilityContractError):
            aggregate_volatility_metrics(
                [{"metrics": {"qlike": 1.0, "rmse": 1.0, "mae": 1.0}, "n_test": 0}],
            )
        with pytest.raises(VolatilityContractError):
            aggregate_volatility_metrics(
                [{"metrics": {"qlike": 1.0, "mae": 1.0}, "n_test": 1}],
            )


# ---------------------------------------------------------------------------
# 6. Собственный volatility baseline: EWMA (RiskMetrics), fold-local
# ---------------------------------------------------------------------------

class TestVolatilityNaiveBaseline:
    """EWMA-baseline: seed=train-дисперсия, рекурсия, плоское продление."""

    def test_ewma_recursion_oracle(self) -> None:
        returns = np.array([0.01, -0.02, 0.015, -0.005, 0.03])
        horizon = 3
        forecast = volatility_naive_baseline(returns, horizon, decay=0.94)
        seed = float(np.var(returns, ddof=1))
        s2 = seed
        for r in returns:
            s2 = 0.94 * s2 + (1 - 0.94) * r * r
        assert len(forecast) == horizon
        assert all(value == s2 for value in forecast)

    def test_flat_horizon_extension(self) -> None:
        """RiskMetrics-конвенция: плоское продление (без скрытой реверсии)."""
        returns, _ = _garch_process(80, seed=11)
        forecast = volatility_naive_baseline(returns, 5, decay=0.94)
        assert len(set(forecast)) == 1
        assert forecast[0] > 0

    def test_decay_changes_forecast(self) -> None:
        returns, _ = _garch_process(80, seed=13)
        fast = volatility_naive_baseline(returns, 1, decay=0.90)
        slow = volatility_naive_baseline(returns, 1, decay=0.99)
        assert fast[0] != slow[0]

    def test_decay_validation(self) -> None:
        returns = np.array([0.01, -0.01, 0.02])
        for bad in (0.0, 1.0, -0.5, 1.5):
            with pytest.raises(VolatilityContractError, match="decay"):
                volatility_naive_baseline(returns, 2, decay=bad)

    def test_degenerate_inputs_rejected(self) -> None:
        with pytest.raises(VolatilityContractError):
            volatility_naive_baseline(np.array([0.01]), 2)
        with pytest.raises(VolatilityContractError, match="NaN|Inf"):
            volatility_naive_baseline(np.array([0.01, np.nan, 0.02]), 2)
        with pytest.raises(VolatilityContractError, match="нул|вырожд"):
            volatility_naive_baseline(np.zeros(25), 2)

    def test_deterministic_bitwise(self) -> None:
        returns, _ = _garch_process(60, seed=17)
        first = volatility_naive_baseline(returns, 4)
        second = volatility_naive_baseline(returns, 4)
        assert first == tuple(second)


# ---------------------------------------------------------------------------
# 7. Диагностика standardized residuals и squared residuals
# ---------------------------------------------------------------------------

class TestStandardizedResidualDiagnostics:
    """LB на z + LB на z^2 (McLeod-Li) + ARCH-LM (Engle) с оракул-паритетом."""

    def test_arch_lm_parity_with_statsmodels_het_arch(self) -> None:
        """Оракул-тест: ручная реализация == официальная statsmodels."""
        eps, _ = _garch_process(500, seed=42)
        report = standardized_residual_diagnostics(eps, nlags=5)
        sm_stat, sm_p, _, _ = het_arch(eps, nlags=5)
        assert np.isclose(
            report["arch_lm"]["statistic"], float(sm_stat), rtol=1e-10, atol=0,
        )
        assert np.isclose(
            report["arch_lm"]["p_value"], float(sm_p), rtol=1e-10, atol=0,
        )
        assert report["arch_lm"]["df"] == 5

    def test_garch_residuals_reveal_remaining_arch(self) -> None:
        """Сырые GARCH-остатки: LB на квадратах и ARCH-LM отвергают H0."""
        eps, _ = _garch_process(600, seed=7)
        report = standardized_residual_diagnostics(eps, nlags=8)
        assert report["available"] is True
        assert report["ljung_box_squared"]["reject_null"] is True
        assert report["arch_lm"]["reject_null"] is True
        # Среднее уравнение белое: LB на уровнях не отвергает (ARCH lives in squares)
        assert report["ljung_box"]["reject_null"] is False

    def test_standardization_removes_arch(self) -> None:
        """Смысл стандартизации: z = eps/sqrt(sigma2_true) -- ARCH исчезает."""
        eps, sigma2 = _garch_process(600, seed=7)
        z = eps / np.sqrt(sigma2)
        report = standardized_residual_diagnostics(z, nlags=8)
        assert report["ljung_box"]["reject_null"] is False
        assert report["ljung_box_squared"]["reject_null"] is False
        assert report["arch_lm"]["reject_null"] is False

    def test_white_noise_no_false_detection(self) -> None:
        white = np.random.default_rng(99).standard_normal(600)
        report = standardized_residual_diagnostics(white, nlags=8)
        assert report["ljung_box"]["reject_null"] is False
        assert report["ljung_box_squared"]["reject_null"] is False
        assert report["arch_lm"]["reject_null"] is False

    def test_payload_shape_complete(self) -> None:
        white = np.random.default_rng(3).standard_normal(120)
        report = standardized_residual_diagnostics(white, nlags=3, alpha=0.01)
        for block in ("ljung_box", "ljung_box_squared", "arch_lm"):
            assert {"statistic", "p_value", "reject_null"} <= set(report[block])
        assert report["n_observations"] == 120
        assert report["nlags"] == 3
        assert report["alpha"] == 0.01

    def test_degenerate_residuals_rejected(self) -> None:
        """Константные остатки (нулевая дисперсия) -- fail-closed, не «идеал»."""
        with pytest.raises(VolatilityContractError, match="вырожд|дисперс"):
            standardized_residual_diagnostics(np.ones(50), nlags=3)

    def test_nan_and_short_input_rejected(self) -> None:
        with pytest.raises(VolatilityContractError, match="NaN|Inf"):
            standardized_residual_diagnostics(
                np.array([0.1, np.nan] + [0.0] * 30), nlags=3,
            )
        with pytest.raises(VolatilityContractError, match="nlags"):
            standardized_residual_diagnostics(np.array([0.1, -0.1, 0.05]), nlags=8)

    def test_invalid_nlags_and_alpha_rejected(self) -> None:
        white = np.random.default_rng(5).standard_normal(60)
        with pytest.raises(VolatilityContractError, match="nlags"):
            standardized_residual_diagnostics(white, nlags=0)
        with pytest.raises(VolatilityContractError, match="alpha"):
            standardized_residual_diagnostics(white, nlags=3, alpha=1.0)
        with pytest.raises(VolatilityContractError, match="alpha"):
            standardized_residual_diagnostics(white, nlags=3, alpha=0.0)


class TestVolatilityClusteringEvidence:
    """A priori evidence кластеризации: ARCH-LM на самих returns."""

    def test_garch_returns_show_clustering(self) -> None:
        eps, _ = _garch_process(600, seed=7)
        evidence = volatility_clustering_evidence(eps, nlags=5)
        assert evidence["available"] is True
        assert evidence["reject_null"] is True
        assert evidence["p_value"] < 0.05

    def test_white_noise_no_clustering(self) -> None:
        white = np.random.default_rng(99).standard_normal(600)
        evidence = volatility_clustering_evidence(white, nlags=5)
        assert evidence["reject_null"] is False

    def test_parity_with_het_arch(self) -> None:
        eps, _ = _garch_process(400, seed=23)
        evidence = volatility_clustering_evidence(eps, nlags=3)
        sm_stat, sm_p, _, _ = het_arch(eps, nlags=3)
        assert np.isclose(evidence["statistic"], float(sm_stat), rtol=1e-10, atol=0)
        assert np.isclose(evidence["p_value"], float(sm_p), rtol=1e-10, atol=0)

    def test_degenerate_and_short_rejected(self) -> None:
        with pytest.raises(VolatilityContractError):
            volatility_clustering_evidence(np.zeros(50), nlags=3)
        with pytest.raises(VolatilityContractError):
            volatility_clustering_evidence(np.array([0.1, -0.1]), nlags=3)


# ---------------------------------------------------------------------------
# 8. Полностью отдельный cohort (objective="volatility", primary=qlike)
# ---------------------------------------------------------------------------

class TestVolatilityCohortContract:
    """volatility_cohort_contract: отдельный cohort, GARCH не рядом с ETS."""

    def test_contract_structure(self) -> None:
        contract = volatility_cohort_contract(
            target_column="price", fingerprint="fp-1", returns_method="log",
            n_returns=100,
        )
        assert contract["objective"] == "volatility"
        assert contract["series_fingerprints"] == {"price": "fp-1"}
        policy = contract["metric_policy"]
        assert policy["primary"] == "qlike"
        assert policy["metrics"] == ["qlike", "rmse", "mae"]
        assert policy["aggregation"] == "test_size_weighted_folds"
        vol_block = policy["volatility"]
        assert vol_block["contract_version"] == VOLATILITY_CONTRACT_VERSION
        assert vol_block["target_kind"] == "conditional_variance"
        assert vol_block["returns_method"] == "log"
        assert vol_block["realized_proxy"] == "squared_returns"
        assert vol_block["baseline"] == {"type": "ewma_riskmetrics", "decay": 0.94}
        assert tuple(vol_block["oof_point_keys"]) == VOLATILITY_OOF_POINT_KEYS
        target = contract["target"]
        assert target["source_column"] == "price"
        assert target["returns_method"] == "log"
        assert target["n_returns_observations"] == 100

    def test_returns_method_required_and_validated(self) -> None:
        with pytest.raises(TypeError):
            volatility_cohort_contract(
                target_column="price", fingerprint="fp", n_returns=100,
            )
        with pytest.raises(VolatilityContractError, match="log.*simple|simple.*log"):
            volatility_cohort_contract(
                target_column="price", fingerprint="fp",
                returns_method="pct", n_returns=100,
            )

    def test_custom_decay_recorded(self) -> None:
        contract = volatility_cohort_contract(
            target_column="price", fingerprint="fp", returns_method="simple",
            n_returns=100, decay=0.97,
        )
        assert contract["metric_policy"]["volatility"]["baseline"] == {
            "type": "ewma_riskmetrics", "decay": 0.97,
        }

    def test_decay_validation(self) -> None:
        for bad in (0.0, 1.0, 2.0, -0.1):
            with pytest.raises(VolatilityContractError, match="decay"):
                volatility_cohort_contract(
                    target_column="p", fingerprint="f",
                    returns_method="log", n_returns=50, decay=bad,
                )

    def test_empty_identifiers_rejected(self) -> None:
        with pytest.raises(VolatilityContractError, match="target"):
            volatility_cohort_contract(
                target_column="  ", fingerprint="f", returns_method="log",
                n_returns=50,
            )
        with pytest.raises(VolatilityContractError, match="fingerprint"):
            volatility_cohort_contract(
                target_column="p", fingerprint="", returns_method="log",
                n_returns=50,
            )

    def test_json_serializable_for_session_store(self) -> None:
        contract = volatility_cohort_contract(
            target_column="price", fingerprint="fp-1", returns_method="log",
            n_returns=100,
        )
        restored = json.loads(json.dumps(contract, ensure_ascii=False))
        assert restored == contract

    def test_cohort_id_separation_from_level_forecast(self) -> None:
        """«Полностью отдельный cohort»: тот же ряд -- другой cohort_id."""
        from apps.api.backtesting import build_backtest_plan

        validation = {
            "strategy": "expanding", "horizon": 2, "gap": 0, "n_splits": 2,
            "folds": [
                {"fold": 1, "train_start": 0, "train_end": 11,
                 "test_start": 12, "test_end": 13},
                {"fold": 2, "train_start": 0, "train_end": 13,
                 "test_start": 14, "test_end": 15},
            ],
        }
        vol_contract = volatility_cohort_contract(
            target_column="price", fingerprint="fp-1", returns_method="log",
            n_returns=16,
        )
        vol_plan = build_backtest_plan(
            validation, n_observations=16, fingerprint="fp-1",
            target_column="price", seasonal_period=1, objective="volatility",
            cohort_contract_override=vol_contract,
        )
        level_plan = build_backtest_plan(
            validation, n_observations=16, fingerprint="fp-1",
            target_column="price", seasonal_period=1,
        )
        assert vol_plan.objective == "volatility"
        assert vol_plan.cohort_id != level_plan.cohort_id
        assert vol_plan.cohort_contract["objective"] == "volatility"
        assert vol_plan.cohort_contract["metric_policy"]["primary"] == "qlike"

    def test_override_mismatch_with_level_plan_rejected(self) -> None:
        from apps.api.backtesting import build_backtest_plan

        validation = {
            "strategy": "single", "horizon": 2, "gap": 0,
            "folds": [
                {"fold": 1, "train_start": 0, "train_end": 13,
                 "test_start": 14, "test_end": 15},
            ],
        }
        vol_contract = volatility_cohort_contract(
            target_column="price", fingerprint="fp-1", returns_method="log",
            n_returns=16,
        )
        with pytest.raises(Exception, match="cohort_contract_override|objective"):
            build_backtest_plan(
                validation, n_observations=16, fingerprint="fp-1",
                target_column="price", seasonal_period=1,
                objective="level_forecast",
                cohort_contract_override=vol_contract,
            )


# ---------------------------------------------------------------------------
# 9. Структурное разделение objective на движках (fail-closed)
# ---------------------------------------------------------------------------

class TestVolatilityObjectiveSeparation:
    """Level-движки не исполняют volatility-планы: без QLIKE уровня нет."""

    def test_univariate_engine_rejects_volatility_plan(self) -> None:
        """Дыра закрыта: injected-predictor + volatility-план запрещён.

        До фикса одномерный движок с injected-predictor вычислял бы
        level-метрики (MAE/RMSE) на прогнозах дисперсии -- именно это
        запрещает постановка («цель -- условная дисперсия»).
        """
        from apps.api.backtesting import (
            BacktestExecutionError,
            BacktestPlan,
            BacktestFoldPlan,
            run_backtest_plan,
        )

        plan = BacktestPlan(
            strategy="single", horizon=2, gap=0,
            folds=[BacktestFoldPlan(fold=1, train_indices=list(range(10)),
                                    test_indices=[10, 11], gap=0)],
            cohort_id="cohort-vol", fingerprint="fp", target_column="r",
            seasonal_period=1, n_observations=12, objective="volatility",
        )
        with pytest.raises(BacktestExecutionError, match="volatility|дисперс"):
            run_backtest_plan(
                model_id="naive", model_name="Naive", family_id="baselines",
                series=[1.0] * 12, labels=[str(i) for i in range(12)],
                plan=plan, seasonal_period=1,
                predictors={"naive": lambda y, h, m, p: [float(y[-1])] * h},
            )

    def test_vector_engine_rejects_volatility_plan(self) -> None:
        """Векторный движок исполняет только multivariate (regression-pin)."""
        from apps.api.backtesting import (
            BacktestExecutionError,
            BacktestPlan,
            BacktestFoldPlan,
            run_vector_backtest_plan,
        )
        from apps.api.multivariate_contract import build_endogenous_system

        plan = BacktestPlan(
            strategy="single", horizon=2, gap=0,
            folds=[BacktestFoldPlan(fold=1, train_indices=list(range(10)),
                                    test_indices=[10, 11], gap=0)],
            cohort_id="cohort-vol", fingerprint="fp", target_column="r",
            seasonal_period=1, n_observations=12, objective="volatility",
        )
        system = build_endogenous_system(
            {"a": list(np.linspace(1, 2, 24)), "b": list(np.linspace(2, 1, 24))},
        )
        with pytest.raises(BacktestExecutionError, match="multivariate"):
            run_vector_backtest_plan(
                model_id="var", model_name="VAR", family_id="multivariate",
                system=system, plan=plan, seasonal_period=1,
            )

    def test_registry_rejects_volatility_objective_for_level_models(self) -> None:
        """Regression-pin: реестр не даст level-модели objective=volatility."""
        from apps.api.model_execution import (
            MODEL_EXECUTION_REGISTRY,
            ModelExecutionContractError,
            ModelExecutionRequest,
        )

        with pytest.raises(ModelExecutionContractError, match="volatility"):
            MODEL_EXECUTION_REGISTRY.execute(
                "ets",
                ModelExecutionRequest(
                    target=[1.0, 2.0, 3.0], horizon=1, objective="volatility",
                ),
            )

    def test_aligned_oof_rejects_objective_mix(self) -> None:
        """Regression-pin: comparison не смешивает volatility и level."""
        from apps.api.modeling_comparison import (
            ComparisonContractError,
            aligned_oof,
        )

        base = {
            "preprocessing": {"evaluation_scale": "y"},
            "folds": [{"fold": 1, "train_start": 0, "train_end": 3,
                       "test_start": 4, "test_end": 5, "gap": 0,
                       "mase_scale": 1.0}],
            "oof_predictions": [
                {"fold": 1, "horizon_step": 1, "index": 4, "label": "t4",
                 "actual": 1.0, "predicted": 1.0, "residual": 0.0},
            ],
        }
        level = {**base, "model_id": "a", "objective": "level_forecast"}
        vol = {**base, "model_id": "b", "objective": "volatility",
               "cohort_contract": {"objective": "volatility"}}
        with pytest.raises(ComparisonContractError, match="objective"):
            aligned_oof([level, vol])
