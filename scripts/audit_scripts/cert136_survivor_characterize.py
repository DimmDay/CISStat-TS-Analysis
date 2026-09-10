"""Characterization probes for mutation survivors M6/M12/M13 (auditor side).

M6: when does arch actually rescale? (data-dependence of the rescale test)
M12: on the executor's own test data, WHERE does the interval clamp fire?
M13: what does arch raise on NaN input when the adapter's guard is absent?
"""
from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path

import numpy as np
from arch import arch_model

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def leverage_returns(seed: int = 2026, n: int = 260) -> np.ndarray:
    rng = np.random.default_rng(seed)
    omega, alpha, gamma, beta = -0.05, 0.12, -0.15, 0.90
    nc = math.sqrt(2 / math.pi)
    ln_s2 = omega / (1 - beta)
    s2 = math.exp(ln_s2)
    out = np.empty(n)
    for t in range(n):
        eps = math.sqrt(s2) * rng.standard_normal()
        out[t] = eps
        e = eps / math.sqrt(s2)
        ln_s2 = omega + alpha * (abs(e) - nc) + gamma * e + beta * ln_s2
        s2 = math.exp(ln_s2)
    return out


def m6_rescale_threshold() -> None:
    series = leverage_returns()
    print(f"M6 base series std = {series.std():.4f}")
    for scale, label in ((1.0, "x1 (std 0.84)"), (1e-2, "x0.01 (std 0.0084)"),
                         (1e-3, "x0.001 (std 0.00084)")):
        data = series * scale
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            rescaled_fit = arch_model(
                data, mean="Constant", vol="EGARCH", p=1, o=1, q=1,
                dist="normal", rescale=True,
            ).fit(disp="off", show_warning=False)
            warns = [str(w.message)[:60] for w in caught
                     if issubclass(w.category, Warning)]
        base_fit = arch_model(
            data, mean="Constant", vol="EGARCH", p=1, o=1, q=1,
            dist="normal", rescale=False,
        ).fit(disp="off", show_warning=False)
        same = math.isclose(
            float(rescaled_fit.params["omega"]),
            float(base_fit.params["omega"]), rel_tol=1e-12,
        )
        print(f"  {label}: rescale=True params identical to rescale=False: "
              f"{same}; warnings={len(warns)} {warns[:1]}")


def m12_clamp_regime() -> None:
    from apps.api.model_impls.egarch import (
        INTERVAL_SIMULATIONS,
        _egarch_fit_predict,
    )

    series = leverage_returns()
    direct = arch_model(
        series, mean="Constant", vol="EGARCH", p=1, o=1, q=1,
        dist="normal", rescale=False,
    ).fit(disp="off", show_warning=False)
    for horizon in (3, 4, 6, 8, 12, 20):
        for alpha in (0.01, 0.05, 0.10):
            payload = _egarch_fit_predict(
                [float(v) for v in series], horizon,
                params={"alpha": alpha}, random_state=42,
            )
            gen = np.random.default_rng(42)
            sim = direct.forecast(
                horizon=horizon, method="simulation",
                simulations=INTERVAL_SIMULATIONS,
                rng=lambda size, _g=gen: _g.standard_normal(size),
                reindex=False,
            )
            paths = np.asarray(sim.simulations.variances[-1], float)
            point = np.asarray(payload["variance_forecast"], float)
            raw_u = np.quantile(paths, 1 - alpha / 2, axis=0)
            raw_l = np.quantile(paths, alpha / 2, axis=0)
            upper_hits = int((raw_u < point).sum())
            lower_hits = int((raw_l > point).sum())
            if upper_hits or lower_hits:
                print(f"  M12 clamp FIRES on executor test data: horizon={horizon} "
                      f"alpha={alpha}: upper<point {upper_hits} cells, "
                      f"lower>point {lower_hits} cells "
                      f"(raw upper {raw_u.min():.4e} vs point {point.min():.4e})")
    print("  M12 done (silence above = no firing on executor data)")


def m13_arch_nan_error() -> None:
    series = leverage_returns(n=60)
    series[7] = float("nan")
    try:
        arch_model(
            series, mean="Constant", vol="EGARCH", p=1, o=1, q=1,
            dist="normal", rescale=False,
        ).fit(disp="off", show_warning=False)
    except Exception as exc:  # noqa: BLE001
        print(f"M13 arch on NaN input: {type(exc).__name__}: {str(exc)[:110]}")
    else:
        print("M13 arch on NaN input: FIT SUCCEEDED (no error!)")


if __name__ == "__main__":
    m6_rescale_threshold()
    m12_clamp_regime()
    m13_arch_nan_error()
