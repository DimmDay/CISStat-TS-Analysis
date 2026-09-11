from apps.api.model_impls.neural_runtime import neuralforecast_runtime_available
from apps.api.routers.models import _compute_candidates
from apps.api.schemas import CandidatesRequest, DataProfileRequest

# Task 138: lstm -- первый исполнитель neural-runtime контракта Task 137;
# neural-runtime -- опциональная dependency-группа (requirements-neural.txt),
# поэтому членство lstm в readiness честно зависит от проба пакета.
_HAS_NEURAL = neuralforecast_runtime_available()
_CATALOG_ONLY_NEURAL = () if _HAS_NEURAL else ("lstm",)


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
                     "random_forest", "xgboost", "lightgbm", "catboost"):
        assert candidates[model_id].platform_status == "ready"
        assert "backtest" in candidates[model_id].available_actions
        assert "diagnostics" in candidates[model_id].available_actions
        assert candidates[model_id].blocking_reason is None

    assert response.capability_contract_version == "model-capabilities-v1"
    assert len(candidates["naive"].stage_capabilities) == 11
    assert candidates["naive"].stage_capabilities["tuning"].status == "not_applicable"
    assert candidates["ets"].stage_capabilities["tuning"].status == "available"

    # Task 138: при установленном neural-runtime lstm -- production-модель
    # (20-я), tft/nbeats/nhits остаются catalog_only (Tasks 139-141).
    for model_id in ("tft", "nbeats", "nhits") + _CATALOG_ONLY_NEURAL:
        assert candidates[model_id].platform_status == "catalog_only"
        assert candidates[model_id].available_actions == []
        assert candidates[model_id].stage_capabilities["backtest"].status == "not_implemented"
        assert "production" in candidates[model_id].blocking_reason.lower()
    if _HAS_NEURAL:
        lstm = candidates["lstm"]
        assert lstm.platform_status == "ready"
        assert "backtest" in lstm.available_actions
        assert lstm.stage_capabilities["backtest"].status == "available"
        assert lstm.blocking_reason is None


def test_candidate_statistics_report_runtime_availability_separately():
    response = _compute_candidates(CandidatesRequest(
        profile=_broad_profile(),
        min_level="CONDITIONALLY_APPLICABLE",
    ))

    # Task 130: catboost стал production-моделью -- runnable 15, catalog-only 9.
    # Task 132: var стал production-моделью (16-я); на n_series=1 он
    # production+blocked (F01: требует >= 2 рядов) -- catalog-only 8, blocked 1.
    # Task 133: vecm -- 17-я; на n_series=1 также production+blocked (F01) --
    # catalog-only 7, blocked 2.
    # Task 135: garch -- 18-я (volatility-исполнитель контракта Task 134);
    # на macro-профиле честно blocked domain-гейтом (volatility-семейство
    # предназначено financial/price) -- blocked 3, catalog-only 6.
    # Task 136: egarch -- 19-я (второй volatility-исполнитель, прецедент
    # var/vecm); domain-гейт тот же -- blocked 4, catalog-only 5.
    # Task 138: lstm -- 20-я (первый исполнитель neural-runtime контракта
    # Task 137); на neural-воркере runnable 16 / catalog-only 4, без
    # опциональной группы -- честные 15/5 (Task 136).
    if _HAS_NEURAL:
        assert response.statistics.runnable_candidates == 16
        assert response.statistics.catalog_only_candidates == 4
    else:
        assert response.statistics.runnable_candidates == 15
        assert response.statistics.catalog_only_candidates == 5
    assert response.statistics.blocked_candidates == 4
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
    # Task 127/128/129/130: random_forest, xgboost, lightgbm и catboost тоже
    # объявляют min_observations=100 и на коротком профиле блокируются вместе
    # с TBATS -- explain, не fake.  Task 132: var блокируется F01 (n_series=1
    # < min_series=2) тем же честным explain-механизмом.
    for model_id, name in (("random_forest", "Random Forest"), ("xgboost", "XGBoost"),
                           ("lightgbm", "LightGBM"), ("catboost", "CatBoost")):
        candidate = next(item for item in response.catalog if item.model_id == model_id)
        assert candidate.platform_status == "ready"
        assert candidate.available_actions == []
        assert candidate.blocking_reason == f"Недостаточно данных: 60 < 100 (требуется {name})"
    var_candidate = next(item for item in response.catalog if item.model_id == "var")
    assert var_candidate.platform_status == "ready"
    assert var_candidate.available_actions == []
    assert var_candidate.blocking_reason
    # Task 133: vecm блокируется F01 тем же честным explain-механизмом
    # (n_series=1 < min_series=2).
    vecm_candidate = next(item for item in response.catalog if item.model_id == "vecm")
    assert vecm_candidate.platform_status == "ready"
    assert vecm_candidate.available_actions == []
    assert vecm_candidate.blocking_reason
    # Task 135: garch на коротком профиле (60 < 100) блокируется тем же
    # честным explain-механизмом.
    garch_candidate = next(item for item in response.catalog if item.model_id == "garch")
    assert garch_candidate.platform_status == "ready"
    assert garch_candidate.available_actions == []
    assert garch_candidate.blocking_reason
    # Task 136: egarch -- второй volatility-исполнитель; тот же честный
    # explain на коротком профиле (60 < 100).
    egarch_candidate = next(item for item in response.catalog if item.model_id == "egarch")
    assert egarch_candidate.platform_status == "ready"
    assert egarch_candidate.available_actions == []
    assert egarch_candidate.blocking_reason
    # Task 138: lstm на коротком профиле честно блокируется
    # min_observations=200 (60 < 200) тем же explain-механизмом.
    lstm_candidate = next(item for item in response.catalog if item.model_id == "lstm")
    assert lstm_candidate.blocking_reason == "Недостаточно данных: 60 < 200 (требуется LSTM / GRU)"
    if _HAS_NEURAL:
        assert lstm_candidate.platform_status == "ready"
        assert lstm_candidate.available_actions == []
        assert response.statistics.blocked_candidates == 10
    else:
        assert lstm_candidate.platform_status == "catalog_only"
        assert response.statistics.blocked_candidates == 9
