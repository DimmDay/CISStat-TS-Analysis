# tests/unit/test_final_fit.py
# TDD RED: финальный рефит на всей доступной истории (spec_forecasting2.md §3).
# Ключевое требование §3: обратная трансформация КАЖДОЙ границы интервала
# проходит через ту же нелинейную inverse, что и точка прогноза.
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.final_fit import (
    FinalFitError,
    FinalFitResult,
    build_final_fit,
)


def _frame(n: int = 96, positive: bool = True) -> pd.DataFrame:
    t = np.arange(n, dtype=float)
    if positive:
        value = 100 * np.exp(0.002 * t) + 5 * np.sin(2 * np.pi * t / 12)
    else:
        value = 100 + 0.4 * t + 7 * np.sin(2 * np.pi * t / 12)
    return pd.DataFrame({
        "date": pd.date_range("2018-01-01", periods=n, freq="MS").astype(str),
        "value": value,
    })


# ── Без преобразований: identity ──────────────────────────────────


def test_no_chain_returns_identity_fit():
    frame = _frame()
    result = build_final_fit(
        frame, target_column="value", date_column="date",
        transformations={}, scaling_recipe={},
    )
    assert isinstance(result, FinalFitResult)
    assert result.source_column == "value"
    assert result.target_column == "value"
    assert result.reversible is True
    np.testing.assert_allclose(result.model_train, frame["value"].to_numpy(float))
    assert len(result.history_labels) == len(frame)
    restored = result.restore(result.model_train)
    np.testing.assert_allclose(restored, frame["value"].to_numpy(float), rtol=1e-9)


# ── Variance-цепочка (Box-Cox) ────────────────────────────────────


def test_variance_chain_round_trip_restores_original_scale():
    frame = _frame(positive=True)
    transformations = {
        "value_box_cox": {
            "method": "box_cox", "lambda_policy": "fixed", "lambda_value": 0.2,
            "source_column": "value", "inverse_supported": True,
        },
    }
    result = build_final_fit(
        frame, target_column="value_box_cox", date_column="date",
        transformations=transformations, scaling_recipe={},
    )
    assert result.source_column == "value"
    assert result.target_column == "value_box_cox"
    # Модель обучается на трансформированном ряде с укороченной осью? Нет:
    # variance-преобразование сохраняет длину.
    assert len(result.model_train) == len(frame)
    np.testing.assert_allclose(
        result.restore(result.model_train), frame["value"].to_numpy(float), rtol=1e-8,
    )


def test_fixed_lambda_is_not_reestimated_on_full_history():
    frame = _frame(positive=True)
    transformations = {
        "value_bc": {
            "method": "box_cox", "lambda_policy": "fixed", "lambda_value": 0.3,
            "source_column": "value", "inverse_supported": True,
        },
    }
    result = build_final_fit(
        frame, target_column="value_bc", date_column="date",
        transformations=transformations, scaling_recipe={},
    )
    state = result.transform_states[0]
    assert state["lambda_value"] == pytest.approx(0.3)
    assert state["lambda_policy"] == "fixed"


# ── Stationarity-цепочка: нелинейная инверсия границ ─────────────


def test_stationarity_chain_shortens_series_and_inverts_boundaries_separately():
    frame = _frame()
    transformations = {
        "value_diff": {
            "kind": "stationarity", "method": "first_difference",
            "seasonal_period": 12,
            "source_column": "value", "inverse_supported": True,
        },
    }
    result = build_final_fit(
        frame, target_column="value_diff", date_column="date",
        transformations=transformations, scaling_recipe={},
    )
    assert len(result.model_train) == len(frame) - 1
    point = np.asarray([0.5, 0.6, 0.7])
    lower = np.asarray([0.3, 0.4, 0.5])
    upper = np.asarray([0.7, 0.8, 0.9])
    restored_point = result.restore(point)
    restored_lower = result.restore(lower)
    restored_upper = result.restore(upper)
    # Каждая граница -- через ту же нелинейную inverse (§3): порядок границ
    # сохраняется, а интервал в исходной шкале восстанавливается по-точечно.
    assert (restored_lower < restored_point).all()
    assert (restored_point < restored_upper).all()
    # Повторный вызов restore с теми же значениями -- детерминирован
    # (stateless: вызов для lower не портит вызов для point).
    np.testing.assert_allclose(result.restore(point), restored_point, rtol=1e-12)


def test_log_difference_chain_produces_asymmetric_interval_in_original_scale():
    # §3: обратная трансформация границ нелинейна -- для log_difference
    # интервал в исходной шкале обязан быть асимметричным, если в
    # transformed-шкале он симметричен.
    frame = _frame(positive=True)
    transformations = {
        "value_logdiff": {
            "kind": "stationarity", "method": "log_difference",
            "seasonal_period": 12,
            "source_column": "value", "inverse_supported": True,
        },
    }
    result = build_final_fit(
        frame, target_column="value_logdiff", date_column="date",
        transformations=transformations, scaling_recipe={},
    )
    symmetric = np.asarray([0.01, 0.01, 0.01])
    lower = result.restore(symmetric - 0.02)
    point = result.restore(symmetric)
    upper = result.restore(symmetric + 0.02)
    assert (lower < point).all() and (point < upper).all()
    lower_gap = point - lower
    upper_gap = upper - point
    # Асимметрия присутствует хотя бы в одной точке (рост экспоненты).
    assert np.any(np.abs(upper_gap - lower_gap) > 1e-9)


def test_seasonal_difference_uses_period_from_metadata():
    frame = _frame()
    transformations = {
        "value_sdiff": {
            "kind": "stationarity", "method": "seasonal_difference",
            "seasonal_period": 12,
            "source_column": "value", "inverse_supported": True,
        },
    }
    result = build_final_fit(
        frame, target_column="value_sdiff", date_column="date",
        transformations=transformations, scaling_recipe={},
    )
    assert len(result.model_train) == len(frame) - 12
    forecast = np.asarray([1.0, 2.0, 3.0])
    restored = result.restore(forecast)
    last_season = frame["value"].to_numpy(float)[-12:]
    np.testing.assert_allclose(
        restored, last_season[:3] + forecast, rtol=1e-9,
    )


# ── Композиция цепочки + scaling ──────────────────────────────────


def test_chain_of_variance_and_stationarity_is_composed_in_order():
    frame = _frame(positive=True)
    transformations = {
        "value_bc": {
            "kind": "variance", "method": "box_cox", "lambda_policy": "fixed",
            "lambda_value": 0.5,
            "source_column": "value", "inverse_supported": True,
        },
        "value_bc_diff": {
            "kind": "stationarity", "method": "first_difference",
            "seasonal_period": 12,
            "source_column": "value_bc", "inverse_supported": True,
        },
    }
    result = build_final_fit(
        frame, target_column="value_bc_diff", date_column="date",
        transformations=transformations, scaling_recipe={},
    )
    assert result.source_column == "value"
    assert len(result.model_train) == len(frame) - 1
    # Композиция в правильном порядке: first_difference inverse использует
    # input_train = VARIANCE-трансформированную историю (не сырую), затем
    # box_cox inverse. Ожидание собирается независимо из тех же публичных
    # функций приложения.
    from app.preprocessing.transforms import (
        apply_variance_transform,
        inverse_variance_transform,
    )
    bc, _fitted = apply_variance_transform(
        frame["value"].to_numpy(float), "box_cox", 0.5,
    )
    forecast = np.asarray(result.model_train, dtype=float)
    expected = inverse_variance_transform(
        bc[-1] + np.cumsum(forecast), "box_cox", 0.5,
    )
    np.testing.assert_allclose(result.restore(forecast), expected, rtol=1e-9)


def test_target_scaling_recipe_is_fitted_on_full_history_and_inverted():
    frame = _frame()
    transformations = {}
    scaling_recipe = {
        "method": "standard", "columns": ["value"],
        "fit_policy": "per_train_fold", "parameters": {},
    }
    result = build_final_fit(
        frame, target_column="value", date_column="date",
        transformations=transformations, scaling_recipe=scaling_recipe,
    )
    # StandardScaler: mean 0, std 1 на ПОЛНОЙ истории.
    np.testing.assert_allclose(result.model_train.mean(), 0.0, atol=1e-9)
    np.testing.assert_allclose(result.model_train.std(), 1.0, atol=1e-9)
    np.testing.assert_allclose(
        result.restore(result.model_train), frame["value"].to_numpy(float), rtol=1e-9,
    )


# ── Честные отказы ────────────────────────────────────────────────


def test_non_reversible_chain_is_marked_not_reversible():
    # Сглаживание (inverse_supported=False) делает восстановление исходной
    # шкалы невозможным -- прогноз-контур обязан отказать (fail-closed).
    frame = _frame()
    transformations = {
        "value_smooth": {
            "kind": "smoothing", "method": "ema", "parameters": {"span": 7},
            "causal": True,
            "source_column": "value", "inverse_supported": False,
        },
    }
    result = build_final_fit(
        frame, target_column="value_smooth", date_column="date",
        transformations=transformations, scaling_recipe={},
    )
    assert result.reversible is False
    with pytest.raises(FinalFitError, match="необратим"):
        result.restore(np.asarray([1.0, 2.0]))


def test_non_causal_smoother_is_rejected_before_fit():
    frame = _frame()
    transformations = {
        "value_lowess": {
            "kind": "smoothing", "method": "lowess", "parameters": {},
            "causal": False,
            "source_column": "value", "inverse_supported": False,
        },
    }
    with pytest.raises(FinalFitError, match="Некаузальн"):
        build_final_fit(
            frame, target_column="value_lowess", date_column="date",
            transformations=transformations, scaling_recipe={},
        )


def test_signature_differs_from_fold_policy():
    frame = _frame()
    identity = build_final_fit(
        frame, target_column="value", date_column="date",
        transformations={}, scaling_recipe={},
    )
    assert identity.summary["fit_policy"] == "full_history"
    assert identity.signature
    assert len(identity.signature) == 64


def test_history_labels_align_with_transformed_series_tail():
    frame = _frame()
    transformations = {
        "value_diff": {
            "kind": "stationarity", "method": "first_difference",
            "seasonal_period": 12,
            "source_column": "value", "inverse_supported": True,
        },
    }
    result = build_final_fit(
        frame, target_column="value_diff", date_column="date",
        transformations=transformations, scaling_recipe={},
    )
    assert len(result.model_train_labels) == len(result.model_train)
    assert result.model_train_labels[-1] == result.history_labels[-1]
    assert result.model_train_labels[0] == result.history_labels[1]
