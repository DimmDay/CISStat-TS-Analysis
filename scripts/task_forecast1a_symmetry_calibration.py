# -*- coding: utf-8 -*-
"""Калибровка симметрийного оракула симуляции (убийца MUT-06).

На симметричном шуме (белый шум вокруг константы) веер параметрической
симуляции обязан быть симметричным вокруг точки: |point-lower| ~= |upper-point|.
MUT-06 (нижний квантиль alpha/2 -> alpha) сужает нижнюю границу и ломает
симметрию. Скрипт снимает фактическую асимметрию на чистом коде и под
мутантом, чтобы выбрать допуск оракула с запасом.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import numpy as np
import pandas as pd


def asymmetry(trajectories: int) -> tuple[float, float]:
    from apps.api.final_fit import build_final_fit
    from apps.api.forecasting import compute_forecast
    from apps.api.forecasting_contract import resolve_forecast_alpha
    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY

    rng = np.random.default_rng(20261)
    n = 96
    values = 100.0 + rng.normal(0, 5.0, n)  # симметричный шум вокруг константы
    frame = pd.DataFrame({
        "date": pd.date_range("2018-01-01", periods=n, freq="MS").astype(str),
        "value": values,
    })
    fit = build_final_fit(
        frame, target_column="value", date_column="date",
        transformations={}, scaling_recipe={},
    )
    computation = compute_forecast(
        model_id="ets", horizon=4,
        alpha_resolution=resolve_forecast_alpha("ets", 0.05, {}),
        final_fit=fit, seasonal_period=1,
        params={"trend": None, "seasonal": None},
        registry=MODEL_EXECUTION_REGISTRY, history_values=fit.source_values,
        history_labels=fit.history_labels,
        future_labels=[
            str(d.date()) for d in pd.date_range(frame["date"].iloc[-1], periods=5, freq="MS")[1:]
        ],
        oof_predictions=[], validated_horizon=6,
        simulation_trajectories=trajectories, random_state=20261,
    )
    ratios = []
    for p in computation.points:
        down = p["value"] - p["ci_lower"]
        up = p["ci_upper"] - p["value"]
        ratios.append(abs(up - down) / max(down, up))
    return max(ratios), float(np.mean(ratios))


if __name__ == "__main__":
    for trajs in (500, 1500, 3000):
        worst, mean = asymmetry(trajs)
        print(f"clean trajectories={trajs}: worst_asymmetry={worst:.4f} mean={mean:.4f}")
