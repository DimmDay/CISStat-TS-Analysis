# tests/unit/test_var_registry_integration.py
"""Task 132 -- VAR: интеграция реестра v2, схем ответа и честного профиля.

Точки подключения (worklog3.md, «Задел Tasks 132–133»):
- реестр: objective="multivariate", input_kind="multivariate",
  requires_related_series=True -- гейты реестра v2;
- dispatch: _BACKTEST_IMPLEMENTATIONS согласован с реестром;
- схемы: векторные артефакты (series в OOF-точке, per_series_metrics,
  scaled_loss, vector_baseline, multivariate_diagnostics) не теряются при
  Pydantic-сериализации;
- comparison: ключ OOF-точки различает серии (без коллизий);
- build_modeling_context: честный n_series вместо жёсткой единицы.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.model_execution import (
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionContractError,
    ModelExecutionRequest,
)
from apps.api.modeling_comparison import ComparisonContractError, _point_key
from apps.api.modeling_workflow import honest_system_profile
from apps.api.routers.models import _BACKTEST_IMPLEMENTATIONS


# ---------------------------------------------------------------------------
# Реестр v2: гейты multivariate
# ---------------------------------------------------------------------------

def test_var_definition_declares_multivariate_contract() -> None:
    definition = MODEL_EXECUTION_REGISTRY.require("var")
    assert definition.objective == "multivariate"
    assert definition.input_kind == "multivariate"
    assert definition.requires_related_series is True
    assert definition.deterministic is True
    assert definition.supports_prediction_intervals is True
    assert "backtest" in definition.actions


def test_var_request_without_related_series_fails_closed() -> None:
    request = ModelExecutionRequest(
        target=[float(v) for v in np.random.default_rng(7).normal(size=60)],
        horizon=4,
        objective="multivariate",
        seasonal_period=1,
        params={},
    )
    with pytest.raises(ModelExecutionContractError, match="related_series"):
        MODEL_EXECUTION_REGISTRY.execute("var", request)


def test_var_request_with_wrong_objective_fails_closed() -> None:
    matrix = np.random.default_rng(7).normal(size=(60, 2))
    request = ModelExecutionRequest(
        target=[float(v) for v in matrix[:, 0]],
        horizon=4,
        objective="level_forecast",
        seasonal_period=1,
        params={},
        related_series={"b": [float(v) for v in matrix[:, 1]]},
    )
    with pytest.raises(ModelExecutionContractError, match="objective"):
        MODEL_EXECUTION_REGISTRY.execute("var", request)


def test_var_execution_returns_vector_payload_and_flat_target_slice() -> None:
    rng = np.random.default_rng(7)
    out = np.zeros((90, 2))
    out[0] = rng.normal(size=2)
    for t in range(1, 90):
        out[t] = 0.5 * out[t - 1] + rng.normal(size=2)
    request = ModelExecutionRequest(
        target=[float(v) for v in out[:, 0]],
        horizon=5,
        objective="multivariate",
        seasonal_period=1,
        params={"maxlags": 2, "ic": None},
        related_series={"b": [float(v) for v in out[:, 1]]},
    )
    result = MODEL_EXECUTION_REGISTRY.execute("var", request)
    # Плоский контракт forecast = колонка target-ряда (первая колонка системы).
    assert len(result.forecast) == 5
    metadata = result.metadata
    assert np.asarray(metadata["vector_forecast"]).shape == (5, 2)
    assert np.asarray(metadata["vector_lower"]).shape == (5, 2)
    assert np.asarray(metadata["vector_upper"]).shape == (5, 2)
    assert metadata["lag_order"] == 2
    # Плоский срез == первая колонка векторного прогноза (согласованность).
    assert result.forecast == pytest.approx(
        [float(v) for v in np.asarray(metadata["vector_forecast"])[:, 0]],
    )


def test_backtest_dispatch_consistent_with_registry() -> None:
    # Гейт routers/models.py: dispatch обязан совпадать с реестром.
    production_ids = {
        model_id for model_id, definition in
        MODEL_EXECUTION_REGISTRY._definitions.items()
        if "backtest" in definition.actions and definition.runtime_available()
    }
    assert production_ids == set(_BACKTEST_IMPLEMENTATIONS)
    assert "var" in _BACKTEST_IMPLEMENTATIONS


# ---------------------------------------------------------------------------
# Схемы: векторные артефакты не теряются
# ---------------------------------------------------------------------------

def test_oof_point_schema_keeps_series_dimension() -> None:
    from apps.api.schemas import BacktestPredictionPoint

    point = BacktestPredictionPoint(
        fold=1, horizon_step=1, index=10, label="t10",
        series="inflation", actual=2.0, predicted=1.0, residual=1.0,
    )
    dumped = point.model_dump(mode="json")
    assert dumped["series"] == "inflation"


def test_oof_point_series_defaults_to_none_for_univariate() -> None:
    from apps.api.schemas import BacktestPredictionPoint

    point = BacktestPredictionPoint(
        fold=1, horizon_step=1, index=10, actual=2.0, predicted=1.0, residual=1.0,
    )
    assert point.series is None


def test_fold_and_response_schemas_keep_vector_artifacts() -> None:
    from apps.api.schemas import BacktestFoldResult

    fold = BacktestFoldResult(
        fold=1, status="success", train_start=0, train_end=9,
        test_start=10, test_end=12, n_train=10, n_test=3, duration_ms=1.0,
        per_series_metrics={"a": {"mae": 1.0}},
        scaled_loss=0.5,
        vector_baseline={"aggregate": {"mae": 2.0}},
        multivariate_diagnostics={"var": {"lag_order": 2}},
    )
    dumped = fold.model_dump(mode="json")
    assert dumped["per_series_metrics"] == {"a": {"mae": 1.0}}
    assert dumped["scaled_loss"] == 0.5
    assert dumped["vector_baseline"] == {"aggregate": {"mae": 2.0}}
    assert dumped["multivariate_diagnostics"] == {"var": {"lag_order": 2}}


# ---------------------------------------------------------------------------
# Comparison: ключ OOF-точки различает серии
# ---------------------------------------------------------------------------

def test_point_key_distinguishes_series_without_collision() -> None:
    univariate = {"fold": 1, "horizon_step": 1, "index": 10, "label": None}
    vector_a = {**univariate, "series": "gdp"}
    vector_b = {**univariate, "series": "inflation"}
    assert _point_key(vector_a) != _point_key(vector_b)
    assert _point_key(univariate) != _point_key(vector_a)


def test_point_key_is_backward_compatible_for_univariate_points() -> None:
    point = {"fold": 2, "horizon_step": 3, "index": 14, "label": "t14"}
    fold, step, index, label, series = _point_key(point)
    assert (fold, step, index, label, series) == (2, 3, 14, "t14", "")


# ---------------------------------------------------------------------------
# Честный профиль системы в build_modeling_context
# ---------------------------------------------------------------------------

def _dataframe(n: int = 120, k_extra: int = 1, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data = {"date": pd.date_range("2020-01-01", periods=n, freq="D")}
    data["value"] = [float(v) for v in np.cumsum(rng.normal(size=n))]
    for index in range(k_extra):
        data[f"related_{index}"] = [float(v) for v in rng.normal(size=n)]
    return pd.DataFrame(data)


def test_honest_profile_counts_numeric_series_beyond_target() -> None:
    profile = honest_system_profile(
        _dataframe(k_extra=1), date_column="date", target_column="value",
    )
    assert profile["n_series"] == 2
    assert profile["related_series"] == ["related_0"]


def test_honest_profile_single_series_is_one() -> None:
    profile = honest_system_profile(
        _dataframe(k_extra=0), date_column="date", target_column="value",
    )
    assert profile["n_series"] == 1
    assert profile["related_series"] == []


def test_honest_profile_ignores_non_numeric_columns() -> None:
    frame = _dataframe(k_extra=1)
    frame["segment"] = ["eu"] * len(frame)
    profile = honest_system_profile(
        frame, date_column="date", target_column="value",
    )
    assert profile["n_series"] == 2
    assert profile["related_series"] == ["related_0"]


def test_honest_profile_excludes_declared_numeric_date_column() -> None:
    # Объявленная date-колонка исключается, даже если она числового типа
    # (unix-timestamp): числовая дата -- не endogenous-ряд.
    frame = _dataframe(k_extra=0)
    frame["date_unix"] = frame["date"].astype("int64")
    profile = honest_system_profile(
        frame, date_column="date_unix", target_column="value",
    )
    assert profile["n_series"] == 1
    assert profile["related_series"] == []
    assert profile["date_is_numeric"] is True


def test_honest_profile_cointegration_is_advisory_evidence() -> None:
    # Две НЕЗАВИСИМЫЕ случайные прогулки (обе I(1)): коинтеграция не должна
    # выдумываться.  Конструкция/seed верифицированы в Task 131 (n=150,
    # seed 42 -> trace-ранг 0 на 95%; связывающий тест Task 131).
    rng = np.random.default_rng(42)
    n = 150
    frame = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=n, freq="D"),
        "value": [float(v) for v in np.cumsum(rng.normal(size=n))],
        "related_0": [float(v) for v in np.cumsum(rng.normal(size=n))],
    })
    profile = honest_system_profile(
        frame, date_column="date", target_column="value",
    )
    assert profile["n_series"] == 2
    assert profile["is_cointegrated"] is False


def test_honest_profile_detects_cointegrated_pair() -> None:
    # Коинтегрированная пара с шумом (точная линейная связь вырождена --
    # ковариация сингулярна, Johansen library-native отказ).
    rng = np.random.default_rng(7)
    x = np.cumsum(rng.normal(size=200))
    noise = rng.normal(size=200) * 0.05
    frame = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=200, freq="D"),
        "value": [float(v) for v in x],
        "linked": [float(2.0 * v + 0.1 + e) for v, e in zip(x, noise)],
    })
    profile = honest_system_profile(
        frame, date_column="date", target_column="value",
    )
    assert profile["n_series"] == 2
    assert profile["is_cointegrated"] is True
