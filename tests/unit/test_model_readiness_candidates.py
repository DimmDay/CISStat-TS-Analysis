from apps.api.routers.models import _compute_candidates
from apps.api.schemas import CandidatesRequest, DataProfileRequest


def _broad_profile() -> DataProfileRequest:
    return DataProfileRequest(
        n_observations=500,
        n_series=1,
        n_exogenous=3,
        is_regular=True,
        frequency="M",
        has_seasonality=True,
        seasonal_periods=[12],
        is_stationary_or_diffable=True,
        domain="macro",
        gpu_available=True,
        feature_engineering_applied=True,
    )


def test_candidate_contract_separates_methodological_applicability_from_runtime_readiness():
    response = _compute_candidates(CandidatesRequest(
        profile=_broad_profile(),
        min_level="CONDITIONALLY_APPLICABLE",
    ))
    candidates = {item.model_id: item for item in response.candidates}

    for model_id in ("naive", "ets", "theta", "arima", "arima_auto", "prophet", "tbats",
                     "random_forest", "xgboost", "lightgbm"):
        assert candidates[model_id].platform_status == "ready"
        assert "backtest" in candidates[model_id].available_actions
        assert "diagnostics" in candidates[model_id].available_actions
        assert candidates[model_id].blocking_reason is None

    assert response.capability_contract_version == "model-capabilities-v1"
    assert len(candidates["naive"].stage_capabilities) == 11
    assert candidates["naive"].stage_capabilities["tuning"].status == "not_applicable"
    assert candidates["ets"].stage_capabilities["tuning"].status == "available"

    for model_id in ("catboost", "lstm", "tft", "nbeats", "nhits"):
        assert candidates[model_id].platform_status == "catalog_only"
        assert candidates[model_id].available_actions == []
        assert candidates[model_id].stage_capabilities["backtest"].status == "not_implemented"
        assert "production" in candidates[model_id].blocking_reason.lower()


def test_candidate_statistics_report_runtime_availability_separately():
    response = _compute_candidates(CandidatesRequest(
        profile=_broad_profile(),
        min_level="CONDITIONALLY_APPLICABLE",
    ))

    # Task 129: lightgbm стал production-моделью -- runnable 14, catalog-only 10.
    assert response.statistics.runnable_candidates == 14
    assert response.statistics.catalog_only_candidates == 10
    assert response.statistics.total_models_in_spec == 24


def test_response_keeps_filtered_candidate_pool_and_exposes_complete_catalog():
    response = _compute_candidates(CandidatesRequest(
        profile=_broad_profile(),
        min_level="CONDITIONALLY_APPLICABLE",
    ))

    candidate_ids = {item.model_id for item in response.candidates}
    catalog = {item.model_id: item for item in response.catalog}

    assert len(response.catalog) == response.statistics.total_models_in_spec == 24
    assert len(response.candidates) < len(response.catalog)
    assert "var" not in candidate_ids
    assert catalog["var"].level == "NOT_APPLICABLE"
    assert catalog["var"].available_actions == []
    assert catalog["var"].message


def test_tbats_is_connected_but_explains_when_current_training_fold_is_too_short():
    profile = _broad_profile().model_copy(update={"n_observations": 60})

    response = _compute_candidates(CandidatesRequest(
        profile=profile,
        min_level="CONDITIONALLY_APPLICABLE",
    ))
    tbats = next(item for item in response.catalog if item.model_id == "tbats")

    assert tbats.platform_status == "ready"
    assert tbats.available_actions == []
    assert tbats.blocking_reason == "Недостаточно данных: 60 < 100 (требуется TBATS)"
    # Task 127/128/129: random_forest, xgboost и lightgbm тоже объявляют
    # min_observations=100 и на коротком профиле блокируются вместе с
    # TBATS -- explain, не fake.
    for model_id, name in (("random_forest", "Random Forest"), ("xgboost", "XGBoost"),
                           ("lightgbm", "LightGBM")):
        candidate = next(item for item in response.catalog if item.model_id == model_id)
        assert candidate.platform_status == "ready"
        assert candidate.available_actions == []
        assert candidate.blocking_reason == f"Недостаточно данных: 60 < 100 (требуется {name})"
    assert response.statistics.blocked_candidates == 4
