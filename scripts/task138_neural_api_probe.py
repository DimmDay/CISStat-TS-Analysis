# scripts/task138_neural_api_probe.py
"""Task 138 -- эмпирический проб neuralforecast 3.2.2 для LSTM/GRU slice.

Проверяем на живом runtime (та же поверхность, что сертифицирована Task 137):
1. GRU-конструктор принимает budget контракта (max_steps/accelerator/
   early_stop_patience_steps/enable_progress_bar/random_seed) и alias;
2. conformal-путь: fit(prediction_intervals=PredictionIntervals()) +
   predict(level=[...]) -> колонки <alias>-lo-<level>/<alias>-hi-<level>;
3. MQLoss(level=[...]) -> колонки <alias>-median/-lo-<level>/-hi-<level>;
4. futr_exog_list: fit(df с колонкой) + predict(futr_df) на GRU;
5. same-seed детерминизм GRU (бит-в-бит) и different-seed различие.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _long(n: int = 120, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "unique_id": ["series_0"] * n,
        "ds": pd.date_range("2024-01-01", periods=n, freq="D"),
        "y": 10 + 0.03 * np.arange(n) + rng.standard_normal(n) * 0.15,
        "promo": rng.integers(0, 2, n).astype(float),
    })


def main() -> int:
    import neuralforecast as nf
    from neuralforecast.losses.pytorch import MQLoss
    from apps.api.neural_contract import NeuralTrainingConfig, fold_seed
    from apps.api.model_impls.neural_runtime import (
        train_and_forecast, neural_model_budget_kwargs, seed_neural_runtime,
    )

    print("neuralforecast", nf.__version__)
    models = nf.models
    config = NeuralTrainingConfig(seed=21, max_steps=4)

    # (1) GRU + budget + alias, conformal
    def gru_factory(budget: dict) -> object:
        return models.GRU(h=6, input_size=24, alias="gru_test", **budget)

    preds = train_and_forecast(
        model_factory=gru_factory, freq="D", train_long=_long(),
        horizon=6, config=config, levels=(10.0, 90.0), fold_index=0,
    )
    cols = list(preds.columns)
    print("(1) GRU conformal columns:", cols)
    assert any(c.endswith("-lo-10.0") for c in cols), cols
    assert any(c.endswith("-hi-90.0") for c in cols), cols
    point = [c for c in cols if c == "gru_test"]
    assert point, cols
    lo = preds[[c for c in cols if c.endswith("-lo-10.0")][0]]
    hi = preds[[c for c in cols if c.endswith("-hi-90.0")][0]]
    assert (lo <= preds["gru_test"]).all() and (preds["gru_test"] <= hi).all()

    # (2) MQLoss
    def gru_mq_factory(budget: dict) -> object:
        return models.GRU(
            h=6, input_size=24, alias="gru_mq", loss=MQLoss(level=[10.0, 90.0]),
            **budget,
        )

    preds_mq = train_and_forecast(
        model_factory=gru_mq_factory, freq="D", train_long=_long(),
        horizon=6, config=config, fold_index=0,
    )
    print("(2) GRU MQLoss columns:", list(preds_mq.columns))
    assert "gru_mq-median" in preds_mq.columns, preds_mq.columns

    # (3) futr_exog через фабрику + futr_df
    def gru_futr_factory(budget: dict) -> object:
        return models.GRU(
            h=6, input_size=24, alias="gru_f", futr_exog_list=["promo"], **budget,
        )

    train = _long()
    next_ds = pd.date_range(
        train["ds"].max() + pd.Timedelta(days=1), periods=6, freq="D",
    )
    futr = pd.DataFrame({
        "unique_id": ["series_0"] * 6,
        "ds": next_ds,
        "promo": [0.0, 1.0, 0.0, 0.0, 1.0, 0.0],
    })
    preds_f = train_and_forecast(
        model_factory=gru_futr_factory, freq="D", train_long=train,
        horizon=6, config=config, futr_df=futr, fold_index=0,
    )
    print("(3) GRU futr_exog OK, columns:", list(preds_f.columns))
    assert "gru_f" in preds_f.columns

    # (4) детерминизм GRU: same seed бит-в-бит, другой seed -- другой прогноз
    def plain_gru(budget: dict) -> object:
        return models.GRU(h=6, input_size=24, alias="gru_d", **budget)

    p1 = train_and_forecast(
        model_factory=plain_gru, freq="D", train_long=_long(),
        horizon=6, config=NeuralTrainingConfig(seed=77, max_steps=4), fold_index=0,
    )
    p2 = train_and_forecast(
        model_factory=plain_gru, freq="D", train_long=_long(),
        horizon=6, config=NeuralTrainingConfig(seed=77, max_steps=4), fold_index=0,
    )
    p3 = train_and_forecast(
        model_factory=plain_gru, freq="D", train_long=_long(),
        horizon=6, config=NeuralTrainingConfig(seed=78001, max_steps=4), fold_index=0,
    )
    same = float(np.max(np.abs(p1["gru_d"].to_numpy() - p2["gru_d"].to_numpy())))
    diff = float(np.max(np.abs(p1["gru_d"].to_numpy() - p3["gru_d"].to_numpy())))
    print(f"(4) GRU determinism: same_seed max_diff={same}, other_seed max_diff={diff}")
    assert same == 0.0 and diff > 0.0

    # (5) LSTM тоже проходит единый путь (паритет классов)
    def lstm_factory(budget: dict) -> object:
        return models.LSTM(h=6, input_size=24, alias="lstm_t", **budget)

    preds_l = train_and_forecast(
        model_factory=lstm_factory, freq="D", train_long=_long(),
        horizon=6, config=config, fold_index=0,
    )
    assert "lstm_t" in preds_l.columns
    print("(5) LSTM unified path OK")

    print("PROBE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
