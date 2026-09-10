"""Focused OR6 characterization: does the adapter's normal-rng simulation
contour systematically deviate from a properly standardized-t contour for
dist='t' fits with small fitted nu?

Method: simulate EGARCH(1,1,1) with t(3) innovations (strong heavy tails),
fit dist='t' (expect small nu), then compare at sims=200_000:
  (a) adapter-style normal-rng contour
  (b) standardized-t-rng contour (fitted distribution's law)
  (c) arch default contour (rng=None, unseeded) -- reference only
Systematic drift direction/magnitude is what matters, not MC noise.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from arch import arch_model

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def simulate_egarch_t3(seed: int, n: int = 900) -> np.ndarray:
    rng = np.random.default_rng(seed)
    omega, alpha, gamma, beta = -0.10, 0.18, -0.25, 0.92
    norm_const = math.sqrt(2.0 / math.pi)
    ln_s2 = omega / (1.0 - beta)
    s2 = math.exp(ln_s2)
    out = np.empty(n)
    for t in range(n):
        t_draw = rng.standard_t(3) / math.sqrt(3.0 / 1.0)  # Var(t3)=3 -> std t3
        # standardized to Var=1: t3/sqrt(3) has Var=1
        eps = math.sqrt(s2) * t_draw
        out[t] = eps
        e = eps / math.sqrt(s2)
        ln_s2 = omega + alpha * (abs(e) - norm_const) + gamma * e + beta * ln_s2
        s2 = math.exp(ln_s2)
    return out


def main() -> None:
    returns = np.asarray(simulate_egarch_t3(777001))
    fit = arch_model(
        returns, mean="Constant", vol="EGARCH", p=1, o=1, q=1,
        dist="t", rescale=False,
    ).fit(disp="off", show_warning=False)
    nu = float(fit.params["nu"])
    print(f"fitted nu = {nu:.3f} (small => heavy tails confirmed)")
    assert fit.convergence_flag == 0

    sims = 200_000
    horizon = 6

    gen_n = np.random.default_rng(314159265)
    sim_normal = fit.forecast(
        horizon=horizon, method="simulation", simulations=sims,
        rng=lambda size, _g=gen_n: _g.standard_normal(size), reindex=False,
    )
    gen_t = np.random.default_rng(314159265)

    def t_rng(size, _g=gen_t, _nu=nu):
        z = _g.standard_t(_nu, size=size) / math.sqrt(_nu / (_nu - 2.0))
        return z

    sim_t = fit.forecast(
        horizon=horizon, method="simulation", simulations=sims,
        rng=t_rng, reindex=False,
    )
    mean_normal = np.asarray(sim_normal.variance.values[-1], float)
    mean_t = np.asarray(sim_t.variance.values[-1], float)
    rel = (mean_normal - mean_t) / mean_t
    print("h      normal-rng mean   t-rng mean        rel diff")
    for h in range(horizon):
        print(f"{h+1}  {mean_normal[h]:12.6e}  {mean_t[h]:12.6e}  {rel[h]:+.3%}")
    print(f"\nSystematic deviation (normal vs t contour) at 200k paths: "
          f"h=1 {rel[0]:+.3%} .. h={horizon} {rel[-1]:+.3%}")
    # tail behavior: interval widths
    paths_n = np.asarray(sim_normal.simulations.variances[-1], float)
    paths_t = np.asarray(sim_t.simulations.variances[-1], float)
    for name, paths in (("normal-rng", paths_n), ("t-rng", paths_t)):
        up = np.quantile(paths, 0.995, axis=0)
        lo = np.quantile(paths, 0.005, axis=0)
        print(f"{name}: h=6 [q0.5%,q99.5%] = [{lo[5]:.4e}, {up[5]:.4e}]")


if __name__ == "__main__":
    main()
