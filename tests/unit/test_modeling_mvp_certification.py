"""Release gate for the certified fifteen-model Modeling scope."""

import math
from pathlib import Path

from apps.api.backtesting import PRODUCTION_PREDICTORS
from apps.api.model_impls.arima import _arima_fit_predict
from apps.api.model_impls.neural_runtime import neuralforecast_runtime_available
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
    "prophet",
    "tbats",
    # Task 127: Random Forest -- первый ML-адаптер (dependency_group="ml").
    "random_forest",
    # Task 128: XGBoost -- второй ML-адаптер (quantile-regression интервалы).
    "xgboost",
    # Task 129: LightGBM -- третий ML-адаптер (native API, leaf-wise).
    "lightgbm",
    # Task 130: CatBoost -- четвёртый ML-адаптер (native CatBoostRegressor,
    # Quantile:alpha интервалы, ordered boosting).
    "catboost",
    # Task 132: VAR -- первый multivariate-исполнитель контракта Task 131.
    "var",
    # Task 133: VECM -- второй multivariate-исполнитель (fold-local ранг
    # Йохансена; нативный VECMResults.predict с интервалами).
    "vecm",
    # Task 135: GARCH -- первый volatility-исполнитель контракта Task 134
    # (native arch, fold-local MLE, rescale=False; QLIKE volatility-cohort,
    # отдельный cohort: не ранжируется рядом с ETS/ARIMA).
    "garch",
    # Task 136: EGARCH -- второй volatility-исполнитель (прецедент пары
    # var/vecm; o >= 1 -- параметризация leverage/asymmetry).
    "egarch",
})

# Task 138/139/140/141: LSTM/GRU, N-BEATS, N-HiTS и TFT -- первые четыре
# исполнителя neural-runtime контракта Task 137.  Реестровые записи и
# legacy-предикторы существуют всегда (код), но readiness-членство
# честно зависит от установки опциональной dependency-группы "neural"
# (apps/api/requirements-neural.txt).
_EXPECTED_NEURAL = (
    {"lstm", "nbeats", "nhits", "tft"} if neuralforecast_runtime_available() else frozenset()
)
EXPECTED_PRODUCTION_MODEL_IDS = CERTIFIED_MODEL_IDS | _EXPECTED_NEURAL

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_certified_scope_is_exactly_nineteen_real_models_in_the_24_model_catalog():
    spec = ModelingSpec.from_yaml("rules/modeling.yaml")
    catalog = {
        model.id: family.id
        for family in spec.families
        for model in family.models
    }

    assert len(catalog) == 24
    # Task 138/139/140/141: readiness = 19 сертифицированных + lstm/
    # nbeats/nhits/tft при установленной опциональной neural-группе (см.
    # EXPECTED_PRODUCTION_MODEL_IDS).
    assert PRODUCTION_BACKTEST_MODEL_IDS == EXPECTED_PRODUCTION_MODEL_IDS
    assert PRODUCTION_DIAGNOSTICS_MODEL_IDS == EXPECTED_PRODUCTION_MODEL_IDS
    # Legacy-предикторы строятся по ЗАПИСЯМ реестра (код) -- lstm/nbeats/
    # nhits/tft входят независимо от среды; вызов без группы честно
    # отклоняется гейтом зависимостей registry.execute.
    assert frozenset(PRODUCTION_PREDICTORS) == CERTIFIED_MODEL_IDS | {"lstm", "nbeats", "nhits", "tft"}
    assert PRODUCTION_TUNING_MODEL_IDS == frozenset(
        {"ets", "ets_damped", "arima", "prophet", "tbats", "random_forest", "xgboost",
         "lightgbm", "catboost",
         # Task 133: векторный tuning -- execute_vector_tuning_plan
         # (каждый trial -- векторный backtest на тех же folds).
         "var", "vecm",
         # Task 135: volatility tuning -- execute_volatility_tuning_plan
         # (каждый trial -- volatility backtest на тех же folds, metric=qlike;
         # Task 136: egarch -- второй исполнитель того же движка).
         "garch", "egarch"}
        | _EXPECTED_NEURAL,
    )

    for model_id, family_id in catalog.items():
        capabilities = model_stage_capabilities(model_id, family_id)
        assert tuple(capabilities) == MODELING_STAGE_IDS
        actions = available_model_actions(model_id)
        if model_id in EXPECTED_PRODUCTION_MODEL_IDS:
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


def test_ci_and_api_image_install_and_probe_prophet_and_tbats_dependencies():
    """A clean release must not silently certify a reduced runtime registry."""
    workflow = (REPOSITORY_ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8-sig")
    dockerfile = (REPOSITORY_ROOT / "apps/api/Dockerfile").read_text(encoding="utf-8")
    api_requirements = (REPOSITORY_ROOT / "apps/api/requirements.txt").read_text(encoding="utf-8")

    assert "apps/api/requirements.txt" in workflow
    assert "prophet==1.4.0" in api_requirements
    assert "statsforecast==2.1.1" in api_requirements
    assert "_prophet_fit_predict" in dockerfile
    assert "_tbats_fit_predict" in dockerfile
    # Task 127/128/129/130: пробы исполняемости ML-адаптеров в release-образе.
    assert "_rf_fit_predict" in dockerfile
    assert "_xgb_fit_predict" in dockerfile
    assert "_lgb_fit_predict" in dockerfile
    assert "_cb_fit_predict" in dockerfile
    # Task 132: проба исполняемости VAR-адаптера в release-образе.
    assert "_var_fit_predict" in dockerfile
