# apps/api/model_impls/_metrics.py
"""
Общие метрики бэктеста для всех реализаций model_impls.

Скопировано из apps/api/routers/models.py::_compute_metrics — БЕЗ изменений
формул. Причина копирования (а не импорта из роутера): избежать циклического
импорта model_impls <-> routers.models. Роутер импортирует model_impls (чтобы
зарегистрировать реализации в _BACKTEST_IMPLEMENTATIONS), а model_impls
импортирует _metrics. Если бы _compute_metrics остался в роутере —
model_impls пришлось бы импортировать routers.models, что создало бы цикл.

Контракт метрик (НЕ меняется в Phase 6-P0):
- MAE: mean(|y_true - y_pred|)
- RMSE: sqrt(mean((y_true - y_pred)^2))
- MAPE: mean(|y_true - y_pred| / |y_true|) * 100, с защитой от деления на 0
- MASE: MAE_model / MAE_naive (naive = shift-1 на train)
- weighted_score: 0.35*MAE_n + 0.25*RMSE_n + 0.20*MAPE_n + 0.20*MASE_n
"""
from __future__ import annotations

import math
from typing import List

from apps.api.schemas import BacktestMetrics


# Веса ранжирования (из rules/modeling.yaml, секция metrics.weights)
_METRIC_WEIGHTS = {"mae": 0.35, "rmse": 0.25, "mape": 0.20, "mase": 0.20}


def compute_metrics(
    y_true: List[float],
    y_pred: List[float],
    y_train: List[float],
) -> BacktestMetrics:
    """Вычисление MAE, RMSE, MAPE, MASE и weighted_score.

    Идентично routers/models.py::_compute_metrics — те же формулы,
    та же нормализация, тот же round(). Изменения здесь автоматически
    означают расхождение с baseline-метриками — НЕ делать без
    согласования с тимлидом (контракт UI/UX).
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
    if len(y_train) > 1:
        naive_errors = [
            abs(y_train[i] - y_train[i - 1]) for i in range(1, len(y_train))
        ]
        mae_naive = sum(naive_errors) / len(naive_errors) if naive_errors else 1.0
    else:
        mae_naive = 1.0
    mase = mae / mae_naive if mae_naive > 1e-10 else 0.0

    # Нормализация для weighted_score (0-1 scale, где ниже = лучше)
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
