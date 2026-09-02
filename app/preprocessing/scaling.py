"""Чистое ядро диагностического масштабирования числовой матрицы.

Функции этого модуля намеренно не решают, на каких наблюдениях выполнять
``fit``. Остановка UI строит preview на полной истории, но сохраняет только
рецепт: production-моделирование обязано переобучать scaler внутри train-fold.
"""
from __future__ import annotations

from typing import Literal, Sequence

import numpy as np
import pandas as pd
from sklearn.preprocessing import (
    MaxAbsScaler,
    MinMaxScaler,
    QuantileTransformer,
    RobustScaler,
    StandardScaler,
)


ScalingMethod = Literal["standard", "minmax", "robust", "maxabs", "quantile"]
SCALING_METHODS = {"standard", "minmax", "robust", "maxabs", "quantile"}


def _pair(value: Sequence[float], name: str, *, percentile: bool = False) -> tuple[float, float]:
    if len(value) != 2:
        raise ValueError(f"{name} должен содержать ровно две границы")
    lower, upper = float(value[0]), float(value[1])
    if not np.isfinite([lower, upper]).all() or lower >= upper:
        raise ValueError(f"{name}: нижняя граница должна быть конечной и меньше верхней")
    if percentile and (lower < 0 or upper > 100):
        raise ValueError(f"{name} должен лежать внутри [0, 100]")
    return lower, upper


def fit_transform_scaling(
    frame: pd.DataFrame,
    columns: Sequence[str],
    method: ScalingMethod,
    *,
    feature_range: Sequence[float] = (0.0, 1.0),
    quantile_range: Sequence[float] = (25.0, 75.0),
    output_distribution: Literal["uniform", "normal"] = "normal",
    n_quantiles: int = 1000,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Fit/transform копии выбранных колонок официальным sklearn scaler.

    Это низкоуровневая вычислительная операция для preview и тестов. Возврат
    не содержит обученные массивы параметров: полный-history fit нельзя
    переносить в production/backtest как готовую модель преобразования.
    """
    selected = [str(column) for column in columns]
    if not selected:
        raise ValueError("Выберите хотя бы одну колонку для масштабирования")
    if len(selected) > 50:
        raise ValueError("За один рецепт можно выбрать не более 50 колонок")
    if len(set(selected)) != len(selected):
        raise ValueError("Список колонок содержит повтор")
    missing_columns = [column for column in selected if column not in frame.columns]
    if missing_columns:
        raise ValueError(f"Колонки отсутствуют в датасете: {', '.join(missing_columns)}")
    if method not in SCALING_METHODS:
        raise ValueError(f"Неподдерживаемый метод масштабирования: {method}")
    if len(frame) < 2:
        raise ValueError("Для масштабирования нужно минимум 2 наблюдения")

    data = frame.loc[:, selected].copy(deep=True)
    for column in selected:
        if pd.api.types.is_bool_dtype(data[column]) or not pd.api.types.is_numeric_dtype(data[column]):
            raise ValueError(f"Колонка '{column}' должна быть числовой и не boolean")
    numeric = data.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    if np.isnan(numeric).any():
        raise ValueError("Выбранные колонки содержат пропуски; сначала завершите остановку «Пропуски»")
    if not np.isfinite(numeric).all():
        raise ValueError("Выбранные колонки содержат бесконечные значения")
    for index, column in enumerate(selected):
        values = numeric[:, index]
        tolerance = 1e-12 * max(1.0, float(np.max(np.abs(values))))
        if float(np.ptp(values)) <= tolerance:
            raise ValueError(f"Колонка '{column}' константна и не несёт масштабируемой вариации")

    scaler: object
    parameters: dict[str, object]
    actual_n_quantiles: int | None = None
    if method == "standard":
        scaler = StandardScaler(with_mean=True, with_std=True)
        parameters = {"with_mean": True, "with_std": True}
    elif method == "minmax":
        bounds = _pair(feature_range, "feature_range")
        scaler = MinMaxScaler(feature_range=bounds, clip=False)
        parameters = {"feature_range": list(bounds), "clip": False}
    elif method == "robust":
        bounds = _pair(quantile_range, "quantile_range", percentile=True)
        scaler = RobustScaler(
            with_centering=True, with_scaling=True,
            quantile_range=bounds, unit_variance=False,
        )
        parameters = {
            "with_centering": True, "with_scaling": True,
            "quantile_range": list(bounds), "unit_variance": False,
        }
    elif method == "maxabs":
        scaler = MaxAbsScaler()
        parameters = {}
    else:
        if output_distribution not in {"uniform", "normal"}:
            raise ValueError("output_distribution должен быть uniform или normal")
        if not 10 <= int(n_quantiles) <= 1000:
            raise ValueError("n_quantiles должен быть от 10 до 1000")
        actual_n_quantiles = min(int(n_quantiles), len(data))
        scaler = QuantileTransformer(
            n_quantiles=actual_n_quantiles,
            output_distribution=output_distribution,
            random_state=0,
            copy=True,
        )
        parameters = {
            "n_quantiles": int(n_quantiles),
            "output_distribution": output_distribution,
            "random_state": 0,
        }

    transformed = scaler.fit_transform(numeric)  # type: ignore[union-attr]
    result = pd.DataFrame(transformed, index=data.index, columns=selected, dtype=float)
    metadata: dict[str, object] = {
        "method": method,
        "scaler_class": type(scaler).__name__,
        "parameters": parameters,
        "columns": selected,
        "fitted_on_n": len(data),
        "linear": method != "quantile",
        "fit_scope": "provided_rows",
    }
    if actual_n_quantiles is not None:
        metadata["actual_n_quantiles"] = actual_n_quantiles
    return result, metadata

