"""Hyperparameter search over the immutable EDA BacktestPlan."""
from __future__ import annotations

import itertools
import random
import time
from typing import Any, Mapping, Optional

from apps.api.backtesting import (
    BacktestExecutionError,
    FoldPreprocessorProtocol,
    BacktestPlan,
    Predictor,
    run_backtest_plan,
)
from apps.api.schemas import (
    BacktestMetrics,
    CVConfig,
    TuneFoldPlan,
    TuneResponse,
    TuneTrialResult,
)


MAX_TRIALS = 64
VALID_SESSION_TUNING_METRICS = {"mae", "rmse", "mape", "mase"}


def _grid(param_space: Mapping[str, list[Any]]) -> list[dict[str, Any]]:
    keys = list(param_space)
    return [
        dict(zip(keys, values, strict=True))
        for values in itertools.product(*(param_space[key] for key in keys))
    ]


def _truncate(
    grid: list[dict[str, Any]], max_trials: int, random_state: int,
) -> tuple[list[dict[str, Any]], bool]:
    if len(grid) <= max_trials:
        return grid, False
    indices = sorted(random.Random(random_state).sample(range(len(grid)), max_trials))
    return [grid[index] for index in indices], True


def _cv_summary(plan: BacktestPlan) -> CVConfig:
    first_train = len(plan.folds[0].train_indices)
    if len(plan.folds) > 1:
        step = plan.folds[1].test_indices[0] - plan.folds[0].test_indices[0]
    else:
        step = plan.horizon
    return CVConfig(
        n_splits=len(plan.folds), test_size=plan.horizon,
        min_train_size=first_train, step=step, gap=plan.gap,
    )


def execute_tuning_plan(
    *, model_id: str, model_name: str, family_id: str,
    param_space: Mapping[str, list[Any]], series: list[float], labels: list[str],
    plan: BacktestPlan, seasonal_period: int, max_trials: Optional[int],
    metric: str, random_state: int,
    predictors: Optional[Mapping[str, Predictor]] = None,
    fold_preprocessor: Optional[FoldPreprocessorProtocol] = None,
    preprocessing_warnings: Optional[list[str]] = None,
) -> TuneResponse:
    """Execute every trial with the same folds and engine as backtest."""
    started = time.monotonic()
    if metric not in VALID_SESSION_TUNING_METRICS:
        raise BacktestExecutionError(
            "Session tuning поддерживает mae/rmse/mape/mase; weighted_score "
            "определяется только после сравнения общего cohort"
        )
    full_grid = _grid(param_space)
    if not full_grid:
        raise BacktestExecutionError(f"Для модели '{model_id}' param_space пуст")
    requested = min(int(max_trials or MAX_TRIALS), MAX_TRIALS)
    selected_grid, truncated = _truncate(full_grid, requested, random_state)
    trials: list[TuneTrialResult] = []
    warnings = list(preprocessing_warnings or [])
    failures: list[str] = []
    for params in selected_grid:
        try:
            result = run_backtest_plan(
                model_id=model_id, model_name=model_name, family_id=family_id,
                series=series, labels=labels, plan=plan,
                seasonal_period=seasonal_period, params=params,
                predictors=predictors, fold_preprocessor=fold_preprocessor,
                preprocessing_warnings=preprocessing_warnings,
            )
            metrics = BacktestMetrics(**result["metrics"])
            if getattr(metrics, metric) is None:
                failures.append(f"params={params}: метрика {metric} не определена")
                continue
            trials.append(TuneTrialResult(
                params=params, metrics=metrics, n_folds=len(plan.folds),
            ))
        except (BacktestExecutionError, ValueError, RuntimeError, ArithmeticError) as exc:
            failures.append(f"params={params}: {exc}")
    if not trials:
        detail = failures[0] if failures else "нет исполнимых trials"
        raise BacktestExecutionError(
            f"Ни один trial модели '{model_id}' не завершился успешно: {detail}"
        )
    best_index = min(
        range(len(trials)),
        key=lambda index: float(getattr(trials[index].metrics, metric)),
    )
    if failures:
        warnings.append(
            f"Пропущено несовместимых trial: {len(failures)} из {len(selected_grid)}."
        )
    preprocessing = (
        dict(fold_preprocessor.summary) if fold_preprocessor is not None else {
            "fit_policy": "none", "source_column": plan.target_column,
            "target_column": plan.target_column, "evaluation_scale": plan.target_column,
        }
    )
    return TuneResponse(
        model_id=model_id, model_name=model_name, family_id=family_id,
        best_params=trials[best_index].params,
        best_metrics=trials[best_index].metrics,
        best_trial=best_index, n_trials=len(trials), grid_size=len(full_grid),
        truncated=truncated, cv_config=_cv_summary(plan), metric=metric,
        trials=trials, duration_ms=round((time.monotonic() - started) * 1000, 2),
        strategy=plan.strategy, cohort_id=plan.cohort_id,
        folds=[
            TuneFoldPlan(
                fold=fold.fold, train_start=fold.train_indices[0],
                train_end=fold.train_indices[-1], test_start=fold.test_indices[0],
                test_end=fold.test_indices[-1], gap=fold.gap,
            )
            for fold in plan.folds
        ],
        preprocessing=preprocessing, warnings=warnings,
    )
