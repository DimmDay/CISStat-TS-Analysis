"""Release gate for the certified nine-model Modeling MVP."""

import math

from apps.api.backtesting import PRODUCTION_PREDICTORS
from apps.api.model_impls.arima import _arima_fit_predict
from apps.api.model_readiness import (
    MODELING_STAGE_IDS,
    PRODUCTION_BACKTEST_MODEL_IDS,
    PRODUCTION_DIAGNOSTICS_MODEL_IDS,
    PRODUCTION_TUNING_MODEL_IDS,
    available_model_actions,
    model_stage_capabilities,
)
from src.catalog.modeling_spec_loader import ModelingSpec


CERTIFIED_MODEL_IDS = frozenset({
    "naive",
    "seasonal_naive",
    "drift",
    "mean",
    "ets",
    "ets_damped",
    "theta",
    "arima",
    "arima_auto",
})


def test_certified_scope_is_exactly_nine_real_models_in_the_24_model_catalog():
    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    catalog = {
        model.id: family.id
        for family in spec.families
        for model in family.models
    }

    assert len(catalog) == 24
    assert PRODUCTION_BACKTEST_MODEL_IDS == CERTIFIED_MODEL_IDS
    assert PRODUCTION_DIAGNOSTICS_MODEL_IDS == CERTIFIED_MODEL_IDS
    assert frozenset(PRODUCTION_PREDICTORS) == CERTIFIED_MODEL_IDS
    assert PRODUCTION_TUNING_MODEL_IDS == frozenset({"ets", "ets_damped", "arima"})

    for model_id, family_id in catalog.items():
        capabilities = model_stage_capabilities(model_id, family_id)
        assert tuple(capabilities) == MODELING_STAGE_IDS
        actions = available_model_actions(model_id)
        if model_id in CERTIFIED_MODEL_IDS:
            assert "backtest" in actions
            assert "diagnostics" in actions
            assert ("tune" in actions) is (model_id in PRODUCTION_TUNING_MODEL_IDS)
        else:
            assert actions == []
            assert capabilities["backtest"]["status"] == "not_implemented"


def test_arima_grid_handles_the_minimum_expanding_window_fold():
    """Statsmodels upgrades must not break valid grid trials on a two-point fold."""
    forecast = _arima_fit_predict([100.0, 101.0], 2, (2, 1, 2))

    assert len(forecast) == 2
    assert all(math.isfinite(value) for value in forecast)
