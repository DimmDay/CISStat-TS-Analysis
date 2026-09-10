# scripts/task137_neural_api_probe.py
"""Task 137 -- эмпирический проб API neuralforecast 3.x перед реализацией runtime.

Проверяет: конструкторы пяти каталог-моделей, kwarg-поверхность (max_steps,
early_stop_patience_steps, enable_progress_bar, accelerator, level),
fit/predict-цикл, имена point/quantile-колонок прогноза.
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

    # детерминизм: тот же seed -> тот же прогноз
    import random as py_random
    def _train_point(seed):
        py_random.seed(seed); np.random.seed(seed)
        import torch
        torch.manual_seed(seed)
        m = M.NHITS(h=4, input_size=16, max_steps=3,
                    early_stop_patience_steps=-1, enable_progress_bar=False,
                    accelerator="cpu")
        nfx = NeuralForecast(models=[m], freq="D")
        nfx.fit(df)
        return nfx.predict()["NHITS"].to_numpy()
    a, b = _train_point(21), _train_point(21)
    print("deterministic:", bool(np.allclose(a, b)), "max diff:", float(np.abs(a - b).max()))

    # max_epochs через trainer_kwargs
    model2 = M.LSTM(
        h=4, input_size=16, enable_progress_bar=False, accelerator="cpu",
        trainer_kwargs={"max_epochs": 2},
    )
    nf2 = NeuralForecast(models=[model2], freq="D")
    nf2.fit(df)
    p2 = nf2.predict()
    print("LSTM trainer_kwargs fit/predict OK:", list(p2.columns))

    # probabilistic loss: QuantileLoss как train loss -- квантильные выходы
    from neuralforecast.losses.pytorch import QuantileLoss
    model3 = M.NHITS(
        h=4, input_size=16, max_steps=2, enable_progress_bar=False,
        accelerator="cpu", loss=QuantileLoss(level=[10.0, 90.0]),
    )
    nf4 = NeuralForecast(models=[model3], freq="D")
    nf4.fit(df)
    p4 = nf4.predict()
    print("QuantileLoss predict columns:", list(p4.columns))

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
