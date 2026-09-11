# scripts/task138_neural_lstm_probe.py
"""Task 138 probe: LSTM/GRU kwargs + conformal columns + int-ds grid.

Empirische вопросы адаптера apps/api/model_impls/lstm.py:
1. LSTM/GRU конструируются с encoder/decoder kwargs на 3.2.2;
2. conformal-выходы point-loss моделей: колонки <Model>-lo-<level>/<Model>-hi-<level>;
3. freq для целочисленной ds-сетки (NeuralForecast(freq=1)?);
4. seed-детерминизм (same-seed бит-паритет) на адаптерном пути.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from apps.api.model_impls.neural_runtime import train_and_forecast
from apps.api.neural_contract import NeuralTrainingConfig


def _frame(n: int = 64, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "unique_id": ["series_0"] * n,
        "ds": pd.date_range("2024-01-01", periods=n, freq="D"),
        "y": 10 + 0.05 * np.arange(n) + rng.standard_normal(n) * 0.2,
    })


def main() -> None:
    models = require = __import__("neuralforecast").models

    # 1) LSTM kwargs (encoder/decoder) + GRU
    for cls_name, extra in (("LSTM", {}), ("GRU", {})):
        cls = getattr(models, cls_name)
        model = cls(
            h=4, input_size=16,
            encoder_n_layers=1, encoder_hidden_size=32, decoder_hidden_size=32,
            max_steps=3, accelerator="cpu", enable_progress_bar=False,
            early_stop_patience_steps=-1, random_seed=7,
        )
        print(f"{cls_name} constructed OK:", type(model).__name__)

    # 2) conformal columns for LSTM
    preds = train_and_forecast(
        model_factory=lambda budget: models.LSTM(
            h=4, input_size=16, encoder_n_layers=1, encoder_hidden_size=32,
            decoder_hidden_size=32, **budget),
        freq="D", train_long=_frame(), horizon=4,
        config=NeuralTrainingConfig(seed=11, max_steps=3),
        levels=(5.0, 50.0, 95.0),
    )
    print("LSTM conformal columns:", list(preds.columns))
    assert len(preds) == 4

    # 3) integer ds grid with freq=1
    long_int = _frame().copy()
    long_int["ds"] = np.arange(len(long_int))
    try:
        preds_int = train_and_forecast(
            model_factory=lambda budget: models.GRU(
                h=4, input_size=16, encoder_n_layers=1, encoder_hidden_size=32,
                decoder_hidden_size=32, **budget),
            freq=1, train_long=long_int, horizon=4,
            config=NeuralTrainingConfig(seed=11, max_steps=3),
        )
        print("GRU int-ds freq=1 OK:", list(preds_int.columns))
    except Exception as exc:  # noqa: BLE001
        print("GRU int-ds freq=1 FAILED:", type(exc).__name__, exc)

    # 4) same-seed bit-parity (LSTM)
    def _run(seed: int) -> np.ndarray:
        return train_and_forecast(
            model_factory=lambda budget: models.LSTM(
                h=4, input_size=16, encoder_n_layers=1, encoder_hidden_size=32,
                decoder_hidden_size=32, **budget),
            freq="D", train_long=_frame(), horizon=4,
            config=NeuralTrainingConfig(seed=seed, max_steps=3),
        )["LSTM"].to_numpy()

    same_a, same_b = _run(21), _run(21)
    diff = _run(31337)
    print("same-seed max|diff|:", float(np.abs(same_a - same_b).max()))
    print("cross-seed max|diff|:", float(np.abs(same_a - diff).max()))


if __name__ == "__main__":
    main()
