from apps.api.model_impls.neural_runtime import neuralforecast_runtime_available
from apps.api.model_readiness import PRODUCTION_BACKTEST_MODEL_IDS
from apps.api.routers.models import _compute_candidates
from apps.api.schemas import CandidatesRequest, DataProfileRequest

# Task 138/139/140/141: lstm, nbeats, nhits и tft -- первые четыре
# исполнителя neural-runtime контракта Task 137; neural-runtime --
# опциональная dependency-группа (requirements-neural.txt), поэтому
# членство lstm/nbeats/nhits/tft в readiness честно зависит от проба
# пакета.
_HAS_NEURAL = neuralforecast_runtime_available()
_CATALOG_ONLY_NEURAL = () if _HAS_NEURAL else ("lstm", "nbeats", "nhits", "tft")

# Task 144: tbats readiness зависит от statsforecast (core-зависимость
# apps/api/requirements.txt, но среда разработки может быть частичной).
_HAS_STATSFORECAST = "tbats" in PRODUCTION_BACKTEST_MODEL_IDS


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
    catalog = {item.model_id: item for item in response.catalog}

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

    # Task 138/139/140/141: при установленном neural-runtime lstm,
    # nbeats, nhits и tft -- production-модели (20-я -- 23-я).
    # Task 142: deepar -- 24-я (пятый исполнитель, panel-постановка):
    # на macro-профиле (n_series=1) он production+blocked правилом F05
    # (панель min_series=5) -- platform_status="ready" в ПОЛНОМ каталоге
    # (catalog), available_actions пусты, stage backtest -- "blocked";
    # в отфильтрованный пул кандидатов (candidates) он не входит.  Без
    # опциональной группы deepar вместе с остальной нейро-четвёркой
    # честно catalog_only.
    if _HAS_NEURAL:
        deepar = catalog["deepar"]
        assert deepar.platform_status == "ready"
        assert deepar.available_actions == []
        assert deepar.stage_capabilities["backtest"].status == "blocked"
        assert deepar.blocking_reason
        for model_id in ("lstm", "nbeats", "nhits", "tft"):
            candidate = candidates[model_id]
            assert candidate.platform_status == "ready"
            assert "backtest" in candidate.available_actions
            assert candidate.stage_capabilities["backtest"].status == "available"
            assert candidate.blocking_reason is None
    else:
        for model_id in ("deepar",) + _CATALOG_ONLY_NEURAL:
            assert catalog[model_id].platform_status == "catalog_only"
            assert catalog[model_id].available_actions == []
            assert catalog[model_id].stage_capabilities["backtest"].status == "not_implemented"
            assert "production" in catalog[model_id].blocking_reason.lower()


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
    # Task 138/139/140/141: lstm -- 20-я, nbeats -- 21-я, nhits -- 22-я,
    # tft -- 23-я (исполнители neural-runtime контракта Task 137);
    # Task 142: deepar -- 24-я (пятый исполнитель, panel-постановка).  На
    # neural-воркере runnable 19 (deepar на n_series=1 excluded правилом
    # F05) / catalog-only 0 / blocked 5 (var, vecm, garch, egarch,
    # deepar); без опциональной группы -- честные 15/5/4 (Task 136).
    if _HAS_NEURAL:
        assert response.statistics.runnable_candidates == 19
        assert response.statistics.catalog_only_candidates == 0
        assert response.statistics.blocked_candidates == 5
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
def test_not_recommended_soft_window_warns_but_allows_in_catalog():
    """Task 144: NOT_RECOMMENDED + platform ready -- «предупредить, но не
    запретить» (уровень 3 исходной 4-уровневой шкалы).

    TBATS (soft 50) и четвёрка tree_ml (soft 40) на профиле n=60 попадают
    в мягкое окно истории: правило D07 даёт NOT_RECOMMENDED с явным
    предупреждением в message, available_actions НЕ пусты, blocking_reason
    снят. NOT_APPLICABLE (уровень 4) остаётся полностью заблокированным:
    var/vecm -- F01 (n_series=1 < min_series=2), garch/egarch -- F04
    (60 < 100, без soft), нейро-пятёрка -- F04 (60 < 200) / F05 (deepar).
    """
    from apps.api.model_readiness import available_model_actions

    profile = _broad_profile().model_copy(update={"n_observations": 60})

    response = _compute_candidates(CandidatesRequest(
        profile=profile,
        min_level="CONDITIONALLY_APPLICABLE",
    ))
    catalog = {item.model_id: item for item in response.catalog}

    # -- Мягкое окно: warn-but-allow ------------------------------------
    soft_specs = {
        "tbats": ("50", _HAS_STATSFORECAST),
        "random_forest": ("40", True),
        "xgboost": ("40", True),
        "lightgbm": ("40", True),
        "catboost": ("40", True),
    }
    for model_id, (soft_value, is_ready) in soft_specs.items():
        candidate = catalog[model_id]
        assert candidate.level == "NOT_RECOMMENDED", model_id
        assert candidate.rule_id == "D07", model_id
        assert candidate.message, model_id
        assert "60" in candidate.message and "100" in candidate.message, model_id
        assert soft_value in candidate.message, model_id
        assert "осторожностью" in candidate.message, model_id
        if is_ready:
            assert candidate.platform_status == "ready", model_id
            assert candidate.available_actions, model_id
            assert candidate.available_actions == available_model_actions(model_id), model_id
            assert "backtest" in candidate.available_actions, model_id
            assert candidate.blocking_reason is None, model_id
        else:
            # Без statsforecast tbats честно catalog_only: действий нет,
            # но причина -- отсутствие реализации, а не применимость.
            assert candidate.platform_status == "catalog_only", model_id
            assert candidate.available_actions == []

    # NOT_RECOMMENDED-модели по-прежнему НЕ входят в суженный пул
    # кандидатов (min_level default = CONDITIONALLY_APPLICABLE),
    # но присутствуют в полном каталоге.
    candidate_ids = {item.model_id for item in response.candidates}
    assert candidate_ids.isdisjoint(soft_specs)

    # -- NOT_APPLICABLE: граница уровней 3 и 4 не стирается -------------
    var_candidate = catalog["var"]
    assert var_candidate.level == "NOT_APPLICABLE"
    assert var_candidate.available_actions == []
    assert var_candidate.blocking_reason
    vecm_candidate = catalog["vecm"]
    assert vecm_candidate.available_actions == []
    assert vecm_candidate.blocking_reason
    garch_candidate = catalog["garch"]
    assert garch_candidate.level == "NOT_APPLICABLE"
    # macro-домен: GARCH отсекается F02 (финансовая модель) раньше F04 --
    # в любом случае полностью заблокирована (уровень 4 не тронут).
    assert garch_candidate.available_actions == []
    assert garch_candidate.blocking_reason
    egarch_candidate = catalog["egarch"]
    assert egarch_candidate.available_actions == []
    assert egarch_candidate.blocking_reason
    # Task 138-142: нейро-пятёрка на коротком профиле честно блокируется
    # F04 (60 < 200) / F05 (deepar -- панель); причина видна только при
    # установленной neural-группе, иначе блокирует отсутствие реализации.
    if _HAS_NEURAL:
        assert catalog["deepar"].blocking_reason == "Модель DeepAR требует минимум 5 рядов"
        assert catalog["lstm"].blocking_reason == "Недостаточно данных: 60 < 200 (требуется LSTM / GRU)"
        assert catalog["nbeats"].blocking_reason == "Недостаточно данных: 60 < 200 (требуется N-BEATS)"
        assert catalog["nhits"].blocking_reason == "Недостаточно данных: 60 < 200 (требуется N-HiTS)"
        assert catalog["tft"].blocking_reason == "Недостаточно данных: 60 < 200 (требуется Temporal Fusion Transformer)"
        for model_id in ("lstm", "nbeats", "nhits", "tft", "deepar"):
            assert catalog[model_id].platform_status == "ready", model_id
            assert catalog[model_id].available_actions == [], model_id
        # 4 ready-but-blocked (var/vecm/garch/egarch) + 5 нейро = 9
        assert response.statistics.blocked_candidates == 9
    else:
        for model_id in ("lstm", "nbeats", "nhits", "tft", "deepar"):
            assert catalog[model_id].platform_status == "catalog_only", model_id
            assert catalog[model_id].blocking_reason == (
                "Production-реализация модели ещё не подключена; "
                "фиктивные метрики запрещены."
            ), model_id
        # Только var/vecm/garch/egarch остаются ready-but-blocked
        assert response.statistics.blocked_candidates == 4
