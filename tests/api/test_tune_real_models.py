"""Phase 1-D integration tests: tune grid/CV over real ETS and ARIMA fits."""
from __future__ import annotations

import math
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException

from apps.api.cv import ExpandingWindowCV
from apps.api.model_impls.arima import _arima_fit_predict
from apps.api.model_impls.ets import _ets_fit_predict
from apps.api.routers import models as models_router
from apps.api.schemas import CVConfig
from src.catalog.modeling_spec_loader import ModelingSpec

SPEC_PATH = "rules/modeling.yaml"


def _make_series(n: int = 72) -> List[float]:
    """Positive deterministic trend+seasonality series for real statsmodels."""
    return [
        100.0
        + 0.45 * t
        + 7.0 * math.sin(2.0 * math.pi * t / 12.0)
        + 0.5 * math.cos(2.0 * math.pi * t / 6.0)
        for t in range(n)
    ]


@pytest.fixture(scope="module")
def spec() -> ModelingSpec:
    return ModelingSpec.from_yaml(SPEC_PATH)


def _real_tunable_predict(
    model_id: str,
    y_train: List[float],
    test_size: int,
    params: Dict[str, Any],
) -> List[float]:
    """Direct reference to the real Phase 6-P0 implementations."""
    if model_id == "ets":
        return _ets_fit_predict(
            y_train=y_train,
            n_test=test_size,
            seasonal_period=int(params["seasonal_periods"]),
            damped=bool(params["damped_trend"]),
            trend=params.get("trend", "add"),
            seasonal=params.get("seasonal"),
        )
    if model_id == "arima":
        order = (
            int(params["p"]),
            int(params["d"]),
            int(params["q"]),
        )
        return _arima_fit_predict(y_train, test_size, order)
    raise AssertionError(f"Phase 1-D real adapter does not support {model_id}")


@pytest.fixture
def use_real_tunable_predict(monkeypatch):
    monkeypatch.setattr(models_router, "_tunable_predict", _real_tunable_predict)


class TestPhase1DBaselineSkip:
    @pytest.mark.parametrize(
        "model_id",
        ["naive", "seasonal_naive", "drift", "mean"],
    )
    def test_baseline_is_not_tunable(self, spec, model_id):
        with pytest.raises(HTTPException) as exc_info:
            models_router._execute_tune(
                spec=spec,
                model_id=model_id,
                series=_make_series(),
                cv_config=CVConfig(n_splits=3, test_size=2),
                max_trials=None,
                metric="rmse",
                random_state=42,
            )
        assert exc_info.value.status_code == 422
        assert "param_space" in str(exc_info.value)


class TestPhase1DEtsRealGrid:
    def test_ets_grid_runs_real_statsmodels(self, spec, use_real_tunable_predict):
        response = models_router._execute_tune(
            spec=spec,
            model_id="ets",
            series=_make_series(),
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=None,
            metric="rmse",
            random_state=42,
        )
        assert response.grid_size == 12
        assert response.n_trials == 12
        assert response.truncated is False
        assert response.cv_config.n_splits == 3
        assert all(trial.n_folds == 3 for trial in response.trials)
        assert response.best_params in [trial.params for trial in response.trials]
        for trial in response.trials:
            assert math.isfinite(trial.metrics.rmse)
            assert math.isfinite(trial.metrics.mae)
            assert trial.metrics.rmse >= 0
            assert trial.metrics.mae >= 0
        assert len({round(t.metrics.rmse, 8) for t in response.trials}) >= 2

    def test_ets_real_predictions_are_not_synthetic(self, use_real_tunable_predict):
        y_train = _make_series(48)
        params = {
            "trend": "add",
            "seasonal": "add",
            "seasonal_periods": 12,
            "damped_trend": False,
        }
        real_pred = _real_tunable_predict("ets", y_train, 3, params)
        assert len(real_pred) == 3
        assert all(math.isfinite(v) for v in real_pred)


class TestPhase1DArimaRealGrid:
    @pytest.mark.filterwarnings("ignore::UserWarning")
    @pytest.mark.filterwarnings(
        "ignore::statsmodels.tools.sm_exceptions.ConvergenceWarning"
    )
    def test_arima_grid_runs_real_statsmodels(self, spec, use_real_tunable_predict):
        response = models_router._execute_tune(
            spec=spec,
            model_id="arima",
            series=_make_series(),
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=None,
            metric="rmse",
            random_state=42,
        )
        assert response.grid_size == 18
        assert response.n_trials == 18
        assert response.truncated is False
        assert all(trial.n_folds == 3 for trial in response.trials)
        for trial in response.trials:
            assert math.isfinite(trial.metrics.rmse)
            assert math.isfinite(trial.metrics.mae)
            assert trial.metrics.rmse >= 0
            assert trial.metrics.mae >= 0
        assert len({round(t.metrics.rmse, 8) for t in response.trials}) >= 2

    @pytest.mark.filterwarnings("ignore::UserWarning")
    @pytest.mark.filterwarnings(
        "ignore::statsmodels.tools.sm_exceptions.ConvergenceWarning"
    )
    def test_arima_real_prediction_is_not_synthetic(self, use_real_tunable_predict):
        y_train = _make_series(48)
        params = {"p": 1, "d": 1, "q": 1}
        real_pred = _real_tunable_predict("arima", y_train, 3, params)
        assert len(real_pred) == 3
        assert all(math.isfinite(v) for v in real_pred)


class TestPhase1DCVSplits:
    def test_expanding_window_has_five_non_leaking_folds(self):
        cv = ExpandingWindowCV(
            n_splits=5,
            test_size=2,
            min_train_size=12,
            step=2,
        )
        splits = cv.split(22)
        assert len(splits) == 5
        assert [len(s.train_idx) for s in splits] == [12, 14, 16, 18, 20]
        for split in splits:
            assert split.train_idx
            assert split.test_idx
            assert max(split.train_idx) < min(split.test_idx)
            assert max(split.test_idx) < 22

    def test_execute_tune_reports_exact_cv_fold_count(
        self, spec, use_real_tunable_predict
    ):
        response = models_router._execute_tune(
            spec=spec,
            model_id="ets",
            series=_make_series(),
            cv_config=CVConfig(
                n_splits=5,
                test_size=2,
                min_train_size=12,
                step=2,
            ),
            max_trials=2,
            metric="rmse",
            random_state=42,
        )
        assert response.n_trials == 2
        assert response.grid_size == 12
        assert response.truncated is True
        assert all(trial.n_folds == 5 for trial in response.trials)
