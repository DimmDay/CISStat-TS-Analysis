# scripts/task137_neural_api_probe.py
"""Task 137 -- эмпирический проб API neuralforecast 3.x перед реализацией runtime.

Проверяет: конструкторы пяти каталог-моделей, kwarg-поверхность (max_steps,
early_stop_patience_steps, enable_progress_bar, accelerator, random_seed,
level), fit/predict-цикл, имена point/quantile-колонок прогноза.

Ресертификация Task 137 (НАХОДКА-2): шаги приведены к фактическому API
neuralforecast 3.2.2:
- trainer_kwargs в 3.2.2 -- kwargs-ЗАХВАТ: ключ вкладывается
  ({"trainer_kwargs": {...}}), pl.Trainer(**model.trainer_kwargs) падает с
  TypeError -- контракт НЕ использует trainer_kwargs, бюджет идёт нативными
  kwargs конструктора (max_steps); проб фиксирует квирк БЕЗ fit;
- QuantileLoss(level=[...]) в 3.2.2 отклоняется конструктором (q-сигнатура);
  РАБОЧИЙ probabilistic-путь -- MQLoss(level=[10.0, 90.0]) -> колонки
  <Model>-median/-lo-<level>/-hi-<level>;
- BaseModel ставит accelerator="gpu" ТОЛЬКО при torch.cuda.is_available();
- конструктор BaseModel перезасеивает весь раном (pl.seed_everything) --
  детерминизм обязан опираться на random_seed В КОНСТРУКТОРЕ, а не только
  на внешнее сеяние (блокирующая находка сертификации Task 137).
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd


def main() -> None:
    import neuralforecast
    print("neuralforecast", neuralforecast.__version__)
    from neuralforecast import NeuralForecast
    import neuralforecast.models as M

    for name in ("LSTM", "NBEATS", "NHITS", "TFT", "DeepAR"):
        cls = getattr(M, name)
        print(f"model {name}: OK ({cls.__name__})")

    rng = np.random.default_rng(5)
    n = 96
    df = pd.DataFrame({
        "unique_id": ["series_0"] * n,
        "ds": pd.date_range("2024-01-01", periods=n, freq="D"),
        "y": 10 + 0.03 * np.arange(n) + rng.standard_normal(n) * 0.15,
    })

    model = M.NHITS(
        h=4, input_size=16, max_steps=3,
        early_stop_patience_steps=-1, enable_progress_bar=False,
        accelerator="cpu",
    )
    nf = NeuralForecast(models=[model], freq="D")
    from neuralforecast.utils import PredictionIntervals
    nf.fit(df, prediction_intervals=PredictionIntervals())
    preds = nf.predict(level=[10.0, 90.0])
    print("predict columns (conformal level):", list(preds.columns))

    # детерминизм: random_seed в КОНСТРУКТОРЕ (ресертификация): тот же seed
    # -> тот же прогноз, другой seed -> другой прогноз. Внешнее сеяние
    # (random/numpy/torch) согласовано с random_seed -- BaseModel 3.2.2 всё
    # равно перезасеивает в __init__ (pl.seed_everything).
    import random as py_random
    def _train_point(seed):
        py_random.seed(seed); np.random.seed(seed)
        import torch
        torch.manual_seed(seed)
        m = M.NHITS(h=4, input_size=16, max_steps=3,
                    early_stop_patience_steps=-1, enable_progress_bar=False,
                    accelerator="cpu", random_seed=seed)
        nfx = NeuralForecast(models=[m], freq="D")
        nfx.fit(df)
        return nfx.predict()["NHITS"].to_numpy()
    a, b = _train_point(21), _train_point(21)
    print("deterministic:", bool(np.allclose(a, b)), "max diff:", float(np.abs(a - b).max()))
    c = _train_point(31337)
    print("seed-diversity (21 vs 31337):", float(np.abs(a - c).max()) > 0.0,
          "max diff:", float(np.abs(a - c).max()))

    # trainer_kwargs в 3.2.2 -- kwargs-захват: ключ вкладывается, fit по
    # model.trainer_kwargs падает -- квирк фиксируется БЕЗ fit; бюджетный
    # путь контракта -- нативный max_steps (проверяется следующим шагом).
    model2 = M.LSTM(
        h=4, input_size=16, enable_progress_bar=False, accelerator="cpu",
        trainer_kwargs={"max_epochs": 2},
    )
    print("LSTM trainer_kwargs capture (3.2.2):", model2.trainer_kwargs)
    captured = model2.trainer_kwargs
    print("nested 'trainer_kwargs' key present (pl.Trainer(**kwargs) упал бы):",
          "trainer_kwargs" in captured)

    # рабочий бюджетный путь: LSTM на нативных kwargs конструктора
    model2b = M.LSTM(
        h=4, input_size=16, max_steps=2, enable_progress_bar=False,
        accelerator="cpu", random_seed=7,
    )
    nf2 = NeuralForecast(models=[model2b], freq="D")
    nf2.fit(df)
    p2 = nf2.predict()
    print("LSTM native budget fit/predict OK:", list(p2.columns))

    # probabilistic loss: MQLoss как train loss -- квантильные выходы
    # (3.2.2: QuantileLoss(level=...) отклоняется конструктором)
    from neuralforecast.losses.pytorch import MQLoss, QuantileLoss
    try:
        QuantileLoss(level=[10.0, 90.0])
        print("QuantileLoss(level=...): принят (не ожидалось в 3.2.2)")
    except TypeError as exc:
        print("QuantileLoss(level=...) отклонён (ожидаемо в 3.2.2):",
              str(exc)[:80])
    model3 = M.NHITS(
        h=4, input_size=16, max_steps=2, enable_progress_bar=False,
        accelerator="cpu", loss=MQLoss(level=[10.0, 90.0]),
    )
    nf4 = NeuralForecast(models=[model3], freq="D")
    nf4.fit(df)
    p4 = nf4.predict()
    print("MQLoss predict columns:", list(p4.columns))

    # DeepAR panel: 3 series
    frames = []
    for i in range(3):
        frames.append(pd.DataFrame({
            "unique_id": [f"obj_{i}"] * n,
            "ds": pd.date_range("2024-01-01", periods=n, freq="D"),
            "y": 5 + i + rng.standard_normal(n) * 0.2,
        }))
    panel = pd.concat(frames, ignore_index=True)
    deepar = M.DeepAR(h=4, input_size=16, max_steps=2,
                      enable_progress_bar=False, accelerator="cpu")
    nf3 = NeuralForecast(models=[deepar], freq="D")
    nf3.fit(panel)
    p3 = nf3.predict()
    print("DeepAR panel predict OK:", len(p3), "rows")

    print("PROBE OK")


if __name__ == "__main__":
    main()
