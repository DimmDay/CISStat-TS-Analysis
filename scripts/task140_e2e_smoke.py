# scripts/task140_e2e_smoke.py
"""Task 140 -- E2E-смоук N-HiTS (вертикальный срез, neural-runtime).

Полная цепочка каталога на neural-воркере (группа установлена):
1. readiness реестра v2: 22 connected (19 + lstm + nbeats + nhits),
   честный runtime_available;
2. consistency gate: dispatch <-> readiness;
3. candidates: nhits -- ready с backtest/tune/diagnostics (на macro-
   профиле 500 точек neural-правило < 300 не срабатывает);
4. session-движок: реальный нейро-фит в общем одномерном OOF cohort
   (уровневые метрики на экспандирующих fold'ах);
5. tuning-grid: bounded param_space yaml::nhits (8 trials);
6. legacy POST /v1/models/backtest: однорядный путь применим (N-HiTS --
   level-модель; прецедент lstm Task 138 / nbeats Task 139);
7. база сравнения Task 140: пара N-BEATS/N-HiTS на ОДНОМ runtime --
   один план fold'ов, один level-cohort, когортные ключи
   execution-контракта идентичны (честное ранжирование comparison
   sectioned by objective применимо к паре напрямую).

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
        "E2E-смоук Task 140 исполняется на neural-воркере: установите "
        "apps/api/requirements-neural.txt"
    )

    # 1) readiness: 22 connected.
    assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 22, (
        f"ожидалось 22 connected, получено {len(PRODUCTION_BACKTEST_MODEL_IDS)}"
    )
    assert "nhits" in PRODUCTION_BACKTEST_MODEL_IDS
    assert "nbeats" in PRODUCTION_BACKTEST_MODEL_IDS
    assert "lstm" in PRODUCTION_BACKTEST_MODEL_IDS

    # 2) consistency gate dispatch <-> readiness.
    assert frozenset(_BACKTEST_IMPLEMENTATIONS) == PRODUCTION_BACKTEST_MODEL_IDS

    # 3) candidates: nhits ready, tft/deepar catalog_only.
    response = _compute_candidates(CandidatesRequest(
        profile=_profile(), min_level="CONDITIONALLY_APPLICABLE",
    ))
    candidates = {item.model_id: item for item in response.candidates}
    nhits = candidates["nhits"]
    assert nhits.platform_status == "ready", nhits.platform_status
    actions = set(available_model_actions("nhits"))
    assert {"backtest", "tune", "diagnostics"} <= actions
    # deepar (min_series=5) не входит в пул кандидатов на n_series=1 --
    # catalog_only-проверка идёт по ПОЛНОМУ каталогу (24 записи).
    catalog_by_id = {item.model_id: item for item in response.catalog}
    for catalog_only in ("tft", "deepar"):
        assert catalog_by_id[catalog_only].platform_status == "catalog_only"
    assert response.statistics.runnable_candidates == 18
    assert response.statistics.catalog_only_candidates == 2
    descriptor = MODEL_EXECUTION_REGISTRY.describe("nhits")
    assert descriptor["family_id"] == "neural"
    assert descriptor["dependency_group"] == "neural"
    assert descriptor["engine"] == "neuralforecast"
    assert descriptor["adapter_id"] == "neuralforecast-nhits"
    print("[1-3] catalog OK: 22 connected; nhits ready (backtest/tune/diagnostics)")

    # 4) session-движок: реальный OOF cohort (2 fold'а, 72 точки).
    from apps.api.backtesting import build_backtest_plan, run_backtest_plan

    series = [
        100 + 0.3 * step + 5 * math.sin(2 * math.pi * step / 12)
        for step in range(72)
    ]
    dates = pd.date_range("2018-01-01", periods=len(series), freq="MS")
    labels = [value.isoformat() for value in dates]
    validation = {
        "strategy": "expanding", "horizon": 3, "n_splits": 2, "gap": 0,
        "folds": [
            {"fold": 1, "train_start": 0, "train_end": 65, "gap_size": 0, "test_start": 66, "test_end": 68},
            {"fold": 2, "train_start": 0, "train_end": 68, "gap_size": 0, "test_start": 69, "test_end": 71},
        ],
    }
    plan = build_backtest_plan(
        validation, n_observations=len(series), fingerprint="task140-smoke",
        target_column="value", seasonal_period=12,
    )
    result = run_backtest_plan(
        model_id="nhits", model_name="N-HiTS", family_id="neural",
        series=series, labels=labels,
        plan=plan, seasonal_period=12,
    )
    assert result["status"] == "success"
    assert len(result["oof_predictions"]) == 6
    mae = result["metrics"]["mae"]
    assert mae is not None and mae >= 0
    assert result["execution_contract"]["model_id"] == "nhits"
    print(f"[4] session engine OK: 2 folds, OOF=6, mae={mae:.4f}")

    # 5) tuning-grid: 8 trials из yaml.
    from src.catalog.modeling_spec_loader import ModelingSpec

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    space = spec.get_model("nhits").param_space
    grid_size = math.prod(len(values) for values in space.values())
    assert grid_size == 8, grid_size
    print(f"[5] tuning grid OK: {grid_size} trials {space}")

    # 6) legacy однорядный путь (N-HiTS -- level-модель, прецедент lstm/nbeats).
    from apps.api.model_impls import run_nhits_backtest

    demo = [10 + 0.05 * step + math.sin(step / 3.0) for step in range(120)]
    metrics = run_nhits_backtest(demo, 0.75, 12)
    assert metrics.mae is not None and metrics.mae >= 0
    print(f"[6] legacy single-series OK: mae={metrics.mae:.4f}")

    # 7) база сравнения Task 140: пара N-BEATS/N-HiTS на одном runtime.
    results = {
        model_id: run_backtest_plan(
            model_id=model_id,
            model_name="N-BEATS" if model_id == "nbeats" else "N-HiTS",
            family_id="neural", series=series, labels=labels,
            plan=plan, seasonal_period=12,
        )
        for model_id in ("nbeats", "nhits")
    }
    assert all(item["status"] == "success" for item in results.values())
    contracts = {
        model_id: results[model_id]["execution_contract"]
        for model_id in ("nbeats", "nhits")
    }
    for key in ("version", "objective", "input_kind", "output_kind",
                "fit_policy", "dependency_group"):
        assert contracts["nhits"][key] == contracts["nbeats"][key], key
    pair_metrics = {
        model_id: results[model_id]["metrics"]["mae"]
        for model_id in ("nbeats", "nhits")
    }
    print(
        "[7] pair comparison base OK: nbeats mae="
        f"{pair_metrics['nbeats']:.4f}, nhits mae={pair_metrics['nhits']:.4f} "
        "(один runtime, один cohort, идентичные когортные контракты)"
    )

    print("E2E-смоук Task 140: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ (22 connected, nhits ready)")


if __name__ == "__main__":
    main()
