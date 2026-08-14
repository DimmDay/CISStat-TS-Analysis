# apps/api/routers/models.py
"""
Роутер модуля «Моделирование».

Эндпоинты:
  POST /v1/models/candidates  — пул кандидатов (движок применимости)
  POST /v1/models/backtest    — бэктест одной модели
  POST /v1/models/train       — обучение модели (заглушка)
  POST /v1/models/tune        — grid search гиперпараметров с CV (Phase 1-C)
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

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Загрузка спецификации modeling.yaml (один раз при старте) ──────────────
# Ленивая загрузка: спецификация парсится при первом обращении,
# затем кэшируется в модуле. При ошибке — 500 с понятным сообщением.

_spec_cache = None
_SPEC_YAML_PATH = "rules/modeling.yaml"


def _get_spec():
    """Получить спецификацию моделирования (с кэшем)."""
    global _spec_cache
    if _spec_cache is not None:
        return _spec_cache
    try:
        from src.catalog.modeling_spec_loader import ModelingSpec
        _spec_cache = ModelingSpec.from_yaml(_SPEC_YAML_PATH)
        logger.info("Modeling spec loaded: %s", repr(_spec_cache))
        return _spec_cache
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail=f"Спецификация моделирования не найдена: {_SPEC_YAML_PATH}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Ошибка загрузки спецификации моделирования: {e}",
        )


def _reset_spec_cache():
    """Сбросить кэш (для тестов)."""
    global _spec_cache
    _spec_cache = None


# ═══════════════════════════════════════════════════════════
# POST /v1/models/candidates
# ═══════════════════════════════════════════════════════════

@router.post(
    "/candidates",
    response_model=CandidatesResponse,
    dependencies=[Depends(require_capability("can_train_models"))],
)
def get_candidates(
    payload: CandidatesRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """
    Получить пул кандидатов для моделирования на основе профиля данных.

    Применяет движок применимости (23 правила, 4 уровня) ко всем 24 моделям
    из 8 семейств. Возвращает модели с уровнем ≥ min_level, исключая
    NOT_APPLICABLE. Baseline-модели включаются всегда.

    Доступно только принципалам с can_train_models=True
    (professional, enterprise, admin, internal_analyst).

    Браузер visitor'а standalone НЕ имеет API-ключа — для него есть
    зеркало /v1/internal/models/candidates (без auth).
    """
    return _compute_candidates(payload)


def _compute_candidates(payload: CandidatesRequest) -> CandidatesResponse:
    """Чистая бизнес-логика: применить движок применимости к 24 моделям.

    Вынесена из get_candidates, чтобы её мог переиспользовать зеркальный
    эндпоинт /v1/internal/models/candidates (routers/internal.py). Логика
    идентична — разница только в auth. Восстановлено (утрачено в Task 19-C,
    см. worklog: коммит ветвился от устаревшей базы models.py).
    """
    spec = _get_spec()

    # Конвертируем request-схему в DataProfile (Pydantic → Pydantic)
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

    # Валидация min_level
    valid_levels = {"RECOMMENDED", "CONDITIONALLY_APPLICABLE",
                    "NOT_RECOMMENDED", "NOT_APPLICABLE"}
    min_level = payload.min_level or "CONDITIONALLY_APPLICABLE"
    if min_level not in valid_levels:
        raise HTTPException(
            status_code=422,
            detail=f"Некорректный min_level: '{min_level}'. Допустимые: {valid_levels}",
        )

    # Получаем пул кандидатов
    candidate_results = spec.get_candidate_pool(profile, min_level=min_level)

    # Конвертируем в response-схему
    candidates = [
        ModelCandidate(
            model_id=r.model_id,
            model_name=r.model_name,
            family_id=r.family_id,
            level=r.level,
            rule_id=r.rule_id,
            message=r.message,
            rank=r.rank,
        )
        for r in candidate_results
    ]

    # Статистика
    level_counts = Counter(c.level for c in candidates)
    statistics = CandidatesStatistics(
        total_candidates=len(candidates),
        by_level=dict(level_counts),
        total_models_in_spec=spec.total_model_count(),
    )

    return CandidatesResponse(
        candidates=candidates,
        statistics=statistics,
        spec_version=spec.metadata.version,
    )


# ═══════════════════════════════════════════════════════════
# POST /v1/models/backtest
# ═══════════════════════════════════════════════════════════

# ── Веса ранжирования (из modeling.yaml) ──
_METRIC_WEIGHTS = {"mae": 0.35, "rmse": 0.25, "mape": 0.20, "mase": 0.20}


def _generate_series(n: int, frequency: str, has_seasonality: bool) -> list[float]:
    """
    Генерация синтетического временного ряда для бэктеста.

    Используется, когда реальный датасет ещё не загружен.
    Формула: trend + seasonality + noise
    - trend: линейный рост 0.5 * t
    - seasonality: sin(2π * t / period) * amplitude
    - noise: N(0, σ²) где σ = 0.1 * mean_value
    """
    import random
    random.seed(42)  # воспроизводимость
    seasonal_period = {"D": 7, "W": 52, "M": 12, "Q": 4, "Y": 1}.get(frequency, 12)
    series = []
    for t in range(n):
        trend = 100.0 + 0.5 * t
        season = (10.0 * math.sin(2 * math.pi * t / seasonal_period)
                  if has_seasonality else 0.0)
        noise = random.gauss(0, 2.0)
        series.append(trend + season + noise)
    return series


def _compute_metrics(
    y_true: list[float],
    y_pred: list[float],
    y_train: list[float],
) -> BacktestMetrics:
    """
    Вычисление MAE, RMSE, MAPE, MASE и weighted_score.

    MASE = MAE_model / MAE_naive, где MAE_naive — ошибка Naive-прогноза
    на обучающей выборке (shift на 1).
    """
    n = len(y_true)
    if n == 0:
        return BacktestMetrics(mae=0, rmse=0, mape=0, mase=0, weighted_score=0)

    # MAE
    mae = sum(abs(a - p) for a, p in zip(y_true, y_pred)) / n

    # RMSE
    rmse = math.sqrt(sum((a - p) ** 2 for a, p in zip(y_true, y_pred)) / n)

    # MAPE (%), защищаем от деления на 0
    mape_sum = 0.0
    mape_count = 0
    for a, p in zip(y_true, y_pred):
        if abs(a) > 1e-10:
            mape_sum += abs((a - p) / a)
            mape_count += 1
    mape = (mape_sum / mape_count * 100) if mape_count > 0 else 0.0

    # MASE: MAE_model / MAE_naive_season1
    # Naive seasonal (season=1 → обычный Naive): прогноз = y_{t-1}
    if len(y_train) > 1:
        naive_errors = [
            abs(y_train[i] - y_train[i - 1]) for i in range(1, len(y_train))
        ]
        mae_naive = sum(naive_errors) / len(naive_errors) if naive_errors else 1.0
    else:
        mae_naive = 1.0
    mase = mae / mae_naive if mae_naive > 1e-10 else 0.0

    # Нормализация для weighted_score (0–1 scale, где ниже = лучше)
    # Используем simple min-max с reasonable bounds
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
        mae=round(mae, 4),
        rmse=round(rmse, 4),
        mape=round(mape, 2),
        mase=round(mase, 4),
        weighted_score=round(weighted_score, 4),
    )


def _run_naive_backtest(
    series: list[float], train_ratio: float
) -> BacktestMetrics:
    """Naive: ŷ_t = y_{t-1}."""
    n = len(series)
    n_train = int(n * train_ratio)
    y_train, y_test = series[:n_train], series[n_train:]
    y_pred = [y_train[-1]] + y_test[:-1]  # shift by 1
    return _compute_metrics(y_test, y_pred, y_train)


def _run_seasonal_naive_backtest(
    series: list[float], train_ratio: float, seasonal_period: int = 12
) -> BacktestMetrics:
    """Seasonal Naive: ŷ_t = y_{t-m}."""
    n = len(series)
    n_train = int(n * train_ratio)
    y_train, y_test = series[:n_train], series[n_train:]
    y_pred = []
    for i in range(len(y_test)):
        idx = n_train + i - seasonal_period
        if idx >= 0:
            y_pred.append(series[idx])
        else:
            y_pred.append(y_train[-1])  # fallback
    return _compute_metrics(y_test, y_pred, y_train)


def _run_drift_backtest(
    series: list[float], train_ratio: float
) -> BacktestMetrics:
    """Drift: ŷ_t = y_{t-1} + (y_T - y_1) / (T-1)."""
    n = len(series)
    n_train = int(n * train_ratio)
    y_train, y_test = series[:n_train], series[n_train:]
    drift = (y_train[-1] - y_train[0]) / max(len(y_train) - 1, 1)
    y_pred = [y_train[-1] + drift * (i + 1) for i in range(len(y_test))]
    return _compute_metrics(y_test, y_pred, y_train)


def _run_mean_backtest(
    series: list[float], train_ratio: float
) -> BacktestMetrics:
    """Mean: ŷ_t = mean(y_train)."""
    n = len(series)
    n_train = int(n * train_ratio)
    y_train, y_test = series[:n_train], series[n_train:]
    train_mean = sum(y_train) / len(y_train) if y_train else 0.0
    y_pred = [train_mean] * len(y_test)
    return _compute_metrics(y_test, y_pred, y_train)


# Маппинг model_id → функция бэктеста
# Phase 6-P0: добавлены 5 реальных реализаций через statsmodels:
#   - ets / ets_damped: Holt-Winters ExponentialSmoothing
#   - theta: формальная Theta-модель (Assimakopoulos & Nikolopoulos 2000)
#   - arima: ARIMA(1,1,1) с фиксированным порядком
#   - arima_auto: grid search по (p,d,q) с AIC-критерием
# До Phase 6-P0 эти 5 model_id попадали в else-ветку ниже (заглушка
# naive*penalty). Теперь они вызывают реальные модели из apps/api/model_impls/.
# Восстановлено (было утрачено в Task 19-C, ветвившемся от устаревшей базы
# models.py — код в apps/api/model_impls/ физически присутствовал на диске,
# но не был подключён сюда).
#
# Семейства neural / structural / tree_ml / multivariate / volatility
# остаются заглушками (Phase 6-P1+).
from apps.api.model_impls import (
    run_ets_backtest,
    run_ets_damped_backtest,
    run_theta_backtest,
    run_arima_backtest,
    run_auto_arima_backtest,
)

_BACKTEST_IMPLEMENTATIONS = {
    # ── Baselines (Phase 0): без statsmodels, простые формулы ──
    "naive": lambda s, tr, p: _run_naive_backtest(s, tr),
    "seasonal_naive": lambda s, tr, p: _run_seasonal_naive_backtest(s, tr, p),
    "drift": lambda s, tr, p: _run_drift_backtest(s, tr),
    "mean": lambda s, tr, p: _run_mean_backtest(s, tr),
    # ── Phase 6-P0: реальные модели через statsmodels ──
    "ets": run_ets_backtest,
    "ets_damped": run_ets_damped_backtest,
    "theta": run_theta_backtest,
    "arima": run_arima_backtest,
    "arima_auto": run_auto_arima_backtest,
}


# ═══════════════════════════════════════════════════════════
# Phase 1-C: Тюнинг гиперпараметров (POST /v1/models/tune)
# ═══════════════════════════════════════════════════════════

# Hard cap на размер grid'а. Защита от экспоненциального роста
# (например, p[5]×d[3]×q[5]×P[2]×D[2]×Q[2] = 600 trials). Если grid
# превысит этот лимит — обрезаем random sampling с воспроизводимым seed.
# Контракт зафиксирован в Phase 1-A (см. modeling_spec_loader.py).
MAX_TRIALS: int = 64


def _build_grid(param_space: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    """Декартово произведение всех значений в param_space.

    Возвращает list of dict, где каждый dict — одна комбинация:
        {"trend": "add", "seasonal": None, "seasonal_periods": 12, ...}

    Порядок соответствует itertools.product (последний ключ меняется быстрее).

    Пример:
        {"p": [0, 1], "q": [0, 1]} → [
            {"p": 0, "q": 0},
            {"p": 0, "q": 1},
            {"p": 1, "q": 0},
            {"p": 1, "q": 1},
        ]

    Пустой param_space возвращает [{}] — один trial с пустыми params
    (валидный крайний случай: модель без гиперпараметров всё равно
    может быть оценена через CV, хотя обычно такие модели не имеют
    param_space вовсе — см. baseline-модели).
    """
    keys = list(param_space.keys())
    values = [param_space[k] for k in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def _truncate_grid(
    grid: List[Dict[str, Any]],
    max_trials: int,
    random_state: int,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Применить max_trials защиту к grid'у.

    Если len(grid) <= max_trials → без изменений (truncated=False).
    Если len(grid) >  max_trials → random sample max_trials trials без
    возвращения, с воспроизводимым random_state (truncated=True).

    Возвращает (trials, truncated).

    Контракт воспроизводимости: одинаковый random_state → одинаковый
    набор trials. Используется random.Random(seed).sample — стандартный
    Python sampler без возвращения.
    """
    if len(grid) <= max_trials:
        return grid, False

    rng = random.Random(random_state)
    sampled_indices = sorted(rng.sample(range(len(grid)), max_trials))
    return [grid[i] for i in sampled_indices], True


def _tunable_predict(
    model_id: str,
    y_train: List[float],
    test_size: int,
    params: Dict[str, Any],
) -> List[float]:
    """STUB: прогноз с вариацией по params.

    Phase 1-C проверяет механику grid × CV × max_trials, а НЕ реальные
    модели. Этот stub возвращает прогноз длиной test_size, который
    ЗАВИСИТ от params — этого достаточно, чтобы CV выбрал «лучший»
    trial детерминированно.

    Phase 6 заменит эту функцию на реальные ETS/ARIMA/Prophet реализации
    (apps/api/model_impls/), которые будут вызывать statsmodels/pmdarima/etc.
    Тогда same params → same y_pred (что важно для воспроизводимости CV).

    Эвристика stub'а (по типам params):
      - trend="add" → линейный drift (y[-1]-y[0])/(n-1)
      - trend="mul" → геометрический growth (y[-1]/y[0])^(1/(n-1)) - 1
      - damped_trend=True → trend_term *= 0.5 (затухание)
      - seasonal: stub игнорирует (Phase 6 добавит сезонную компоненту)
      - p/q (ARIMA): небольшие константные сдвиги (p*0.01, q*0.01, d*0.02)

    Все расчёты сделаны простыми (без numpy), чтобы тесты были
    детерминированы и не зависели от внешних библиотек.
    """
    if not y_train:
        return [0.0] * test_size

    last = y_train[-1]
    n_train = len(y_train)

    # Trend component
    trend_term = 0.0
    if "trend" in params:
        if params["trend"] == "mul":
            # Geometric growth
            if n_train > 1 and y_train[0] > 1e-10:
                growth = (y_train[-1] / y_train[0]) ** (1.0 / max(n_train - 1, 1)) - 1
                trend_term = growth * last
        else:  # "add" or anything else
            if n_train > 1:
                trend_term = (y_train[-1] - y_train[0]) / max(n_train - 1, 1)

    # Damped trend reduces the trend component
    if params.get("damped_trend") is True:
        trend_term *= 0.5

    # ARIMA-style params (p, d, q) — small variations
    p_factor = float(params.get("p", 0)) * 0.01
    d_factor = float(params.get("d", 0)) * 0.02
    q_factor = float(params.get("q", 0)) * 0.01

    preds: List[float] = []
    for i in range(test_size):
        pred = last + trend_term * (i + 1) + p_factor * i + d_factor + q_factor * i
        preds.append(pred)
    return preds


# Допустимые метрики для выбора лучшего trial'а (валидация в endpoint)
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
    """Pure function: grid search гиперпараметров с expanding-window CV.

    Не зависит от FastAPI request/response — принимает уже-validated
    параметры. Это позволяет тестировать логику напрямую (без HTTP),
    см. tests/api/test_tune.py.

    Шаги:
      1. Получить модель из spec по model_id (404 если нет).
      2. Проверить param_space (422 если None — baseline/no-tuning).
      3. Построить grid (декартово произведение).
      4. Применить max_trials защиту (random sampling если нужно).
      5. Валидировать CV config и длину ряда (422 если слишком короток).
      6. Для каждого trial: для каждого fold — predict + compute metrics.
         Усреднить метрики по folds.
      7. Выбрать best_trial с минимальным значением `metric`.
      8. Вернуть TuneResponse.

    Аргументы:
        spec:          ModelingSpec (загруженная из YAML).
        model_id:      ID модели (должна быть в spec).
        series:        временной ряд (List[float], длина >= cv.min_samples()).
        cv_config:     CVConfig (Pydantic-схема, уже валидирована).
        max_trials:    Optional[int]; None → использовать MAX_TRIALS.
        metric:        str из _VALID_METRICS (mae/rmse/mape/mase/weighted_score).
        random_state:  seed для воспроизводимого random sampling.

    Raises:
        HTTPException(404): model_id не найден в spec.
        HTTPException(422): param_space is None / ряд слишком короток /
                            невалидная метрика / невалидный CV config.
    """
    start = time.monotonic()

    # ── 1. Получить модель ────────────────────────────────────
    model = spec.get_model(model_id)
    if model is None:
        raise HTTPException(
            status_code=404,
            detail=f"Модель '{model_id}' не найдена в спецификации",
        )

    # ── 2. Проверить param_space ──────────────────────────────
    if model.param_space is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Модель '{model_id}' не поддерживает тюнинг: "
                f"param_space не задан в спецификации. "
                f"Baseline-модели (naive/drift/mean) не имеют гиперпараметров."
            ),
        )

    # ── 3. Построить grid ─────────────────────────────────────
    full_grid = _build_grid(model.param_space)
    grid_size = len(full_grid)

    # ── 4. max_trials защита ─────────────────────────────────
    # effective_max: пользовательский max_trials, но не больше MAX_TRIALS.
    requested = max_trials if max_trials is not None else MAX_TRIALS
    effective_max = min(requested, MAX_TRIALS)
    trials_grid, truncated = _truncate_grid(
        full_grid, max_trials=effective_max, random_state=random_state,
    )

    # ── 5. Валидировать CV config и длину ряда ────────────────
    try:
        cv = ExpandingWindowCV(
            n_splits=cv_config.n_splits,
            test_size=cv_config.test_size,
            min_train_size=cv_config.min_train_size,
            step=cv_config.step,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Некорректная CV config: {e}",
        )

    if len(series) < cv.min_samples():
        raise HTTPException(
            status_code=422,
            detail=(
                f"Слишком короткий ряд для CV: нужно >= {cv.min_samples()}, "
                f"есть {len(series)}. Уменьшите n_splits, test_size "
                f"или min_train_size."
            ),
        )

    # ── Валидация metric (дополнительная защита, хотя Pydantic Literal уже отсекает) ─
    if metric not in _VALID_METRICS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Некорректная метрика '{metric}'. "
                f"Допустимые: {sorted(_VALID_METRICS)}."
            ),
        )

    # ── 6. CV для каждого trial ──────────────────────────────
    splits = cv.split(len(series))
    n_folds = len(splits)

    trial_results: List[TuneTrialResult] = []
    for params in trials_grid:
        fold_metrics: List[BacktestMetrics] = []
        for split in splits:
            y_train = [series[i] for i in split.train_idx]
            y_test = [series[i] for i in split.test_idx]
            y_pred = _tunable_predict(model_id, y_train, len(y_test), params)
            fold_metrics.append(_compute_metrics(y_test, y_pred, y_train))

        # Усреднение по folds
        if fold_metrics:
            avg_metrics = BacktestMetrics(
                mae=round(sum(m.mae for m in fold_metrics) / len(fold_metrics), 6),
                rmse=round(sum(m.rmse for m in fold_metrics) / len(fold_metrics), 6),
                mape=round(sum(m.mape for m in fold_metrics) / len(fold_metrics), 6),
                mase=round(sum(m.mase for m in fold_metrics) / len(fold_metrics), 6),
                weighted_score=round(
                    sum(m.weighted_score for m in fold_metrics) / len(fold_metrics), 6
                ),
            )
        else:
            # Fallback (не должно случиться, т.к. cv.split вернул >= 1 fold
            # после проверки min_samples выше)
            avg_metrics = BacktestMetrics(
                mae=0.0, rmse=0.0, mape=0.0, mase=0.0, weighted_score=0.0,
            )

        trial_results.append(TuneTrialResult(
            params=params,
            metrics=avg_metrics,
            n_folds=n_folds,
        ))

    # ── 7. Выбрать best trial (минимум metric) ───────────────
    best_idx = min(
        range(len(trial_results)),
        key=lambda i: getattr(trial_results[i].metrics, metric),
    )
    best = trial_results[best_idx]

    # ── 8. Имя/семейство модели ──────────────────────────────
    family = spec.get_family_for_model(model_id)
    family_id = family.id if family else "unknown"

    duration_ms = (time.monotonic() - start) * 1000

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
    )

# Маппинг model_id → (model_name, family_id) для неизвестных моделй
_MODEL_INFO = {
    "naive": ("Naive", "baselines"),
    "seasonal_naive": ("Seasonal Naive", "baselines"),
    "drift": ("Drift", "baselines"),
    "mean": ("Mean", "baselines"),
    "ets": ("ETS (Auto)", "exponential_smoothing"),
    "ets_damped": ("ETS Damped", "exponential_smoothing"),
    "theta": ("Theta", "exponential_smoothing"),
    "arima": ("ARIMA/SARIMA", "arima"),
    "arima_auto": ("Auto-ARIMA", "arima"),
    "var": ("VAR", "multivariate"),
    "vecm": ("VECM", "multivariate"),
    "garch": ("GARCH(p,q)", "volatility"),
    "egarch": ("EGARCH", "volatility"),
    "prophet": ("Prophet", "structural"),
    "tbats": ("TBATS", "structural"),
    "xgboost": ("XGBoost", "tree_ml"),
    "lightgbm": ("LightGBM", "tree_ml"),
    "catboost": ("CatBoost", "tree_ml"),
    "random_forest": ("Random Forest", "tree_ml"),
    "lstm": ("LSTM", "neural"),
    "deepar": ("DeepAR", "neural"),
    "tft": ("TFT", "neural"),
    "nbeats": ("N-BEATS", "neural"),
    "wavenet": ("WaveNet", "neural"),
}


def _resolve_model_info(model_id: str) -> tuple[str, str]:
    """Найти (model_name, family_id) по model_id.

    Сначала в _MODEL_INFO dict, потом в спецификации modeling.yaml.
    Поднимает HTTPException(404) если модель не найдена.

    Восстановлено как отдельная функция (была утрачена при коммите
    Task 19-C, ветвившемся от устаревшей базы models.py -- см. worklog).
    apps/api/routers/internal.py импортирует эту функцию напрямую;
    инлайновая копия в run_backtest ниже была тем самым дублированием,
    против которого предостерегает docs/MIGRATION_ARCHITECTURE.md §7.2.
    """
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
            raise HTTPException(
                status_code=404,
                detail=f"Модель '{model_id}' не найдена в спецификации",
            )
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
    """
    Запустить бэктест для одной модели.

    Для baseline-моделей (Naive, Seasonal Naive, Drift, Mean) выполняется
    реальный расчёт на синтетическом ряде, сгенерированном по профилю данных.
    Для остальных моделей — заглушка с аппроксимированными метриками.

    Метрики: MAE, RMSE, MAPE (%), MASE.
    Взвешенный скоринг: 0.35*MAE_n + 0.25*RMSE_n + 0.20*MAPE_n + 0.20*MASE_n.
    """
    model_id = payload.model_id
    profile = payload.profile
    train_ratio = payload.train_ratio

    model_info = _resolve_model_info(model_id)

    # Генерируем синтетический ряд по профилю
    series = _generate_series(
        n=profile.n_observations,
        frequency=profile.frequency,
        has_seasonality=profile.has_seasonality,
    )

    # Сезонный период для Seasonal Naive
    seasonal_period = _resolve_seasonal_period(profile)

    metrics, duration_ms = _run_backtest_with_series(
        model_id=model_id,
        model_info=model_info,
        series=series,
        train_ratio=train_ratio,
        seasonal_period=seasonal_period,
    )

    n_train = int(profile.n_observations * train_ratio)
    n_test = profile.n_observations - n_train

    return BacktestResponse(
        model_id=model_id,
        model_name=model_info[0],
        family_id=model_info[1],
        metrics=metrics,
        n_train=n_train,
        n_test=n_test,
        train_ratio=train_ratio,
        duration_ms=round(duration_ms, 2),
        data_source="synthetic",  # legacy path: всегда синтетика
    )


# ═══════════════════════════════════════════════════════════
# Phase 0.5: переиспользуемые функции для зеркала /v1/internal/models/backtest
#
# Восстановлено (утрачено в Task 19-C, коммит ветвился от устаревшей базы
# models.py — см. worklog "fix: restore session/target_column/panel-balance
# schemas lost in Task 19-C base merge"). apps/api/routers/internal.py
# импортирует _resolve_seasonal_period и _run_backtest_with_series напрямую
# для зеркального эндпоинта /v1/internal/models/backtest (реальный ряд из
# session.dataframe, а не синтетика).
# ═══════════════════════════════════════════════════════════


def _resolve_seasonal_period(profile) -> int:
    """Сезонный период для Seasonal Naive — из profile.seasonal_periods
    или из дефолтного маппинга frequency → period.
    """
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
    """Выполнить бэктест на ЗАДАННОМ ряде (синтетическом или реальном).

    Возвращает (metrics, duration_ms). Не знает о сессии — просто считает
    метрики по ряду, который ей передали. Это позволяет переиспользовать
    её и для /v1/models/backtest (синтетический ряд), и для
    /v1/internal/models/backtest (реальный ряд из session.dataframe).
    """
    model_name, family_id = model_info
    start = time.monotonic()

    impl = _BACKTEST_IMPLEMENTATIONS.get(model_id)
    if impl:
        metrics = impl(series, train_ratio, seasonal_period)
    else:
        # Заглушка: аппроксимация на основе Naive + штраф за сложность
        naive_metrics = _run_naive_backtest(series, train_ratio)
        family_penalty = {
            "exponential_smoothing": 0.85,
            "arima": 0.80,
            "structural": 0.75,
            "tree_ml": 0.70,
            "neural": 0.60,
            "multivariate": 0.65,
            "volatility": 0.70,
        }.get(family_id, 1.0)
        metrics = BacktestMetrics(
            mae=round(naive_metrics.mae * (1.1 / family_penalty), 4),
            rmse=round(naive_metrics.rmse * (1.1 / family_penalty), 4),
            mape=round(naive_metrics.mape * (1.1 / family_penalty), 2),
            mase=round(naive_metrics.mase * (1.1 / family_penalty), 4),
            weighted_score=round(
                naive_metrics.weighted_score * (1.1 / family_penalty), 4
            ),
        )

    duration_ms = (time.monotonic() - start) * 1000
    return metrics, duration_ms


# ═══════════════════════════════════════════════════════════
# POST /v1/models/train  (заглушка — из предыдущей версии)
# ═══════════════════════════════════════════════════════════

@router.post(
    "/train",
    dependencies=[Depends(require_capability("can_train_models"))],
)
def train_model(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """
    Доступно только принципалам, чей план/роль даёт can_train_models=True
    (internal_analyst, admin, тарифы professional/enterprise) -- НЕ demo
    и НЕ starter (см. PLAN_DEFINITIONS в plans.py).
    """
    return {
        "status": "accepted",
        "principal_id": principal.principal_id,
        "message": "Обучение модели запущено (заглушка -- реальный запуск не реализован)",
    }


# ═══════════════════════════════════════════════════════════
# POST /v1/models/tune — grid search гиперпараметров (Phase 1-C)
# ═══════════════════════════════════════════════════════════
#
# Зависимости:
#   - Phase 1-A: param_space в modeling.yaml + FamilyModel.param_space поле.
#   - Phase 1-B: ExpandingWindowCV в apps/api/cv.py.
#
# Логика (см. _execute_tune docstring):
#   1. Загрузить spec, найти модель по model_id (404 если нет).
#   2. Если param_space is None → 422 (baseline/no-tuning).
#   3. Построить grid (декартово произведение).
#   4. max_trials защита: если grid_size > MAX_TRIALS → random sample.
#      Пользователь может запросить меньший max_trials.
#   5. CV: для каждого trial × каждого fold → predict + metrics.
#      Усреднить метрики по folds.
#   6. Выбрать best_trial с минимальным значением metric.
#
# ВАЖНО: _tunable_predict() — STUB. Phase 6 заменит на реальные ETS/ARIMA
# имплементации (apps/api/model_impls/). Stub сделан детерминированным,
# чтобы CV выбор был воспроизводим.


@router.post(
    "/tune",
    response_model=TuneResponse,
    dependencies=[Depends(require_capability("can_train_models"))],
)
def tune_model(
    payload: TuneRequest,
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """
    Grid search гиперпараметров модели через expanding-window CV.

    Читает param_space модели из спецификации (Phase 1-A) и применяет
    ExpandingWindowCV (Phase 1-B) для честной оценки гиперпараметров
    на временных рядах (KFold sklearn не подходит — он нарушает
    временную причинность).

    max_trials защита (hard cap MAX_TRIALS=64):
      - Если grid_size <= MAX_TRIALS → выполняются все trials.
      - Если grid_size >  MAX_TRIALS → random sampling MAX_TRIALS trials
        с воспроизводимым random_state.
      - Пользователь может запросить меньший max_trials (для ускорения).

    Возвращает best_params + все trials с метриками (для аудита).

    Доступно только принципалам с can_train_models=True
    (professional, enterprise, admin, internal_analyst).
    """
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
