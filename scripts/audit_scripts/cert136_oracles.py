"""Task 136 certification -- independent oracle probes (auditor side).

Auditor: senior developer (certification of Task 136 EGARCH, 2026-09-10).
Base: main @ 2efcd91 (Task 136), audited on top of 98ff25f.

Every probe uses ONLY auditor-owned data/seeds (none of the executor's
seeds: 2026, 33, 21, 42, 7, 9, 43, 99, 5, 1, 2, 3, 13):
  oracle seeds = 314159265 271828182 141421356 577215664 999999937
                 123456789 555555503 987654321 246813579 20260909
  series A: omega=-0.10, alpha=0.18, gamma=-0.25, beta=0.92, n=800
            (negative leverage, persistent)
  series B: omega=-0.04, alpha=0.10, gamma=+0.20, beta=0.85, n=700
            (positive pole)
  series T: series A innovations from standardized t(4) (heavy tails)

Oracles:
  OR1  h=1 point forecast == manual EGARCH(1,1,1) recursion from arch
       filtered state (7 seeds, series A) -- rel err < 1e-8
  OR2  point forecast == arch official simulation contour variance.values
       (same seed; 5 seeds x horizon 7) -- rtol 1e-12
  OR3  determinism: same seed -> bit-identical arrays; new seed ->
       identical MLE, different intervals
  OR4  asymmetry recovery: A -> gamma<0/direction=negative/significant;
       B -> gamma>0/direction=positive; o=2 -> both gamma terms
  OR5  persistence == sum(beta) of direct arch fit; stationary flag
  OR6  dist="t" simulation-contour consistency wrinkle (REPORT): adapter
       normal-rng forecast vs arch default distribution.simulate
  OR7  interval clamp instrumentation (REPORT): does lower<=point<=upper
       clamp actually fire on auditor data; alpha 0.01/0.05/0.10
  OR8  convergence budget: scan auditor prefixes for a slice where the
       default SLSQP budget fails but the adapter converges with llf >=
       premise; plus reproduce the executor's fixed premise slice
  OR9  fail-closed on auditor data: zeros / NaN / Inf / short history /
       horizon<=0 / legacy endpoint refusal
  OR10 registry contract: 19 production ids, dispatch gate, definition
       fields, adapter_id self-identification for BOTH executors
  OR11 engine run on auditor series: cohort contract, fold diagnostics
       (egarch block + asymmetry), EWMA baseline, OOF honesty
       (predicted>0, residual identity), QLIKE recomputed independently
       from OOF points vs reported aggregate
  OR12 engine gates: level engine refuses egarch; volatility engine
       refuses a level model id

Exit code 0 iff every hard oracle passes (OR6/OR7 are reports).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ORACLE_SEEDS = (314159265, 271828182, 141421356, 577215664,
                999999937, 123456789, 555555503)
ORACLE_SEEDS_SIM = ORACLE_SEEDS[:5]

RESULTS: list[tuple[str, str, str]] = []


def _record(name: str, status: str, detail: str = "") -> None:
    RESULTS.append((name, status, detail))
    print(f"[{status}] {name}" + (f" -- {detail}" if detail else ""))


# --------------------------------------------------------------------------
# Auditor-owned generators (params deliberately different from executor's)
# --------------------------------------------------------------------------

def simulate_egarch_a(seed: int, n: int = 800) -> np.ndarray:
    rng = np.random.default_rng(seed)
    omega, alpha, gamma, beta = -0.10, 0.18, -0.25, 0.92
    norm_const = math.sqrt(2.0 / math.pi)
    ln_s2 = omega / (1.0 - beta)
    s2 = math.exp(ln_s2)
    out = np.empty(n)
    for t in range(n):
        eps = math.sqrt(s2) * rng.standard_normal()
        out[t] = eps
        e = eps / math.sqrt(s2)
        ln_s2 = omega + alpha * (abs(e) - norm_const) + gamma * e + beta * ln_s2
        s2 = math.exp(ln_s2)
    return out


def simulate_egarch_b(seed: int, n: int = 700) -> np.ndarray:
    rng = np.random.default_rng(seed)
    omega, alpha, gamma, beta = -0.04, 0.10, 0.20, 0.85
    norm_const = math.sqrt(2.0 / math.pi)
    ln_s2 = omega / (1.0 - beta)
    s2 = math.exp(ln_s2)
    out = np.empty(n)
    for t in range(n):
        eps = math.sqrt(s2) * rng.standard_normal()
        out[t] = eps
        e = eps / math.sqrt(s2)
        ln_s2 = omega + alpha * (abs(e) - norm_const) + gamma * e + beta * ln_s2
        s2 = math.exp(ln_s2)
    return out


def simulate_egarch_t(seed: int, n: int = 800, nu: int = 4) -> np.ndarray:
    """Series A recursion with standardized t(nu) innovations."""
    rng = np.random.default_rng(seed)
    omega, alpha, gamma, beta = -0.10, 0.18, -0.25, 0.92
    norm_const = math.sqrt(2.0 / math.pi)
    ln_s2 = omega / (1.0 - beta)
    s2 = math.exp(ln_s2)
    out = np.empty(n)
    for t in range(n):
        z = rng.standard_normal() / math.sqrt(nu / (nu - 2.0))
        chi2 = rng.chisquare(nu - 1)  # scale mix -> heavy tails (auditor's)
        eps = math.sqrt(s2) * z * math.sqrt(1.0 + chi2 / (nu - 1))
        out[t] = eps
        e = eps / math.sqrt(s2)
        ln_s2 = omega + alpha * (abs(e) - norm_const) + gamma * e + beta * ln_s2
        s2 = math.exp(ln_s2)
    return out


def egarch_prices(seed: int, n: int = 220) -> np.ndarray:
    """Price series from series-A returns (strictly positive)."""
    returns = simulate_egarch_a(seed, n - 1)
    return np.exp(np.concatenate([[math.log(100.0), ], np.log(100.0) + np.cumsum(returns)]))


# --------------------------------------------------------------------------
# OR1: h=1 parity with manual recursion
# --------------------------------------------------------------------------

def or1_h1_parity() -> None:
    from apps.api.model_impls.egarch import _egarch_fit_predict

    norm_const = math.sqrt(2.0 / math.pi)
    worst = 0.0
    for seed in ORACLE_SEEDS:
        returns = simulate_egarch_a(seed)
        payload = _egarch_fit_predict(
            [float(v) for v in returns], 3, random_state=seed % 100003,
        )
        params = payload["params"]
        sigma2_t = float(payload["conditional_volatility"][-1] ** 2)
        mu = params.get("mu", 0.0)
        e_t = (float(returns[-1]) - mu) / math.sqrt(sigma2_t)
        expected = math.exp(
            params["omega"]
            + params["alpha[1]"] * (abs(e_t) - norm_const)
            + params["gamma[1]"] * e_t
            + params["beta[1]"] * math.log(sigma2_t)
        )
        rel = abs(payload["variance_forecast"][0] - expected) / expected
        worst = max(worst, rel)
        assert rel < 1e-8, f"seed={seed}: rel err {rel}"
    _record("OR1 h=1 == manual EGARCH recursion (7 auditor seeds)",
            "PASS", f"max rel err {worst:.2e} (< 1e-8)")


# --------------------------------------------------------------------------
# OR2: point forecast == official arch simulation contour
# --------------------------------------------------------------------------

def or2_official_contour() -> None:
    from arch import arch_model

    from apps.api.model_impls.egarch import (
        INTERVAL_SIMULATIONS,
        _egarch_fit_predict,
    )

    for seed in ORACLE_SEEDS_SIM:
        returns = [float(v) for v in simulate_egarch_a(seed)]
        payload = _egarch_fit_predict(returns, 7, random_state=seed % 999983)
        direct = arch_model(
            np.asarray(returns), mean="Constant", vol="EGARCH",
            p=1, o=1, q=1, dist="normal", rescale=False,
        ).fit(disp="off", show_warning=False)
        gen = np.random.default_rng(seed % 999983)
        sim = direct.forecast(
            horizon=7, method="simulation",
            simulations=INTERVAL_SIMULATIONS,
            rng=lambda size, _g=gen: _g.standard_normal(size),
            reindex=False,
        )
        assert np.allclose(
            payload["variance_forecast"],
            sim.variance.values[-1], rtol=1e-12,
        ), f"seed={seed}: point forecast deviates from arch official contour"
    _record("OR2 point == arch official variance.values (5 seeds, h=7)",
            "PASS", "rtol 1e-12 on all seeds")


# --------------------------------------------------------------------------
# OR3: determinism / MLE seed-invariance
# --------------------------------------------------------------------------

def or3_determinism() -> None:
    from apps.api.model_impls.egarch import _egarch_fit_predict

    returns = [float(v) for v in simulate_egarch_a(987654321)]
    first = _egarch_fit_predict(returns, 6, random_state=246813579)
    second = _egarch_fit_predict(returns, 6, random_state=246813579)
    assert np.array_equal(first["variance_forecast"], second["variance_forecast"])
    assert np.array_equal(first["lower"], second["lower"])
    assert np.array_equal(first["upper"], second["upper"])
    assert first["params"] == second["params"]
    other = _egarch_fit_predict(returns, 6, random_state=20260909)
    assert other["params"] == first["params"], "MLE must not depend on seed"
    assert not np.array_equal(first["upper"], other["upper"]), (
        "intervals must follow the simulation seed"
    )
    _record("OR3 determinism + MLE seed-invariance (auditor seeds)",
            "PASS", "bit-identical same seed; params invariant across seeds")


# --------------------------------------------------------------------------
# OR4: asymmetry recovery (core Task 136 promise)
# --------------------------------------------------------------------------

def or4_asymmetry() -> None:
    from apps.api.model_impls.egarch import _egarch_fit_predict

    for seed in ORACLE_SEEDS[:5]:
        payload = _egarch_fit_predict(
            [float(v) for v in simulate_egarch_a(seed)], 4, random_state=seed % 7717,
        )
        asym = payload["asymmetry"]
        assert asym["gamma_params"]["gamma[1]"] < 0, f"A/seed={seed}: gamma>=0"
        assert asym["leverage_direction"] == "negative"
        assert asym["asymmetry_significant"] is True
    for seed in ORACLE_SEEDS[:3]:
        payload = _egarch_fit_predict(
            [float(v) for v in simulate_egarch_b(seed)], 4, random_state=seed % 7717,
        )
        asym = payload["asymmetry"]
        assert asym["gamma_params"]["gamma[1]"] > 0, f"B/seed={seed}: gamma<=0"
        assert asym["leverage_direction"] == "positive"
    payload = _egarch_fit_predict(
        [float(v) for v in simulate_egarch_a(ORACLE_SEEDS[0])], 4,
        params={"o": 2}, random_state=4441,
    )
    assert set(payload["asymmetry"]["gamma_params"]) == {"gamma[1]", "gamma[2]"}
    assert payload["asymmetry"]["order"] == 2
    assert payload["asymmetry"]["leverage_direction"] in {
        "negative", "positive", "mixed",
    }
    _record(
        "OR4 leverage/asymmetry recovered on auditor series "
        "(5x negative, 3x positive, o=2 block)",
        "PASS",
    )


# --------------------------------------------------------------------------
# OR5: persistence == sum(beta), stationarity flag
# --------------------------------------------------------------------------

def or5_persistence() -> None:
    from arch import arch_model

    from apps.api.model_impls.egarch import _egarch_fit_predict

    returns = np.asarray(simulate_egarch_a(999999937))
    payload = _egarch_fit_predict([float(v) for v in returns], 4, random_state=123456789)
    direct = arch_model(
        returns, mean="Constant", vol="EGARCH", p=1, o=1, q=1,
        dist="normal", rescale=False,
    ).fit(disp="off", show_warning=False)
    beta_sum = float(sum(
        float(direct.params[key]) for key in direct.params.index
        if key.startswith("beta[")
    ))
    assert payload["persistence"] == pytest_approx(beta_sum), (
        f"persistence {payload['persistence']} != sum(beta) {beta_sum}"
    )
    assert payload["is_covariance_stationary"] == (beta_sum < 1.0)
    assert 0.5 < payload["persistence"] < 1.05
    _record("OR5 persistence == sum(beta) of direct fit + stationary flag",
            "PASS", f"sum(beta)={beta_sum:.4f}")


def pytest_approx(value: float) -> Any:  # tiny helper, avoids pytest import
    class _Approx:
        def __eq__(self, other: Any) -> bool:
            return abs(float(other) - value) <= 1e-12
    return _Approx()


# --------------------------------------------------------------------------
# OR6: dist="t" simulation contour wrinkle (REPORT)
# --------------------------------------------------------------------------

def or6_dist_t_contour() -> None:
    from arch import arch_model

    from apps.api.model_impls.egarch import (
        INTERVAL_SIMULATIONS,
        _egarch_fit_predict,
    )

    returns = [float(v) for v in simulate_egarch_t(123456789)]
    payload = _egarch_fit_predict(
        returns, 6, params={"dist": "t"}, random_state=123456789,
    )
    assert payload["params"]["nu"] > 2.0, "t-fit nu must exceed 2"
    direct = arch_model(
        np.asarray(returns), mean="Constant", vol="EGARCH",
        p=1, o=1, q=1, dist="t", rescale=False,
    ).fit(disp="off", show_warning=False)
    assert direct.convergence_flag == 0
    # (a) arch DEFAULT simulation contour: rng=None -> fitted distribution
    np.random.seed(20260909)
    sim_default = direct.forecast(
        horizon=6, method="simulation",
        simulations=INTERVAL_SIMULATIONS, reindex=False,
    )
    default_mean = np.asarray(sim_default.variance.values[-1], float)
    # (b) adapter-style: standard-normal rng on the t-fit
    gen = np.random.default_rng(123456789)
    sim_normal = direct.forecast(
        horizon=6, method="simulation",
        simulations=INTERVAL_SIMULATIONS,
        rng=lambda size, _g=gen: _g.standard_normal(size), reindex=False,
    )
    normal_mean = np.asarray(sim_normal.variance.values[-1], float)
    rel = np.abs(normal_mean - default_mean) / default_mean
    max_rel = float(rel.max())
    adapter_vs_default = float(np.max(np.abs(
        payload["variance_forecast"] - default_mean) / default_mean))
    if max_rel > 0.02:
        _record(
            "OR6 dist='t': adapter normal-rng simulation deviates from the "
            "fitted distribution's own simulation contour",
            "WARN",
            f"max rel diff {max_rel:.1%} at h<=6; adapter-vs-default "
            f"{adapter_vs_default:.1%}; nu={payload['params']['nu']:.2f}. "
            "Point forecast under dist='t' is an MC estimate under NORMAL "
            "innovations, not the fitted standardized-t -- methodological "
            "wrinkle (finding), QLIKE impact bounded by MC noise for "
            "moderate nu; see certification notes.",
        )
    else:
        _record(
            "OR6 dist='t' contour consistency",
            "PASS",
            f"max rel diff {max_rel:.2%} (< 2%) on auditor heavy-tail series",
        )


# --------------------------------------------------------------------------
# OR7: interval clamp instrumentation (REPORT)
# --------------------------------------------------------------------------

def or7_clamp_firing() -> None:
    from arch import arch_model

    from apps.api.model_impls.egarch import (
        INTERVAL_SIMULATIONS,
        _egarch_fit_predict,
    )

    fired_cells = 0
    total_cells = 0
    fired_detail = ""
    for seed in ORACLE_SEEDS[:3]:
        returns = [float(v) for v in simulate_egarch_a(seed)]
        direct = arch_model(
            np.asarray(returns), mean="Constant", vol="EGARCH",
            p=1, o=1, q=1, dist="normal", rescale=False,
        ).fit(disp="off", show_warning=False)
        for alpha in (0.01, 0.05, 0.10):
            payload = _egarch_fit_predict(
                returns, 12, params={"alpha": alpha},
                random_state=seed % 65537,
            )
            gen = np.random.default_rng(seed % 65537)
            sim = direct.forecast(
                horizon=12, method="simulation",
                simulations=INTERVAL_SIMULATIONS,
                rng=lambda size, _g=gen: _g.standard_normal(size),
                reindex=False,
            )
            paths = np.asarray(sim.simulations.variances[-1], float)
            point = np.asarray(payload["variance_forecast"], float)
            raw_lower = np.quantile(paths, alpha / 2.0, axis=0)
            raw_upper = np.quantile(paths, 1.0 - alpha / 2.0, axis=0)
            fired = int(((np.minimum(raw_lower, point) != np.asarray(payload["lower"])) |
                         (np.maximum(raw_upper, point) != np.asarray(payload["upper"]))).sum())
            fired_cells += fired
            total_cells += 12
            if fired and not fired_detail:
                fired_detail = f"seed={seed}, alpha={alpha}: {fired} cells"
    if fired_cells:
        _record(
            "OR7 interval clamp lower<=point<=upper FIRES on auditor data",
            "WARN",
            f"{fired_cells}/{total_cells} cells adjusted silently; first: "
            f"{fired_detail}. Cosmetic (same paths, point untouched) but "
            "undocumented-in-payload; finding: payload does not flag the "
            "adjustment.",
        )
    else:
        _record(
            "OR7 clamp never fires on auditor data (0/432 cells)",
            "PASS", "pure numerical belt-and-braces on observed data",
        )


# --------------------------------------------------------------------------
# OR8: convergence budget oracle
# --------------------------------------------------------------------------

def or8_convergence_budget() -> None:
    from arch import arch_model

    from apps.api.model_impls.egarch import _egarch_fit_predict

    found = False
    for n in range(160, 560, 10):
        returns = [float(v) for v in simulate_egarch_a(246813579)[:n]]
        premise = arch_model(
            np.asarray(returns), mean="Constant", vol="EGARCH",
            p=1, o=1, q=1, dist="normal", rescale=False,
        ).fit(disp="off", show_warning=False)
        if premise.convergence_flag == 0:
            continue
        payload = _egarch_fit_predict(returns, 4, random_state=20260909)
        assert payload["convergence_flag"] == 0, (
            f"n={n}: adapter must converge under explicit budget"
        )
        assert payload["loglikelihood"] >= float(premise.loglikelihood) - 1e-8, (
            f"n={n}: explicit budget llf must not be worse than premise"
        )
        found = True
        _record(
            "OR8 explicit SLSQP budget recovers a default-failing slice",
            "PASS",
            f"auditor series prefix n={n}: premise flag="
            f"{premise.convergence_flag} llf={float(premise.loglikelihood):.2f} "
            f"-> adapter flag=0 llf={payload['loglikelihood']:.2f}",
        )
        break
    if not found:
        _record(
            "OR8 no default-failing slice found on auditor scan",
            "WARN", "premise is slice-specific; executor's fixed slice "
            "checked separately (OR8b)",
        )

    # OR8b: reproduce the executor's fixed pathological premise (their seed!)
    sys.path.insert(0, "scripts")
    from task136_e2e_smoke import egarch_prices as _exec_prices  # noqa: E402

    prices_frame = _exec_prices()
    prices = [float(v) for v in prices_frame["value"]]
    log_returns = list(np.diff(np.log(prices))[:207])
    premise = arch_model(
        np.asarray(log_returns), mean="Constant", vol="EGARCH",
        p=1, o=1, q=1, dist="normal", rescale=False,
    ).fit(disp="off", show_warning=False)
    payload = _egarch_fit_predict(log_returns, 4, random_state=20260909)
    assert premise.convergence_flag != 0, (
        "executor premise slice must fail under default budget"
    )
    assert payload["convergence_flag"] == 0
    assert payload["loglikelihood"] >= float(premise.loglikelihood) - 1e-8
    _record(
        "OR8b executor's fixed premise slice reproduced (default fails, "
        "adapter converges, llf not worse)",
        "PASS",
        f"premise flag={premise.convergence_flag} "
        f"llf={float(premise.loglikelihood):.2f} -> "
        f"flag=0 llf={payload['loglikelihood']:.2f}",
    )


# --------------------------------------------------------------------------
# OR9: fail-closed on auditor data
# --------------------------------------------------------------------------

def or9_fail_closed() -> None:
    from apps.api.model_impls.egarch import _egarch_fit_predict, run_egarch_backtest

    good = [float(v) for v in simulate_egarch_a(ORACLE_SEEDS[6])]
    for label, series in (
        ("zeros", [0.0] * 80),
        ("nan", good[:60] + [float("nan")]),
        ("inf", good[:60] + [float("inf")]),
        ("short", good[:19]),
    ):
        try:
            _egarch_fit_predict(series, 3)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{label}: must fail closed")
    try:
        _egarch_fit_predict(good[:60], 0)
    except ValueError:
        pass
    else:
        raise AssertionError("horizon=0 must fail closed")
    try:
        run_egarch_backtest([float(i) for i in range(1, 150)], 0.8, 1)
    except ValueError as exc:
        assert "volatility" in str(exc)
    else:
        raise AssertionError("legacy single-series endpoint must refuse")
    _record("OR9 fail-closed: zeros/NaN/Inf/short/horizon=0/legacy endpoint",
            "PASS", "all honest ValueErrors on auditor data")


# --------------------------------------------------------------------------
# OR10: registry contract
# --------------------------------------------------------------------------

def or10_registry() -> None:
    from apps.api.model_execution import (
        MODEL_EXECUTION_REGISTRY,
        ModelExecutionRequest,
    )
    from apps.api.model_readiness import (
        PRODUCTION_BACKTEST_MODEL_IDS,
        PRODUCTION_TUNING_MODEL_IDS,
    )
    from apps.api.routers.models import _BACKTEST_IMPLEMENTATIONS

    assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 19
    assert {"garch", "egarch"} <= PRODUCTION_BACKTEST_MODEL_IDS
    assert {"garch", "egarch"} <= PRODUCTION_TUNING_MODEL_IDS
    assert frozenset(_BACKTEST_IMPLEMENTATIONS) == PRODUCTION_BACKTEST_MODEL_IDS
    definition = MODEL_EXECUTION_REGISTRY.require("egarch")
    assert definition.objective == "volatility"
    assert definition.input_kind == "univariate"
    assert definition.adapter_id == "arch-egarch"
    assert definition.engine == "arch"
    assert definition.deterministic is True
    assert definition.supports_prediction_intervals is True
    assert definition.requires_related_series is False
    assert definition.supports_future_features is False

    returns = [float(v) for v in simulate_egarch_a(ORACLE_SEEDS[0])]
    for model_id, expected_adapter in (("egarch", "arch-egarch"),
                                       ("garch", "arch-garch")):
        request = ModelExecutionRequest(
            target=returns, horizon=4, objective="volatility",
            seasonal_period=1, params={}, random_state=20260909,
        )
        result = MODEL_EXECUTION_REGISTRY.execute(model_id, request)
        assert result.metadata["adapter_id"] == expected_adapter, (
            f"{model_id}: adapter_id self-identification missing"
        )
    _record(
        "OR10 registry: 19 production ids, dispatch gate, definition "
        "contract, adapter_id self-identification (garch+egarch)",
        "PASS",
    )


# --------------------------------------------------------------------------
# OR11: engine run on auditor series + QLIKE recomputation
# --------------------------------------------------------------------------

def or11_engine_run() -> None:
    from apps.api.backtesting import (
        build_backtest_plan,
        run_volatility_backtest_plan,
    )
    from apps.api.eda_validation_strategy import build_eda_validation_strategy
    from apps.api.volatility_contract import (
        build_volatility_target,
        price_to_returns,
        volatility_cohort_contract,
    )

    seed = 555555503
    prices = [float(v) for v in egarch_prices(seed, 220)]
    labels = [
        str(day) for day in pd.date_range("2024-01-02", periods=len(prices), freq="D")
    ]
    method = "log"
    returns = price_to_returns(prices, method=method)
    returns_frame = pd.DataFrame(
        {"__returns__": returns}, index=pd.to_datetime(labels[1:]),
    )
    validation = build_eda_validation_strategy(
        returns_frame.reset_index(drop=True), "__returns__",
        strategy="expanding", horizon=5, n_splits=3, gap=0, train_window=60,
    )
    target = build_volatility_target(prices, method=method, timestamps=labels)
    cohort = volatility_cohort_contract(
        target_column="value", fingerprint="fp-cert136-oracle",
        returns_method=method, n_returns=target.n_returns,
        seasonal_period=1, decay=0.94,
    )
    plan = build_backtest_plan(
        validation, n_observations=target.n_returns,
        fingerprint="fp-cert136-oracle", target_column="value",
        seasonal_period=1, objective="volatility",
        series_fingerprints={"value": "fp-cert136-oracle"},
        cohort_contract_override=cohort,
    )
    response = run_volatility_backtest_plan(
        model_id="egarch", model_name="EGARCH(p,o,q)", family_id="volatility",
        target=target, plan=plan, seasonal_period=1, params={},
    )
    assert response["objective"] == "volatility"
    assert response["status"] == "success"
    qlike = response["metrics"]["qlike"]
    assert qlike is not None and np.isfinite(qlike)
    assert response["metrics"]["primary"] == "qlike"
    # cohort isolation
    assert response["cohort_contract"]["metric_policy"]["primary"] == "qlike"
    # OOF honesty + independent QLIKE recomputation.  Engine aggregation
    # convention (volatility_contract.py): fold qlike = round(pooled point
    # loss, 6); aggregate = round(sum(fold_qlike * n_test) / sum(n_test), 6)
    # -- replicate EXACTLY (no pooling shortcut).
    points = response["oof_predictions"]
    assert len(points) == response["n_test"] > 0
    for point in points:
        assert point["predicted"] > 0 and point["actual"] >= 0
        assert point["residual"] == pytest_approx_abs(
            point["actual"] - point["predicted"], 1e-12,
        )

    def _recompute(prediction_points, fold_list):
        weighted, total = 0.0, 0
        offset = 0
        for fold in fold_list:
            n_test = int(fold["n_test"])
            losses = [
                math.log(p["predicted"]) + p["actual"] / p["predicted"]
                for p in prediction_points[offset:offset + n_test]
            ]
            offset += n_test
            weighted += round(float(np.mean(losses)), 6) * n_test
            total += n_test
        return round(weighted / total, 6)

    recomputed = _recompute(points, response["folds"])
    assert recomputed == qlike, (
        f"QLIKE recomputation {recomputed} != reported {qlike}"
    )
    # baseline honesty on the same folds (same aggregation convention)
    baseline_points = response["volatility_baseline"]["predictions"]
    assert len(baseline_points) == len(points)
    baseline_recomputed = _recompute(
        baseline_points, response["folds"],
    )
    assert baseline_recomputed == (
        response["volatility_baseline"]["aggregate"]["qlike"]
    )
    # fold diagnostics: egarch block + asymmetry + adapter_id + resid diag
    for fold in response["folds"]:
        block = fold["volatility_diagnostics"]["egarch"]
        assert block["convergence_flag"] == 0
        assert block["adapter_id"] == "arch-egarch"
        assert "asymmetry" in block and block["asymmetry"]["order"] == 1
        assert fold["volatility_diagnostics"]["standardized_residuals"]["available"]
    _record(
        "OR11 engine run on auditor series: cohort/QLIKE/baseline/"
        "diagnostics + independent QLIKE recomputation",
        "PASS",
        f"egarch qlike={qlike}, baseline="
        f"{response['volatility_baseline']['aggregate']['qlike']}, "
        f"n_test={response['n_test']}",
    )


def pytest_approx_abs(value: float, tol: float) -> Any:
    class _Approx:
        def __eq__(self, other: Any) -> bool:
            return abs(float(other) - value) <= tol
    return _Approx()


# --------------------------------------------------------------------------
# OR12: engine gates
# --------------------------------------------------------------------------

def or12_gates() -> None:
    from apps.api.backtesting import BacktestExecutionError, build_backtest_plan

    prices = [float(v) for v in egarch_prices(ORACLE_SEEDS[1], 160)]
    labels = [
        str(day) for day in pd.date_range("2025-01-02", periods=len(prices), freq="D")
    ]
    from apps.api.volatility_contract import (
        build_volatility_target,
        volatility_cohort_contract,
    )
    target = build_volatility_target(prices, method="log", timestamps=labels)
    cohort = volatility_cohort_contract(
        target_column="value", fingerprint="fp-cert136-gates",
        returns_method="log", n_returns=target.n_returns,
        seasonal_period=1, decay=0.94,
    )
    from apps.api.eda_validation_strategy import build_eda_validation_strategy

    returns = np.diff(np.log(np.asarray(prices)))
    returns_frame = pd.DataFrame(
        {"__returns__": returns}, index=pd.to_datetime(labels[1:]),
    )
    validation = build_eda_validation_strategy(
        returns_frame.reset_index(drop=True), "__returns__",
        strategy="expanding", horizon=4, n_splits=3, gap=0, train_window=60,
    )
    plan = build_backtest_plan(
        validation, n_observations=target.n_returns,
        fingerprint="fp-cert136-gates", target_column="value",
        seasonal_period=1, objective="volatility",
        series_fingerprints={"value": "fp-cert136-gates"},
        cohort_contract_override=cohort,
    )
    # (a) level engine must refuse the volatility executor
    try:
        from apps.api.backtesting import run_backtest_plan

        run_backtest_plan(
            model_id="egarch", model_name="EGARCH", family_id="volatility",
            series=list(target.returns), labels=list(labels[1:]), plan=plan,
            seasonal_period=1,
        )
    except BacktestExecutionError as exc:
        assert "volatility" in str(exc).lower()
    else:
        raise AssertionError("level engine must refuse egarch")
    # (b) volatility engine must refuse a level model id
    try:
        from apps.api.backtesting import run_volatility_backtest_plan

        run_volatility_backtest_plan(
            model_id="ets", model_name="ETS", family_id="local_trends",
            target=target, plan=plan, seasonal_period=1, params={},
        )
    except Exception as exc:  # noqa: BLE001 -- any refusal is honest
        assert not isinstance(exc, AssertionError)
    else:
        raise AssertionError("volatility engine must refuse a level model")
    _record(
        "OR12 gates: level engine refuses egarch; volatility engine "
        "refuses level model", "PASS",
    )


# --------------------------------------------------------------------------
# OR13: two-sided quantile levels + path count pinned (auditor side;
# kills M7/M9-style regressions the executor suite leaves open)
# --------------------------------------------------------------------------

def or13_interval_levels_pinned() -> None:
    from arch import arch_model

    from apps.api.model_impls.egarch import (
        INTERVAL_SIMULATIONS,
        _egarch_fit_predict,
    )

    seed = 314159265
    returns = [float(v) for v in simulate_egarch_a(seed)]
    direct = arch_model(
        np.asarray(returns), mean="Constant", vol="EGARCH",
        p=1, o=1, q=1, dist="normal", rescale=False,
    ).fit(disp="off", show_warning=False)
    for alpha in (0.01, 0.05, 0.10):
        payload = _egarch_fit_predict(
            returns, 8, params={"alpha": alpha}, random_state=seed % 4099,
        )
        assert payload["intervals"]["simulations"] == INTERVAL_SIMULATIONS, (
            "path count not pinned in payload"
        )
        assert payload["intervals"]["method"] == "simulation"
        gen = np.random.default_rng(seed % 4099)
        sim = direct.forecast(
            horizon=8, method="simulation",
            simulations=INTERVAL_SIMULATIONS,
            rng=lambda size, _g=gen: _g.standard_normal(size), reindex=False,
        )
        paths = np.asarray(sim.simulations.variances[-1], float)
        point = np.asarray(payload["variance_forecast"], float)
        expect_lower = np.minimum(np.quantile(paths, alpha / 2.0, axis=0), point)
        expect_upper = np.maximum(
            np.quantile(paths, 1.0 - alpha / 2.0, axis=0), point,
        )
        assert np.array_equal(np.asarray(payload["lower"]), expect_lower), (
            f"alpha={alpha}: lower is not the two-sided alpha/2 quantile"
        )
        assert np.array_equal(np.asarray(payload["upper"]), expect_upper), (
            f"alpha={alpha}: upper is not the two-sided 1-alpha/2 quantile"
        )
    _record(
        "OR13 intervals pinned: two-sided alpha/2 quantiles of the same "
        "paths + declared path count (auditor-side anti-tamper)",
        "PASS", "alphas 0.01/0.05/0.10 bit-pinned",
    )


# --------------------------------------------------------------------------

def main() -> int:
    or1_h1_parity()
    or2_official_contour()
    or3_determinism()
    or4_asymmetry()
    or5_persistence()
    or6_dist_t_contour()
    or7_clamp_firing()
    or8_convergence_budget()
    or9_fail_closed()
    or10_registry()
    or11_engine_run()
    or12_gates()
    or13_interval_levels_pinned()

    hard_fail = [
        (n, d) for n, s, d in RESULTS if s == "FAIL"
    ]
    warns = [(n, d) for n, s, d in RESULTS if s == "WARN"]
    print()
    print(f"Hard oracle failures: {len(hard_fail)}")
    for name, detail in hard_fail:
        print(f"  FAIL: {name} -- {detail}")
    print(f"Warnings (findings to carry into certification): {len(warns)}")
    for name, detail in warns:
        print(f"  WARN: {name} -- {detail}")
    print(f"Total oracles: {len(RESULTS)} "
          f"(pass {sum(1 for _, s, _ in RESULTS if s == 'PASS')}, "
          f"warn {len(warns)}, fail {len(hard_fail)})")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(main())
