# scripts/audit_scripts/task142_fix_surface_probe12.py
"""Дополнение матрицы task142_fix_surface_probe.py: E1 (MQLoss+identity,
RED-базлайн) и E2 (MQLoss+robust) -- подтверждение механизма M1:
нулевая ширина MQLoss НЕ зависит от scaler (баг рекуррентного predict
3.2.2 уничтожает квантильные каналы в обеих конфигурациях)."""
import sys

sys.path.insert(0, ".")

import numpy as np
import pandas as pd

rng = np.random.default_rng(142)
n = 120
t = np.arange(n, dtype=float)
target = 100.0 + 0.08 * t + 6.0 * np.sin(2.0 * np.pi * t / 14.0) + rng.normal(
    0.0, 1.5, n
)
related = {
    "flow": 40.0 + 0.05 * t + 3.0 * np.cos(2.0 * np.pi * t / 7.0)
    + rng.normal(0.0, 1.0, n),
    "pressure": 12.0 + 2.5 * np.sin(2.0 * np.pi * t / 10.0)
    + rng.normal(0.0, 0.8, n),
    "load": 70.0 - 0.06 * t + rng.normal(0.0, 1.2, n),
    "price": 25.0 + 0.03 * t + 2.0 * np.sin(2.0 * np.pi * t / 21.0)
    + rng.normal(0.0, 1.0, n),
}

from neuralforecast import NeuralForecast
from neuralforecast.losses.pytorch import MQLoss
from neuralforecast.models import DeepAR

from apps.api.neural_contract import fold_seed

seed = fold_seed(142, fold_index=0)
QUANTILES = [0.025, 0.5, 0.975]


def long_df_from(series_map):
    frames = []
    for uid, values in series_map.items():
        frames.append(pd.DataFrame({
            "unique_id": uid, "ds": np.arange(len(values), dtype=np.int64),
            "y": values,
        }))
    return pd.concat(frames, ignore_index=True)


PANEL = {"series_0": target, **related}


def run(name, scaler_type):
    model = DeepAR(
        h=12, input_size=24, lstm_hidden_size=16, alias="DeepAR",
        loss=MQLoss(quantiles=QUANTILES),
        valid_loss=MQLoss(quantiles=QUANTILES),
        scaler_type=scaler_type,
        max_steps=60, random_seed=seed,
    )
    nf = NeuralForecast(models=[model], freq=1)
    nf.fit(df=long_df_from(PANEL))
    preds = nf.predict()
    rows = preds[preds["unique_id"].astype(str) == "series_0"].sort_values("ds")
    med = rows["DeepAR-median"].to_numpy(dtype=float)
    lo = rows["DeepAR-lo-95.0"].to_numpy(dtype=float)
    hi = rows["DeepAR-hi-95.0"].to_numpy(dtype=float)
    print(f"== {name}")
    print(f"   median[:4]={np.array2string(med[:4], precision=3)}")
    print(f"   max|med-lo|={float(np.max(np.abs(med - lo))):.6g} "
          f"max|hi-med|={float(np.max(np.abs(hi - med))):.6g} "
          f"mean_width={float(np.mean(hi - lo)):.6g}")
    print(f"   VERDICT: width>0: {float(np.mean(hi - lo)) > 1e-9}")


run("E1 DeepAR+MQLoss+identity (status-quo RED)", "identity")
run("E2 DeepAR+MQLoss+robust", "robust")
