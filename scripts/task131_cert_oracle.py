# scripts/task131_cert_oracle.py — независимая сверка сертификации Task 131
from __future__ import annotations

import numpy as np
import pytest
from statsmodels.tsa.vector_ar.var_model import VAR
from statsmodels.tsa.vector_ar.vecm import coint_johansen

from apps.api.multivariate_contract import (
    companion_stability,
    compute_vector_metrics,
    fold_cointegration_evidence,
    multivariate_cohort_contract,
    system_white_noise_diagnostics,
    validate_regular_grid,
    vector_metric_scales,
    vector_oof_points,
)

ok = 0
fail = 0


def check(label: str, cond: bool) -> None:
    global ok, fail
    if cond:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label}")


print("== 1. Portmanteau oracle: мои данные (K=4, p=3, mean!=0), оба варианта adjusted ==")
rng = np.random.default_rng(2026)
data = np.column_stack(
    [np.cumsum(rng.normal(size=220)) for _ in range(3)]
    + [rng.normal(size=220) * 3.0 + 11.0]
)
fitted = VAR(data).fit(3)
resid = np.asarray(fitted.resid)
for adjusted in (True, False):
    mine = system_white_noise_diagnostics(
        resid, nlags=10, fitted_var_order=3, adjusted=adjusted,
    )
    oracle = fitted.test_whiteness(nlags=10, adjusted=adjusted)
    rel = abs(mine["joint"]["statistic"] - float(oracle.test_statistic)) / abs(
        float(oracle.test_statistic)
    )
    check(
        f"adjusted={adjusted}: statistic rel={rel:.2e}, df={mine['joint']['df']}=={oracle.df}",
        rel < 1e-10 and mine["joint"]["df"] == int(oracle.df),
    )

print("== 2. Йохансен: alpha 0.10/0.01, cointegrated vs independent (мои seed) ==")
rng = np.random.default_rng(31337)
x = np.cumsum(rng.normal(size=200))
y = 1.7 * x + rng.normal(size=200) * 0.3
z = np.cumsum(rng.normal(size=200))
matrix = np.column_stack([x, y, z])
ev = fold_cointegration_evidence(matrix, det_order=0, k_ar_diff=2, alpha=0.10)
ref = coint_johansen(matrix, 0, 2)
check("alpha=0.10: stats == coint_johansen (rel 1e-12)",
      np.allclose(ev["trace"]["statistics"], ref.lr1, rtol=1e-12))
check("alpha=0.10: rank>=1 (y=1.7x+eps коинтегрирована)",
      ev["trace"]["rank"] >= 1 and ev["cointegration_evidence"])
check("alpha=0.10: cv колонка соответствует 90%",
      np.allclose(ev["trace"]["critical_values"]["90"], ref.cvt[:, 0]))
ev01 = fold_cointegration_evidence(matrix, det_order=0, k_ar_diff=2, alpha=0.01)
check("alpha=0.01: cv колонка соответствует 99%",
      np.allclose(ev01["trace"]["critical_values"]["99"], ref.cvt[:, 2]))
seq_ok = ev["trace"]["rank"] == 1 or ev["trace"]["rank"] == 2
check("последовательное правило ранга (rank in {1,2} для 3 рядов)", seq_ok)

print("== 3. Мои mutation spot-checks ==")
try:
    validate_regular_grid(
        ["2024-01-03", "2024-01-01", "2024-01-02", "2024-01-04",
         "2024-01-05", "2024-01-06"]
    )
    check("несортированная сетка отвергается (fail-closed)", False)
except Exception as exc:
    check(f"несортированная сетка отвергается: {type(exc).__name__}", True)

pts = vector_oof_points(
    fold=1, test_indices=[40, 41],
    actual_matrix=np.array([[2.0, 8.0], [4.0, 10.0]]),
    predicted_matrix=np.array([[1.0, 9.0], [5.0, 12.0]]),
    names=("b", "a"),
)
order = [(p["horizon_step"], p["series"]) for p in pts]
check("порядок (шаг, серия-объявление) без сортировки имён",
      order == [(1, "b"), (1, "a"), (2, "b"), (2, "a")])
resid_map = {(p["horizon_step"], p["series"]): p["residual"] for p in pts}
check("residual = actual - predicted (знак)",
      resid_map[(1, "b")] == 1.0 and resid_map[(2, "a")] == -2.0)

rng = np.random.default_rng(5)
c1 = np.abs(rng.normal(size=30)) + 0.5
c2 = np.abs(rng.normal(size=30)) * 100.0 + 5.0
m1 = vector_metric_scales(np.column_stack([c1, c2]), ("s1", "s2"))
m2 = vector_metric_scales(np.column_stack([c2, c1]), ("s2", "s1"))
check("масштаб per-series (перестановка колонок согласована)",
      m1["s1"]["mase_scale"] == m2["s1"]["mase_scale"]
      and m1["s2"]["mase_scale"] == m2["s2"]["mase_scale"]
      and m1["s1"]["mase_scale"] != m1["s2"]["mase_scale"])

phi = np.array([[0.9, 0.1], [0.0, 0.8]])
st = companion_stability([phi])
ev_eig = np.sort(np.abs(np.linalg.eigvals(phi)))
check("companion для VAR(1): max|lambda| == max|eig(PHI)|",
      np.allclose(sorted(st["eigenvalue_moduli"]), ev_eig, atol=1e-12)
      and st["is_stable"])
st_un = companion_stability([np.array([[1.05, 0.2], [0.0, 0.5]])])
check("взрывной VAR(1) неустойчив", not st_un["is_stable"])

res = compute_vector_metrics(
    np.array([[1.0, 100.0]]), np.array([[0.5, 100.0]]), ("s1", "s2"),
    mase_scales={"s1": 1.0, "s2": None},
)
check("all-or-none: mase s2 None -> scaled_loss None",
      res["per_series"]["s2"].mase is None and res["scaled_loss"] is None)
res2 = compute_vector_metrics(
    np.array([[1.0, 100.0]]), np.array([[0.5, 100.0]]), ("s1", "s2"),
    mase_scales={"s1": 1.0, "s2": 4.0},
)
check("полные scale -> агрегат mean(0.5, 0.0) = 0.25",
      res2["scaled_loss"] == pytest.approx(0.25))

print("== 4. Cohort contract: ключи совместимы со схемой build_backtest_plan ==")
from apps.api.backtesting import build_backtest_plan  # noqa: E402
from apps.api.multivariate_contract import build_endogenous_system  # noqa: E402

sysm = build_endogenous_system(
    {"gdp": list(np.linspace(1, 20, 20)), "infl": list(np.linspace(2, 21, 20))}
)
contract = multivariate_cohort_contract(
    sysm, series_fingerprints={"gdp": "fp1", "infl": "fp2"}
)
check("top-level ключи cohort: objective/series_fingerprints/feature_contract/metric_policy",
      set(contract) >= {"objective", "series_fingerprints", "feature_contract",
                        "metric_policy"})
check("objective == 'multivariate' (изоляция от level_forecast cohort'ов)",
      contract["objective"] == "multivariate")

print()
print(f"ИТОГО: ok={ok}, fail={fail}")
if fail:
    raise SystemExit(1)
