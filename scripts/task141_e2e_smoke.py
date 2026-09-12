# scripts/task141_e2e_smoke.py
"""Task 141 -- E2E-смоук TFT (вертикальный срез, neural-runtime).

Полная цепочка каталога на neural-воркере (группа установлена):
1. readiness реестра v2: 23 connected (19 + lstm + nbeats + nhits + tft),
   честный runtime_available;
2. consistency gate: dispatch <-> readiness;
3. candidates: tft -- ready с backtest/tune/diagnostics (на macro-
   профиле 500 точек neural-правило < 300 не срабатывает); deepar --
   единственный catalog_only (Task 142);
4. session-движок: реальный нейро-фит в общем одномерном OOF cohort
   (уровневые метрики на экспандирующих fold'ах);
5. tuning-grid: bounded param_space yaml::tft (8 trials -- n_head x
   hidden_size x input_size);
6. legacy POST /v1/models/backtest: однорядный путь применим (TFT --
   level-модель; прецедент lstm Task 138 / nbeats Task 139 / nhits
   Task 140);
7. база сравнения Task 141: quartet N-BEATS/N-HiTS/TFT на ОДНОМ
   runtime -- один план fold'ов, один level-cohort, когортные ключи
   execution-контракта идентичны; ПРОИСХОЖДЕНИЕ интервалов честно
   различается (tft -- native quantiles MQLoss, тройка -- conformal):
   различие задекларировано, а не скрыто.

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
        "E2E-смоук Task 141 исполняется на neural-воркере: установите "
        "apps/api/requirements-neural.txt"
    )

    # 1) readiness: 23 connected.
    assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 23, (
        f"ожидалось 23 connected, получено {len(PRODUCTION_BACKTEST_MODEL_IDS)}"
    )
    assert "tft" in PRODUCTION_BACKTEST_MODEL_IDS
    assert "nhits" in PRODUCTION_BACKTEST_MODEL_IDS
    assert "nbeats" in PRODUCTION_BACKTEST_MODEL_IDS
    assert "lstm" in PRODUCTION_BACKTEST_MODEL_IDS

    # 2) consistency gate dispatch <-> readiness.
    assert frozenset(_BACKTEST_IMPLEMENTATIONS) == PRODUCTION_BACKTEST_MODEL_IDS

    # 3) candidates: tft ready, deepar catalog_only.
    response = _compute_candidates(CandidatesRequest(
        profile=_profile(), min_level="CONDITIONALLY_APPLICABLE",
    ))
    candidates = {item.model_id: item for item in response.candidates}
    tft = candidates["tft"]
    assert tft.platform_status == "ready", tft.platform_status
    actions = set(available_model_actions("tft"))
    assert {"backtest", "tune", "diagnostics"} <= actions
    # deepar (min_series=5) не входит в пул кандидатов на n_series=1 --
    # catalog_only-проверка идёт по ПОЛНОМУ каталогу (24 записи).
    catalog_by_id = {item.model_id: item for item in response.catalog}
    assert catalog_by_id["deepar"].platform_status == "catalog_only"
    assert response.statistics.runnable_candidates == 19
    assert response.statistics.catalog_only_candidates == 1
    descriptor = MODEL_EXECUTION_REGISTRY.describe("tft")
    assert descriptor["family_id"] == "neural"
    assert descriptor["dependency_group"] == "neural"
    assert descriptor["engine"] == "neuralforecast"
    assert descriptor["adapter_id"] == "neuralforecast-tft"
    from apps.api.model_impls.tft import _resolve_max_steps

    print(
        "[1-3] catalog OK: 23 connected; tft ready (backtest/tune/"
        f"/diagnostics); бюджет обучения fold'а max_steps="
        f"{_resolve_max_steps()} (env-рычаг CISSTAT_NEURAL_MAX_STEPS "
        "или сертифицированная константа 300)"
    )

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
        validation, n_observations=len(series), fingerprint="task141-smoke",
        target_column="value", seasonal_period=12,
    )
    result = run_backtest_plan(
        model_id="tft", model_name="Temporal Fusion Transformer",
        family_id="neural", series=series, labels=labels,
        plan=plan, seasonal_period=12,
    )
    assert result["status"] == "success"
    assert len(result["oof_predictions"]) == 6
    mae = result["metrics"]["mae"]
    assert mae is not None and mae >= 0
    assert result["execution_contract"]["model_id"] == "tft"
    print(f"[4] session engine OK: 2 folds, OOF=6, mae={mae:.4f}")

    # 5) tuning-grid: 8 trials из yaml.
    from src.catalog.modeling_spec_loader import ModelingSpec

    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    space = spec.get_model("tft").param_space
    grid_size = math.prod(len(values) for values in space.values())
    assert grid_size == 8, grid_size
    print(f"[5] tuning grid OK: {grid_size} trials {space}")

    # 6) legacy однорядный путь (TFT -- level-модель, прецедент
    #    lstm/nbeats/nhits).
    from apps.api.model_impls import run_tft_backtest

    demo = [10 + 0.05 * step + math.sin(step / 3.0) for step in range(120)]
    metrics = run_tft_backtest(demo, 0.75, 12)
    assert metrics.mae is not None and metrics.mae >= 0
    print(f"[6] legacy single-series OK: mae={metrics.mae:.4f}")

    # 7) база сравнения Task 141: quartet на одном runtime; честное
    #    различие происхождения интервалов (quantiles vs conformal).
    results = {
        model_id: run_backtest_plan(
            model_id=model_id,
            model_name={
                "nbeats": "N-BEATS", "nhits": "N-HiTS",
                "tft": "Temporal Fusion Transformer",
            }[model_id],
            family_id="neural", series=series, labels=labels,
            plan=plan, seasonal_period=12,
        )
        for model_id in ("nbeats", "nhits", "tft")
    }
    assert all(item["status"] == "success" for item in results.values())
    contracts = {
        model_id: results[model_id]["execution_contract"]
        for model_id in ("nbeats", "nhits", "tft")
    }
    for key in ("version", "objective", "input_kind", "output_kind",
                "fit_policy", "dependency_group"):
        assert contracts["tft"][key] == contracts["nbeats"][key], key
        assert contracts["tft"][key] == contracts["nhits"][key], key
    # Probabilistic-поверхность Task 141: native quantiles MQLoss.
    from apps.api.model_impls.tft import _quantile_plan

    plan_quantiles = _quantile_plan(0.05)
    assert plan_quantiles["method"] == "neural_quantile_outputs"
    assert plan_quantiles["quantiles"] == (0.025, 0.5, 0.975)
    quartet_metrics = {
        model_id: results[model_id]["metrics"]["mae"]
        for model_id in ("nbeats", "nhits", "tft")
    }
    print(
        "[7] quartet comparison base OK: nbeats mae="
        f"{quartet_metrics['nbeats']:.4f}, nhits mae="
        f"{quartet_metrics['nhits']:.4f}, tft mae="
        f"{quartet_metrics['tft']:.4f} (один runtime, один cohort; "
        "интервалы tft -- native quantiles MQLoss, тройки -- conformal)"
    )

    print("E2E-смоук Task 141: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ (23 connected, tft ready)")


if __name__ == "__main__":
    main()
