# tests/unit/test_var_backtest.py
"""Task 132 -- VAR: векторная интеграция движка (run_vector_backtest_plan).

Требования серии «Многомерные модели» (Task 131 contract + Task 132 VAR):
- fold-local исполнение EndogenousSystem на точных EDA-folds;
- векторные OOF-точки (long-format с размерностью series) и per-series
  метрики с агрегированной scaled loss (all-or-none);
- многомерный persistence-baseline на ТЕХ ЖЕ folds (fold-local);
- отдельный multivariate cohort (система блок Task 131 в cohort_contract);
- fold-local диагностика: порядок лага, стационарность, коинтеграция,
  companion-устойчивость и белый шум системы;
- нулевая утечка: будущее системы недостижимо из fold-прогнозов.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from statsmodels.tsa.vector_ar.var_model import VAR

from apps.api.backtesting import (
    BacktestExecutionError,
    build_backtest_plan,
    run_vector_backtest_plan,
)
from apps.api.modeling_comparison import ComparisonContractError, aligned_oof
from apps.api.multivariate_contract import (
    MultivariateContractError,
    build_endogenous_system,
    compute_vector_metrics,
    multivariate_cohort_contract,
    vector_metric_scales,
)


NAMES = ("y", "b", "c")


def _system_matrix(n: int = 120, seed: int = 7) -> np.ndarray:
    """Стационарная VAR(1)-система K=3 с перекрёстными связями."""
    rng = np.random.default_rng(seed)
    eps = rng.normal(size=(n, 3))
    out = np.zeros((n, 3))
    for t in range(1, n):
        out[t] = 0.5 * out[t - 1] + eps[t] + 0.2 * np.roll(out[t - 1], 1)
    return out


def _related(matrix: np.ndarray) -> dict[str, list[float]]:
    return {
        name: [float(v) for v in matrix[:, position]]
        for position, name in enumerate(NAMES[1:], start=1)
    }


def _labels(n: int) -> list[str]:
    return [
        stamp.strftime("%Y-%m-%d")
        for stamp in pd.date_range("2020-01-01", periods=n, freq="D")
    ]


def _validation(n_splits: int = 2, horizon: int = 3, gap: int = 0, n: int = 120):
    folds = []
    train_end = n - n_splits * horizon - gap * n_splits - 1
    for index in range(n_splits):
        start_test = train_end + 1 + gap + (horizon + gap) * index
        folds.append({
            "fold": index + 1, "train_start": 0, "train_end": train_end + (horizon + gap) * index,
            "gap_size": gap, "test_start": start_test, "test_end": start_test + horizon - 1,
        })
    return {"strategy": "expanding", "horizon": horizon, "n_splits": n_splits,
            "gap": gap, "folds": folds}


def _fingerprints(matrix: np.ndarray, labels: list[str]) -> dict[str, str]:
    import pandas as pd

    from app.core.passport import series_fingerprint

    return {
        name: series_fingerprint(
            pd.Series([float(v) for v in matrix[:, position]], index=labels),
        )
        for position, name in enumerate(NAMES)
    }


def _run(matrix: np.ndarray | None = None, horizon: int = 3, n_splits: int = 2,
         gap: int = 0, params: dict | None = None, seed: int = 7):
    matrix = _system_matrix(seed=seed) if matrix is None else matrix
    labels = _labels(len(matrix))
    system = build_endogenous_system(
        {name: [float(v) for v in matrix[:, position]]
         for position, name in enumerate(NAMES)},
        timestamps=labels,
    )
    fingerprints = _fingerprints(matrix, labels)
    contract = multivariate_cohort_contract(
        system, series_fingerprints=fingerprints,
    )
    plan = build_backtest_plan(
        _validation(n_splits=n_splits, horizon=horizon, gap=gap, n=len(matrix)),
        n_observations=len(matrix), fingerprint="fp-var",
        target_column=NAMES[0], seasonal_period=1,
        objective="multivariate", series_fingerprints=fingerprints,
        cohort_contract_override=contract,
    )
    result = run_vector_backtest_plan(
        model_id="var", model_name="VAR", family_id="multivariate",
        system=system, plan=plan, seasonal_period=1,
        params=params or {},
    )
    return result, matrix, system, plan


# ---------------------------------------------------------------------------
# Базовая геометрия векторного прогона
# ---------------------------------------------------------------------------

def test_vector_run_executes_every_fold_with_long_oof_points() -> None:
    result, matrix, system, plan = _run()
    assert result["status"] == "success"
    assert result["objective"] == "multivariate"
    assert len(result["folds"]) == 2
    # OOF: каждая точка тест-горизонта каждой серии, long-format.
    assert len(result["oof_predictions"]) == 2 * 3 * len(NAMES)
    keys = {(point["horizon_step"], point["series"])
            for point in result["oof_predictions"]}
    assert keys == {(step, name) for step in (1, 2, 3) for name in NAMES}


def test_oof_points_carry_engine_schema_plus_series() -> None:
    result, *_ = _run()
    expected = {"fold", "horizon_step", "index", "label", "series",
                "actual", "predicted", "residual"}
    assert all(set(point) == expected for point in result["oof_predictions"])
    first = result["oof_predictions"][0]
    assert first["fold"] == 1 and first["horizon_step"] == 1
    assert first["series"] == NAMES[0]
    assert first["residual"] == round(first["actual"] - first["predicted"], 12)


def test_oof_points_bind_to_exact_system_values() -> None:
    result, matrix, system, plan = _run()
    for point in result["oof_predictions"]:
        position = NAMES.index(point["series"])
        assert point["actual"] == pytest.approx(
            matrix[point["index"], position], abs=1e-12,
        )
        assert point["label"] == _labels(len(matrix))[point["index"]]


def test_gap_steps_are_forecast_but_excluded_from_oof_scoring() -> None:
    result, matrix, system, plan = _run(gap=2)
    assert result["gap"] == 2
    for fold in result["folds"]:
        # OOF-очки только тест-горизонт; gap-шаги исполнены, но не скорятся.
        assert {point["horizon_step"] for point in
                [p for p in fold["predictions"]]} == {1, 2, 3}
        assert max(point["index"] for point in fold["predictions"]) == fold["test_end"]


def test_oof_predictions_bind_to_adapter_forecast_with_gap() -> None:
    """Прямой binding при gap>0 (аудит Task 132, проба M3):

    OOF-прогноз шага h обязан совпадать бит-в-бит с forecast[gap+h]
    адаптера, вызванным на ТОЧНОМ train-префиксе fold'а.  Раньше привязки
    исполнялись только при gap=0, и мутация «движок не отбрасывает
    gap-шаги» выживала во всём наборе.  Исполнение горизонта как
    gap+n_test с отбрасыванием gap-строк фиксирует семантику напрямую.
    """
    from apps.api.model_impls.var import _var_fit_predict

    result, matrix, system, plan = _run(gap=2, params={"maxlags": 3, "ic": None})
    for fold in result["folds"]:
        n_train = fold["n_train"]
        prefix = system.matrix()[:n_train]
        payload = _var_fit_predict(
            [float(v) for v in prefix[:, 0]],
            fold["gap"] + fold["n_test"],
            related_series={
                name: [float(v) for v in prefix[:, position]]
                for position, name in enumerate(NAMES[1:], start=1)
            },
            params={"maxlags": 3, "ic": None},
        )
        scored = np.asarray(payload["forecast"], dtype=float)[fold["gap"]:, :]
        assert scored.shape == (fold["n_test"], len(NAMES))
        for point in fold["predictions"]:
            position = NAMES.index(point["series"])
            assert point["predicted"] == pytest.approx(
                scored[point["horizon_step"] - 1, position], abs=1e-12,
            )


# ---------------------------------------------------------------------------
# Метрики: per-series + scaled loss (all-or-none) + агрегаты
# ---------------------------------------------------------------------------

def test_fold_per_series_metrics_bind_to_contract_formulas() -> None:
    result, matrix, system, plan = _run()
    for fold in result["folds"]:
        n_train = fold["n_train"]
        train_matrix = system.matrix()[:n_train]
        actual = system.matrix()[fold["test_start"]:fold["test_end"] + 1]
        predicted = np.column_stack([
            [point["predicted"] for point in fold["predictions"]
             if point["series"] == name]
            for name in NAMES
        ])
        scales = vector_metric_scales(train_matrix, NAMES)
        reference = compute_vector_metrics(
            actual, predicted, NAMES,
            mase_scales={name: scales[name]["mase_scale"] for name in NAMES},
            rmsse_scales={name: scales[name]["rmsse_scale"] for name in NAMES},
        )
        for name in NAMES:
            assert fold["per_series_metrics"][name]["mae"] == \
                reference["per_series"][name].mae
            assert fold["per_series_metrics"][name]["rmse"] == \
                reference["per_series"][name].rmse
        assert fold["scaled_loss"] == pytest.approx(reference["scaled_loss"])


def test_scaled_loss_is_all_or_none_when_series_scale_degenerate() -> None:
    # Константная endogenous-серия: statsmodels отказывается фитовать
    # (константная колонка при trend='c' -- library-native fail-closed),
    # ошибку fold'а нельзя подменять частично-деградированными метриками.
    matrix = _system_matrix()
    matrix[:, 2] = 5.0
    with pytest.raises(BacktestExecutionError, match="fold 1"):
        _run(matrix=matrix)


def test_constant_series_fails_closed_like_library() -> None:
    # Deliberate: contract-level all-or-none для scale=None связан тестом
    # Task 131 (test_scaled_loss_none_when_any_series_scale_undefined);
    # движок честно отказывается исполнять вырожденную систему.
    matrix = _system_matrix()
    matrix[:, 1] = 3.0
    with pytest.raises(BacktestExecutionError):
        _run(matrix=matrix)


def test_aggregate_metrics_pool_all_oof_points() -> None:
    result, *_ = _run()
    residuals = [abs(point["residual"]) for point in result["oof_predictions"]]
    assert result["metrics"]["mae"] == pytest.approx(
        float(np.mean(residuals)), abs=1e-6,
    )
    assert result["n_test"] == len(result["oof_predictions"])
    assert set(result["per_series_metrics"]) == set(NAMES)


# ---------------------------------------------------------------------------
# Многомерный baseline (persistence) на тех же folds
# ---------------------------------------------------------------------------

def test_vector_baseline_is_fold_local_persistence() -> None:
    result, matrix, system, plan = _run()
    for fold in result["folds"]:
        baseline = fold["vector_baseline"]
        assert baseline["fold"] == fold["fold"]
        n_train = fold["n_train"]
        for position, name in enumerate(NAMES):
            expected_last = system.matrix()[n_train - 1, position]
            baseline_series = baseline["per_series_metrics"][name]
            # Persistence-прогноз совпадает с последним train-значением.
            points = [point for point in baseline["predictions"]
                      if point["series"] == name]
            assert all(
                point["predicted"] == pytest.approx(expected_last, abs=1e-12)
                for point in points
            )
        assert baseline["metrics"]["mae"] > 0.0


def test_vector_baseline_aggregate_present_at_top_level() -> None:
    result, *_ = _run()
    baseline = result["vector_baseline"]
    assert set(baseline) >= {"aggregate", "folds", "scaled_loss"}
    assert len(baseline["folds"]) == 2
    assert baseline["aggregate"]["mae"] > 0.0


# ---------------------------------------------------------------------------
# Отдельный multivariate cohort (Task 131 contract)
# ---------------------------------------------------------------------------

def test_cohort_contract_carries_system_block_and_fingerprints() -> None:
    result, matrix, system, plan = _run()
    contract = result["cohort_contract"]
    assert contract["objective"] == "multivariate"
    assert contract["system"]["endogenous"] == list(NAMES)
    assert contract["system"]["n_observations"] == len(matrix)
    assert contract["system"]["grid"]["regular"] is True
    assert set(contract["series_fingerprints"]) == set(NAMES)


def test_different_systems_produce_different_cohorts() -> None:
    first, *_ = _run(seed=7)
    second, *_ = _run(seed=99)
    assert first["cohort_id"] != second["cohort_id"]


def test_aligned_oof_compares_two_var_runs_without_collisions() -> None:
    # Векторные точки РАЗНЫХ серий не должны коллизировать в aligned_oof.
    first, *_ = _run(seed=7, params={"maxlags": 2, "ic": None})
    second, *_ = _run(seed=7, params={"maxlags": 3, "ic": None})
    keys, residuals = aligned_oof([first, second])
    assert len(keys) == len(first["oof_predictions"])
    # Ключи различают серии: число точек сохраняется без дублей.
    assert len(set(keys)) == len(keys)


def test_aligned_oof_rejects_mixed_univariate_vector_cohort() -> None:
    vector_result, *_ = _run(seed=7)
    univariate = {
        **vector_result,
        "model_id": "arima",
        "objective": "level_forecast",
        "cohort_contract": {"objective": "level_forecast"},
    }
    with pytest.raises(ComparisonContractError):
        aligned_oof([vector_result, univariate])


# ---------------------------------------------------------------------------
# Нулевая утечка (fold-locality)
# ---------------------------------------------------------------------------

def test_forecast_depends_only_on_train_prefix() -> None:
    # Основная проверка утечки -- test_leakage_probe_identical_prefix ниже;
    # здесь фиксируем инвариант плана: train-срезы -- строгие префиксы системы.
    result, matrix, system, plan = _run()
    for fold in result["folds"]:
        assert fold["train_start"] == 0
        assert fold["train_end"] == fold["n_train"] - 1
        assert fold["n_train"] < len(matrix)


def test_leakage_probe_identical_prefix_identical_fold_one() -> None:
    # Система A: полная история. Система B: та же история на [0, train_end]
    # первого fold, а после -- другой ряд. Прогноз fold 1 обязан совпасть.
    matrix = _system_matrix(seed=7)
    labels = _labels(len(matrix))
    validation = _validation(n_splits=2, horizon=3, gap=0, n=len(matrix))
    train_end_first = validation["folds"][0]["train_end"]

    system_a = build_endogenous_system(
        {name: [float(v) for v in matrix[:, position]] for position, name in enumerate(NAMES)},
        timestamps=labels,
    )
    polluted = matrix.copy()
    polluted[train_end_first + 1:, :] += 25.0  # всё ПОСЛЕ train-среза первого fold
    system_b = build_endogenous_system(
        {name: [float(v) for v in polluted[:, position]] for position, name in enumerate(NAMES)},
        timestamps=labels,
    )

    fingerprints_a = _fingerprints(matrix, labels)
    plan_a = build_backtest_plan(
        validation, n_observations=len(matrix), fingerprint="fp-a",
        target_column=NAMES[0], seasonal_period=1,
        objective="multivariate", series_fingerprints=fingerprints_a,
        cohort_contract_override=multivariate_cohort_contract(
            system_a, series_fingerprints=fingerprints_a,
        ),
    )
    fingerprints_b = _fingerprints(polluted, labels)
    plan_b = build_backtest_plan(
        validation, n_observations=len(polluted), fingerprint="fp-b",
        target_column=NAMES[0], seasonal_period=1,
        objective="multivariate", series_fingerprints=fingerprints_b,
        cohort_contract_override=multivariate_cohort_contract(
            system_b, series_fingerprints=fingerprints_b,
        ),
    )
    result_a = run_vector_backtest_plan(
        model_id="var", model_name="VAR", family_id="multivariate",
        system=system_a, plan=plan_a, seasonal_period=1, params={"maxlags": 2, "ic": None},
    )
    result_b = run_vector_backtest_plan(
        model_id="var", model_name="VAR", family_id="multivariate",
        system=system_b, plan=plan_b, seasonal_period=1, params={"maxlags": 2, "ic": None},
    )
    forecasts_a = [(p["series"], p["index"], p["predicted"])
                   for p in result_a["folds"][0]["predictions"]]
    forecasts_b = [(p["series"], p["index"], p["predicted"])
                   for p in result_b["folds"][0]["predictions"]]
    assert forecasts_a == forecasts_b


# ---------------------------------------------------------------------------
# Fold-local диагностика VAR
# ---------------------------------------------------------------------------

def test_fold_diagnostics_bind_lag_order_to_statsmodels_oracle() -> None:
    result, matrix, system, plan = _run(params={"maxlags": 5, "ic": "aic"})
    for fold in result["folds"]:
        diagnostics = fold["multivariate_diagnostics"]
        train_matrix = system.matrix()[:fold["n_train"]]
        reference = VAR(train_matrix).fit(maxlags=5, ic="aic")
        assert diagnostics["var"]["lag_order"] == reference.k_ar
        assert diagnostics["var"]["is_stable"] is True


def test_fold_diagnostics_cover_stationarity_cointegration_whitenoise() -> None:
    result, matrix, system, plan = _run(params={"maxlags": 3, "ic": None})
    for fold in result["folds"]:
        diagnostics = fold["multivariate_diagnostics"]
        assert set(diagnostics) >= {
            "stationarity_evidence", "cointegration_evidence",
            "companion_stability", "white_noise",
        }
        assert set(diagnostics["stationarity_evidence"]["components"]) == set(NAMES)
        assert diagnostics["stationarity_evidence"]["available"] in {True, False}
        wn = diagnostics["white_noise"]
        assert wn["joint"]["df"] == len(NAMES) ** 2 * (wn["joint"]["nlags"] - diagnostics["var"]["lag_order"])


def test_white_noise_rejects_iid_residuals_less_often_than_ar1() -> None:
    # Санити-сигнал: у стационарной VAR(1)-системы остатки близки к белому шуму.
    result, *_ = _run(seed=7, params={"maxlags": 2, "ic": None})
    fold = result["folds"][0]
    assert fold["multivariate_diagnostics"]["white_noise"]["available"] is True


# ---------------------------------------------------------------------------
# Fail-closed интеграция
# ---------------------------------------------------------------------------

def test_irregular_grid_fails_closed() -> None:
    matrix = _system_matrix()
    # Нерегулярная сетка той же длины: 2 даты удалены, 2 добавлены в хвост.
    stamps = pd.date_range("2020-01-01", periods=len(matrix) + 2, freq="D")
    stamps = stamps.delete(5)  # дыра в сетке
    stamps = stamps.delete(9)
    labels = [stamp.strftime("%Y-%m-%d") for stamp in stamps]
    assert len(labels) == len(matrix)
    with pytest.raises(MultivariateContractError, match="регуляр"):
        build_endogenous_system(
            {name: [float(v) for v in matrix[:, position]] for position, name in enumerate(NAMES)},
            timestamps=labels,
        )


def test_univariate_objective_plan_is_rejected() -> None:
    matrix = _system_matrix()
    labels = _labels(len(matrix))
    system = build_endogenous_system(
        {name: [float(v) for v in matrix[:, position]] for position, name in enumerate(NAMES)},
        timestamps=labels,
    )
    fingerprints = _fingerprints(matrix, labels)
    plan = build_backtest_plan(
        _validation(n=len(matrix)), n_observations=len(matrix), fingerprint="fp",
        target_column=NAMES[0], seasonal_period=1,
        series_fingerprints=fingerprints,
    )
    with pytest.raises(BacktestExecutionError, match="multivariate"):
        run_vector_backtest_plan(
            model_id="var", model_name="VAR", family_id="multivariate",
            system=system, plan=plan, seasonal_period=1,
        )


def test_too_short_system_fails_closed() -> None:
    matrix = _system_matrix(n=25)
    labels = _labels(len(matrix))
    with pytest.raises((MultivariateContractError, BacktestExecutionError)):
        system = build_endogenous_system(
            {name: [float(v) for v in matrix[:, position]] for position, name in enumerate(NAMES)},
            timestamps=labels,
        )
        fingerprints = _fingerprints(matrix, labels)
        plan = build_backtest_plan(
            _validation(n=len(matrix), horizon=3, n_splits=2),
            n_observations=len(matrix), fingerprint="fp",
            target_column=NAMES[0], seasonal_period=1,
            objective="multivariate", series_fingerprints=fingerprints,
            cohort_contract_override=multivariate_cohort_contract(
                system, series_fingerprints=fingerprints,
            ),
        )
        run_vector_backtest_plan(
            model_id="var", model_name="VAR", family_id="multivariate",
            system=system, plan=plan, seasonal_period=1,
        )


def test_fold_train_indices_must_be_contiguous_prefix() -> None:
    # VAR требует упорядоченный непрерывный train-срез; дырявый train fail-closed.
    matrix = _system_matrix()
    labels = _labels(len(matrix))
    system = build_endogenous_system(
        {name: [float(v) for v in matrix[:, position]] for position, name in enumerate(NAMES)},
        timestamps=labels,
    )
    fingerprints = _fingerprints(matrix, labels)
    validation = _validation(n=len(matrix))
    validation["folds"][0]["train_indices_hack"] = True
    plan = build_backtest_plan(
        validation, n_observations=len(matrix), fingerprint="fp",
        target_column=NAMES[0], seasonal_period=1,
        objective="multivariate", series_fingerprints=fingerprints,
        cohort_contract_override=multivariate_cohort_contract(
            system, series_fingerprints=fingerprints,
        ),
    )
    # Сдвигаем train_indices: делаем не-префикс (удаляем индекс 0 и добавляем
    # первый тестовый) -- движок обязан отклонить.
    fold = plan.folds[0]
    fold.train_indices = list(range(1, len(fold.train_indices) + 1))
    with pytest.raises(BacktestExecutionError, match="непрерывн"):
        run_vector_backtest_plan(
            model_id="var", model_name="VAR", family_id="multivariate",
            system=system, plan=plan, seasonal_period=1,
        )


def test_execution_contract_is_var_adapter() -> None:
    result, *_ = _run()
    assert result["execution_contract"]["model_id"] == "var"
    assert result["execution_contract"]["adapter_id"] == "statsmodels-var"
    assert result["execution_contract"]["objective"] == "multivariate"


def test_tuned_params_flow_into_adapter() -> None:
    result, *_ = _run(params={"maxlags": 2, "ic": None})
    for fold in result["folds"]:
        assert fold["multivariate_diagnostics"]["var"]["lag_order"] == 2


def test_aggregate_mase_is_test_size_weighted_across_folds() -> None:
    # Неравные n_test: агрегат MASE обязан быть взвешенным по n_test средним
    # fold-значений (зеркало _aggregate_metrics univariate-движка).
    from apps.api.backtesting import _aggregate_vector_metrics

    folds = [
        {"predictions": [], "n_test": 9,
         "metrics": {"mase": 1.0, "rmsse": 2.0}},
        {"predictions": [], "n_test": 3,
         "metrics": {"mase": 3.0, "rmsse": 6.0}},
    ]
    aggregate = _aggregate_vector_metrics(folds)
    assert aggregate.mase == pytest.approx((1.0 * 9 + 3.0 * 3) / 12)
    assert aggregate.rmsse == pytest.approx(
        float(np.sqrt((2.0 ** 2 * 9 + 6.0 ** 2 * 3) / 12)),
    )
