# tests/unit/test_volatility_engine.py
"""Task 135 -- volatility-движок: run_volatility_backtest_plan.

Зеркало run_vector_backtest_plan (Task 132) для volatility-контракта
Task 134:
- исполняет ТОЛЬКО планы objective="volatility" (гейт);
- fold-local: адаптер через реестр получает ТОЛЬКО train-префикс returns
  (проверяется перехватом registry.execute);
- OOF-точки -- VOLATILITY_OOF_POINT_KEYS: actual = realized proxy
  (squared return тест-окна), predicted = прогноз дисперсии,
  label = timestamps[i+1] (return i реализуется между t[i] и t[i+1]);
- метрики -- compute_volatility_metrics (QLIKE primary, fail-closed) +
  агрегация aggregate_volatility_metrics (взвешивание по n_test);
- baseline -- EWMA (volatility_naive_baseline) на ТЕХ ЖЕ folds, decay из
  cohort-контракта;
- диагностика fold'а -- standardized_residual_diagnostics по остаткам
  адаптера + a priori volatility_clustering_evidence train-среза.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from apps.api.backtesting import (
    BacktestExecutionError,
    build_backtest_plan,
    run_volatility_backtest_plan,
)
from apps.api.eda_validation_strategy import build_eda_validation_strategy
from apps.api.model_execution import (
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionRequest,
)
from apps.api.volatility_contract import (
    VOLATILITY_OOF_POINT_KEYS,
    build_volatility_target,
    price_to_returns,
    volatility_cohort_contract,
    volatility_naive_baseline,
)


def _garch_prices(n: int = 160, seed: int = 13) -> pd.DataFrame:
    """Ценовой ряд с кластеризацией волатильности (строго положительный)."""
    rng = np.random.default_rng(seed)
    omega, alpha, beta = 1e-6, 0.12, 0.8
    sigma2 = omega / (1.0 - alpha - beta)
    log_price = [np.log(100.0)]
    for _ in range(n - 1):
        eps = rng.standard_normal() * np.sqrt(sigma2)
        log_price.append(log_price[-1] + eps)
        sigma2 = omega + alpha * eps**2 + beta * sigma2
    return pd.DataFrame({
        "date": pd.date_range("2023-01-02", periods=n, freq="D").astype(str),
        "value": np.exp(np.asarray(log_price)),
    })


def _vol_plan(
    frame: pd.DataFrame,
    *,
    method: str = "log",
    horizon: int = 6,
    n_splits: int = 3,
    decay: float = 0.94,
):
    """Фабрика (target, plan) volatility-cohort на ЦЕЛОЙ истории frame."""
    prices = [float(v) for v in frame["value"]]
    labels = [str(v) for v in frame["date"]]
    returns = price_to_returns(prices, method=method)
    returns_frame = pd.DataFrame({"__returns__": returns}, index=pd.to_datetime(labels[1:]))
    validation = build_eda_validation_strategy(
        returns_frame.reset_index(drop=True).rename_axis(None),
        "__returns__",
        strategy="expanding", horizon=horizon, n_splits=n_splits, gap=0,
        train_window=40,
    )
    target = build_volatility_target(prices, method=method, timestamps=labels)
    cohort = volatility_cohort_contract(
        target_column="value",
        fingerprint="fp-garch-engine-test",
        returns_method=method,
        n_returns=target.n_returns,
        seasonal_period=1,
        decay=decay,
    )
    plan = build_backtest_plan(
        validation, n_observations=target.n_returns,
        fingerprint="fp-garch-engine-test", target_column="value",
        seasonal_period=1, objective="volatility",
        series_fingerprints={"value": "fp-garch-engine-test"},
        cohort_contract_override=cohort,
    )
    return target, plan


class TestEngineGates:
    def test_rejects_non_volatility_plan(self) -> None:
        target, plan = _vol_plan(_garch_prices())
        level_plan = build_backtest_plan(
            build_eda_validation_strategy(
                _garch_prices(), "value", strategy="expanding",
                horizon=6, n_splits=3, gap=0, train_window=40,
            ),
            n_observations=len(_garch_prices()),
            fingerprint="fp", target_column="value", seasonal_period=1,
        )
        with pytest.raises(BacktestExecutionError, match="volatility"):
            run_volatility_backtest_plan(
                model_id="garch", model_name="GARCH(p,q)", family_id="volatility",
                target=target, plan=level_plan, seasonal_period=1,
            )

    def test_rejects_model_with_wrong_objective(self) -> None:
        target, plan = _vol_plan(_garch_prices())
        with pytest.raises(BacktestExecutionError, match="volatility"):
            run_volatility_backtest_plan(
                model_id="naive", model_name="Naive", family_id="baselines",
                target=target, plan=plan, seasonal_period=1,
            )

    def test_rejects_seasonal_period_mismatch(self) -> None:
        target, plan = _vol_plan(_garch_prices())
        with pytest.raises(BacktestExecutionError, match="Seasonal period"):
            run_volatility_backtest_plan(
                model_id="garch", model_name="GARCH(p,q)", family_id="volatility",
                target=target, plan=plan, seasonal_period=plan.seasonal_period + 1,
            )

    def test_rejects_target_length_mismatch(self) -> None:
        target, plan = _vol_plan(_garch_prices())
        shrunk = build_volatility_target(
            [float(v) for v in _garch_prices()["value"]][:60],
            method="log",
            timestamps=[str(v) for v in _garch_prices()["date"]][:60],
        )
        with pytest.raises(BacktestExecutionError, match="расходится"):
            run_volatility_backtest_plan(
                model_id="garch", model_name="GARCH(p,q)", family_id="volatility",
                target=shrunk, plan=plan, seasonal_period=plan.seasonal_period,
            )


class TestEngineExecution:
    def test_full_run_metrics_and_cohort(self) -> None:
        frame = _garch_prices()
        target, plan = _vol_plan(frame)
        result = run_volatility_backtest_plan(
            model_id="garch", model_name="GARCH(p,q)", family_id="volatility",
            target=target, plan=plan, seasonal_period=1,
        )
        assert result["status"] == "success"
        assert result["objective"] == "volatility"
        assert result["cohort_contract"]["objective"] == "volatility"
        metrics = result["metrics"]
        for key in ("qlike", "rmse", "mae"):
            assert metrics[key] is not None and np.isfinite(metrics[key])
        # Robust-форма Паттона mean(log sv + rv/sv) законно отрицательна
        # для малых дисперсий (log sv ~ log 1e-5); fail-closed -- только
        # конечность (контракт Task 134).
        assert metrics["qlike"] < 0
        assert metrics["mape"] is None and metrics["mase"] is None
        assert result["cohort_id"] == plan.cohort_id

    def test_oof_points_contract(self) -> None:
        frame = _garch_prices()
        target, plan = _vol_plan(frame)
        result = run_volatility_backtest_plan(
            model_id="garch", model_name="GARCH(p,q)", family_id="volatility",
            target=target, plan=plan, seasonal_period=1,
        )
        points = result["oof_predictions"]
        expected_total = sum(len(fold.test_indices) for fold in plan.folds)
        assert len(points) == expected_total
        for point in points:
            assert set(point) >= set(VOLATILITY_OOF_POINT_KEYS)
            assert point["residual"] == pytest.approx(
                point["actual"] - point["predicted"], abs=1e-12,
            )
            assert point["actual"] >= 0.0  # realized proxy: квадрат return
            assert point["predicted"] > 0.0  # прогноз дисперсии
        # labels -- timestamps[i+1] (return i реализуется между t[i], t[i+1])
        stamps = list(target.timestamps)
        test_indices = set(plan.folds[-1].test_indices)
        last_fold_points = [p for p in points if p["fold"] == plan.folds[-1].fold]
        for point in last_fold_points:
            assert point["label"] == stamps[point["index"] + 1]
        # actual -- квадрат return тест-окна (бит-в-бит)
        for point in last_fold_points:
            assert point["actual"] == pytest.approx(
                float(target.returns_array[point["index"]]) ** 2, rel=1e-12,
            )
        assert test_indices

    def test_fold_local_adapter_sees_only_train_prefix(self, monkeypatch) -> None:
        """Перехват registry.execute: адаптер получает ТОЛЬКО train-срез
        returns и objective="volatility" (leakage-safety по построению)."""
        frame = _garch_prices()
        target, plan = _vol_plan(frame)
        captured: list[ModelExecutionRequest] = []
        original_execute = MODEL_EXECUTION_REGISTRY.execute

        def spy(model_id: str, request: ModelExecutionRequest):
            captured.append(request)
            return original_execute(model_id, request)

        monkeypatch.setattr(MODEL_EXECUTION_REGISTRY, "execute", spy)
        run_volatility_backtest_plan(
            model_id="garch", model_name="GARCH(p,q)", family_id="volatility",
            target=target, plan=plan, seasonal_period=1,
        )
        assert len(captured) == len(plan.folds)
        returns = target.returns_array
        for request, fold in zip(captured, plan.folds):
            assert request.objective == "volatility"
            n_train = len(fold.train_indices)
            assert len(request.target) == n_train
            assert np.array_equal(
                np.asarray(request.target, dtype=float), returns[:n_train],
            )
            assert request.horizon == fold.gap + len(fold.test_indices)

    def test_ewma_baseline_on_same_folds(self) -> None:
        """Baseline -- EWMA(cohort decay) на train-префиксе fold'а: оракул --
        независимый перерасчёт volatility_naive_baseline."""
        frame = _garch_prices()
        decay = 0.90
        target, plan = _vol_plan(frame, decay=decay)
        result = run_volatility_backtest_plan(
            model_id="garch", model_name="GARCH(p,q)", family_id="volatility",
            target=target, plan=plan, seasonal_period=1,
        )
        returns = target.returns_array
        baseline = result["volatility_baseline"]
        assert len(baseline["folds"]) == len(plan.folds)
        for fold_result, fold in zip(baseline["folds"], plan.folds):
            n_train = len(fold.train_indices)
            expected = volatility_naive_baseline(
                returns[:n_train], fold.gap + len(fold.test_indices), decay=decay,
            )
            points = [
                p for p in baseline["predictions"] if p["fold"] == fold.fold
            ]
            assert len(points) == len(fold.test_indices)
            for point, horizon_step in zip(points, range(1, len(points) + 1)):
                assert point["predicted"] == pytest.approx(
                    expected[fold.gap + horizon_step - 1], rel=1e-12,
                )
        assert baseline["aggregate"]["qlike"] is not None
        assert baseline["aggregate"]["realized_proxy"] == "squared_returns"

    def test_aggregation_weights_match_contract(self) -> None:
        frame = _garch_prices()
        target, plan = _vol_plan(frame)
        result = run_volatility_backtest_plan(
            model_id="garch", model_name="GARCH(p,q)", family_id="volatility",
            target=target, plan=plan, seasonal_period=1,
        )
        folds = result["folds"]
        weights = np.asarray([fold["n_test"] for fold in folds], dtype=float)
        qlikes = np.asarray([fold["metrics"]["qlike"] for fold in folds], dtype=float)
        expected = float(np.average(qlikes, weights=weights))
        assert result["metrics"]["qlike"] == pytest.approx(expected, abs=1e-6)
        assert result["metrics"]["realized_proxy"] == "squared_returns"
        assert result["metrics"]["primary"] == "qlike"

    def test_fold_diagnostics_present(self) -> None:
        frame = _garch_prices()
        target, plan = _vol_plan(frame)
        result = run_volatility_backtest_plan(
            model_id="garch", model_name="GARCH(p,q)", family_id="volatility",
            target=target, plan=plan, seasonal_period=1,
        )
        for fold in result["folds"]:
            diagnostics = fold["volatility_diagnostics"]
            garch_block = diagnostics["garch"]
            assert garch_block["convergence_flag"] == 0
            assert garch_block["persistence"] > 0
            assert "params" in garch_block
            evidence = diagnostics["standardized_residuals"]
            assert evidence["available"] is True
            assert "ljung_box" in evidence and "arch_lm" in evidence
            assert diagnostics["volatility_clustering_evidence"]["available"] is True

    def test_error_path_raises_backtest_execution_error(self) -> None:
        """Вырожденный target (нулевые returns невозможны -- контракты цен;
        поэтому честный отказ имитируем слишком короткой историей через
        plan с минимальным train)."""
        frame = _garch_prices(n=60)
        target, plan = _vol_plan(frame, horizon=8, n_splits=4)
        # Вручную ломаем первый fold: train-срез короче минимума адаптера.
        broken_folds = list(plan.folds)
        broken_folds[0] = type(broken_folds[0])(
            fold=broken_folds[0].fold,
            train_indices=list(range(10)),
            test_indices=broken_folds[0].test_indices,
            gap=broken_folds[0].gap,
            train_start_label=broken_folds[0].train_start_label,
            train_end_label=broken_folds[0].train_end_label,
            test_start_label=broken_folds[0].test_start_label,
            test_end_label=broken_folds[0].test_end_label,
        )
        broken_plan = replace(plan, folds=broken_folds)
        with pytest.raises(BacktestExecutionError):
            run_volatility_backtest_plan(
                model_id="garch", model_name="GARCH(p,q)", family_id="volatility",
                target=target, plan=broken_plan, seasonal_period=1,
            )
