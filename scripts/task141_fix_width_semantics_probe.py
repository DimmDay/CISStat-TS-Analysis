# scripts/task141_fix_width_semantics_probe.py
"""НАХОДКА Task 141 п.2 (level-семантика 3.2.2) -- контрольный замер правки.

Эмпирическая проверка семантики суффиксов '-lo-<w>'/'-hi-<w>' на РЕАЛЬНОМ
neuralforecast 3.2.2 (тот же окружение, что ресертификация тройки):

1. СТАРЫЙ запрос тройки lstm/nbeats/nhits: predict(level=[2.5, 50.0, 97.5])
   -- процентили ПЛАНА ошибочно передаются как ШИРИНЫ.  Ожидание находки:
   колонка lo-2.5 схлопнута к точке (48.75-й процентиль), истинная
   нижняя граница живёт в lo-97.5 (1.25-й процентиль).
2. НОВЫЙ запрос (правка): predict(level=[95.0]) -- ШИРИНА w=100*(1-alpha).
   Ожидание: lo-95.0 = 2.5-й процентиль (50 - 95/2), hi-95.0 = 97.5-й;
   границы симметрично разнесены вокруг точки.

Оракул разлиновки: |lo - point| и |hi - point| при старом запросе на
нижней границе КРАЙНЕ малы (схлопывание к медиане), при новом -- значимы
и сопоставимы сверху/снизу.  Абсолютные числа зависят от окружения
(траектория обучения); структурные соотношения -- стабильны.

Запуск: python scripts/task141_fix_width_semantics_probe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from apps.api.model_impls.neural_runtime import train_and_forecast
from apps.api.neural_contract import NeuralTrainingConfig

MODEL_KW = dict(
    h=8,
    input_size=16,
    encoder_n_layers=1,
    encoder_hidden_size=10,
    decoder_hidden_size=10,
    encoder_dropout=0.0,
)


def _long(n: int = 96, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "unique_id": ["series_0"] * n,
        "ds": pd.date_range("2024-01-01", periods=n, freq="D"),
        "y": 10.0 + 0.05 * np.arange(n) + rng.standard_normal(n) * 0.4,
    })


def _columns(preds: pd.DataFrame) -> list[str]:
    return [c for c in preds.columns if "-lo-" in c or "-hi-" in c or c == "LSTM"]


def _probe(label: str, levels: tuple[float, ...]) -> None:
    print(f"\n=== {label}: predict(level={list(levels)}) ===")
    preds = train_and_forecast(
        model_factory=lambda budget: __import__(
            "neuralforecast.models", fromlist=["LSTM"]
        ).LSTM(**MODEL_KW, **budget),
        freq="D",
        train_long=_long(),
        horizon=8,
        config=NeuralTrainingConfig(seed=7, max_steps=40),
        levels=levels,
        fold_index=0,
    )
    point = preds["LSTM"].to_numpy(dtype=float)
    scale = float(np.mean(np.abs(point))) or 1.0
    print("колонки отклика:", _columns(preds))
    for column in _columns(preds):
        if column == "LSTM":
            continue
        values = preds[column].to_numpy(dtype=float)
        gap = float(np.mean(np.abs(values - point)))
        side = "ниже" if float(np.mean(values - point)) < 0 else "выше"
        print(
            f"  {column:<14} mean={float(np.mean(values)):.4f}  "
            f"средний отступ от точки = {gap:.4f} ({gap / scale * 100:.2f}% "
            f"масштаба; {side})"
        )


if __name__ == "__main__":
    # 1) СТАРЫЙ (дефектный) запрос тройки: процентили плана как ширины.
    _probe("СТАРЫЙ запрос (дефект: процентили как ширины)", (2.5, 50.0, 97.5))
    # 2) НОВЫЙ запрос (правка): ширина w = 100*(1-alpha), alpha=0.05.
    _probe("НОВЫЙ запрос (правка: ширина w=95)", (95.0,))
    # 3) АДАПТЕР ПОСЛЕ ПРАВКИ: полный путь _lstm_fit_predict на реальном
    #    runtime -- извлечение width-колонок и честная разнесённость границ.
    print("\n=== АДАПТЕР LSTM ПОСЛЕ ПРАВКИ (реальный runtime) ===")
    from apps.api.model_impls.lstm import _lstm_fit_predict

    rng = np.random.default_rng(8)
    series = (10.0 + 0.05 * np.arange(64) + rng.standard_normal(64) * 0.2).tolist()
    import os

    os.environ["CISSTAT_NEURAL_MAX_STEPS"] = "40"
    payload = _lstm_fit_predict(series, 8)
    os.environ.pop("CISSTAT_NEURAL_MAX_STEPS", None)
    point = np.asarray(payload["forecast"], dtype=float)
    lower = np.asarray(payload["lower"], dtype=float)
    upper = np.asarray(payload["upper"], dtype=float)
    scale = float(np.mean(np.abs(point)))
    print("metadata.intervals:", payload["intervals"])
    print(
        f"lower: средний отступ {float(np.mean(point - lower)):.4f} "
        f"({float(np.mean(point - lower)) / scale * 100:.2f}% масштаба, ниже)"
    )
    print(
        f"upper: средний отступ {float(np.mean(upper - point)):.4f} "
        f"({float(np.mean(upper - point)) / scale * 100:.2f}% масштаба, выше)"
    )
    assert (lower < point).all() and (point < upper).all(), "границы схлопнуты!"
    print("OK: lower < point < upper, границы значимо разнесены "
          "(не схлопнуты к медиане)")
