# scripts/audit_scripts/task142a_f3_validation_probe.py
"""Независимая валидация находки F3 аудита Task 142 (Дарио) на дереве
main@4e5df1b (после Task 143) -- ПЕРЕД применением фикса Task 142a.

Задача исполнителя (Super Z): оценить состоятельность находок первого
аудита Сертификации Task 142 по ТЕКУЩЕМУ коду.  F3 -- блокирующая:
probabilistic-поверхность DeepAR+MQLoss вырождена на живом runtime
neuralforecast 3.2.2 (квантили == медиана бит-в-бит, ширина 0), точка
дегенерирует по масштабу (дефолт scaler_type="identity").

Проб -- СЫРАЯ библиотека вне адаптера (находка не должна зависеть от
кодовой обвязки платформы), панель исполнителя валидации (НЕ панель
аудитора -- seed=20261, независимость данных), малый бюджет 40 шагов.

Матрица:
  V1 DeepAR + MQLoss + identity  (статус-кво 4e5df1b) -- ожидание RED:
     ширина 0, точка вне масштаба;
  V2 DeepAR + DistributionLoss + robust (кандидат фикса Task 142a) --
     ожидание GREEN: ширина > 0, точка в масштабе;
  К DeepAR + MQLoss + robust -- изоляция механизма M1 (ширина 0 даже
     на robust -- коллапс квантилей не зависит от скейлера).

Запуск: CISSTAT_NEURAL_MAX_STEPS-независим (сырая библиотека, бюджет
задан явно).  OMP_NUM_THREADS=1 для стабильности на малых хостах.
"""
import os
import sys

os.environ.setdefault("OMP_NUM_THREADS", "1")
sys.path.insert(0, ".")

import numpy as np
import pandas as pd

# ── Панель валидатора (seed=20261, НЕ данные Дарио seed=142) ────────────
rng = np.random.default_rng(20261)
n = 120
t = np.arange(n, dtype=float)
target = 100.0 + 0.08 * t + 6.0 * np.sin(2.0 * np.pi * t / 14.0) + rng.normal(0.0, 1.5, n)
related = {
    "flow": 40.0 + 0.05 * t + 3.0 * np.cos(2.0 * np.pi * t / 7.0) + rng.normal(0.0, 1.0, n),
    "pressure": 12.0 + 2.5 * np.sin(2.0 * np.pi * t / 10.0) + rng.normal(0.0, 0.8, n),
    "load": 70.0 - 0.06 * t + rng.normal(0.0, 1.2, n),
    "price": 25.0 + 0.03 * t + 2.0 * np.sin(2.0 * np.pi * t / 21.0) + rng.normal(0.0, 1.0, n),
}
PANEL = {"series_0": target, **related}

QUANTILES = [0.025, 0.5, 0.975]
H, INPUT, BUDGET, SEED = 12, 24, 40, 20261

from neuralforecast import NeuralForecast
from neuralforecast.losses.pytorch import DistributionLoss, MQLoss
from neuralforecast.models import DeepAR


def long_df(series_map):
    frames = []
    for uid, values in series_map.items():
        frames.append(pd.DataFrame({
            "unique_id": uid, "ds": np.arange(len(values), dtype=np.int64),
            "y": values,
        }))
    return pd.concat(frames, ignore_index=True)


def run(name, loss, valid_loss, scaler_type):
    kwargs = dict(h=H, input_size=INPUT, lstm_hidden_size=16, alias="DeepAR",
                  scaler_type=scaler_type, max_steps=BUDGET, random_seed=SEED)
    if valid_loss is not None:
        kwargs["valid_loss"] = valid_loss
    model = DeepAR(loss=loss, **kwargs)
    nf = NeuralForecast(models=[model], freq=1)
    nf.fit(df=long_df(PANEL))
    preds = nf.predict()
    rows = preds[preds["unique_id"].astype(str) == "series_0"].sort_values("ds")
    med_col = [c for c in preds.columns if str(c).endswith("-median")]
    lo_col = [c for c in preds.columns if "-lo-" in str(c)]
    hi_col = [c for c in preds.columns if "-hi-" in str(c)]
    tail_mean = float(np.mean(target[-H:]))
    if med_col and lo_col and hi_col:
        med = rows[med_col[0]].to_numpy(dtype=float)
        lo = rows[lo_col[0]].to_numpy(dtype=float)
        hi = rows[hi_col[0]].to_numpy(dtype=float)
        width = float(np.mean(hi - lo))
        scale_dev = abs(float(np.mean(med)) - tail_mean)
        print(f"== {name}")
        print(f"   columns: {list(preds.columns)}")
        print(f"   median[:4]={np.array2string(med[:4], precision=3)}")
        print(f"   lo[:4]    ={np.array2string(lo[:4], precision=3)}")
        print(f"   hi[:4]    ={np.array2string(hi[:4], precision=3)}")
        print(f"   max|med-lo|={float(np.max(np.abs(med - lo))):.6g} "
              f"max|hi-med|={float(np.max(np.abs(hi - med))):.6g} "
              f"mean_width={width:.6g}")
        print(f"   tail_mean={tail_mean:.3f} | point_mean={float(np.mean(med)):.3f} "
              f"| scale_dev={scale_dev:.3f}")
        ok_width = width > 0.0
        ok_scale = scale_dev < 15.0
        print(f"   VERDICT: width>0: {ok_width}; scale OK (<15): {ok_scale}")
        return ok_width, ok_scale
    print(f"== {name}: квантильных колонок нет; columns={list(preds.columns)}")
    return False, False


results = {}
results["V1 status-quo (MQLoss+identity)"] = run(
    "V1 DeepAR+MQLoss+identity (статус-кво 4e5df1b)",
    MQLoss(quantiles=QUANTILES), MQLoss(quantiles=QUANTILES), "identity")
results["К изоляция M1 (MQLoss+robust)"] = run(
    "К  DeepAR+MQLoss+robust (изоляция M1)",
    MQLoss(quantiles=QUANTILES), MQLoss(quantiles=QUANTILES), "robust")
results["V2 кандидат фикса (DistributionLoss+robust)"] = run(
    "V2 DeepAR+DistributionLoss+robust (кандидат Task 142a)",
    DistributionLoss(distribution="StudentT", quantiles=QUANTILES), None, "robust")

print("\n===== ИТОГ валидации F3 =====")
v1w, v1s = results["V1 status-quo (MQLoss+identity)"]
kw, _ = results["К изоляция M1 (MQLoss+robust)"]
v2w, v2s = results["V2 кандидат фикса (DistributionLoss+robust)"]
print(f"F3-M1 (коллапс ширины на MQLoss): воспроизведён: {not v1w}; "
      f"независим от скейлера: {not kw}; лечится DistributionLoss: {v2w}")
print(f"F3-M2 (коллапс масштаба на identity): воспроизведён: {not v1s}; "
      f"лечится robust: {v2s}")
if (not v1w) and (not kw) and v2w and (not v1s) and v2s:
    print("PROBE OK: обе находки F3 (M1+M2) подтверждены независимо; "
          "кандидат фикса Task 142a закрывает обе.")
else:
    print("PROBE MISMATCH: картина отличается от диагноза Дарио -- "
          "требуется разбор.")
    sys.exit(1)
