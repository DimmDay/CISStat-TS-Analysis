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

    for model_id in ("naive", "ets", "theta", "arima", "arima_auto"):
        assert candidates[model_id].platform_status == "ready"
        assert "backtest" in candidates[model_id].available_actions
        assert candidates[model_id].blocking_reason is None

    for model_id in ("prophet", "tbats", "xgboost", "lightgbm", "catboost", "lstm", "tft", "nbeats", "nhits"):
        assert candidates[model_id].platform_status == "catalog_only"
        assert candidates[model_id].available_actions == []
        assert "production" in candidates[model_id].blocking_reason.lower()


def test_candidate_statistics_report_runtime_availability_separately():
    response = _compute_candidates(CandidatesRequest(
        profile=_broad_profile(),
        min_level="CONDITIONALLY_APPLICABLE",
    ))

    assert response.statistics.runnable_candidates == 9
    assert response.statistics.catalog_only_candidates > 0
    assert (
        response.statistics.runnable_candidates
        + response.statistics.catalog_only_candidates
        == response.statistics.total_candidates
    )
