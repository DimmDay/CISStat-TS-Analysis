# -*- coding: utf-8 -*-
"""Task FORECAST-1a (F-1): проверка находки аудитора на statsmodels 0.14.5.

Ожидания на 0.14.5 (удовлетворяет декларации >=0.14.0):
1. compute_forecast(ci_method=parametric_simulation) выбрасывает СЫРОЙ TypeError
   (не ForecastingError) -> в API-контуре это 500 вместо честного 422.
2. Юнит-тесты прогнозного контура RED.

Скрипт запускается ТОЛЬКО на statsmodels 0.14.x (временная установка).
"""
from __future__ import annotations

import sys

import numpy as np
import statsmodels


def main() -> int:
    print(f"statsmodels {statsmodels.__version__}")
    assert statsmodels.__version__.startswith("0.14"), (
        "Скрипт предназначен для проверки пола 0.14.x"
    )

    from apps.api.final_fit import build_final_fit
    from apps.api.forecasting import compute_forecast
    from apps.api.forecasting_contract import (
        AlphaResolution,
        resolve_forecast_alpha,
    )
    from apps.api.model_execution import MODEL_EXECUTION_REGISTRY

    rng = np.random.default_rng(20260914)
    history = list(np.sin(np.arange(96) / 6.0) + 10.0 + rng.normal(0, 0.1, 96))

    fit = build_final_fit(
        frame=__import__("pandas").DataFrame(
            {"value": history, "date": __import__("pandas").date_range("2025-01-01", periods=96, freq="D")}
        ),
        target_column="value",
        date_column="date",
        transformations=[],
        scaling_recipe="none",
    )
    alpha_resolution = resolve_forecast_alpha("ets", None, {})
    assert isinstance(alpha_resolution, AlphaResolution)

    dates = __import__("pandas").date_range("2025-01-01", periods=96, freq="D")
    future = [str(d.date()) for d in __import__("pandas").date_range(dates[-1], periods=8, freq="D")[1:]]

    try:
        compute_forecast(
            model_id="ets",
            horizon=8,
            alpha_resolution=alpha_resolution,
            final_fit=fit,
            seasonal_period=1,
            params={},
            registry=MODEL_EXECUTION_REGISTRY,
            history_values=history,
            history_labels=[str(d.date()) for d in dates],
            future_labels=future,
            oof_predictions=[],
            validated_horizon=None,
            random_state=42,
        )
    except Exception as exc:  # noqa: BLE001
        kind = type(exc).__name__
        honest = "ForecastingError" == kind
        print(f"exception kind={kind} honest_fail_closed={honest}")
        print(f"message: {exc}")
        return 0 if not honest else 1

    print("NO EXCEPTION -- неожидаемо на 0.14.x")
    return 1


if __name__ == "__main__":
    sys.exit(main())
