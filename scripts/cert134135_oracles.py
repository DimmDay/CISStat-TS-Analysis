# scripts/cert134135_oracles.py
"""Независимые оракул-пробы сертификации Task 134 + Task 135.

Аудиторская проверка (не является частью тестовой базы проекта):
собственные данные и собственные сиды (20260910 / 424242 / 777001...),
НЕ совпадающие с сидами исполнителя. Каждая проба печатает PASS/FAIL;
любой FAIL -- ненулевой exit code.

Запуск:  python scripts/cert134135_oracles.py   (из корня репозитория)
"""
from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    RESULTS.append((name, bool(condition), detail))
    print(f"[{status}] {name}" + (f"  -- {detail}" if detail else ""))


# ---------------------------------------------------------------------------

def o1_price_to_returns() -> None:
    from apps.api.volatility_contract import (
        VolatilityContractError, price_to_returns,
    )
    rng = np.random.default_rng(20260910)
    prices = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, 300)))

    log_r = price_to_returns(prices, method="log")
    simple_r = price_to_returns(prices, method="simple")
    check("O1a log == np.diff(np.log(P)) бит-в-бит",
          np.array_equal(log_r, np.diff(np.log(prices))))
    check("O1b simple == P_t/P_{t-1}-1 бит-в-бит",
          np.array_equal(simple_r, prices[1:] / prices[:-1] - 1.0))
    check("O1c длина returns == n_prices - 1",
          log_r.size == 299 and simple_r.size == 299)

    ok_typeerror = False
    try:
        price_to_returns(prices)  # без method
    except TypeError:
        ok_typeerror = True
    except VolatilityContractError:
        ok_typeerror = False
    check("O1d вызов без method невозможен (TypeError, keyword-only)", ok_typeerror)

    def _raises(fn) -> bool:
        try:
            fn()
            return False
        except VolatilityContractError:
            return True

    check("O1e неизвестный method отклонён",
          _raises(lambda: price_to_returns(prices, method="dlog")))
    check("O1f неположительные цены отклонены",
          _raises(lambda: price_to_returns([1.0, 0.0, 2.0], method="log")))
    check("O1g NaN-цены отклонены",
          _raises(lambda: price_to_returns([1.0, float("nan"), 2.0], method="log")))
    check("O1h одна цена отклонена",
          _raises(lambda: price_to_returns([1.0], method="log")))


def o2_volatility_target() -> None:
    from apps.api.volatility_contract import (
        MIN_RETURNS_OBSERVATIONS, build_volatility_target,
    )
    rng = np.random.default_rng(424242)
    prices = list(100.0 * np.exp(np.cumsum(rng.normal(0, 0.02, 60))))
    stamps = [str(v) for v in pd.date_range("2026-01-01", periods=60, freq="B")]
    target = build_volatility_target(prices, method="log", timestamps=stamps)
    check("O2a Target: n_returns == n_prices - 1",
          target.n_returns == 59 and target.n_prices == 60)
    tampered = list(target.returns)
    tampered[3] += 1e-12
    try:
        type(target)(
            prices=tuple(prices), returns=tuple(tampered), method="log",
            timestamps=tuple(stamps),
        )
        ok = False
    except Exception:
        ok = True
    check("O2b анти-тампер: чужие returns обнаружены бит-в-бит", ok)
    head = target.head(25)
    check("O2c head(25): префикс returns[0:25] и prices[0:26]",
          head.n_returns == 25 and head.n_prices == 26
          and np.array_equal(head.returns_array, target.returns_array[:25]))
    check("O2d timestamps выровнены с ценами (60 меток)",
          target.timestamps is not None and len(target.timestamps) == 60)
    check("O2e MIN_RETURNS_OBSERVATIONS == 20", MIN_RETURNS_OBSERVATIONS == 20)


def o3_qlike_equivalence() -> None:
    from apps.api.volatility_contract import compute_volatility_metrics
    rng = np.random.default_rng(777001)
    rv = rng.uniform(0.000001, 0.001, 128)  # realized proxy (variance scale)
    ok_rank = True
    const_term = float(np.mean(np.log(rv))) + 1.0
    max_diff = 0.0
    for _ in range(5):
        sv = rv * rng.lognormal(0.0, 0.8, 128)
        robust = float(np.mean(np.log(sv) + rv / sv))
        classic = float(np.mean(rv / sv - np.log(rv / sv) - 1.0))
        max_diff = max(max_diff, abs((robust - classic) - const_term))
        m1 = compute_volatility_metrics(rv, sv, proxy="squared_returns")["qlike"]
        sv2 = sv * 1.7
        m2 = compute_volatility_metrics(rv, sv2, proxy="squared_returns")["qlike"]
        if (robust < float(np.mean(np.log(sv2) + rv / sv2))) != (m1 < m2):
            ok_rank = False
    check("O3a QLIKE: robust - classic == mean(log rv) + 1 (разность константна)",
          max_diff < 1e-9, f"max|diff-const|={max_diff:.2e}")
    check("O3b QLIKE: ранжирование-эквивалентность (растущее sv -> больше loss)",
          ok_rank)

    hand = float(np.mean(np.log(rv[:16] * 1.1) + rv[:16] / (rv[:16] * 1.1)))
    got = compute_volatility_metrics(rv[:16], rv[:16] * 1.1, proxy="squared_returns")
    check("O3c QLIKE == ручная формула (round 6)",
          abs(got["qlike"] - round(hand, 6)) < 5e-7,
          f"got={got['qlike']} hand={round(hand, 6)}")

    def _raises(fn) -> bool:
        try:
            fn()
            return False
        except Exception:
            return True

    ok_neg = _raises(lambda: compute_volatility_metrics(
        rv[:8], -np.abs(rv[:8]), proxy="squared_returns"))
    ok_zero = _raises(lambda: compute_volatility_metrics(
        rv[:8], np.zeros(8), proxy="squared_returns"))
    ok_negreal = _raises(lambda: compute_volatility_metrics(
        -rv[:8], rv[:8], proxy="squared_returns"))
    ok_proxy = _raises(lambda: compute_volatility_metrics(rv[:8], rv[:8], proxy="range"))
    ok_kw = _raises(lambda: compute_volatility_metrics(rv[:8], rv[:8]))
    check("O3d fail-closed: sv<0 отклонён", ok_neg)
    check("O3e fail-closed: sv=0 отклонён (без clamp)", ok_zero)
    check("O3f realized<0 -- нарушение proxy, отклонён", ok_negreal)
    check("O3g неизвестный proxy отклонён", ok_proxy)
    check("O3h proxy -- обязательный keyword (TypeError)", ok_kw)


def o5_aggregate() -> None:
    from apps.api.volatility_contract import (
        VolatilityContractError, aggregate_volatility_metrics,
    )
    folds = [
        {"n_test": 5, "metrics": {"qlike": -9.0, "rmse": 2.0, "mae": 1.0,
                                  "realized_proxy": "squared_returns"}},
        {"n_test": 8, "metrics": {"qlike": -8.0, "rmse": 3.0, "mae": 2.0,
                                  "realized_proxy": "squared_returns"}},
        {"n_test": 7, "metrics": {"qlike": -10.0, "rmse": 1.0, "mae": 0.5,
                                  "realized_proxy": "squared_returns"}},
    ]
    agg = aggregate_volatility_metrics(folds)
    n = 20
    q_hand = (-9.0 * 5 - 8.0 * 8 - 10.0 * 7) / n
    mae_hand = (1.0 * 5 + 2.0 * 8 + 0.5 * 7) / n
    mse_hand = (4.0 * 5 + 9.0 * 8 + 1.0 * 7) / n
    rmse_hand = math.sqrt(mse_hand)
    mean_rmse = (2.0 + 3.0 + 1.0) / 3
    check("O5a qlike -- взвешенное по n_test среднее",
          abs(agg["qlike"] - round(q_hand, 6)) < 1e-9,
          f"got={agg['qlike']} hand={round(q_hand, 6)}")
    check("O5b mae -- взвешенное среднее",
          abs(agg["mae"] - round(mae_hand, 6)) < 1e-9)
    check("O5c rmse == корень взвешенного MSE (НЕ среднее RMSE)",
          abs(agg["rmse"] - round(rmse_hand, 6)) < 1e-9
          and abs(agg["rmse"] - round(mean_rmse, 6)) > 1e-6,
          f"got={agg['rmse']} sqrt(MSE)={round(rmse_hand, 6)} meanRMSE={round(mean_rmse, 6)}")
    check("O5d n_points == сумма n_test", agg["n_points"] == n)
    check("O5e primary == 'qlike'", agg["primary"] == "qlike")

    def _raises(folds_in) -> bool:
        try:
            aggregate_volatility_metrics(folds_in)
            return False
        except VolatilityContractError:
            return True
    mixed = [dict(f) for f in folds]
    mixed[2]["metrics"] = dict(mixed[2]["metrics"])
    mixed[2]["metrics"]["realized_proxy"] = "range_volatility"
    check("O5f подмена proxy между folds отклонена (all-or-none)", _raises(mixed))
    missing = [{"n_test": 5, "metrics": {"qlike": -9.0, "rmse": 2.0}}]
    check("O5g частичная агрегация (без mae) отклонена", _raises(missing))


def o6_ewma() -> None:
    from apps.api.volatility_contract import (
        DEFAULT_EWMA_DECAY, VolatilityContractError, volatility_naive_baseline,
    )
    rng = np.random.default_rng(991100)
    returns = list(rng.normal(0, 0.012, 150))
    for decay in (0.94, 0.90, 0.97):
        got = np.asarray(volatility_naive_baseline(returns, 6, decay=decay))
        s2 = float(np.var(returns, ddof=1))
        for value in returns:
            s2 = decay * s2 + (1.0 - decay) * float(value) ** 2
        hand = np.full(6, s2)
        check(f"O6 EWMA decay={decay}: seed=var(ddof=1), рекурсия, плоский горизонт",
              np.allclose(got, hand, rtol=1e-12, atol=0.0)
              and got[0] == got[-1])
    check("O6 DEFAULT_EWMA_DECAY == 0.94 (RiskMetrics)", DEFAULT_EWMA_DECAY == 0.94)

    def _raises(fn) -> bool:
        try:
            fn()
            return False
        except VolatilityContractError:
            return True
    check("O6 decay=1.0 отклонён", _raises(
        lambda: volatility_naive_baseline(returns, 3, decay=1.0)))
    check("O6 decay=0.0 отклонён", _raises(
        lambda: volatility_naive_baseline(returns, 3, decay=0.0)))
    check("O6 вырожденный train (все нули) -- честный отказ", _raises(
        lambda: volatility_naive_baseline([0.0] * 40, 3)))
    check("O6 один return -- отказ (нужно >= 2)", _raises(
        lambda: volatility_naive_baseline([0.01], 3)))


def o7_arch_lm_oracle() -> None:
    from apps.api.volatility_contract import _arch_lm_statistic
    from statsmodels.stats.diagnostic import het_arch
    rng = np.random.default_rng(31415)
    series_list = {
        "white_noise_T500": rng.normal(0, 1, 500),
        "arch_T600": None,
    }
    e = rng.normal(0, 1, 600)
    a = np.zeros(600)
    s2 = 0.2
    for t in range(600):
        s2 = 0.05 + 0.10 * (e[t - 1] ** 2 if t else 0.0) + 0.80 * s2
        a[t] = math.sqrt(s2) * e[t]
    series_list["arch_T600"] = a
    worst = 0.0
    for name, series in series_list.items():
        for nlags in (1, 3, 5, 8, 12):
            mine, df = _arch_lm_statistic(series, nlags)
            lm = het_arch(series, nlags=nlags)[0]
            rel = abs(mine - lm) / max(abs(lm), 1e-300)
            worst = max(worst, rel)
            check(f"O7 {name} nlags={nlags}: LM == het_arch (df={df}=={nlags})",
                  rel < 1e-10 and df == nlags, f"rel={rel:.2e}")
    print(f"    worst relative deviation: {worst:.2e}")


def o8_residual_diagnostics() -> None:
    from apps.api.volatility_contract import (
        VolatilityContractError, standardized_residual_diagnostics,
    )
    from statsmodels.stats.diagnostic import acorr_ljungbox
    rng = np.random.default_rng(271828)
    # Стандартизованные остатки корректной модели ~ iid normal.
    z = rng.normal(0, 1, 400) / np.sqrt(1.0)
    diag = standardized_residual_diagnostics(z, nlags=8, alpha=0.05)
    direct = acorr_ljungbox(z, lags=[8], model_df=0, return_df=True)
    check("O8a LB на z == прямой acorr_ljungbox",
          abs(diag["ljung_box"]["statistic"] - float(direct["lb_stat"].iloc[-1])) < 1e-9)
    direct_sq = acorr_ljungbox(z**2, lags=[8], model_df=0, return_df=True)
    check("O8b LB^2 (McLeod-Li) == acorr_ljungbox(z^2)",
          abs(diag["ljung_box_squared"]["statistic"]
              - float(direct_sq["lb_stat"].iloc[-1])) < 1e-9)
    check("O8c структура: ljung_box / ljung_box_squared / arch_lm",
          {"ljung_box", "ljung_box_squared", "arch_lm"} <= set(diag)
          and diag["available"] is True)
    try:
        standardized_residual_diagnostics(np.full(100, 0.5), nlags=8)
        ok = False
    except VolatilityContractError:
        ok = True
    check("O8d вырожденные остатки (нулевая дисперсия) -- отказ", ok)


def o9_clustering_evidence() -> None:
    from apps.api.volatility_contract import volatility_clustering_evidence
    rng = np.random.default_rng(161803)
    wn = rng.normal(0, 0.01, 1200)
    ev_wn = volatility_clustering_evidence(wn, nlags=8)
    e = rng.normal(0, 1, 1200)
    r = np.zeros(1200)
    s2 = (0.05 + 0.10 + 0.83) and 0.05 / (1 - 0.10 - 0.83)
    for t in range(1200):
        s2 = 0.05 + 0.10 * (r[t - 1] ** 2 if t else 0.0) + 0.83 * s2
        r[t] = math.sqrt(s2) * e[t]
    ev_g = volatility_clustering_evidence(r, nlags=8)
    check("O9a белый шум: ARCH-LM НЕ отвергает H0 (нет кластеризации)",
          ev_wn["reject_null"] is False, f"p={ev_wn['p_value']:.4f}")
    check("O9b GARCH(1,1) 0.10/0.83: ARCH-LM отвергает (кластеризация есть)",
          ev_g["reject_null"] is True, f"p={ev_g['p_value']:.2e}")


def o10_cohort_contract() -> None:
    from apps.api.volatility_contract import volatility_cohort_contract
    ok_kw = False
    try:
        volatility_cohort_contract(target_column="p", fingerprint="abc")  # без returns_method
    except TypeError:
        ok_kw = True
    check("O10a returns_method -- обязательный keyword (TypeError)", ok_kw)
    cohort = volatility_cohort_contract(
        target_column="price", fingerprint="fp-1", returns_method="log",
        n_returns=259, seasonal_period=1,
    )
    vol_block = cohort["metric_policy"]["volatility"]
    check("O10b objective='volatility', primary='qlike', policy='none'",
          cohort["objective"] == "volatility"
          and cohort["metric_policy"]["primary"] == "qlike"
          and cohort["feature_contract"]["policy"] == "none")
    check("O10c volatility-блок: target_kind/proxy/baseline/decay",
          vol_block["target_kind"] == "conditional_variance"
          and vol_block["realized_proxy"] == "squared_returns"
          and vol_block["baseline"] == {"type": "ewma_riskmetrics", "decay": 0.94})
    check("O10d target-блок фиксирует returns_method",
          cohort["target"]["returns_method"] == "log"
          and cohort["target"]["source_column"] == "price")


# ---------------------------------------------------------------------------

def _sim_garch(rng, n, omega=2e-6, alpha=0.12, beta=0.83, s0=None):
    s2 = s0 if s0 is not None else omega / (1 - alpha - beta)
    out = np.zeros(n)
    for t in range(n):
        eps = rng.standard_normal()
        out[t] = math.sqrt(s2) * eps
        s2 = omega + alpha * out[t] ** 2 + beta * s2
    return out


def o11_registry() -> None:
    from apps.api.model_execution import (
        MODEL_EXECUTION_REGISTRY, ModelExecutionRequest,
    )
    d = MODEL_EXECUTION_REGISTRY.describe("garch")
    check("O11a реестр: garch objective/input_kind/family/engine/adapter",
          d.get("objective") == "volatility" and d.get("input_kind") == "univariate"
          and d.get("family_id") == "volatility" and d.get("engine") == "arch"
          and d.get("adapter_id") == "arch-garch")
    check("O11b реестр: intervals + deterministic + dependency_group",
          d.get("supports_prediction_intervals") is True
          and d.get("deterministic") is True
          and d.get("dependency_group") == "volatility")

    from apps.api.model_readiness import PRODUCTION_BACKTEST_MODEL_IDS
    check("O11c PRODUCTION_BACKTEST_MODEL_IDS: 18 моделей, включает garch",
          len(PRODUCTION_BACKTEST_MODEL_IDS) == 18
          and "garch" in PRODUCTION_BACKTEST_MODEL_IDS,
          f"n={len(PRODUCTION_BACKTEST_MODEL_IDS)}")

    # Одномерный движок отказывает volatility-модели через реестр-гейт Task 134
    from apps.api.backtesting import BacktestExecutionError, run_backtest_plan
    from apps.api.model_impls.garch import _garch_fit_predict  # noqa: F401 (реестр-эекзекьютор жив)

    ok_gate = True
    try:
        # volatility-план строится, но одномерный движок обязан отказать
        # ДО любого исполнения (гейт Task 134 перед реестром/адаптером)
        from apps.api.backtesting import BacktestFoldPlan, BacktestPlan
        plan = BacktestPlan(
            strategy="expanding", horizon=5, gap=0,
            folds=[BacktestFoldPlan(fold=1, train_indices=list(range(28)),
                                    test_indices=list(range(28, 33)), gap=0)],
            cohort_id="c", fingerprint="fp", target_column="y",
            seasonal_period=1, n_observations=40,
            objective="volatility",
        )
        run_backtest_plan(
            model_id="garch", model_name="GARCH", family_id="volatility",
            series=list(np.abs(np.random.default_rng(1).normal(1, 0.1, 40))),
            labels=[str(i) for i in range(40)], plan=plan,
            seasonal_period=1,
        )
        ok_gate = False
    except BacktestExecutionError as exc:
        ok_gate = "volatility" in str(exc)
    check("O11d гейт Task 134: одномерный движок отказывает volatility-плану "
          "до исполнения", bool(ok_gate))


def o12_garch_recursion_oracle() -> None:
    from arch import arch_model
    from apps.api.model_impls.garch import _garch_fit_predict
    rng = np.random.default_rng(555000)
    returns = _sim_garch(rng, 800)
    payload = _garch_fit_predict(list(returns), 7, params={"p": 1, "q": 1}, random_state=1)

    model = arch_model(returns, mean="Constant", vol="GARCH", p=1, q=1,
                       dist="normal", rescale=False)
    fitted = model.fit(disp="off", show_warning=False)
    params = {str(k): float(v) for k, v in fitted.params.items()}
    omega = params["omega"]
    alpha_ = sum(v for k, v in params.items() if k.startswith("alpha["))
    beta_ = sum(v for k, v in params.items() if k.startswith("beta["))
    resid_T = float(fitted.resid[-1])
    sigma2_T = float(fitted.conditional_volatility[-1]) ** 2
    fc = [omega + alpha_ * resid_T ** 2 + beta_ * sigma2_T]
    for _ in range(1, 7):
        fc.append(omega + (alpha_ + beta_) * fc[-1])
    manual = np.asarray(fc)
    direct = np.asarray(
        fitted.forecast(horizon=7, method="analytic", reindex=False)
        .variance.values[-1])
    adapter = np.asarray(payload["variance_forecast"])
    check("O12a аналитическая рекурсия == прямой arch analytic forecast",
          np.allclose(manual, direct, rtol=1e-8, atol=0.0),
          f"max rel={np.max(np.abs(manual - direct) / direct):.2e}")
    check("O12b адаптер == ручная рекурсия (rtol 1e-8)",
          np.allclose(adapter, manual, rtol=1e-8, atol=0.0),
          f"max rel={np.max(np.abs(adapter - manual) / manual):.2e}")
    check("O12c params адаптера == прямому фиту (rescale=False)",
          all(abs(payload["params"][k] - params[k]) < 1e-10 for k in params))
    persistence = alpha_ + beta_
    check("O12d persistence = sum(alpha)+sum(beta)",
          abs(payload["persistence"] - persistence) < 1e-10
          and payload["is_covariance_stationary"] == (persistence < 1.0))
    check("O12e convergence_flag == 0", payload["convergence_flag"] == 0)


def o13_determinism() -> None:
    from apps.api.model_impls.garch import _garch_fit_predict
    rng = np.random.default_rng(606060)
    returns = _sim_garch(rng, 300)
    a = _garch_fit_predict(list(returns), 5, random_state=123)
    b = _garch_fit_predict(list(returns), 5, random_state=123)
    c = _garch_fit_predict(list(returns), 5, random_state=456)
    check("O13a один seed: точечный прогноз и интервалы бит-идентичны",
          np.array_equal(a["variance_forecast"], b["variance_forecast"])
          and np.array_equal(a["lower"], b["lower"])
          and np.array_equal(a["upper"], b["upper"]))
    check("O13b другой seed: точечный тот же, интервалы другие",
          np.array_equal(a["variance_forecast"], c["variance_forecast"])
          and not np.array_equal(a["lower"], c["lower"]))


def o14_rescale_explicit() -> None:
    from apps.api.model_impls.garch import _garch_fit_predict
    rng = np.random.default_rng(707070)
    returns = _sim_garch(rng, 600) * 0.5  # std << 1 -- триггер DataScaleWarning,
    # но MLE ещё сходится (flag=0); на более мелких шкалах MLE не сходится и
    # адаптер обязан отказать fail-closed (проверено эмпирически, flag=4).
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        try:
            payload = _garch_fit_predict(list(returns), 3, random_state=5)
            no_warning = True
        except Warning as exc:
            payload = None
            no_warning = False
            print(f"    unexpected warning: {exc!r}")
    check("O14a rescale=False: DataScaleWarning отсутствует на мелкой шкале",
          no_warning)
    from arch import arch_model
    fitted = arch_model(np.asarray(returns), mean="Constant", vol="GARCH",
                        p=1, q=1, dist="normal", rescale=False
                        ).fit(disp="off", show_warning=False)
    params = {str(k): float(v) for k, v in fitted.params.items()}
    check("O14b параметры на шкале входа (паритет с прямым фитом)",
          payload is not None
          and all(abs(payload["params"][k] - params[k]) < 1e-10 for k in params))


def o15_fail_closed() -> None:
    from apps.api.model_impls.garch import _garch_fit_predict, validate_garch_params

    def _raises(fn) -> bool:
        try:
            fn()
            return False
        except Exception:
            return True

    rng = np.random.default_rng(808080)
    good = _sim_garch(rng, 120)
    check("O15a вырожденный вход (все нули) -- отказ", _raises(
        lambda: _garch_fit_predict([0.0] * 60, 3)))
    check("O15b NaN во входе -- отказ", _raises(
        lambda: _garch_fit_predict(list(good[:100]) + [float("nan")], 3)))
    check("O15c короткая история (<20) -- отказ", _raises(
        lambda: _garch_fit_predict(list(good[:15]), 3)))
    check("O15d p=5 вне границ [1,3] -- отказ", _raises(
        lambda: _garch_fit_predict(list(good), 3, params={"p": 5})))
    check("O15e mean='Linear' отклонён", _raises(
        lambda: validate_garch_params({"mean": "Linear"})))
    check("O15f alpha=0.025 вне {0.01,0.05,0.10} отклонён", _raises(
        lambda: validate_garch_params({"alpha": 0.025})))
    check("O15g bool на месте p отклонён (isinstance(True, int)-ловушка)",
          _raises(lambda: validate_garch_params({"p": True})))
    check("O15h horizon=0 отклонён", _raises(
        lambda: _garch_fit_predict(list(good), 0)))


def o16_engine_e2e() -> None:
    """Полный e2e путь _volatility_context -> run_volatility_backtest_plan
    на МОИХ данных: fold-locality, OOF-контракт, baseline-фолд-локальность,
    изоляция метрик уровня."""
    from apps.api.backtesting import (
        build_backtest_plan, run_volatility_backtest_plan,
    )
    from apps.api.eda_validation_strategy import build_eda_validation_strategy
    from apps.api.volatility_contract import build_volatility_target

    rng = np.random.default_rng(909090)
    n_prices = 500
    rets = _sim_garch(rng, n_prices - 1)
    # Цены обязаны СОДЕРЖАТЬ rets как свои log-returns: price_to_returns
    # внутри VolatilityTarget пересчитает returns из цен (анти-тампер)
    prices = (50.0 * np.exp(np.cumsum(np.concatenate([[0.0], rets])))).tolist()
    stamps = pd.date_range("2025-01-01", periods=n_prices, freq="B").astype(str)
    labels = [str(s) for s in stamps]

    frame = pd.DataFrame({"__date__": labels[1:], "__returns__": rets})
    level_validation = {"strategy": "expanding", "horizon": 10,
                        "effective_splits": 3, "gap": 0, "train_window": 120}
    returns_validation = build_eda_validation_strategy(
        frame, "__returns__", strategy="expanding", horizon=10, n_splits=3,
        gap=0, train_window=120,
    )
    check("O16a стратегия применима к returns (folds построены)",
          bool(returns_validation.get("applicable")),
          str(returns_validation.get("reason", ""))[:80])

    target = build_volatility_target(prices, method="log", timestamps=labels)
    from apps.api.volatility_contract import volatility_cohort_contract
    cohort = volatility_cohort_contract(
        target_column="price", fingerprint="cert-fp", returns_method="log",
        n_returns=target.n_returns, seasonal_period=1,
    )
    plan = build_backtest_plan(
        returns_validation, n_observations=target.n_returns,
        fingerprint="cert-fp", target_column="price", seasonal_period=1,
        preprocessing_signature="none", objective="volatility",
        series_fingerprints={"price": "cert-fp"},
        cohort_contract_override=cohort,
    )
    result = run_volatility_backtest_plan(
        model_id="garch", model_name="GARCH", family_id="volatility",
        target=target, plan=plan, seasonal_period=1,
    )
    check("O16b статус success, 3 fold'а, objective/cohort корректны",
          result["status"] == "success" and len(result["folds"]) == 3
          and result["objective"] == "volatility")
    check("O16c evaluation_scale == method ('log') -- изоляция шкал comparison",
          result["preprocessing"]["evaluation_scale"] == "log")

    returns_arr = target.returns_array
    oof = result["oof_predictions"]
    ok_actual, ok_label, ok_resid = True, True, True
    for point in oof:
        idx = int(point["index"])
        if abs(float(point["actual"]) - float(returns_arr[idx]) ** 2) > 1e-15:
            ok_actual = False
        if point["label"] != str(labels[idx + 1]):
            ok_label = False
        if abs(float(point["residual"])
               - round(float(point["actual"]) - float(point["predicted"]), 12)) > 1e-15:
            ok_resid = False
    check("O16d OOF: actual == квадрат return тест-окна (все точки)", ok_actual)
    check("O16e OOF: label == timestamps[index+1] (все точки)", ok_label)
    check("O16f OOF: residual == round(actual - predicted, 12)", ok_resid)

    ok_prefix, ok_nobs = True, True
    for fold in result["folds"]:
        n_train = fold["n_train"]
        if list(range(n_train)) != list(range(fold["train_start"], fold["train_end"] + 1)) \
                or fold["test_start"] <= fold["train_end"]:
            ok_prefix = False
        nobs = fold["volatility_diagnostics"]["garch"].get("nobs")
        if nobs is None or int(nobs) != n_train:
            ok_nobs = False
            print(f"    fold nobs={nobs} vs n_train={n_train}")
    check("O16g fold-locality: train -- непрерывный префикс, тест не пересекает", ok_prefix)
    check("O16h fold-locality: адаптер видел ровно n_train наблюдений (nobs)", ok_nobs)

    # Baseline: независимая EWMA-рекурсия на train-префиксе каждого fold'а
    decay = cohort["metric_policy"]["volatility"]["baseline"]["decay"]
    ok_base = True
    for fold in result["folds"]:
        n_train, horizon = fold["n_train"], fold["gap"] + fold["n_test"]
        s2 = float(np.var(returns_arr[:n_train], ddof=1))
        for v in returns_arr[:n_train]:
            s2 = decay * s2 + (1 - decay) * float(v) ** 2
        hand_pred = np.full(horizon, s2)[fold["gap"]:]
        got_pred = np.asarray([
            p["predicted"] for p in fold["volatility_baseline"]["predictions"]
        ])
        if not np.allclose(got_pred, hand_pred, rtol=1e-9, atol=0.0):
            ok_base = False
        rv = returns_arr[fold["test_start"]: fold["test_end"] + 1] ** 2
        q_hand = float(np.mean(np.log(hand_pred) + rv / hand_pred))
        if abs(fold["volatility_baseline"]["metrics"]["qlike"]
               - round(q_hand, 6)) > 5e-7:
            ok_base = False
    check("O16i baseline: EWMA cohort-decay на train-префиксе (fold-local), "
          "QLIKE == независимой рекурсии", ok_base)

    lvl = result["metrics"]
    check("O16j level-метрики на дисперсии отсутствуют (None), qlike конечен",
          lvl["mape"] is None and lvl["mase"] is None
          and lvl["weighted_score"] is None and np.isfinite(lvl["qlike"]))
    q_model = lvl["qlike"]
    q_base = result["volatility_baseline"]["aggregate"]["qlike"]
    # РЕПОРТ (не гейт): одиночная реализация -- шумная выборка; честность
    # baseline-машерии доказана O16i, статистика сравнения -- O18.
    print(f"    [REPORT O16k] qlike garch={q_model} vs ewma={q_base} "
          f"({"GARCH лучше" if q_model < q_base else "EWMA лучше на этой реализации"}; "
          "контракт не гарантирует победу в каждом розыгрыше, см. O18)")
    diag0 = result["folds"][0]["volatility_diagnostics"]
    check("O16l диагностика: standardized residuals + clustering evidence",
          diag0["standardized_residuals"]["available"] is True
          and diag0["volatility_clustering_evidence"]["available"] is True
          and diag0["garch"]["persistence"] is not None)


def o18_baseline_comparison_multiseed() -> None:
    """Репорт-исследование QLIKE GARCH vs EWMA (не гейт контракта).

    Контракт Task 134/135 не обещает победу GARCH над EWMA на каждой
    реализации: baseline -- контекст сравнения на ТЕХ ЖЕ folds/proxy
    (честность машинерии доказана O16i -- ручная рекурсия бит-в-бит).
    Здесь статистика: (a) короткие серии T=500; (b) длинные T=900;
    (c) DGP с persistence 0.98, где фиксированный EWMA(0.94) заведомо
    misspecified -- там fitted GARCH обязан выигрывать в среднем.
    """
    from apps.api.backtesting import build_backtest_plan, run_volatility_backtest_plan
    from apps.api.eda_validation_strategy import build_eda_validation_strategy
    from apps.api.volatility_contract import (
        build_volatility_target, volatility_cohort_contract,
    )

    def run_panel(name, seeds, n_prices, n_splits, horizon, dgp):
        diffs = []
        for seed in seeds:
            rng = np.random.default_rng(seed)
            rets = _sim_garch(rng, n_prices - 1, **dgp)
            prices = (50.0 * np.exp(np.cumsum(np.concatenate([[0.0], rets])))).tolist()
            labels = [str(v) for v in pd.date_range("2025-01-01", periods=n_prices, freq="B")]
            frame = pd.DataFrame({"__date__": labels[1:], "__returns__": rets})
            validation = build_eda_validation_strategy(
                frame, "__returns__", strategy="expanding", horizon=horizon,
                n_splits=n_splits, gap=0, train_window=120,
            )
            target = build_volatility_target(prices, method="log", timestamps=labels)
            cohort = volatility_cohort_contract(
                target_column="price", fingerprint="cert-fp", returns_method="log",
                n_returns=target.n_returns, seasonal_period=1,
            )
            plan = build_backtest_plan(
                validation, n_observations=target.n_returns,
                fingerprint="cert-fp", target_column="price", seasonal_period=1,
                preprocessing_signature="none", objective="volatility",
                series_fingerprints={"price": "cert-fp"},
                cohort_contract_override=cohort,
            )
            result = run_volatility_backtest_plan(
                model_id="garch", model_name="GARCH", family_id="volatility",
                target=target, plan=plan, seasonal_period=1,
            )
            q_g = result["metrics"]["qlike"]
            q_b = result["volatility_baseline"]["aggregate"]["qlike"]
            diffs.append(q_b - q_g)  # >0 = GARCH лучше
            print(f"    [{name}] seed={seed}: qlike_garch={q_g}, "
                  f"qlike_ewma={q_b}, adv(garch-ewma)={q_b - q_g:+.4f}")
        mean_adv = float(np.mean(diffs))
        wins = sum(1 for d in diffs if d > 0)
        print(f"    [{name}] ИТОГ: mean advantage GARCH={mean_adv:+.5f}, "
              f"wins={wins}/{len(diffs)}")
        return mean_adv, wins

    base_dgp = dict(omega=2e-6, alpha=0.12, beta=0.83)
    strong_dgp = dict(omega=1e-6, alpha=0.08, beta=0.90)
    a_mean, a_wins = run_panel("a T=500 3folds", (909090, 909091, 909092, 909093),
                               500, 3, 10, base_dgp)
    b_mean, b_wins = run_panel("b T=900 4folds", (909090, 909091, 909092, 909093),
                               900, 4, 12, base_dgp)
    c_mean, c_wins = run_panel("c T=900 persistence=0.98", (909090, 909091, 909092, 909093),
                               900, 4, 12, strong_dgp)
    # ГЕЙТ только на панели (c): фиксированный EWMA misspecified, fitted
    # GARCH на процессе GARCH(1,1) с persistence 0.98 обязан не проигрывать
    # в среднем -- иначе стоило бы искать дефект конвейера.
    check("O18 панель (c), EWMA misspecified: GARCH не проигрывает в среднем",
          c_mean >= 0, f"mean advantage={c_mean:+.5f}")


def o17_catalog_gates() -> None:
    from apps.api.model_readiness import PRODUCTION_BACKTEST_MODEL_IDS
    from src.catalog.modeling_spec_loader import ModelingSpec
    spec = ModelingSpec.from_yaml(str(Path(__file__).resolve().parents[1] / "rules" / "modeling.yaml"))
    garch = spec.get_model("garch")
    check("O17a modeling.yaml: garch декларирован с bounded param_space; "
          "production-статус -- из реестра (18/24)",
          garch is not None and "garch" in PRODUCTION_BACKTEST_MODEL_IDS
          and bool(garch.param_space))
    ps = garch.param_space if garch is not None else {}
    combos = 1
    for values in ps.values():
        combos *= len(values)
    check("O17b param_space garch: 16 trials (<= 64)",
          combos == 16, f"combos={combos} из {dict(ps)}")
    egarch = spec.get_model("egarch")
    check("O17c EGARCH остаётся catalog-only: нет в реестре исполнения "
          "(граница Task 136)",
          egarch is not None
          and "egarch" not in PRODUCTION_BACKTEST_MODEL_IDS)

    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY
    from apps.api.model_readiness import (
        PRODUCTION_BACKTEST_MODEL_IDS as _PBMI,
    )
    n_ready = 0
    for mid in PRODUCTION_BACKTEST_MODEL_IDS:
        try:
            MODEL_EXECUTION_REGISTRY.describe(mid)
            n_ready += 1
        except ValueError:
            pass
    check("O17d все 18 production-моделей присутствуют в реестре исполнения",
          n_ready == 18, f"registered={n_ready}")


# ---------------------------------------------------------------------------

def main() -> int:
    o1_price_to_returns()
    o2_volatility_target()
    o3_qlike_equivalence()
    o5_aggregate()
    o6_ewma()
    o7_arch_lm_oracle()
    o8_residual_diagnostics()
    o9_clustering_evidence()
    o10_cohort_contract()
    o11_registry()
    o12_garch_recursion_oracle()
    o13_determinism()
    o14_rescale_explicit()
    o15_fail_closed()
    o16_engine_e2e()
    o18_baseline_comparison_multiseed()
    o17_catalog_gates()

    failed = [name for name, ok, _ in RESULTS if not ok]
    print("\n==== ИТОГ ====")
    print(f"всего проб: {len(RESULTS)}, PASS: {len(RESULTS) - len(failed)}, "
          f"FAIL: {len(failed)}")
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    print("Все независимые оракул-пробы пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
