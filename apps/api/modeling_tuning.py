"""Hyperparameter search over the immutable EDA BacktestPlan."""
from __future__ import annotations

import itertools
import hashlib
import json
import random
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from uuid import uuid4

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


def parameter_signature(model_id: str, params: Mapping[str, Any]) -> str:
    """Return a stable identity for the exact model parameterization."""
    encoded = json.dumps(
        {"model_id": model_id, "params": dict(params)},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def oof_signature(points: list[dict[str, Any]]) -> str:
    """Bind diagnostics to ordered OOF facts, forecasts and residuals."""
    canonical = [
        {
            "fold": point.get("fold"), "horizon_step": point.get("horizon_step"),
            "index": point.get("index"), "actual": point.get("actual"),
            "predicted": point.get("predicted"), "residual": point.get("residual"),
        }
        for point in points
    ]
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class TuningPlanExecution:
    response: TuneResponse
    best_backtest: dict[str, Any]


@dataclass(frozen=True)
class PreparedTuningGrid:
    selected: list[dict[str, Any]]
    grid_size: int
    truncated: bool


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


def prepare_tuning_grid(
    param_space: Mapping[str, list[Any]], *, max_trials: Optional[int],
    metric: str, random_state: int,
) -> PreparedTuningGrid:
    """Validate and deterministically select the trials before execution."""
    if metric not in VALID_SESSION_TUNING_METRICS:
        raise BacktestExecutionError(
            "Session tuning поддерживает mae/rmse/mape/mase; weighted_score "
            "определяется только после сравнения общего cohort"
        )
    full_grid = _grid(param_space)
    if not full_grid:
        raise BacktestExecutionError("Param space пуст")
    requested = min(int(max_trials or MAX_TRIALS), MAX_TRIALS)
    selected, truncated = _truncate(full_grid, requested, random_state)
    return PreparedTuningGrid(
        selected=selected, grid_size=len(full_grid), truncated=truncated,
    )


def execute_tuning_trial(
    *, model_id: str, model_name: str, family_id: str, params: Mapping[str, Any],
    series: list[float], labels: list[str], plan: BacktestPlan, seasonal_period: int,
    metric: str, predictors: Optional[Mapping[str, Predictor]] = None,
    fold_preprocessor: Optional[FoldPreprocessorProtocol] = None,
    preprocessing_warnings: Optional[list[str]] = None,
) -> tuple[TuneTrialResult, dict[str, Any]]:
    """Execute exactly one bounded trial on the immutable EDA plan."""
    if metric not in VALID_SESSION_TUNING_METRICS:
        raise BacktestExecutionError(f"Метрика tuning '{metric}' не поддерживается")
    result = run_backtest_plan(
        model_id=model_id, model_name=model_name, family_id=family_id,
        series=series, labels=labels, plan=plan,
        seasonal_period=seasonal_period, params=dict(params),
        predictors=predictors, fold_preprocessor=fold_preprocessor,
        preprocessing_warnings=preprocessing_warnings,
    )
    metrics = BacktestMetrics(**result["metrics"])
    if getattr(metrics, metric) is None:
        raise BacktestExecutionError(f"Метрика {metric} не определена")
    return TuneTrialResult(
        params=dict(params), metrics=metrics, n_folds=len(plan.folds),
    ), result


def finalize_tuning_plan_with_artifacts(
    *, model_id: str, model_name: str, family_id: str,
    trials: list[TuneTrialResult], trial_backtests: list[dict[str, Any]],
    failures: list[str], grid_size: int, selected_count: int, truncated: bool,
    plan: BacktestPlan, metric: str, duration_ms: float,
    fold_preprocessor: Optional[FoldPreprocessorProtocol] = None,
    preprocessing_warnings: Optional[list[str]] = None,
) -> TuningPlanExecution:
    """Build the canonical response after monolithic or resumed execution."""
    if not trials:
        detail = failures[0] if failures else "нет исполнимых trials"
        raise BacktestExecutionError(
            f"Ни один trial модели '{model_id}' не завершился успешно: {detail}"
        )
    best_index = min(
        range(len(trials)),
        key=lambda index: float(getattr(trials[index].metrics, metric)),
    )
    warnings = list(preprocessing_warnings or [])
    if failures:
        warnings.append(
            f"Пропущено несовместимых trial: {len(failures)} из {selected_count}."
        )
    preprocessing = (
        dict(fold_preprocessor.summary) if fold_preprocessor is not None else {
            "fit_policy": "none", "source_column": plan.target_column,
            "target_column": plan.target_column, "evaluation_scale": plan.target_column,
        }
    )
    tuning_id = str(uuid4())
    best_params = trials[best_index].params
    response = TuneResponse(
        model_id=model_id, model_name=model_name, family_id=family_id,
        best_params=best_params, best_metrics=trials[best_index].metrics,
        best_trial=best_index, n_trials=len(trials), grid_size=grid_size,
        truncated=truncated, cv_config=_cv_summary(plan), metric=metric,
        trials=trials, duration_ms=round(duration_ms, 2),
        strategy=plan.strategy, cohort_id=plan.cohort_id,
        objective=plan.objective, cohort_contract=plan.cohort_contract,
        folds=[
            TuneFoldPlan(
                fold=fold.fold, train_start=fold.train_indices[0],
                train_end=fold.train_indices[-1], test_start=fold.test_indices[0],
                test_end=fold.test_indices[-1], gap=fold.gap,
            )
            for fold in plan.folds
        ],
        preprocessing=preprocessing, warnings=warnings, tuning_id=tuning_id,
        parameter_signature=parameter_signature(model_id, best_params),
        execution_contract=trial_backtests[best_index].get("execution_contract", {}),
    )
    return TuningPlanExecution(response=response, best_backtest=trial_backtests[best_index])


def execute_tuning_plan_with_artifacts(
    *, model_id: str, model_name: str, family_id: str,
    param_space: Mapping[str, list[Any]], series: list[float], labels: list[str],
    plan: BacktestPlan, seasonal_period: int, max_trials: Optional[int],
    metric: str, random_state: int,
    predictors: Optional[Mapping[str, Predictor]] = None,
    fold_preprocessor: Optional[FoldPreprocessorProtocol] = None,
    preprocessing_warnings: Optional[list[str]] = None,
) -> TuningPlanExecution:
    """Execute every trial with the same folds and engine as backtest."""
    started = time.monotonic()
    prepared_grid = prepare_tuning_grid(
        param_space, max_trials=max_trials, metric=metric, random_state=random_state,
    )
    trials: list[TuneTrialResult] = []
    trial_backtests: list[dict[str, Any]] = []
    failures: list[str] = []
    for params in prepared_grid.selected:
        try:
            trial, result = execute_tuning_trial(
                model_id=model_id, model_name=model_name, family_id=family_id,
                params=params, series=series, labels=labels, plan=plan,
                seasonal_period=seasonal_period, metric=metric,
                predictors=predictors, fold_preprocessor=fold_preprocessor,
                preprocessing_warnings=preprocessing_warnings,
            )
            trials.append(trial)
            trial_backtests.append(result)
        except (BacktestExecutionError, ValueError, RuntimeError, ArithmeticError) as exc:
            failures.append(f"params={params}: {exc}")
    return finalize_tuning_plan_with_artifacts(
        model_id=model_id, model_name=model_name, family_id=family_id,
        trials=trials, trial_backtests=trial_backtests, failures=failures,
        grid_size=prepared_grid.grid_size,
        selected_count=len(prepared_grid.selected), truncated=prepared_grid.truncated,
        plan=plan, metric=metric,
        duration_ms=(time.monotonic() - started) * 1000,
        fold_preprocessor=fold_preprocessor,
        preprocessing_warnings=preprocessing_warnings,
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
    """Backward-compatible response-only facade for non-session callers."""
    return execute_tuning_plan_with_artifacts(
        model_id=model_id, model_name=model_name, family_id=family_id,
        param_space=param_space, series=series, labels=labels, plan=plan,
        seasonal_period=seasonal_period, max_trials=max_trials, metric=metric,
        random_state=random_state, predictors=predictors,
        fold_preprocessor=fold_preprocessor,
        preprocessing_warnings=preprocessing_warnings,
    ).response
