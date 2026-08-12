# apps/api/routers/models.py
"""
Роутер модуля «Моделирование».

Эндпоинты:
  POST /v1/models/candidates  — пул кандидатов (движок применимости)
  POST /v1/models/backtest    — бэктест одной модели (auth-protected,
                                 синтетический ряд — legacy Phase 0)
  POST /v1/models/train        — обучение модели (заглушка)

Phase 0.5: логика бэктеста вынесена в _run_backtest_with_series(), чтобы
её мог переиспользовать зеркальный эндпоинт /v1/internal/models/backtest
(в routers/internal.py) — он использует РЕАЛЬНЫЙ ряд из сессии когда
target_column задан.
"""
import logging
import time
import math
from collections import Counter
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException

from apps.api.auth import require_capability, get_current_principal
from apps.api.plans import AuthenticatedPrincipal
from apps.api.schemas import (
    CandidatesRequest,
    CandidatesResponse,
    ModelCandidate,
    CandidatesStatistics,
    BacktestRequest,
    BacktestResponse,
    BacktestMetrics,
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
_BACKTEST_IMPLEMENTATIONS = {
    "naive": lambda s, tr, p: _run_naive_backtest(s, tr),
    "seasonal_naive": lambda s, tr, p: _run_seasonal_naive_backtest(s, tr, p),
    "drift": lambda s, tr, p: _run_drift_backtest(s, tr),
    "mean": lambda s, tr, p: _run_mean_backtest(s, tr),
}

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
    Запустить бэктест для одной модели (auth-protected, /v1/models/backtest).

    Историческое поведение (Phase 0): всегда использует синтетический ряд,
    сгенерированный по профилю данных. Без API-ключа сюда не дойти --
    браузер посетителя standalone использует зеркало /v1/internal/models/backtest.

    Метрики: MAE, RMSE, MAPE (%), MASE.
    Взвешенный скоринг: 0.35*MAE_n + 0.25*RMSE_n + 0.20*MAPE_n + 0.20*MASE_n.
    """
    model_id = payload.model_id
    profile = payload.profile
    train_ratio = payload.train_ratio

    # Определяем (model_name, family_id)
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
# ═══════════════════════════════════════════════════════════


def _resolve_model_info(model_id: str) -> tuple[str, str]:
    """Найти (model_name, family_id) по model_id.

    Сначала в _MODEL_INFO dict, потом в спецификации modeling.yaml.
    Поднимает HTTPException(404) если модель не найдена.
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
