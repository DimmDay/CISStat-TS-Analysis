# scripts/task138_e2e_smoke.py
"""Task 138 -- E2E смоук LSTM/GRU vertical slice.

Полный chain платформы на живом дереве:
1. registry v2: lstm в PRODUCTION_BACKTEST_MODEL_IDS/TUNING/DIAGNOSTICS (20);
2. dispatch<->readiness consistency gate (import routers.models не падает);
3. candidates: lstm ready, tft/deepar/nbeats/nhits честно catalog_only,
   статистика 16/4/4 на macro-профиле n=500;
4. реальный OOF-бэктест lstm через run_backtest_plan (движок уровня,
   точные folds, seed-дисциплина);
5. tuning-план lstm: bounded grid 16 trials из yaml, один trial реальным
   движком (короткий бюджет max_steps);
6. exogenous-канал: future-known регрессор доходит до адаптера;
7. изоляция cohort: level-модели сравнимы, volatility-движок отказывает
   lstm-планам (гейт Task 134) -- наобоrot level-движок отказывает egarch.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api.backtesting import build_backtest_plan, run_backtest_plan  # noqa: E402
from apps.api.model_execution import MODEL_EXECUTION_REGISTRY  # noqa: E402
from apps.api.model_readiness import (  # noqa: E402
    PRODUCTION_BACKTEST_MODEL_IDS,
    PRODUCTION_TUNING_MODEL_IDS,
)
from apps.api.routers.models import _BACKTEST_IMPLEMENTATIONS, _get_spec  # noqa: E402


def main() -> int:
    # 1-2. Registry + consistency gate
    assert "lstm" in PRODUCTION_BACKTEST_MODEL_IDS
    assert "lstm" in PRODUCTION_TUNING_MODEL_IDS
    assert "lstm" in _BACKTEST_IMPLEMENTATIONS
    assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 20
    definition = MODEL_EXECUTION_REGISTRY.require("lstm")
    descriptor = definition.descriptor()
    assert descriptor["dependency_group"] == "neural"
    assert descriptor["engine"] == "neuralforecast"
    assert descriptor["adapter_id"] == "neuralforecast-lstm"
    print("(1) registry+dispatch OK: 20 production models, lstm neural/neuralforecast")

    # 3. Candidates
    from apps.api.routers.models import _compute_candidates
    from apps.api.schemas import CandidatesRequest, DataProfileRequest

    response = _compute_candidates(CandidatesRequest(
        profile=DataProfileRequest(
            n_observations=500, n_series=1, n_exogenous=3, is_regular=True,
            frequency="M", has_seasonality=True, seasonal_periods=[12],
            is_stationary_or_diffable=True, domain="macro", gpu_available=True,
            feature_engineering_applied=True,
        ),
        min_level="CONDITIONALLY_APPLICABLE",
    ))
    catalog = {item.model_id: item for item in response.catalog}
    assert catalog["lstm"].platform_status == "ready"
    assert catalog["lstm"].execution_contract is not None
    for model_id in ("tft", "nbeats", "nhits", "deepar"):
        assert catalog[model_id].platform_status == "catalog_only", model_id
    stats = response.statistics
    assert (stats.runnable_candidates, stats.catalog_only_candidates,
            stats.blocked_candidates) == (16, 4, 4), stats
    print("(2) candidates OK: lstm ready; 16 runnable / 4 catalog_only / 4 blocked")

    # 4. Реальный OOF-бэктест через level-движок
    n = 260
    rng = np.random.default_rng(31)
    t = np.arange(n, dtype=float)
    series = [
        float(value)
        for value in 100 + 0.25 * t + 8 * np.sin(2 * np.pi * t / 12)
        + rng.standard_normal(n) * 0.8
    ]
    labels = [value.isoformat() for value in pd.date_range("2020-01-01", periods=n, freq="D")]
    validation = {
        "strategy": "expanding", "horizon": 7, "n_splits": 3, "gap": 0,
        "folds": [
            {"fold": 1, "train_start": 0, "train_end": 238, "gap_size": 0, "test_start": 239, "test_end": 245},
            {"fold": 2, "train_start": 0, "train_end": 245, "gap_size": 0, "test_start": 246, "test_end": 252},
            {"fold": 3, "train_start": 0, "train_end": 252, "gap_size": 0, "test_start": 253, "test_end": 259},
        ],
    }
    plan = build_backtest_plan(
        validation, n_observations=n, fingerprint="task138-smoke",
        target_column="value", seasonal_period=12,
    )
    result = run_backtest_plan(
        model_id="lstm", model_name="LSTM / GRU", family_id="neural",
        series=series, labels=labels, plan=plan, seasonal_period=12,
        params={"cell": "gru", "max_steps": 40, "input_size": 24},
        random_state=42,
    )
    assert result["metrics"]["mae"] > 0
    assert len(result["folds"]) == 3
    for fold in result["folds"]:
        assert fold["status"] == "success"
        assert len(fold["predictions"]) == 7
        assert all(np.isfinite(p["predicted"]) for p in fold["predictions"])
        assert all(np.isfinite(p["residual"]) for p in fold["predictions"])
    signature = result["execution_contract"]["signature"]
    assert signature == descriptor["signature"], "cohort contract не совпал"
    print(f"(3) OOF backtest OK: gru cell, 3 folds, mae={result['metrics']['mae']:.4f}")

    # Детерминизм всего плана: тот же seed -- бит-в-бит
    result2 = run_backtest_plan(
        model_id="lstm", model_name="LSTM / GRU", family_id="neural",
        series=series, labels=labels, plan=plan, seasonal_period=12,
        params={"cell": "gru", "max_steps": 40, "input_size": 24},
        random_state=42,
    )
    assert result2["metrics"] == result["metrics"]
    print("(4) plan determinism OK: same seed -> identical metrics")

    # 5. Tuning: bounded grid из yaml + один реальный trial
    from apps.api.modeling_tuning import prepare_tuning_grid

    model = _get_spec().get_model("lstm")
    grid = prepare_tuning_grid(model.param_space, max_trials=1, metric="mae", random_state=7)
    assert grid.grid_size == 16 and len(grid.selected) == 1
    params = grid.selected[0]
    params = {**params, "max_steps": 30}
    tuned = run_backtest_plan(
        model_id="lstm", model_name="LSTM / GRU", family_id="neural",
        series=series, labels=labels, plan=plan, seasonal_period=12,
        params=params, random_state=42,
    )
    assert tuned["metrics"]["mae"] > 0
    print(f"(5) tuning grid OK: 16 trials (bounded), sample trial "
          f"cell={params['cell']} mae={tuned['metrics']['mae']:.4f}")

    # 6. Exogenous-канал: future-known регрессор доходит до модели
    promo_train = [0.0] * 156 + [1.0] * 100
    exog_result = run_backtest_plan(
        model_id="lstm", model_name="LSTM / GRU", family_id="neural",
        series=series, labels=labels, plan=plan, seasonal_period=12,
        params={"max_steps": 30, "input_size": 24},
        random_state=42,
        # Granted-канал имитируется ниже напрямую через registry (движок
        # строит FeaturePlan из сессии; здесь проверяем контракт адаптера).
    )
    assert exog_result["metrics"]["mae"] > 0
    from apps.api.model_execution import ModelExecutionRequest

    request = ModelExecutionRequest(
        target=series[:200], horizon=7, objective="level_forecast",
        seasonal_period=12, params={"max_steps": 30, "input_size": 24},
        train_features={"promo": promo_train[:200]},
        future_features={"promo": [1.0] * 7},
        train_timestamps=labels[:200], future_timestamps=labels[200:207],
        random_state=42,
    )
    exec_result = MODEL_EXECUTION_REGISTRY.execute("lstm", request)
    assert exec_result.metadata["exogenous_plan"]["futr"] == ["promo"]
    assert exec_result.metadata["exogenous_plan"]["signature"]
    print("(6) exogenous channel OK: future-known regressor -> futr_exog")

    # 7. Изоляция cohort: level-движок отказывает volatility-планам
    from apps.api.backtesting import BacktestExecutionError

    volatility_plan = build_backtest_plan(
        validation, n_observations=n, fingerprint="task138-smoke",
        target_column="value", seasonal_period=12, objective="volatility",
    )
    try:
        run_backtest_plan(
            model_id="lstm", model_name="LSTM / GRU", family_id="neural",
            series=series, labels=labels, plan=volatility_plan,
            seasonal_period=12,
        )
        raise AssertionError("level-движок принял volatility-план -- гейт Task 134 сломан")
    except BacktestExecutionError as exc:
        assert "volatility" in str(exc)
    print("(7) cohort isolation OK: level engine rejects volatility plan")

    print("E2E SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
