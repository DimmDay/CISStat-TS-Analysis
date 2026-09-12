# scripts/task141_tft_probe.py
"""Task 141 probe: поверхность конструктора TFT 3.2.2 + MQLoss/quantiles.

Эмпирические вопросы адаптера apps/api/model_impls/tft.py (прецедент
scripts/task140_nhits_probe.py); постановка -- Task 141: ПЕРВЫЙ срез с
probabilistic-поверхностью MQLoss/quantiles (контракт Task 137:
"probabilistic losses и quantiles"; граница Task 138/140 -- MQLoss
зарезервирован за срезами 141-142):

1. TFT конструируется на 3.2.2 с какими kwargs: hidden_size (d_model:
   GRU-энкодер + VSN + InterpretableMultiHeadAttention), n_head
   (attention-оси каталожного описания "Attention-based architecture"),
   lstm_layers, dropout; официальные дефолты 3.2.2;
2. probabilistic-путь: loss=MQLoss(level=[...]) -- колонки отклика
   predict: "TFT-median" (точка = медиана), "TFT-lo-<level>",
   "TFT-hi-<level>"; форматирование дробных уровней (2.5/97.5);
   дублирует ли MQLoss медиану при явном 50.0 в level;
3. совместимость с единым runtime: train_and_forecast(..., levels=())
   БЕЗ conformal (PredictionIntervals не нужен -- квантили нативны);
4. constraint n_head x hidden_size (InterpretableMultiHeadAttention:
   d_k = d_model // n_head) -- эмпирическая проверка делимости;
5. freq=1 для целочисленной ds-сетки (нативная поддержка -- как у
   lstm/nbeats/nhits);
6. seed-детерминизм: same-seed бит-паритет, другой seed -- другой
   прогноз (сид ДОХОДИТ до конструктора -- ресертификация Task 137);
7. проводка бюджета: сконструированная модель несёт max_steps/
   random_seed/input_size (урок НАХОДКИ-1/M18 сертификации Task 138);
8. гейт неосуществимого окна: библиотека честно отказывает на
   n_train < input_size + horizon;
9. контрактный гейт resolve_probabilistic_loss("mqloss", levels=...)
   пропускает план interval_levels_for_alpha.
"""
from __future__ import annotations

import inspect
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from apps.api.model_impls.neural_runtime import train_and_forecast
from apps.api.neural_contract import (
    NeuralTrainingConfig,
    interval_levels_for_alpha,
    resolve_probabilistic_loss,
)


def _frame(n: int = 64, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "unique_id": ["series_0"] * n,
        "ds": pd.date_range("2024-01-01", periods=n, freq="D"),
        "y": 10 + 0.05 * np.arange(n) + rng.standard_normal(n) * 0.2,
    })


def _mqloss_cls():
    nf = __import__("neuralforecast")
    return nf.losses.pytorch.MQLoss


def main() -> None:
    models = __import__("neuralforecast").models
    MQLoss = _mqloss_cls()

    # 0) Поверхность конструктора TFT
    signature = inspect.signature(models.TFT.__init__)
    params = list(signature.parameters)
    interesting = [
        name for name in params
        if any(token in name for token in (
            "input", "hidden", "head", "layer", "dropout", "scaler",
            "loss", "alias", "random_seed", "max_steps", "h",
        ))
    ]
    print("TFT constructor surface:", interesting)
    defaults = {
        name: parameter.default
        for name, parameter in signature.parameters.items()
    }
    for key in ("hidden_size", "lstm_layers", "hidden_continuous_size",
                "n_head", "dropout", "scaler_type"):
        if key in defaults:
            print(f"  default {key} = {defaults[key]!r}")

    # 1) Контрактный гейт probabilistic-поверхности
    plan = interval_levels_for_alpha(0.05)
    loss_name = resolve_probabilistic_loss("mqloss", levels=plan.levels)
    print("resolve_probabilistic_loss('mqloss') OK:", loss_name,
          "| plan.levels:", plan.levels,
          "| plan.method:", plan.method)

    # 2) Конструирование канонической конфигурации + бюджетный путь
    started = time.perf_counter()
    model = models.TFT(
        h=4, input_size=16, alias="TFT",
        loss=MQLoss(level=[2.5, 97.5]),
        max_steps=3, accelerator="cpu", enable_progress_bar=False,
        early_stop_patience_steps=-1, random_seed=7,
    )
    print("TFT constructed OK (MQLoss level=[2.5, 97.5]):",
          type(model).__name__, f"({time.perf_counter() - started:.1f}s)")
    print("model.max_steps:", getattr(model, "max_steps", "ABSENT"),
          "model.random_seed:", getattr(model, "random_seed", "ABSENT"),
          "model.input_size:", getattr(model, "input_size", "ABSENT"))

    # 3) MQLoss-прогон через единый runtime (БЕЗ conformal levels)
    preds = train_and_forecast(
        model_factory=lambda budget: models.TFT(
            h=4, input_size=16, alias="TFT",
            loss=MQLoss(level=[2.5, 97.5]), **budget),
        freq="D", train_long=_frame(), horizon=4,
        config=NeuralTrainingConfig(seed=11, max_steps=3),
        levels=(),
    )
    print("TFT MQLoss columns:", list(preds.columns))
    assert len(preds) == 4

    # 4) Явная медиана 50.0 в level: дубликат ли колонки?
    preds_dup = train_and_forecast(
        model_factory=lambda budget: models.TFT(
            h=4, input_size=16, alias="TFT",
            loss=MQLoss(level=[2.5, 50.0, 97.5]), **budget),
        freq="D", train_long=_frame(), horizon=4,
        config=NeuralTrainingConfig(seed=11, max_steps=3),
        levels=(),
    )
    print("TFT MQLoss columns (explicit 50.0):", list(preds_dup.columns))

    # 5) Другие уровни alpha: 0.01 -> [0.5, 99.5], 0.10 -> [5.0, 95.0]
    for alpha in (0.01, 0.10):
        sub_plan = interval_levels_for_alpha(alpha)
        lo, hi = float(sub_plan.levels[0]), float(sub_plan.levels[-1])
        cols = train_and_forecast(
            model_factory=lambda budget: models.TFT(
                h=4, input_size=16, alias="TFT",
                loss=MQLoss(level=[lo, hi]), **budget),
            freq="D", train_long=_frame(), horizon=4,
            config=NeuralTrainingConfig(seed=11, max_steps=3),
            levels=(),
        ).columns
        print(f"TFT MQLoss columns alpha={alpha} level=[{lo}, {hi}]:",
              list(cols))

    # 6) constraint n_head x hidden_size (делимость d_model)
    try:
        bad = models.TFT(
            h=4, input_size=16, alias="TFT", hidden_size=10, n_head=4,
            loss=MQLoss(level=[2.5, 97.5]),
            max_steps=3, accelerator="cpu", enable_progress_bar=False,
            early_stop_patience_steps=-1, random_seed=7,
        )
        nf_bad = __import__("neuralforecast").NeuralForecast(
            models=[bad], freq="D")
        nf_bad.fit(_frame())
        nf_bad.predict()
        print("TFT hidden_size=10 n_head=4: NOT REFUSED (unexpected)")
    except Exception as exc:  # noqa: BLE001
        print("TFT hidden_size=10 n_head=4 refused:",
              type(exc).__name__, str(exc)[:110])

    # 7) integer ds grid with freq=1
    long_int = _frame().copy()
    long_int["ds"] = np.arange(len(long_int))
    try:
        preds_int = train_and_forecast(
            model_factory=lambda budget: models.TFT(
                h=4, input_size=16, alias="TFT",
                loss=MQLoss(level=[2.5, 97.5]), **budget),
            freq=1, train_long=long_int, horizon=4,
            config=NeuralTrainingConfig(seed=11, max_steps=3),
            levels=(),
        )
        print("TFT int-ds freq=1 OK:", list(preds_int.columns))
    except Exception as exc:  # noqa: BLE001
        print("TFT int-ds freq=1 FAILED:", type(exc).__name__, exc)

    # 8) same-seed bit-parity + cross-seed difference (медиана)
    def _median(seed: int) -> np.ndarray:
        return train_and_forecast(
            model_factory=lambda budget: models.TFT(
                h=4, input_size=16, alias="TFT",
                loss=MQLoss(level=[2.5, 97.5]), **budget),
            freq="D", train_long=_frame(), horizon=4,
            config=NeuralTrainingConfig(seed=seed, max_steps=3),
            levels=(),
        )["TFT-median"].to_numpy()

    same_a, same_b = _median(21), _median(21)
    diff = _median(31337)
    print("same-seed max|diff|:", float(np.abs(same_a - same_b).max()))
    print("cross-seed max|diff|:", float(np.abs(same_a - diff).max()))

    # 9) неосуществимое окно: честный отказ библиотеки
    short = _frame(20)
    try:
        train_and_forecast(
            model_factory=lambda budget: models.TFT(
                h=4, input_size=48, alias="TFT",
                loss=MQLoss(level=[2.5, 97.5]), **budget),
            freq="D", train_long=short, horizon=4,
            config=NeuralTrainingConfig(seed=11, max_steps=3),
            levels=(),
        )
        print("TFT infeasible window: NOT REFUSED (unexpected)")
    except Exception as exc:  # noqa: BLE001
        print("TFT infeasible window refused:",
              type(exc).__name__, str(exc)[:120])

    print("PROBE OK")


if __name__ == "__main__":
    main()
