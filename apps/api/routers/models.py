# apps/api/routers/models.py
"""
Роутер модуля «Моделирование».

Эндпоинты:
  POST /v1/models/candidates  — пул кандидатов (движок применимости)
  POST /v1/models/backtest    — бэктест одной модели
  POST /v1/models/train       — обучение модели (заглушка)
  POST /v1/models/tune        — grid search гиперпараметров с CV
"""
import itertools
import logging
import random
import time
import math
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException

from apps.api.auth import require_capability, get_current_principal
from apps.api.cv import ExpandingWindowCV
from apps.api.plans import AuthenticatedPrincipal
from apps.api.schemas import (
    CandidatesRequest,
    CandidatesResponse,
    ModelCandidate,
    CandidatesStatistics,
    BacktestRequest,
    BacktestResponse,
    BacktestMetrics,
    CVConfig,
    TuneRequest,
    TuneResponse,
    TuneTrialResult,
)
from apps.api.model_impls import (
    run_ets_backtest,
    run_ets_damped_backtest,
    run_theta_backtest,
    run_arima_backtest,
    run_auto_arima_backtest,
    run_prophet_backtest,
)
from apps.api.model_impls.tuning import tune_ets_predict, tune_arima_predict
from apps.api.model_execution import (
    MODEL_EXECUTION_CONTRACT_VERSION,
    MODEL_EXECUTION_REGISTRY,
)
from apps.api.model_readiness import (
    MODELING_CAPABILITY_CONTRACT_VERSION,
    PRODUCTION_BACKTEST_MODEL_IDS,
    available_model_actions,
    model_stage_capabilities,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_spec_cache = None
_SPEC_YAML_PATH = "rules/modeling.yaml"


def _get_spec():
    global _spec_cache
    if _spec_cache is not None:
        return _spec_cache
    try:
        from src.catalog.modeling_spec_loader import ModelingSpec
        _spec_cache = ModelingSpec.from_yaml(_SPEC_YAML_PATH)
        logger.info("Modeling spec loaded: %s", repr(_spec_cache))
        return _spec_cache
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail=f"Спецификация моделирования не найдена: {_SPEC_YAML_PATH}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка загрузки спецификации моделирования: {e}")


def _reset_spec_cache():
    global _spec_cache
    _spec_cache = None


@router.post(
    "/candidates",
    response_model=CandidatesResponse,
    dependencies=[Depends(require_capability("can_train_models"))],
)
def get_candidates(
    payload: CandidatesRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    return _compute_candidates(payload)


def _compute_candidates(payload: CandidatesRequest) -> CandidatesResponse:
    """Чистая бизнес-логика кандидатов, переиспользуемая internal-зеркалом."""
    spec = _get_spec()
    from src.catalog.modeling_spec_loader import DataProfile

    profile = DataProfile(
        n_observations=payload.profile.n_observations,
        n_series=payload.profile.n_series,
        n_exogenous=payload.profile.n_exogenous,
        is_regular=payload.profile.is_regular,
        frequency=payload.profile.frequency,
        has_seasonality=payload.profile.has_seasonality,
        seasonal_periods=payload.profile.seasonal_periods,
        is_stationary_or_diffable=payload.profile.is_stationary_or_diffable,
        is_cointegrated=payload.profile.is_cointegrated,
        has_negative_values=payload.profile.has_negative_values,
        has_volatility_clustering=payload.profile.has_volatility_clustering,
        domain=payload.profile.domain,
        missing_ratio=payload.profile.missing_ratio,
        outlier_ratio=payload.profile.outlier_ratio,
        has_holidays=payload.profile.has_holidays,
        gpu_available=payload.profile.gpu_available,
        feature_engineering_applied=payload.profile.feature_engineering_applied,
    )
    valid_levels = {"RECOMMENDED", "CONDITIONALLY_APPLICABLE", "NOT_RECOMMENDED", "NOT_APPLICABLE"}
    min_level = payload.min_level or "CONDITIONALLY_APPLICABLE"
    if min_level not in valid_levels:
        raise HTTPException(status_code=422, detail=f"Некорректный min_level: '{min_level}'. Допустимые: {valid_levels}")
    candidate_results = spec.get_candidate_pool(profile, min_level=min_level)
    candidate_ids = {candidate.model_id for candidate in candidate_results}
    all_results = spec.resolve_all_applicability(profile)

    def build_catalog_item(candidate) -> ModelCandidate:
        production_actions = available_model_actions(candidate.model_id)
        platform_ready = "backtest" in production_actions
        included = candidate.model_id in candidate_ids
        actions = production_actions if included else []
        if not platform_ready:
            blocking_reason = (
                "Production-реализация модели ещё не подключена; "
                "фиктивные метрики запрещены."
            )
        elif not included:
            blocking_reason = candidate.message or (
                f"Модель исключена из пула уровнем применимости {candidate.level}."
            )
        else:
            blocking_reason = None
        return ModelCandidate(
            model_id=candidate.model_id, model_name=candidate.model_name,
            family_id=candidate.family_id, level=candidate.level,
            rule_id=candidate.rule_id, message=candidate.message,
            rank=candidate.rank,
            platform_status="ready" if platform_ready else "catalog_only",
            available_actions=actions,
            blocking_reason=blocking_reason,
            stage_capabilities=model_stage_capabilities(
                candidate.model_id, candidate.family_id,
                included=included,
                blocking_reason=blocking_reason if platform_ready and not included else None,
            ),
            execution_contract=(
                MODEL_EXECUTION_REGISTRY.describe(candidate.model_id)
                if platform_ready else None
            ),
        )

    # Полный каталог сохраняет порядок modeling.yaml и содержит все уровни
    # применимости. Профильный candidates остаётся отдельным shortlist.
    catalog = [build_catalog_item(candidate) for candidate in all_results.values()]
    catalog_by_id = {candidate.model_id: candidate for candidate in catalog}
    candidates = [catalog_by_id[candidate.model_id] for candidate in candidate_results]
    level_counts = Counter(c.level for c in candidates)
    statistics = CandidatesStatistics(
        total_candidates=len(candidates), by_level=dict(level_counts),
        total_models_in_spec=spec.total_model_count(),
        runnable_candidates=sum("backtest" in item.available_actions for item in candidates),
        catalog_only_candidates=sum(item.platform_status == "catalog_only" for item in catalog),
        blocked_candidates=sum(
            item.platform_status == "ready" and not item.available_actions
            for item in catalog
        ),
    )
    return CandidatesResponse(
        candidates=candidates, catalog=catalog,
        statistics=statistics, spec_version=spec.metadata.version,
        capability_contract_version=MODELING_CAPABILITY_CONTRACT_VERSION,
        execution_contract_version=MODEL_EXECUTION_CONTRACT_VERSION,
    )


_METRIC_WEIGHTS = {"mae": 0.35, "rmse": 0.25, "mape": 0.20, "mase": 0.20}


def _generate_series(n: int, frequency: str, has_seasonality: bool) -> list[float]:
    import random as _random
    _random.seed(42)
    seasonal_period = {"D": 7, "W": 52, "M": 12, "Q": 4, "Y": 1}.get(frequency, 12)
    series = []
    for t in range(n):
        trend = 100.0 + 0.5 * t
        season = 10.0 * math.sin(2 * math.pi * t / seasonal_period) if has_seasonality else 0.0
        noise = _random.gauss(0, 2.0)
        series.append(trend + season + noise)
    return series


def _compute_metrics(y_true: list[float], y_pred: list[float], y_train: list[float]) -> BacktestMetrics:
    n = len(y_true)
    if n == 0:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)
    mae = sum(abs(a - p) for a, p in zip(y_true, y_pred)) / n
    rmse = math.sqrt(sum((a - p) ** 2 for a, p in zip(y_true, y_pred)) / n)
    mape_sum = 0.0
    mape_count = 0
    for a, p in zip(y_true, y_pred):
        if abs(a) > 1e-10:
            mape_sum += abs((a - p) / a)
            mape_count += 1
    mape = (mape_sum / mape_count * 100) if mape_count > 0 else 0.0
    if len(y_train) > 1:
        naive_errors = [abs(y_train[i] - y_train[i - 1]) for i in range(1, len(y_train))]
        mae_naive = sum(naive_errors) / len(naive_errors) if naive_errors else 1.0
    else:
        mae_naive = 1.0
    mase = mae / mae_naive if mae_naive > 1e-10 else 0.0
    mae_n = min(mae / 50.0, 1.0)
    rmse_n = min(rmse / 50.0, 1.0)
    mape_n = min(mape / 100.0, 1.0)
    mase_n = min(mase / 2.0, 1.0)
    weighted_score = (
        _METRIC_WEIGHTS["mae"] * mae_n
        + _METRIC_WEIGHTS["rmse"] * rmse_n
        + _METRIC_WEIGHTS["mape"] * mape_n
        + _METRIC_WEIGHTS["mase"] * mase_n
    )
    return BacktestMetrics(
        mae=round(mae, 4), rmse=round(rmse, 4), mape=round(mape, 2),
        mase=round(mase, 4), weighted_score=round(weighted_score, 4),
    )


def _run_naive_backtest(series: list[float], train_ratio: float) -> BacktestMetrics:
    n_train = int(len(series) * train_ratio)
    y_train, y_test = series[:n_train], series[n_train:]
    y_pred = [y_train[-1]] + y_test[:-1]
    return _compute_metrics(y_test, y_pred, y_train)


def _run_seasonal_naive_backtest(series: list[float], train_ratio: float, seasonal_period: int = 12) -> BacktestMetrics:
    n_train = int(len(series) * train_ratio)
    y_train, y_test = series[:n_train], series[n_train:]
    y_pred = []
    for i in range(len(y_test)):
        idx = n_train + i - seasonal_period
        y_pred.append(series[idx] if idx >= 0 else y_train[-1])
    return _compute_metrics(y_test, y_pred, y_train)


def _run_drift_backtest(series: list[float], train_ratio: float) -> BacktestMetrics:
    n_train = int(len(series) * train_ratio)
    y_train, y_test = series[:n_train], series[n_train:]
    drift = (y_train[-1] - y_train[0]) / max(len(y_train) - 1, 1)
    y_pred = [y_train[-1] + drift * (i + 1) for i in range(len(y_test))]
    return _compute_metrics(y_test, y_pred, y_train)


def _run_mean_backtest(series: list[float], train_ratio: float) -> BacktestMetrics:
    n_train = int(len(series) * train_ratio)
    y_train, y_test = series[:n_train], series[n_train:]
    train_mean = sum(y_train) / len(y_train) if y_train else 0.0
    return _compute_metrics(y_test, [train_mean] * len(y_test), y_train)


_BACKTEST_IMPLEMENTATIONS = {
    "naive": lambda s, tr, p: _run_naive_backtest(s, tr),
    "seasonal_naive": lambda s, tr, p: _run_seasonal_naive_backtest(s, tr, p),
    "drift": lambda s, tr, p: _run_drift_backtest(s, tr),
    "mean": lambda s, tr, p: _run_mean_backtest(s, tr),
    "ets": run_ets_backtest,
    "ets_damped": run_ets_damped_backtest,
    "theta": run_theta_backtest,
    "arima": run_arima_backtest,
    "arima_auto": run_auto_arima_backtest,
    "prophet": run_prophet_backtest,
}

if frozenset(_BACKTEST_IMPLEMENTATIONS) != PRODUCTION_BACKTEST_MODEL_IDS:
    raise RuntimeError("Реестр готовности моделей расходится с production backtest dispatch")


MAX_TRIALS: int = 64


def _build_grid(param_space: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    keys = list(param_space.keys())
    values = [param_space[k] for k in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def _truncate_grid(grid: List[Dict[str, Any]], max_trials: int, random_state: int) -> Tuple[List[Dict[str, Any]], bool]:
    if len(grid) <= max_trials:
        return grid, False
    rng = random.Random(random_state)
    sampled_indices = sorted(rng.sample(range(len(grid)), max_trials))
    return [grid[i] for i in sampled_indices], True


def _tunable_predict(model_id: str, y_train: List[float], test_size: int, params: Dict[str, Any]) -> List[float]:
    """Production tuning dispatch.

    ETS and ARIMA trials use the same real statsmodels implementations as
    Phase 6-P0 backtest. Unsupported tunable models fail explicitly rather
    than silently producing synthetic/stub forecasts.
    """
    if model_id in {"ets", "ets_damped"}:
        if model_id == "ets_damped" and "damped_trend" not in params:
            params = {**params, "damped_trend": True}
        return tune_ets_predict(y_train, test_size, params)
    if model_id == "arima":
        return tune_arima_predict(y_train, test_size, params)
    raise HTTPException(
        status_code=422,
        detail=f"Реальный tuning для модели '{model_id}' пока не реализован",
    )


_VALID_METRICS = {"mae", "rmse", "mape", "mase", "weighted_score"}


def _execute_tune(
    spec,
    model_id: str,
    series: List[float],
    cv_config: CVConfig,
    max_trials: Optional[int],
    metric: str,
    random_state: int,
) -> TuneResponse:
    start = time.monotonic()
    model = spec.get_model(model_id)
    if model is None:
        raise HTTPException(status_code=404, detail=f"Модель '{model_id}' не найдена в спецификации")
    if model.param_space is None:
        raise HTTPException(
            status_code=422,
            detail=(f"Модель '{model_id}' не поддерживает тюнинг: param_space не задан в спецификации. "
                    f"Baseline-модели (naive/drift/mean) не имеют гиперпараметров."),
        )
    full_grid = _build_grid(model.param_space)
    grid_size = len(full_grid)
    requested = max_trials if max_trials is not None else MAX_TRIALS
    effective_max = min(requested, MAX_TRIALS)
    trials_grid, truncated = _truncate_grid(full_grid, effective_max, random_state)
    try:
        cv = ExpandingWindowCV(
            n_splits=cv_config.n_splits,
            test_size=cv_config.test_size,
            min_train_size=cv_config.min_train_size,
            step=cv_config.step,
            gap=cv_config.gap,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Некорректная CV config: {e}")
    if len(series) < cv.min_samples():
        raise HTTPException(
            status_code=422,
            detail=(f"Слишком короткий ряд для CV: нужно >= {cv.min_samples()}, есть {len(series)}. "
                    f"Уменьшите n_splits, test_size или min_train_size."),
        )
    if metric not in _VALID_METRICS:
        raise HTTPException(status_code=422, detail=f"Некорректная метрика '{metric}'. Допустимые: {sorted(_VALID_METRICS)}.")

    splits = cv.split(len(series))
    n_folds = len(splits)
    trial_results: List[TuneTrialResult] = []
    failed_trials = 0

    for params in trials_grid:
        fold_metrics: List[BacktestMetrics] = []
        for split in splits:
            y_train = [series[i] for i in split.train_idx]
            y_test = [series[i] for i in split.test_idx]
            try:
                y_pred = _tunable_predict(model_id, y_train, len(y_test), params)
                fold_metrics.append(_compute_metrics(y_test, y_pred, y_train))
            except (ValueError, RuntimeError, ArithmeticError, IndexError) as exc:
                logger.warning("Tuning trial failed: model=%s params=%s error=%s", model_id, params, exc)
                failed_trials += 1
                break
        if len(fold_metrics) != n_folds:
            continue
        avg_metrics = BacktestMetrics(
            mae=round(sum(m.mae for m in fold_metrics) / n_folds, 6),
            rmse=round(sum(m.rmse for m in fold_metrics) / n_folds, 6),
            mape=round(sum(m.mape for m in fold_metrics) / n_folds, 6),
            mase=round(sum(m.mase for m in fold_metrics) / n_folds, 6),
            weighted_score=round(sum(m.weighted_score for m in fold_metrics) / n_folds, 6),
        )
        trial_results.append(TuneTrialResult(params=params, metrics=avg_metrics, n_folds=n_folds))

    if not trial_results:
        raise HTTPException(
            status_code=422,
            detail=(f"Ни один trial модели '{model_id}' не завершился успешно. "
                    f"Проверьте длину ряда и совместимость параметров."),
        )

    best_idx = min(range(len(trial_results)), key=lambda i: getattr(trial_results[i].metrics, metric))
    best = trial_results[best_idx]
    family = spec.get_family_for_model(model_id)
    family_id = family.id if family else "unknown"
    duration_ms = (time.monotonic() - start) * 1000
    if failed_trials:
        logger.warning("Tuning completed with %d failed trial-fold executions: model=%s", failed_trials, model_id)
    return TuneResponse(
        model_id=model_id,
        model_name=model.name,
        family_id=family_id,
        best_params=best.params,
        best_metrics=best.metrics,
        best_trial=best_idx,
        n_trials=len(trial_results),
        grid_size=grid_size,
        truncated=truncated,
        cv_config=cv_config,
        metric=metric,
        trials=trial_results,
        duration_ms=round(duration_ms, 2),
        execution_contract=MODEL_EXECUTION_REGISTRY.describe(model_id),
    )


_MODEL_INFO = {
    "naive": ("Naive", "baselines"), "seasonal_naive": ("Seasonal Naive", "baselines"),
    "drift": ("Drift", "baselines"), "mean": ("Mean", "baselines"),
    "ets": ("ETS (Auto)", "exponential_smoothing"), "ets_damped": ("ETS Damped", "exponential_smoothing"),
    "theta": ("Theta", "exponential_smoothing"), "arima": ("ARIMA/SARIMA", "arima"),
    "arima_auto": ("Auto-ARIMA", "arima"), "var": ("VAR", "multivariate"), "vecm": ("VECM", "multivariate"),
    "garch": ("GARCH(p,q)", "volatility"), "egarch": ("EGARCH", "volatility"),
    "prophet": ("Prophet", "structural"), "tbats": ("TBATS", "structural"),
    "xgboost": ("XGBoost", "tree_ml"), "lightgbm": ("LightGBM", "tree_ml"),
    "catboost": ("CatBoost", "tree_ml"), "random_forest": ("Random Forest", "tree_ml"),
    "lstm": ("LSTM", "neural"), "deepar": ("DeepAR", "neural"), "tft": ("TFT", "neural"),
    "nbeats": ("N-BEATS", "neural"), "nhits": ("N-HiTS", "neural"),
}


def _resolve_model_info(model_id: str) -> tuple[str, str]:
    model_info = _MODEL_INFO.get(model_id)
    if model_info is None:
        spec = _get_spec()
        found = None
        for fam in spec.families:
            for m in fam.models:
                if m.id == model_id:
                    found = (m.name, fam.family_id)
                    break
            if found:
                break
        if not found:
            raise HTTPException(status_code=404, detail=f"Модель '{model_id}' не найдена в спецификации")
        model_info = found
    return model_info


@router.post(
    "/backtest",
    response_model=BacktestResponse,
    dependencies=[Depends(require_capability("can_train_models"))],
)
def run_backtest(
    payload: BacktestRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    model_id = payload.model_id
    profile = payload.profile
    train_ratio = payload.train_ratio
    model_info = _resolve_model_info(model_id)
    series = _generate_series(profile.n_observations, profile.frequency, profile.has_seasonality)
    seasonal_period = _resolve_seasonal_period(profile)
    metrics, duration_ms = _run_backtest_with_series(model_id, model_info, series, train_ratio, seasonal_period)
    n_train = int(profile.n_observations * train_ratio)
    n_test = profile.n_observations - n_train
    return BacktestResponse(
        model_id=model_id, model_name=model_info[0], family_id=model_info[1], metrics=metrics,
        n_train=n_train, n_test=n_test, train_ratio=train_ratio,
        duration_ms=round(duration_ms, 2), data_source="synthetic",
        execution_contract=MODEL_EXECUTION_REGISTRY.describe(model_id),
    )


def _resolve_seasonal_period(profile) -> int:
    if profile.seasonal_periods:
        return profile.seasonal_periods[0]
    return {"D": 7, "W": 52, "M": 12, "Q": 4, "Y": 1}.get(profile.frequency, 12)


def _run_backtest_with_series(
    model_id: str,
    model_info: tuple[str, str],
    series: list[float],
    train_ratio: float,
    seasonal_period: int,
) -> tuple[BacktestMetrics, float]:
    start = time.monotonic()
    if model_id not in PRODUCTION_BACKTEST_MODEL_IDS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Production backtest для модели '{model_id}' не реализован; "
                "фиктивные метрики запрещены"
            ),
        )
    impl = _BACKTEST_IMPLEMENTATIONS.get(model_id)
    if impl:
        metrics = impl(series, train_ratio, seasonal_period)
    else:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Реестр помечает '{model_id}' как production-ready, "
                "но backtest implementation отсутствует"
            ),
        )
    return metrics, (time.monotonic() - start) * 1000


@router.post(
    "/train",
    dependencies=[Depends(require_capability("can_train_models"))],
)
def train_model(principal: AuthenticatedPrincipal = Depends(get_current_principal)):
    return {
        "status": "accepted",
        "principal_id": principal.principal_id,
        "message": "Обучение модели запущено (заглушка -- реальный запуск не реализован)",
    }


@router.post(
    "/tune",
    response_model=TuneResponse,
    dependencies=[Depends(require_capability("can_train_models"))],
)
def tune_model(
    payload: TuneRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """Grid search гиперпараметров через expanding-window CV."""
    spec = _get_spec()
    cv_config = payload.cv or CVConfig()
    return _execute_tune(
        spec=spec,
        model_id=payload.model_id,
        series=payload.series,
        cv_config=cv_config,
        max_trials=payload.max_trials,
        metric=payload.metric,
        random_state=payload.random_state,
    )
