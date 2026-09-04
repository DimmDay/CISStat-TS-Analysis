"""Session-backed, traceable Modeling workflow for both web shells."""
from __future__ import annotations

from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Literal, Optional
from uuid import uuid4

import numpy as np
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.core.passport import prepare_passport_series
from apps.api.backtesting import (
    BacktestExecutionError,
    build_backtest_plan,
    run_backtest_plan,
)
from apps.api.fold_preprocessing import prepare_modeling_target
from apps.api.model_readiness import (
    PRODUCTION_BACKTEST_MODEL_IDS,
    PRODUCTION_TUNING_MODEL_IDS,
)
from apps.api.modeling_comparison import (
    ComparisonContractError,
    build_comparison,
    diagnostics_signature,
)
from apps.api.modeling_selection import (
    SelectionContractError,
    SelectionPolicy,
    evaluate_selection,
)
from apps.api.modeling_tuning import (
    execute_tuning_plan_with_artifacts,
    oof_signature,
    parameter_signature,
)
from apps.api.modeling_workflow import build_modeling_context
from apps.api.routers.diagnostics import DiagnosticResult, _diagnose
from apps.api.routers.models import (
    _compute_candidates,
    _resolve_model_info,
    _run_backtest_with_series,
)
from apps.api.schemas import (
    BacktestResponse,
    CVConfig,
    CandidatesRequest,
    CandidatesResponse,
    DataProfileRequest,
    ModelingComparisonResponse,
    TuneResponse,
)
from apps.api.session_store import get_or_create_session_id, get_session_store


router = APIRouter()


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not-installed"


class ModelingCandidatesRequest(BaseModel):
    min_level: str = "CONDITIONALLY_APPLICABLE"
    strategy: Literal["expanding", "sliding", "single"] = "expanding"
    horizon: int = Field(12, ge=1, le=10000)
    n_splits: int = Field(5, ge=1, le=20)
    gap: int = Field(0, ge=0, le=10000)
    train_window: int = Field(60, ge=2, le=100000)


class ModelingBacktestRequest(BaseModel):
    model_id: str
    train_ratio: Optional[float] = Field(None, ge=0.5, le=0.95)


class ModelingTuneRequest(BaseModel):
    model_id: str
    cv: Optional[CVConfig] = None
    max_trials: Optional[int] = Field(None, ge=1)
    metric: Literal["mae", "rmse", "mape", "mase", "weighted_score"] = "rmse"
    random_state: int = 42


class ModelingDiagnosticsRequest(BaseModel):
    model_id: str
    alpha: float = Field(0.05, gt=0, lt=1)
    ljung_box_lags: Optional[int] = Field(None, ge=1, le=50)
    arch_lags: Optional[int] = Field(None, ge=1, le=20)


class SessionDiagnosticsResponse(BaseModel):
    model_id: str
    target_column: str
    n_observations: int
    residuals_count: int
    alpha: float
    params_source: Literal["model_default", "tuning"]
    params: dict[str, Any] = Field(default_factory=dict)
    parameter_signature: str
    tuning_id: Optional[str] = None
    backtest_run_id: str
    residuals_signature: str
    residuals_source: Literal["backtest_oof", "tuned_backtest_oof"]
    cohort_id: str
    preprocessing: dict[str, Any] = Field(default_factory=dict)
    diagnostics: list[DiagnosticResult]
    diagnostics_signature: str


class ModelingCompareRequest(BaseModel):
    model_ids: list[str] = Field(default_factory=list)


class ModelingSelectRequest(BaseModel):
    model_id: str
    selection_analysis_id: Optional[str] = None
    selection_signature: Optional[str] = None
    acknowledge_baseline_risk: bool = False
    acknowledge_selection_bias: bool = False
    acknowledge_ensemble_no_gain: bool = False


class ModelingSelectionEvaluationRequest(BaseModel):
    primary_metric: Literal["mae", "rmse"] = "rmse"
    max_member_relative_gap: float = Field(0.10, ge=0, le=10)
    max_error_correlation: float = Field(0.80, ge=-1, le=1)
    min_oof_points: int = Field(8, ge=2, le=100000)
    min_ensemble_relative_improvement: float = Field(0.01, ge=0, le=1)
    min_fold_win_rate: float = Field(0.50, ge=0, le=1)
    practical_tie_relative: float = Field(0.01, ge=0, le=1)


class ModelingCardRequest(BaseModel):
    notes: Optional[str] = Field(None, max_length=2000)


def _context(session, *, require_ready: bool = True, **kwargs) -> dict[str, Any]:
    try:
        context = build_modeling_context(session, **kwargs)
        if require_ready and not context.get("ready"):
            raise ValueError("Modeling заблокирован критическими проверками; устраните причины из traceability")
        return context
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _validation_contract(context: dict[str, Any]) -> dict[str, Any]:
    return {
        key: context["validation_strategy"].get(key)
        for key in (
            "column", "applicable", "reason",
            "strategy", "horizon", "n_splits", "gap", "train_window",
            "initial_train_size", "effective_splits", "requested_splits",
            "n_observations", "folds", "order_source", "order_column",
            "frequency", "warnings",
        )
    }


def _action_context(session) -> dict[str, Any]:
    """Rebuild readiness using the validation contract chosen for this run."""
    saved = session.modeling_artifacts.get("validation_strategy", {})
    kwargs = {
        "horizon": saved.get("horizon", 12),
        "strategy": saved.get("strategy", "expanding"),
        "n_splits": saved.get("n_splits", 5),
        "gap": saved.get("gap", 0),
        "train_window": saved.get("train_window", 60),
    }
    return _context(session, **{key: value for key, value in kwargs.items() if value is not None})


def _prepare_state(session, context: dict[str, Any], *, refresh_contract: bool = False) -> None:
    fingerprint = context["fingerprint"]
    if session.modeling_artifacts.get("source_fingerprint") != fingerprint:
        session.reset_modeling()
        session.modeling_artifacts = {
            "source_fingerprint": fingerprint,
            "source_checkpoint": context["checkpoint"],
            "profile": context["profile"],
            "validation_strategy": _validation_contract(context),
            "traceability_summary": context["traceability"]["summary"],
            "backtests": {}, "tuning": {}, "diagnostics": {}, "model_cards": {},
        }
        for stage in ("problem_definition", "data_structure", "constraint_mapping"):
            session.modeling_pipeline[stage] = "done"
        session.modeling_pipeline["candidate_generation"] = "in_progress"
    elif refresh_contract:
        session.modeling_artifacts["validation_strategy"] = _validation_contract(context)
        session.modeling_artifacts["profile"] = context["profile"]
        session.modeling_artifacts["runnable_shortlist"] = context["runnable_shortlist"]


def _trace_backtest(
    raw: dict[str, Any], *, model_id: str, params: dict[str, Any],
    params_source: Literal["model_default", "tuning"], tuning_id: Optional[str] = None,
) -> BacktestResponse:
    """Attach immutable execution and OOF lineage to a backtest payload."""
    payload = dict(raw)
    payload.update({
        "run_id": str(uuid4()),
        "params": dict(params),
        "params_source": params_source,
        "parameter_signature": parameter_signature(model_id, params),
        "tuning_id": tuning_id,
        "oof_signature": oof_signature(payload.get("oof_predictions") or []),
    })
    return BacktestResponse(**payload)


def _invalidate_after_model_run(session, model_id: str) -> None:
    """Remove every artifact that depended on an older OOF execution."""
    session.modeling_artifacts.setdefault("diagnostics", {}).pop(model_id, None)
    session.modeling_artifacts.pop("comparison", None)
    session.modeling_artifacts.pop("selection_analysis", None)
    session.modeling_artifacts.pop("ensemble_backtests", None)
    session.modeling_artifacts.pop("ensemble_diagnostics", None)
    session.modeling_artifacts.pop("selection", None)
    session.modeling_artifacts["model_cards"] = {}
    session.modeling_pipeline["diagnostics"] = "in_progress"
    for stage in ("comparison", "selection", "model_card"):
        session.modeling_pipeline[stage] = "pending"


def _invalidate_after_diagnostics(session) -> None:
    """Diagnostics are a comparison input, so every downstream artifact is stale."""
    session.modeling_artifacts.pop("comparison", None)
    session.modeling_artifacts.pop("selection_analysis", None)
    session.modeling_artifacts.pop("ensemble_backtests", None)
    session.modeling_artifacts.pop("ensemble_diagnostics", None)
    session.modeling_artifacts.pop("selection", None)
    session.modeling_artifacts["model_cards"] = {}
    session.modeling_pipeline["comparison"] = "in_progress"
    for stage in ("selection", "model_card"):
        session.modeling_pipeline[stage] = "pending"


def _get_session(request: Request, response: Response):
    session_id = get_or_create_session_id(request, response)
    store = get_session_store()
    return store, store.get_or_create(session_id)


@router.get("/context")
def get_modeling_context(
    request: Request,
    response: Response,
    horizon: Optional[int] = Query(None, ge=1, le=10000),
    strategy: Optional[Literal["expanding", "sliding", "single"]] = None,
    n_splits: Optional[int] = Query(None, ge=1, le=20),
    gap: Optional[int] = Query(None, ge=0, le=10000),
    train_window: Optional[int] = Query(None, ge=2, le=100000),
):
    store, session = _get_session(request, response)
    saved = session.modeling_artifacts.get("validation_strategy") or session.eda_validation_strategy
    if saved.get("column") not in {None, session.target_column}:
        saved = {}
    context = _context(
        session,
        horizon=horizon if horizon is not None else int(saved.get("horizon") or 12),
        strategy=strategy or saved.get("strategy") or "expanding",
        n_splits=n_splits if n_splits is not None else int(
            saved.get("requested_splits") or saved.get("n_splits") or 5
        ),
        gap=gap if gap is not None else int(saved.get("gap") or 0),
        train_window=(
            train_window if train_window is not None else int(saved.get("train_window") or 60)
        ),
        require_ready=False,
    )
    _prepare_state(session, context, refresh_contract=True)
    store.save(session)
    return context


@router.get("/state")
def get_modeling_state(request: Request, response: Response):
    store, session = _get_session(request, response)
    stale = False
    try:
        context = _context(session, require_ready=False)
        _prepare_state(session, context)
        store.save(session)
    except HTTPException:
        stale = bool(session.modeling_artifacts)
    return {
        "pipeline": session.modeling_pipeline,
        "artifacts": session.modeling_artifacts,
        "stale": stale,
    }


@router.post("/candidates", response_model=CandidatesResponse)
def generate_modeling_candidates(
    payload: ModelingCandidatesRequest,
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    context = _context(
        session, strategy=payload.strategy, horizon=payload.horizon,
        n_splits=payload.n_splits, gap=payload.gap,
        train_window=payload.train_window,
    )
    _prepare_state(session, context, refresh_contract=True)
    result = _compute_candidates(CandidatesRequest(
        profile=DataProfileRequest(**context["profile"]),
        min_level=payload.min_level,
    ))
    runnable = set(context["runnable_shortlist"])
    matrix_models = {
        item["model_id"]: item for item in context["model_matrix"].get("models", [])
    }
    # Ограничения EDA применяются ко всему каталогу, иначе реализованная, но
    # противопоказанная модель могла бы получить кнопку запуска в режиме all.
    for candidate in result.catalog:
        if candidate.platform_status != "ready" or candidate.model_id in runnable:
            continue
        matrix_item = matrix_models.get(candidate.model_id, {})
        reasons = matrix_item.get("blocking_reasons") or matrix_item.get("cautions") or []
        candidate.available_actions = []
        candidate.blocking_reason = (
            "; ".join(str(reason) for reason in reasons)
            or "Модель реализована, но заблокирована матрицей применимости для текущего ряда."
        )
    catalog_by_id = {candidate.model_id: candidate for candidate in result.catalog}
    result.candidates = [catalog_by_id[candidate.model_id] for candidate in result.candidates]
    result.statistics.runnable_candidates = sum(
        "backtest" in candidate.available_actions for candidate in result.candidates
    )
    result.statistics.catalog_only_candidates = sum(
        candidate.platform_status == "catalog_only" for candidate in result.catalog
    )
    result.statistics.blocked_candidates = sum(
        candidate.platform_status == "ready" and not candidate.available_actions
        for candidate in result.catalog
    )
    session.modeling_artifacts["candidates"] = result.model_dump(mode="json")
    session.modeling_artifacts["runnable_shortlist"] = context["runnable_shortlist"]
    session.modeling_pipeline["candidate_generation"] = "done"
    session.modeling_pipeline["baseline_estimation"] = "in_progress"
    session.touch()
    store.save(session)
    return result


@router.post("/backtest", response_model=BacktestResponse)
def run_modeling_backtest(
    payload: ModelingBacktestRequest,
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    context = _action_context(session)
    _prepare_state(session, context)
    if payload.model_id not in PRODUCTION_BACKTEST_MODEL_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"Production backtest для модели '{payload.model_id}' не реализован; фиктивные метрики запрещены",
        )
    runnable = set(session.modeling_artifacts.get("runnable_shortlist") or context.get("runnable_shortlist", []))
    if payload.model_id not in runnable:
        raise HTTPException(
            status_code=422,
            detail=f"Модель '{payload.model_id}' заблокирована матрицей применимости для текущего ряда",
        )
    if payload.train_ratio is not None:
        raise HTTPException(
            status_code=422,
            detail="Ручной train_ratio запрещён: backtest исполняет точные folds из EDA validation strategy",
        )
    period = (session.modeling_artifacts.get("profile", context["profile"]).get("seasonal_periods") or [1])[0]
    model_info = _resolve_model_info(payload.model_id)
    validation = session.modeling_artifacts["validation_strategy"]
    try:
        prepared = prepare_modeling_target(
            session.dataframe, target_column=session.target_column,
            date_column=session.date_column,
            transformations=session.preprocessing_transformations,
            scaling_recipe=session.preprocessing_scaling_recipe,
        )
        plan = build_backtest_plan(
            validation, n_observations=len(prepared.series),
            fingerprint=context["fingerprint"], target_column=session.target_column,
            seasonal_period=int(period),
            preprocessing_signature=prepared.preprocessing_signature,
        )
        tuned = session.modeling_artifacts.get("tuning", {}).get(payload.model_id, {})
        tuned_matches = bool(tuned) and tuned.get("cohort_id") == plan.cohort_id
        tuned_params = tuned.get("best_params", {}) if tuned_matches else {}
        preprocessing_warnings = list(prepared.warnings)
        if tuned and not tuned_params:
            preprocessing_warnings.append(
                "Сохранённые tuned-параметры относятся к другому cohort и не применены."
            )
        raw_result = run_backtest_plan(
            model_id=payload.model_id, model_name=model_info[0], family_id=model_info[1],
            series=prepared.series, labels=prepared.labels,
            plan=plan, seasonal_period=int(period), params=tuned_params,
            preprocessing_warnings=preprocessing_warnings,
            fold_preprocessor=prepared.fold_preprocessor,
        )
        result = _trace_backtest(
            raw_result, model_id=payload.model_id, params=tuned_params,
            params_source="tuning" if tuned_matches else "model_default",
            tuning_id=tuned.get("tuning_id") if tuned_matches else None,
        )
    except BacktestExecutionError as exc:
        session.modeling_artifacts.setdefault("backtest_failures", {})[payload.model_id] = {
            "model_id": payload.model_id, "cohort_id": getattr(locals().get("plan"), "cohort_id", None),
            "error": str(exc), "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        session.touch()
        store.save(session)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _invalidate_after_model_run(session, payload.model_id)
    session.modeling_artifacts.setdefault("backtests", {})[payload.model_id] = result.model_dump(mode="json")
    if model_info[1] == "baselines":
        session.modeling_pipeline["baseline_estimation"] = "done"
    session.modeling_pipeline["backtest"] = "done"
    session.modeling_pipeline["tuning"] = "done" if tuned_matches else "in_progress"
    session.touch()
    store.save(session)
    return result


@router.post("/tune", response_model=TuneResponse)
def tune_modeling_candidate(
    payload: ModelingTuneRequest,
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    context = _action_context(session)
    _prepare_state(session, context)
    from apps.api.routers.models import _get_spec
    if payload.model_id not in PRODUCTION_TUNING_MODEL_IDS:
        raise HTTPException(
            status_code=422,
            detail=f"Production tuning для модели '{payload.model_id}' не реализован",
        )
    runnable = set(session.modeling_artifacts.get("runnable_shortlist") or context.get("runnable_shortlist", []))
    if payload.model_id not in runnable:
        raise HTTPException(
            status_code=422,
            detail=f"Модель '{payload.model_id}' заблокирована матрицей применимости для текущего ряда",
        )
    validation = session.modeling_artifacts["validation_strategy"]
    if payload.cv is not None:
        raise HTTPException(
            status_code=422,
            detail="Ручная CV config запрещена: session tuning исполняет точный BacktestPlan из EDA",
        )
    model = _get_spec().get_model(payload.model_id)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Модель '{payload.model_id}' не найдена")
    if model.param_space is None:
        raise HTTPException(status_code=422, detail=f"Для модели '{payload.model_id}' param_space не задан")
    period = (session.modeling_artifacts.get("profile", context["profile"]).get("seasonal_periods") or [1])[0]
    model_info = _resolve_model_info(payload.model_id)
    try:
        prepared = prepare_modeling_target(
            session.dataframe, target_column=session.target_column,
            date_column=session.date_column,
            transformations=session.preprocessing_transformations,
            scaling_recipe=session.preprocessing_scaling_recipe,
        )
        plan = build_backtest_plan(
            validation, n_observations=len(prepared.series),
            fingerprint=context["fingerprint"], target_column=session.target_column,
            seasonal_period=int(period),
            preprocessing_signature=prepared.preprocessing_signature,
        )
        execution = execute_tuning_plan_with_artifacts(
            model_id=payload.model_id, model_name=model_info[0], family_id=model_info[1],
            param_space=model.param_space, series=prepared.series, labels=prepared.labels,
            plan=plan, seasonal_period=int(period), max_trials=payload.max_trials,
            metric=payload.metric, random_state=payload.random_state,
            fold_preprocessor=prepared.fold_preprocessor,
            preprocessing_warnings=prepared.warnings,
        )
        result = execution.response
        promoted = _trace_backtest(
            execution.best_backtest, model_id=payload.model_id,
            params=result.best_params, params_source="tuning",
            tuning_id=result.tuning_id,
        )
        result = result.model_copy(update={"promoted_backtest": promoted})
    except BacktestExecutionError as exc:
        session.modeling_artifacts.setdefault("tuning_failures", {})[payload.model_id] = {
            "model_id": payload.model_id,
            "cohort_id": getattr(locals().get("plan"), "cohort_id", None),
            "error": str(exc), "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        session.touch()
        store.save(session)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _invalidate_after_model_run(session, payload.model_id)
    session.modeling_artifacts.setdefault("backtests", {})[payload.model_id] = promoted.model_dump(mode="json")
    session.modeling_artifacts.setdefault("tuning", {})[payload.model_id] = result.model_dump(mode="json")
    session.modeling_pipeline["tuning"] = "done"
    session.modeling_pipeline["diagnostics"] = "in_progress"
    session.touch()
    store.save(session)
    return result


@router.post("/diagnostics", response_model=SessionDiagnosticsResponse)
def diagnose_modeling_candidate(
    payload: ModelingDiagnosticsRequest,
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    context = _action_context(session)
    _prepare_state(session, context)
    backtest = session.modeling_artifacts.get("backtests", {}).get(payload.model_id)
    if not backtest:
        raise HTTPException(status_code=409, detail="Сначала выполните backtest модели на EDA folds")
    points = backtest.get("oof_predictions") or []
    if not points:
        raise HTTPException(status_code=409, detail="Backtest не содержит OOF-остатков для диагностики")
    current_oof_signature = oof_signature(points)
    current_parameter_signature = parameter_signature(
        payload.model_id, backtest.get("params") or {},
    )
    if (
        not backtest.get("run_id")
        or not backtest.get("cohort_id")
        or backtest.get("oof_signature") != current_oof_signature
        or backtest.get("parameter_signature") != current_parameter_signature
    ):
        raise HTTPException(
            status_code=409,
            detail="Backtest не содержит валидную OOF lineage; повторите backtest или tuning",
        )
    tuning = session.modeling_artifacts.get("tuning", {}).get(payload.model_id)
    if backtest.get("params_source") == "tuning":
        if (
            not tuning
            or tuning.get("cohort_id") != backtest.get("cohort_id")
            or tuning.get("tuning_id") != backtest.get("tuning_id")
            or tuning.get("parameter_signature") != backtest.get("parameter_signature")
            or tuning.get("parameter_signature") != parameter_signature(
                payload.model_id, tuning.get("best_params") or {},
            )
        ):
            raise HTTPException(
                status_code=409,
                detail="Promoted backtest не соответствует текущему tuning run; повторите tuning",
            )
    elif tuning and tuning.get("cohort_id") == backtest.get("cohort_id"):
        raise HTTPException(
            status_code=409,
            detail="Backtest устарел относительно текущего tuning run; повторите tuning",
        )
    residuals = np.asarray([point["residual"] for point in points], dtype=float)
    try:
        diagnostics = _diagnose(residuals, payload.alpha, payload.ljung_box_lags, payload.arch_lags)
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result_payload = {
        "model_id": payload.model_id, "target_column": session.target_column,
        "n_observations": int(residuals.size), "residuals_count": int(residuals.size),
        "alpha": payload.alpha,
        "params_source": backtest.get("params_source", "model_default"),
        "params": backtest.get("params", {}),
        "parameter_signature": backtest.get("parameter_signature"),
        "tuning_id": backtest.get("tuning_id"),
        "backtest_run_id": backtest.get("run_id"),
        "residuals_signature": current_oof_signature,
        "residuals_source": (
            "tuned_backtest_oof" if backtest.get("params_source") == "tuning"
            else "backtest_oof"
        ),
        "cohort_id": backtest.get("cohort_id"),
        "preprocessing": backtest.get("preprocessing", {}),
        "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
    }
    result_payload["diagnostics_signature"] = diagnostics_signature(result_payload)
    result = SessionDiagnosticsResponse(**result_payload)
    _invalidate_after_diagnostics(session)
    session.modeling_artifacts.setdefault("diagnostics", {})[payload.model_id] = result.model_dump(mode="json")
    session.modeling_pipeline["diagnostics"] = "done"
    session.modeling_pipeline["comparison"] = "in_progress"
    session.touch()
    store.save(session)
    return result


@router.post("/compare", response_model=ModelingComparisonResponse)
def compare_modeling_candidates(
    payload: ModelingCompareRequest,
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    context = _action_context(session)
    _prepare_state(session, context)
    saved = session.modeling_artifacts.get("backtests", {})
    if len(payload.model_ids) != len(set(payload.model_ids)):
        raise HTTPException(status_code=422, detail="model_ids содержит дубликаты")
    model_ids = payload.model_ids or list(saved)
    missing_backtests = [model_id for model_id in model_ids if model_id not in saved]
    if missing_backtests:
        raise HTTPException(
            status_code=409,
            detail={"message": "Не все запрошенные backtests существуют", "missing_backtests": missing_backtests},
        )
    results = [saved[model_id] for model_id in model_ids]
    if len(results) < 2:
        raise HTTPException(status_code=409, detail="Для сравнения нужны минимум два сопоставимых бэктеста")
    if not any(item.get("family_id") == "baselines" for item in results):
        raise HTTPException(
            status_code=409,
            detail="Comparable pool должен содержать минимум один рассчитанный baseline",
        )
    incomplete = [item["model_id"] for item in results if item.get("status") != "success"]
    if incomplete:
        raise HTTPException(status_code=409, detail=f"Неполные backtest нельзя сравнивать: {incomplete}")
    cohorts = {item.get("cohort_id") for item in results}
    if None in cohorts or len(cohorts) != 1:
        raise HTTPException(status_code=409, detail="Бэктесты рассчитаны на разных разбиениях и несопоставимы")
    untraceable = [
        item["model_id"] for item in results
        if not item.get("run_id") or not item.get("parameter_signature")
        or item.get("parameter_signature") != parameter_signature(
            item["model_id"], item.get("params") or {},
        )
        or item.get("oof_signature") != oof_signature(item.get("oof_predictions") or [])
    ]
    if untraceable:
        raise HTTPException(
            status_code=409,
            detail=f"Бэктесты не имеют валидной execution/OOF lineage: {untraceable}",
        )
    tunings = session.modeling_artifacts.get("tuning", {})
    stale_tuned = []
    for item in results:
        tuning = tunings.get(item["model_id"])
        if tuning and tuning.get("cohort_id") == item.get("cohort_id") and (
            item.get("params_source") != "tuning"
            or item.get("tuning_id") != tuning.get("tuning_id")
            or item.get("parameter_signature") != tuning.get("parameter_signature")
            or tuning.get("parameter_signature") != parameter_signature(
                item["model_id"], tuning.get("best_params") or {},
            )
        ):
            stale_tuned.append(item["model_id"])
    if stale_tuned:
        raise HTTPException(
            status_code=409,
            detail=f"Бэктесты устарели относительно текущего tuning run: {stale_tuned}",
        )
    saved_diagnostics = session.modeling_artifacts.get("diagnostics", {})
    missing_diagnostics = [model_id for model_id in model_ids if model_id not in saved_diagnostics]
    if missing_diagnostics:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Для comparison нужны diagnostics каждого backtest",
                "missing_diagnostics": missing_diagnostics,
            },
        )
    stale_diagnostics = []
    for backtest in results:
        model_id = backtest["model_id"]
        report = saved_diagnostics[model_id]
        expected_signature = diagnostics_signature(report)
        if (
            report.get("backtest_run_id") != backtest.get("run_id")
            or report.get("residuals_signature") != backtest.get("oof_signature")
            or report.get("parameter_signature") != backtest.get("parameter_signature")
            or report.get("cohort_id") != backtest.get("cohort_id")
            or report.get("diagnostics_signature") != expected_signature
        ):
            stale_diagnostics.append(model_id)
    if stale_diagnostics:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Diagnostics не соответствуют текущим backtest runs",
                "stale_diagnostics": stale_diagnostics,
            },
        )
    candidate_catalog = _compute_candidates(CandidatesRequest(
        profile=DataProfileRequest(**context["profile"]),
        min_level="NOT_APPLICABLE",
    )).catalog
    applicability_levels = {
        candidate.model_id: candidate.level for candidate in candidate_catalog
    }
    missing_applicability = [
        model_id for model_id in model_ids if model_id not in applicability_levels
    ]
    if missing_applicability:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Для comparison отсутствует оценка применимости",
                "missing_applicability": missing_applicability,
            },
        )
    try:
        result = build_comparison(
            fingerprint=context["fingerprint"], cohort_id=next(iter(cohorts)),
            backtests=results, diagnostics=saved_diagnostics,
            applicability_levels=applicability_levels,
            comparison_id=str(uuid4()),
        )
    except ComparisonContractError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.modeling_artifacts["comparison"] = result.model_dump(mode="json")
    session.modeling_artifacts.pop("selection_analysis", None)
    session.modeling_artifacts.pop("ensemble_backtests", None)
    session.modeling_artifacts.pop("ensemble_diagnostics", None)
    session.modeling_artifacts.pop("selection", None)
    session.modeling_artifacts["model_cards"] = {}
    session.modeling_pipeline["comparison"] = "done"
    session.modeling_pipeline["selection"] = "in_progress"
    session.modeling_pipeline["model_card"] = "pending"
    session.touch()
    store.save(session)
    return result


@router.post("/selection/evaluate")
def evaluate_modeling_selection(
    payload: ModelingSelectionEvaluationRequest,
    request: Request,
    response: Response,
):
    """Build a traceable recommendation and actually test ensemble OOF."""
    store, session = _get_session(request, response)
    _action_context(session)
    comparison = session.modeling_artifacts.get("comparison")
    if not comparison:
        raise HTTPException(status_code=409, detail="Сначала выполните сравнение моделей")
    policy = SelectionPolicy(**payload.model_dump())
    try:
        result = evaluate_selection(
            comparison=comparison,
            backtests=session.modeling_artifacts.get("backtests", {}),
            diagnostics=session.modeling_artifacts.get("diagnostics", {}),
            policy=policy,
        )
    except (SelectionContractError, ValueError, TypeError, ArithmeticError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.modeling_artifacts["selection_analysis"] = result
    session.modeling_artifacts["ensemble_backtests"] = {}
    session.modeling_artifacts["ensemble_diagnostics"] = {}
    ensemble = result.get("ensemble") or {}
    if ensemble.get("backtest"):
        ensemble_id = ensemble["backtest"]["model_id"]
        session.modeling_artifacts["ensemble_backtests"][ensemble_id] = ensemble["backtest"]
        session.modeling_artifacts["ensemble_diagnostics"][ensemble_id] = ensemble["diagnostics"]
    session.modeling_artifacts.pop("selection", None)
    session.modeling_artifacts["model_cards"] = {}
    session.modeling_pipeline["selection"] = "in_progress"
    session.modeling_pipeline["model_card"] = "pending"
    session.touch()
    store.save(session)
    return result


@router.post("/select")
def select_modeling_candidate(
    payload: ModelingSelectRequest,
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    _action_context(session)
    comparison = session.modeling_artifacts.get("comparison")
    analysis = session.modeling_artifacts.get("selection_analysis")
    if not comparison or not analysis:
        raise HTTPException(
            status_code=409,
            detail="Сначала выполните comparison и верифицируйте selection/ensemble trigger",
        )
    if (
        analysis.get("comparison_signature") != comparison.get("comparison_signature")
        or payload.selection_analysis_id != analysis.get("selection_analysis_id")
        or payload.selection_signature != analysis.get("selection_signature")
    ):
        raise HTTPException(status_code=409, detail="Selection analysis устарел или не подтверждён подписью")
    if not payload.acknowledge_selection_bias:
        raise HTTPException(
            status_code=409,
            detail="Подтвердите отсутствие независимого final holdout: оценка использует selection OOF",
        )
    candidate = next(
        (item for item in comparison["ranking"] if item["model_id"] == payload.model_id), None,
    )
    ensemble = analysis.get("ensemble") or {}
    ensemble_backtest = ensemble.get("backtest")
    is_ensemble = bool(ensemble_backtest and ensemble_backtest.get("model_id") == payload.model_id)
    if candidate is None and not is_ensemble:
        raise HTTPException(status_code=404, detail="Кандидат отсутствует в текущем selection analysis")
    if is_ensemble and ensemble.get("status") != "recommended" and not payload.acknowledge_ensemble_no_gain:
        raise HTTPException(
            status_code=409,
            detail="Ансамбль не доказал улучшение; требуется явный override",
        )
    primary_metric = analysis["policy"]["primary_metric"]
    baseline_loss = float(analysis["best_baseline"]["primary_loss"])
    selected_loss = float(
        ensemble_backtest["metrics"][primary_metric]
        if is_ensemble else candidate["metrics"][primary_metric]
    )
    baseline_risk = selected_loss > baseline_loss + np.finfo(float).eps
    if baseline_risk and not payload.acknowledge_baseline_risk:
        raise HTTPException(status_code=409, detail="Подтвердите выбор, уступающий лучшему фактическому OOF baseline")
    diagnostics = (
        ensemble.get("diagnostics") if is_ensemble else candidate["diagnostics"]
    )
    backtest_run_id = (
        ensemble_backtest["run_id"] if is_ensemble else candidate["backtest_run_id"]
    )
    result = {
        "selected_model_id": payload.model_id,
        "selected_kind": "ensemble" if is_ensemble else "single",
        "selection_analysis_id": analysis["selection_analysis_id"],
        "selection_signature": analysis["selection_signature"],
        "comparison_id": comparison["comparison_id"],
        "comparison_signature": comparison["comparison_signature"],
        "backtest_run_id": backtest_run_id,
        "diagnostics_signature": diagnostics["diagnostics_signature"],
        "selected_at": datetime.now(timezone.utc).isoformat(),
        "user_override": payload.model_id != analysis["recommended_candidate"]["model_id"],
        "baseline_risk_acknowledged": payload.acknowledge_baseline_risk,
        "selection_bias_acknowledged": payload.acknowledge_selection_bias,
        "independent_holdout": False,
        "primary_metric": primary_metric,
        "primary_loss": selected_loss,
        "best_baseline_loss": baseline_loss,
        "ensemble_status": ensemble.get("status"),
        "ensemble_recommended": ensemble.get("status") == "recommended",
        "ensemble_members": ensemble.get("member_ids") if is_ensemble else [],
    }
    session.modeling_artifacts["selection"] = result
    session.modeling_pipeline["selection"] = "done"
    session.modeling_pipeline["model_card"] = "in_progress"
    session.touch()
    store.save(session)
    return result


@router.post("/card")
def create_model_card(
    payload: ModelingCardRequest,
    request: Request,
    response: Response,
):
    store, session = _get_session(request, response)
    context = _action_context(session)
    _prepare_state(session, context)
    selection = session.modeling_artifacts.get("selection")
    comparison = session.modeling_artifacts.get("comparison")
    if not selection or not comparison:
        raise HTTPException(status_code=409, detail="Сначала сравните и выберите модель")
    model_id = selection["selected_model_id"]
    is_ensemble = selection.get("selected_kind") == "ensemble"
    selection_analysis = session.modeling_artifacts.get("selection_analysis") or {}
    if (
        selection.get("comparison_signature") != comparison.get("comparison_signature")
        or selection.get("selection_analysis_id") != selection_analysis.get("selection_analysis_id")
        or selection.get("selection_signature") != selection_analysis.get("selection_signature")
    ):
        raise HTTPException(status_code=409, detail="Selection lineage устарела; повторите верификацию")
    if is_ensemble:
        backtest = session.modeling_artifacts.get("ensemble_backtests", {}).get(model_id)
        diagnostics = session.modeling_artifacts.get("ensemble_diagnostics", {}).get(model_id)
        if not backtest or not diagnostics:
            raise HTTPException(status_code=409, detail="Ensemble selection artifact устарел")
        ensemble = selection_analysis.get("ensemble") or {}
        ranked = {
            "family_id": "ensemble",
            "applicability_level": "CONDITIONALLY_APPLICABLE",
            "model_name": backtest["model_name"],
            "metrics": backtest["metrics"],
            "normalized_metrics": {},
            "weighted_score": None,
            "fold_stability": {
                "metric": selection_analysis.get("policy", {}).get("primary_metric", "rmse"),
                "fold_values": [
                    fold["metrics"][selection_analysis.get("policy", {}).get("primary_metric", "rmse")]
                    for fold in backtest.get("folds") or []
                ],
                "top1_rate": ensemble.get("fold_win_rate"),
            },
            "baseline_eligible": (ensemble.get("relative_improvement_vs_best_baseline") or 0) >= 0,
            "baseline_note": "сравнение с лучшим фактическим OOF baseline",
        }
        tuning = None
        candidate = None
    else:
        ranked = next(item for item in comparison["ranking"] if item["model_id"] == model_id)
        backtest = session.modeling_artifacts["backtests"][model_id]
        tuning = session.modeling_artifacts.get("tuning", {}).get(model_id)
        diagnostics = session.modeling_artifacts.get("diagnostics", {}).get(model_id)
        candidate = next((item for item in session.modeling_artifacts.get("candidates", {}).get("candidates", []) if item["model_id"] == model_id), None)
    series = prepare_passport_series(session.dataframe, session.target_column, session.date_column)
    folds = backtest.get("folds") or []
    first_fold = folds[0] if folds else None
    last_fold = folds[-1] if folds else None
    diagnostics_items = (diagnostics or {}).get("diagnostics", [])
    passed = [item["test"] for item in diagnostics_items if item["applicable"] and item["status"] == "pass"]
    failed = [item for item in diagnostics_items if item["applicable"] and item["status"] in {"warning", "fail"}]
    limitations = ["Оценка основана на историческом временном разбиении; будущий режим может отличаться."]
    if not selection.get("independent_holdout"):
        limitations.append(
            "Независимый final holdout не использован: tuning и selection опираются на один OOF cohort."
        )
    if not diagnostics:
        limitations.append("Диагностика остатков для выбранной модели не зафиксирована.")
    limitations.append("Prediction intervals и их coverage ещё не реализованы в production backtest.")
    card_id = str(uuid4())
    card = {
        "model_info": {
            "model_id": model_id, "family": ranked["family_id"],
            "applicability_level": ranked["applicability_level"],
            "description": (candidate or {}).get("message", ranked["model_name"]),
            "selection_kind": selection.get("selected_kind", "single"),
            "ensemble_members": selection.get("ensemble_members", []),
            "version": "1.0", "library_versions": {
                "numpy": _package_version("numpy"),
                "pandas": _package_version("pandas"),
                "statsmodels": _package_version("statsmodels"),
            },
        },
        "data_summary": {
            "n_observations": len(series), "n_series": context["profile"]["n_series"],
            "frequency": context["profile"]["frequency"], "domain": context["profile"]["domain"],
            "target_column": session.target_column, "date_column": session.date_column,
            "source_checkpoint": context["checkpoint"]["checkpoint_id"],
            "fingerprint": context["fingerprint"],
        },
        "hyperparameters": backtest.get("params", {}),
        "training": {
            "train_start": (
                first_fold.get("train_start_label") if first_fold else str(series.index[0])
            ),
            "train_end": (
                last_fold.get("train_end_label") if last_fold
                else str(series.index[backtest["n_train"] - 1])
            ),
            "validation_method": backtest.get("strategy", context["validation_strategy"]["strategy"]),
            "n_folds": backtest.get("n_folds", context["validation_strategy"]["n_splits"]),
            "horizon": backtest.get("horizon"),
            "gap": backtest.get("gap", 0),
            "cohort_id": backtest.get("cohort_id"),
            "backtest_run_id": backtest.get("run_id"),
            "params_source": backtest.get("params_source"),
            "parameter_signature": backtest.get("parameter_signature"),
            "tuning_id": backtest.get("tuning_id"),
            "oof_signature": backtest.get("oof_signature"),
            "folds": folds,
            "preprocessing": backtest.get("preprocessing", {}),
            "training_time_seconds": round(backtest["duration_ms"] / 1000, 6),
            "gpu_used": False,
        },
        "performance": {
            "backtest_metrics": backtest["metrics"],
            "normalized_comparison_metrics": ranked.get("normalized_metrics", {}),
            "weighted_score": ranked.get("weighted_score"),
            "fold_stability": ranked.get("fold_stability"),
            "residuals_source": (diagnostics or {}).get("residuals_source", "backtest_oof"),
            "residuals_signature": (diagnostics or {}).get("residuals_signature"),
            "oof_predictions": backtest.get("oof_predictions", []),
            "cv_metrics": (tuning or {}).get("best_metrics") or {},
            "baseline_comparison": {
                "mase": ranked["metrics"].get("mase"),
                "primary_metric": selection.get("primary_metric"),
                "selected_loss": selection.get("primary_loss"),
                "best_baseline_loss": selection.get("best_baseline_loss"),
                "eligible": ranked["baseline_eligible"],
                "note": ranked["baseline_note"],
            },
            "prediction_interval_coverage": None, "winkler_score": None,
        },
        "diagnostics": {"passed": passed, "failed": failed, "report": diagnostics},
        "limitations": limitations,
        "recommendations": ["Переобучать preprocessing и модель внутри каждого train fold.", "Мониторить ошибку и дрейф после ввода прогноза в эксплуатацию."],
        "feature_importance": None,
        "traceability": {
            "total_sources": context["traceability"]["summary"]["total"],
            "summary": context["traceability"]["summary"],
            "checkpoint_id": context["checkpoint"]["checkpoint_id"],
            "comparison_id": comparison.get("comparison_id"),
            "comparison_signature": comparison.get("comparison_signature"),
            "diagnostics_signature": (diagnostics or {}).get("diagnostics_signature"),
            "selection_analysis_id": selection.get("selection_analysis_id"),
            "selection_signature": selection.get("selection_signature"),
            "independent_holdout": selection.get("independent_holdout", False),
        },
        "notes": payload.notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = {"card_id": card_id, "card": card}
    session.modeling_artifacts.setdefault("model_cards", {})[card_id] = result
    session.modeling_pipeline["model_card"] = "done"
    session.set_stage("modeling", "done")
    session.touch()
    store.save(session)
    return result


@router.get("/card/{card_id}")
def get_model_card(card_id: str, request: Request, response: Response):
    _store, session = _get_session(request, response)
    card = session.modeling_artifacts.get("model_cards", {}).get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Model Card не найден")
    return card
