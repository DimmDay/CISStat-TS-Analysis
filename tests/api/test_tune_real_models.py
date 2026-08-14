"""Phase 1-D integration tests for tuning on real ETS/ARIMA implementations."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pytest
from fastapi import HTTPException

from apps.api.cv import ExpandingWindowCV
from apps.api.routers import models as models_router
from apps.api.schemas import CVConfig
from apps.api.model_impls.arima import _arima_fit_predict
from src.catalog.modeling_spec_loader import ModelingSpec

SPEC_PATH = Path("rules/modeling.yaml")
_LEGACY_TUNABLE_PREDICT = models_router._tunable_predict


def _make_series(n: int = 72) -> List[float]:
    return [100.0 + 0.45 * t + 7.0 * math.sin(2.0 * math.pi * t / 12.0) + 0.5 * math.cos(2.0 * math.pi * t / 6.0) for t in range(n)]


@pytest.fixture(scope="module")
def spec() -> ModelingSpec:
    return ModelingSpec.from_yaml(str(SPEC_PATH))


def _real_tunable_predict(model_id: str, y_train: List[float], test_size: int, params: Dict[str, Any]) -> List[float]:
    if model_id in {"ets", "ets_damped"}:
        trend = params.get("trend", "add")
        seasonal = params.get("seasonal")
        seasonal_period = int(params.get("seasonal_periods", 12))
        damped = bool(params.get("damped_trend", False)) if model_id == "ets" else True
        if trend == "mul" and any(v <= 0 for v in y_train):
            raise ValueError("multiplicative ETS requires positive training data")
        if seasonal == "mul" and any(v <= 0 for v in y_train):
            raise ValueError("multiplicative seasonality requires positive data")
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        kwargs: Dict[str, Any] = {"trend": trend, "damped_trend": damped, "initialization_method": "estimated"}
        if seasonal is not None and seasonal_period > 1:
            if len(y_train) < 2 * seasonal_period:
                raise ValueError("not enough observations for two seasonal cycles")
            kwargs["seasonal"] = seasonal
            kwargs["seasonal_periods"] = seasonal_period
        fitted = ExponentialSmoothing(pd.Series(y_train, index=pd.RangeIndex(len(y_train))), **kwargs).fit()
        return list(fitted.forecast(test_size))
    if model_id == "arima":
        return _arima_fit_predict(y_train, test_size, (int(params["p"]), int(params["d"]), int(params["q"])))
    raise AssertionError(f"Real Phase 1-D adapter not implemented for {model_id}")


@pytest.fixture
def use_real_tunable_predict(monkeypatch):
    monkeypatch.setattr(models_router, "_tunable_predict", _real_tunable_predict)


class TestPhase1DBaselineSkip:
    @pytest.mark.parametrize("model_id", ["naive", "seasonal_naive", "drift", "mean"])
    def test_baseline_is_not_tunable(self, spec, model_id):
        with pytest.raises(HTTPException) as exc_info:
            models_router._execute_tune(spec=spec, model_id=model_id, series=_make_series(), cv_config=CVConfig(n_splits=3, test_size=2), max_trials=None, metric="rmse", random_state=42)
        assert exc_info.value.status_code == 422
        assert "param_space" in str(exc_info.value)


class TestPhase1DEtsRealGrid:
    def test_ets_grid_executes_real_statsmodels(self, spec, use_real_tunable_predict):
        response = models_router._execute_tune(spec=spec, model_id="ets", series=_make_series(), cv_config=CVConfig(n_splits=3, test_size=2), max_trials=None, metric="rmse", random_state=42)
        assert response.grid_size == 12
        assert response.n_trials == 12
        assert response.truncated is False
        assert response.cv_config.n_splits == 3
        assert all(trial.n_folds == 3 for trial in response.trials)
        assert response.best_params in [trial.params for trial in response.trials]
        for trial in response.trials:
            assert math.isfinite(trial.metrics.rmse) and trial.metrics.rmse >= 0
            assert math.isfinite(trial.metrics.mae) and trial.metrics.mae >= 0
        assert len({round(trial.metrics.rmse, 8) for trial in response.trials}) >= 2

    def test_ets_real_predictions_are_not_legacy_stub(self, spec, use_real_tunable_predict):
        y_train = _make_series(48)
        params = {"trend": "add", "seasonal": "add", "seasonal_periods": 12, "damped_trend": False}
        real_pred = _real_tunable_predict("ets", y_train, 3, params)
        legacy_pred = _LEGACY_TUNABLE_PREDICT("ets", y_train, 3, params)
        assert len(real_pred) == 3
        assert all(math.isfinite(v) for v in real_pred)
        assert real_pred != legacy_pred


class TestPhase1DArimaRealGrid:
    @pytest.mark.filterwarnings("ignore::UserWarning")
    @pytest.mark.filterwarnings("ignore::statsmodels.tools.sm_exceptions.ConvergenceWarning")
    def test_arima_grid_executes_real_statsmodels(self, spec, use_real_tunable_predict):
        response = models_router._execute_tune(spec=spec, model_id="arima", series=_make_series(), cv_config=CVConfig(n_splits=3, test_size=2), max_trials=None, metric="rmse", random_state=42)
        assert response.grid_size == 18
        assert response.n_trials == 18
        assert response.truncated is False
        assert all(trial.n_folds == 3 for trial in response.trials)
        for trial in response.trials:
            assert math.isfinite(trial.metrics.rmse) and trial.metrics.rmse >= 0
            assert math.isfinite(trial.metrics.mae) and trial.metrics.mae >= 0
        assert len({round(trial.metrics.rmse, 8) for trial in response.trials}) >= 2

    @pytest.mark.filterwarnings("ignore::UserWarning")
    @pytest.mark.filterwarnings("ignore::statsmodels.tools.sm_exceptions.ConvergenceWarning")
    def test_arima_real_prediction_is_not_legacy_stub(self, spec, use_real_tunable_predict):
        y_train = _make_series(48)
        params = {"p": 1, "d": 1, "q": 1}
        real_pred = _real_tunable_predict("arima", y_train, 3, params)
        legacy_pred = _LEGACY_TUNABLE_PREDICT("arima", y_train, 3, params)
        assert len(real_pred) == 3
        assert all(math.isfinite(v) for v in real_pred)
        assert real_pred != legacy_pred


class TestPhase1DCVSplits:
    def test_expanding_window_has_five_non_leaking_folds(self):
        cv = ExpandingWindowCV(n_splits=5, test_size=2, min_train_size=12, step=2)
        splits = cv.split(22)
        assert len(splits) == 5
        train_sizes = []
        for split in splits:
            assert split.train_idx and split.test_idx
            assert max(split.train_idx) < min(split.test_idx)
            assert max(split.test_idx) < 22
            train_sizes.append(len(split.train_idx))
        assert train_sizes == [12, 14, 16, 18, 20]

    def test_execute_tune_reports_exact_cv_fold_count(self, spec, use_real_tunable_predict):
        response = models_router._execute_tune(spec=spec, model_id="ets", series=_make_series(), cv_config=CVConfig(n_splits=5, test_size=2, min_train_size=12, step=2), max_trials=2, metric="rmse", random_state=42)
        assert response.n_trials == 2
        assert response.grid_size == 12
        assert response.truncated is True
        assert all(trial.n_folds == 5 for trial in response.trials)
