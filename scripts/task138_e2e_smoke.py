# scripts/task138_e2e_smoke.py
"""Task 138 -- E2E-смоук LSTM/GRU (вертикальный срез, neural-runtime).

Полная цепочка каталога на neural-воркере (group установлена):
1. readiness реестра v2: 20 connected (19 + lstm), честный runtime_available;
2. consistency gate: dispatch <-> readiness;
3. candidates: lstm -- ready с backtest/tune/diagnostics;
4. session-движок: реальный нейро-фит в общем одномерном OOF cohort
   (уровневые метрики на экспандирующих fold'ах);
5. tuning-grid: bounded param_space yaml::lstm (8 trials);
6. legacy POST /v1/models/backtest: однорядный путь применим (LSTM --
   level-модель; прецедент random_forest).

Абсолютные числа нейро-прогноза зависят от окружения (версии
torch/numpy меняют траекторию обучения); структурные ассерты --
стабильны.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from apps.api.model_execution import MODEL_EXECUTION_REGISTRY
from apps.api.model_impls.neural_runtime import neuralforecast_runtime_available
from apps.api.model_readiness import (
    PRODUCTION_BACKTEST_MODEL_IDS,
    available_model_actions,
)
from apps.api.routers.models import _BACKTEST_IMPLEMENTATIONS, _compute_candidates
from apps.api.schemas import CandidatesRequest, DataProfileRequest


def _profile() -> DataProfileRequest:
    return DataProfileRequest(
        n_observations=500,
        n_series=1,
        n_exogenous=2,
        is_regular=True,
        frequency="M",
        has_seasonality=True,
        seasonal_periods=[12],
        is_stationary_or_diffable=True,
        domain="macro",
        gpu_available=True,
        feature_engineering_applied=True,
    )


def main() -> None:
    assert neuralforecast_runtime_available(), (
        "E2E-смоук Task 138 исполняется на neural-воркере: установите "
        "apps/api/requirements-neural.txt"
    )

    # 1) readiness: 20 connected.
    assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 20, (
        f"ожидалось 20 connected, получено {len(PRODUCTION_BACKTEST_MODEL_IDS)}"
    )
    assert "lstm" in PRODUCTION_BACKTEST_MODEL_IDS

    # 2) consistency gate dispatch <-> readiness.
    assert frozenset(_BACKTEST_IMPLEMENTATIONS) == PRODUCTION_BACKTEST_MODEL_IDS

    # 3) candidates: lstm ready.
    response = _compute_candidates(CandidatesRequest(
        profile=_profile(), min_level="CONDITIONALLY_APPLICABLE",
    ))
    candidates = {item.model_id: item for item in response.candidates}
    lstm = candidates["lstm"]
    assert lstm.platform_status == "ready", lstm.platform_status
    actions = set(available_model_actions("lstm"))
    assert {"backtest", "tune", "diagnostics"} <= actions
    assert response.statistics.runnable_candidates == 16
    assert response.statistics.catalog_only_candidates == 4
    descriptor = MODEL_EXECUTION_REGISTRY.describe("lstm")
    assert descriptor["family_id"] == "neural"
    assert descriptor["dependency_group"] == "neural"
    assert descriptor["engine"] == "neuralforecast"
    print("[1-3] catalog OK: 20 connected; lstm ready (backtest/tune/diagnostics)")

    # 4) session-движок: реальный OOF cohort (2 fold'а, 72 точки).
    from apps.api.backtesting import build_backtest_plan, run_backtest_plan

    series = [
        100 + 0.3 * step + 5 * math.sin(2 * math.pi * step / 12)
        for step in range(72)
    ]
    dates = pd.date_range("2018-01-01", periods=len(series), freq="MS")
    validation = {
        "strategy": "expanding", "horizon": 3, "n_splits": 2, "gap": 0,
        "folds": [
            {"fold": 1, "train_start": 0, "train_end": 65, "gap_size": 0, "test_start": 66, "test_end": 68},
            {"fold": 2, "train_start": 0, "train_end": 68, "gap_size": 0, "test_start": 69, "test_end": 71},
        ],
    }
    plan = build_backtest_plan(
        validation, n_observations=len(series), fingerprint="task138-smoke",
        target_column="value", seasonal_period=12,
    )
    result = run_backtest_plan(
        model_id="lstm", model_name="LSTM / GRU", family_id="neural",
        series=series, labels=[value.isoformat() for value in dates],
        plan=plan, seasonal_period=12,
    )
    assert result["status"] == "success"
    assert len(result["oof_predictions"]) == 6
    mae = result["metrics"]["mae"]
    assert mae is not None and mae >= 0
    assert result["execution_contract"]["model_id"] == "lstm"
    print(f"[4] session engine OK: 2 folds, OOF=6, mae={mae:.4f}")

    # 5) tuning-grid: 8 trials из yaml.
    from src.catalog.modeling_spec_loader import ModelingSpec

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    space = spec.get_model("lstm").param_space
    grid_size = math.prod(len(values) for values in space.values())
    assert grid_size == 8, grid_size
    print(f"[5] tuning grid OK: {grid_size} trials {space}")

    # 6) legacy однорядный путь (LSTM -- level-модель, прецедент RF).
    from apps.api.model_impls import run_lstm_backtest

    demo = [10 + 0.05 * step + math.sin(step / 3.0) for step in range(120)]
    metrics = run_lstm_backtest(demo, 0.75, 12)
    assert metrics.mae is not None and metrics.mae >= 0
    print(f"[6] legacy single-series OK: mae={metrics.mae:.4f}")

    print("E2E-смоук Task 138: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ (20 connected, lstm ready)")


if __name__ == "__main__":
    main()
