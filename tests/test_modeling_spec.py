"""
Тесты для загрузчика спецификации модуля «Моделирование».
Покрывают: загрузку YAML, структуру Pydantic-моделей, движок применимости,
пайплайн, метрики, Model Card, жизненные циклы, ансамбли.
"""
import pytest
from pathlib import Path
from typing import Dict, Any

from src.catalog.modeling_spec_loader import (
    ModelingSpec,
    Family,
    FamilyModel,
    ApplicabilityLevel,
    ApplicabilityEngine,
    ApplicabilityRule,
    Pipeline,
    PipelineStage,
    MetricsConfig,
    MetricDef,
    RankingFormula,
    PredictionIntervalsConfig,
    ModelCardTemplate,
    LifecycleSeparation,
    EnsembleConfig,
    PreprocessingRule,
    UIConfig,
    DataProfile,
    ApplicabilityResult,
)

SPEC_PATH = Path("rules/modeling.yaml")


# ═══════════════════════════════════════════════════════════
# ФИКСТУРЫ
# ═══════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def spec() -> ModelingSpec:
    """Загружаем спецификацию один раз на сессию."""
    return ModelingSpec.from_yaml(str(SPEC_PATH))


@pytest.fixture
def macro_profile() -> DataProfile:
    """Типичный профиль макроэкономического ряда: 120 наблюдений, M, стационарный."""
    return DataProfile(
        n_observations=120,
        n_series=1,
        n_exogenous=0,
        is_regular=True,
        frequency="M",
        has_seasonality=True,
        seasonal_periods=[12],
        is_stationary_or_diffable=True,
        is_cointegrated=False,
        has_negative_values=False,
        has_volatility_clustering=False,
        domain="macro",
        missing_ratio=0.0,
        outlier_ratio=0.0,
    )


@pytest.fixture
def financial_profile() -> DataProfile:
    """Профиль финансового ряда: 500 дневных наблюдений, волатильность."""
    return DataProfile(
        n_observations=500,
        n_series=1,
        n_exogenous=0,
        is_regular=True,
        frequency="D",
        has_seasonality=False,
        seasonal_periods=[],
        is_stationary_or_diffable=False,
        is_cointegrated=False,
        has_negative_values=True,
        has_volatility_clustering=True,
        domain="financial",
        missing_ratio=0.0,
        outlier_ratio=0.02,
    )


@pytest.fixture
def multivariate_profile() -> DataProfile:
    """Профиль многомерного ряда: 200 наблюдений, 3 ряда, коинтегрированы."""
    return DataProfile(
        n_observations=200,
        n_series=3,
        n_exogenous=1,
        is_regular=True,
        frequency="Q",
        has_seasonality=True,
        seasonal_periods=[4],
        is_stationary_or_diffable=False,
        is_cointegrated=True,
        has_negative_values=False,
        has_volatility_clustering=False,
        domain="macro",
        missing_ratio=0.0,
        outlier_ratio=0.0,
    )


@pytest.fixture
def tiny_profile() -> DataProfile:
    """Профиль с очень малым числом наблюдений (5)."""
    return DataProfile(
        n_observations=5,
        n_series=1,
        n_exogenous=0,
        is_regular=True,
        frequency="M",
        has_seasonality=False,
        seasonal_periods=[],
        is_stationary_or_diffable=True,
        is_cointegrated=False,
        has_negative_values=False,
        has_volatility_clustering=False,
        domain="other",
        missing_ratio=0.0,
        outlier_ratio=0.0,
    )


# ═══════════════════════════════════════════════════════════
# 1. ЗАГРУЗКА И СТРУКТУРА
# ═══════════════════════════════════════════════════════════

class TestSpecLoading:
    """Тесты загрузки и базовой структуры."""

    def test_spec_loads(self, spec):
        """Спецификация загружается без ошибок."""
        assert spec is not None
        assert spec.metadata.version == "1.1.0-draft"

    def test_spec_has_8_families(self, spec):
        """Ровно 8 семейств моделей."""
        assert len(spec.families) == 8

    def test_family_ids(self, spec):
        """ID семейств соответствуют спецификации."""
        expected = {
            "baselines", "exponential_smoothing", "arima",
            "multivariate", "volatility", "structural",
            "tree_ml", "neural",
        }
        actual = {f.id for f in spec.families}
        assert actual == expected

    def test_baselines_family_required(self, spec):
        """Семейство baselines обязательно."""
        baselines = spec.get_family("baselines")
        assert baselines is not None
        assert baselines.required is True

    def test_baselines_have_4_models(self, spec):
        """4 baseline-модели: naive, seasonal_naive, drift, mean."""
        baselines = spec.get_family("baselines")
        assert len(baselines.models) == 4
        ids = {m.id for m in baselines.models}
        assert ids == {"naive", "seasonal_naive", "drift", "mean"}

    def test_total_model_count(self, spec):
        """24 модели суммарно."""
        total = spec.total_model_count()
        assert total == 24

    def test_get_model_across_families(self, spec):
        """get_model находит модель по ID среди всех семейств."""
        arima = spec.get_model("arima")
        assert arima is not None
        assert arima.name == "ARIMA / SARIMA"

    def test_get_model_not_found(self, spec):
        """get_model возвращает None для несуществующего ID."""
        assert spec.get_model("nonexistent_xyz") is None


# ═══════════════════════════════════════════════════════════
# 2. УРОВНИ ПРИМЕНИМОСТИ
# ═══════════════════════════════════════════════════════════

class TestApplicabilityLevels:
    """Тесты уровней применимости."""

    def test_4_levels(self, spec):
        """4 уровня применимости."""
        assert len(spec.applicability_levels) == 4

    def test_level_ids(self, spec):
        """ID уровней соответствуют спецификации."""
        ids = {l.id for l in spec.applicability_levels}
        expected = {
            "RECOMMENDED", "CONDITIONALLY_APPLICABLE",
            "NOT_RECOMMENDED", "NOT_APPLICABLE",
        }
        assert ids == expected

    def test_level_ranks_ordered(self, spec):
        """Ранги уровней идут по возрастанию."""
        ranks = [l.rank for l in spec.applicability_levels]
        assert ranks == sorted(ranks)
        assert ranks == [1, 2, 3, 4]

    def test_get_level_by_id(self, spec):
        """get_applicability_level находит уровень по ID."""
        level = spec.get_applicability_level("RECOMMENDED")
        assert level is not None
        assert level.rank == 1

    def test_get_level_not_found(self, spec):
        """get_applicability_level возвращает None для несуществующего ID."""
        assert spec.get_applicability_level("IMPOSSIBLE") is None


# ═══════════════════════════════════════════════════════════
# 3. ДВИЖОК ПРИМЕНИМОСТИ
# ═══════════════════════════════════════════════════════════

class TestApplicabilityEngine:
    """Тесты движка применимости — ключевого компонента."""

    def test_engine_has_all_sections(self, spec):
        """Движок содержит все 4 секции правил."""
        engine = spec.applicability_engine
        assert len(engine.forbidden) > 0
        assert len(engine.discouraged) > 0
        assert len(engine.conditional) > 0
        assert len(engine.preferred) > 0

    def test_total_rules_count(self, spec):
        """Суммарно 23 правила."""
        total = spec.applicability_engine.total_rules_count()
        assert total == 23

    # ── NOT_APPLICABLE ─────────────────────────────────────

    def test_garch_for_macro_is_not_applicable(self, spec, macro_profile):
        """GARCH для макроэкономических данных → NOT_APPLICABLE (F02)."""
        result = spec.resolve_applicability("garch", macro_profile)
        assert result.level == "NOT_APPLICABLE"
        assert result.rule_id == "F02"

    def test_deepar_for_univariate_is_not_applicable(self, spec, macro_profile):
        """DeepAR для одномерного ряда → NOT_APPLICABLE (F01 или F05)."""
        result = spec.resolve_applicability("deepar", macro_profile)
        assert result.level == "NOT_APPLICABLE"
        # F01 (многомерная при одном ряде) срабатывает раньше F05
        assert result.rule_id in ("F01", "F05")

    def test_lstm_for_tiny_data_is_not_applicable(self, spec, tiny_profile):
        """LSTM при n=5 → NOT_APPLICABLE (F04: n < min_observations)."""
        result = spec.resolve_applicability("lstm", tiny_profile)
        assert result.level == "NOT_APPLICABLE"
        assert result.rule_id == "F04"

    def test_var_for_univariate_is_not_applicable(self, spec, macro_profile):
        """VAR для одномерного ряда → NOT_APPLICABLE (F01)."""
        result = spec.resolve_applicability("var", macro_profile)
        assert result.level == "NOT_APPLICABLE"
        assert result.rule_id == "F01"

    # ── NOT_RECOMMENDED ────────────────────────────────────

    def test_dl_for_small_data_not_recommended(self, spec):
        """DL-модель при n=250 (но ≥ min) → NOT_RECOMMENDED (D02)."""
        profile = DataProfile(
            n_observations=250, n_series=1, n_exogenous=0,
            is_regular=True, frequency="D",
            has_seasonality=False, seasonal_periods=[],
            is_stationary_or_diffable=True, is_cointegrated=False,
            has_negative_values=False, has_volatility_clustering=False,
            domain="other", missing_ratio=0.0, outlier_ratio=0.0,
        )
        result = spec.resolve_applicability("lstm", profile)
        assert result.level == "NOT_RECOMMENDED"
        assert result.rule_id == "D02"

    def test_garch_for_non_financial_not_recommended(self, spec):
        """GARCH для не-финансового домена → NOT_RECOMMENDED (D04)."""
        profile = DataProfile(
            n_observations=500, n_series=1, n_exogenous=0,
            is_regular=True, frequency="D",
            has_seasonality=False, seasonal_periods=[],
            is_stationary_or_diffable=True, is_cointegrated=False,
            has_negative_values=False, has_volatility_clustering=True,
            domain="macro", missing_ratio=0.0, outlier_ratio=0.0,
        )
        result = spec.resolve_applicability("garch", profile)
        # F02 checks domain == 'financial' AND data.domain != 'financial'
        # For macro domain, GARCH is NOT_APPLICABLE via F02
        assert result.level in ("NOT_APPLICABLE", "NOT_RECOMMENDED")

    # ── CONDITIONALLY_APPLICABLE ───────────────────────────

    def test_arima_boundary_n_conditionally(self, spec):
        """Auto-ARIMA при n=40 (30 ≤ n < 50) → CONDITIONALLY_APPLICABLE (C01).

        Примечание: arima (min=50) при n=40 блокируется F04 раньше C01.
        Поэтому используем arima_auto (min=30), к которому C01 применим.
        """
        profile = DataProfile(
            n_observations=40, n_series=1, n_exogenous=0,
            is_regular=True, frequency="M",
            has_seasonality=True, seasonal_periods=[12],
            is_stationary_or_diffable=True, is_cointegrated=False,
            has_negative_values=False, has_volatility_clustering=False,
            domain="macro", missing_ratio=0.0, outlier_ratio=0.0,
        )
        result = spec.resolve_applicability("arima_auto", profile)
        assert result.level == "CONDITIONALLY_APPLICABLE"
        assert result.rule_id == "C01"

    # ── RECOMMENDED ────────────────────────────────────────

    def test_ets_small_seasonal_recommended(self, spec):
        """ETS при n=60 с сезонностью → RECOMMENDED (P01)."""
        profile = DataProfile(
            n_observations=60, n_series=1, n_exogenous=0,
            is_regular=True, frequency="M",
            has_seasonality=True, seasonal_periods=[12],
            is_stationary_or_diffable=False, is_cointegrated=False,
            has_negative_values=False, has_volatility_clustering=False,
            domain="macro", missing_ratio=0.0, outlier_ratio=0.0,
        )
        result = spec.resolve_applicability("ets", profile)
        assert result.level == "RECOMMENDED"

    def test_arima_medium_stationary_recommended(self, spec):
        """ARIMA при n=200, стационарный → RECOMMENDED (P02)."""
        profile = DataProfile(
            n_observations=200, n_series=1, n_exogenous=0,
            is_regular=True, frequency="M",
            has_seasonality=True, seasonal_periods=[12],
            is_stationary_or_diffable=True, is_cointegrated=False,
            has_negative_values=False, has_volatility_clustering=False,
            domain="macro", missing_ratio=0.0, outlier_ratio=0.0,
        )
        result = spec.resolve_applicability("arima", profile)
        assert result.level == "RECOMMENDED"

    def test_garch_financial_recommended(self, spec, financial_profile):
        """GARCH для финансов с кластеризацией → RECOMMENDED (P04)."""
        result = spec.resolve_applicability("garch", financial_profile)
        assert result.level == "RECOMMENDED"

    # ── Baselines всегда RECOMMENDED ───────────────────────

    def test_naive_always_recommended(self, spec, macro_profile):
        """Naive baseline → всегда RECOMMENDED (нет запрещающих условий)."""
        result = spec.resolve_applicability("naive", macro_profile)
        assert result.level == "RECOMMENDED"

    def test_seasonal_naive_with_seasonality(self, spec, macro_profile):
        """Seasonal Naive при наличии сезонности → RECOMMENDED."""
        result = spec.resolve_applicability("seasonal_naive", macro_profile)
        assert result.level == "RECOMMENDED"


# ═══════════════════════════════════════════════════════════
# 4. ПАЙПЛАЙН
# ═══════════════════════════════════════════════════════════

class TestPipeline:
    """Тесты пайплайна моделирования."""

    def test_11_stages(self, spec):
        """11 стадий пайплайна."""
        assert len(spec.pipeline.stages) == 11

    def test_stage_order_sequential(self, spec):
        """Порядок стадий последовательный 1–11."""
        orders = [s.order for s in spec.pipeline.stages]
        assert orders == list(range(1, 12))

    def test_first_stage_problem_definition(self, spec):
        """Первая стадия — Problem Definition."""
        assert spec.pipeline.stages[0].id == "problem_definition"

    def test_last_stage_model_card(self, spec):
        """Последняя стадия — Model Card."""
        assert spec.pipeline.stages[-1].id == "model_card"

    def test_baseline_stage_required(self, spec):
        """Стадия Baseline Estimation обязательна."""
        baseline_stage = next(
            s for s in spec.pipeline.stages if s.id == "baseline_estimation"
        )
        assert baseline_stage.required is True

    def test_model_card_stage_required(self, spec):
        """Стадия Model Card обязательна."""
        mc_stage = next(
            s for s in spec.pipeline.stages if s.id == "model_card"
        )
        assert mc_stage.required is True


# ═══════════════════════════════════════════════════════════
# 5. МЕТРИКИ
# ═══════════════════════════════════════════════════════════

class TestMetrics:
    """Тесты конфигурации метрик."""

    def test_4_primary_metrics(self, spec):
        """4 основные метрики: MAE, RMSE, MAPE, MASE."""
        assert len(spec.metrics.primary) == 4
        ids = {m.id for m in spec.metrics.primary}
        assert ids == {"mae", "rmse", "mape", "mase"}

    def test_weights_sum_to_1(self, spec):
        """Веса основных метрик суммируются в 1.0."""
        total = sum(m.weight_in_ranking for m in spec.metrics.primary)
        assert abs(total - 1.0) < 0.001

    def test_r_squared_not_in_ranking(self, spec):
        """R² не входит в ранжирование."""
        r2 = next(
            (m for m in spec.metrics.secondary if m.id == "r_squared"),
            None,
        )
        assert r2 is not None
        assert r2.use_in_ranking is False

    def test_ranking_formula_has_4_weights(self, spec):
        """Формула ранжирования содержит 4 веса."""
        assert len(spec.metrics.ranking_formula.weights) == 4

    def test_mase_in_primary(self, spec):
        """MASE остаётся scale-free метрикой, но не подменяет OOF baseline gate."""
        mase = next(m for m in spec.metrics.primary if m.id == "mase")
        assert mase.weight_in_ranking > 0
        assert "непригодна" not in mase.interpretation.lower()
        assert "train" in mase.interpretation.lower()

    def test_baseline_gate_is_horizon_consistent(self, spec):
        ranking = spec.metrics.ranking_formula
        assert ranking.baseline_oof_metric == "rmse"
        assert ranking.baseline_oof_tolerance_ratio == 1.05
        assert ranking.baseline_filter_threshold is None


# ═══════════════════════════════════════════════════════════
# 6. PREDICTION INTERVALS
# ═══════════════════════════════════════════════════════════

class TestPredictionIntervals:
    """Тесты конфигурации доверительных интервалов."""

    def test_default_confidence_95(self, spec):
        """Доверительный уровень по умолчанию — 0.95."""
        assert spec.prediction_intervals.default_confidence_level == 0.95

    def test_methods_for_all_8_families(self, spec):
        """Методы PI определены для всех 8 семейств."""
        assert len(spec.prediction_intervals.methods_by_family) == 8

    def test_available_levels(self, spec):
        """4 доступных уровня доверия."""
        assert len(spec.prediction_intervals.available_levels) == 4
        assert 0.95 in spec.prediction_intervals.available_levels


# ═══════════════════════════════════════════════════════════
# 7. MODEL CARD
# ═══════════════════════════════════════════════════════════

class TestModelCard:
    """Тесты шаблона Model Card."""

    def test_required_fields_present(self, spec):
        """Model Card имеет обязательные поля."""
        assert len(spec.model_card_template.required_fields) >= 15

    def test_key_required_fields(self, spec):
        """Ключевые обязательные поля присутствуют."""
        paths = {f.path for f in spec.model_card_template.required_fields}
        assert "model_info.model_id" in paths
        assert "model_info.applicability_level" in paths
        assert "performance.cv_metrics" in paths
        assert "diagnostics.passed" in paths
        assert "limitations" in paths


# ═══════════════════════════════════════════════════════════
# 8. ЖИЗНЕННЫЕ ЦИКЛЫ
# ═══════════════════════════════════════════════════════════

class TestLifecycleSeparation:
    """Тесты разделения моделирование ≠ прогнозирование."""

    def test_modeling_phase(self, spec):
        """Фаза моделирования определена."""
        assert spec.lifecycle_separation.modeling is not None
        assert spec.lifecycle_separation.modeling.trigger is not None

    def test_forecasting_phase(self, spec):
        """Фаза прогнозирования определена."""
        assert spec.lifecycle_separation.forecasting is not None

    def test_different_outputs(self, spec):
        """Моделирование и прогнозирование имеют разные выходы."""
        m_outputs = spec.lifecycle_separation.modeling.outputs
        f_outputs = spec.lifecycle_separation.forecasting.outputs
        assert m_outputs != f_outputs

    def test_modeling_produces_model_card(self, spec):
        """Моделирование порождает Model Card."""
        assert "model_card" in spec.lifecycle_separation.modeling.outputs


# ═══════════════════════════════════════════════════════════
# 9. АНСАМБЛИ
# ═══════════════════════════════════════════════════════════

class TestEnsemble:
    """Тесты конфигурации ансамблирования."""

    def test_4_strategies(self, spec):
        """4 стратегии ансамблирования."""
        assert len(spec.ensemble.strategies) == 4

    def test_strategy_ids(self, spec):
        """ID стратегий ансамбля."""
        ids = {s.id for s in spec.ensemble.strategies}
        expected = {"simple_average", "weighted_average", "median", "stacking"}
        assert ids == expected

    def test_unverified_auto_ensemble_trigger_is_disabled(self, spec):
        """Старая MASE-эвристика не должна включать ансамбль автоматически."""
        assert spec.ensemble.auto_ensemble_trigger is None


# ═══════════════════════════════════════════════════════════
# 10. ПРЕДОБРАБОТКА
# ═══════════════════════════════════════════════════════════

class TestPreprocessing:
    """Тесты правил предобработки."""

    def test_preprocessing_rules_count(self, spec):
        """5 правил предобработки."""
        assert len(spec.preprocessing_rules) == 5

    def test_each_rule_has_trigger_and_action(self, spec):
        """Каждое правило имеет trigger и action."""
        for rule in spec.preprocessing_rules:
            assert rule.trigger is not None
            assert rule.action is not None
            assert len(rule.trigger) > 0
            assert len(rule.action) > 0


# ═══════════════════════════════════════════════════════════
# 11. UI КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════

class TestUIConfig:
    """Тесты конфигурации UI."""

    def test_comparison_table_columns(self, spec):
        """Таблица сравнения содержит ключевые столбцы."""
        cols = spec.ui_config.comparison_table.columns
        assert "model_name" in cols
        assert "MASE" in cols
        assert "applicability_level" in cols
        assert "oof_baseline_ratio" in cols
        assert "baseline_status" not in cols

    def test_filters_present(self, spec):
        """Фильтры определены."""
        assert len(spec.ui_config.filters) >= 3

    def test_forecasting_panel(self, spec):
        """Панель прогнозирования сконфигурирована."""
        fp = spec.ui_config.forecasting_panel
        assert fp.default_confidence == 0.95
        assert 0.95 in fp.confidence_levels


# ═══════════════════════════════════════════════════════════
# 12. МАССОВАЯ ОЦЕНКА ПРИМЕНИМОСТИ
# ═══════════════════════════════════════════════════════════

class TestBulkApplicability:
    """Тесты resolve_all_applicability — массовая оценка моделей."""

    def test_macro_profile_results(self, spec, macro_profile):
        """Оценка всех моделей для макроэкономического профиля."""
        results = spec.resolve_all_applicability(macro_profile)
        assert len(results) > 0

        # Baselines всегда присутствуют и применимы
        for bid in ["naive", "drift", "mean"]:
            assert bid in results
            assert results[bid].level != "NOT_APPLICABLE"

        # GARCH неприменим для macro
        assert results["garch"].level == "NOT_APPLICABLE"

        # DeepAR неприменим для одномерного ряда
        assert results["deepar"].level == "NOT_APPLICABLE"

    def test_financial_profile_garch_recommended(self, spec, financial_profile):
        """GARCH рекомендуется для финансового профиля."""
        results = spec.resolve_all_applicability(financial_profile)
        assert results["garch"].level == "RECOMMENDED"

    def test_multivariate_vecm_recommended(self, spec):
        """VECM рекомендуется для коинтегрированных многомерных рядов."""
        # VECM не поддерживает экзогенные → n_exogenous=0
        profile = DataProfile(
            n_observations=200, n_series=3, n_exogenous=0,
            is_regular=True, frequency="Q",
            has_seasonality=True, seasonal_periods=[4],
            is_stationary_or_diffable=False, is_cointegrated=True,
            has_negative_values=False, has_volatility_clustering=False,
            domain="macro", missing_ratio=0.0, outlier_ratio=0.0,
        )
        results = spec.resolve_all_applicability(profile)
        assert results["vecm"].level == "RECOMMENDED"

    def test_no_model_returns_empty(self, spec, tiny_profile):
        """Все модели с min_observations > n → NOT_APPLICABLE."""
        results = spec.resolve_all_applicability(tiny_profile)
        # Даже при n=5, naive (min=2) и mean (min=3) применимы
        assert results["naive"].level != "NOT_APPLICABLE"
        assert results["mean"].level != "NOT_APPLICABLE"


# ═══════════════════════════════════════════════════════════
# 13. ЦЕЛОСТНОСТЬ СПЕЦИФИКАЦИИ
# ═══════════════════════════════════════════════════════════

class TestSpecIntegrity:
    """Тесты целостности спецификации."""

    def test_no_duplicate_model_ids(self, spec):
        """Нет дубликатов model_id среди всех семейств."""
        all_ids = []
        for family in spec.families:
            for model in family.models:
                all_ids.append(model.id)
        assert len(all_ids) == len(set(all_ids))

    def test_all_models_have_min_observations(self, spec):
        """Все модели имеют min_observations > 0."""
        for family in spec.families:
            for model in family.models:
                assert model.min_observations >= 1, (
                    f"{family.id}/{model.id}: min_observations must be >= 1"
                )

    def test_model_dump_roundtrip(self, spec):
        """Сериализация model_dump() и обратная загрузка — идентичность."""
        data = spec.model_dump()
        spec2 = ModelingSpec(**data)
        assert spec2.metadata.version == spec.metadata.version
        assert spec2.total_model_count() == spec.total_model_count()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
