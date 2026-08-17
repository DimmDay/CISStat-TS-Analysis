"""Regression tests for production Tune -> real ETS/ARIMA dispatch."""
from __future__ import annotations

import math

import pytest

from apps.api.routers import models as models_router
from apps.api.schemas import CVConfig
from src.catalog.modeling_spec_loader import ModelingSpec

SPEC_PATH = "rules/modeling.yaml"


def _series(n: int = 72) -> list[float]:
    return [
        100.0 + 0.4 * t + 6.0 * math.sin(2.0 * math.pi * t / 12.0)
        for t in range(n)
    ]


@pytest.fixture(scope="module")
def spec() -> ModelingSpec:
    return ModelingSpec.from_yaml(SPEC_PATH)


class TestProductionTuneDispatch:
    def test_ets_tune_uses_real_predictor(self, spec, monkeypatch):
        calls = []
        real = models_router.tune_ets_predict

        def spy(y_train, n_test, params):
            calls.append(dict(params))
            return real(y_train, n_test, params)

        monkeypatch.setattr(models_router, "tune_ets_predict", spy)
        response = models_router._execute_tune(
            spec=spec,
            model_id="ets",
            series=_series(),
            cv_config=CVConfig(n_splits=2, test_size=2),
            max_trials=2,
            metric="rmse",
            random_state=42,
        )
        assert response.n_trials == 2
        assert len(calls) == 4
        assert all("trend" in params for params in calls)
        assert all(math.isfinite(trial.metrics.rmse) for trial in response.trials)

    def test_arima_tune_uses_real_predictor(self, spec, monkeypatch):
        calls = []
        real = models_router.tune_arima_predict

        def spy(y_train, n_test, params):
            calls.append(dict(params))
            return real(y_train, n_test, params)

        monkeypatch.setattr(models_router, "tune_arima_predict", spy)
        response = models_router._execute_tune(
            spec=spec,
            model_id="arima",
            series=_series(),
            cv_config=CVConfig(n_splits=2, test_size=2),
            max_trials=2,
            metric="rmse",
            random_state=42,
        )
        assert response.n_trials == 2
        assert len(calls) == 4
        assert all(set(("p", "d", "q")) <= params.keys() for params in calls)
        assert all(math.isfinite(trial.metrics.rmse) for trial in response.trials)

    def test_unsupported_tunable_model_fails_explicitly(self, spec):
        with pytest.raises(Exception) as exc_info:
            models_router._execute_tune(
                spec=spec,
                model_id="theta",
                series=_series(),
                cv_config=CVConfig(n_splits=2, test_size=2),
                max_trials=2,
                metric="rmse",
                random_state=42,
            )
        assert "param_space" in str(exc_info.value)

    def test_multiplicative_ets_trial_is_not_silently_replaced(self):
        negative_series = [-10.0 + 0.1 * t for t in range(48)]
        with pytest.raises(ValueError, match="strictly positive"):
            models_router._tunable_predict(
                "ets",
                negative_series,
                2,
                {
                    "trend": "mul",
                    "seasonal": "add",
                    "seasonal_periods": 12,
                    "damped_trend": False,
                },
            )