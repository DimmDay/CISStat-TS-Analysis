# scripts/task140_nhits_probe.py
"""Task 140 probe: N-HiTS kwargs + conformal columns + int-ds grid.

Эмпирические вопросы адаптера apps/api/model_impls/nhits.py (прецедент
scripts/task139_nbeats_probe.py):

1. NHITS конструируется на 3.2.2 с какими kwargs: mlp_units (как NBEATS)
   или encoder_hidden_size, plus N-HiTS-специфика -- n_pool_kernel_size
   (multi-rate input pooling) и n_freq_downsample (hierarchical
   interpolation); официальные дефолты 3.2.2;
2. обе bounded-конфигурации интерполяции конструируются и фитятся:
   hierarchical (каноническая -- официальные дефолты библиотеки) и
   light (минимальная иерархия, фактор 2 только на самом грубом стеке);
3. conformal-выходы point-loss модели (loss=MAE): колонки
   NHITS-lo-<level>/NHITS-hi-<level> (PredictionIntervals + predict level);
4. freq=1 для целочисленной ds-сетки (нативная поддержка);
5. seed-детерминизм: same-seed бит-паритет, другой seed -- другой прогноз
   (сид ДОХОДИТ до конструктора -- ресертификация Task 137);
6. alias-поверхность: нейминг колонок при alias="NHITS";
7. проводка бюджета: сконструированная модель несёт max_steps/random_seed
   (урок НАХОДКИ-1/M18 сертификации Task 138);
8. гейт неосуществимого окна: библиотека с start_padding_enabled=False
   честно отказывает на n_train < input_size + horizon.
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

    # 0) Поверхность конструктора NHITS
    signature = inspect.signature(models.NHITS.__init__)
    params = list(signature.parameters)
    interesting = [
        name for name in params
        if any(token in name for token in (
            "input", "hidden", "layers", "stack", "block", "pool",
            "freq", "down", "loss", "alias", "random_seed", "max_steps", "h",
        ))
    ]
    print("NHITS constructor surface:", interesting)

    defaults = {
        name: parameter.default
        for name, parameter in signature.parameters.items()
    }
    for key in ("stack_types", "n_blocks", "mlp_units",
                "n_pool_kernel_size", "n_freq_downsample"):
        if key in defaults:
            print(f"  default {key} = {defaults[key]}")

    # 1) Конструирование с официальными дефолтами (каноническая
    #    конфигурация) + бюджетный путь
    model = models.NHITS(
        h=4, input_size=16,
        mlp_units=[[16, 16], [16, 16], [16, 16]],
        max_steps=3, accelerator="cpu", enable_progress_bar=False,
        early_stop_patience_steps=-1, random_seed=7,
    )
    print("NHITS constructed OK (canonical defaults):", type(model).__name__)

    # 1b) light-конфигурация: минимальная иерархия
    model_light = models.NHITS(
        h=4, input_size=16,
        n_pool_kernel_size=[2, 1, 1], n_freq_downsample=[2, 1, 1],
        mlp_units=[[16, 16], [16, 16], [16, 16]],
        max_steps=3, accelerator="cpu", enable_progress_bar=False,
        early_stop_patience_steps=-1, random_seed=7,
    )
    print("NHITS constructed OK (light interpolation):", type(model_light).__name__)

    # 1c) атрибуты бюджета на сконструированной модели (spy-проводка)
    print("model.max_steps:", getattr(model, "max_steps", "ABSENT"),
          "model.random_seed:", getattr(model, "random_seed", "ABSENT"),
          "model.input_size:", getattr(model, "input_size", "ABSENT"))

    # 2) conformal columns for NHITS (loss по умолчанию = MAE)
    preds = train_and_forecast(
        model_factory=lambda budget: models.NHITS(
            h=4, input_size=16,
            mlp_units=[[16, 16], [16, 16], [16, 16]], **budget),
        freq="D", train_long=_frame(), horizon=4,
        config=NeuralTrainingConfig(seed=11, max_steps=3),
        levels=(5.0, 50.0, 95.0),
    )
    print("NHITS conformal columns:", list(preds.columns))
    assert len(preds) == 4

    # 2b) light-конфигурация фитится на том же runtime
    preds_light = train_and_forecast(
        model_factory=lambda budget: models.NHITS(
            h=4, input_size=16,
            n_pool_kernel_size=[2, 1, 1], n_freq_downsample=[2, 1, 1],
            mlp_units=[[16, 16], [16, 16], [16, 16]], **budget),
        freq="D", train_long=_frame(), horizon=4,
        config=NeuralTrainingConfig(seed=11, max_steps=3),
    )
    print("NHITS light config columns:", list(preds_light.columns))
    assert len(preds_light) == 4

    # 2c) alias-поверхность (стабильное именование колонок)
    try:
        preds_alias = train_and_forecast(
            model_factory=lambda budget: models.NHITS(
                h=4, input_size=16, alias="NHITS",
                mlp_units=[[16, 16], [16, 16], [16, 16]], **budget),
            freq="D", train_long=_frame(), horizon=4,
            config=NeuralTrainingConfig(seed=11, max_steps=3),
        )
        print("NHITS alias columns:", list(preds_alias.columns))
    except Exception as exc:  # noqa: BLE001
        print("NHITS alias FAILED:", type(exc).__name__, exc)

    # 3) integer ds grid with freq=1
    long_int = _frame().copy()
    long_int["ds"] = np.arange(len(long_int))
    try:
        preds_int = train_and_forecast(
            model_factory=lambda budget: models.NHITS(
                h=4, input_size=16,
                mlp_units=[[16, 16], [16, 16], [16, 16]], **budget),
            freq=1, train_long=long_int, horizon=4,
            config=NeuralTrainingConfig(seed=11, max_steps=3),
        )
        print("NHITS int-ds freq=1 OK:", list(preds_int.columns))
    except Exception as exc:  # noqa: BLE001
        print("NHITS int-ds freq=1 FAILED:", type(exc).__name__, exc)

    # 4) same-seed bit-parity (NHITS, дефолтная конфигурация)
    def _run(seed: int) -> np.ndarray:
        return train_and_forecast(
            model_factory=lambda budget: models.NHITS(
                h=4, input_size=16,
                mlp_units=[[16, 16], [16, 16], [16, 16]], **budget),
            freq="D", train_long=_frame(), horizon=4,
            config=NeuralTrainingConfig(seed=seed, max_steps=3),
        )["NHITS"].to_numpy()

    same_a, same_b = _run(21), _run(21)
    diff = _run(31337)
    print("same-seed max|diff|:", float(np.abs(same_a - same_b).max()))
    print("cross-seed max|diff|:", float(np.abs(same_a - diff).max()))

    # 5) неосуществимое окно: честный отказ библиотеки
    short = _frame(20)
    try:
        train_and_forecast(
            model_factory=lambda budget: models.NHITS(
                h=4, input_size=48,
                mlp_units=[[16, 16], [16, 16], [16, 16]], **budget),
            freq="D", train_long=short, horizon=4,
            config=NeuralTrainingConfig(seed=11, max_steps=3),
        )
        print("NHITS infeasible window: NOT REFUSED (unexpected)")
    except Exception as exc:  # noqa: BLE001
        print("NHITS infeasible window refused:",
              type(exc).__name__, str(exc)[:120])

    print("PROBE OK")


if __name__ == "__main__":
    main()
