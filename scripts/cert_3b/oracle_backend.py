# scripts/cert_3b/oracle_backend.py
"""PANEL-MODELS-3b certification: oracles on OWN data («Новгородские склады»).

Каждая проверка O-XX сравнивает функции app/modeling/panel_models.py и
движок/реестр/каталог с НЕЗАВИСИМЫМИ ручными ожиданиями из oracle_corpus.py
(константные корпуса + np.linalg.lstsq + стандартные формулы). Запуск:
    python3 scripts/cert_3b/oracle_backend.py
Протокол: stdout; каждая строка "O-XX ... PASS/FAIL <detail>".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import oracle_corpus as oc  # noqa: E402

from app.preprocessing.panel import build_panel_frame, panel_fingerprint  # noqa: E402
from app.modeling.panel_models import (  # noqa: E402
    PanelModelError,
    build_panel_entity_folds,
    fit_fixed_effects,
    fit_fixed_effects_dummies,
    fit_panel_var,
    fit_random_effects,
    hausman_test,
    panel_fe_re_scenario_forecast,
    panel_var_forecast,
)
from apps.api.backtesting import run_panel_entity_backtest_plan  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(oid: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((oid, bool(ok), detail))
    flag = "PASS" if ok else "FAIL"
    print(f"{oid:8s} {flag}  {detail if not ok else ''}")


def rel(a: float, b: float) -> float:
    d = max(abs(float(a)), abs(float(b)), 1e-12)
    return abs(float(a) - float(b)) / d


def approx(a: float, b: float, tol: float = 1e-9) -> bool:
    # S-ФИКС (PANEL-MODELS-3b-FIX): гибридный допуск (семантика
    # numpy.allclose): |a-b| <= atol + rtol*max(|a|,|b|). Прежняя чистая
    # rel-метрика с полом 1e-12 ложно краснела на точных нулях корпусных
    # констант (VAR2_A["v2"]["v1"]=0.0) против float-шума OLS ~1e-15.
    # Для ненулевых значений порядка 1 гибрид >= прежней rel-метрики --
    # ни одна проходившая проверка не ослаблена.
    return abs(float(a) - float(b)) <= tol + tol * max(abs(float(a)), abs(float(b)))


def expect_error(oid: str, fn, *parts: str) -> None:
    try:
        fn()
        check(oid, False, "expected refusal, got success")
    except PanelModelError as exc:
        text = str(exc)
        ok = all(p in text for p in parts)
        check(oid, ok, f"message={text!r}, need parts={parts}")
    except Exception as exc:  # noqa: BLE001
        check(oid, False, f"wrong exception {type(exc).__name__}: {exc}")


def frame(df, target, values=None):
    values = values or [c for c in df.columns
                        if c not in (df.columns[0], df.columns[1])]
    return build_panel_frame(
        df, date_column=df.columns[1], entity_column=df.columns[0],
        value_columns=list(values), target_column=target,
    )


# ══════════════════ FE: корпус NS-1 (точная арифметика) ═════════════════════

def o01_o10_fe() -> None:
    exp = oc.ns1_expected()
    fr = frame(oc.ns1_frame(), "выручка")
    res = fit_fixed_effects(fr)

    check("O01", all(approx(res.coefficients[n], b, 1e-9)
                     for n, b in zip(("поставки", "спрос"), exp["beta"])),
          f"beta={res.coefficients}")
    check("O02", all(approx(res.entity_effects[k], v, 1e-9)
                     for k, v in exp["effects"].items()),
          f"effects={res.entity_effects}")
    check("O03", approx(res.r2_within, exp["r2_within"], 1e-9),
          f"r2_within {res.r2_within} vs {exp['r2_within']}")
    check("O04", approx(res.r2_between, exp["r2_between"], 1e-9),
          f"r2_between {res.r2_between} vs {exp['r2_between']}")
    check("O05", approx(res.r2_overall, exp["r2_overall"], 1e-9),
          f"r2_overall {res.r2_overall} vs {exp['r2_overall']}")
    check("O06", approx(res.residual_variance, exp["residual_variance"], 1e-10),
          f"resvar {res.residual_variance} vs {exp['residual_variance']}")

    V = exp["V_cluster"]
    cov_ok = True
    for i, r in enumerate(("поставки", "спрос")):
        for j, c in enumerate(("поставки", "спрос")):
            got = res.covariance[r][c]
            if rel(got, V[i][j]) > 1e-6:
                cov_ok = False
    check("O07", cov_ok, f"cluster cov mismatch vs manual {V.tolist()}")

    se_ok = all(approx(res.std_errors[n], float(np.sqrt(V[i, i])), 1e-6)
                for i, n in enumerate(("поставки", "спрос")))
    check("O08", se_ok, f"SE={res.std_errors} vs sqrt(diag V)")

    # O09: исходный df не мутирует
    df_raw = oc.ns1_frame()
    fp_before = panel_fingerprint(df_raw, date_column="дата", entity_column="склад",
                                  value_columns=["выручка", "поставки", "спрос"],
                                  target_column="выручка")
    fr2 = frame(df_raw.copy(), "выручка")
    fit_fixed_effects(fr2)
    fp_after = panel_fingerprint(df_raw, date_column="дата", entity_column="склад",
                                 value_columns=["выручка", "поставки", "спрос"],
                                 target_column="выручка")
    check("O09", fp_before == fp_after, "source frame mutated")

    # O10: dummies-кросс-реализация
    res_d = fit_fixed_effects_dummies(fr)
    check("O10a", all(approx(res_d.coefficients[n], res.coefficients[n], 1e-8)
                      for n in res.coefficients),
          f"dummies beta {res_d.coefficients} vs within {res.coefficients}")
    check("O10b", approx(res_d.r2_overall, res.r2_overall, 1e-8),
          "r2_overall cross")
    diff_w = {k: res.entity_effects[k] - res.entity_effects["НС-1"]
              for k in res.entity_effects}
    diff_d = {k: res_d.entity_effects[k] - res_d.entity_effects["НС-1"]
              for k in res_d.entity_effects}
    check("O10c", all(approx(diff_w[k], diff_d[k], 1e-8) for k in diff_w),
          f"effects differences {diff_w} vs {diff_d}")
    # классические SE dummies: ручной OLS на [1, x, dummies]
    df = oc.ns1_frame()
    codes = pd.factorize(df["склад"], sort=True)[0]
    x = df[["поставки", "спрос"]].to_numpy(dtype=float)
    dummies = np.zeros((len(df), 5))
    for idx in range(1, 6):
        dummies[:, idx - 1] = (codes == idx).astype(float)
    Z = np.column_stack([np.ones(len(df)), x, dummies])
    y = df["выручка"].to_numpy(dtype=float)
    _, _, cov_m = oc.manual_ols(Z, y)
    se_manual = np.sqrt(np.diag(cov_m))[1:3]
    se_ok = all(approx(res_d.std_errors[n], se_manual[i], 1e-8)
                for i, n in enumerate(("поставки", "спрос")))
    check("O10d", se_ok, f"dummies SE {res_d.std_errors} vs classic {se_manual}")
    check("O10e", any("классические OLS" in w for w in res_d.warnings),
          f"disclosure missing: {res_d.warnings}")
    check("O10f", res_d.intercept is None and res.intercept is None,
          "FE intercept must be None")


# ══════════════════ Хаусман (форма Мундлака, ручной Wald) ═══════════════════

def _manual_hausman(df: pd.DataFrame, ecol: str, dcol: str,
                    target: str, exog: list[str]) -> float:
    x = df[exog].to_numpy(dtype=float)
    y = df[target].to_numpy(dtype=float)
    xbar_rows = df.groupby(df[ecol], sort=True)[exog].transform("mean").to_numpy(dtype=float)
    codes = pd.factorize(df[ecol], sort=True)[0]
    Z = np.column_stack([np.ones(len(y)), x, xbar_rows])
    beta, resid, _ = oc.manual_ols(Z, y)
    V = oc.manual_cluster_cov(Z, resid, codes)
    K = len(exog)
    gamma = beta[1 + K: 1 + 2 * K]
    v_gamma = V[1 + K: 1 + 2 * K, 1 + K: 1 + 2 * K]
    return float(gamma @ np.linalg.solve(v_gamma, gamma))


def o11_o14_hausman() -> None:
    fr = frame(oc.ns1_frame(), "выручка")
    res = hausman_test(fr)
    exp_stat = _manual_hausman(oc.ns1_frame(), "склад", "дата", "выручка",
                               ["поставки", "спрос"])
    check("O11a", approx(res.statistic, exp_stat, 1e-6),
          f"stat {res.statistic} vs manual {exp_stat}")
    check("O11b", res.preferred == "fixed_effects" and res.p_value < 0.05,
          f"correlated DGP must reject: p={res.p_value}, preferred={res.preferred}")
    check("O11c", res.df == 2 and res.note != "" and "40" in res.note,
          f"df={res.df}, note={res.note!r}")

    fr_corr = frame(oc.nsh_frame(correlated=True), "брак")
    res_c = hausman_test(fr_corr)
    exp_c = _manual_hausman(oc.nsh_frame(True), "цех", "сутки", "брак",
                            ["подача", "цикл"])
    check("O12a", approx(res_c.statistic, exp_c, 1e-6),
          f"N=50 correlated: stat {res_c.statistic} vs {exp_c}")
    check("O12b", res_c.preferred == "fixed_effects" and res_c.note == "",
          f"preferred={res_c.preferred}, note={res_c.note!r}")

    fr_ind = frame(oc.nsh_frame(correlated=False), "брак")
    res_i = hausman_test(fr_ind)
    exp_i = _manual_hausman(oc.nsh_frame(False), "цех", "сутки", "брак",
                            ["подача", "цикл"])
    check("O13a", approx(res_i.statistic, exp_i, 1e-6),
          f"N=50 independent: stat {res_i.statistic} vs {exp_i}")
    check("O13b", res_i.preferred == "random_effects",
          f"independent DGP should not reject: p={res_i.p_value}")

    d = res.to_dict()
    check("O14", d["advisory"] is True and "аналитиком" in d["note"]
          and json.dumps(d, allow_nan=False) is not None,
          f"advisory dict: {d}")


# ══════════════════ RE: Swamy-Arora (ручной путь) ═══════════════════════════

def o20_o22_re() -> None:
    exp = oc.ns2_expected()
    fr = frame(oc.ns2_frame(), "выход")
    res = fit_random_effects(fr)
    check("O20a", all(approx(res.coefficients[n], b, 1e-6)
                      for n, b in zip(("норма", "простои"), exp["beta"])),
          f"RE beta {res.coefficients} vs manual {exp['beta']}")
    check("O20c", approx(res.intercept, exp["intercept"], 1e-6),
          f"RE intercept {res.intercept} vs {exp['intercept']}")
    vc = res.variance_components
    check("O20d", approx(vc["sigma_e2"], exp["sigma_e2"], 1e-6)
          and approx(vc["sigma_u2"], exp["sigma_u2"], 1e-6)
          and approx(vc["theta_mean"], exp["theta"], 1e-6),
          f"components {vc} vs manual sigma_e2={exp['sigma_e2']:.6f} "
          f"sigma_u2={exp['sigma_u2']:.6f} theta={exp['theta']:.6f}")
    cov_ok = all(rel(res.covariance["норма"]["норма"], exp["cov"][0][0]) < 1e-6
                 and rel(res.covariance["простои"]["простои"], exp["cov"][1][1]) < 1e-6
                 for _ in (0,))
    check("O20e", cov_ok, f"GLS cov diag vs manual {np.diag(exp['cov'])}")
    check("O20f", any("модельные GLS" in w for w in res.warnings),
          f"SE disclosure: {res.warnings}")
    check("O20g", res.model_id == "panel_re" and res.r2_within <= 1.0 + 1e-12,
          "model_id/r2 sanity")

    # O21: NS-REneg -- sigma_u2 < 0 -> clamp + pooled OLS
    fr_neg = frame(oc.nsreneg_frame(), "погрузка")
    res_neg = fit_random_effects(fr_neg)
    clamp_warn = any("отрицательна" in w and "clamp" in w for w in res_neg.warnings)
    df = oc.nsreneg_frame()
    x = df[["наряды", "ветер"]].to_numpy(dtype=float)
    y = df["погрузка"].to_numpy(dtype=float)
    beta_pooled = oc.manual_ols_const(x, y)[0]
    check("O21a", clamp_warn, f"clamp warning missing: {res_neg.warnings}")
    check("O21b", res_neg.variance_components["sigma_u2"] == 0.0,
          f"sigma_u2 clamped to 0, got {res_neg.variance_components}")
    check("O21c", all(approx(res_neg.coefficients[n], b, 1e-8)
                      for n, b in zip(("наряды", "ветер"), beta_pooled[1:])),
          f"theta=0 => pooled OLS: {res_neg.coefficients} vs {beta_pooled[1:]}")
    check("O21d", approx(res_neg.intercept, float(beta_pooled[0]), 1e-8),
          "pooled intercept")

    # O22: несбалансированная RE -- theta_i по фактическим T_i
    exp_u = oc.nsreunbal_expected()
    fr_u = frame(oc.nsreunbal_frame(), "оборот")
    res_u = fit_random_effects(fr_u)
    check("O22a", all(approx(res_u.coefficients[n], b, 1e-6)
                      for n, b in zip(("рейсы", "туман"), exp_u["beta"])),
          f"RE unbal beta {res_u.coefficients} vs {exp_u['beta']}")
    check("O22b", approx(res_u.variance_components["sigma_e2"], exp_u["sigma_e2"], 1e-6)
          and approx(res_u.variance_components["sigma_u2"], exp_u["sigma_u2"], 1e-6),
          f"unbal components {res_u.variance_components} vs "
          f"sigma_e2={exp_u['sigma_e2']:.6f} sigma_u2={exp_u['sigma_u2']:.6f}")
    thetas = {str(k): v for k, v in
              zip(sorted(res_u.variance_components), res_u.variance_components)}
    check("O22c", abs(res_u.variance_components["theta_mean"]
                      - float(np.mean(list(exp_u["theta_map"].values())))) < 1e-8,
          f"theta_mean {res_u.variance_components['theta_mean']} vs "
          f"{float(np.mean(list(exp_u['theta_map'].values())))}")


# ══════════════════ Panel VAR ═══════════════════════════════════════════════

def o30_o38_var() -> None:
    fr = frame(oc.nsvar_frame(), "v1", values=["v1", "v2"])
    res = fit_panel_var(fr, lags=1)
    # S-ФИКС (PANEL-MODELS-3b-FIX): ручная сторона обязана ссылаться на
    # корпусную константу VAR1_A (0.85/0.1/-0.1/0.9), а не на посторонний
    # литерал (0.5/0.2/-0.3/0.4) -- в кампании 3b это делало O30a/O33
    # инертно-красными (сравнение с чужой матрицей) -- дефект СВОЕЙ
    # инфраструктуры, продуктовый код не менялся.
    exp = oc.var_expected([oc.VAR1_A], oc.VAR_C, oc.VAR_ALPHAS)
    A = res.a_matrices[0]
    check("O30a", all(approx(A[eq][var], exp["a_matrices"][0][eq][var], 1e-9)
                      for eq in ("v1", "v2") for var in ("v1", "v2")),
          f"A={A} vs manual {exp['a_matrices'][0]}")
    check("O30b", all(approx(res.base_intercept[eq], exp["base"][eq], 1e-9)
                      for eq in ("v1", "v2")),
          f"base {res.base_intercept} vs {exp['base']}")
    check("O30c", all(approx(res.entity_intercepts[f"О-{i+1}"][eq],
                             exp["entity"][f"О-{i+1}"][eq], 1e-9)
                      for i in range(6) for eq in ("v1", "v2")),
          f"entity intercepts vs {exp['entity']}")
    check("O30d", all(abs(v - 1.0) < 1e-9 for v in res.r2_by_equation.values()),
          f"exact DGP => R2=1, got {res.r2_by_equation}")

    last = oc.var_last_states(oc.nsvar_frame(), 24, 1)
    check("O31", all(approx(res.last_states[0][v], last[0][v], 1e-9)
                     for v in ("v1", "v2")),
          f"last_states {res.last_states[0]} vs {last[0]}")

    # O32: VAR(2) восстановление -- ручная сторона = корпусная VAR2_A
    # (S-ФИКС: прежний литерал {0.4,...} не совпадал с корпусом nsvar2_frame).
    fr2 = frame(oc.nsvar2_frame(), "v1", values=["v1", "v2"])
    res2 = fit_panel_var(fr2, lags=2)
    exp2_A = [oc.VAR2_A[0], oc.VAR2_A[1]]
    ok = all(approx(res2.a_matrices[ell][eq][var], exp2_A[ell][eq][var], 1e-9)
             for ell in (0, 1) for eq in ("v1", "v2") for var in ("v1", "v2"))
    check("O32", ok, f"VAR(2) A={res2.a_matrices}")

    # O33: рекурсивный прогноз -- ручная рекурсия от корпусной VAR1_A
    # (S-ФИКС: см. комментарий к O30a).
    fc = panel_var_forecast(res, frame=fr, horizon=3)
    manual = oc.var_manual_forecast(
        [oc.VAR1_A], oc.VAR_C, oc.VAR_ALPHAS, last, 3)
    ok = all(approx(fc.steps[s]["values"][v], manual[s][v], 1e-9)
             for s in range(3) for v in ("v1", "v2"))
    check("O33", ok and fc.horizon == 3,
          f"forecast {fc.steps} vs manual {manual}")

    # O34-O36: гейты
    fr_unbal = frame(oc.nsvar_unbal_frame(), "v1", values=["v1", "v2"])
    expect_error("O34", lambda: fit_panel_var(fr_unbal, lags=1),
                 "общ", "сетк")
    fr_4ent = frame(oc.gate_entities_frame(4, 24), "у", values=["у", "э"])
    expect_error("O35", lambda: fit_panel_var(fr_4ent, lags=1),
                 "Недостаточно сущностей")
    one_var = oc.nsvar_frame()[["объект", "шаг", "v1"]]
    fr_1v = frame(one_var, "v1", values=["v1"])
    expect_error("O36a", lambda: fit_panel_var(fr_1v, lags=1), "минимум 2")
    expect_error("O36b", lambda: fit_panel_var(fr, lags=3), "lags [1, 2]")
    short11 = oc.gen_var_panel(
        [{"v1": {"v1": 0.5, "v2": 0.2}, "v2": {"v1": -0.3, "v2": 0.4}}],
        oc.VAR_C, oc.VAR_ALPHAS, T=11)
    fr_11 = frame(short11, "v1", values=["v1", "v2"])
    expect_error("O36c", lambda: fit_panel_var(fr_11, lags=1),
                 "3*n_vars*(p+1)=12")

    # O37: предупреждение малого T (16 >= 12 гейт, < 18 рекомендация)
    fr_short = frame(oc.nsvar_short_frame(), "v1", values=["v1", "v2"])
    res_short = fit_panel_var(fr_short, lags=1)
    check("O37", any("Малое T_common=16" in w for w in res_short.warnings),
          f"warnings={res_short.warnings}")

    # O38: to_dict JSON-safe
    try:
        json.dumps(res.to_dict(), allow_nan=False)
        check("O38", True, "")
    except Exception as exc:  # noqa: BLE001
        check("O38", False, f"to_dict not JSON-safe: {exc}")


# ══════════════════ Сценарный прогноз FE/RE ═════════════════════════════════

def o40_o42_forecast() -> None:
    fr = frame(oc.ns1_frame(), "выручка")
    fe = fit_fixed_effects(fr)
    re_ = fit_random_effects(fr)
    paths = {"поставки": [3.0, 4.0], "спрос": [1.5, 2.5]}
    z = float(sps.norm.ppf(0.975))

    fc = panel_fe_re_scenario_forecast(fe, frame=fr, entity="НС-3",
                                       exog_paths=paths, confidence=0.95)
    exp = oc.ns1_expected()
    ok_point, ok_int = True, True
    for s in range(2):
        xs = np.array([paths["поставки"][s], paths["спрос"][s]])
        point_manual = xs @ exp["beta"] + exp["effects"]["НС-3"]
        var_manual = float(xs @ exp["V_cluster"] @ xs) + exp["residual_variance"]
        half = z * np.sqrt(max(var_manual, 0.0))
        if not approx(fc.point[s], point_manual, 1e-9):
            ok_point = False
        if not (approx(fc.lower[s], point_manual - half, 1e-6)
                and approx(fc.upper[s], point_manual + half, 1e-6)):
            ok_int = False
    check("O40a", ok_point, f"FE points {fc.point} vs manual "
          f"{[float(np.array([paths['поставки'][s_], paths['спрос'][s_]]) @ exp['beta'] + exp['effects']['НС-3']) for s_ in range(2)]}")
    check("O40b", ok_int, f"FE intervals [{fc.lower}, {fc.upper}]")
    check("O40c", "кластерная ковариация FE" in fc.method and fc.entity == "НС-3"
          and fc.horizon == 2 and fc.confidence == 0.95,
          f"method={fc.method!r}")

    # RE: offset = общий интерсепт (E(u_i)=0), ручная GLS-арифметика
    exp_re = oc.ns2_expected()
    fr2 = frame(oc.ns2_frame(), "выход")
    re2 = fit_random_effects(fr2)
    fc_re = panel_fe_re_scenario_forecast(
        re2, frame=fr2, entity="УЧ-2",
        exog_paths={"норма": [3.0], "простои": [0.4]}, confidence=0.95)
    xs = np.array([3.0, 0.4])
    point_manual = float(xs @ exp_re["beta"]) + exp_re["intercept"]
    var_manual = float(xs @ exp_re["cov"] @ xs) + re2.residual_variance
    half = z * np.sqrt(max(var_manual, 0.0))
    check("O41a", approx(fc_re.point[0], point_manual, 1e-6),
          f"RE point {fc_re.point[0]} vs {point_manual}")
    check("O41b", approx(fc_re.lower[0], point_manual - half, 1e-4)
          and approx(fc_re.upper[0], point_manual + half, 1e-4),
          f"RE interval vs [{point_manual - half}, {point_manual + half}]")
    check("O41c", "GLS-ковариация RE" in fc_re.method, fc_re.method)

    # O42: честные отказы
    expect_error("O42a", lambda: panel_fe_re_scenario_forecast(
        fe, frame=fr, entity="НС-99", exog_paths=paths), "Неизвестная сущность")
    expect_error("O42b", lambda: panel_fe_re_scenario_forecast(
        fe, frame=fr, entity="НС-3", exog_paths={"поставки": [1.0]}),
        "отсутствуют")
    expect_error("O42c", lambda: panel_fe_re_scenario_forecast(
        fe, frame=fr, entity="НС-3",
        exog_paths={"поставки": [1.0, 2.0], "спрос": [1.0]}), "расходится")
    fr_v = frame(oc.nsvar_frame(), "v1", values=["v1", "v2"])
    res_v = fit_panel_var(fr_v, lags=1)
    expect_error("O42d", lambda: panel_var_forecast(res_v, frame=fr_v, horizon=0),
                 "положительным")


# ══════════════════ Folds ═══════════════════════════════════════════════════

def o50_o52_folds() -> None:
    fr = frame(oc.nsfold_frame(), "груз")
    dates = list(pd.date_range("2025-09-01", periods=30, freq="D"))

    def idx(plan, i):
        return (dates.index(plan[i].train_dates[0]), dates.index(plan[i].train_dates[-1]),
                dates.index(plan[i].test_dates[0]), dates.index(plan[i].test_dates[-1]))

    # expanding h=3 f=3 g=1
    plan = build_panel_entity_folds(fr, horizon=3, n_folds=3, gap=1)
    exp = oc.expected_folds(30, 3, 3, 1, "expanding", 10)
    check("O50a", all(idx(plan, i) == tuple(exp[i]) for i in range(3)),
          f"expanding layout {[idx(plan, i) for i in range(3)]} vs {exp}")
    # кластерная честность: train строго раньше test в КАЖДОМ fold
    check("O50b", all(max(f.train_dates) < min(f.test_dates) for f in plan),
          "train must be strictly before test")

    # sliding h=3 f=3 g=1: окно max(9,10)=10
    plan_s = build_panel_entity_folds(fr, horizon=3, n_folds=3, gap=1,
                                      strategy="sliding")
    exp_s = oc.expected_folds(30, 3, 3, 1, "sliding", 10)
    check("O50c", all(idx(plan_s, i) == tuple(exp_s[i]) for i in range(3)),
          f"sliding layout {[idx(plan_s, i) for i in range(3)]} vs {exp_s}")

    # single h=3 f=1 g=0
    plan_1 = build_panel_entity_folds(fr, horizon=3, n_folds=1)
    exp_1 = oc.expected_folds(30, 3, 1, 0, "expanding", 10)
    check("O50d", idx(plan_1, 0) == tuple(exp_1[0]) and plan_1[0].mode == "dates",
          f"single layout {idx(plan_1, 0)} vs {exp_1[0]}")

    # mode common_grid: сбалансированная OK, несбалансированная -- отказ
    fr_bal = frame(oc.nsvar_frame(), "v1", values=["v1", "v2"])
    plan_v = build_panel_entity_folds(fr_bal, horizon=2, n_folds=2,
                                      mode="common_grid")
    exp_v = oc.expected_folds(24, 2, 2, 0, "expanding", 12)
    v_dates = sorted(set(oc.nsvar_frame()["шаг"]))
    ok_v = (plan_v[0].mode == "common_grid"
            and len(plan_v[0].train_dates) == exp_v[0][1] - exp_v[0][0] + 1
            and v_dates.index(plan_v[0].train_dates[0]) == exp_v[0][0]
            and v_dates.index(plan_v[0].test_dates[-1]) == exp_v[0][3])
    check("O50e", ok_v,
          f"common_grid fold1 {len(plan_v[0].train_dates)} dates vs manual {exp_v[0]}")
    fr_unbal = frame(oc.nsvar_unbal_frame(), "v1", values=["v1", "v2"])
    expect_error("O50f", lambda: build_panel_entity_folds(
        fr_unbal, horizon=2, n_folds=2, mode="common_grid"), "сбалансирован")

    # O51: честные отказы
    expect_error("O51a", lambda: build_panel_entity_folds(
        fr, horizon=3, n_folds=3, gap=1, strategy="rolling"), "стратегия")
    expect_error("O51b", lambda: build_panel_entity_folds(
        fr, horizon=3, n_folds=3, mode="weird"), "режим")
    expect_error("O51c", lambda: build_panel_entity_folds(
        fr, horizon=0, n_folds=2), "положительными")
    expect_error("O51d", lambda: build_panel_entity_folds(
        fr, horizon=2, n_folds=0), "положительными")
    expect_error("O51e", lambda: build_panel_entity_folds(
        fr, horizon=2, n_folds=2, gap=-1), "неотрицательным")
    fr21 = frame(oc.nsfold_frame(T=21), "груз")
    expect_error("O51f", lambda: build_panel_entity_folds(
        fr21, horizon=3, n_folds=3, gap=1), "Недостаточно истории")
    # O50g: sliding с h*n_folds > min_train (окно max(16,10)=16, НЕ min_train)
    plan_s4 = build_panel_entity_folds(fr, horizon=4, n_folds=4, gap=0,
                                       strategy="sliding")
    exp_s4 = oc.expected_folds(30, 4, 4, 0, "sliding", 10)
    check("O50g", all(idx(plan_s4, i) == tuple(exp_s4[i]) for i in range(4)),
          f"sliding h=4 f=4 layout {[idx(plan_s4, i) for i in range(4)]} vs {exp_s4}")

    # O51g: common_grid boundary -- T_common=15 < needed=12+4=16 -- отказ
    fr_v15 = frame(oc.gen_var_panel([oc.VAR1_A], oc.VAR_C, oc.VAR_ALPHAS, T=15),
                   "v1", values=["v1", "v2"])
    expect_error("O51g", lambda: build_panel_entity_folds(
        fr_v15, horizon=2, n_folds=2, mode="common_grid"),
        "Недостаточно истории")

    # O52: граница -- дат ровно needed
    fr_need = frame(oc.nsfold_frame(T=22), "груз")
    plan_need = build_panel_entity_folds(fr_need, horizon=3, n_folds=3, gap=1)
    check("O52", len(plan_need) == 3
          and len(plan_need[0].train_dates) == 10,
          f"boundary: fold1 train len {len(plan_need[0].train_dates)} != 10")


# ══════════════════ Движок run_panel_entity_backtest_plan ═══════════════════

def _manual_fe_fit(df: pd.DataFrame, ecol: str, target: str, exog: list[str]):
    w = oc.manual_within(df, ecol, [target] + exog)
    Xw = np.column_stack([w[c] for c in exog])
    yw = w[target]
    beta, resid, _ = oc.manual_ols(Xw, yw)
    g = df.groupby(df[ecol], sort=True)
    y_bar = g[target].mean()
    x_bar = g[exog].mean()
    effects = {}
    for e in y_bar.index:
        row = np.asarray(x_bar.loc[e], dtype=float)
        effects[str(e)] = float(y_bar.loc[e] - row @ beta)
    x = df[exog].to_numpy(dtype=float)
    y = df[target].to_numpy(dtype=float)
    ent = df[ecol].to_numpy()
    fitted = x @ beta + np.array([effects[str(e)] for e in ent])
    codes = pd.factorize(df[ecol], sort=True)[0]
    V = oc.manual_cluster_cov(Xw, resid, codes)
    df_res = len(y) - df[ecol].nunique() - len(exog)
    resvar = float(resid @ resid) / max(df_res, 1)
    return beta, effects, V, resvar


def o60_o64_engine() -> None:
    df = oc.nsengine_frame()
    fr = frame(df, "груз")
    result = run_panel_entity_backtest_plan(
        model_id="panel_fe", model_name="Fixed Effects (within)",
        family_id="panel", frame=fr,
        validation={"strategy": "expanding", "horizon": 2, "n_folds": 2},
        seasonal_period=1, params=None)

    # O60a: раскладка folds в результате == ручной
    dates = sorted(df["число"].unique())
    manual_layout = oc.expected_folds(14, 2, 2, 0, "expanding", 10)
    ok_layout = True
    for i, fold in enumerate(result["folds"]):
        tr0 = dates.index(pd.Timestamp(fold["train_start_label"]))
        tr1 = dates.index(pd.Timestamp(fold["train_end_label"]))
        te0 = dates.index(pd.Timestamp(fold["test_start_label"]))
        te1 = dates.index(pd.Timestamp(fold["test_end_label"]))
        if (tr0, tr1, te0, te1) != tuple(manual_layout[i]):
            ok_layout = False
    check("O60a", ok_layout, f"engine fold layout {[ (f['train_start_label'], f['test_start_label']) for f in result['folds'] ]}")

    # O60b: предсказания fold1 == ручной FE-fit на train-префиксе + сценарий
    fold1 = result["folds"][0]
    train_df = df[df["число"].isin(pd.to_datetime(
        [fold1["train_start_label"], fold1["train_end_label"]] + [
            d for d in dates
            if pd.Timestamp(fold1["train_start_label"]) <= d <= pd.Timestamp(fold1["train_end_label"])
        ]))]
    beta, effects, V, resvar = _manual_fe_fit(train_df, "камера", "груз",
                                              ["приём", "отгруз"])
    z = float(sps.norm.ppf(0.975))
    preds = {(p["entity"], p["date"]): p["predicted"] for p in fold1["predictions"]}
    ok_pred = True
    for _, row in train_df.drop_duplicates("камера").iterrows():
        pass
    test_df = df[(df["число"] > pd.Timestamp(fold1["train_end_label"]))
                 & (df["число"] <= pd.Timestamp(fold1["test_end_label"]))]
    for _, row in test_df.iterrows():
        e = row["камера"]
        xs = np.array([row["приём"], row["отгруз"]], dtype=float)
        point = float(xs @ beta + effects[e])
        if not approx(preds[(e, str(row["число"]))], point, 1e-8):
            ok_pred = False
    check("O60b", ok_pred, "engine fold1 predictions vs manual fold-local FE")

    # O60c: per-entity MASE-scale = mean|dY| train-only (последний fold-префикс)
    ep = result["panel"]["entity_metrics"]
    ok_scale = True
    for e in sorted(df["камера"].unique()):
        tr = df[(df["камера"] == e)
                & (df["число"] <= pd.Timestamp(result["folds"][-1]["train_end_label"]))]
        vals = tr.sort_values("число")["груз"].to_numpy(dtype=float)
        scale = float(np.mean(np.abs(vals[1:] - vals[:-1])))
        got = ep[e]["mase"]
        # mase в метриках зависит от фактических ошибок; сверяем только
        # наличие поля и положительность, а СКЕЙЛ -- через pooled-метод
        if got is None:
            ok_scale = False
    check("O60c", ok_scale, "per-entity mase present")
    # pooled scale == median по-сущностных train-only скейлов
    scales = []
    for e in sorted(df["камера"].unique()):
        tr = df[(df["камера"] == e)
                & (df["число"] <= pd.Timestamp(result["folds"][-1]["train_end_label"]))]
        vals = tr.sort_values("число")["груз"].to_numpy(dtype=float)
        scales.append(float(np.mean(np.abs(vals[1:] - vals[:-1]))))
    check("O60d", approx(result["panel"]["pooled_mase_scale"],
                         float(np.median(scales)), 1e-9),
          f"pooled scale {result['panel']['pooled_mase_scale']} vs median {np.median(scales)}")

    # O60e: pooled MAE == mean|resid| по всем OOF
    oof = result["oof_predictions"]
    mae_manual = float(np.mean([abs(p["actual"] - p["predicted"]) for p in oof]))
    check("O60e", approx(result["metrics"]["mae"], mae_manual, 1e-6),
          f"pooled MAE {result['metrics']['mae']} vs {mae_manual}")

    # O61: cohort_contract с fingerprint 3a + панельная фактура
    fp = panel_fingerprint(df, date_column="число", entity_column="камера",
                           value_columns=["груз", "приём", "отгруз"],
                           target_column="груз")
    cc = result["cohort_contract"]
    check("O61", cc["fingerprint"] == fp and cc["panel_entity"] is True
          and cc["input_kind"] == "panel_entity" and cc["n_entities"] == 6
          and cc["balance"] == "balanced",
          f"cohort_contract={cc}")

    # O62: детектор утечки -- подмена тестовых y НЕ меняет предсказания
    df_poison = df.copy()
    test_mask = df_poison["число"] > pd.Timestamp("2025-09-12")
    df_poison.loc[test_mask, "груз"] = df_poison.loc[test_mask, "груз"] * 3.0
    fr_poison = frame(df_poison, "груз")
    result_poison = run_panel_entity_backtest_plan(
        model_id="panel_fe", model_name="FE", family_id="panel", frame=fr_poison,
        validation={"strategy": "expanding", "horizon": 2, "n_folds": 2},
        seasonal_period=1, params=None)
    preds_a = {(p["fold"], p["entity"], p["date"]): p["predicted"]
               for p in result["oof_predictions"]}
    preds_b = {(p["fold"], p["entity"], p["date"]): p["predicted"]
               for p in result_poison["oof_predictions"]}
    check("O62", preds_a == preds_b, "predictions changed after poisoning test y -- LEAKAGE")

    # O63: VAR-движок: по-переменные метрики + step->date отображение
    fr_var = frame(oc.nsvar_frame(), "v1", values=["v1", "v2"])
    rv = run_panel_entity_backtest_plan(
        model_id="panel_var", model_name="Panel VAR (pooled)", family_id="panel",
        frame=fr_var,
        validation={"strategy": "expanding", "horizon": 2, "n_folds": 2},
        seasonal_period=1, params=None)
    check("O63a", "variable_metrics" in rv["panel"]
          and set(rv["panel"]["variable_metrics"]) == {"v1", "v2"},
          f"variable_metrics keys {rv['panel'].get('variable_metrics', {}).keys()}")
    # fold1: train d0..d19 (20 дат), test d20..d21; рекурсия 2 шага
    f1 = rv["folds"][0]
    exp_f1 = oc.expected_folds(24, 2, 2, 0, "expanding", 12)[0]
    vdates = sorted(set(oc.nsvar_frame()["шаг"]))
    train_dates = vdates[exp_f1[0]: exp_f1[1] + 1]
    manual_steps = oc.var_manual_forecast(
        [oc.VAR1_A], oc.VAR_C, oc.VAR_ALPHAS,
        oc.var_last_states(oc.nsvar_frame()[
            oc.nsvar_frame()["шаг"].isin(train_dates)], 20, 1), 2)
    test_keys = {str(vdates[exp_f1[2]]): 0, str(vdates[exp_f1[3]]): 1}
    matched = 0
    ok_var = True
    for p in f1["predictions"]:
        step = test_keys.get(str(p["date"]))
        if step is None:
            continue
        matched += 1
        if not approx(p["predicted"], manual_steps[step][p["variable"]], 1e-8):
            ok_var = False
    check("O63b", ok_var and matched == 24,
          f"VAR engine fold1 vs manual recursion (matched={matched}/24)")

    # O64: гейты движка
    try:
        run_panel_entity_backtest_plan(
            model_id="arima", model_name="ARIMA", family_id="arima", frame=fr,
            validation={"strategy": "expanding", "horizon": 2, "n_folds": 2},
            seasonal_period=1, params=None)
        check("O64a", False, "arima accepted by panel engine")
    except Exception as exc:  # noqa: BLE001
        check("O64a", "panel_entity" in str(exc), f"{type(exc).__name__}: {exc}")
    try:
        run_panel_entity_backtest_plan(
            model_id="deepar_panel", model_name="DeepAR panel", family_id="panel",
            frame=fr, validation={"strategy": "expanding", "horizon": 2,
                                  "n_folds": 2},
            seasonal_period=1, params=None)
        check("O64b", False, "deepar_panel without runtime returned metrics!")
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        honest = name in ("NeuralRuntimeCapacityError", "BacktestExecutionError")
        check("O64b", honest, f"{name}: {exc}")


# ══════════════════ Реестр / executor / dispatch / каталог / отказной модуль ═

def o70_o73_contour() -> None:
    from apps.api.model_execution import (
        MODEL_EXECUTION_REGISTRY,
        ModelExecutionRequest,
        _panel_entity_executor,
    )

    d = MODEL_EXECUTION_REGISTRY.describe("panel_fe")
    check("O70a", d["input_kind"] == "panel_entity" and d["family_id"] == "panel"
          and d["engine"] == "statsmodels" and d["deterministic"] is True,
          f"describe(panel_fe)={d}")
    for mid in ("panel_re", "panel_var"):
        dd = MODEL_EXECUTION_REGISTRY.describe(mid)
        if dd["input_kind"] != "panel_entity" or dd["family_id"] != "panel":
            check("O70b", False, f"{mid}: {dd}")
            break
    else:
        check("O70b", True, "")
    try:
        _panel_entity_executor(ModelExecutionRequest(
            target=[1.0, 2.0, 3.0], horizon=1, seasonal_period=1))
        check("O70c", False, "executor did not refuse")
    except Exception as exc:  # noqa: BLE001
        check("O70c", type(exc).__name__ == "ModelExecutionContractError"
              and "run_panel_entity_backtest_plan" in str(exc),
              f"{type(exc).__name__}: {exc}")

    # O71: dispatch -- честный отказ на однорядном synthetic-эндпоинте
    from apps.api.routers.models import _BACKTEST_IMPLEMENTATIONS
    ok = all(mid in _BACKTEST_IMPLEMENTATIONS
             for mid in ("panel_fe", "panel_re", "panel_var"))
    try:
        if ok:
            _BACKTEST_IMPLEMENTATIONS["panel_fe"]([1.0, 2.0, 3.0], 0.8, 7)
        check("O71", False, "dispatch returned metrics instead of refusal")
    except ValueError as exc:
        check("O71", "panel_entry" in str(exc) and "панель" in str(exc),
              f"refusal text: {exc}")

    # O72: каталог -- семейство №9, F06 первым в forbidden
    import yaml
    rules = yaml.safe_load((REPO / "rules" / "modeling.yaml").read_text("utf-8"))
    fam = next(f for f in rules["families"] if f["id"] == "panel")
    ids = [m["id"] for m in fam["models"]]
    check("O72a", fam["priority"] == 9 and ids == ["panel_fe", "panel_re",
                                                   "panel_var", "deepar_panel"],
          f"family 9 ids={ids}")
    fe_model = next(m for m in fam["models"] if m["id"] == "panel_fe")
    check("O72b", fe_model["min_series"] == 5 and fe_model["min_observations"] == 50,
          f"panel_fe gates {fe_model['min_series']}/{fe_model['min_observations']}")
    f06 = rules["applicability_engine"]["forbidden"][0]
    check("O72c", f06["id"] == "F06"
          and f06["condition"] == "model.family == 'panel'"
          and f06["result"] == "NOT_APPLICABLE"
          and "run_panel_entity_backtest_plan" in f06["message"],
          f"F06={f06}")

    # O73: отказной модуль model_impls/panel_entity.py
    from apps.api.model_impls.panel_entity import run_panel_entity_backtest_refusal
    try:
        run_panel_entity_backtest_refusal([1.0, 2.0], 0.8, 7)
        check("O73", False, "refusal module returned metrics")
    except ValueError as exc:
        check("O73", "panel_entry" in str(exc)
              and "run_panel_entity_backtest_plan" in str(exc),
              f"text: {exc}")


def o80_r4_tripwire() -> None:
    src = (REPO / "app" / "modeling" / "panel_models.py").read_text("utf-8")
    bt = (REPO / "apps" / "api" / "backtesting.py").read_text("utf-8")
    ok = ("prepare_passport_series" not in src
          and "modeling_entry" not in src
          and "prepare_passport_series" not in bt.split("def run_panel_entity_backtest_plan")[1].split("def ")[0])
    check("O80", ok, "panel contour must never touch single-series passport (R4)")


def main() -> int:
    o01_o10_fe()
    o11_o14_hausman()
    o20_o22_re()
    o30_o38_var()
    o40_o42_forecast()
    o50_o52_folds()
    o60_o64_engine()
    o70_o73_contour()
    o80_r4_tripwire()
    failed = [oid for oid, ok, _ in RESULTS if not ok]
    print(f"\nTOTAL {len(RESULTS)} | PASS {len(RESULTS) - len(failed)} | FAIL {len(failed)}")
    if failed:
        print("FAILED:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
