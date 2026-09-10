# Аудит Task 132/133: независимые оракул-проверки (свои данные и сиды).
# Oracle = прямые вызовы официального statsmodels на тех же матрицах.
from __future__ import annotations

import numpy as np
import pandas as pd

from apps.api.model_impls.var import _var_fit_predict
from apps.api.model_impls.vecm import _vecm_fit_predict
from apps.api.multivariate_contract import (
    build_endogenous_system,
    companion_stability,
    compute_vector_metrics,
    multivariate_cohort_contract,
    vector_metric_scales,
    vecm_stability,
)
from apps.api.backtesting import build_backtest_plan, run_vector_backtest_plan
from statsmodels.tsa.vector_ar.var_model import VAR
from statsmodels.tsa.vector_ar.vecm import VECM, coint_johansen, select_coint_rank

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


# ── Мои данные (не из тестов коллеги) ────────────────────────────────────
def my_var3_system(n=160, seed=20260910):
    """Стационарная VAR(2), K=3, собственные PHI с перекрёстными связями."""
    rng = np.random.default_rng(seed)
    eps = rng.normal(size=(n, 3)) * np.array([1.0, 0.7, 1.3])
    out = np.zeros((n, 3))
    for t in range(2, n):
        out[t] = (
            0.45 * out[t - 1] - 0.10 * np.roll(out[t - 1], 1)
            + 0.20 * out[t - 2] + eps[t]
        )
    return out


def my_coint_system(n=180, seed=777):
    """Коинтегрированная тройка ранга 1: y2=y1+eps, y3=0.5*y1+20+медленный walk."""
    rng = np.random.default_rng(seed)
    y1 = 50.0 + np.cumsum(rng.normal(0, 1.2, n))
    y2 = y1 + rng.normal(0, 0.4, n)
    y3 = 0.5 * y1 + 20.0 + np.cumsum(rng.normal(0, 0.1, n)) + rng.normal(0, 0.3, n)
    return np.column_stack([y1, y2, y3])


def system_payload(matrix, horizon, params=None, **kw):
    return _var_fit_predict(
        [float(v) for v in matrix[:, 0]], horizon,
        related_series={
            name: [float(v) for v in matrix[:, i]]
            for i, name in enumerate(("ra", "rb"), start=1)
        },
        params=params, **kw,
    )


def vecm_payload(matrix, horizon, params=None, **kw):
    return _vecm_fit_predict(
        [float(v) for v in matrix[:, 0]], horizon,
        related_series={
            name: [float(v) for v in matrix[:, i]]
            for i, name in enumerate(("ra", "rb"), start=1)
        },
        params=params, **kw,
    )


print("=== A. VAR-адаптер против официального statsmodels ===")
matrix = my_var3_system()
params = {"maxlags": 3, "ic": None, "trend": "c", "alpha": 0.05}
payload = system_payload(matrix, 6, params)
fitted = VAR(matrix).fit(maxlags=3, trend="c")
point, lower, upper = fitted.forecast_interval(matrix[-3:], steps=6, alpha=0.05)
check("A1 прогноз VAR бит-в-бит == statsmodels",
      np.allclose(payload["forecast"], point, rtol=0, atol=1e-12))
check("A2 lower/upper бит-в-бит == statsmodels forecast_interval",
      np.allclose(payload["lower"], lower, rtol=0, atol=1e-12)
      and np.allclose(payload["upper"], upper, rtol=0, atol=1e-12))
check("A3 in-sample остатки == statsmodels",
      np.allclose(payload["in_sample_residuals"], np.asarray(fitted.resid), atol=1e-12))
stability = companion_stability(payload["coefficient_matrices"])
ref_stable = fitted.is_stable(verbose=False)
check("A4 is_stable согласован с VARResults.is_stable",
      stability["is_stable"] == bool(ref_stable),
      f"max_modulus={stability['max_modulus']:.6f}")

matrix_ic = my_var3_system(seed=31337)
payload_ic = system_payload(matrix_ic, 4, {"maxlags": 6, "ic": "bic"})
ref_order = VAR(matrix_ic).select_order(maxlags=6, trend="c").selected_orders["bic"]
check("A5 fold-local порядок лага == select_order(statsmodels) на том же срезе",
      payload_ic["lag_order"] == ref_order, f"p={payload_ic['lag_order']}, ref={ref_order}")

print("=== B. VARX-канал против официального statsmodels ===")
x = np.sin(np.linspace(0, 12, len(matrix))) + np.random.default_rng(5).normal(0, .05, len(matrix))
payload_x = _var_fit_predict(
    [float(v) for v in matrix[:, 0]], 5,
    related_series={"ra": [float(v) for v in matrix[:, 1]],
                    "rb": [float(v) for v in matrix[:, 2]]},
    params={"maxlags": 2, "ic": None},
    exog={"x": [float(v) for v in x]},
    exog_future={"x": [float(v) for v in x[-5:]]},
)
fit_x = VAR(matrix, exog=x).fit(maxlags=2, trend="c")
px, lx, ux = fit_x.forecast_interval(
    matrix[-2:], steps=5, alpha=0.05, exog_future=x[-5:],
)
check("B1 VARX прогноз бит-в-бит == statsmodels VAR(exog=...)",
      np.allclose(payload_x["forecast"], px, atol=1e-12))
check("B2 VARX интервалы бит-в-бит == statsmodels exog_future",
      np.allclose(payload_x["lower"], lx, atol=1e-12)
      and np.allclose(payload_x["upper"], ux, atol=1e-12))

print("=== C. VECM-адаптер против официального statsmodels ===")
coint = my_coint_system()
vp = vecm_payload(coint, 5, {"k_ar_diff": 1, "coint_rank": "auto",
                             "deterministic": "ci", "alpha": 0.05})
rank_ref = select_coint_rank(coint, det_order=0, k_ar_diff=1,
                             method="trace", signif=0.05).rank
check("C1 auto-ранг == select_coint_rank(trace, 0.05) на той же матрице",
      vp["coint_rank"] == rank_ref, f"rank={vp['coint_rank']}")
jh = coint_johansen(coint, det_order=0, k_ar_diff=1)
trace_rank = int(np.sum(jh.lr1 > jh.cvt[:, 1]))
check("C2 ранг согласован с прямым coint_johansen (95%)",
      trace_rank >= 1 and vp["coint_rank"] >= 1,
      f"trace_rank(95%)={trace_rank}")
fit_v = VECM(coint, k_ar_diff=1, coint_rank=rank_ref, deterministic="ci").fit()
pv, lv, uv = fit_v.predict(steps=5, alpha=0.05)
check("C3 VECM прогноз бит-в-бит == VECMResults.predict",
      np.allclose(vp["forecast"], pv, atol=1e-12))
check("C4 VECM интервалы бит-в-бит == predict(alpha=0.05)",
      np.allclose(vp["lower"], lv, atol=1e-12)
      and np.allclose(vp["upper"], uv, atol=1e-12))
check("C5 var_rep-блоки == statsmodels (VAR(k_ar_diff+1) в уровнях)",
      len(vp["coefficient_matrices"]) == len(fit_v.var_rep)
      and all(np.allclose(a, b, atol=1e-12)
              for a, b in zip(vp["coefficient_matrices"], fit_v.var_rep)))
st_v = vecm_stability(vp["coefficient_matrices"], coint_rank=vp["coint_rank"])
check("C6 vecm_stability: единичные корни == coint_rank на реальном fit",
      st_v["n_unit_roots"] == vp["coint_rank"] and st_v["is_stable"],
      f"n_unit={st_v['n_unit_roots']}, rank={vp['coint_rank']}")

print("=== D. Векторный движок: fold-оракул (префикс и gap) ===")
n = len(matrix)
labels = [d.strftime("%Y-%m-%d") for d in pd.date_range("2021-03-01", periods=n, freq="D")]
system = build_endogenous_system(
    {name: [float(v) for v in matrix[:, i]]
     for i, name in enumerate(("y", "ra", "rb"))},
    timestamps=labels,
)
from app.core.passport import series_fingerprint
fingerprints = {
    name: series_fingerprint(pd.Series(matrix[:, i], index=labels))
    for i, name in enumerate(("y", "ra", "rb"))
}
contract = multivariate_cohort_contract(system, series_fingerprints=fingerprints)
horizon, gap, n_splits = 4, 2, 2
train_end = n - n_splits * horizon - gap * n_splits - 1
folds = []
for i in range(n_splits):
    start_test = train_end + 1 + gap + (horizon + gap) * i
    folds.append({"fold": i + 1, "train_start": 0,
                  "train_end": train_end + (horizon + gap) * i,
                  "gap_size": gap, "test_start": start_test,
                  "test_end": start_test + horizon - 1})
plan = build_backtest_plan(
    {"strategy": "expanding", "horizon": horizon, "n_splits": n_splits,
     "gap": gap, "folds": folds},
    n_observations=n, fingerprint="fp-audit", target_column="y",
    seasonal_period=1, objective="multivariate",
    series_fingerprints=fingerprints, cohort_contract_override=contract,
)
result = run_vector_backtest_plan(
    model_id="var", model_name="VAR", family_id="multivariate",
    system=system, plan=plan, seasonal_period=1,
    params={"maxlags": 2, "ic": None},
)
for fold in result["folds"]:
    n_train = fold["n_train"]
    manual = _var_fit_predict(
        [float(v) for v in matrix[:n_train, 0]], gap + horizon,
        related_series={
            "ra": [float(v) for v in matrix[:n_train, 1]],
            "rb": [float(v) for v in matrix[:n_train, 2]],
        },
        params={"maxlags": 2, "ic": None},
    )
    engine_pred = {
        (p["horizon_step"], p["series"]): p["predicted"]
        for p in fold["predictions"]
    }
    ok = True
    for step, name in enumerate(("y", "ra", "rb")):
        for h in range(horizon):
            key = (h + 1, name)
            if abs(engine_pred[key] - manual["forecast"][gap + h, step]) > 1e-12:
                ok = False
    check(f"D-fold{fold['fold']} OOF == адаптер на точном префиксе "
          f"[:n_train] с отбрасыванием gap", ok,
          f"n_train={n_train}")

print("=== E. Векторные метрики: ручная арифметика ===")
names = ("y", "ra")
rng = np.random.default_rng(11)
actual = rng.normal(10, 2, size=(3, 2))
pred = actual + rng.normal(0, 0.5, size=(3, 2))
train = rng.normal(10, 2, size=(40, 2))
scales = {}
for i, name in enumerate(names):
    diffs = np.abs(np.diff(train[:, i]))
    scales[name] = float(diffs.mean())
scales_engine = vector_metric_scales(train, names, seasonal_period=1)
check("E1 mase_scale == mean|diff(train)| каждой серии",
      all(abs(scales_engine[nm]["mase_scale"] - scales[nm]) < 1e-12 for nm in names))
m = compute_vector_metrics(actual, pred, names,
                           mase_scales={nm: scales[nm] for nm in names},
                           rmsse_scales={nm: scales[nm] for nm in names})
manual_mae = {nm: float(np.mean(np.abs(actual[:, i] - pred[:, i])))
              for i, nm in enumerate(names)}
check("E2 per-series MAE ручная == движок",
      all(abs(m["per_series"][nm].mae - manual_mae[nm]) < 1e-6 for nm in names))
mase_vals = [m["per_series"][nm].mase for nm in names]
check("E3 scaled_loss == mean(per-series MASE) (all-or-none)",
      abs(m["scaled_loss"] - float(np.mean(mase_vals))) < 1e-6)

print()
print(f"ИТОГО: {len(PASS)} PASS / {len(FAIL)} FAIL")
if FAIL:
    print("Провалы:", FAIL)
