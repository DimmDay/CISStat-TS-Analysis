# tests/unit/test_vector_tuning.py
"""Task 133 -- векторный tuning: grid search над multivariate-планом.

Требования работы (worklog3.md, «Границы Task 132»):
- execute_vector_tuning_plan исполняет КАЖДЫЙ trial на тех же EDA-folds
  и тем же векторным движком, что и backtest (никаких упрощённых
  train/test-срезов в tuning);
- grid/truncation/finalization -- семантика prepare_tuning_grid /
  finalize_tuning_plan_with_artifacts (общий контракт tuning платформы);
- TuneResponse честно несёт objective=multivariate и cohort-контракт
  плана; promoted best_backtest -- полноценный векторный артефакт
  (per_series_metrics, scaled_loss, vector_baseline);
- несовместимые trials записываются в failures (не рушат план);
  все-провалены -- BacktestExecutionError;
- bounded param_space берётся из rules/modeling.yaml (var: 6 trials,
  vecm: 6 trials);
- VECM tuning: ранг Йохансена fold-local на каждом trial ("auto").
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apps.api.backtesting import (
    BacktestExecutionError,
    build_backtest_plan,
    run_vector_backtest_plan,
)
from apps.api.modeling_tuning import (
    MAX_TRIALS,
    execute_vector_tuning_plan_with_artifacts,
    prepare_tuning_grid,
)
from apps.api.multivariate_contract import (
    build_endogenous_system,
    multivariate_cohort_contract,
)


def _stationary_system(n: int = 120, seed: int = 7) -> np.ndarray:
    """Стационарная VAR(1)-система K=3 (как в test_var_backtest)."""
    rng = np.random.default_rng(seed)
    eps = rng.normal(size=(n, 3))
    out = np.zeros((n, 3))
    for t in range(1, n):
        out[t] = 0.5 * out[t - 1] + eps[t] + 0.2 * np.roll(out[t - 1], 1)
    return out


def _labels(n: int) -> list[str]:
    return [
        stamp.strftime("%Y-%m-%d")
        for stamp in pd.date_range("2020-01-01", periods=n, freq="D")
    ]


def _validation(n_splits: int = 2, horizon: int = 3, gap: int = 0, n: int = 120):
    folds = []
    train_end = n - n_splits * horizon - gap * n_splits - 1
    for index in range(n_splits):
        start_test = train_end + 1 + gap + (horizon + gap) * index
        folds.append({
            "fold": index + 1, "train_start": 0,
            "train_end": train_end + (horizon + gap) * index,
            "gap_size": gap, "test_start": start_test,
            "test_end": start_test + horizon - 1,
        })
    return {"strategy": "expanding", "horizon": horizon,
            "n_splits": n_splits, "gap": gap, "folds": folds}


def _vector_plan(matrix: np.ndarray, *, n_splits: int = 2, horizon: int = 3):
    labels = _labels(len(matrix))
    system = build_endogenous_system(
        {name: [float(v) for v in matrix[:, position]]
         for position, name in enumerate(("y", "b", "c"))},
        timestamps=labels,
    )
    from app.core.passport import series_fingerprint

    fingerprints = {
        name: series_fingerprint(pd.Series(
            [float(v) for v in matrix[:, position]], index=labels,
        ))
        for position, name in enumerate(("y", "b", "c"))
    }
    contract = multivariate_cohort_contract(
        system, series_fingerprints=fingerprints,
    )
    plan = build_backtest_plan(
        _validation(n_splits=n_splits, horizon=horizon, n=len(matrix)),
        n_observations=len(matrix), fingerprint="fp-tuning",
        target_column="y", seasonal_period=1,
        objective="multivariate", series_fingerprints=fingerprints,
        cohort_contract_override=contract,
    )
    return system, plan


def _tune(model_id: str, matrix: np.ndarray, param_space: dict,
          metric: str = "rmse", **kwargs):
    system, plan = _vector_plan(matrix, **kwargs.pop("plan_kwargs", {}))
    return execute_vector_tuning_plan_with_artifacts(
        model_id=model_id, model_name=model_id.upper(),
        family_id="multivariate", param_space=param_space,
        system=system, plan=plan, seasonal_period=1,
        max_trials=kwargs.pop("max_trials", None), metric=metric,
        random_state=kwargs.pop("random_state", 42), **kwargs,
    )


class TestVectorTuningPlan:
    """Векторный tuning: trials на тех же folds, честный best."""

    def test_var_grid_from_bounded_space(self):
        # Аудит Task 133 (проба M4): сетка обязана быть РАЗЛИЧИМОЙ.
        # Прежняя [4, 8]x["aic"] вырождалась -- AIC выбирал одинаковый
        # порядок в обоих trials, RMSE совпадали бит-в-бит, и мутация
        # argmax вместо argmin выживала.  ic=None => фиксированные
        # порядки 4 и 8 -- разные фиты, разные RMSE.
        matrix = _stationary_system()
        execution = _tune(
            "var", matrix,
            {"maxlags": [4, 8], "ic": [None]},
        )
        response = execution.response
        assert response.n_trials == 2
        assert response.grid_size == 2
        assert response.truncated is False
        assert response.objective == "multivariate"
        assert response.metric == "rmse"
        assert response.best_params in (
            {"maxlags": 4, "ic": None}, {"maxlags": 8, "ic": None},
        )
        # Best -- минимум метрики среди trials (аргмин, не первый);
        # сетка различима, поэтому assertion чувствителен к argmax-мутации.
        values = [float(getattr(trial.metrics, "rmse")) for trial in response.trials]
        assert len({round(value, 12) for value in values}) == 2
        assert response.best_trial == values.index(min(values))

    def test_trials_genuinely_differ(self):
        """Разные гиперпараметры -- разные OOF-прогнозы (нет подмены)."""
        matrix = _stationary_system()
        response = _tune(
            "var", matrix, {"maxlags": [4, 8], "ic": [None]},
        ).response
        rmse_values = {round(float(trial.metrics.rmse), 12)
                       for trial in response.trials}
        assert len(rmse_values) == 2

    def test_best_backtest_is_full_vector_artifact(self):
        matrix = _stationary_system()
        execution = _tune("var", matrix, {"maxlags": [4], "ic": ["aic"]})
        best = execution.best_backtest
        assert set(best["per_series_metrics"]) == {"y", "b", "c"}
        assert best["scaled_loss"] is not None
        assert best["vector_baseline"]["aggregate"]["mae"] > 0
        assert best["objective"] == "multivariate"
        assert best["cohort_contract"]["objective"] == "multivariate"
        points = best["oof_predictions"]
        assert {point["series"] for point in points} == {"y", "b", "c"}

    def test_trials_share_plan_folds_with_backtest(self):
        """Тот же план == те же folds/points, что у обычного backtest."""
        matrix = _stationary_system()
        system, plan = _vector_plan(matrix)
        reference = run_vector_backtest_plan(
            model_id="var", model_name="VAR", family_id="multivariate",
            system=system, plan=plan, seasonal_period=1,
            params={"maxlags": 4, "ic": None},
        )
        execution = execute_vector_tuning_plan_with_artifacts(
            model_id="var", model_name="VAR", family_id="multivariate",
            param_space={"maxlags": [4], "ic": [None]},
            system=system, plan=plan, seasonal_period=1,
            max_trials=None, metric="rmse", random_state=42,
        )
        trial = execution.response.trials[0]
        assert round(float(trial.metrics.rmse), 12) == \
            round(float(reference["metrics"]["rmse"]), 12)
        assert [point["predicted"] for point in execution.best_backtest["oof_predictions"]] == \
            [point["predicted"] for point in reference["oof_predictions"]]

    def test_vecm_vector_tuning_fold_local_rank(self):
        """VECM tuning: ранг "auto" переоценивается на train-срезе fold'а."""
        rng = np.random.default_rng(13)
        n = 120
        y1 = 100.0 + np.cumsum(rng.normal(0.0, 1.0, n))
        matrix = np.column_stack([y1, y1 + rng.normal(0.0, 0.5, n),
                                  50.0 + np.cumsum(rng.normal(0.0, 1.0, n))])
        execution = _tune(
            "vecm", matrix,
            {"k_ar_diff": [1, 2], "deterministic": ["ci"]},
        )
        response = execution.response
        assert response.n_trials == 2
        assert response.objective == "multivariate"
        for fold in execution.best_backtest["folds"]:
            vecm_diag = fold["multivariate_diagnostics"]["vecm"]
            assert vecm_diag["coint_rank"] >= 1
            assert vecm_diag["rank_selection"]["mode"] == "auto"


class TestFailureSemantics:
    """Несовместимые trials -- честные failures; полный провал -- ошибка."""

    def test_infeasible_trial_recorded_not_fatal(self):
        short = _stationary_system(n=30)
        execution = _tune(
            "var", short, {"maxlags": [12, 1], "ic": [None]},
            plan_kwargs={"n_splits": 2, "horizon": 3},
        )
        response = execution.response
        # maxlags=12 не помещается в train ~24 наблюдения K=3 (нужно 51) --
        # честный failure; maxlags=1 исполним.
        assert response.n_trials == 1
        assert len(response.trials) == 1

    def test_all_trials_failed_raises(self):
        short = _stationary_system(n=30)
        with pytest.raises(BacktestExecutionError, match="Ни один trial"):
            _tune("var", short, {"maxlags": [12], "ic": [None]})

    def test_metric_validation(self):
        matrix = _stationary_system()
        with pytest.raises(BacktestExecutionError, match="weighted_score"):
            _tune("var", matrix, {"maxlags": [2], "ic": ["aic"]},
                  metric="weighted_score")


class TestGridSemantics:
    """Детерминированный grid: усечение <= MAX_TRIALS, стабильный seed."""

    def test_truncation_deterministic(self):
        space = {"maxlags": list(range(1, 13)), "ic": ["aic", "bic", "hqic", "fpe"],
                 "trend": ["c", "n"]}  # 96 combos > 64
        first = prepare_tuning_grid(space, max_trials=None, metric="rmse",
                                    random_state=42)
        second = prepare_tuning_grid(space, max_trials=None, metric="rmse",
                                     random_state=42)
        assert first.grid_size == 96
        assert first.truncated is True
        assert len(first.selected) == MAX_TRIALS
        assert first.selected == second.selected

    def test_empty_space_yields_single_empty_trial(self):
        """Контракт платформы: _grid({}) == [{}] -- один trial с дефолтами.

        Пустой param_space отсекается выше по потоку (router: param_space
        is None -> 422); движок grid честно исполняет пустую комбинацию
        как модель с дефолтными параметрами.
        """
        prepared = prepare_tuning_grid({}, max_trials=None, metric="rmse",
                                       random_state=42)
        assert prepared.grid_size == 1
        assert prepared.selected == [{}]
        assert prepared.truncated is False

    def test_yaml_param_spaces_are_bounded(self):
        from src.catalog.modeling_spec_loader import ModelingSpec

        spec = ModelingSpec.from_yaml("rules/modeling.yaml")
        for model_id in ("var", "vecm"):
            model = spec.get_model(model_id)
            assert model is not None and model.param_space, model_id
            grid = prepare_tuning_grid(
                model.param_space, max_trials=None, metric="rmse",
                random_state=1,
            )
            assert grid.grid_size <= MAX_TRIALS, model_id
            assert grid.grid_size == 6, model_id  # 2x3 / 3x2 -- компактные grid
