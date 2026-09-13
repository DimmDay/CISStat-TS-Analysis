# scripts/task142_e2e_smoke.py
"""Task 142 -- E2E-смоук DeepAR (вертикальный срез, panel-постановка).

Полная цепочка каталога на neural-воркере (группа установлена):
1. readiness реестра v2: 24 connected (19 + lstm + nbeats + nhits + tft
   + deepar), честный runtime_available;
2. consistency gate: dispatch <-> readiness (deepar -- честный отказ в
   legacy dispatch, прецедент var/vecm);
3. candidates: deepar -- production-ready в ПОЛНОМ каталоге, но на
   macro-профиле (n_series=1) честно blocked правилом F05 (панель
   min_series=5); catalog-only моделей больше НЕТ;
4. panel-движок: реальный ГЛОБАЛЬНЫЙ нейро-фит на панели из 5 рядов в
   panel-cohort (нейро-контракт Task 137: panel=true/n_series/
   min_series=5), OOF-точки target-ряда;
5. panel tuning: bounded param_space yaml::deepar (4 trials --
   lstm_hidden_size x input_size) через панельный движок;
6. cohort-изоляция: panel-cohort_id ОТЛИЧЕН от univariate-cohort_id на
   тех же fold'ах (честный comparison, контрактный гейт);
7. панельный гейт честности: панель из 4 рядов (< min_series=5) --
   отказ ДО фита; несколько числовых колонок одного объекта не
   выдаются за панель.

Абсолютные числа нейро-прогноза зависят от окружения; структурные
ассерты -- стабильны.
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

DEEPAR_MIN_SERIES = 5


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
        "E2E-смоук Task 142 исполняется на neural-воркере: установите "
        "apps/api/requirements-neural.txt"
    )

    # 1) readiness: 24 connected.
    assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 24, (
        f"ожидалось 24 connected, получено {len(PRODUCTION_BACKTEST_MODEL_IDS)}"
    )
    assert "deepar" in PRODUCTION_BACKTEST_MODEL_IDS

    # 2) consistency gate dispatch <-> readiness.
    assert frozenset(_BACKTEST_IMPLEMENTATIONS) == PRODUCTION_BACKTEST_MODEL_IDS

    # 3) candidates: deepar production+blocked (F05) на n_series=1;
    #    catalog-only моделей больше нет.
    response = _compute_candidates(CandidatesRequest(
        profile=_profile(), min_level="CONDITIONALLY_APPLICABLE",
    ))
    catalog = {item.model_id: item for item in response.catalog}
    deepar = catalog["deepar"]
    assert deepar.platform_status == "ready", deepar.platform_status
    assert deepar.available_actions == []
    assert deepar.blocking_reason
    assert response.statistics.runnable_candidates == 19
    assert response.statistics.catalog_only_candidates == 0
    descriptor = MODEL_EXECUTION_REGISTRY.describe("deepar")
    assert descriptor["family_id"] == "neural"
    assert descriptor["input_kind"] == "panel"
    assert descriptor["requires_related_series"] is True
    assert descriptor["engine"] == "neuralforecast"
    assert descriptor["adapter_id"] == "neuralforecast-deepar"
    from apps.api.model_impls.deepar import _resolve_max_steps

    print(
        "[1-3] catalog OK: 24 connected; deepar production+blocked (F05, "
        f"panel min_series={DEEPAR_MIN_SERIES}); бюджет обучения fold'а "
        f"max_steps={_resolve_max_steps()} (env-рычаг "
        "CISSTAT_NEURAL_MAX_STEPS или сертифицированная константа 300)"
    )

    # 4) panel-движок: реальный глобальный OOF cohort (2 fold'а, 72 точки
    #    x 5 рядов).
    from apps.api.backtesting import build_backtest_plan, run_panel_backtest_plan
    from apps.api.multivariate_contract import build_endogenous_system
    from apps.api.neural_contract import (
        NeuralTrainingConfig,
        build_exogenous_plan,
        interval_levels_for_alpha,
        neural_cohort_contract,
    )

    target = [
        100 + 0.3 * step + 5 * math.sin(2 * math.pi * step / 12)
        for step in range(72)
    ]
    related = {
        "co2": [50.0 + 0.1 * step for step in range(72)],
        "temp": [10.0 + 3.0 * math.sin(2 * math.pi * step / 12)
                 for step in range(72)],
        "load": [80.0 - 0.2 * step for step in range(72)],
        "price": [20.0 + 0.4 * step for step in range(72)],
    }
    system = build_endogenous_system(
        {"value": target, **related},
        timestamps=[
            value.isoformat()
            for value in pd.date_range("2018-01-01", periods=72, freq="MS")
        ],
    )
    validation = {
        "strategy": "expanding", "horizon": 3, "n_splits": 2, "gap": 0,
        "folds": [
            {"fold": 1, "train_start": 0, "train_end": 65, "gap_size": 0, "test_start": 66, "test_end": 68},
            {"fold": 2, "train_start": 0, "train_end": 68, "gap_size": 0, "test_start": 69, "test_end": 71},
        ],
    }
    cohort = neural_cohort_contract(
        fingerprint="task142-smoke",
        n_series=len(system.names),
        min_series=DEEPAR_MIN_SERIES,
        exogenous=build_exogenous_plan(pd.DataFrame(
            {"unique_id": [], "ds": [], "y": []})),
        interval=interval_levels_for_alpha(0.05),
        loss="mqloss",
        config=NeuralTrainingConfig(seed=42, max_steps=60),
    )
    plan = build_backtest_plan(
        validation, n_observations=len(target), fingerprint="task142-smoke",
        target_column="value", seasonal_period=12,
        series_fingerprints={"value": "task142-smoke", **{
            name: f"fp-{name}" for name in related}},
        cohort_contract_override=cohort,
    )
    assert plan.objective == "level_forecast"
    result = run_panel_backtest_plan(
        model_id="deepar", model_name="DeepAR",
        family_id="neural", system=system, plan=plan, seasonal_period=12,
    )
    assert result["status"] == "success"
    assert len(result["oof_predictions"]) == 6
    mae = result["metrics"]["mae"]
    assert mae is not None and mae >= 0
    assert result["cohort_contract"]["panel"] is True
    assert result["cohort_contract"]["n_series"] == 5
    assert result["panel"]["series_names"][0] == "value"
    assert result["execution_contract"]["model_id"] == "deepar"
    print(f"[4] panel engine OK: 2 folds, OOF=6 (target), mae={mae:.4f}")

    # 5) panel tuning: 4 trials из yaml.
    from apps.api.modeling_tuning import execute_panel_tuning_plan_with_artifacts

    spec_mod = __import__(
        "src.catalog.modeling_spec_loader", fromlist=["ModelingSpec"],
    )
    spec = spec_mod.ModelingSpec.from_yaml("rules/modeling.yaml")
    space = spec.get_model("deepar").param_space
    grid_size = math.prod(len(values) for values in space.values())
    assert grid_size == 4, grid_size
    execution = execute_panel_tuning_plan_with_artifacts(
        model_id="deepar", model_name="DeepAR", family_id="neural",
        param_space=space, system=system, plan=plan,
        seasonal_period=12, max_trials=4, metric="mae", random_state=42,
    )
    tune_response = execution.response
    assert tune_response.best_params, tune_response
    assert tune_response.n_trials >= 1
    assert tune_response.cohort_id == plan.cohort_id
    print(f"[5] panel tuning OK: {tune_response.n_trials}/{grid_size} trials, "
          f"best={tune_response.best_params}")

    # 6) cohort-изоляция: panel-cohort != univariate-cohort на тех же folds.
    univariate_plan = build_backtest_plan(
        validation, n_observations=len(target), fingerprint="task142-smoke",
        target_column="value", seasonal_period=12,
    )
    assert plan.cohort_id != univariate_plan.cohort_id
    assert plan.cohort_contract != univariate_plan.cohort_contract
    print("[6] cohort isolation OK: panel cohort_id != univariate cohort_id")

    # 7) панельный гейт честности: 4 ряда < min_series=5 -- отказ ДО фита.
    from apps.api.model_impls.deepar import _deepar_fit_predict

    short_panel = {name: values[:66] for name, values in related.items()
                   if name != "price"}
    assert len(short_panel) == 3
    try:
        _deepar_fit_predict(target[:66], 4, related_series=short_panel)
        raise AssertionError("панель из 4 рядов не должна исполняться")
    except ValueError as exc:
        assert "панель" in str(exc) and "5" in str(exc)
    print("[7] panel gate OK: 4 series < min_series=5 -> honest refusal")

    actions = available_model_actions("deepar")
    assert {"backtest", "tune", "diagnostics"} <= set(actions), actions
    print("E2E SMOKE OK")


if __name__ == "__main__":
    main()
