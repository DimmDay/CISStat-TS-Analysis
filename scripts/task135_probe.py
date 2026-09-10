# scripts/task135_probe.py
"""Task 135 design reconnaissance: arch (official circuit) oracle facts.

1) determinism: fit+analytic forecast bit-identical across runs;
2) simulation intervals with seeded random_state bit-identical;
3) analytic variance forecast == manual GARCH(1,1) recursion on fitted params;
4) rescale=False: NO hidden rescaling (params on the raw return scale);
5) degenerate input (zero variance) fails closed;
6) std_resid / conditional_volatility available for diagnostics;
7) timing sanity on production-sized folds.
"""
import time

import numpy as np
from arch import arch_model


def sample_returns(n: int = 300, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    omega, alpha, beta = 1e-6, 0.10, 0.85
    sigma2 = omega / (1 - alpha - beta)
    out = np.empty(n)
    for t in range(n):
        eps = rng.standard_normal() * np.sqrt(sigma2)
        out[t] = eps
        sigma2 = omega + alpha * eps**2 + beta * sigma2
    return out


def main() -> None:
    r = sample_returns()

    # (1) determinism of fit + analytic forecast
    def fit_and_forecast():
        am = arch_model(r, mean="Constant", vol="GARCH", p=1, q=1,
                        dist="normal", rescale=False)
        fit = am.fit(disp="off", show_warning=False)
        fc = fit.forecast(horizon=5, method="analytic", reindex=False)
        return fit, np.asarray(fc.variance.values[-1], dtype=float)

    fit1, var1 = fit_and_forecast()
    fit2, var2 = fit_and_forecast()
    assert np.array_equal(var1, var2), "analytic forecast not deterministic"
    assert fit1.params.equals(fit2.params), "params not deterministic"
    print("(1) analytic determinism OK; forecast:", var1)

    # (3) manual GARCH(1,1) recursion on fitted params, seeded from arch's
    # own filtered state (conditional_volatility[-1]^2): h=1 uses the last
    # observed eps^2; h>=2 replaces unobserved eps^2 by its expectation.
    params = fit1.params
    mu = float(params["mu"])
    omega = float(params["omega"])
    alpha1 = float(params["alpha[1]"])
    beta1 = float(params["beta[1]"])
    eps = r - mu
    sigma2_t = float(np.asarray(fit1.conditional_volatility, dtype=float)[-1] ** 2)
    sigma2_next = omega + alpha1 * eps[-1] ** 2 + beta1 * sigma2_t
    manual = [sigma2_next]
    for _ in range(4):
        sigma2_next = omega + (alpha1 + beta1) * sigma2_next
        manual.append(sigma2_next)
    manual = np.asarray(manual)
    assert np.allclose(var1, manual, rtol=1e-8), (
        f"analytic != manual recursion: {var1} vs {manual}"
    )
    print("(3) oracle parity analytic == manual recursion OK (rtol 1e-8)")

    # (2) simulation intervals determinism via seeded rng-callable
    # (arch: random_state is for 'bootstrap' only; 'simulation' takes rng).
    def sim_interval(seed: int):
        gen = np.random.default_rng(seed)
        fc = fit1.forecast(
            horizon=5, method="simulation", simulations=500,
            rng=lambda size: gen.standard_normal(size), reindex=False,
        )
        sims = np.asarray(fc.simulations.variances[-1], dtype=float)  # (sims, horizon)
        return np.quantile(sims, [0.025, 0.975], axis=0)

    s1, s2 = sim_interval(42), sim_interval(42)
    assert np.array_equal(s1, s2), "simulation intervals not deterministic"
    s3 = sim_interval(43)
    assert not np.array_equal(s1, s3), "different seeds gave identical paths"
    assert (s1[0] <= var1).all() and (var1 <= s1[1]).all()
    print("(2) simulation intervals deterministic (seeded), bracket point fc OK")

    # (4) rescale=False keeps raw scale
    assert float(fit1.params["omega"]) < 1e-3, "omega rescaled: hidden transform"
    print("(4) rescale=False: omega on raw scale OK:", float(fit1.params["omega"]))

    # (5) degenerate input: zero variance fails closed
    zeros = np.zeros(120)
    am0 = arch_model(zeros, mean="Zero", vol="GARCH", p=1, q=1,
                     dist="normal", rescale=False)
    try:
        am0.fit(disp="off", show_warning=False)
        print("(5) DEGENERATE: fit unexpectedly succeeded")
    except Exception as exc:  # noqa: BLE001
        print("(5) degenerate fails closed OK:", type(exc).__name__, str(exc)[:80])

    # (6) diagnostics accessors
    z = np.asarray(fit1.std_resid, dtype=float)
    cv = np.asarray(fit1.conditional_volatility, dtype=float)
    assert np.isfinite(z).all() and np.isfinite(cv).all()
    assert np.allclose(z * cv, r - float(fit1.params["mu"]), atol=1e-10)
    print("(6) std_resid/conditional_volatility OK; len(z)=", z.size)

    # (7) timing sanity: fold-sized train (e.g. 130) and full grid trial
    t0 = time.monotonic()
    small = arch_model(r[:130], mean="Constant", vol="GARCH", p=2, q=2,
                       dist="t", rescale=False)
    f2 = small.fit(disp="off", show_warning=False)
    f2.forecast(horizon=8, method="analytic", reindex=False)
    print(f"(7) p=2,q=2,dist=t n=130 fit+forecast: {time.monotonic()-t0:.3f}s; conv={f2.convergence_flag}")

    # (8) forecast beyond data: long horizon OK
    long_fc = fit1.forecast(horizon=64, method="analytic", reindex=False)
    assert np.asarray(long_fc.variance.values[-1]).shape == (64,)
    print("(8) long-horizon analytic forecast OK")

    print("ALL PROBES OK")


if __name__ == "__main__":
    main()
