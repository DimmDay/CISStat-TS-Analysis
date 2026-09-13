# scripts/audit_scripts/task142_fix_surface_probe.py
"""Аудиторский пробник фикса F3 (пересертификация Task 142).

Гипотеза о ДВУХ механизмах деградации DeepAR на neuralforecast 3.2.2:
  M1 (квантили): рекуррентный predict-шаг _base_model.py для
     не-distribution losses делает output_batch.mean(dim=-1) ДО
     сохранения y_hat -- все n_outputs каналов получают одно значение
     (среднее квантилей) => ширина интервала тождественно 0.
     Лечится ТОЛЬКО сменой loss-головы (DistributionLoss: y_hat =
     concat(mean, quants) -- раздельные значения).
  M2 (масштаб точки): DeepAR default scaler_type="identity" --
     рекуррентная сеть с Adam(1e-3) за семейный бюджет 300 шагов не
     выходит на уровень данных (~100).  LSTM/TFT не страдают: у них
     default scaler_type="robust" (per-window нормализация).
     Лечится явным scaler_type="robust" в фабрике адаптера.

Матрица экспериментов (панель аудитора seed=142, 5x120, budget=60):
  E1 DeepAR + MQLoss      + identity  (статус-кво коллеги)  -> RED baseline
  E2 DeepAR + MQLoss      + robust    (лечит только M2?)
  E3 DeepAR + DistributionLoss + identity (лечит только M1?)
  E4 DeepAR + DistributionLoss + robust    (комбинация -- кандидат фикса)
"""
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
from neuralforecast.losses.pytorch import DistributionLoss, MQLoss
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


def run(name, loss, valid_loss, scaler_type):
    kwargs = dict(
        h=12, input_size=24, lstm_hidden_size=16, alias="DeepAR",
        scaler_type=scaler_type,
        max_steps=60, random_seed=seed,
    )
    if valid_loss is not None:
        kwargs["valid_loss"] = valid_loss
    model = DeepAR(loss=loss, **kwargs)
    nf = NeuralForecast(models=[model], freq=1)
    nf.fit(df=long_df_from(PANEL))
    preds = nf.predict()
    rows = preds[preds["unique_id"].astype(str) == "series_0"].sort_values("ds")
    med_col = [c for c in preds.columns if str(c).endswith("-median")]
    lo_col = [c for c in preds.columns if "-lo-" in str(c)]
    hi_col = [c for c in preds.columns if "-hi-" in str(c)]
    bare = [c for c in preds.columns
            if str(c) not in ("unique_id", "ds")
            and not med_col or c == "DeepAR"]
    print(f"== {name}")
    print(f"   columns: {list(preds.columns)}")
    if med_col and lo_col and hi_col:
        med = rows[med_col[0]].to_numpy(dtype=float)
        lo = rows[lo_col[0]].to_numpy(dtype=float)
        hi = rows[hi_col[0]].to_numpy(dtype=float)
        print(f"   median[:4]={np.array2string(med[:4], precision=3)}")
        print(f"   lo[:4]    ={np.array2string(lo[:4], precision=3)}")
        print(f"   hi[:4]    ={np.array2string(hi[:4], precision=3)}")
        print(f"   max|med-lo|={float(np.max(np.abs(med - lo))):.6g} "
              f"max|hi-med|={float(np.max(np.abs(hi - med))):.6g} "
              f"mean_width={float(np.mean(hi - lo)):.6g}")
        print(f"   VERDICT: width>0: {float(np.mean(hi - lo)) > 0.0}; "
              f"point-scale OK(|median-tail|<15): "
              f"{abs(float(np.mean(med)) - float(np.mean(target[-12:]))) < 15.0}")
    else:
        print(f"   (нет тройки квантильных колонок; bare={bare})")


mq = lambda: MQLoss(quantiles=QUANTILES)
dl = lambda: DistributionLoss(distribution="StudentT", quantiles=QUANTILES)

run("E1 DeepAR+MQLoss+identity (status-quo)", mq(), mq(), "identity")
run("E2 DeepAR+MQLoss+robust", mq(), mq(), "robust")
run("E3 DeepAR+DistributionLoss+identity", dl(), None, "identity")
run("E4 DeepAR+DistributionLoss+robust", dl(), None, "robust")
