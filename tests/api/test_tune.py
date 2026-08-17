# tests/api/test_tune.py
"""
Phase 1-C: Тесты для POST /v1/models/tune + max_trials защита.

Покрывают:
  1. Схемы CVConfig, TuneRequest, TuneResponse, TuneTrialResult (Pydantic)
  2. _build_grid — декартово произведение param_space
  3. _truncate_grid — max_trials защита (random sampling)
  4. _execute_tune — интеграция grid × CV × selection:
     • ETS / ets_damped / arima grid search → корректный best_params
     • Baseline (no param_space) → 422
     • Unknown model → 404
     • Too short series → 422
     • Invalid metric → 422
     • best_trial — индекс trial'а с минимальным metric
     • Воспроизводимость random_state
  5. Интеграция с ExpandingWindowCV — n_folds в trials соответствует n_splits
  6. Синтетический spec с grid_size > MAX_TRIALS — реальная truncation

ВАЖНО: эти тесты НЕ импортируют apps.api.main (который тянет pandera).
Тестируют чистую логику _execute_tune() напрямую.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from apps.api.cv import ExpandingWindowCV
from apps.api.schemas import (
    BacktestMetrics,
    CVConfig,
    TuneRequest,
    TuneResponse,
    TuneTrialResult,
)
from apps.api.routers.models import (
    MAX_TRIALS,
    _build_grid,
    _truncate_grid,
    _execute_tune,
)
from src.catalog.modeling_spec_loader import (
    Family,
    FamilyModel,
    LifecyclePhase,
    LifecycleSeparation,
    Metadata,
    ModelingSpec,
)

SPEC_PATH = Path("rules/modeling.yaml")


# ═══════════════════════════════════════════════════════════
# ФИКСТУРЫ
# ═══════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def spec() -> ModelingSpec:
    return ModelingSpec.from_yaml(str(SPEC_PATH))


def _make_series(n: int = 60) -> List[float]:
    """Синтетический ряд: trend + seasonality, детерминированный."""
    return [100.0 + 0.5 * t + 5.0 * math.sin(2 * math.pi * t / 12) for t in range(n)]


def _make_huge_grid_spec(grid_size: int = 100) -> ModelingSpec:
    """Синтетический spec с моделью, у которой param_space > MAX_TRIALS.

    Используется для теста реальной truncation через _execute_tune.
    4 параметра × 4 значения × 2 × 2 × 2 = 128 ( > MAX_TRIALS=64).
    """
    param_space = {
        "p": list(range(4)),       # 4
        "d": list(range(4)),       # 4
        "q": list(range(2)),       # 2
        "r": list(range(2)),       # 2
        "s": list(range(2)),       # 2  → 4*4*2*2*2 = 128
    }
    assert (
        4 * 4 * 2 * 2 * 2 == grid_size
    ), f"Expected grid_size={grid_size}, got {4*4*2*2*2}"
    return ModelingSpec(
        metadata=Metadata(version="test"),
        families=[
            Family(
                id="test_family",
                name="Test",
                priority=1,
                models=[
                    FamilyModel(
                        id="test_model",
                        name="Test Model",
                        description="for truncation test",
                        min_observations=1,
                        param_space=param_space,
                    )
                ],
            )
        ],
        lifecycle_separation=LifecycleSeparation(
            modeling=LifecyclePhase(),
            forecasting=LifecyclePhase(),
        ),
    )


# ═══════════════════════════════════════════════════════════
# 1. СХЕМЫ (Pydantic)
# ═══════════════════════════════════════════════════════════

class TestCVConfig:
    """CVConfig — параметры expanding-window CV."""

    def test_defaults(self):
        c = CVConfig()
        assert c.n_splits == 5
        assert c.test_size == 1
        assert c.min_train_size is None  # None → default = test_size в cv.py
        assert c.step is None             # None → default = test_size в cv.py

    def test_custom_values(self):
        c = CVConfig(n_splits=3, test_size=2, min_train_size=10, step=2)
        assert c.n_splits == 3
        assert c.test_size == 2
        assert c.min_train_size == 10
        assert c.step == 2

    def test_n_splits_must_be_positive(self):
        with pytest.raises(ValidationError):
            CVConfig(n_splits=0)
        with pytest.raises(ValidationError):
            CVConfig(n_splits=-1)

    def test_test_size_must_be_positive(self):
        with pytest.raises(ValidationError):
            CVConfig(test_size=0)
        with pytest.raises(ValidationError):
            CVConfig(test_size=-5)

    def test_min_train_size_must_be_positive(self):
        with pytest.raises(ValidationError):
            CVConfig(min_train_size=0)

    def test_step_must_be_positive(self):
        with pytest.raises(ValidationError):
            CVConfig(step=0)


class TestTuneRequest:
    """TuneRequest — запрос к POST /v1/models/tune."""

    def test_required_fields(self):
        """Без model_id и series — ValidationError."""
        with pytest.raises(ValidationError):
            TuneRequest()

    def test_minimal_request(self):
        r = TuneRequest(model_id="ets", series=[1.0, 2.0, 3.0])
        assert r.model_id == "ets"
        assert r.series == [1.0, 2.0, 3.0]
        assert r.cv is None
        assert r.max_trials is None
        assert r.metric == "rmse"
        assert r.random_state == 42

    def test_full_request(self):
        r = TuneRequest(
            model_id="arima",
            series=list(range(60)),
            cv=CVConfig(n_splits=3, test_size=2),
            max_trials=10,
            metric="mae",
            random_state=99,
        )
        assert r.cv.n_splits == 3
        assert r.max_trials == 10
        assert r.metric == "mae"
        assert r.random_state == 99

    def test_series_cannot_be_empty(self):
        """series: min_length=1 → пустой список недопустим."""
        with pytest.raises(ValidationError):
            TuneRequest(model_id="ets", series=[])

    def test_max_trials_must_be_positive(self):
        with pytest.raises(ValidationError):
            TuneRequest(model_id="ets", series=[1.0], max_trials=0)
        with pytest.raises(ValidationError):
            TuneRequest(model_id="ets", series=[1.0], max_trials=-5)

    def test_metric_must_be_in_allowed_set(self):
        """metric — Literal, не любое значение."""
        with pytest.raises(ValidationError):
            TuneRequest(model_id="ets", series=[1.0], metric="invalid")
        with pytest.raises(ValidationError):
            TuneRequest(model_id="ets", series=[1.0], metric="RMSE")  # case-sensitive

    @pytest.mark.parametrize(
        "metric",
        ["mae", "rmse", "mape", "mase", "weighted_score"],
    )
    def test_all_metrics_accepted(self, metric):
        r = TuneRequest(model_id="ets", series=[1.0], metric=metric)
        assert r.metric == metric


class TestTuneResponse:
    """TuneResponse — результат grid search."""

    def _make_metrics(self):
        return BacktestMetrics(
            mae=1.0, rmse=1.5, mape=10.0, mase=0.9, weighted_score=0.5
        )

    def test_construct_minimal(self):
        r = TuneResponse(
            model_id="ets",
            model_name="ETS",
            family_id="exponential_smoothing",
            best_params={"trend": "add"},
            best_metrics=self._make_metrics(),
            best_trial=0,
            n_trials=1,
            grid_size=1,
            truncated=False,
            cv_config=CVConfig(),
            metric="rmse",
            trials=[],
            duration_ms=10.0,
        )
        assert r.model_id == "ets"
        assert r.truncated is False
        assert r.cv_config.n_splits == 5

    def test_trials_default_empty(self):
        r = TuneResponse(
            model_id="ets", model_name="ETS", family_id="es",
            best_params={}, best_metrics=self._make_metrics(),
            best_trial=0, n_trials=1, grid_size=1,
            truncated=False, cv_config=CVConfig(), metric="rmse",
            duration_ms=0.0,
        )
        assert r.trials == []


class TestTuneTrialResult:
    """TuneTrialResult — один trial grid search'а."""

    def test_construct(self):
        t = TuneTrialResult(
            params={"p": 1, "q": 0},
            metrics=BacktestMetrics(
                mae=1.0, rmse=1.5, mape=10.0, mase=0.9, weighted_score=0.5
            ),
            n_folds=5,
        )
        assert t.params == {"p": 1, "q": 0}
        assert t.n_folds == 5
        assert t.metrics.rmse == 1.5


# ═══════════════════════════════════════════════════════════
# 2. _build_grid — ДЕКАРТОВО ПРОИЗВЕДЕНИЕ
# ═══════════════════════════════════════════════════════════

class TestBuildGrid:
    """_build_grid(param_space) → list[dict]: декартово произведение."""

    def test_single_param(self):
        grid = _build_grid({"p": [0, 1, 2]})
        assert len(grid) == 3
        assert {"p": 0} in grid
        assert {"p": 1} in grid
        assert {"p": 2} in grid

    def test_two_params(self):
        grid = _build_grid({"p": [0, 1], "q": [0, 1]})
        assert len(grid) == 4
        assert {"p": 0, "q": 0} in grid
        assert {"p": 1, "q": 1} in grid

    def test_three_params_ets(self):
        """ETS param_space: trend×seasonal×seasonal_periods = 6 combos."""
        grid = _build_grid({
            "trend": ["add", "mul"],
            "seasonal": ["add", "mul", None],
            "seasonal_periods": [12],
        })
        assert len(grid) == 6  # 2 × 3 × 1

    def test_empty_param_space(self):
        """Пустой dict → один trial с пустыми params (нулевая grid)."""
        grid = _build_grid({})
        assert grid == [{}]

    def test_none_in_values(self):
        """None — валидное значение (например, seasonal=None отключает сезонность)."""
        grid = _build_grid({"seasonal": ["add", None]})
        assert len(grid) == 2
        assert {"seasonal": None} in grid
        assert {"seasonal": "add"} in grid

    def test_bool_in_values(self):
        grid = _build_grid({"damped": [False, True]})
        assert len(grid) == 2
        assert {"damped": False} in grid
        assert {"damped": True} in grid

    def test_arima_grid_size(self, spec):
        """ARIMA param_space: p(3) × d(2) × q(3) = 18 combos."""
        arima = spec.get_model("arima")
        assert arima.param_space is not None
        grid = _build_grid(arima.param_space)
        assert len(grid) == 18


# ═══════════════════════════════════════════════════════════
# 3. _truncate_grid — MAX_TRIALS ЗАЩИТА
# ═══════════════════════════════════════════════════════════

class TestTruncateGrid:
    """_truncate_grid(grid, max_trials, random_state) → (trials, truncated).

    Контракт:
      - len(grid) <= max_trials → без изменений, truncated=False
      - len(grid) > max_trials → random sample max_trials trials, truncated=True
      - random_state → воспроизводимость
    """

    def test_grid_under_max_no_truncation(self):
        grid = [{"p": i} for i in range(10)]
        trials, truncated = _truncate_grid(grid, max_trials=64, random_state=42)
        assert truncated is False
        assert trials == grid
        assert len(trials) == 10

    def test_grid_equal_max_no_truncation(self):
        """Граница: grid_size == max_trials — не truncation."""
        grid = [{"p": i} for i in range(64)]
        trials, truncated = _truncate_grid(grid, max_trials=64, random_state=42)
        assert truncated is False
        assert len(trials) == 64

    def test_grid_over_max_truncates(self):
        grid = [{"p": i} for i in range(100)]
        trials, truncated = _truncate_grid(grid, max_trials=64, random_state=42)
        assert truncated is True
        assert len(trials) == 64

    def test_user_smaller_max_trials_truncates(self):
        """User просит max_trials=5 < grid_size=12 → truncated=True, n=5."""
        grid = [{"p": i} for i in range(12)]
        trials, truncated = _truncate_grid(grid, max_trials=5, random_state=42)
        assert truncated is True
        assert len(trials) == 5

    def test_reproducible_with_same_seed(self):
        """Тот же random_state → тот же sampled набор."""
        grid = [{"p": i} for i in range(100)]
        t1, _ = _truncate_grid(grid, max_trials=10, random_state=42)
        t2, _ = _truncate_grid(grid, max_trials=10, random_state=42)
        assert t1 == t2

    def test_different_seed_different_sample(self):
        """Разный random_state → (почти наверняка) разный sampled набор."""
        grid = [{"p": i} for i in range(100)]
        t1, _ = _truncate_grid(grid, max_trials=10, random_state=42)
        t2, _ = _truncate_grid(grid, max_trials=10, random_state=99)
        assert t1 != t2

    def test_sampled_trials_are_subset_of_original(self):
        grid = [{"p": i} for i in range(100)]
        trials, _ = _truncate_grid(grid, max_trials=10, random_state=42)
        for t in trials:
            assert t in grid

    def test_no_duplicates_in_sample(self):
        """Random.sample без возвращения — каждый trial уникален."""
        grid = [{"p": i} for i in range(100)]
        trials, _ = _truncate_grid(grid, max_trials=10, random_state=42)
        assert len(set(tuple(sorted(t.items())) for t in trials)) == 10

    def test_max_trials_constant(self):
        """MAX_TRIALS = 64 — хардкод-контракт из Phase 1-A."""
        assert MAX_TRIALS == 64


# ═══════════════════════════════════════════════════════════
# 4. _execute_tune — ИНТЕГРАЦИЯ GRID × CV × SELECTION
# ═══════════════════════════════════════════════════════════

class TestExecuteTuneEts:
    """Интеграционные тесты _execute_tune для ETS."""

    def test_ets_returns_valid_response(self, spec):
        series = _make_series(60)
        resp = _execute_tune(
            spec=spec, model_id="ets", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=None, metric="rmse", random_state=42,
        )
        assert resp.model_id == "ets"
        assert resp.model_name  # non-empty
        assert resp.family_id == "exponential_smoothing"
        assert resp.grid_size == 12
        assert resp.n_trials == 12
        assert resp.truncated is False
        assert 0 <= resp.best_trial < resp.n_trials
        assert resp.best_params in [t.params for t in resp.trials]
        assert resp.metric == "rmse"
        assert resp.duration_ms >= 0

    def test_ets_trials_all_have_correct_n_folds(self, spec):
        """n_folds в trials = cv.n_splits (если ряд не слишком короток)."""
        series = _make_series(60)
        resp = _execute_tune(
            spec=spec, model_id="ets", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=None, metric="rmse", random_state=42,
        )
        assert len(resp.trials) == 12
        for t in resp.trials:
            assert t.n_folds == 3

    def test_ets_cv_config_echoed_back(self, spec):
        series = _make_series(60)
        cv = CVConfig(n_splits=4, test_size=2, min_train_size=10, step=2)
        resp = _execute_tune(
            spec=spec, model_id="ets", series=series,
            cv_config=cv, max_trials=None, metric="rmse", random_state=42,
        )
        assert resp.cv_config.n_splits == 4
        assert resp.cv_config.test_size == 2
        assert resp.cv_config.min_train_size == 10
        assert resp.cv_config.step == 2


class TestExecuteTuneOtherModels:
    """ets_damped и arima — другие модели с param_space."""

    def test_ets_damped_grid(self, spec):
        series = _make_series(60)
        resp = _execute_tune(
            spec=spec, model_id="ets_damped", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=None, metric="rmse", random_state=42,
        )
        assert resp.grid_size == 6  # 2×3×1
        assert resp.n_trials == 6
        assert resp.truncated is False
        assert resp.family_id == "exponential_smoothing"

    def test_arima_grid(self, spec):
        series = _make_series(60)
        resp = _execute_tune(
            spec=spec, model_id="arima", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=None, metric="rmse", random_state=42,
        )
        assert resp.grid_size == 18  # 3×2×3
        assert resp.n_trials == 18
        assert resp.truncated is False
        assert resp.family_id == "arima"


class TestExecuteTuneErrors:
    """Ошибка-кейсы: 404, 422, 422 (validation)."""

    def test_unknown_model_raises_404(self, spec):
        series = _make_series(60)
        with pytest.raises(HTTPException) as exc_info:
            _execute_tune(
                spec=spec, model_id="nonexistent_model", series=series,
                cv_config=CVConfig(n_splits=3, test_size=2),
                max_trials=None, metric="rmse", random_state=42,
            )
        assert exc_info.value.status_code == 404
        assert "nonexistent_model" in exc_info.value.detail

    @pytest.mark.parametrize("model_id", ["naive", "seasonal_naive", "drift", "mean"])
    def test_baseline_model_raises_422(self, spec, model_id):
        """Baseline-модели не имеют param_space → 422."""
        series = _make_series(60)
        with pytest.raises(HTTPException) as exc_info:
            _execute_tune(
                spec=spec, model_id=model_id, series=series,
                cv_config=CVConfig(n_splits=3, test_size=2),
                max_trials=None, metric="rmse", random_state=42,
            )
        assert exc_info.value.status_code == 422
        assert "param_space" in exc_info.value.detail or "тюнинг" in exc_info.value.detail.lower()

    def test_theta_no_param_space_raises_422(self, spec):
        """theta не имеет param_space (формула фиксирована) → 422."""
        series = _make_series(60)
        with pytest.raises(HTTPException) as exc_info:
            _execute_tune(
                spec=spec, model_id="theta", series=series,
                cv_config=CVConfig(n_splits=3, test_size=2),
                max_trials=None, metric="rmse", random_state=42,
            )
        assert exc_info.value.status_code == 422

    def test_too_short_series_raises_422(self, spec):
        """Ряд короче cv.min_samples() → 422.

        min_samples = min_train_size + test_size + (n_splits-1)*step
                    = 10 + 2 + (5-1)*2 = 20
        """
        series = [1.0, 2.0, 3.0]  # 3 точки — мало для 5 folds
        with pytest.raises(HTTPException) as exc_info:
            _execute_tune(
                spec=spec, model_id="ets", series=series,
                cv_config=CVConfig(n_splits=5, test_size=2, min_train_size=10),
                max_trials=None, metric="rmse", random_state=42,
            )
        assert exc_info.value.status_code == 422
        # В сообщении есть минимально требуемая длина (20) и фактическая (3)
        assert "20" in str(exc_info.value.detail)
        assert "3" in str(exc_info.value.detail)

    def test_invalid_metric_raises_422(self, spec):
        """Несуществующая метрика → 422 (не падает с KeyError)."""
        series = _make_series(60)
        with pytest.raises(HTTPException) as exc_info:
            _execute_tune(
                spec=spec, model_id="ets", series=series,
                cv_config=CVConfig(n_splits=3, test_size=2),
                max_trials=None, metric="nonexistent_metric", random_state=42,
            )
        assert exc_info.value.status_code == 422
        assert "metric" in exc_info.value.detail.lower()


class TestExecuteTuneBestSelection:
    """best_trial — выбор trial'а с минимальным metric."""

    def test_best_trial_has_min_rmse(self, spec):
        series = _make_series(60)
        resp = _execute_tune(
            spec=spec, model_id="ets", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=None, metric="rmse", random_state=42,
        )
        best_rmse = resp.trials[resp.best_trial].metrics.rmse
        all_rmses = [t.metrics.rmse for t in resp.trials]
        assert best_rmse == min(all_rmses)

    def test_best_trial_has_min_mae(self, spec):
        series = _make_series(60)
        resp = _execute_tune(
            spec=spec, model_id="ets", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=None, metric="mae", random_state=42,
        )
        best_mae = resp.trials[resp.best_trial].metrics.mae
        all_maes = [t.metrics.mae for t in resp.trials]
        assert best_mae == min(all_maes)

    def test_best_trial_has_min_weighted_score(self, spec):
        series = _make_series(60)
        resp = _execute_tune(
            spec=spec, model_id="arima", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=None, metric="weighted_score", random_state=42,
        )
        best_ws = resp.trials[resp.best_trial].metrics.weighted_score
        all_ws = [t.metrics.weighted_score for t in resp.trials]
        assert best_ws == min(all_ws)

    def test_best_params_match_best_trial(self, spec):
        """best_params === trials[best_trial].params."""
        series = _make_series(60)
        resp = _execute_tune(
            spec=spec, model_id="ets", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=None, metric="rmse", random_state=42,
        )
        assert resp.best_params == resp.trials[resp.best_trial].params


# ═══════════════════════════════════════════════════════════
# 5. MAX_TRIALS через _execute_tune (реальная truncation)
# ═══════════════════════════════════════════════════════════

class TestExecuteTuneMaxTrials:
    """max_trials параметр — клиентское ограничение + MAX_TRIALS hard cap."""

    def test_user_max_trials_smaller_than_grid(self, spec):
        """User просит max_trials=5, grid_size=12 → truncated=True, n_trials=5."""
        series = _make_series(60)
        resp = _execute_tune(
            spec=spec, model_id="ets", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=5, metric="rmse", random_state=42,
        )
        assert resp.truncated is True
        assert resp.n_trials == 5
        assert resp.grid_size == 12

    def test_user_max_trials_larger_than_grid(self, spec):
        """User просит max_trials=100, grid_size=12 → нет truncation, n_trials=12."""
        series = _make_series(60)
        resp = _execute_tune(
            spec=spec, model_id="ets", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=100, metric="rmse", random_state=42,
        )
        assert resp.truncated is False
        assert resp.n_trials == 12

    def test_user_max_trials_clamped_to_max_trials_constant(self, spec):
        """User просит max_trials=1000 (> MAX_TRIALS) → clamp to MAX_TRIALS.

        Если grid_size тоже > MAX_TRIALS, truncated=True, n_trials=MAX_TRIALS.
        """
        huge_spec = _make_huge_grid_spec(grid_size=128)
        series = _make_series(60)
        resp = _execute_tune(
            spec=huge_spec, model_id="test_model", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=1000,  # requested > MAX_TRIALS → clamp
            metric="rmse", random_state=42,
        )
        assert resp.truncated is True
        assert resp.n_trials == MAX_TRIALS  # clamped, not 1000
        assert resp.grid_size == 128

    def test_grid_over_max_trials_truncates_to_max(self):
        """grid_size=128 > MAX_TRIALS=64 → truncated=True, n_trials=64."""
        huge_spec = _make_huge_grid_spec(grid_size=128)
        series = _make_series(60)
        resp = _execute_tune(
            spec=huge_spec, model_id="test_model", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=None,  # по умолчанию → MAX_TRIALS
            metric="rmse", random_state=42,
        )
        assert resp.truncated is True
        assert resp.n_trials == MAX_TRIALS
        assert resp.grid_size == 128

    def test_reproducible_random_state_in_execute_tune(self, spec):
        """Тот же random_state → тот же набор trials (воспроизводимость)."""
        series = _make_series(60)
        kwargs = dict(
            spec=spec, model_id="ets", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=5, metric="rmse", random_state=42,
        )
        resp1 = _execute_tune(**kwargs)
        resp2 = _execute_tune(**kwargs)
        assert [t.params for t in resp1.trials] == [t.params for t in resp2.trials]

    def test_different_random_state_changes_trials(self, spec):
        """Разный random_state → (почти наверняка) разный набор trials."""
        series = _make_series(60)
        resp1 = _execute_tune(
            spec=spec, model_id="ets", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=5, metric="rmse", random_state=42,
        )
        resp2 = _execute_tune(
            spec=spec, model_id="ets", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=5, metric="rmse", random_state=99,
        )
        assert [t.params for t in resp1.trials] != [t.params for t in resp2.trials]


# ═══════════════════════════════════════════════════════════
# 6. КОНТРАКТ: trials СОРТИРОВАН ПО ПОРЯДКУ В GRID (когда нет truncation)
# ═══════════════════════════════════════════════════════════

class TestTrialsOrder:
    """Без truncation trials идут в порядке декартова произведения param_space."""

    def test_ets_trials_no_truncation_preserves_grid_order(self, spec):
        series = _make_series(60)
        resp = _execute_tune(
            spec=spec, model_id="ets", series=series,
            cv_config=CVConfig(n_splits=3, test_size=2),
            max_trials=None, metric="rmse", random_state=42,
        )
        ets = spec.get_model("ets")
        assert ets.param_space is not None
        expected_grid = _build_grid(ets.param_space)
        actual_params = [t.params for t in resp.trials]
        assert actual_params == expected_grid, (
            "Без truncation trials должны идти в порядке декартова произведения"
        )
