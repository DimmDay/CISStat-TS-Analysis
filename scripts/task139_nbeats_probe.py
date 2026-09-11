# scripts/task139_nbeats_probe.py
"""Task 139 probe: N-BEATS kwargs + conformal columns + int-ds grid.

Эмпирические вопросы адаптера apps/api/model_impls/nbeats.py (прецедент
scripts/task138_neural_lstm_probe.py):

1. NB BEATS конструируется на 3.2.2 с encoder/decoder kwargs:
   input_size, encoder_hidden_size, encoder_n_layers, decoder_hidden_size,
   стеков stack_types/n_blocks -- какая поверхность реальна и какая
   минимальная конфигурация валидна;
2. conformal-выходы point-loss модели (loss=MAE): колонки
   NBEATS-lo-<level>/NBEATS-hi-<level> (PredictionIntervals + predict level);
3. freq=1 для целочисленной ds-сетки (нативная поддержка);
4. seed-детерминизм: same-seed бит-паритет, другой seed -- другой прогноз
   (сид ДОХОДИТ до конструктора -- ресурсертификация Task 137);
5. alias-поверхность: нейминг колонок при alias="NBEATS".
"""
from __future__ import annotations

import inspect
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
    models = __import__("neuralforecast").models

    # 0) Поверхность конструктора NBEATS
    signature = inspect.signature(models.NBEATS.__init__)
    params = list(signature.parameters)
    interesting = [
        name for name in params
        if any(token in name for token in (
            "input", "hidden", "layers", "stack", "block", "pool",
            "loss", "alias", "random_seed", "max_steps", "h",
        ))
    ]
    print("NBEATS constructor surface:", interesting)

    # 1) Конструирование с encoder/decoder kwargs + бюджетный путь
    model = models.NBEATS(
        h=4, input_size=16,
        stack_types=2 * ["trend"],          # минимальный честный стек
        n_blocks=2 * [1],
        mlp_units=3 * [[32, 32]],
        max_steps=3, accelerator="cpu", enable_progress_bar=False,
        early_stop_patience_steps=-1, random_seed=7,
    )
    print("NBEATS constructed OK:", type(model).__name__)

    # 2) conformal columns for NBEATS (loss по умолчанию = MAE)
    preds = train_and_forecast(
        model_factory=lambda budget: models.NBEATS(
            h=4, input_size=16, stack_types=2 * ["trend"], n_blocks=2 * [1],
            mlp_units=3 * [[32, 32]], **budget),
        freq="D", train_long=_frame(), horizon=4,
        config=NeuralTrainingConfig(seed=11, max_steps=3),
        levels=(5.0, 50.0, 95.0),
    )
    print("NBEATS conformal columns:", list(preds.columns))
    assert len(preds) == 4

    # 2b) alias-поверхность (стабильное именование колонок)
    try:
        preds_alias = train_and_forecast(
            model_factory=lambda budget: models.NBEATS(
                h=4, input_size=16, alias="NBEATS",
                stack_types=2 * ["trend"], n_blocks=2 * [1],
                mlp_units=3 * [[32, 32]], **budget),
            freq="D", train_long=_frame(), horizon=4,
            config=NeuralTrainingConfig(seed=11, max_steps=3),
        )
        print("NBEATS alias columns:", list(preds_alias.columns))
    except Exception as exc:  # noqa: BLE001
        print("NBEATS alias FAILED:", type(exc).__name__, exc)

    # 3) integer ds grid with freq=1
    long_int = _frame().copy()
    long_int["ds"] = np.arange(len(long_int))
    try:
        preds_int = train_and_forecast(
            model_factory=lambda budget: models.NBEATS(
                h=4, input_size=16, stack_types=2 * ["seasonality"],
                n_blocks=2 * [1], mlp_units=3 * [[32, 32]], **budget),
            freq=1, train_long=long_int, horizon=4,
            config=NeuralTrainingConfig(seed=11, max_steps=3),
        )
        print("NBEATS int-ds freq=1 OK:", list(preds_int.columns))
    except Exception as exc:  # noqa: BLE001
        print("NBEATS int-ds freq=1 FAILED:", type(exc).__name__, exc)

    # 4) same-seed bit-parity (NBEATS, дефолтный стек)
    def _run(seed: int) -> np.ndarray:
        return train_and_forecast(
            model_factory=lambda budget: models.NBEATS(
                h=4, input_size=16, stack_types=2 * ["trend"], n_blocks=2 * [1],
                mlp_units=3 * [[32, 32]], **budget),
            freq="D", train_long=_frame(), horizon=4,
            config=NeuralTrainingConfig(seed=seed, max_steps=3),
        )["NBEATS"].to_numpy()

    same_a, same_b = _run(21), _run(21)
    diff = _run(31337)
    print("same-seed max|diff|:", float(np.abs(same_a - same_b).max()))
    print("cross-seed max|diff|:", float(np.abs(same_a - diff).max()))

    print("PROBE OK")


if __name__ == "__main__":
    main()
