# tests/unit/test_multivariate_contract.py
"""Task 131 -- Multivariate Modeling Contract: RED-контур сертификационных тестов.

Требования постановки (docs/modeling_task_list.md::Task 131):
1. Явный набор endogenous-рядов вместо одной target.
2. Общая регулярная временная сетка без скрытой агрегации.
3. Fold-local стационарность всех компонент и cointegration evidence.
4. Векторные OOF-точки, метрики по каждому ряду и агрегированная scaled loss.
5. Многомерный baseline и отдельный comparison cohort.
6. Диагностика устойчивости и белого шума системы.

Все сиды/пороги подобраны эмпирической рекогносцировкой
(scripts/task131_probe.py) и детерминированы.
"""
from __future__ import annotations

import numpy as np
import pytest

from apps.api.multivariate_contract import (
    MIN_ENDOGENOUS_SERIES,
    MIN_SYSTEM_OBSERVATIONS,
    MULTIVARIATE_CONTRACT_VERSION,
    EndogenousSystem,
    MultivariateContractError,
    build_endogenous_system,
    companion_stability,
    component_stationarity,
    compute_vector_metrics,
    fold_cointegration_evidence,
    fold_stationarity_evidence,
    multivariate_cohort_contract,
    system_white_noise_diagnostics,
    validate_regular_grid,
    vector_metric_scales,
    vector_naive_baseline,
    vector_oof_points,
)
from apps.api.schemas import BacktestMetrics


NAMES = ("gdp", "inflation")


def _system(n: int = 60, seed: int = 7, timestamps: bool = False) -> EndogenousSystem:
    rng = np.random.default_rng(seed)
    series = {
        "gdp": [float(value) for value in rng.normal(size=n)],
        "inflation": [float(value) for value in rng.normal(size=n)],
    }
    if timestamps:
        stamps = [f"2024-01-{day:02d}" for day in range(1, n + 1)]
        return build_endogenous_system(series, timestamps=stamps)
    return build_endogenous_system(series)


# ---------------------------------------------------------------------------
# 1. Явный набор endogenous-рядов вместо одной target
# ---------------------------------------------------------------------------

def test_contract_version_is_stable() -> None:
    assert MULTIVARIATE_CONTRACT_VERSION == "multivariate-contract-v1"


def test_system_requires_at_least_two_endogenous_series() -> None:
    with pytest.raises(MultivariateContractError, match="не менее 2"):
        build_endogenous_system({"gdp": [1.0, 2.0, 3.0]})
    assert MIN_ENDOGENOUS_SERIES == 2


def test_system_rejects_duplicate_series_names() -> None:
    with pytest.raises(MultivariateContractError, match="дублируются"):
        build_endogenous_system({"gdp": [1.0, 2.0], "gdp ": [3.0, 4.0]})


def test_system_rejects_empty_series_name() -> None:
    with pytest.raises(MultivariateContractError, match="пуст"):
        build_endogenous_system({"gdp": [1.0, 2.0], "": [3.0, 4.0]})


def test_system_rejects_length_mismatch_between_series() -> None:
    with pytest.raises(MultivariateContractError, match="длина"):
        build_endogenous_system({
            "gdp": [1.0] * 30,
            "inflation": [1.0] * 29,
        })


def test_system_rejects_nan_or_inf_values() -> None:
    with pytest.raises(MultivariateContractError, match="NaN/Inf"):
        build_endogenous_system({"gdp": [1.0, float("nan")] + [1.0] * 28,
                                 "inflation": [1.0] * 30})
    with pytest.raises(MultivariateContractError, match="NaN/Inf"):
        build_endogenous_system({"gdp": [1.0, float("inf")] + [1.0] * 28,
                                 "inflation": [1.0] * 30})


def test_system_rejects_non_numeric_values() -> None:
    with pytest.raises(MultivariateContractError):
        build_endogenous_system({"gdp": ["x"] * 30, "inflation": [1.0] * 30})


def test_system_rejects_observations_below_platform_minimum() -> None:
    # MIN_SYSTEM_OBSERVATIONS = 20 -- согласовано с MIN_TRAIN_OBSERVATIONS
    # EDA validation strategy: ниже фолды невозможны.
    assert MIN_SYSTEM_OBSERVATIONS == 20
    with pytest.raises(MultivariateContractError, match="наблюдений"):
        build_endogenous_system({
            "gdp": [1.0] * (MIN_SYSTEM_OBSERVATIONS - 1),
            "inflation": [1.0] * (MIN_SYSTEM_OBSERVATIONS - 1),
        })


def test_system_preserves_explicit_series_order_in_matrix() -> None:
    system = build_endogenous_system({
        "zebra": [3.0] * 20,
        "alpha": [1.0] * 20,
    })
    # Порядок колонок = порядок объявления (существенен для VAR/VECM),
    # никакой скрытой сортировки.
    assert system.names == ("zebra", "alpha")
    matrix = system.matrix()
    assert matrix.shape == (20, 2)
    assert matrix[0, 0] == 3.0 and matrix[0, 1] == 1.0


def test_system_properties_expose_dimensions() -> None:
    system = _system(n=40)
    assert system.n_series == 2
    assert system.n_observations == 40
    assert system.series["gdp"][0] == system.matrix()[0, 0]


def test_system_train_and_test_slices_are_exact() -> None:
    system = _system(n=30)
    train = system.train_slice(24)
    test = system.test_slice(24, 30)
    assert train.shape == (24, 2) and test.shape == (6, 2)
    assert train[-1, 0] == system.matrix()[23, 0]
    assert test[0, 1] == system.matrix()[24, 1]


def test_system_timestamps_must_match_length() -> None:
    with pytest.raises(MultivariateContractError, match="временной оси"):
        build_endogenous_system(
            {"gdp": [1.0] * 30, "inflation": [1.0] * 30},
            timestamps=[f"2024-01-{day:02d}" for day in range(1, 30)],
        )


def test_system_without_timestamps_is_row_order_mode() -> None:
    system = _system(n=25)
    assert system.timestamps is None
    assert system.grid is None


# ---------------------------------------------------------------------------
# 2. Общая регулярная временная сетка без скрытой агрегации
# ---------------------------------------------------------------------------

def test_regular_daily_grid_accepted() -> None:
    stamps = [f"2024-01-{day:02d}" for day in range(1, 30)]
    grid = validate_regular_grid(stamps)
    assert grid["regular"] is True
    assert grid["frequency"] is not None
    assert grid["n_observations"] == 29


def test_regular_monthly_grid_accepted() -> None:
    # Календарные месяцы имеют разную длину в секундах -- регулярность
    # определяется платформенным detect_column_frequency (pd.infer_freq),
    # а не наивным равенством timedelta.
    stamps = [f"2024-{month:02d}-01" for month in range(1, 13)]
    grid = validate_regular_grid(stamps)
    assert grid["regular"] is True
    assert grid["frequency"] is not None


def test_irregular_grid_fails_closed_without_hidden_aggregation() -> None:
    stamps = ["2024-01-01", "2024-01-02", "2024-01-05", "2024-01-06",
              "2024-01-10", "2024-01-11"]
    with pytest.raises(MultivariateContractError, match="регуляриз"):
        validate_regular_grid(stamps)


def test_duplicate_timestamps_fail_closed_with_panel_message() -> None:
    stamps = ["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-03",
              "2024-01-04", "2024-01-05"]
    with pytest.raises(MultivariateContractError, match="панел"):
        validate_regular_grid(stamps)


def test_unsorted_timestamps_fail_closed() -> None:
    # Скрытая пересортировка запрещена: вход обязан быть упорядочен явно.
    stamps = ["2024-01-03", "2024-01-01", "2024-01-02", "2024-01-04",
              "2024-01-05", "2024-01-06"]
    with pytest.raises(MultivariateContractError, match="упорядочен"):
        validate_regular_grid(stamps)


def test_non_parseable_timestamps_fail_closed() -> None:
    stamps = ["2024-01-01", "not-a-date", "2024-01-03", "2024-01-04",
              "2024-01-05", "2024-01-06"]
    with pytest.raises(MultivariateContractError, match="дат"):
        validate_regular_grid(stamps)


def test_grid_with_fewer_than_three_observations_is_not_regular() -> None:
    # detect_column_frequency честно возвращает None при < 3 уникальных дат.
    with pytest.raises(MultivariateContractError, match="регуляриз"):
        validate_regular_grid(["2024-01-01", "2024-01-02"])


def test_system_rejects_irregular_grid_at_construction() -> None:
    stamps = ["2024-01-01", "2024-01-02", "2024-01-05", "2024-01-06",
              "2024-01-10", "2024-01-11"]
    with pytest.raises(MultivariateContractError, match="регуляриз"):
        build_endogenous_system(
            {"gdp": [1.0] * 6, "inflation": [1.0] * 6}, timestamps=stamps,
        )


def test_system_with_regular_grid_exposes_grid_info() -> None:
    system = _system(n=30, timestamps=True)
    assert system.grid is not None
    assert system.grid["regular"] is True
    assert system.grid["n_observations"] == 30


# ---------------------------------------------------------------------------
# 3. Fold-local стационарность всех компонент
# ---------------------------------------------------------------------------

def test_stationary_component_consensus_is_stationary() -> None:
    rng = np.random.default_rng(7)
    evidence = component_stationarity([float(v) for v in rng.normal(size=200)])
    assert evidence["available"] is True
    assert evidence["consensus"] == "stationary"
    assert evidence["adf"]["reject_null"] is True
    assert evidence["kpss"]["reject_null"] is False


def test_random_walk_component_consensus_is_non_stationary() -> None:
    rng = np.random.default_rng(7)
    walk = np.cumsum(rng.normal(size=200))
    evidence = component_stationarity([float(v) for v in walk])
    assert evidence["available"] is True
    assert evidence["consensus"] == "non-stationary"
    assert evidence["adf"]["reject_null"] is False
    assert evidence["kpss"]["reject_null"] is True


def test_stationarity_consensus_labels_mirror_eda() -> None:
    rng = np.random.default_rng(7)
    labels = {
        component_stationarity([float(v) for v in rng.normal(size=100)])["consensus"],
        component_stationarity([float(v) for v in np.cumsum(rng.normal(size=100))])["consensus"],
    }
    assert labels <= {"stationary", "non-stationary", "inconclusive"}


def test_fold_local_evidence_ignores_data_after_train_window() -> None:
    # Первые 170 наблюдений -- белый шум, последние 30 -- дрейф +200.
    # Полная система: non-stationary; train-срез: stationary.
    # Доказывает, что evidence вычисляется ТОЛЬКО на переданной матрице.
    rng = np.random.default_rng(7)
    base = rng.normal(size=200)
    ramp = np.linspace(0.0, 200.0, 30)
    full = np.concatenate([base[:170], base[170:] + ramp])
    on_train = fold_stationarity_evidence(full[:170, None] * np.ones((1, 2)), NAMES)
    on_full = fold_stationarity_evidence(full[:, None] * np.ones((1, 2)), NAMES)
    assert on_train["available"] and on_full["available"]
    assert on_train["components"]["gdp"]["consensus"] == "stationary"
    assert on_full["components"]["gdp"]["consensus"] == "non-stationary"


def test_stationarity_evidence_covers_every_component() -> None:
    system = _system(n=80)
    evidence = fold_stationarity_evidence(system.matrix(), system.names)
    assert set(evidence["components"]) == {"gdp", "inflation"}
    assert evidence["n_observations"] == 80
    assert evidence["alpha"] == 0.05


def test_constant_component_evidence_is_unavailable_not_fabricated() -> None:
    matrix = np.ones((40, 2))
    evidence = fold_stationarity_evidence(matrix, NAMES)
    assert evidence["available"] is False
    assert evidence["reason"]
    component = evidence["components"]["gdp"]
    assert component["available"] is False
    assert component["consensus"] is None


def test_stationarity_evidence_rejects_nonfinite_input() -> None:
    matrix = np.arange(40, dtype=float).reshape(40, 1) * np.ones((1, 2))
    matrix[5, 0] = np.nan
    with pytest.raises(MultivariateContractError, match="NaN/Inf"):
        fold_stationarity_evidence(matrix, NAMES)


def test_stationarity_evidence_rejects_name_mismatch() -> None:
    matrix = np.ones((40, 3))
    with pytest.raises(MultivariateContractError, match="имён"):
        fold_stationarity_evidence(matrix, ("a", "b"))


# ---------------------------------------------------------------------------
# 3b. Cointegration evidence (fold-local, Johansen)
# ---------------------------------------------------------------------------

def test_cointegrated_pair_yields_positive_rank_evidence() -> None:
    rng = np.random.default_rng(7)
    x = np.cumsum(rng.normal(size=150))
    y = 2.0 * x + rng.normal(size=150) * 0.5
    evidence = fold_cointegration_evidence(np.column_stack([x, y]))
    assert evidence["available"] is True
    assert evidence["cointegration_evidence"] is True
    assert evidence["trace"]["rank"] >= 1
    assert evidence["trace"]["statistics"][0] > evidence["trace"]["critical_values"]["95"][0]


def test_independent_random_walks_yield_zero_rank_evidence() -> None:
    # seed 42 верифицирован рекогносцировкой: независимые I(1) ряды не дают
    # ложной коинтеграции на 95% (trace < критического значения).
    rng = np.random.default_rng(42)
    a = np.cumsum(rng.normal(size=150))
    b = np.cumsum(rng.normal(size=150))
    evidence = fold_cointegration_evidence(np.column_stack([a, b]))
    assert evidence["available"] is True
    assert evidence["cointegration_evidence"] is False
    assert evidence["trace"]["rank"] == 0


def test_cointegration_evidence_binds_to_exact_train_matrix() -> None:
    # Reference-сверка: статистики модуля == прямому вызову Йохансена
    # на ТОЙ ЖЕ матрице (доказательство fold-local: функция видит только
    # переданный ей срез).
    from statsmodels.tsa.vector_ar.vecm import coint_johansen

    rng = np.random.default_rng(7)
    matrix = np.column_stack([np.cumsum(rng.normal(size=120)),
                              np.cumsum(rng.normal(size=120))])
    evidence = fold_cointegration_evidence(matrix, k_ar_diff=2, det_order=0)
    reference = coint_johansen(matrix, det_order=0, k_ar_diff=2)
    assert evidence["trace"]["statistics"] == pytest.approx(
        list(reference.lr1), rel=1e-12,
    )
    assert evidence["max_eig"]["statistics"] == pytest.approx(
        list(reference.lr2), rel=1e-12,
    )


def test_cointegration_evidence_short_fold_reports_unavailable() -> None:
    # Короткие фолды: evidence честно недоступен (асимптотика Йохансена),
    # никаких выдуманных рангов.
    rng = np.random.default_rng(7)
    matrix = np.cumsum(rng.normal(size=(22, 2)), axis=0)
    evidence = fold_cointegration_evidence(matrix, k_ar_diff=3)
    assert evidence["available"] is False
    assert evidence["reason"]
    assert evidence["trace"] is None
    assert evidence["cointegration_evidence"] is False


def test_cointegration_evidence_rejects_invalid_det_order() -> None:
    matrix = np.ones((40, 2))
    with pytest.raises(MultivariateContractError, match="det_order"):
        fold_cointegration_evidence(matrix, det_order=5)


def test_cointegration_evidence_rejects_invalid_k_ar_diff() -> None:
    matrix = np.ones((40, 2))
    with pytest.raises(MultivariateContractError, match="k_ar_diff"):
        fold_cointegration_evidence(matrix, k_ar_diff=0)
    with pytest.raises(MultivariateContractError, match="k_ar_diff"):
        fold_cointegration_evidence(matrix, k_ar_diff=13)


def test_cointegration_evidence_rejects_nonfinite_input() -> None:
    matrix = np.ones((40, 2))
    matrix[3, 1] = np.nan
    with pytest.raises(MultivariateContractError, match="NaN/Inf"):
        fold_cointegration_evidence(matrix)


def test_cointegration_evidence_rejects_single_series() -> None:
    with pytest.raises(MultivariateContractError, match="не менее 2"):
        fold_cointegration_evidence(np.ones((40, 1)))


# ---------------------------------------------------------------------------
# 4. Векторные OOF-точки
# ---------------------------------------------------------------------------

def _matrix(values: float, h: int, k: int = 2) -> np.ndarray:
    return np.full((h, k), values)


def test_vector_oof_points_long_format_keys() -> None:
    points = vector_oof_points(
        fold=1, test_indices=[30, 31, 32],
        actual_matrix=_matrix(2.0, 3), predicted_matrix=_matrix(1.0, 3),
        names=NAMES,
    )
    assert len(points) == 6  # 3 шага x 2 ряда
    expected_keys = {"fold", "horizon_step", "index", "label", "series",
                     "actual", "predicted", "residual"}
    assert all(set(point) == expected_keys for point in points)


def test_vector_oof_points_cover_every_series_and_step() -> None:
    points = vector_oof_points(
        fold=2, test_indices=[10, 11],
        actual_matrix=_matrix(5.0, 2), predicted_matrix=_matrix(4.0, 2),
        names=NAMES,
    )
    pairs = [(point["horizon_step"], point["series"]) for point in points]
    assert pairs == [(1, "gdp"), (1, "inflation"), (2, "gdp"), (2, "inflation")]
    assert {point["fold"] for point in points} == {2}
    assert [point["index"] for point in points if point["series"] == "gdp"] == [10, 11]


def test_vector_oof_residual_sign_convention_and_rounding() -> None:
    points = vector_oof_points(
        fold=1, test_indices=[7],
        actual_matrix=np.array([[1.0 / 3.0, -2.0]]),
        predicted_matrix=np.array([[0.0, -1.0]]),
        names=NAMES,
    )
    residuals = {(point["series"]): point["residual"] for point in points}
    assert residuals["gdp"] == round(1.0 / 3.0 - 0.0, 12)
    assert residuals["inflation"] == round(-2.0 - (-1.0), 12)
    # residual = actual - predicted (знак движка backtesting.py).


def test_vector_oof_labels_bound_to_grid_labels() -> None:
    points = vector_oof_points(
        fold=1, test_indices=[5, 6],
        actual_matrix=_matrix(1.0, 2), predicted_matrix=_matrix(1.0, 2),
        names=NAMES, labels=["t5", "t6"],
    )
    labels = {(point["horizon_step"], point["series"]): point["label"]
              for point in points}
    assert labels[(1, "gdp")] == "t5" and labels[(2, "gdp")] == "t6"


def test_vector_oof_points_without_labels_use_none() -> None:
    points = vector_oof_points(
        fold=1, test_indices=[5], actual_matrix=_matrix(1.0, 1),
        predicted_matrix=_matrix(1.0, 1), names=NAMES,
    )
    assert all(point["label"] is None for point in points)


def test_vector_oof_shape_mismatch_fails_closed() -> None:
    with pytest.raises(MultivariateContractError, match="длина"):
        vector_oof_points(
            fold=1, test_indices=[1, 2],
            actual_matrix=_matrix(1.0, 2), predicted_matrix=_matrix(1.0, 3),
            names=NAMES,
        )


def test_vector_oof_test_indices_must_align_with_horizon() -> None:
    with pytest.raises(MultivariateContractError, match="test_indices"):
        vector_oof_points(
            fold=1, test_indices=[1, 2, 3],
            actual_matrix=_matrix(1.0, 2), predicted_matrix=_matrix(1.0, 2),
            names=NAMES,
        )


def test_vector_oof_nan_fails_closed() -> None:
    with pytest.raises(MultivariateContractError, match="NaN/Inf"):
        vector_oof_points(
            fold=1, test_indices=[1],
            actual_matrix=np.array([[float("nan"), 1.0]]),
            predicted_matrix=_matrix(1.0, 1), names=NAMES,
        )


def test_vector_oof_duplicate_series_names_fail_closed() -> None:
    with pytest.raises(MultivariateContractError, match="дублируются"):
        vector_oof_points(
            fold=1, test_indices=[1], actual_matrix=_matrix(1.0, 1),
            predicted_matrix=_matrix(1.0, 1), names=("a", "a"),
        )


# ---------------------------------------------------------------------------
# 4b. Метрики по каждому ряду и агрегированная scaled loss
# ---------------------------------------------------------------------------

def test_per_series_metrics_closed_form() -> None:
    actual = np.array([[10.0, 100.0], [12.0, 90.0]])
    predicted = np.array([[8.0, 105.0], [12.0, 95.0]])
    result = compute_vector_metrics(actual, predicted, NAMES)
    gdp, inflation = result["per_series"]["gdp"], result["per_series"]["inflation"]
    assert isinstance(gdp, BacktestMetrics)
    assert gdp.mae == pytest.approx(1.0)
    assert gdp.rmse == pytest.approx(np.sqrt(2.0))
    # MAPE = mean(|e/a|)*100 = (20% + 0%) / 2 = 10%.
    assert gdp.mape == pytest.approx(10.0)
    assert inflation.mae == pytest.approx(5.0)
    assert inflation.rmse == pytest.approx(5.0)
    assert result["n_series"] == 2 and result["n_points"] == 2


def test_per_series_mase_uses_train_only_scale() -> None:
    # train: |diff| = 2 -> naive MAE = 2; MAE модели = 1 -> MASE = 0.5.
    train = np.array([[0.0, 100.0], [2.0, 96.0], [4.0, 92.0]])
    scales = vector_metric_scales(train, NAMES)
    assert scales["gdp"]["mase_scale"] == pytest.approx(2.0)
    actual = np.array([[6.0, 88.0]])
    predicted = np.array([[5.0, 88.0]])
    result = compute_vector_metrics(
        actual, predicted, NAMES, mase_scales={
            name: scales[name]["mase_scale"] for name in NAMES
        },
    )
    assert result["per_series"]["gdp"].mase == pytest.approx(0.5)
    # inflation: scale = 4.0 (|100-96|), MAE = 0 (прогноз точен) -> MASE 0;
    # агрегат = mean(0.5, 0.0).
    assert result["scaled_loss"] == pytest.approx(0.25)


def test_scaled_loss_is_mean_of_per_series_mase() -> None:
    train = np.array([[0.0, 0.0], [1.0, 5.0], [2.0, 10.0]])
    scales = vector_metric_scales(train, NAMES)
    actual = np.array([[3.0, 15.0], [4.0, 20.0]])
    predicted = np.array([[2.0, 14.0], [5.0, 19.0]])
    result = compute_vector_metrics(
        actual, predicted, NAMES, mase_scales={
            name: scales[name]["mase_scale"] for name in NAMES
        },
    )
    mases = [result["per_series"][name].mase for name in NAMES]
    assert all(value is not None for value in mases)
    assert result["scaled_loss"] == pytest.approx(float(np.mean(mases)))
    assert result["scaled_loss_aggregation"] == "mean_of_per_series_mase"


def test_scaled_loss_none_when_any_series_scale_undefined() -> None:
    # Константный train второй серии -> нулевая naive-ошибка -> scale None;
    # агрегат честно None (all-or-none), никакой частичной подмены.
    train = np.array([[0.0, 5.0], [2.0, 5.0], [4.0, 5.0]])
    scales = vector_metric_scales(train, NAMES)
    assert scales["inflation"]["mase_scale"] is None
    result = compute_vector_metrics(
        np.array([[6.0, 5.0]]), np.array([[5.0, 5.0]]), NAMES,
        mase_scales={name: scales[name]["mase_scale"] for name in NAMES},
    )
    assert result["per_series"]["inflation"].mase is None
    assert result["scaled_loss"] is None


def test_vector_metric_scales_match_engine_formulas() -> None:
    # Привязка к сертифицированным формулам движка (compute_metric_scales).
    from apps.api.backtesting import compute_metric_scales

    rng = np.random.default_rng(7)
    column = [float(v) for v in rng.normal(size=40)]
    train = np.column_stack([column, list(reversed(column))])
    scales = vector_metric_scales(train, NAMES, seasonal_period=3)
    for position, name in enumerate(NAMES):
        mase_ref, rmsse_ref = compute_metric_scales(
            [float(v) for v in train[:, position]], 3,
        )
        assert scales[name]["mase_scale"] == mase_ref
        assert scales[name]["rmsse_scale"] == rmsse_ref


def test_vector_metrics_match_engine_forecast_metrics() -> None:
    # Формулы на ряд == сертифицированной compute_forecast_metrics движка.
    from apps.api.backtesting import compute_forecast_metrics

    rng = np.random.default_rng(11)
    actual_col = [float(v) for v in rng.normal(size=15)]
    predicted_col = [float(v) for v in rng.normal(size=15)]
    actual = np.column_stack([actual_col, actual_col])
    predicted = np.column_stack([predicted_col, predicted_col])
    scales = {name: 1.5 for name in NAMES}
    result = compute_vector_metrics(
        actual, predicted, NAMES,
        mase_scales=scales, rmsse_scales=scales,
    )
    reference = compute_forecast_metrics(
        actual_col, predicted_col, mase_scale=1.5, rmsse_scale=1.5,
    )
    for name in NAMES:
        per_series = result["per_series"][name]
        assert per_series.mae == reference.mae
        assert per_series.rmse == reference.rmse
        assert per_series.mape == reference.mape
        assert per_series.mase == reference.mase
        assert per_series.smape == reference.smape
        assert per_series.rmsse == reference.rmsse
        assert per_series.weighted_score is None
        assert per_series.mape_valid_points == reference.mape_valid_points


def test_vector_metrics_reject_length_mismatch() -> None:
    with pytest.raises(MultivariateContractError, match="форма"):
        compute_vector_metrics(
            np.ones((3, 2)), np.ones((4, 2)), NAMES,
        )


def test_vector_metrics_reject_name_mismatch() -> None:
    with pytest.raises(MultivariateContractError, match="имён"):
        compute_vector_metrics(np.ones((3, 2)), np.ones((3, 2)), ("a",))


def test_vector_metrics_reject_nan() -> None:
    matrix = np.ones((3, 2))
    matrix[1, 0] = np.nan
    with pytest.raises(MultivariateContractError, match="NaN/Inf"):
        compute_vector_metrics(matrix, np.ones((3, 2)), NAMES)


def test_vector_metrics_reject_empty_horizon() -> None:
    with pytest.raises(MultivariateContractError, match="пуст"):
        compute_vector_metrics(np.empty((0, 2)), np.empty((0, 2)), NAMES)


# ---------------------------------------------------------------------------
# 5. Многомерный baseline
# ---------------------------------------------------------------------------

def test_baseline_persists_last_train_value_per_series() -> None:
    system = _system(n=20)
    horizon = 5
    baseline = vector_naive_baseline(system, horizon)
    assert set(baseline) == {"gdp", "inflation"}
    for position, name in enumerate(system.names):
        last = system.matrix()[-1, position]
        assert baseline[name] == (last,) * horizon


def test_baseline_horizon_length_is_exact() -> None:
    system = _system(n=20)
    assert all(len(values) == 7 for values in
               vector_naive_baseline(system, 7).values())


def test_baseline_requires_positive_horizon() -> None:
    system = _system(n=20)
    with pytest.raises(MultivariateContractError, match="horizon"):
        vector_naive_baseline(system, 0)


def test_baseline_uses_only_provided_train_slice() -> None:
    # Fold-local: baseline строится от среза системы, а не от полной истории.
    system = _system(n=30)
    train_only = system.head(24)
    baseline = vector_naive_baseline(train_only, 3)
    assert baseline["gdp"][0] == train_only.matrix()[-1, 0]
    assert baseline["gdp"][0] != system.matrix()[-1, 0]


# ---------------------------------------------------------------------------
# 5b. Отдельный comparison cohort
# ---------------------------------------------------------------------------

def test_cohort_contract_declares_multivariate_objective() -> None:
    system = _system(n=20)
    contract = multivariate_cohort_contract(
        system, series_fingerprints={name: f"fp-{name}" for name in system.names},
    )
    assert contract["objective"] == "multivariate"
    assert contract["system"]["contract_version"] == MULTIVARIATE_CONTRACT_VERSION
    assert contract["system"]["endogenous"] == ["gdp", "inflation"]


def test_cohort_contract_metric_policy_declares_vector_semantics() -> None:
    system = _system(n=20)
    contract = multivariate_cohort_contract(
        system, series_fingerprints={name: f"fp-{name}" for name in system.names},
        seasonal_period=4,
    )
    policy = contract["metric_policy"]
    assert policy["seasonal_period"] == 4
    assert policy["primary"] == "rmse"
    assert policy["vector"]["scaled_loss_aggregation"] == "mean_of_per_series_mase"
    assert "series" in policy["vector"]["oof_point_keys"]


def test_cohort_contract_includes_grid_and_feature_contract() -> None:
    system = _system(n=30, timestamps=True)
    contract = multivariate_cohort_contract(
        system, series_fingerprints={name: f"fp-{name}" for name in system.names},
    )
    assert contract["system"]["grid"]["regular"] is True
    # legacy feature-контракт отсутствует у систем без регрессоров:
    assert contract["feature_contract"] == {
        "historic": [], "future_known": [], "static": [], "policy": "none",
    }


def test_cohort_contract_validates_fingerprint_names() -> None:
    system = _system(n=20)
    with pytest.raises(MultivariateContractError, match="fingerprint"):
        multivariate_cohort_contract(
            system, series_fingerprints={"gdp": "fp", "other": "fp2"},
        )
    with pytest.raises(MultivariateContractError, match="fingerprint"):
        multivariate_cohort_contract(system, series_fingerprints={"gdp": "fp"})


def test_cohort_contract_is_deterministic() -> None:
    system = _system(n=20)
    fingerprints = {name: f"fp-{name}" for name in system.names}
    first = multivariate_cohort_contract(system, series_fingerprints=fingerprints)
    second = multivariate_cohort_contract(system, series_fingerprints=fingerprints)
    assert first == second
    other_system = _system(n=25, seed=99)
    third = multivariate_cohort_contract(
        other_system, series_fingerprints={
            name: f"fp-{name}" for name in other_system.names
        },
    )
    assert first != third


def test_different_systems_cannot_share_cohort_contract() -> None:
    left = _system(n=20, seed=1)
    right = _system(n=30, seed=2)
    left_contract = multivariate_cohort_contract(
        left, series_fingerprints={name: f"fp-{name}" for name in left.names},
    )
    right_contract = multivariate_cohort_contract(
        right, series_fingerprints={name: f"fp-{name}" for name in right.names},
    )
    assert left_contract != right_contract


def test_aligned_oof_rejects_mixed_objective_cohort() -> None:
    # Привязка разделения cohort'ов к сертифицированному движку comparison:
    # multivariate-модель не может сравниваться с univariate-моделью.
    from apps.api.modeling_comparison import ComparisonContractError, aligned_oof

    multivariate_backtest = {
        "model_id": "var", "objective": "multivariate",
        "cohort_contract": {"objective": "multivariate"},
        "oof_predictions": [{"fold": 1, "horizon_step": 1, "index": 0,
                             "label": None, "actual": 1.0, "predicted": 1.0,
                             "residual": 0.0}],
        "folds": [],
    }
    univariate_backtest = {
        **multivariate_backtest,
        "model_id": "arima", "objective": "level_forecast",
        "cohort_contract": {"objective": "level_forecast"},
    }
    with pytest.raises(ComparisonContractError):
        aligned_oof([multivariate_backtest, univariate_backtest])


# ---------------------------------------------------------------------------
# 6a. Диагностика устойчивости системы
# ---------------------------------------------------------------------------

def test_stationary_var_coefficient_is_stable() -> None:
    phi = np.array([[0.5, 0.0], [0.0, 0.3]])
    result = companion_stability([phi])
    assert result["max_modulus"] == pytest.approx(0.5)
    assert result["is_stable"] is True
    assert sorted(result["eigenvalue_moduli"]) == pytest.approx([0.3, 0.5])


def test_explosive_var_is_unstable() -> None:
    phi = np.array([[1.5, 0.0], [0.0, 0.3]])
    result = companion_stability([phi])
    assert result["max_modulus"] == pytest.approx(1.5)
    assert result["is_stable"] is False


def test_unit_circle_boundary_is_unstable_by_strict_inequality() -> None:
    result = companion_stability([np.array([[1.0]])])
    assert result["max_modulus"] == pytest.approx(1.0)
    assert result["is_stable"] is False


def test_var2_companion_matrix_shape_and_eigenvalues() -> None:
    phi1 = np.array([[0.5, 0.0], [0.0, 0.3]])
    phi2 = np.array([[0.1, 0.0], [0.0, 0.2]])
    result = companion_stability([phi1, phi2])
    # Companion-матрица VAR(2) с K=2 имеет размер 4x4; собственные значения
    # рекогносцировкой (scripts/task131_probe.py, секция 8).
    assert len(result["eigenvalue_moduli"]) == 4
    assert result["max_modulus"] == pytest.approx(0.6531128874149275)
    assert result["is_stable"] is True
    assert result["order"] == 2


def test_stability_rejects_wrong_shapes() -> None:
    with pytest.raises(MultivariateContractError, match="квадрат"):
        companion_stability([np.ones((2, 3))])
    with pytest.raises(MultivariateContractError, match="размерн"):
        companion_stability([np.eye(2), np.eye(3)])
    with pytest.raises(MultivariateContractError, match="пуст"):
        companion_stability([])


def test_stability_rejects_nonfinite() -> None:
    phi = np.eye(2)
    phi[0, 0] = np.nan
    with pytest.raises(MultivariateContractError, match="NaN/Inf"):
        companion_stability([phi])


# ---------------------------------------------------------------------------
# 6b. Диагностика белого шума системы
# ---------------------------------------------------------------------------

def test_joint_portmanteau_matches_statsmodels_oracle() -> None:
    # Независимая сверка с официальной реализацией statsmodels
    # (VARResults.test_whiteness, Lütkepohl 2005, §4.4.3).
    from statsmodels.tsa.vector_ar.var_model import VAR

    rng = np.random.default_rng(5)
    data = np.column_stack([rng.normal(size=160) for _ in range(3)])
    fitted = VAR(data).fit(2)
    residuals = np.asarray(fitted.resid)
    for adjusted in (True, False):
        mine = system_white_noise_diagnostics(
            residuals, nlags=8, fitted_var_order=2, adjusted=adjusted,
        )
        oracle = fitted.test_whiteness(nlags=8, adjusted=adjusted)
        assert mine["joint"]["statistic"] == pytest.approx(
            float(oracle.test_statistic), rel=1e-10,
        )
        assert mine["joint"]["df"] == int(oracle.df)


def test_white_noise_iid_residuals_not_rejected() -> None:
    # seed 3 верифицирован рекогносцировкой (p = 0.9587).
    rng = np.random.default_rng(3)
    residuals = rng.normal(size=(400, 2))
    result = system_white_noise_diagnostics(residuals, nlags=8)
    assert result["available"] is True
    assert result["joint"]["reject_null"] is False
    assert result["joint"]["p_value"] > 0.05
    assert result["joint"]["df"] == 2 * 2 * 8


def test_ar1_residuals_rejected_as_system_noise() -> None:
    rng = np.random.default_rng(3)
    shocks = rng.normal(size=402)
    ar = np.empty((400, 2))
    ar[0] = shocks[:2]
    for step in range(1, 400):
        ar[step] = 0.9 * ar[step - 1] + shocks[2 + step]
    result = system_white_noise_diagnostics(ar, nlags=8)
    assert result["joint"]["reject_null"] is True
    assert result["joint"]["p_value"] < 0.001


def test_per_series_ljung_box_covers_every_component() -> None:
    rng = np.random.default_rng(3)
    residuals = rng.normal(size=(300, 3))
    result = system_white_noise_diagnostics(residuals, nlags=6)
    assert len(result["per_series"]) == 3
    for position, entry in enumerate(result["per_series"]):
        assert entry["index"] == position
        assert entry["statistic"] > 0.0
        assert 0.0 <= entry["p_value"] <= 1.0
        assert entry["reject_null"] == (entry["p_value"] < 0.05)


def test_white_noise_rejects_nlags_not_exceeding_fitted_order() -> None:
    residuals = np.random.default_rng(3).normal(size=(100, 2))
    with pytest.raises(MultivariateContractError, match="nlags"):
        system_white_noise_diagnostics(residuals, nlags=4, fitted_var_order=4)


def test_white_noise_singular_covariance_fails_closed() -> None:
    with pytest.raises(MultivariateContractError, match="вырожден"):
        system_white_noise_diagnostics(np.zeros((100, 2)), nlags=4)


def test_white_noise_rejects_nonfinite_and_short_windows() -> None:
    residuals = np.random.default_rng(3).normal(size=(20, 2))
    with pytest.raises(MultivariateContractError, match="NaN/Inf"):
        dirty = residuals.copy()
        dirty[0, 0] = np.nan
        system_white_noise_diagnostics(dirty, nlags=4)
    with pytest.raises(MultivariateContractError, match="длин"):
        system_white_noise_diagnostics(residuals, nlags=30)


def test_white_noise_rejects_one_dimensional_input() -> None:
    with pytest.raises(MultivariateContractError):
        system_white_noise_diagnostics(
            np.random.default_rng(3).normal(size=100), nlags=4,
        )


def test_portmanteau_is_invariant_to_residual_centering() -> None:
    # Конвенция statsmodels._compute_acov: ковариации считаются по
    # ЦЕНТРИРОВАННЫМ остаткам.  Сдвиг уровня не должен менять статистику --
    # тест ловит удаление центрирования (на VAR-остатках с перехватом
    # выборочное среднее == 0, поэтому оракул-тест этот путь не различает).
    rng = np.random.default_rng(3)
    residuals = rng.normal(size=(300, 2)) + 7.0
    shifted = system_white_noise_diagnostics(residuals, nlags=6)
    centered = system_white_noise_diagnostics(residuals - 7.0, nlags=6)
    assert shifted["joint"]["statistic"] == pytest.approx(
        centered["joint"]["statistic"], abs=1e-9,
    )
    assert shifted["joint"]["p_value"] == pytest.approx(
        centered["joint"]["p_value"], abs=1e-12,
    )
