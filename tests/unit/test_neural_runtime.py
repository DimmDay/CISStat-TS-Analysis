# tests/unit/test_neural_runtime.py
"""Task 137 -- Neural Runtime Contract: единый NeuralForecast-runtime.

Уровень neural_runtime -- единственная точка, где torch/neuralforecast
ИМПОРТИРУЮТСЯ лениво; пять вертикальных срезов (Tasks 138-142: LSTM/GRU,
N-BEATS, N-HiTS, TFT, DeepAR) получают один и тот же fit/predict-цикл,
детерминированный seed и budget-мэппинг вместо смеси Darts/GluonTS/
PyTorch Forecasting.

Эмпирические факты neuralforecast 3.2.2 (проб scripts/task137_neural_api_probe.py):
- BaseModel: max_epochs DEPRECATED (Exception) -- единый бюджет max_steps;
- BaseModel: accelerator по умолчанию "gpu" -- устройство задаётся ЯВНО;
- квантильные выходы point-loss моделей: fit(prediction_intervals=PredictionIntervals())
  + predict(level=[...]) (conformal);
- детерминизм: seed_neural_runtime ДО конструирования модели -> бит-в-бит прогноз.
"""
from __future__ import annotations

import random as py_random

import numpy as np
import pandas as pd
import pytest

from apps.api.neural_contract import NeuralContractError, NeuralTrainingConfig
from apps.api.model_impls.neural_runtime import (
    NEURALFORECAST_VERSION_BOUND,
    neural_model_budget_kwargs,
    neuralforecast_runtime_available,
    require_neuralforecast,
    seed_neural_runtime,
    train_and_forecast,
)

pytest.importorskip("neuralforecast", reason="neural runtime -- опциональная группа")


def _long(n: int = 96, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "unique_id": ["series_0"] * n,
        "ds": pd.date_range("2024-01-01", periods=n, freq="D"),
        "y": 10 + 0.03 * np.arange(n) + rng.standard_normal(n) * 0.15,
    })


# ── 1-2. Runtime probe и честный отказ ───────────────────────────────────

def test_runtime_available_is_true_after_install():
    assert neuralforecast_runtime_available() is True


def test_runtime_probe_reports_false_without_package(monkeypatch):
    # find_spec импортирован в неймспейс модуля -- честный проб
    # имитируем отсутствующим пакетом именно там.
    monkeypatch.setattr(
        "apps.api.model_impls.neural_runtime.find_spec",
        lambda name: None,
    )
    assert neuralforecast_runtime_available() is False


def test_require_neuralforecast_returns_module():
    module = require_neuralforecast()
    assert module is not None
    assert hasattr(module, "NeuralForecast")


def test_require_neuralforecast_fail_closed_when_missing(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "neuralforecast", None)
    with pytest.raises(NeuralContractError, match="neuralforecast"):
        require_neuralforecast()


def test_version_bound_declared():
    assert NEURALFORECAST_VERSION_BOUND.startswith("neuralforecast>=")


# ── 3. Детерминированный seed ────────────────────────────────────────────

def test_seed_neural_runtime_binds_python_and_numpy():
    seed_neural_runtime(1234)
    py_value = py_random.random()
    np_value = float(np.random.rand())
    seed_neural_runtime(1234)
    assert py_random.random() == py_value
    assert float(np.random.rand()) == np_value


def test_seed_neural_runtime_seeds_torch():
    torch = pytest.importorskip("torch")
    seed_neural_runtime(99)
    a = torch.rand(4)
    seed_neural_runtime(99)
    b = torch.rand(4)
    torch.testing.assert_close(a, b)


def test_seed_neural_runtime_rejects_out_of_bounds():
    with pytest.raises(NeuralContractError, match="seed"):
        seed_neural_runtime(-5)


# ── 4. Budget-мэппинг на kwargs нейро-модели ─────────────────────────────

def test_budget_kwargs_native_max_steps():
    config = NeuralTrainingConfig(seed=1, max_steps=42)
    kwargs = neural_model_budget_kwargs(config, device="cpu")
    assert kwargs["max_steps"] == 42


def test_budget_kwargs_explicit_device_accelerator():
    # BaseModel по умолчанию ставит accelerator="gpu" -- контракт обязан
    # задавать устройство ЯВНО (честные CPU/GPU capabilities).
    config = NeuralTrainingConfig(seed=1, max_steps=3)
    cpu = neural_model_budget_kwargs(config, device="cpu")
    assert cpu["accelerator"] == "cpu"
    gpu = neural_model_budget_kwargs(config, device="cuda")
    assert gpu["accelerator"] == "cuda"


def test_budget_kwargs_progress_bar_disabled():
    config = NeuralTrainingConfig(seed=1, max_steps=3)
    kwargs = neural_model_budget_kwargs(config, device="cpu")
    assert kwargs.get("enable_progress_bar") is False


def test_budget_kwargs_early_stopping_mapping():
    enabled = NeuralTrainingConfig(
        seed=1, max_steps=50, early_stopping_patience=3, val_size=8,
    )
    kwargs = neural_model_budget_kwargs(enabled, device="cpu")
    assert kwargs["early_stop_patience_steps"] == 3
    disabled = NeuralTrainingConfig(seed=1, max_steps=50, early_stopping_patience=0)
    kwargs = neural_model_budget_kwargs(disabled, device="cpu")
    assert kwargs["early_stop_patience_steps"] == -1


# ── 5. Унифицированный fit/predict-цикл ──────────────────────────────────

def _nhits_factory(h: int = 4, input_size: int = 16):
    models = require_neuralforecast().models
    return lambda budget: models.NHITS(h=h, input_size=input_size, **budget)


def test_train_and_forecast_point_and_quantile_outputs():
    preds = train_and_forecast(
        model_factory=_nhits_factory(), freq="D", train_long=_long(),
        horizon=4, config=NeuralTrainingConfig(seed=11, max_steps=3),
        levels=(10.0, 90.0),
    )
    assert len(preds) == 4
    assert "unique_id" in preds.columns and "ds" in preds.columns
    assert "NHITS" in preds.columns
    lo = [c for c in preds.columns if c.endswith("-lo-10.0")]
    hi = [c for c in preds.columns if c.endswith("-hi-90.0")]
    assert lo and hi, "quantile-колонки отсутствуют при level=[10, 90]"
    assert (preds[lo[0]] <= preds[hi[0]]).all()


def test_train_and_forecast_point_only_without_levels():
    preds = train_and_forecast(
        model_factory=_nhits_factory(), freq="D", train_long=_long(),
        horizon=4, config=NeuralTrainingConfig(seed=11, max_steps=3),
    )
    assert "NHITS" in preds.columns
    assert not any("-lo-" in c or "-hi-" in c for c in preds.columns)


def test_train_and_forecast_deterministic_for_same_seed():
    preds_a = train_and_forecast(
        model_factory=_nhits_factory(), freq="D", train_long=_long(),
        horizon=4, config=NeuralTrainingConfig(seed=21, max_steps=3),
    )
    preds_b = train_and_forecast(
        model_factory=_nhits_factory(), freq="D", train_long=_long(),
        horizon=4, config=NeuralTrainingConfig(seed=21, max_steps=3),
    )
    np.testing.assert_allclose(
        preds_a["NHITS"].to_numpy(), preds_b["NHITS"].to_numpy(), rtol=1e-6,
    )


def test_train_and_forecast_rejects_empty_train():
    empty = _long().iloc[:0]
    with pytest.raises(NeuralContractError):
        train_and_forecast(
            model_factory=_nhits_factory(), freq="D", train_long=empty,
            horizon=4, config=NeuralTrainingConfig(seed=1, max_steps=3),
        )


# ── 6. Пять каталог-моделей на одном runtime (smoke унификации) ──────────

@pytest.mark.parametrize("cls_name", ["LSTM", "NBEATS", "NHITS", "TFT", "DeepAR"])
def test_five_catalog_models_construct_on_unified_runtime(cls_name):
    """Унификация Task 137: пять моделей Tasks 138-142 конструируются
    на ЕДИНОМ NeuralForecast-runtime с бюджетом из контракта."""
    models = require_neuralforecast().models
    config = NeuralTrainingConfig(seed=137, max_steps=1)
    budget = neural_model_budget_kwargs(config, device="cpu")
    model = getattr(models, cls_name)(h=4, input_size=16, **budget)
    assert model.h == 4
