# PANEL-MODELS-3b: интеграция панельного семейства с реестром исполнения,
# каталогом (modeling.yaml, семейство №9 panel, F06) и движком бэктеста
# run_panel_entity_backtest_plan (зеркало Task 142-движка).
# TDD RED -- тесты написаны ДО реализации (спека §3b, TDD-план §5b-6/7).
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.backtesting import BacktestExecutionError, run_panel_entity_backtest_plan
from apps.api.model_execution import (
    MODEL_EXECUTION_REGISTRY,
    ModelExecutionContractError,
    ModelExecutionDefinition,
    ModelExecutionRequest,
    _panel_entity_executor,
)

from app.preprocessing.panel import build_panel_frame
from app.modeling.panel_models import PanelModelError


# ── DGP ──────────────────────────────────────────────────────────────────────

def _make_panel_df(*, n_entities=8, t_per_entity=40, beta=1.0, seed=42):
    rng = np.random.default_rng(seed)
    rows = []
    dates = pd.date_range("2022-01-31", periods=t_per_entity, freq="ME")
    for i in range(n_entities):
        alpha = rng.normal(0.0, 2.0)
        entity = f"e{i:02d}"
        x = rng.normal(0.0, 1.0, size=t_per_entity)
        y = alpha + beta * x + rng.normal(0.0, 0.5, size=t_per_entity)
        for t in range(t_per_entity):
            rows.append({"entity": entity, "date": dates[t], "y": float(y[t]), "x": float(x[t])})
    return pd.DataFrame(rows)


@pytest.fixture()
def panel_frame():
    return build_panel_frame(
        _make_panel_df(), date_column="date", entity_column="entity",
        value_columns=["y", "x"], target_column="y",
    )


# ── Реестр исполнения: input_kind="panel_entity" ────────────────────────────

class TestRegistry:
    @pytest.mark.parametrize("model_id", ["panel_fe", "panel_re", "panel_var"])
    def test_definitions_registered(self, model_id):
        definition = MODEL_EXECUTION_REGISTRY.require(model_id)
        assert definition.family_id == "panel"
        assert definition.input_kind == "panel_entity"
        assert definition.deterministic is True
        assert "backtest" in definition.actions

    @pytest.mark.parametrize("model_id", ["panel_fe", "panel_re", "panel_var"])
    def test_descriptors(self, model_id):
        descriptor = MODEL_EXECUTION_REGISTRY.describe(model_id)
        assert descriptor["input_kind"] == "panel_entity"
        assert descriptor["runtime_available"] is True  # statsmodels установлен

    def test_panel_entity_distinct_from_column_parallel_panel(self):
        # R2: две «панели» явно различимы -- Task 142 колонко-параллельный
        # "panel" не тронут, сущностный контур -- отдельный input_kind.
        assert MODEL_EXECUTION_REGISTRY.require("deepar").input_kind == "panel"
        assert MODEL_EXECUTION_REGISTRY.require("panel_fe").input_kind == "panel_entity"

    def test_requires_gates_validate_panel_entity(self):
        # Валидация нового input_kind в requires-гейтах: панельная модель
        # НЕ может декларировать related_series/train_features-каналы
        # (панель проходит собственным движком, не через плоский request).
        with pytest.raises(ModelExecutionContractError):
            ModelExecutionDefinition(
                model_id="panel_x", family_id="panel",
                adapter_id="panel-x", executor=lambda request: None,
                input_kind="panel_entity", requires_related_series=True,
            )
        with pytest.raises(ModelExecutionContractError):
            ModelExecutionDefinition(
                model_id="panel_x", family_id="panel",
                adapter_id="panel-x", executor=lambda request: None,
                input_kind="panel_entity", requires_train_features=True,
            )

    def test_stub_executor_honest_refusal(self):
        # panel_entity-модели исполняются ТОЛЬКО панельным движком;
        # плоский ModelExecutionRequest для сущностной панели не существует.
        request = ModelExecutionRequest(target=[1.0, 2.0, 3.0], horizon=1)
        with pytest.raises(ModelExecutionContractError) as exc:
            _panel_entity_executor(request)
        assert "run_panel_entity_backtest_plan" in str(exc.value)


# ── Каталог: семейство №9 panel + F06 ───────────────────────────────────────

class TestCatalog:
    @pytest.fixture(scope="class")
    def spec(self):
        from src.catalog.modeling_spec_loader import ModelingSpec
        return ModelingSpec.from_yaml("rules/modeling.yaml")

    def test_family_panel_present(self, spec):
        family = spec.get_family("panel")
        assert family is not None
        ids = {model.id for model in family.models}
        assert {"panel_fe", "panel_re", "panel_var"} <= ids

    def test_spec_integrity(self, spec):
        assert spec.validate_integrity() == []

    def test_single_row_router_marks_panel_not_applicable(self, spec):
        # Однорядный каталог панель не маршрутизирует: F06 честно ведёт
        # панельные модели в NOT_APPLICABLE с указанием панельного контура.
        from src.catalog.modeling_spec_loader import DataProfile
        profile = DataProfile(n_observations=500, n_series=1)
        result = spec.resolve_applicability("panel_fe", profile)
        assert result.level == "NOT_APPLICABLE"
        assert "панель" in (result.message or "").lower()

    def test_catalog_pool_excludes_panel_for_single_row(self, spec):
        from src.catalog.modeling_spec_loader import DataProfile
        profile = DataProfile(n_observations=500, n_series=1)
        pool = spec.get_candidate_pool(profile)
        assert all(result.family_id != "panel" for result in pool)


# ── Движок run_panel_entity_backtest_plan ───────────────────────────────────

class TestPanelEntityEngine:
    def _run(self, frame, model_id, **kwargs):
        return run_panel_entity_backtest_plan(
            model_id=model_id,
            model_name=model_id,
            family_id="panel",
            frame=frame,
            validation={"strategy": "expanding", "horizon": 6, "n_folds": 2, "gap": 0},
            seasonal_period=12,
            **kwargs,
        )

    def test_engine_fe_success(self, panel_frame):
        result = self._run(panel_frame, "panel_fe")
        assert result["status"] == "success"
        assert result["model_id"] == "panel_fe"
        assert result["n_folds"] == 2
        assert result["execution_contract"]["input_kind"] == "panel_entity"
        # По-сущностные + pooled метрики.
        assert result["panel"]["n_entities"] == panel_frame.n_entities
        assert result["panel"]["pooled_metrics"]["mae"] >= 0.0
        assert len(result["panel"]["entity_metrics"]) == panel_frame.n_entities

    def test_engine_re_success(self, panel_frame):
        result = self._run(panel_frame, "panel_re")
        assert result["status"] == "success"
        assert result["panel"]["pooled_metrics"]["rmse"] >= 0.0

    def test_engine_oof_full(self, panel_frame):
        # OOF покрывает ВСЕ test-наблюдения каждого fold (по-сущностно).
        result = self._run(panel_frame, "panel_fe")
        oof = result["oof_predictions"]
        assert oof, "OOF пуст"
        entities = {point["entity"] for point in oof}
        assert entities == {f"e{i:02d}" for i in range(panel_frame.n_entities)}
        for point in oof:
            assert {"fold", "entity", "date", "actual", "predicted", "residual"} <= set(point)

    def test_engine_pooled_matches_concatenation(self, panel_frame):
        # Micro-average: pooled MAE == MAE на конкатенации по-сущностных OOF
        # (допуск 1e-6 -- сертифицированная compute_forecast_metrics округляет).
        result = self._run(panel_frame, "panel_fe")
        oof = result["oof_predictions"]
        residuals = [abs(point["actual"] - point["predicted"]) for point in oof]
        assert abs(np.mean(residuals) - result["panel"]["pooled_metrics"]["mae"]) < 1e-6

    def test_engine_var_success(self, panel_frame):
        # Панель y/x сбалансирована с T=40, n_vars=2: T_common=40 >= 3*2*2=12.
        result = self._run(panel_frame, "panel_var")
        assert result["status"] == "success"
        assert result["panel"]["n_entities"] == panel_frame.n_entities

    def test_engine_var_refuses_unbalanced(self):
        df = _make_panel_df()
        df = df.drop(index=df.index[
            (df["entity"] == "e00") & (df["date"] == df["date"].max())
        ])
        frame = build_panel_frame(
            df, date_column="date", entity_column="entity",
            value_columns=["y", "x"], target_column="y",
        )
        with pytest.raises(BacktestExecutionError) as exc:
            self._run(frame, "panel_var")
        assert "общей сетки" in str(exc.value) or "сбалансированный" in str(exc.value)

    def test_engine_rejects_non_panel_entity_model(self, panel_frame):
        # Модели без input_kind="panel_entity" панельным движком не
        # исполняются (гейт зеркала Task 142).
        with pytest.raises(BacktestExecutionError):
            self._run(panel_frame, "naive")

    def test_engine_leakage_guard(self, panel_frame):
        # Изменение ФАКТОВ test-периода не меняет прогнозы: модель видит
        # только train-префикс (FE/RE: экзогенные test-дат -- сценарий,
        # y test-дат в фит не входит).
        base = self._run(panel_frame, "panel_fe")
        leaked_frame = build_panel_frame(
            _make_panel_df(), date_column="date", entity_column="entity",
            value_columns=["y", "x"], target_column="y",
        )
        mask = leaked_frame.frame["date"] >= panel_frame.frame["date"].max()
        leaked_frame.frame.loc[mask, "y"] = 1e6
        leaked = self._run(leaked_frame, "panel_fe")
        base_points = [
            (point["entity"], point["date"], point["predicted"])
            for point in base["oof_predictions"]
        ]
        leaked_points = [
            (point["entity"], point["date"], point["predicted"])
            for point in leaked["oof_predictions"]
        ]
        assert base_points == leaked_points

    def test_engine_metric_scales_train_only(self, panel_frame):
        # MASE-скейл считается ТОЛЬКО по train-префиксу (сертифицированный
        # compute_metric_scales); pooled MASE -- медиана по-сущностных скейлов.
        result = self._run(panel_frame, "panel_fe")
        assert result["panel"]["pooled_mase_scale"] > 0.0

    def test_engine_honest_scenario_disclosure(self, panel_frame):
        # OOF FE/RE -- сценарная постановка: экзогенные test-дат берутся
        # из факта; дисклоужено в warnings.
        result = self._run(panel_frame, "panel_fe")
        assert any("сценар" in warning.lower() for warning in result["warnings"])


# ══════════════════════════════════════════════════════════════════════════════
# PANEL-GMM-4: panel_gmm -- Arellano-Bond difference GMM (динамические панели).
# Реестр исполнения + панельный движок. TDD RED -- тесты ДО реализации.
# ══════════════════════════════════════════════════════════════════════════════

def _make_dynamic_panel_df(*, n_entities=12, t_per_entity=24, alpha=0.6,
                           beta=0.8, seed=42, with_exog=True):
    """Динамический панельный DGP: y_it = alpha*y_i,t-1 + beta*x_it + mu_i + e."""
    rng = np.random.default_rng(seed)
    rows = []
    dates = pd.date_range("2022-01-31", periods=t_per_entity, freq="ME")
    mus = rng.normal(0.0, 2.0, size=n_entities)
    for i in range(n_entities):
        entity = f"g{i:02d}"
        x = rng.normal(0.0, 1.0, size=t_per_entity) if with_exog else np.zeros(t_per_entity)
        y = np.zeros(t_per_entity)
        y[0] = mus[i] / (1.0 - alpha) + beta * x[0] + rng.normal(0.0, 0.7)
        for t in range(1, t_per_entity):
            y[t] = alpha * y[t - 1] + beta * x[t] + mus[i] + rng.normal(0.0, 0.7)
        for t in range(t_per_entity):
            row = {"entity": entity, "date": dates[t], "y": float(y[t])}
            if with_exog:
                row["x"] = float(x[t])
            rows.append(row)
    return pd.DataFrame(rows)


class TestPanelGmmRegistry:
    def test_panel_gmm_registered_as_panel_entity(self):
        definition = MODEL_EXECUTION_REGISTRY.require("panel_gmm")
        assert definition.family_id == "panel"
        assert definition.input_kind == "panel_entity"
        assert definition.deterministic is True
        assert "backtest" in definition.actions

    def test_panel_gmm_descriptor(self):
        descriptor = MODEL_EXECUTION_REGISTRY.describe("panel_gmm")
        assert descriptor["input_kind"] == "panel_entity"
        assert descriptor["runtime_available"] is True  # statsmodels установлен

    def test_panel_gmm_in_production_backtest_ids(self):
        from apps.api.model_readiness import PRODUCTION_BACKTEST_MODEL_IDS
        assert "panel_gmm" in PRODUCTION_BACKTEST_MODEL_IDS

    def test_panel_entity_executor_refuses_panel_gmm(self):
        # Прецедент FE/RE/VAR: сущностная панель не представима плоским
        # request -- executor честно отказывает, исполнение ТОЛЬКО движком.
        import numpy as np
        request = ModelExecutionRequest(
            target=[float(value) for value in np.arange(20)],
            horizon=4, params={},
        )
        with pytest.raises(ModelExecutionContractError):
            _panel_entity_executor(request)


class TestPanelGmmEngine:
    @pytest.fixture()
    def gmm_frame(self):
        return build_panel_frame(
            _make_dynamic_panel_df(),
            date_column="date", entity_column="entity",
            value_columns=["y", "x"], target_column="y",
        )

    def test_backtest_end_to_end(self, gmm_frame):
        result = run_panel_entity_backtest_plan(
            model_id="panel_gmm", model_name="Arellano-Bond GMM",
            family_id="panel", frame=gmm_frame,
            validation={"strategy": "expanding", "horizon": 4, "n_folds": 2},
            seasonal_period=12,
        )
        assert result["status"] == "success"
        assert result["model_id"] == "panel_gmm"
        assert result["cohort_contract"]["panel_entity"] is True
        assert result["cohort_contract"]["input_kind"] == "panel_entity"
        assert len(result["folds"]) == 2
        assert all(fold["status"] == "success" for fold in result["folds"])
        assert result["oof_predictions"], "OOF-точки обязаны быть"
        for point in result["oof_predictions"]:
            assert "entity" in point and "actual" in point and "predicted" in point
        assert result["panel"]["n_entities"] == 12
        assert set(result["panel"]["entity_metrics"]) == {
            f"g{i:02d}" for i in range(12)
        }
        assert any("динамическ" in warning for warning in result["warnings"])

    def test_backtest_pure_dynamics_without_exog(self):
        # ДИФФЕРЕНЦИАТОР от FE/RE: панель БЕЗ экзогенных исполняется --
        # динамическая панель прогнозирует от собственной динамики (R6).
        frame = build_panel_frame(
            _make_dynamic_panel_df(with_exog=False),
            date_column="date", entity_column="entity",
            value_columns=["y"], target_column="y",
        )
        result = run_panel_entity_backtest_plan(
            model_id="panel_gmm", model_name="Arellano-Bond GMM",
            family_id="panel", frame=frame,
            validation={"strategy": "expanding", "horizon": 3, "n_folds": 2},
            seasonal_period=12,
        )
        assert result["status"] == "success"
        assert result["oof_predictions"]

    def test_backtest_short_history_refused(self):
        # t_per_entity < fold-минимума -- честный отказ движка (без пустых
        # folds), а не фиктивный прогон.
        frame = build_panel_frame(
            _make_dynamic_panel_df(t_per_entity=9),
            date_column="date", entity_column="entity",
            value_columns=["y", "x"], target_column="y",
        )
        with pytest.raises(BacktestExecutionError) as exc:
            run_panel_entity_backtest_plan(
                model_id="panel_gmm", model_name="Arellano-Bond GMM",
                family_id="panel", frame=frame,
                validation={"strategy": "expanding", "horizon": 2, "n_folds": 1},
                seasonal_period=12,
            )
        assert "Недостаточно истории" in str(exc.value)
