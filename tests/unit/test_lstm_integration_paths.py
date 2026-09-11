# tests/unit/test_lstm_integration_paths.py
"""Task 138 -- LSTM/GRU: интеграция реестра v2, dispatch, readiness, матриц
применимости и executor'а на едином NeuralForecast-runtime (контракт Task 137).

Прецедент каркас -> исполнитель: Task 134 -> 135/136 (volatility) и сам
Task 137 («контракт готов к потреблению адаптером»): runtime
(neural_runtime.py), контракт (neural_contract.py) и dependency-группа
"neural" НЕ меняются -- новый адаптер + запись реестра + yaml + Dockerfile:
- реестр: objective="level_forecast", input_kind="supervised",
  supports_future_features=True (granted-канал Task 126 -> futr_exog),
  dependency_group="neural", engine="neuralforecast", runtime_available --
  честный find_spec-проб (модель исчезает из реестра без пакета);
- dispatch: _BACKTEST_IMPLEMENTATIONS согласован с реестром (gate);
- readiness: lstm в PRODUCTION_BACKTEST_MODEL_IDS (19 -> 20);
- executor: metadata несёт нейро-контракт (config/seed/exogenous-план/
  intervals) -- диагностика Task 137;
- матрица применимости: lstm -- production level-модель, честный
  attention под task="forecast" (catalog-only блок снят), блокировка
  короткой истории остаётся (min_observations=200 yaml, F04);
- yaml: bounded param_space cell x input_size x hidden x max_steps
  = 16 trials (<= MAX_TRIALS=64).
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
from apps.api.model_impls import run_lstm_backtest as exported_run_lstm_backtest
from apps.api.model_readiness import (
    PRODUCTION_BACKTEST_MODEL_IDS,
    PRODUCTION_TUNING_MODEL_IDS,
)
from apps.api.routers.models import _BACKTEST_IMPLEMENTATIONS


def _trend_series(n: int = 220, seed: int = 17) -> list[float]:
    """Синтетический monthly-ряд: тренд + сезонность + шум (детерминированный)."""
    rng = np.random.default_rng(seed)
    return [
        float(
            100.0
            + 0.3 * step
            + 8.0 * np.sin(2.0 * np.pi * step / 12.0)
            + rng.standard_normal() * 0.8
        )
        for step in range(n)
    ]


def _monthly_labels(n: int = 220) -> list[str]:
    return [
        value.isoformat()
        for value in pd.date_range("2015-01-01", periods=n, freq="MS")
    ]


def _lstm_request(**overrides) -> ModelExecutionRequest:
    payload = dict(
        target=_trend_series(120),
        horizon=6,
        objective="level_forecast",
        seasonal_period=12,
        params={"max_steps": 5, "input_size": 24},
        train_timestamps=_monthly_labels(120),
        future_timestamps=_monthly_labels(126)[120:],
        random_state=42,
    )
    payload.update(overrides)
    return ModelExecutionRequest(**payload)


# ---------------------------------------------------------------------------
# Реестр v2: контракт level_forecast на dependency_group="neural"
# ---------------------------------------------------------------------------

def test_lstm_definition_declares_neural_level_contract() -> None:
    definition = MODEL_EXECUTION_REGISTRY.require("lstm")
    assert definition.objective == "level_forecast"
    assert definition.input_kind == "supervised"
    assert definition.family_id == "neural"
    assert definition.dependency_group == "neural"
    assert definition.adapter_id == "neuralforecast-lstm"
    assert definition.engine == "neuralforecast"
    assert definition.required_packages == ("neuralforecast",)
    assert {"backtest", "tune", "diagnostics"} <= set(definition.actions)
    assert definition.supports_prediction_intervals is True
    assert definition.supports_future_features is True
    assert definition.requires_related_series is False
    assert definition.deterministic is True


def test_lstm_runtime_available_follows_package_probe() -> None:
    """runtime_available -- честный проб: пакет установлен -> модель в
    реестре; запись обязана использовать тот же механизм dependency-probe,
    что и остальные записи v2 (без hardcode True)."""
    definition = MODEL_EXECUTION_REGISTRY.require("lstm")
    status = definition.dependency_status()
    assert [item["package"] for item in status] == ["neuralforecast"]
    assert definition.runtime_available() is ("lstm" in PRODUCTION_BACKTEST_MODEL_IDS)


def test_lstm_request_with_wrong_objective_fails_closed() -> None:
    with pytest.raises(ModelExecutionContractError, match="objective"):
        MODEL_EXECUTION_REGISTRY.execute(
            "lstm", _lstm_request(objective="volatility"),
        )


def test_lstm_request_rejects_related_series() -> None:
    with pytest.raises(ModelExecutionContractError, match="related_series"):
        MODEL_EXECUTION_REGISTRY.execute(
            "lstm", _lstm_request(related_series={"x": [1.0] * 120}),
        )


def test_lstm_execution_returns_point_forecast_with_conformal_intervals() -> None:
    result = MODEL_EXECUTION_REGISTRY.execute("lstm", _lstm_request())
    assert len(result.forecast) == 6
    assert all(np.isfinite(result.forecast))
    assert result.lower_interval is not None and result.upper_interval is not None
    assert all(
        lower <= point <= upper
        for lower, point, upper in zip(
            result.lower_interval, result.forecast, result.upper_interval, strict=True,
        )
    )
    metadata = result.metadata
    assert metadata["adapter_id"] == "neuralforecast-lstm"
    assert metadata["deterministic"] is True
    assert metadata["intervals"]["method"] == "conformal"
    assert metadata["params"]["cell"] in {"lstm", "gru"}
    assert metadata["neural"]["config"]["max_steps"] == 5
    assert metadata["neural"]["contract_version"] == "neural-contract-v1"


def test_lstm_execution_with_future_features_uses_exogenous_contract() -> None:
    train = _trend_series(120)
    future = [value + 1.0 for value in train[-6:]]
    request = _lstm_request(
        params={"max_steps": 5, "input_size": 24},
        train_features={"promo": [0.0] * 115 + [1.0] * 5},
        future_features={"promo": [1.0] * 6},
    )
    result = MODEL_EXECUTION_REGISTRY.execute("lstm", request)
    assert len(result.forecast) == 6
    metadata = result.metadata
    assert metadata["exogenous_plan"]["futr"] == ["promo"]
    assert metadata["exogenous_plan"]["signature"]
    # Канал Task 126: future-known колонка дошла до модели как futr_exog.


def test_lstm_execution_deterministic_same_random_state() -> None:
    first = MODEL_EXECUTION_REGISTRY.execute(
        "lstm", _lstm_request(params={"max_steps": 6, "input_size": 24}),
    )
    second = MODEL_EXECUTION_REGISTRY.execute(
        "lstm", _lstm_request(params={"max_steps": 6, "input_size": 24}),
    )
    assert first.forecast == second.forecast
    assert first.lower_interval == second.lower_interval


def test_lstm_execution_different_seed_changes_forecast() -> None:
    """Урок мутационной методологии Task 137: same-seed детерминизм вакуумен
    без дифференциальной пары -- другой seed обязан менять прогноз
    (seed-дисциплина: random_state -> config.seed -> fold_seed -> конструктор)."""
    first = MODEL_EXECUTION_REGISTRY.execute(
        "lstm", _lstm_request(random_state=42, params={"max_steps": 6}),
    )
    second = MODEL_EXECUTION_REGISTRY.execute(
        "lstm", _lstm_request(random_state=43, params={"max_steps": 6}),
    )
    assert first.forecast != second.forecast


def test_lstm_execution_gru_cell_runs_on_same_runtime() -> None:
    """Ядро Task 138: GRU -- легковесная альтернатива LSTM на ТОМ ЖЕ
    едином runtime (один бюджет max_steps, один seed-дисциплин)."""
    result = MODEL_EXECUTION_REGISTRY.execute(
        "lstm", _lstm_request(params={"cell": "gru", "max_steps": 5}),
    )
    assert result.metadata["params"]["cell"] == "gru"
    assert len(result.forecast) == 6


# ---------------------------------------------------------------------------
# Dispatch/readiness: gate согласованности и счётчик production-моделей
# ---------------------------------------------------------------------------

def test_lstm_in_production_backtest_ids_and_dispatch() -> None:
    assert "lstm" in PRODUCTION_BACKTEST_MODEL_IDS
    assert "lstm" in PRODUCTION_TUNING_MODEL_IDS
    assert "lstm" in _BACKTEST_IMPLEMENTATIONS
    assert exported_run_lstm_backtest is not None


def test_production_count_is_twenty() -> None:
    """19 (Task 136) + LSTM/GRU = 20 production backtest-моделей."""
    assert len(PRODUCTION_BACKTEST_MODEL_IDS) == 20


def test_lstm_joins_level_cohort_not_volatility() -> None:
    """LSTM -- level-модель: исполняется одномерным движком уровня и НЕ
    может быть отброшена гейтами cohort'а volatility/multivariate."""
    definition = MODEL_EXECUTION_REGISTRY.require("lstm")
    assert definition.objective == "level_forecast"
    assert definition.input_kind == "supervised"


# ---------------------------------------------------------------------------
# Матрица применимости: catalog-only блок снят, история честно гейтится
# ---------------------------------------------------------------------------

def _matrix_frame(n: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(23)
    values = [
        100.0 + 0.25 * step + 6.0 * np.sin(2.0 * np.pi * step / 12.0)
        + rng.standard_normal() * 0.7
        for step in range(n)
    ]
    return pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=n, freq="D").astype(str),
        "value": values,
    })


def test_matrix_marks_production_lstm_runnable_under_forecast_task() -> None:
    matrix = build_eda_model_matrix(
        _matrix_frame(), "value", task="forecast", horizon=6, n_splits=2,
    )
    entry = next(item for item in matrix["models"] if item["model_id"] == "lstm")
    assert entry["platform_status"] == "ready"
    assert entry["compatibility"] != "blocked"
    assert "lstm" in matrix["runnable_shortlist"]


def test_matrix_blocks_lstm_on_short_history() -> None:
    """min_observations=200 (yaml) -- мягкая рекомендация каталога, но
    матрица честно блокирует короткую историю до появления данных."""
    matrix = build_eda_model_matrix(
        _matrix_frame(n=120), "value", task="forecast", horizon=6, n_splits=2,
    )
    entry = next(item for item in matrix["models"] if item["model_id"] == "lstm")
    assert entry["compatibility"] == "blocked"
    assert "lstm" not in matrix["runnable_shortlist"]


# ---------------------------------------------------------------------------
# Декларации: yaml param_space и Dockerfile-проба
# ---------------------------------------------------------------------------

def test_yaml_lstm_param_space_is_bounded() -> None:
    from apps.api.routers.models import _get_spec

    model = _get_spec().get_model("lstm")
    assert model is not None
    assert model.param_space is not None
    # Ядро Task 138: архитектурный выбор LSTM/GRU -- tuning-параметр.
    assert set(model.param_space["cell"]) == {"lstm", "gru"}
    for value in model.param_space["input_size"]:
        assert 4 <= int(value) <= 128
    for value in model.param_space["encoder_hidden_size"]:
        assert 8 <= int(value) <= 256
    for value in model.param_space["max_steps"]:
        assert 1 <= int(value) <= 10_000
    trials = int(np.prod([len(v) for v in model.param_space.values()]))
    assert trials <= 64


def test_yaml_lstm_declares_neuralforecast_library_and_intervals() -> None:
    from apps.api.routers.models import _get_spec

    model = _get_spec().get_model("lstm")
    assert model is not None
    assert model.libraries == ["neuralforecast"]
    assert model.supports_prediction_intervals is True


def test_dockerfile_release_probe_executes_lstm_adapter() -> None:
    """Нейро-runtime входит в production-образ со среза Task 138: без
    neuralforecast реестр честно отфильтровал бы lstm, но consistency-gate
    dispatch<->readiness честно уронил бы сборку -- образ обязан нести
    neural-зависимости и пробу адаптера."""
    from pathlib import Path

    dockerfile = Path("apps/api/Dockerfile").read_text(encoding="utf-8")
    assert "apps.api.model_impls.lstm" in dockerfile
    assert "_lstm_fit_predict" in dockerfile
    assert "requirements-neural.txt" in dockerfile
