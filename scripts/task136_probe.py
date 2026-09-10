"""Task 136 design recon: EGARCH in arch 8.0 -- empirical facts.

Facts to verify (design input, before tests):
 1. EGARCH(1,1,1) fit: param names (omega/alpha[1]/gamma[1]/beta[1]),
    pvalues/std_err availability for gamma.
 2. Analytic forecast h=1 == manual recursion (rtol 1e-8).
 3. Analytic forecast h>1 raises ValueError (arch hard gate).
 4. Simulation paths: shape (sims, horizon); MC error of mean vs analytic
    h=1 at sims 1000/2000/4000/8000; runtime.
 5. Determinism bit-in-bit (same seed); different seed -> different paths.
 6. rescale=None -> DataScaleWarning on small returns; rescale=False -> no
    warning; params parity with direct arch fit.
 7. Leverage recovery: fitted gamma[1] < 0 on simulated leverage series.
 8. Degenerate input (all zeros): convergence_flag != 0 fail-closed.
 9. o=0 (symmetric EGARCH) is constructible but out of scope for Task 136.
"""
from __future__ import annotations

import time
import warnings

import numpy as np
from arch import arch_model


def simulate_egarch(rng, n=600, omega=-0.05, alpha=0.12, gamma=-0.15, beta=0.90):
    """Manual EGARCH(1,1,1) with classic negative leverage."""
    norm_const = np.sqrt(2.0 / np.pi)
    ln_s2 = omega / (1.0 - beta)
    s2 = float(np.exp(ln_s2))
    e_prev = 0.0
    returns = []
    for _ in range(n):
        z = rng.standard_normal()
        eps = float(np.sqrt(s2) * z)
        returns.append(eps)
        # next-period log variance from current standardized shock
        e = eps / np.sqrt(s2)
        ln_s2 = omega + alpha * (abs(e) - norm_const) + gamma * e + beta * ln_s2
        s2 = float(np.exp(ln_s2))
        e_prev = e
    return np.asarray(returns), e_prev


def main() -> None:
    rng = np.random.default_rng(2026)
    returns, _ = simulate_egarch(rng, n=600)
    print(f"[1] simulated leverage series: n={len(returns)}, "
          f"std={returns.std():.4f}")

    # Fact 6a: rescale=None warns on small returns
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        m = arch_model(returns, mean="Constant", vol="EGARCH", p=1, o=1, q=1,
                       dist="normal", rescale=None)
        m.fit(disp="off", show_warning=False)
    scale_warn = [w for w in caught if issubclass(w.category, Warning)
                  and "rescale" in str(w.message).lower()]
    print(f"[6a] rescale=None warnings: {[str(w.message)[:60] for w in scale_warn]}")

    # Fact 1: param names and gamma metadata
    model = arch_model(returns, mean="Constant", vol="EGARCH", p=1, o=1, q=1,
                       dist="normal", rescale=False)
    fitted = model.fit(disp="off", show_warning=False)
    params = {k: float(v) for k, v in fitted.params.items()}
    print(f"[1] params: {params}")
    print(f"[1] convergence_flag={fitted.convergence_flag}, "
          f"nobs={fitted.nobs}")
    pvalues = {k: float(v) for k, v in fitted.pvalues.items()}
    std_err = {k: float(v) for k, v in fitted.std_err.items()}
    print(f"[1] gamma pvalue={pvalues.get('gamma[1]')}, "
          f"gamma std_err={std_err.get('gamma[1]')}")

    # Fact 2: analytic h=1 == manual recursion
    sigma2_T = float(fitted.conditional_volatility[-1] ** 2)
    mu = float(fitted.params.get("mu", 0.0))
    resid_T = float(returns[-1] - mu)
    e_T = resid_T / np.sqrt(sigma2_T)
    omega_f = params["omega"]
    alpha_f = params["alpha[1]"]
    gamma_f = params["gamma[1]"]
    beta_f = params["beta[1]"]
    norm_const = np.sqrt(2.0 / np.pi)
    expected_h1 = np.exp(
        omega_f + alpha_f * (abs(e_T) - norm_const)
        + gamma_f * e_T + beta_f * np.log(sigma2_T)
    )
    analytic1 = fitted.forecast(horizon=1, method="analytic", reindex=False)
    arch_h1 = float(analytic1.variance.values[-1][0])
    print(f"[2] manual h=1: {expected_h1:.10e}, arch analytic h=1: "
          f"{arch_h1:.10e}, rel err={abs(arch_h1 - expected_h1)/expected_h1:.2e}")

    # Fact 3: analytic h>1 must raise
    try:
        fitted.forecast(horizon=2, method="analytic", reindex=False)
        print("[3] analytic h=2: NO ERROR (unexpected!)")
    except ValueError as exc:
        print(f"[3] analytic h=2 raises: {exc}")

    # Fact 4: simulation paths, MC error vs analytic h=1, timing
    for sims in (1000, 2000, 4000, 8000):
        gen = np.random.default_rng(42)

        def rng_fn(size, _gen=gen):
            return _gen.standard_normal(size)

        t0 = time.monotonic()
        sim = fitted.forecast(horizon=30, method="simulation",
                              simulations=sims, rng=rng_fn, reindex=False)
        dt = time.monotonic() - t0
        paths = np.asarray(sim.simulations.variances[-1], dtype=float)
        mean_h1 = float(paths[:, 0].mean())
        rel = abs(mean_h1 - arch_h1) / arch_h1
        print(f"[4] sims={sims}: paths {paths.shape}, MC rel err h=1 "
              f"{rel:.4f}, runtime {dt:.2f}s")

    # Fact 5: determinism bit-in-bit
    def run_seed(seed):
        gen = np.random.default_rng(seed)
        s = fitted.forecast(horizon=10, method="simulation", simulations=1000,
                            rng=lambda size: gen.standard_normal(size),
                            reindex=False)
        return (np.asarray(s.simulations.variances[-1], dtype=float),
                np.asarray(s.variance.values[-1], dtype=float))

    p1, v1 = run_seed(42)
    p2, v2 = run_seed(42)
    p3, v3 = run_seed(43)
    print(f"[5] same seed identical: {np.array_equal(p1, p2)}; "
          f"diff seed differs: {not np.array_equal(p1, p3)}")
    print(f"[5] arch mean from variance.values == path mean: "
          f"{np.allclose(v1, p1.mean(axis=0), rtol=0)}")

    # Fact 6b: rescale=False parity with direct fit params
    print(f"[6b] rescale=False params on returns scale: omega={omega_f:.6f}")

    # Fact 7: leverage recovery (gamma sign) on 3 seeds
    for seed in (1, 2, 3):
        r, _ = simulate_egarch(np.random.default_rng(seed), n=600)
        f = arch_model(r, mean="Constant", vol="EGARCH", p=1, o=1, q=1,
                       dist="normal", rescale=False).fit(disp="off",
                                                         show_warning=False)
        g = float(f.params["gamma[1]"])
        b1 = float(f.params["beta[1]"])
        print(f"[7] seed={seed}: gamma[1]={g:+.4f} (negative={g < 0}), "
              f"beta[1]={b1:.4f}, sum(beta)={b1:.4f} <1: {b1 < 1}")

    # Fact 8: degenerate all-zero input
    zeros = np.zeros(100)
    try:
        fz = arch_model(zeros, mean="Constant", vol="EGARCH", p=1, o=1, q=1,
                        dist="normal", rescale=False).fit(disp="off",
                                                          show_warning=False)
        print(f"[8] zeros: convergence_flag={fz.convergence_flag}, "
              f"std_resid finite="
              f"{bool(np.isfinite(np.asarray(fz.std_resid, dtype=float)).all())}")
    except Exception as exc:
        print(f"[8] zeros: raises {type(exc).__name__}: {str(exc)[:80]}")

    # Fact 9: o=0 constructible (symmetric exponential GARCH)
    m0 = arch_model(returns, mean="Constant", vol="EGARCH", p=1, o=0, q=1,
                    dist="normal", rescale=False)
    print(f"[9] o=0 constructible: {m0 is not None} (bounds keep o>=1: "
          f"Task 136 requires asymmetry terms)")

    # persistence: arch does NOT provide fitted.persistence for EGARCH?
    print(f"[10] fitted has 'persistence' attr: "
          f"{hasattr(fitted, 'persistence')}")


if __name__ == "__main__":
    main()
