"""Проб API доверительных интервалов statsmodels 0.15.0 для модуля Прогнозирование.

Проверка фактической поверхности (прецедент платформы: «поверхность ожиданий
снимается пробом ДО написания тестов»):
  1. ARIMA get_forecast().summary_frame(alpha) -- mean_ci_lower/upper
  2. ThetaModelResults.prediction_intervals(steps, alpha) -- сигнатура/форма
  3. HoltWintersResults.simulate(nsteps, repetitions) -- параметрическая симуляция
  4. Обратная трансформация границ через нелинейную inverse (log_difference)
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/z/my-project/CISStat-TS-Analysis")


def main() -> None:
    import statsmodels
    print("statsmodels", statsmodels.__version__)
    rng = np.random.default_rng(20261)
    n = 120
    t = np.arange(n, dtype=float)
    y = 100 * np.exp(0.002 * t) + 8 * np.sin(2 * np.pi * t / 12) + rng.normal(0, 2, n)

    # 1. ARIMA
    from statsmodels.tsa.arima.model import ARIMA
    fitted = ARIMA(np.asarray(y, dtype=float), order=(1, 1, 1)).fit()
    sf = fitted.get_forecast(steps=6).summary_frame(alpha=0.05)
    cols = list(sf.columns)
    print("ARIMA summary_frame cols:", cols)
    lower = sf["mean_ci_lower"].to_numpy()
    upper = sf["mean_ci_upper"].to_numpy()
    point = sf["mean"].to_numpy()
    assert (lower < point).all() and (point < upper).all()
    print("ARIMA OK: lower < point < upper, alpha honored (0.05 -> ~1.96 sigma)")

    # 2. Theta
    from statsmodels.tsa.forecasting.theta import ThetaModel
    series = pd.Series(y, index=pd.RangeIndex(start=0, stop=n))
    theta_fit = ThetaModel(series, method="auto", period=12, deseasonalize=True).fit()
    pi = theta_fit.prediction_intervals(steps=6, alpha=0.05)
    print("Theta prediction_intervals type:", type(pi).__name__)
    pi_np = np.asarray(pi)
    print("Theta PI shape:", pi_np.shape, "cols:", list(getattr(pi, "columns", [])))
    theta_point = np.asarray(theta_fit.forecast(steps=6))
    assert (pi_np[:, 0] < theta_point).all() and (theta_point < pi_np[:, 1]).all(), pi_np
    # проверка сигнатуры с theta-параметром
    import inspect
    print("Theta sig:", str(inspect.signature(theta_fit.prediction_intervals)))
    print("Theta OK")

    # 3. ETS simulate
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    ets = ExponentialSmoothing(
        pd.Series(y, index=pd.RangeIndex(start=0, stop=n)),
        trend="add", seasonal="add", seasonal_periods=12,
        initialization_method="estimated",
    ).fit()
    sim = ets.simulate(nsimulations=6, repetitions=200, anchor="end", random_state=777)
    print("ETS simulate type:", type(sim).__name__, "shape:", np.asarray(sim).shape)
    sim_arr = np.asarray(sim)
    # repetitions в последней оси? (nsteps x reps) или (reps x nsteps)
    if sim_arr.shape[0] == 6:
        traj = sim_arr
    else:
        traj = sim_arr.T
    q_lower = np.quantile(traj, 0.025, axis=1)
    q_upper = np.quantile(traj, 0.975, axis=1)
    ets_point = np.asarray(ets.forecast(steps=6))
    assert (q_lower < ets_point).all() and (ets_point < q_upper).all()
    print("ETS simulate OK: quantile envelope around point forecast")
    print("ETS point[0]: %.3f, CI[0]: [%.3f, %.3f]" % (ets_point[0], q_lower[0], q_upper[0]))

    # 4. Нелинейная инверсия границ (log_difference) -- каждая граница отдельно
    from apps.api.fold_preprocessing import _inverse_stationarity
    state = {"seasonal_period": 1}
    input_train = y[: n - 3]  # произвольная история
    diff_fc = np.array([0.01, 0.02, -0.005])
    p = _inverse_stationarity(diff_fc, "log_difference", input_train, state)
    lo = _inverse_stationarity(diff_fc - 0.05, "log_difference", input_train, state)
    hi = _inverse_stationarity(diff_fc + 0.05, "log_difference", input_train, state)
    assert (lo < p).all() and (p < hi).all()
    asym = (p - lo) - (hi - p)
    print("log_difference inversion OK; асимметрия интервала в исходной шкале (не ноль):", asym[0] != 0)
    print("PROBE OK")


if __name__ == "__main__":
    main()
