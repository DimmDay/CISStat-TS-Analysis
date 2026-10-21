# scripts/cert_3b/oracle_corpus.py
"""PANEL-MODELS-3b certification: OWN oracle corpora + INDEPENDENT math.

Corpus family «Новгородские склады» (NS) -- дизъюнктно от repo DGP-фикстур
(test_panel_models/test_panel_execution) и от 3a-корпуса «Уральские цеха»
(scripts/cert_3a/oracle_backend.py).

ПРИНЦИП НЕЗАВИСИМОСТИ: все ожидаемые величины (beta, theta, sigma^2,
Wald, V_cluster, рекурсии VAR, раскладка folds) вычисляются ЗДЕСЬ
вручную из констант корпуса (np.linalg.lstsq + стандартные формулы) --
функции app/modeling/panel_models.py НЕ вызываются для ожиданий, только
ДЛЯ СРАВНЕНИЯ в oracle_backend.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats as sps

# ── ручные примитивы (независимые реализации) ───────────────────────────────

def manual_ols(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """OLS без константы: beta, residuals, cov_classic = s2 (X'X)^-1."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, k = X.shape
    ss = float(resid @ resid)
    s2 = ss / max(n - k, 1)
    xtx_inv = np.linalg.pinv(X.T @ X)
    return beta, resid, s2 * xtx_inv


def manual_ols_const(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """OLS с константой: [const, beta], resid, cov, R2 (центрированный)."""
    Z = np.column_stack([np.ones(len(y)), X])
    beta, resid, cov = manual_ols(Z, y)
    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return beta, resid, cov, r2


def manual_cluster_cov(X: np.ndarray, u: np.ndarray, groups: np.ndarray) -> np.ndarray:
    """Кластерно-робастная V (формула statsmodels, use_correction=True):
    B = sum_g X_g' u_g u_g' X_g; V = (X'X)^-1 B (X'X)^-1 * G/(G-1) * (n-1)/(n-K)."""
    xtx_inv = np.linalg.pinv(X.T @ X)
    g_ids = np.unique(groups)
    G = len(g_ids)
    n, K = X.shape
    B = np.zeros((K, K))
    for g in g_ids:
        m = groups == g
        xg, ug = X[m], u[m]
        s = xg.T @ ug
        B += np.outer(s, s)
    corr = (G / (G - 1.0)) * ((n - 1.0) / (n - K))
    return xtx_inv @ B @ xtx_inv * corr


def manual_within(data: pd.DataFrame, entity_column: str, cols: list[str]) -> dict[str, np.ndarray]:
    return {
        c: (data[c].to_numpy(dtype=float)
            - data.groupby(data[entity_column], sort=True)[c]
              .transform("mean").to_numpy(dtype=float))
        for c in cols
    }

# ── корпус NS-1: FE-восстановление (6 x 12, K=2, точная арифметика) ─────────

NS1_BETA = (1.5, -0.75)
NS1_ALPHAS = [10.0 * (i + 1) for i in range(6)]          # 10..60
NS1_R = [1.0, -1.0, 0.5, -0.5]                            # t%4, сумма за 4 = 0


def ns1_frame() -> pd.DataFrame:
    raw = []
    dates = list(pd.date_range("2025-03-01", periods=12, freq="D"))
    for i in range(6):
        m = 0.05 * (((i * 3) % 4) - 1.5)      # между-сущностной шум среднего
        for t in range(12):
            x1 = 2.0 + 0.1 * t + 0.05 * i
            x2 = 1.0 + ((t + i) % 5) * 0.2 + 0.05 * (i % 2)
            r = NS1_R[t % 4]
            y = NS1_ALPHAS[i] + m + NS1_BETA[0] * x1 + NS1_BETA[1] * x2 + r
            raw.append((f"НС-{i+1}", dates[t], x1, x2, r, y))
    # r ортогонален within-[x1, x2] ПО ПОСТРОЕНИЮ: истинный beta точно восстановим
    df = pd.DataFrame(raw, columns=["e", "d", "x1", "x2", "r", "y"])
    w = manual_within(df, "e", ["x1", "x2"])
    Xw = np.column_stack([w["x1"], w["x2"]])
    c, *_ = np.linalg.lstsq(Xw, df["r"].to_numpy(dtype=float), rcond=None)
    df["r"] = df["r"].to_numpy(dtype=float) - Xw @ c
    df["y"] = df["y"].to_numpy(dtype=float) - Xw @ c
    return pd.DataFrame({"склад": df["e"], "дата": df["d"],
                         "выручка": df["y"], "поставки": df["x1"],
                         "спрос": df["x2"]})


def ns1_expected():
    """Ручные ожидания NS-1 (полностью из констант корпуса)."""
    df = ns1_frame()
    w = manual_within(df, "склад", ["выручка", "поставки", "спрос"])
    Xw = np.column_stack([w["поставки"], w["спрос"]])
    yw = w["выручка"]
    beta_w, resid_w, _ = manual_ols(Xw, yw)               # == (1.5, -0.75)
    ss_res_w = float(resid_w @ resid_w)                    # = 72 * 0.625 = 45
    ss_tot_w = float(yw @ yw)
    r2_within = 1.0 - ss_res_w / ss_tot_w
    # между-регрессия средних
    g = df.groupby("склад", sort=True)
    y_bar = g["выручка"].mean().to_numpy()
    x_bar = g[["поставки", "спрос"]].mean().to_numpy()
    _, resid_b, _, r2_between = manual_ols_const(x_bar, y_bar)
    # полная модель: fitted = x*beta + alpha_i; остатки = r (нулевые средние по сущностям)
    x = df[["поставки", "спрос"]].to_numpy(dtype=float)
    y = df["выручка"].to_numpy(dtype=float)
    ent = df["склад"].to_numpy()
    alpha_map = {f"НС-{i+1}": NS1_ALPHAS[i] + 0.05 * (((i * 3) % 4) - 1.5)
                 for i in range(6)}
    fitted = x @ np.array(NS1_BETA) + np.array([alpha_map[e] for e in ent])
    resid_full = y - fitted                                # == r_it
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2_overall = 1.0 - float(resid_full @ resid_full) / ss_tot
    df_res = 72 - 6 - 2
    residual_variance = ss_res_w / df_res
    # кластерная V: внутри-дизайн, внутри-остатки = r_w == r (уже центрированы)
    codes = pd.factorize(df["склад"], sort=True)[0]
    V_cluster = manual_cluster_cov(Xw, resid_w, codes)
    return {
        "beta": np.array(NS1_BETA), "effects": alpha_map,
        "r2_within": r2_within, "r2_between": r2_between,
        "r2_overall": r2_overall, "residual_variance": residual_variance,
        "V_cluster": V_cluster, "ss_res_w": ss_res_w,
        "fitted_full": fitted, "resid_full": resid_full,
    }

# ── корпус NS-H: Хаусман, N=50 x T=15 (две версии DGP) ──────────────────────

NSH_R = [1.0, -1.0, 0.5, -0.5, 0.0]                       # t%5
NSH_ALPHA_SIGN = [+1, -1, +1, -1, -1, +1, -1, +1, +1, -1, +1, -1, -1, +1, -1,
                  +1, +1, -1, -1, +1, -1, +1, -1, +1, +1, -1, +1, -1, -1, +1,
                  -1, +1, +1, -1, +1, -1, -1, +1, -1, +1, +1, -1, +1, -1, -1,
                  +1, -1, +1, +1, -1]                     # 50 знаков, фикс.


def nsh_frame(correlated: bool) -> pd.DataFrame:
    rows = []
    dates = list(pd.date_range("2025-06-01", periods=15, freq="D"))
    # x̄1_i = 2 + 0.1*t̄ + 0.02*i = 3.4 + 0.02*i (растёт по i)
    x1_mean_i = np.array([3.4 + 0.02 * i for i in range(50)])
    if correlated:
        alphas = [3.0 * float(v - x1_mean_i.mean()) for v in x1_mean_i]
    else:
        alphas = [3.0 * float(NSH_ALPHA_SIGN[i]) for i in range(50)]
    for i in range(50):
        for t in range(15):
            x1 = 2.0 + 0.1 * t + 0.02 * i
            x2 = ((t + i) % 5) * 0.2 + 0.05 * (i % 2)
            r = NSH_R[t % 5] + 0.1 * (((i * 7) % 5) - 2)
            y = alphas[i] + 0.8 * x1 - 0.4 * x2 + r
            rows.append({"цех": f"З-{i:02d}", "сутки": dates[t],
                         "брак": y, "подача": x1, "цикл": x2})
    return pd.DataFrame(rows)

# ── корпус NS-2: RE-компоненты (10 x 14, альфа независима от x̄) ─────────────

NS2_R = [2.0, -2.0, 1.0, -1.0, 0.5, -0.5, 0.25, -0.25, 0.75, -0.75, 0.1, -0.1, 0.0, 0.0]


def ns2_frame() -> pd.DataFrame:
    rows = []
    dates = list(pd.date_range("2025-04-01", periods=14, freq="D"))
    for i in range(10):
        alpha = 1.0 if (i * 7) % 10 < 5 else -1.0          # декоррелировано с фазой
        for t in range(14):
            x1 = 2.0 + 0.1 * t + 0.04 * i
            x2 = ((t + i) % 5) * 0.2 + 0.05 * (i % 2)
            r = NS2_R[t]
            y = alpha + 1.2 * x1 - 0.6 * x2 + r
            rows.append({"участок": f"УЧ-{i+1}", "смена": dates[t],
                         "выход": y, "норма": x1, "простои": x2})
    return pd.DataFrame(rows)


def ns2_expected():
    """Ручной Swamy-Arora путь для NS-2 (сбалансированная, T_i = 14)."""
    df = ns2_frame()
    w = manual_within(df, "участок", ["выход", "норма", "простои"])
    Xw = np.column_stack([w["норма"], w["простои"]])
    yw = w["выход"]
    beta_w, resid_w, _ = manual_ols(Xw, yw)
    N, T, K = 10, 14, 2
    sigma_e2 = float(resid_w @ resid_w) / (N * T - N - K)
    g = df.groupby("участок", sort=True)
    y_bar = g["выход"].mean().to_numpy()
    x_bar = g[["норма", "простои"]].mean().to_numpy()
    b_beta, resid_b, _, _ = manual_ols_const(x_bar, y_bar)
    sigma1 = float(resid_b @ resid_b) / (N - K - 1)
    mean_inv_t = 1.0 / T
    sigma_u2 = sigma1 - mean_inv_t * sigma_e2
    theta = 1.0 - np.sqrt(sigma_e2 / (sigma_e2 + T * sigma_u2)) if sigma_u2 > 0 else 0.0
    # GLS на квази-детрендированных
    y = df["выход"].to_numpy(dtype=float)
    x = df[["норма", "простои"]].to_numpy(dtype=float)
    y_mean_rows = df.groupby("участок", sort=True)["выход"].transform("mean").to_numpy()
    x_mean_rows = df.groupby("участок", sort=True)[["норма", "простои"]].transform("mean").to_numpy()
    y_star = y - theta * y_mean_rows
    x_star = x - theta * x_mean_rows
    Z = np.column_stack([np.ones(len(y)), x_star])
    beta_gls, resid_star, cov_gls = manual_ols(Z, y_star)
    return {"sigma_e2": sigma_e2, "sigma_u2": sigma_u2, "theta": theta,
            "beta": beta_gls[1:], "intercept": float(beta_gls[0]),
            "cov": cov_gls[1:, 1:], "beta_within": beta_w,
            "b_beta": b_beta[1:]}

# ── корпус NS-REneg: sigma_u2 < 0 (clamp) ───────────────────────────────────

RENEG_R = [2.0, -2.0, 1.0, -1.0, 1.5, -1.5, 2.5, -2.5, 0.5, -0.5, 1.0, -1.0]


def nsreneg_frame() -> pd.DataFrame:
    rows = []
    dates = list(pd.date_range("2025-05-01", periods=12, freq="D"))
    for i in range(6):
        alpha = 0.1 if i % 2 == 0 else -0.1                # крошечная альфа
        for t in range(12):
            x1 = 2.0 + 0.1 * t + 0.03 * i
            x2 = ((t + i) % 5) * 0.2 + 0.05 * (i % 2)
            r = RENEG_R[t]                                  # большая дисперсия
            y = alpha + 0.9 * x1 - 0.5 * x2 + r
            rows.append({"база": f"Б-{i+1}", "день": dates[t],
                         "погрузка": y, "наряды": x1, "ветер": x2})
    return pd.DataFrame(rows)

# ── корпус NS-REunbal: несбалансированная RE (T_i разные) ───────────────────

REUNBAL_T = [10, 11, 12, 13, 14, 15]
REUNBAL_R = [1.0, -1.0, 0.5, -0.5, 0.25, -0.25, 0.75, -0.75, 0.1, -0.1, 0.6, -0.6, 0.3, -0.3, 0.0]


def nsreunbal_frame() -> pd.DataFrame:
    rows = []
    start = pd.Timestamp("2025-07-01")
    for i in range(6):
        T = REUNBAL_T[i]
        dates = [start + pd.Timedelta(days=d) for d in range(T)]
        alpha = 2.0 + [3.0, -1.0, 2.0, -3.0, 1.0, -2.0][i]   # не линейно по i
        for t in range(T):
            x1 = 2.0 + 0.1 * t + 0.04 * i
            x2 = ((t + i) % 5) * 0.2 + 0.05 * (i % 2)
            r = REUNBAL_R[t]
            y = alpha + 1.1 * x1 - 0.7 * x2 + r
            rows.append({"терминал": f"Т-{i+1}", "число": dates[t],
                         "оборот": y, "рейсы": x1, "туман": x2})
    return pd.DataFrame(rows)


def nsreunbal_expected():
    df = nsreunbal_frame()
    w = manual_within(df, "терминал", ["оборот", "рейсы", "туман"])
    Xw = np.column_stack([w["рейсы"], w["туман"]])
    yw = w["оборот"]
    beta_w, resid_w, _ = manual_ols(Xw, yw)
    N, K = 6, 2
    total = len(df)
    sigma_e2 = float(resid_w @ resid_w) / (total - N - K)
    g = df.groupby("терминал", sort=True)
    y_bar = g["оборот"].mean().to_numpy()
    x_bar = g[["рейсы", "туман"]].mean().to_numpy()
    _, resid_b, _, _ = manual_ols_const(x_bar, y_bar)
    sigma1 = float(resid_b @ resid_b) / (N - K - 1)
    t_sizes = g.size().to_numpy(dtype=float)
    mean_inv_t = float(np.mean(1.0 / t_sizes))
    sigma_u2 = sigma1 - mean_inv_t * sigma_e2
    thetas = 1.0 - np.sqrt(sigma_e2 / (sigma_e2 + t_sizes * sigma_u2))
    theta_map = {f"Т-{i+1}": float(thetas[i]) for i in range(6)}
    y = df["оборот"].to_numpy(dtype=float)
    x = df[["рейсы", "туман"]].to_numpy(dtype=float)
    y_mean_rows = df.groupby("терминал", sort=True)["оборот"].transform("mean").to_numpy()
    x_mean_rows = df.groupby("терминал", sort=True)[["рейсы", "туман"]].transform("mean").to_numpy()
    ent = df["терминал"].to_numpy()
    th_rows = np.array([theta_map[e] for e in ent])
    y_star = y - th_rows * y_mean_rows
    x_star = x - th_rows[:, None] * x_mean_rows
    Z = np.column_stack([np.ones(len(y)), x_star])
    beta_gls, resid_star, cov_gls = manual_ols(Z, y_star)
    return {"sigma_e2": sigma_e2, "sigma_u2": sigma_u2,
            "theta_map": theta_map, "beta": beta_gls[1:],
            "intercept": float(beta_gls[0]), "cov": cov_gls[1:, 1:]}

# ── корпус NS-VAR: VAR(1)/VAR(2) точное восстановление ──────────────────────

VAR_C = (1.0, 2.0)
VAR_ALPHAS = [(float(i), 2.0 * i) for i in range(6)]      # intercept-векторы


def gen_var_panel(A_list: list[dict], c: tuple, alphas: list[tuple], T: int, K: int = 2, N: int = 6):
    dates = list(pd.date_range("2025-08-01", periods=T, freq="D"))
    rows = []
    for i in range(N):
        y = [c[k] + alphas[i][k] for k in range(K)]
        series = [list(y)]
        for t in range(1, T):
            nxt = []
            for k in range(K):
                v = c[k] + alphas[i][k]
                for ell, A in enumerate(A_list, start=1):
                    for j in range(K):
                        v += A[f"v{k+1}"][f"v{j+1}"] * series[t - ell][j]
                nxt.append(v)
            series.append(nxt)
        for t in range(T):
            row = {"объект": f"О-{i+1}", "шаг": dates[t]}
            row["v1"], row["v2"] = series[t][0], series[t][1]
            rows.append(row)
    return pd.DataFrame(rows)


VAR1_A = {"v1": {"v1": 0.85, "v2": 0.1}, "v2": {"v1": -0.1, "v2": 0.9}}


def nsvar_frame() -> pd.DataFrame:
    return gen_var_panel([VAR1_A], VAR_C, VAR_ALPHAS, T=24)


VAR2_A = [{"v1": {"v1": 0.6, "v2": 0.15}, "v2": {"v1": -0.15, "v2": 0.55}},
          {"v1": {"v1": 0.2, "v2": 0.05}, "v2": {"v1": 0.0, "v2": -0.15}}]


def nsvar2_frame() -> pd.DataFrame:
    return gen_var_panel(VAR2_A, (0.5, -1.0),
                         [(1.0 + i, 0.5 * i) for i in range(6)], T=30)


def nsvar_short_frame() -> pd.DataFrame:
    return gen_var_panel([VAR1_A], VAR_C, VAR_ALPHAS, T=16)


def nsvar_unbal_frame() -> pd.DataFrame:
    """Несбалансированный VAR-корпус: у О-6 сетка сдвинута на 1 день
    (теряет первый день, получает день за краем общей сетки)."""
    df = nsvar_frame()
    shift = df["объект"] == "О-6"
    df.loc[shift, "шаг"] = df.loc[shift, "шаг"] + pd.Timedelta(days=1)
    drop = shift & (df["шаг"] == df.loc[shift, "шаг"].min())
    return df[~drop].reset_index(drop=True)


def var_expected(A_list, c, alphas):
    """Ручные A-матрицы/интерсепты: base = c + alpha_0; entity_i = alpha_i - alpha_0."""
    a_matrices = [dict(A) for A in A_list]
    a0 = alphas[0]
    base = {f"v{k+1}": c[k] + a0[k] for k in range(len(c))}
    ent = {"О-1": {f"v{k+1}": 0.0 for k in range(len(c))}}
    for i, a in enumerate(alphas[1:], start=1):
        ent[f"О-{i+1}"] = {f"v{k+1}": a[k] - a0[k] for k in range(len(c))}
    return {"a_matrices": a_matrices, "base": base, "entity": ent}


def var_last_states(frame: pd.DataFrame, T: int, lags: int, K: int = 2, N: int = 6):
    """Ручные last_states: популяционное среднее последних lags общих дат."""
    wide = frame[["v1", "v2"]].to_numpy(dtype=float).reshape(N, T, K)
    states = []
    for t in range(T - lags, T):
        states.append({f"v{j+1}": float(wide[:, t, j].mean()) for j in range(K)})
    return states


def var_manual_forecast(A_list, c, alphas, last_states, horizon, K=2):
    """Ручная рекурсия: c_pop = c + mean(alpha_i); y_s = c_pop + sum A_ell y_{s-ell}."""
    mean_a = [float(np.mean([a[k] for a in alphas])) for k in range(K)]
    c_pop = {f"v{k+1}": c[k] + mean_a[k] for k in range(K)}
    state = [dict(s) for s in last_states]
    steps = []
    for _ in range(horizon):
        nxt = {}
        for k in range(K):
            v = c_pop[f"v{k+1}"]
            for ell, A in enumerate(A_list, start=1):
                for j in range(K):
                    v += A[f"v{k+1}"][f"v{j+1}"] * state[-ell][f"v{j+1}"]
            nxt[f"v{k+1}"] = v
        state.append(nxt)
        steps.append(dict(nxt))
    return steps

# ── корпус NS-fold: раскладка folds ─────────────────────────────────────────

NSFOLD_DATES = 30


def nsfold_frame(T: int = NSFOLD_DATES, N: int = 6) -> pd.DataFrame:
    rows = []
    dates = list(pd.date_range("2025-09-01", periods=T, freq="D"))
    for i in range(N):
        for t in range(T):
            x1 = 2.0 + (0.05 + 0.02 * i) * t      # по-сущностный наклон
            x2 = ((t + i) % 5) * 0.2 + 0.05 * (i % 2)
            y = 5.0 + i + 1.0 * x1 - 0.5 * x2 + NS1_R[t % 4]
            rows.append({"камера": f"К-{i+1}", "число": dates[t],
                         "груз": y, "приём": x1, "отгруз": x2})
    return pd.DataFrame(rows)


def expected_folds(n_dates: int, horizon: int, n_folds: int, gap: int, strategy: str, min_train: int):
    """Ручная раскладка (контрактная формула, независимо воспроизведённая)."""
    folds = []
    for i in range(1, n_folds + 1):
        test_end = n_dates - (horizon + gap) * (n_folds - i)
        test_start = test_end - horizon
        train_end = test_start - 1 - gap
        if strategy == "sliding":
            train_start = max(train_end + 1 - max(horizon * n_folds, min_train), 0)
        else:
            train_start = 0
        folds.append((train_start, train_end, test_start, test_end - 1))
    return folds

# ── корпус NS-engine: движок end-to-end (6 x 14, h=2, folds=2) ──────────────


def nsengine_frame() -> pd.DataFrame:
    return nsfold_frame(T=14, N=6)

# ── гейт-корпуса ────────────────────────────────────────────────────────────


def gate_entities_frame(n_entities: int = 4, T: int = 12) -> pd.DataFrame:
    rows = []
    dates = list(pd.date_range("2025-10-01", periods=T, freq="D"))
    for i in range(n_entities):
        for t in range(T):
            x1 = 1.0 + 0.1 * t
            y = 3.0 + i + 0.8 * x1
            rows.append({"г": f"G-{i+1}", "д": dates[t], "у": y, "э": x1})
    return pd.DataFrame(rows)


def gate_short_frame(T: int = 9) -> pd.DataFrame:
    return nsfold_frame(T=T, N=6)


def gate_noexog_frame() -> pd.DataFrame:
    rows = []
    dates = list(pd.date_range("2025-10-01", periods=12, freq="D"))
    for i in range(6):
        for t in range(12):
            y = 5.0 + i + ((t * 3 + i) % 7) * 0.5
            rows.append({"н": f"Н-{i+1}", "в": dates[t], "только": y})
    return pd.DataFrame(rows)

# ── кап-корпуса ─────────────────────────────────────────────────────────────


def cap_frame(n_entities: int, T: int = 10) -> pd.DataFrame:
    rows = []
    dates = list(pd.date_range("2025-11-01", periods=T, freq="D"))
    for i in range(n_entities):
        base = float(1000 + i)
        for t in range(T):
            x1 = 1.0 + 0.01 * t
            y = base + 0.5 * x1 + ((t + i) % 3) * 0.1
            rows.append({"e": f"E{i:05d}", "d": dates[t], "y": y, "x": x1})
    return pd.DataFrame(rows)
