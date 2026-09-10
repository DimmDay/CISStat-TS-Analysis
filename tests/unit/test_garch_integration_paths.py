# tests/unit/test_garch_integration_paths.py
"""Task 135 -- GARCH: интеграция реестра v2, dispatch, readiness, схем,
матрицы применимости, selection qlike и честного профиля данных.

Точки подключения (worklog3.md::Task 134, «Границы Task 134 (задел
Tasks 135-136)»):
- реестр: objective="volatility", input_kind="univariate",
  dependency_group="volatility", engine="arch" -- гейты реестра v2;
- dispatch: _BACKTEST_IMPLEMENTATIONS согласован с реестром (gate);
- readiness: garch в PRODUCTION_BACKTEST_MODEL_IDS (17 -> 18);
  Task 136: egarch -- (18 -> 19);
- схемы: qlike в BacktestMetrics, volatility_diagnostics в fold-результате
  не теряются при Pydantic-сериализации;
- матрица применимости: production volatility-модель под task="forecast"
  получает честный attention (не блок); Task 136: catalog-only блок
  EGARCH снят регистрацией в реестре;
- selection v2: primary_metric расширен на qlike (volatility-cohort);
- профиль данных: has_volatility_clustering -- честная evidence.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.eda_model_matrix import build_eda_model_matrix
from apps.api.model_execution import (
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionContractError,
    ModelExecutionRequest,
)
from apps.api.model_impls import run_garch_backtest as exported_run_garch_backtest
from apps.api.model_readiness import (
    PRODUCTION_BACKTEST_MODEL_IDS,
    PRODUCTION_TUNING_MODEL_IDS,
)
from apps.api.modeling_selection import SelectionPolicy, SelectionContractError
from apps.api.modeling_tuning import VALID_SESSION_TUNING_METRICS
from apps.api.routers.models import _BACKTEST_IMPLEMENTATIONS


# ---------------------------------------------------------------------------
# Реестр v2: контракт volatility
# ---------------------------------------------------------------------------

def test_garch_definition_declares_volatility_contract() -> None:
    definition = MODEL_EXECUTION_REGISTRY.require("garch")
    assert definition.objective == "volatility"
    assert definition.input_kind == "univariate"
    assert definition.family_id == "volatility"
    assert definition.dependency_group == "volatility"
    assert definition.adapter_id == "arch-garch"
    assert definition.engine == "arch"
    assert definition.required_packages == ("arch",)
    assert {"backtest", "tune", "diagnostics"} <= set(definition.actions)
    assert definition.supports_prediction_intervals is True
    assert definition.deterministic is True
    assert definition.requires_related_series is False
    assert definition.supports_future_features is False


def test_garch_request_with_wrong_objective_fails_closed() -> None:
    request = ModelExecutionRequest(
        target=[float(v) for v in np.random.default_rng(7).normal(size=120) * 0.01],
        horizon=4, objective="level_forecast", seasonal_period=1, params={},
    )
    with pytest.raises(ModelExecutionContractError, match="objective"):
        MODEL_EXECUTION_REGISTRY.execute("garch", request)


def test_garch_request_rejects_train_features() -> None:
    request = ModelExecutionRequest(
        target=[float(v) for v in np.random.default_rng(7).normal(size=120) * 0.01],
        horizon=4, objective="volatility", seasonal_period=1, params={},
        train_features={"x": [1.0] * 120},
    )
    with pytest.raises(ModelExecutionContractError, match="train_features"):
        MODEL_EXECUTION_REGISTRY.execute("garch", request)


def test_garch_request_rejects_related_series() -> None:
    request = ModelExecutionRequest(
        target=[float(v) for v in np.random.default_rng(7).normal(size=120) * 0.01],
        horizon=4, objective="volatility", seasonal_period=1, params={},
        related_series={"x": [1.0] * 120},
    )
    with pytest.raises(ModelExecutionContractError, match="related_series"):
        MODEL_EXECUTION_REGISTRY.execute("garch", request)


def test_garch_execution_returns_variance_forecast() -> None:
    rng = np.random.default_rng(11)
    returns = []
    sigma2 = 1e-5
    for _ in range(160):
        eps = rng.standard_normal() * np.sqrt(sigma2)
        returns.append(eps)
        sigma2 = 1e-6 + 0.1 * eps**2 + 0.85 * sigma2
    request = ModelExecutionRequest(
        target=returns, horizon=5, objective="volatility",
        seasonal_period=1, params={}, random_state=42,
    )
    result = MODEL_EXECUTION_REGISTRY.execute("garch", request)
    assert len(result.forecast) == 5
    assert all(value > 0 for value in result.forecast)
    assert result.metadata["deterministic"] is True
    assert result.metadata["convergence_flag"] == 0
    assert "std_residuals" in result.metadata
    assert result.metadata["intervals"]["method"] == "simulation"


# ---------------------------------------------------------------------------
# Dispatch/readiness: gate согласованности и счётчик production-моделей
# ---------------------------------------------------------------------------

def test_garch_in_production_backtest_ids_and_dispatch() -> None:
    assert "garch" in PRODUCTION_BACKTEST_MODEL_IDS
    assert "garch" in PRODUCTION_TUNING_MODEL_IDS
    assert "garch" in _BACKTEST_IMPLEMENTATIONS
    assert exported_run_garch_backtest is not None


def test_production_count_is_nineteen() -> None:
    """Task 136: 18 (Task 135) + EGARCH = 19 production backtest-моделей."""
    assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 19


# ---------------------------------------------------------------------------
# Схемы: qlike и volatility-артефакты не теряются при сериализации
# ---------------------------------------------------------------------------

def test_backtest_metrics_schema_accepts_qlike() -> None:
    from apps.api.schemas import BacktestMetrics

    payload = BacktestMetrics(mae=1.0, rmse=1.5, qlike=0.42)
    assert payload.model_dump(mode="json")["qlike"] == 0.42
    legacy = BacktestMetrics(mae=1.0, rmse=1.5)
    assert legacy.qlike is None


def test_fold_and_response_schemas_keep_volatility_artifacts() -> None:
    from apps.api.schemas import (
        BacktestFoldResult,
        BacktestMetrics,
        BacktestPredictionPoint,
        BacktestResponse,
    )

    point = BacktestPredictionPoint(
        fold=1, horizon_step=1, index=20, label="2023-01-22",
        actual=0.0004, predicted=0.00035, residual=0.00005,
    )
    fold = BacktestFoldResult(
        fold=1, status="success", train_start=0, train_end=19,
        test_start=20, test_end=25, n_train=20, n_test=6,
        metrics=BacktestMetrics(mae=1e-4, rmse=2e-4, qlike=1.2),
        predictions=[point],
        volatility_baseline={"fold": 1, "metrics": {"qlike": 1.3}},
        volatility_diagnostics={"garch": {"persistence": 0.9}},
        duration_ms=1.0,
    )
    dumped = fold.model_dump(mode="json")
    assert dumped["volatility_baseline"]["metrics"]["qlike"] == 1.3
    assert dumped["volatility_diagnostics"]["garch"]["persistence"] == 0.9
    response = BacktestResponse(
        model_id="garch", model_name="GARCH(p,q)", family_id="volatility",
        metrics=BacktestMetrics(mae=1e-4, rmse=2e-4, qlike=1.2),
        n_train=20, n_test=6, train_ratio=0.8, duration_ms=1.0,
        objective="volatility", folds=[fold], oof_predictions=[point],
    )
    body = response.model_dump(mode="json")
    assert body["metrics"]["qlike"] == 1.2
    assert body["folds"][0]["volatility_diagnostics"]["garch"]["persistence"] == 0.9


# ---------------------------------------------------------------------------
# Матрица применимости: честный task-критерий volatility-семейства
# ---------------------------------------------------------------------------

def _garch_frame(n: int = 140) -> pd.DataFrame:
    """Ценовой ряд с ЯВНОЙ кластеризацией волатильности (ARCH-LM reject):
    seed/параметры зафиксированы probe'ом (p_value ~ 0 при nlags=8)."""
    rng = np.random.default_rng(21)
    omega, alpha, beta = 5e-6, 0.25, 0.65
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


def test_matrix_marks_production_garch_runnable_under_forecast_task() -> None:
    matrix = build_eda_model_matrix(
        _garch_frame(), "value", task="forecast", horizon=6, n_splits=2,
    )
    entry = next(item for item in matrix["models"] if item["model_id"] == "garch")
    assert entry["platform_status"] == "ready"
    assert entry["compatibility"] != "blocked"
    assert "garch" in matrix["runnable_shortlist"]


def test_matrix_marks_production_egarch_runnable_under_forecast_task() -> None:
    """Task 136: catalog-only блок EGARCH снят честной регистрацией в
    реестре (критерий матрицы выводит готовность из
    PRODUCTION_BACKTEST_MODEL_IDS) -- egarch проходит как production
    volatility-модель (attention, не блок)."""
    matrix = build_eda_model_matrix(
        _garch_frame(), "value", task="forecast", horizon=6, n_splits=2,
    )
    entry = next(item for item in matrix["models"] if item["model_id"] == "egarch")
    assert entry["platform_status"] == "ready"
    assert entry["compatibility"] != "blocked"
    assert "egarch" in matrix["runnable_shortlist"]


def test_matrix_volatility_task_passes_garch() -> None:
    matrix = build_eda_model_matrix(
        _garch_frame(), "value", task="volatility", horizon=6, n_splits=2,
    )
    entry = next(item for item in matrix["models"] if item["model_id"] == "garch")
    assert entry["platform_status"] == "ready"
    assert entry["compatibility"] != "blocked"


def test_matrix_blocks_garch_on_short_history() -> None:
    matrix = build_eda_model_matrix(
        _garch_frame(n=60), "value", task="forecast", horizon=6, n_splits=2,
    )
    entry = next(item for item in matrix["models"] if item["model_id"] == "garch")
    assert entry["compatibility"] == "blocked"
    assert "garch" not in matrix["runnable_shortlist"]


# ---------------------------------------------------------------------------
# Selection v2: primary_metric qlike (ранжирование внутри volatility-cohort)
# ---------------------------------------------------------------------------

def test_selection_policy_accepts_qlike() -> None:
    policy = SelectionPolicy(primary_metric="qlike")
    policy.validate()


def test_selection_policy_still_rejects_unknown_metric() -> None:
    with pytest.raises(SelectionContractError, match="primary_metric"):
        SelectionPolicy(primary_metric="mase").validate()


def test_session_tuning_metrics_include_qlike() -> None:
    assert "qlike" in VALID_SESSION_TUNING_METRICS


# ---------------------------------------------------------------------------
# Честный профиль данных: has_volatility_clustering
# ---------------------------------------------------------------------------

def test_profile_detects_volatility_clustering_on_garch_series() -> None:
    from apps.api.modeling_workflow import volatility_clustering_profile

    frame = _garch_frame()
    profile = volatility_clustering_profile(
        pd.Series(frame["value"].to_numpy(dtype=float)),
    )
    assert profile["available"] is True
    assert profile["returns_method"] == "log"
    assert profile["reject_null"] is True


def test_profile_white_noise_returns_has_no_clustering() -> None:
    """Случайное блуждание с i.i.d.-приращениями (эталон отсутствия
    кластеризации).  NB: i.i.d. УРОВЕНЬ здесь неприменим -- разности
    i.i.d.-уровня образуют MA(1), квадраты которых автокоррелированы по
    построению (ARCH-LM честно это детектирует)."""
    from apps.api.modeling_workflow import volatility_clustering_profile

    rng = np.random.default_rng(23)
    level = 100.0 * np.exp(np.cumsum(0.01 * rng.standard_normal(300)))
    profile = volatility_clustering_profile(pd.Series(level))
    assert profile["available"] is True
    assert profile["reject_null"] is False


def test_profile_degenerate_series_is_honest_unavailable() -> None:
    from apps.api.modeling_workflow import volatility_clustering_profile

    profile = volatility_clustering_profile(
        pd.Series([float(v) for v in range(-50, 50)]),  # есть неположительные
    )
    assert profile["available"] is False
    assert profile["reject_null"] is False


# ---------------------------------------------------------------------------
# Декларации: yaml param_space и Dockerfile-проба
# ---------------------------------------------------------------------------

def test_yaml_garch_param_space_is_bounded() -> None:
    from apps.api.routers.models import _get_spec

    model = _get_spec().get_model("garch")
    assert model is not None
    assert model.param_space is not None
    bounds_p, bounds_q = (1, 3), (1, 3)
    assert all(bounds_p[0] <= v <= bounds_p[1] for v in model.param_space["p"])
    assert all(bounds_q[0] <= v <= bounds_q[1] for v in model.param_space["q"])
    assert set(model.param_space["dist"]) <= {"normal", "t"}
    assert set(model.param_space["mean"]) <= {"Constant", "Zero"}
    trials = int(np.prod([len(v) for v in model.param_space.values()]))
    assert trials <= 64


def test_dockerfile_release_probe_executes_garch_adapter() -> None:
    from pathlib import Path

    dockerfile = Path("apps/api/Dockerfile").read_text(encoding="utf-8")
    assert "apps.api.model_impls.garch" in dockerfile
    assert "_garch_fit_predict" in dockerfile
