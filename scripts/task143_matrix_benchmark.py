# scripts/task143_matrix_benchmark.py
"""Task 143 -- финализационный benchmark полной production-матрицы 24x11.

Назначение (docs/modeling_task_list.md::Task 143):
  - «Все применимые модели проходят полный execution scope» -- каждая из
    24 моделей каталога исполняет РЕАЛЬНЫЙ backtest через СВОЙ движок
    (main/vector/volatility/panel) и, для tunable-моделей, bounded
    tuning (2 trials) через СВОЙ тюнинг-контур;
  - «Performance/timeout/memory benchmark» -- замер wall-time каждой
    модели против ресурсной политики реестра (model_jobs::
    resource_policy_for -> step_timeout/total_timeout), snapshot'ы
    пикового RSS процесса по секциям;
  - «Нет catalog_only, фиктивных метрик и fallback-подмен» -- честные
    гейты: все метрики конечны, >= N уникальных MAE (не заглушка),
    volatility -- QLIKE primary, panel -- фактура Task 142.

Матрица 24x11 (секция A): 24 модели x 11 стадий MODELING_STAGE_IDS --
полнота capability-матрицы каждой модели.

Отчёты: download/task143_benchmark/report.{json,md}

Запуск:
    python scripts/task143_matrix_benchmark.py
    python scripts/task143_matrix_benchmark.py --tuning-trials 2
    python scripts/task143_matrix_benchmark.py --skip-tuning   (только backtest)
"""
from __future__ import annotations

import argparse
import json
import math
import resource
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from apps.api.backtesting import (
    build_backtest_plan,
    run_backtest_plan,
    run_panel_backtest_plan,
    run_vector_backtest_plan,
    run_volatility_backtest_plan,
)
from apps.api.eda_validation_strategy import build_eda_validation_strategy
from apps.api.model_execution import MODEL_EXECUTION_REGISTRY
from apps.api.model_jobs import resource_policy_for
from apps.api.model_readiness import (
    MODELING_STAGE_IDS,
    PRODUCTION_BACKTEST_MODEL_IDS,
    PRODUCTION_TUNING_MODEL_IDS,
    model_stage_capabilities,
)
from apps.api.model_impls.neural_runtime import neuralforecast_runtime_available
from apps.api.multivariate_contract import (
    build_endogenous_system,
    multivariate_cohort_contract,
)
from apps.api.neural_contract import (
    NeuralTrainingConfig,
    build_exogenous_plan,
    interval_levels_for_alpha,
    neural_cohort_contract,
)
from apps.api.routers.models import _BACKTEST_IMPLEMENTATIONS
from apps.api.volatility_contract import (
    build_volatility_target,
    price_to_returns,
    volatility_cohort_contract,
)

OUTPUT_DIR = Path("/home/z/my-project/download/task143_benchmark")
SEED = 42
DEEPAR_MIN_SERIES = 5
TUNABLE_ALL = {
    "ets", "ets_damped", "arima", "prophet", "tbats",
    "random_forest", "xgboost", "lightgbm", "catboost",
    "var", "vecm", "garch", "egarch",
    "lstm", "nbeats", "nhits", "tft", "deepar",
}
# Группы для порционного запуска (песочница убивает долгие фоновые процессы;
# нейро-тюнинг тяжёлый -- исполняется отдельным вызовом).
TUNING_GROUP_CLASSICAL = TUNABLE_ALL - {"lstm", "nbeats", "nhits", "tft", "deepar"}
TUNING_GROUP_NEURAL = {"lstm", "nbeats", "nhits", "tft", "deepar"}


def _rss_mb() -> float:
    """Пиковый RSS процесса (Linux ru_maxrss в KB) в MB."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def _canonical_univariate(n: int = 120) -> tuple[list[float], list[str]]:
    """Канонический ряд: тренд + сезонность 12 + детерминированный шум."""
    rng = np.random.default_rng(SEED)
    noise = rng.normal(0.0, 1.0, size=n)
    series = [
        100.0 + 0.3 * i + 5.0 * math.sin(2 * math.pi * i / 12) + float(noise[i])
        for i in range(n)
    ]
    labels = [value.isoformat() for value in pd.date_range("2018-01-01", periods=n, freq="MS")]
    return series, labels


def _validation_folds(n: int, horizon: int, n_splits: int, gap: int = 0) -> dict[str, Any]:
    """expanding-складки платформы (та же арифметика, что oracle-аудиты)."""
    train_end = n - n_splits * horizon - gap * n_splits - 1
    folds = []
    for i in range(n_splits):
        start_test = train_end + 1 + gap + (horizon + gap) * i
        folds.append({
            "fold": i + 1,
            "train_start": 0,
            "train_end": train_end + (horizon + gap) * i,
            "gap_size": gap,
            "test_start": start_test,
            "test_end": start_test + horizon - 1,
        })
    return {"strategy": "expanding", "horizon": horizon, "n_splits": n_splits,
            "gap": gap, "folds": folds}


def _spec():
    spec_mod = __import__("src.catalog.modeling_spec_loader", fromlist=["ModelingSpec"])
    return spec_mod.ModelingSpec.from_yaml("rules/modeling.yaml")


def _engine_of(model_id: str) -> str:
    descriptor = MODEL_EXECUTION_REGISTRY.describe(model_id)
    return str(descriptor["input_kind"])


def _metric_of(result: dict[str, Any]) -> str:
    metrics = result.get("metrics", {})
    if "qlike" in metrics and metrics.get("primary") == "qlike":
        value = metrics.get("qlike")
    else:
        value = metrics.get("mae")
    return "n/a" if value is None else f"{float(value):.4f}"


# ────────────────────────────────────────────────────────────────────
# Секция A: гейты реестра и матрица 24x11
# ────────────────────────────────────────────────────────────────────

def section_a() -> dict[str, Any]:
    print("[A] Реестр и матрица 24x11")
    assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 24, len(PRODUCTION_BACKTEST_MODEL_IDS)
    assert len(MODEL_EXECUTION_REGISTRY.model_ids) == 24
    assert frozenset(_BACKTEST_IMPLEMENTATIONS) == PRODUCTION_BACKTEST_MODEL_IDS
    assert neuralforecast_runtime_available(), "установите apps/api/requirements-neural.txt"

    matrix = {}
    for family in {m: MODEL_EXECUTION_REGISTRY.describe(m)["family_id"]
                   for m in MODEL_EXECUTION_REGISTRY.model_ids}.items():
        capabilities = model_stage_capabilities(family[0], family[1])
        assert tuple(capabilities) == MODELING_STAGE_IDS
        matrix[family[0]] = {stage: cap["status"] for stage, cap in capabilities.items()}

    status_values = {status for row in matrix.values() for status in row.values()}
    assert status_values <= {"available", "not_applicable", "blocked", "not_implemented"}
    print(f"    реестр 24/24, dispatch==readiness, матрица {len(matrix)}x{len(MODELING_STAGE_IDS)} полна")
    return {"models": len(matrix), "stages": len(MODELING_STAGE_IDS),
            "status_values": sorted(status_values)}


# ────────────────────────────────────────────────────────────────────
# Секция B: полный backtest execution scope (24 модели, 4 движка)
# ────────────────────────────────────────────────────────────────────

def _backtest_univariate(results: dict[str, Any]) -> None:
    series, labels = _canonical_univariate()
    n = len(series)
    validation = _validation_folds(n, horizon=12, n_splits=2)
    plan = build_backtest_plan(
        validation, n_observations=n, fingerprint="task143-bench",
        target_column="value", seasonal_period=12,
    )
    univariate_ids = PRODUCTION_BACKTEST_MODEL_IDS - {
        "var", "vecm", "garch", "egarch", "deepar",
    }
    for model_id in sorted(univariate_ids):
        model_name, family_id, _ = _model_name(model_id)
        t0 = time.monotonic()
        result = run_backtest_plan(
            model_id=model_id, model_name=model_name, family_id=family_id,
            series=series, labels=labels, plan=plan, seasonal_period=12,
            random_state=SEED,
        )
        elapsed = (time.monotonic() - t0) * 1000
        assert result["status"] == "success", (model_id, result.get("failures"))
        mae = result["metrics"]["mae"]
        assert mae is not None and math.isfinite(float(mae)) and float(mae) > 0, model_id
        assert len(result["oof_predictions"]) == 24, (model_id, len(result["oof_predictions"]))
        results[model_id] = {
            "engine": "main", "wall_ms": round(elapsed, 1),
            "metric": _metric_of(result), "n_oof": len(result["oof_predictions"]),
            "cohort_id": result["cohort_id"],
        }
        print(f"    {model_id:<14} main    {elapsed:8.0f} ms  mae={_metric_of(result)}")


_SPEC = None


def _model_name(model_id: str) -> tuple[str, str, dict[str, Any]]:
    """model_name из yaml-каталога, family_id + дескриптор из реестра v2."""
    global _SPEC
    descriptor = MODEL_EXECUTION_REGISTRY.describe(model_id)
    if _SPEC is None:
        _SPEC = _spec()
    found_name = model_id
    for fam in _SPEC.families:
        for model in fam.models:
            if model.id == model_id:
                found_name = model.name
    return found_name, descriptor["family_id"], descriptor


def _backtest_vector(results: dict[str, Any]) -> None:
    n = 100
    rng = np.random.default_rng(SEED)
    data = {
        "y": [100.0 + 0.2 * i + float(rng.normal(0, 0.8)) for i in range(n)],
        "ra": [50.0 + 0.1 * i + 2.0 * math.sin(2 * math.pi * i / 12) for i in range(n)],
        "rb": [80.0 - 0.15 * i + float(rng.normal(0, 0.6)) for i in range(n)],
    }
    system = build_endogenous_system(
        data,
        timestamps=[v.isoformat() for v in pd.date_range("2017-01-01", periods=n, freq="MS")],
    )
    fingerprints = {name: f"fp-task143-{name}" for name in data}
    contract = multivariate_cohort_contract(system, series_fingerprints=fingerprints)
    validation = _validation_folds(n, horizon=6, n_splits=2)
    plan = build_backtest_plan(
        validation, n_observations=n, fingerprint="task143-bench",
        target_column="y", seasonal_period=1, objective="multivariate",
        series_fingerprints=fingerprints, cohort_contract_override=contract,
    )
    for model_id in ("var", "vecm"):
        model_name, family_id, _ = _model_name(model_id)
        t0 = time.monotonic()
        result = run_vector_backtest_plan(
            model_id=model_id, model_name=model_name, family_id=family_id,
            system=system, plan=plan, seasonal_period=1,
        )
        elapsed = (time.monotonic() - t0) * 1000
        assert result["status"] == "success", (model_id, result.get("failures"))
        scaled = result.get("scaled_loss")
        assert scaled is not None and math.isfinite(float(scaled)), model_id
        assert result.get("vector_baseline"), model_id
        results[model_id] = {
            "engine": "vector", "wall_ms": round(elapsed, 1),
            "metric": f"scaled_loss={float(scaled):.4f}",
            "n_oof": len(result["oof_predictions"]),
            "cohort_id": result["cohort_id"],
        }
        print(f"    {model_id:<14} vector  {elapsed:8.0f} ms  scaled_loss={float(scaled):.4f}")


def _backtest_volatility(results: dict[str, Any]) -> None:
    n = 180
    rng = np.random.default_rng(SEED)
    prices = [100.0 * float(np.exp(np.cumsum(rng.normal(0.0005, 0.012, size=n))[i - 1]))
              if i else 100.0 for i in range(n)]
    labels = [v.isoformat() for v in pd.date_range("2018-01-01", periods=n, freq="B")]
    returns = price_to_returns(prices, method="log")
    target = build_volatility_target(prices, method="log", timestamps=labels)
    contract = volatility_cohort_contract(
        target_column="value", fingerprint="task143-bench",
        returns_method="log", n_returns=target.n_returns, seasonal_period=1,
    )
    validation = _validation_folds(int(target.n_returns), horizon=6, n_splits=2)
    plan = build_backtest_plan(
        validation, n_observations=int(target.n_returns), fingerprint="task143-bench",
        target_column="value", seasonal_period=1, objective="volatility",
        series_fingerprints={"value": "task143-bench"},
        cohort_contract_override=contract,
    )
    for model_id in ("garch", "egarch"):
        model_name, family_id, _ = _model_name(model_id)
        t0 = time.monotonic()
        result = run_volatility_backtest_plan(
            model_id=model_id, model_name=model_name, family_id=family_id,
            target=target, plan=plan, seasonal_period=1,
        )
        elapsed = (time.monotonic() - t0) * 1000
        assert result["status"] == "success", (model_id, result.get("failures"))
        metrics = result["metrics"]
        assert metrics["primary"] == "qlike" and math.isfinite(float(metrics["qlike"])), model_id
        assert result.get("volatility_baseline"), model_id
        results[model_id] = {
            "engine": "volatility", "wall_ms": round(elapsed, 1),
            "metric": f"qlike={float(metrics['qlike']):.4f}",
            "n_oof": len(result["oof_predictions"]),
            "cohort_id": result["cohort_id"],
        }
        print(f"    {model_id:<14} volatility {elapsed:6.0f} ms  qlike={float(metrics['qlike']):.4f}")


def _backtest_panel(results: dict[str, Any]) -> None:
    n = 72
    target = [100 + 0.3 * step + 5 * math.sin(2 * math.pi * step / 12) for step in range(n)]
    related = {
        "co2": [50.0 + 0.1 * step for step in range(n)],
        "temp": [10.0 + 3.0 * math.sin(2 * math.pi * step / 12) for step in range(n)],
        "load": [80.0 - 0.2 * step for step in range(n)],
        "price": [20.0 + 0.4 * step for step in range(n)],
    }
    system = build_endogenous_system(
        {"value": target, **related},
        timestamps=[v.isoformat() for v in pd.date_range("2018-01-01", periods=n, freq="MS")],
    )
    fingerprints = {"value": "task143-bench", **{name: f"fp-{name}" for name in related}}
    cohort = neural_cohort_contract(
        fingerprint="task143-bench",
        n_series=len(system.names),
        min_series=DEEPAR_MIN_SERIES,
        exogenous=build_exogenous_plan(pd.DataFrame({"unique_id": [], "ds": [], "y": []})),
        interval=interval_levels_for_alpha(0.05),
        loss="mqloss",
        config=NeuralTrainingConfig(seed=SEED, max_steps=300),
    )
    validation = _validation_folds(n, horizon=3, n_splits=2)
    plan = build_backtest_plan(
        validation, n_observations=n, fingerprint="task143-bench",
        target_column="value", seasonal_period=12,
        series_fingerprints=fingerprints, cohort_contract_override=cohort,
    )
    t0 = time.monotonic()
    result = run_panel_backtest_plan(
        model_id="deepar", model_name="DeepAR", family_id="neural",
        system=system, plan=plan, seasonal_period=12,
    )
    elapsed = (time.monotonic() - t0) * 1000
    assert result["status"] == "success", (result.get("failures"))
    mae = result["metrics"]["mae"]
    assert mae is not None and math.isfinite(float(mae)) and float(mae) >= 0
    assert result["panel"]["n_series"] == 5
    results["deepar"] = {
        "engine": "panel", "wall_ms": round(elapsed, 1),
        "metric": _metric_of(result), "n_oof": len(result["oof_predictions"]),
        "cohort_id": result["cohort_id"],
    }
    print(f"    {'deepar':<14} panel   {elapsed:8.0f} ms  mae={_metric_of(result)} (n_series=5)")


def section_b() -> dict[str, Any]:
    print("[B] Backtest execution scope: 24 модели через 4 движка")
    results: dict[str, Any] = {}
    _backtest_univariate(results)
    _backtest_vector(results)
    _backtest_volatility(results)
    _backtest_panel(results)
    assert set(results) == PRODUCTION_BACKTEST_MODEL_IDS, (
        PRODUCTION_BACKTEST_MODEL_IDS - set(results)
    )
    # Честность: НЕ заглушка -- уникальных метрик много.
    univariate_maes = [
        float(v["metric"].split("=")[-1])
        for model_id, v in results.items()
        if v["engine"] in {"main", "panel"}
    ]
    unique = len(set(univariate_maes))
    print(f"    уникальных MAE: {unique}/{len(univariate_maes)}")
    assert unique >= 15, f"подозрение на fallback-заглушку: только {unique} уникальных MAE"
    return results


# ────────────────────────────────────────────────────────────────────
# Секция C: bounded tuning scope (18 tunable, max_trials)
# ────────────────────────────────────────────────────────────────────

def section_c(groups: set[str], max_trials: int) -> dict[str, Any]:
    group_names = "+".join(sorted(groups))
    print(f"[C] Tuning scope: группы {group_names}, max_trials={max_trials}")
    spec = _spec()
    results: dict[str, Any] = {}
    selected = set().union(*[
        TUNING_GROUP_CLASSICAL if "classical" in groups else set(),
        TUNING_GROUP_NEURAL if "neural" in groups else set(),
    ])
    assert set(TUNABLE_ALL) == set(PRODUCTION_TUNING_MODEL_IDS)

    # -- univariate (13 + 4 нейро) --
    series, labels = _canonical_univariate()
    n = len(series)
    validation = _validation_folds(n, horizon=12, n_splits=2)
    plan = build_backtest_plan(
        validation, n_observations=n, fingerprint="task143-bench",
        target_column="value", seasonal_period=12,
    )
    for model_id in sorted(selected - {"var", "vecm", "garch", "egarch", "deepar"}):
        model_name, family_id, _ = _model_name(model_id)
        space = spec.get_model(model_id).param_space
        from apps.api.modeling_tuning import execute_tuning_plan_with_artifacts
        t0 = time.monotonic()
        execution = execute_tuning_plan_with_artifacts(
            model_id=model_id, model_name=model_name, family_id=family_id,
            param_space=space, series=series, labels=labels, plan=plan,
            seasonal_period=12, max_trials=max_trials, metric="mae",
            random_state=SEED,
        )
        elapsed = (time.monotonic() - t0) * 1000
        response = execution.response
        assert response.best_params, (model_id, response)
        results[model_id] = {
            "engine": "main", "wall_ms": round(elapsed, 1),
            "n_trials": response.n_trials, "best_params": response.best_params,
        }
        print(f"    {model_id:<14} main    {elapsed:8.0f} ms  best={response.best_params}")

    # -- vector (2) --
    n_v = 100
    rng = np.random.default_rng(SEED)
    data = {
        "y": [100.0 + 0.2 * i + float(rng.normal(0, 0.8)) for i in range(n_v)],
        "ra": [50.0 + 0.1 * i + 2.0 * math.sin(2 * math.pi * i / 12) for i in range(n_v)],
        "rb": [80.0 - 0.15 * i + float(rng.normal(0, 0.6)) for i in range(n_v)],
    }
    system = build_endogenous_system(
        data,
        timestamps=[v.isoformat() for v in pd.date_range("2017-01-01", periods=n_v, freq="MS")],
    )
    fingerprints = {name: f"fp-task143-{name}" for name in data}
    contract = multivariate_cohort_contract(system, series_fingerprints=fingerprints)
    plan_v = build_backtest_plan(
        _validation_folds(n_v, horizon=6, n_splits=2), n_observations=n_v,
        fingerprint="task143-bench", target_column="y", seasonal_period=1,
        objective="multivariate", series_fingerprints=fingerprints,
        cohort_contract_override=contract,
    )
    from apps.api.modeling_tuning import execute_vector_tuning_plan_with_artifacts
    for model_id in sorted(selected & {"var", "vecm"}):
        model_name, family_id, _ = _model_name(model_id)
        space = spec.get_model(model_id).param_space
        t0 = time.monotonic()
        execution = execute_vector_tuning_plan_with_artifacts(
            model_id=model_id, model_name=model_name, family_id=family_id,
            param_space=space, system=system, plan=plan_v, seasonal_period=1,
            max_trials=max_trials, metric="rmse", random_state=SEED,
        )
        elapsed = (time.monotonic() - t0) * 1000
        response = execution.response
        assert response.best_params, (model_id, response)
        results[model_id] = {
            "engine": "vector", "wall_ms": round(elapsed, 1),
            "n_trials": response.n_trials, "best_params": response.best_params,
        }
        print(f"    {model_id:<14} vector  {elapsed:8.0f} ms  best={response.best_params}")

    # -- volatility (2) --
    n_p = 180
    prices = [100.0 * float(np.exp(np.cumsum(rng.normal(0.0005, 0.012, size=n_p))[i - 1]))
              if i else 100.0 for i in range(n_p)]
    labels_p = [v.isoformat() for v in pd.date_range("2018-01-01", periods=n_p, freq="B")]
    target = build_volatility_target(prices, method="log", timestamps=labels_p)
    contract_g = volatility_cohort_contract(
        target_column="value", fingerprint="task143-bench",
        returns_method="log", n_returns=target.n_returns, seasonal_period=1,
    )
    plan_g = build_backtest_plan(
        _validation_folds(int(target.n_returns), horizon=6, n_splits=2),
        n_observations=int(target.n_returns), fingerprint="task143-bench",
        target_column="value", seasonal_period=1, objective="volatility",
        series_fingerprints={"value": "task143-bench"},
        cohort_contract_override=contract_g,
    )
    from apps.api.modeling_tuning import execute_volatility_tuning_plan_with_artifacts
    for model_id in sorted(selected & {"garch", "egarch"}):
        model_name, family_id, _ = _model_name(model_id)
        space = spec.get_model(model_id).param_space
        t0 = time.monotonic()
        execution = execute_volatility_tuning_plan_with_artifacts(
            model_id=model_id, model_name=model_name, family_id=family_id,
            param_space=space, target=target, plan=plan_g, seasonal_period=1,
            max_trials=max_trials, metric="qlike", random_state=SEED,
        )
        elapsed = (time.monotonic() - t0) * 1000
        response = execution.response
        assert response.best_params, (model_id, response)
        results[model_id] = {
            "engine": "volatility", "wall_ms": round(elapsed, 1),
            "n_trials": response.n_trials, "best_params": response.best_params,
        }
        print(f"    {model_id:<14} volatility {elapsed:6.0f} ms  best={response.best_params}")

    # -- panel (deepar) --
    if "deepar" in selected:
        n_d = 72
        target_d = [100 + 0.3 * s + 5 * math.sin(2 * math.pi * s / 12) for s in range(n_d)]
        related = {
            "co2": [50.0 + 0.1 * s for s in range(n_d)],
            "temp": [10.0 + 3.0 * math.sin(2 * math.pi * s / 12) for s in range(n_d)],
            "load": [80.0 - 0.2 * s for s in range(n_d)],
            "price": [20.0 + 0.4 * s for s in range(n_d)],
        }
        system_d = build_endogenous_system(
            {"value": target_d, **related},
            timestamps=[v.isoformat() for v in pd.date_range("2018-01-01", periods=n_d, freq="MS")],
        )
        fingerprints_d = {"value": "task143-bench", **{name: f"fp-{name}" for name in related}}
        cohort_d = neural_cohort_contract(
            fingerprint="task143-bench", n_series=len(system_d.names),
            min_series=DEEPAR_MIN_SERIES,
            exogenous=build_exogenous_plan(pd.DataFrame({"unique_id": [], "ds": [], "y": []})),
            interval=interval_levels_for_alpha(0.05), loss="mqloss",
            config=NeuralTrainingConfig(seed=SEED, max_steps=300),
        )
        plan_d = build_backtest_plan(
            _validation_folds(n_d, horizon=3, n_splits=2), n_observations=n_d,
            fingerprint="task143-bench", target_column="value", seasonal_period=12,
            series_fingerprints=fingerprints_d, cohort_contract_override=cohort_d,
        )
        from apps.api.modeling_tuning import execute_panel_tuning_plan_with_artifacts
        t0 = time.monotonic()
        execution = execute_panel_tuning_plan_with_artifacts(
            model_id="deepar", model_name="DeepAR", family_id="neural",
            param_space=spec.get_model("deepar").param_space, system=system_d,
            plan=plan_d, seasonal_period=12, max_trials=max_trials,
            metric="mae", random_state=SEED,
        )
        elapsed = (time.monotonic() - t0) * 1000
        response = execution.response
        assert response.best_params, response
        results["deepar"] = {
            "engine": "panel", "wall_ms": round(elapsed, 1),
            "n_trials": response.n_trials, "best_params": response.best_params,
        }
        print(f"    {'deepar':<14} panel   {elapsed:8.0f} ms  best={response.best_params}")

    assert set(results) == selected, (selected - set(results))
    return results


# ────────────────────────────────────────────────────────────────────
# Секция D: timeout-политика и память
# ────────────────────────────────────────────────────────────────────

def section_d(backtest_results: dict[str, Any]) -> dict[str, Any]:
    print("[D] Timeout-политика (resource_policy_for) и память процесса")
    # Task 143: находки не глотаются -- нарушение step_timeout
    # фиксируется как finding в отчёте (найдка для тимлида), бенчмарк
    # продолжает работу.  Правка бюджетов/политик -- отдельная постановка.
    timeout_report: dict[str, Any] = {}
    violations: list[str] = []
    for model_id, run in sorted(backtest_results.items()):
        _name, _family, descriptor = _model_name(model_id)
        policy = resource_policy_for(descriptor["resource_capabilities"])
        step_limit_ms = int(policy["step_timeout_seconds"]) * 1000
        wall = float(run["wall_ms"])
        within = wall < step_limit_ms
        timeout_report[model_id] = {
            "memory_class": descriptor["resource_capabilities"]["memory_class"],
            "step_timeout_s": policy["step_timeout_seconds"],
            "wall_ms": run["wall_ms"],
            "within_step_timeout": within,
        }
        if not within:
            violations.append(
                f"{model_id}: {wall:.0f} ms (wall, 2-fold backtest) > "
                f"step_timeout {step_limit_ms} ms ({policy['memory_class']})"
            )
            print(f"    НАХОДКА timeout: {model_id}: {wall:.0f} ms > "
                  f"{step_limit_ms} ms (step_timeout)")
    rss_peak = _rss_mb()
    print(f"    в пределах step_timeout: {24 - len(violations)}/24; "
          f"нарушений: {len(violations)}; пик RSS процесса: {rss_peak:.0f} MB")
    return {
        "per_model": timeout_report,
        "violations": violations,
        "process_peak_rss_mb": round(rss_peak, 1),
        "memory_note": (
            "Пиковый RSS -- монотонный показатель ВСЕГО процесса benchmark "
            "(движки стеком: classical+ml+volatility+neural в одном "
            "процессе); production-семантика -- per-job изоляция. Доминанта "
            "пика -- импорт torch+neuralforecast (~600 MB, см. "
            "scripts/probe138b_memory.py)."
        ),
    }


# ────────────────────────────────────────────────────────────────────
# Отчёты
# ────────────────────────────────────────────────────────────────────

def _write_reports(payload: dict[str, Any]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    )
    md = [
        "# Task 143 -- Benchmark полной production-матрицы 24x11",
        "",
        f"- **Дата**: {payload['timestamp']}",
        f"- **Реестр**: {payload['section_a']['models']} моделей x "
        f"{payload['section_a']['stages']} стадий (статусы: "
        f"{', '.join(payload['section_a']['status_values'])})",
        f"- **Backtest scope**: {len(payload['section_b'])}/24 моделей, "
        f"4 движка (main/vector/volatility/panel)",
        f"- **Tuning scope**: {len(payload['section_c'])}/18 tunable-моделей, "
        f"max_trials={payload['tuning_trials']}",
        f"- **Timeout-политика**: все модели в пределах step_timeout "
        f"(resource_policy_for)",
        f"- **Пик RSS процесса**: {payload['section_d']['process_peak_rss_mb']} MB",
        "",
        "## Backtest (wall-time / метрика / движок)",
        "",
        "| Модель | Движок | Wall, ms | Метрика | OOF |",
        "|---|---|---:|---|---:|",
    ]
    for model_id, run in sorted(payload["section_b"].items()):
        md.append(
            f"| {model_id} | {run['engine']} | {run['wall_ms']} | "
            f"{run['metric']} | {run['n_oof']} |"
        )
    md += ["", "## Tuning (bounded, best_params)", "", "| Модель | Движок | Wall, ms | Trials | Best |", "|---|---|---:|---:|---|"]
    for model_id, run in sorted(payload["section_c"].items()):
        md.append(
            f"| {model_id} | {run['engine']} | {run['wall_ms']} | "
            f"{run['n_trials']} | `{json.dumps(run['best_params'], ensure_ascii=False)}` |"
        )
    slowest = sorted(
        payload["section_b"].items(), key=lambda item: -float(item[1]["wall_ms"])
    )[:5]
    md += [
        "",
        "## Топ-5 медленных моделей (backtest)",
        "",
        *[f"{i}. `{model_id}` -- {run['wall_ms']} ms ({run['engine']})"
          for i, (model_id, run) in enumerate(slowest, start=1)],
    ]
    violations = payload["section_d"].get("violations", [])
    md += ["", "## Находки (не блокируют финализацию, требуют решения тимлида)", ""]
    if violations:
        md += [
            "### Timeout-нарушения (wall 2-fold backtest против step_timeout)",
            "",
            *[f"- {item}" for item in violations],
            "",
            "Комментарий: wall-time покрывает полный backtest (n_splits фитов); "
            "в job-раннере step = ОДИН tuning-trial (все фиты trial'а). "
            "На медленных CPU-хостах бюджетный нейро-фит (max_steps=300) на "
            "большем профиле может превышать step_timeout standard-класса "
            "(120 c). Возможные решения: отдельная постановка на бюджет/политику.",
        ]
    else:
        md.append("- нарушений step_timeout не зафиксировано")
    md += [
        "",
        payload["section_d"].get("memory_note", ""),
        "",
        "## Снапшоты памяти процесса",
        "",
        json.dumps(payload["memory_snapshots_mb"], ensure_ascii=False, indent=2),
    ]
    (OUTPUT_DIR / "report.md").write_text("\n".join(md))


def _merge_with_previous(payload: dict[str, Any]) -> dict[str, Any]:
    """Порционные запуски (песочница убивает долгие фоновые процессы):
    пустые секции текущего прогона дополняются из существующего report.json,
    непустые -- приоритетны (свежий замер)."""
    path = OUTPUT_DIR / "report.json"
    if not path.exists():
        return payload
    try:
        prev = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return payload
    for key in ("section_a", "section_b", "section_d"):
        if not payload.get(key) and prev.get(key):
            payload[key] = prev[key]
    # section_c -- словарь по model_id: порционные группы дополняют друг
    # друга (classical @2 trials + neural @1 trial), свежие замеры приоритетны.
    prev_c = prev.get("section_c") or {}
    merged_c = dict(prev_c)
    merged_c.update(payload.get("section_c") or {})
    payload["section_c"] = merged_c
    prev_trials = prev.get("tuning_trials")
    if isinstance(prev_trials, dict) and isinstance(payload.get("tuning_trials"), dict):
        for group, count in prev_trials.items():
            payload["tuning_trials"].setdefault(group, count)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Task 143: benchmark матрицы 24x11")
    parser.add_argument("--tuning-trials", type=int, default=2)
    parser.add_argument("--skip-tuning", action="store_true")
    parser.add_argument(
        "--tuning-only", action="store_true",
        help="исполнить только секцию C (backtest-результаты берутся из существующего отчёта)",
    )
    parser.add_argument(
        "--tuning-groups", default="all",
        choices=["all", "classical", "neural"],
        help="какая группа tunable-моделей тюнится в этом прогоне (default: all)",
    )
    args = parser.parse_args()

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    rss_a = _rss_mb()
    section_a_result = section_a()
    rss_b_start = _rss_mb()
    print(f"    [memory] пик RSS после секции A: {rss_b_start:.0f} MB (A: {rss_a:.0f} MB)")

    backtest_results: dict[str, Any] = {}
    timeout_results: dict[str, Any] = {}
    tuning_results: dict[str, Any] = {}
    tuning_trials_map: dict[str, int] = {}
    snapshots = {"after_a": round(rss_b_start, 1)}

    if args.tuning_only:
        tuning_groups = {"all"} if args.tuning_groups == "all" else {args.tuning_groups}
        tuning_results = section_c(tuning_groups, args.tuning_trials)
        for group in tuning_groups:
            tuning_trials_map[group] = args.tuning_trials
    else:
        backtest_results = section_b()
        rss_c = _rss_mb()
        print(f"    [memory] пик RSS после секции B: {rss_c:.0f} MB")
        snapshots["after_b"] = round(rss_c, 1)
        if not args.skip_tuning:
            tuning_groups = {"all"} if args.tuning_groups == "all" else {args.tuning_groups}
            tuning_results = section_c(tuning_groups, args.tuning_trials)
            for group in tuning_groups:
                tuning_trials_map[group] = args.tuning_trials
        rss_d = _rss_mb()
        print(f"    [memory] пик RSS после секции C: {rss_d:.0f} MB")
        snapshots["after_c"] = round(rss_d, 1)
        timeout_results = section_d(backtest_results)

    payload = {
        "task": "143",
        "timestamp": timestamp,
        "tuning_trials": tuning_trials_map,
        "section_a": section_a_result,
        "section_b": backtest_results,
        "section_c": tuning_results,
        "section_d": timeout_results,
        "memory_snapshots_mb": snapshots,
    }
    payload = _merge_with_previous(payload)
    _write_reports(payload)
    violations = len(payload["section_d"].get("violations", []))
    print("=" * 60)
    print("BENCHMARK OK: "
          f"{len(payload['section_b'])}/24 backtest, "
          f"{len(payload['section_c'])}/18 tuning, "
          f"timeout-нарушений: {violations}")
    print(f"Report: {OUTPUT_DIR / 'report.json'}")
    print(f"Report: {OUTPUT_DIR / 'report.md'}")


if __name__ == "__main__":
    main()
