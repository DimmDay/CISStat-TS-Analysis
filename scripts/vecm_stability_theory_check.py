# Теоретическая сверка vecm_stability: сколько единичных корней должно быть
# в companion уровневого VAR-представления VECM?
# Теория (Lütkepohl 2005, гл. 6): для I(1)-системы размерности K с рангом r
# companion имеет РОВНО K - r единичных корней (число общих стохастических
# трендов), остальные строго внутри круга.  Экстремумы: r=0 -> K корней;
# r=K (стационарные уровни) -> 0 корней.
from __future__ import annotations

import numpy as np
from statsmodels.tsa.vector_ar.vecm import VECM, coint_johansen, select_coint_rank

def companion_unit_roots(var_rep, tol=1e-8):
    k = var_rep[0].shape[0]
    p = len(var_rep)
    comp = np.zeros((p * k, p * k))
    comp[:k, :] = np.hstack([np.asarray(b) for b in var_rep])
    if p > 1:
        comp[k:, :-k] = np.eye((p - 1) * k)
    eig = np.linalg.eigvals(comp)
    return eig, sum(1 for m in np.abs(eig) if abs(m - 1.0) <= tol)

print("=== Случай 1: K=3, истинный ранг 1 (y2=y1+eps; y3 = своя блуждание) ===")
rng = np.random.default_rng(777)
n = 300
y1 = 50.0 + np.cumsum(rng.normal(0, 1.2, n))
y2 = y1 + rng.normal(0, 0.4, n)
y3 = 30.0 + np.cumsum(rng.normal(0, 0.9, n))  # независимый тренд
M = np.column_stack([y1, y2, y3])
jh = coint_johansen(M, det_order=0, k_ar_diff=1)
print("trace lr1:", np.round(jh.lr1, 2))
print("crit 90/95/99:\n", np.round(jh.cvt, 2))
rank = select_coint_rank(M, det_order=0, k_ar_diff=1, method="trace", signif=0.05).rank
print("select_coint_rank:", rank)
fit = VECM(M, k_ar_diff=1, coint_rank=rank, deterministic="ci").fit()
eig, n_unit = companion_unit_roots(fit.var_rep)
print(f"|eig| (топ-6): {sorted(np.round(np.abs(eig), 6), reverse=True)[:6]}")
print(f"единичных корней в companion: {n_unit};  K - r = {3 - rank};  r = {rank}")
print(f"Правило коллеги (n_unit == r): {n_unit == rank};  Правило теории (n_unit == K - r): {n_unit == 3 - rank}")

print()
print("=== Случай 2: K=3, ранг 2 (две коинтегрированные пары + общая база) ===")
rng = np.random.default_rng(4242)
z = 10.0 + np.cumsum(rng.normal(0, 1.0, n))          # единственный общий тренд
a = z + rng.normal(0, 0.3, n)                         # a - z стационарен
b = 2 * z + rng.normal(0, 0.3, n)                     # b - 2z стационарен
M2 = np.column_stack([z, a, b])
rank2 = select_coint_rank(M2, det_order=0, k_ar_diff=1, method="trace", signif=0.05).rank
fit2 = VECM(M2, k_ar_diff=1, coint_rank=rank2, deterministic="ci").fit()
eig2, n_unit2 = companion_unit_roots(fit2.var_rep)
print("rank:", rank2, "| единичных корней:", n_unit2, "| K - r =", 3 - rank2)
print(f"Правило коллеги: {n_unit2 == rank2};  теория: {n_unit2 == 3 - rank2}")

print()
print("=== Случай 3: K=2, ранг 1 (классика — совпадение обоих правил) ===")
rng = np.random.default_rng(13)
w = 100.0 + np.cumsum(rng.normal(0, 1.0, n))
v = w + rng.normal(0, 0.5, n)
M3 = np.column_stack([w, v])
rank3 = select_coint_rank(M3, det_order=0, k_ar_diff=1, method="trace", signif=0.05).rank
fit3 = VECM(M3, k_ar_diff=1, coint_rank=rank3, deterministic="ci").fit()
eig3, n_unit3 = companion_unit_roots(fit3.var_rep)
print("rank:", rank3, "| единичных корней:", n_unit3, "| K - r =", 2 - rank3)
print(f"Правило коллеги: {n_unit3 == rank3};  теория: {n_unit3 == 2 - rank3}")

print()
print("=== Случай 4: ranks 0 и K (границы) ===")
w1 = 100.0 + np.cumsum(rng.normal(0, 1.0, n))
w2 = 50.0 + np.cumsum(rng.normal(0, 1.0, n))
rank0 = select_coint_rank(np.column_stack([w1, w2]), det_order=0, k_ar_diff=1,
                          method="trace", signif=0.05).rank
print("независимые блуждания -> ранг:", rank0, "(ожидался 0; VECM движком отклоняется)")
stat = np.column_stack([rng.normal(0, 1, n), rng.normal(0, 1, n)])
from statsmodels.tsa.vector_ar.var_model import VAR
fit_stat = VAR(stat).fit(maxlags=1, trend="c")
print("стационарная VAR(1) K=2: is_stable =", fit_stat.is_stable(verbose=False),
      "-> если трактовать как VECM r=K=2, теория даёт 0 единичных корней")
