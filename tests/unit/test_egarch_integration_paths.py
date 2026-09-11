# tests/unit/test_egarch_integration_paths.py
"""Task 136 -- EGARCH: интеграция реестра v2, dispatch, readiness, матрицы
применимости, executor'а и volatility-движка (переиспользуемого бит-в-бит).

Прецедент пары var/vecm в одном движке (worklog3.md::Task 135, «Границы
Task 135 (задел Task 136)»): volatility-движок Task 135 не меняется --
новые адаптер + запись реестра + yaml:
- реестр: objective="volatility", input_kind="univariate",
  dependency_group="volatility", engine="arch" -- гейты реестра v2;
- dispatch: _BACKTEST_IMPLEMENTATIONS согласован с реестром (gate);
- readiness: egarch в PRODUCTION_BACKTEST_MODEL_IDS (18 -> 19);
- executor: metadata несёт asymmetry-блок (leverage/asymmetry -- ядро
  Task 136) и читается volatility-движком в fold-диагностику, ключ
  блока -- model_id (для garch ответ бит-идентичен Task 135);
- матрица применимости: EGARCH -- production volatility-модель, честный
  attention под task="forecast" (catalog-only блок снят);
- yaml: bounded param_space p/o/q x mean x dist <= 64 trials.
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
from apps.api.model_impls import run_egarch_backtest as exported_run_egarch_backtest
from apps.api.model_readiness import (
    PRODUCTION_BACKTEST_MODEL_IDS,
    PRODUCTION_TUNING_MODEL_IDS,
)
from apps.api.routers.models import _BACKTEST_IMPLEMENTATIONS


def _egarch_returns(n: int = 260, seed: int = 2026) -> list[float]:
    """EGARCH(1,1,1) с классическим leverage (gamma<0) -- генератор
    probe'а (scripts/task136_probe.py)."""
    rng = np.random.default_rng(seed)
    omega, alpha, gamma, beta = -0.05, 0.12, -0.15, 0.90
    norm_const = np.sqrt(2.0 / np.pi)
    ln_s2 = omega / (1.0 - beta)
    s2 = float(np.exp(ln_s2))
    out = np.empty(n)
    for t in range(n):
        eps = float(np.sqrt(s2) * rng.standard_normal())
        out[t] = eps
        e = eps / np.sqrt(s2)
        ln_s2 = omega + alpha * (abs(e) - norm_const) + gamma * e + beta * ln_s2
        s2 = float(np.exp(ln_s2))
    return [float(value) for value in out]


# ---------------------------------------------------------------------------
# Реестр v2: контракт volatility
# ---------------------------------------------------------------------------

def test_egarch_definition_declares_volatility_contract() -> None:
    definition = MODEL_EXECUTION_REGISTRY.require("egarch")
    assert definition.objective == "volatility"
    assert definition.input_kind == "univariate"
    assert definition.family_id == "volatility"
    assert definition.dependency_group == "volatility"
    assert definition.adapter_id == "arch-egarch"
    assert definition.engine == "arch"
    assert definition.required_packages == ("arch",)
    assert {"backtest", "tune", "diagnostics"} <= set(definition.actions)
    assert definition.supports_prediction_intervals is True
    assert definition.deterministic is True
    assert definition.requires_related_series is False
    assert definition.supports_future_features is False


def test_egarch_request_with_wrong_objective_fails_closed() -> None:
    request = ModelExecutionRequest(
        target=_egarch_returns(120, seed=7),
        horizon=4, objective="level_forecast", seasonal_period=1, params={},
    )
    with pytest.raises(ModelExecutionContractError, match="objective"):
        MODEL_EXECUTION_REGISTRY.execute("egarch", request)


def test_egarch_request_rejects_train_features() -> None:
    request = ModelExecutionRequest(
        target=_egarch_returns(120, seed=7),
        horizon=4, objective="volatility", seasonal_period=1, params={},
        train_features={"x": [1.0] * 120},
    )
    with pytest.raises(ModelExecutionContractError, match="train_features"):
        MODEL_EXECUTION_REGISTRY.execute("egarch", request)


def test_egarch_request_rejects_related_series() -> None:
    request = ModelExecutionRequest(
        target=_egarch_returns(120, seed=7),
        horizon=4, objective="volatility", seasonal_period=1, params={},
        related_series={"x": [1.0] * 120},
    )
    with pytest.raises(ModelExecutionContractError, match="related_series"):
        MODEL_EXECUTION_REGISTRY.execute("egarch", request)


def test_egarch_execution_returns_variance_forecast_with_asymmetry() -> None:
    request = ModelExecutionRequest(
        target=_egarch_returns(), horizon=5, objective="volatility",
        seasonal_period=1, params={}, random_state=42,
    )
    result = MODEL_EXECUTION_REGISTRY.execute("egarch", request)
    assert len(result.forecast) == 5
    assert all(value > 0 for value in result.forecast)
    assert result.metadata["deterministic"] is True
    assert result.metadata["convergence_flag"] == 0
    assert "std_residuals" in result.metadata
    assert result.metadata["intervals"]["method"] == "simulation"
    # Ядро Task 136: asymmetry-блок в metadata executor'а.
    asymmetry = result.metadata["asymmetry"]
    assert asymmetry["order"] == 1
    assert "gamma[1]" in asymmetry["gamma_params"]
    assert asymmetry["leverage_direction"] in {"negative", "positive", "mixed"}
    assert isinstance(asymmetry["asymmetry_significant"], bool)


# ---------------------------------------------------------------------------
# Dispatch/readiness: gate согласованности и счётчик production-моделей
# ---------------------------------------------------------------------------

def test_egarch_in_production_backtest_ids_and_dispatch() -> None:
    assert "egarch" in PRODUCTION_BACKTEST_MODEL_IDS
    assert "egarch" in PRODUCTION_TUNING_MODEL_IDS
    assert "egarch" in _BACKTEST_IMPLEMENTATIONS
    assert exported_run_egarch_backtest is not None


def test_production_count_is_nineteen() -> None:
    """18 (Task 135) + EGARCH = 19 production backtest-моделей.
    Task 138: lstm -- 20-я, Task 139: nbeats -- 21-я, НО neural-runtime --
    опциональная dependency-группа (requirements-neural.txt): членство
    lstm/nbeats в readiness честно зависит от прога
    neuralforecast_runtime_available()."""
    from apps.api.model_impls.neural_runtime import neuralforecast_runtime_available

    expected = 21 if neuralforecast_runtime_available() else 19
    assert len(PRODUCTION_BACKTEST_MODEL_IDS) == expected


def test_both_volatility_models_share_one_engine() -> None:
    """Прецедент var/vecm: garch и egarch -- два исполнителя ОДНОГО
    volatility-движка; гейты cohort'а одинаковы."""
    garch = MODEL_EXECUTION_REGISTRY.require("garch")
    egarch = MODEL_EXECUTION_REGISTRY.require("egarch")
    assert garch.objective == egarch.objective == "volatility"
    assert garch.input_kind == egarch.input_kind == "univariate"
    assert garch.dependency_group == egarch.dependency_group == "volatility"


# ---------------------------------------------------------------------------
# Матрица применимости: catalog-only блок снят честным task-критерием
# ---------------------------------------------------------------------------

def _egarch_frame(n: int = 140) -> pd.DataFrame:
    """Ценовой ряд с ЯВНОЙ кластеризацией волатильности (ARCH-LM reject)
    -- тот же генератор, что у garch-тестов Task 135 (seed зафиксирован)."""
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


def test_matrix_marks_production_egarch_runnable_under_forecast_task() -> None:
    matrix = build_eda_model_matrix(
        _egarch_frame(), "value", task="forecast", horizon=6, n_splits=2,
    )
    entry = next(item for item in matrix["models"] if item["model_id"] == "egarch")
    assert entry["platform_status"] == "ready"
    assert entry["compatibility"] != "blocked"
    assert "egarch" in matrix["runnable_shortlist"]


def test_matrix_volatility_task_passes_egarch() -> None:
    matrix = build_eda_model_matrix(
        _egarch_frame(), "value", task="volatility", horizon=6, n_splits=2,
    )
    entry = next(item for item in matrix["models"] if item["model_id"] == "egarch")
    assert entry["platform_status"] == "ready"
    assert entry["compatibility"] != "blocked"


def test_matrix_blocks_egarch_on_short_history() -> None:
    matrix = build_eda_model_matrix(
        _egarch_frame(n=60), "value", task="forecast", horizon=6, n_splits=2,
    )
    entry = next(item for item in matrix["models"] if item["model_id"] == "egarch")
    assert entry["compatibility"] == "blocked"
    assert "egarch" not in matrix["runnable_shortlist"]


# ---------------------------------------------------------------------------
# Декларации: yaml param_space и Dockerfile-проба
# ---------------------------------------------------------------------------

def test_yaml_egarch_param_space_is_bounded() -> None:
    from apps.api.routers.models import _get_spec

    model = _get_spec().get_model("egarch")
    assert model is not None
    assert model.param_space is not None
    bounds = {"p": (1, 3), "o": (1, 3), "q": (1, 3)}
    for key, (low, high) in bounds.items():
        assert all(low <= v <= high for v in model.param_space[key])
    assert set(model.param_space["dist"]) <= {"normal", "t"}
    assert set(model.param_space["mean"]) <= {"Constant", "Zero"}
    trials = int(np.prod([len(v) for v in model.param_space.values()]))
    assert trials <= 64


def test_dockerfile_release_probe_executes_egarch_adapter() -> None:
    from pathlib import Path

    dockerfile = Path("apps/api/Dockerfile").read_text(encoding="utf-8")
    assert "apps.api.model_impls.egarch" in dockerfile
    assert "_egarch_fit_predict" in dockerfile
