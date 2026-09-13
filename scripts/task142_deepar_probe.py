# scripts/task142_deepar_probe.py
"""Task 142 probe: поверхность конструктора DeepAR 3.2.2 + панель + MQLoss.

Эмпирические вопросы адаптера apps/api/model_impls/deepar.py (прецедент
scripts/task141_tft_probe.py); постановка -- Task 142: DeepAR -- panel-
постановка (правило моделирования: «DeepAR активируется только для
настоящей панели с несколькими рядами; несколько числовых колонок одного
объекта не выдаются за панель»; yaml::deepar min_series=5, F05) + пятый
исполнитель Neural Runtime Contract Task 137 (probabilistic losses и
quantiles; MQLoss зарезервирован за срезами 141-142):

1. DeepAR конструируется на 3.2.2 с какими kwargs: lstm_hidden_size,
   lstm_n_layers, trajectory_samples; официальный дефолт loss
   (DistributionLoss -- каталожное «parametric distribution head»);
2. probabilistic-путь MQLoss: loss=MQLoss(quantiles=[alpha/2, 0.5,
   1-alpha/2]) -- колонки отклика predict: "DeepAR-median" (точка =
   медиана), "DeepAR-lo-<w>"/"DeepAR-hi-<w>" (w = 100*(1-alpha), width-
   семантика НАХОДКИ Task 141 п.2);
3. ПАНЕЛЬ: долгий формат с 5 unique_id -- один глобальный фит, predict
   возвращает n_series * horizon строк; извлечение ПРОГНОЗА ЦЕЛЕВОГО
   ряда по unique_id (глобальная модель DeepAR -- суть среза);
4. дефолтный DistributionLoss: какие колонки (informational -- честное
   описание альтернативы; выбор MQLoss -- платформенная конвенция
   Task 141, дисклоужено в metadata.intervals);
5. freq=1 для целочисленной ds-сетки (конвенция нейро-семейства);
6. seed-детерминизм: same-seed бит-паритет, другой seed -- другой
   прогноз (сид ДОХОДИТ до конструктора -- ресертификация Task 137);
7. проводка бюджета: сконструированная модель несёт max_steps/
   random_seed/input_size (урок НАХОДКИ-1/M18 сертификации Task 138);
8. гейт неосуществимого окна: библиотека честно отказывает на
   n_train < input_size + horizon (MQLoss БЕЗ conformal-калибровки --
   потребность +2 НЕ следует, прецедент tft);
9. граница окна n == input_size + horizon исполняется честно (формула
   гейта адаптера);
10. Balanced-панель платформы: все серии одной длины (related_series
    движка expected_length=len(target)).
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


def _panel(
    n: int = 64, n_series: int = 5, seed: int = 5,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    frames = []
    for index in range(n_series):
        level = 10.0 + 2.0 * index
        frames.append(pd.DataFrame({
            "unique_id": [f"series_{index}"] * n,
            "ds": pd.date_range("2024-01-01", periods=n, freq="D"),
            "y": level + 0.05 * np.arange(n) + rng.standard_normal(n) * 0.2,
        }))
    return pd.concat(frames, ignore_index=True)


def _mqloss_cls():
    nf = __import__("neuralforecast")
    return nf.losses.pytorch.MQLoss


def main() -> None:
    models = __import__("neuralforecast").models
    MQLoss = _mqloss_cls()

    # 0) Поверхность конструктора DeepAR
    signature = inspect.signature(models.DeepAR.__init__)
    defaults = {
        name: parameter.default
        for name, parameter in signature.parameters.items()
    }
    print("DeepAR defaults (interesting):")
    for key in ("input_size", "lstm_n_layers", "lstm_hidden_size",
                "lstm_dropout", "trajectory_samples", "loss", "max_steps",
                "random_seed", "batch_size", "scaler_type", "alias",
                "start_padding_enabled"):
        if key in defaults:
            print(f"  default {key} = {defaults[key]!r}")
    default_loss = defaults.get("loss")
    print("  default loss distribution:",
          type(default_loss).__name__ if default_loss is not None else None,
          getattr(default_loss, "distribution", None))

    # 1) Контрактный гейт probabilistic-поверхности
    plan = interval_levels_for_alpha(0.05)
    loss_name = resolve_probabilistic_loss("mqloss", levels=plan.levels)
    print("resolve_probabilistic_loss('mqloss') OK:", loss_name,
          "| plan.levels:", plan.levels)

    # 2) Односерийный sanity MQLoss-прогона через единый runtime
    started = time.perf_counter()
    single = _panel(n_series=1)
    preds = train_and_forecast(
        model_factory=lambda budget: models.DeepAR(
            h=4, input_size=16, alias="DeepAR",
            loss=MQLoss(quantiles=[0.025, 0.5, 0.975]),
            valid_loss=MQLoss(quantiles=[0.025, 0.5, 0.975]), **budget),
        freq="D", train_long=single, horizon=4,
        config=NeuralTrainingConfig(seed=11, max_steps=3),
        levels=(),
    )
    print("DeepAR MQLoss columns (single series):", list(preds.columns),
          f"({time.perf_counter() - started:.1f}s)")
    assert len(preds) == 4

    # 3) ПАНЕЛЬ из 5 серий: глобальный фит, predict покрывает все серии
    panel = _panel()
    preds_panel = train_and_forecast(
        model_factory=lambda budget: models.DeepAR(
            h=4, input_size=16, alias="DeepAR",
            loss=MQLoss(quantiles=[0.025, 0.5, 0.975]),
            valid_loss=MQLoss(quantiles=[0.025, 0.5, 0.975]), **budget),
        freq="D", train_long=panel, horizon=4,
        config=NeuralTrainingConfig(seed=11, max_steps=3),
        levels=(),
    )
    print("DeepAR panel rows:", len(preds_panel), "(ожидается 5*4=20)")
    print("DeepAR panel columns:", list(preds_panel.columns))
    print("DeepAR panel unique_ids:",
          sorted(preds_panel["unique_id"].astype(str).unique()))
    target_rows = preds_panel[
        preds_panel["unique_id"].astype(str) == "series_0"
    ]
    assert len(target_rows) == 4
    print("target median:",
          [round(float(v), 4) for v in target_rows["DeepAR-median"]])

    # 4) Дефолтный DistributionLoss: колонки отклика (informational)
    try:
        preds_dist = train_and_forecast(
            model_factory=lambda budget: models.DeepAR(
                h=4, input_size=16, alias="DeepAR", **budget),
            freq="D", train_long=_panel(n_series=1), horizon=4,
            config=NeuralTrainingConfig(seed=11, max_steps=3),
            levels=(),
        )
        print("DeepAR default DistributionLoss columns:",
              list(preds_dist.columns))
    except Exception as exc:  # noqa: BLE001
        print("DeepAR default DistributionLoss FAILED:",
              type(exc).__name__, str(exc)[:140])

    # 5) integer ds grid with freq=1
    long_int = panel.copy()
    grid = np.tile(np.arange(64), 5)
    long_int["ds"] = grid
    try:
        preds_int = train_and_forecast(
            model_factory=lambda budget: models.DeepAR(
                h=4, input_size=16, alias="DeepAR",
                loss=MQLoss(quantiles=[0.025, 0.5, 0.975]),
            valid_loss=MQLoss(quantiles=[0.025, 0.5, 0.975]), **budget),
            freq=1, train_long=long_int, horizon=4,
            config=NeuralTrainingConfig(seed=11, max_steps=3),
            levels=(),
        )
        print("DeepAR int-ds freq=1 OK; rows:", len(preds_int))
    except Exception as exc:  # noqa: BLE001
        print("DeepAR int-ds freq=1 FAILED:", type(exc).__name__, exc)

    # 6) same-seed bit-parity + cross-seed difference (медиана цели)
    def _target_median(seed: int) -> np.ndarray:
        frame = train_and_forecast(
            model_factory=lambda budget: models.DeepAR(
                h=4, input_size=16, alias="DeepAR",
                loss=MQLoss(quantiles=[0.025, 0.5, 0.975]),
            valid_loss=MQLoss(quantiles=[0.025, 0.5, 0.975]), **budget),
            freq="D", train_long=panel, horizon=4,
            config=NeuralTrainingConfig(seed=seed, max_steps=3),
            levels=(),
        )
        rows = frame[frame["unique_id"].astype(str) == "series_0"]
        return rows["DeepAR-median"].to_numpy(dtype=float)

    same_a, same_b = _target_median(21), _target_median(21)
    diff = _target_median(31337)
    print("same-seed max|diff|:", float(np.abs(same_a - same_b).max()))
    print("cross-seed max|diff|:", float(np.abs(same_a - diff).max()))

    # 7) проводка бюджета в конструктор
    probe_model = models.DeepAR(
        h=4, input_size=16, alias="DeepAR",
        loss=MQLoss(quantiles=[0.025, 0.5, 0.975]), valid_loss=MQLoss(quantiles=[0.025, 0.5, 0.975]),
        max_steps=3, accelerator="cpu", enable_progress_bar=False,
        early_stop_patience_steps=-1, random_seed=7,
    )
    print("model.max_steps:", getattr(probe_model, "max_steps", "ABSENT"),
          "model.random_seed:", getattr(probe_model, "random_seed", "ABSENT"),
          "model.input_size:", getattr(probe_model, "input_size", "ABSENT"))

    # 8) неосуществимое окно: честный отказ библиотеки
    short = _panel(n=20)
    try:
        train_and_forecast(
            model_factory=lambda budget: models.DeepAR(
                h=4, input_size=48, alias="DeepAR",
                loss=MQLoss(quantiles=[0.025, 0.5, 0.975]),
            valid_loss=MQLoss(quantiles=[0.025, 0.5, 0.975]), **budget),
            freq="D", train_long=short, horizon=4,
            config=NeuralTrainingConfig(seed=11, max_steps=3),
            levels=(),
        )
        print("DeepAR infeasible window: NOT REFUSED (unexpected)")
    except Exception as exc:  # noqa: BLE001
        print("DeepAR infeasible window refused:",
              type(exc).__name__, str(exc)[:120])

    # 9) граница окна n == input_size + horizon (MQLoss без conformal +2)
    edge = _panel(n=20)  # input 16 + h 4 == 20
    try:
        preds_edge = train_and_forecast(
            model_factory=lambda budget: models.DeepAR(
                h=4, input_size=16, alias="DeepAR",
                loss=MQLoss(quantiles=[0.025, 0.5, 0.975]),
            valid_loss=MQLoss(quantiles=[0.025, 0.5, 0.975]), **budget),
            freq="D", train_long=edge, horizon=4,
            config=NeuralTrainingConfig(seed=11, max_steps=3),
            levels=(),
        )
        print("DeepAR window edge n==input+h OK; rows:", len(preds_edge))
    except Exception as exc:  # noqa: BLE001
        print("DeepAR window edge n==input+h FAILED:",
              type(exc).__name__, str(exc)[:140])

    # 10) квантильное пересечение MQLoss на недообученной панели
    low = train_and_forecast(
        model_factory=lambda budget: models.DeepAR(
            h=4, input_size=16, alias="DeepAR",
            loss=MQLoss(quantiles=[0.025, 0.5, 0.975]),
            valid_loss=MQLoss(quantiles=[0.025, 0.5, 0.975]), **budget),
        freq="D", train_long=panel, horizon=4,
        config=NeuralTrainingConfig(seed=2, max_steps=3),
        levels=(),
    )
    target_low = low[low["unique_id"].astype(str) == "series_0"]
    crossings = int(
        (
            target_low["DeepAR-lo-95.0"].to_numpy(dtype=float)
            > target_low["DeepAR-median"].to_numpy(dtype=float)
        ).sum()
        + (
            target_low["DeepAR-median"].to_numpy(dtype=float)
            > target_low["DeepAR-hi-95.0"].to_numpy(dtype=float)
        ).sum()
    )
    print("undertrained crossing points (seed=2, max_steps=3):", crossings)

    print("PROBE OK")


if __name__ == "__main__":
    main()
