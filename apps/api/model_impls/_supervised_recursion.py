# apps/api/model_impls/_supervised_recursion.py
"""
Общее ядро рекурсивных supervised ML-адаптеров (Task 127/128).

Извлечено из random_forest.py при подключении XGBoost (Task 128), чтобы
Tasks 128-130 (XGBoost/LightGBM/CatBoost) переиспользовали паттерн,
сертифицированный в Task 127, БЕЗ копипасты:

- ``supervised_feature_specs`` -- каузальные target-derived спеки адаптера
  (лаги 1..n_lags, rolling mean/std по окну n_lags, diff_1) с префиксом
  адаптера (нет столкновений с колонками платформенного каталога);
- ``supervised_matrix`` -- supervised train-матрица через
  ``RecursiveFeatureState`` (peek_row/push): признак в позиции p использует
  только target[:p]; warm-up дропается, known-колонки обрезаются на тот же
  warm-up -- train/serve skew рекурсивного прогнозирования устранён по
  построению (один и тот же код строит train-матрицу и будущие строки);
- ``validated_known_features`` -- fail-closed валидация regressor-канала
  Task 126/124 (симметрия train/future, длины, NaN/Inf);
- ``matrix_digest`` -- matrix_hash точной X-матрицы (canonical JSON +
  sha256, та же схема, что у FoldFeatureMatrixBuilder) для
  ``bind_feature_importance`` (oracle-защита);
- ``widen_intervals`` -- инвариант реестра lower <= point <= upper при
  любом распределении.

Сообщения об ошибках -- часть контракта тестов обоих адаптеров; менять их
нельзя без синхронного обновления test_random_forest_adapter.py и
test_xgboost_adapter.py.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from typing import Any, Mapping, Optional, Sequence

import numpy as np

from apps.api.feature_plan import (
    FeatureSpec,
    KIND_DIFFERENCE,
    KIND_LAG,
    KIND_ROLLING,
    ROLE_HISTORIC,
    RecursiveFeatureState,
)

# Допустимый диапазон глубины каузальной авторегрессии -- общий для всех
# адаптеров семейства tree_ml (см. PARAM_BOUNDS["n_lags"] каждого адаптера).
N_LAGS_BOUNDS: tuple[int, int] = (1, 32)

# Минимум usable-строк supervised-матрицы: меньше -- адаптер не обучается
# осмысленно, fold отклоняется вместо синтетического результата.
MIN_USABLE_ROWS = 8


def supervised_feature_specs(prefix: str, n_lags: int) -> dict[str, FeatureSpec]:
    """Каузальные target-derived спеки адаптера (роль=historic, Task 126).

    Имена префиксованы ``{prefix}_`` и не могут столкнуться с колонками
    платформенного каталога генерации признаков.
    """
    if not N_LAGS_BOUNDS[0] <= int(n_lags) <= N_LAGS_BOUNDS[1]:
        raise ValueError(f"n_lags={n_lags} вне bounded диапазона {N_LAGS_BOUNDS}")
    specs: dict[str, FeatureSpec] = {}
    for lag in range(1, int(n_lags) + 1):
        specs[f"{prefix}_lag_{lag}"] = FeatureSpec(
            name=f"{prefix}_lag_{lag}", kind=KIND_LAG, role=ROLE_HISTORIC, lookback=lag,
        )
    specs[f"{prefix}_roll_mean"] = FeatureSpec(
        name=f"{prefix}_roll_mean", kind=KIND_ROLLING, role=ROLE_HISTORIC,
        lookback=int(n_lags), params={"statistic": "mean"},
    )
    specs[f"{prefix}_roll_std"] = FeatureSpec(
        name=f"{prefix}_roll_std", kind=KIND_ROLLING, role=ROLE_HISTORIC,
        lookback=int(n_lags), params={"statistic": "std"},
    )
    specs[f"{prefix}_diff_1"] = FeatureSpec(
        name=f"{prefix}_diff_1", kind=KIND_DIFFERENCE, role=ROLE_HISTORIC,
        lookback=2, params={"difference_lag": 1},
    )
    return specs


def supervised_matrix(
    target: Sequence[float],
    *,
    known: Mapping[str, Sequence[float]],
    specs: Mapping[str, FeatureSpec],
    model_label: str = "",
) -> tuple[list[str], list[list[float]], list[float], int]:
    """Supervised train-матрица из каузальных historic-признаков + known-колонок.

    Строится тем же RecursiveFeatureState (peek_row/push), что и рекурсивный
    прогноз: признак в позиции p использует только target[:p] (строго до p).
    Первые max(lookback) наблюдений -- warm-up и отбрасываются; known-колонки
    обрезаются на тот же warm-up (выравненность train-строк с target).
    """
    label = f"{model_label}: " if model_label else ""
    y = [float(value) for value in target]
    if not np.isfinite(np.asarray(y, dtype=float)).all():
        raise ValueError(f"{label}target содержит NaN/Inf (fail-closed)")
    warmup = max(int(spec.lookback) for spec in specs.values())
    if len(y) - warmup < MIN_USABLE_ROWS:
        raise ValueError(
            f"{label}недостаточно истории для supervised-матрицы: "
            f"usable={max(len(y) - warmup, 0)} < {MIN_USABLE_ROWS} "
            f"(warm-up {warmup}, длина ряда {len(y)})"
        )
    state = RecursiveFeatureState(
        history=[], columns=list(specs), specs=dict(specs),
    )
    columns = [*state.columns(), *sorted(known)]
    rows: list[list[float]] = []
    target_rows: list[float] = []
    for position, value in enumerate(y):
        if len(state.history()) >= warmup:
            row = state.peek_row() + [float(known[name][position]) for name in sorted(known)]
            rows.append(row)
            target_rows.append(value)
        state.push(value)
    return columns, rows, target_rows, warmup


def validated_known_features(
    y_train: Sequence[float],
    horizon: int,
    *,
    train_features: Optional[Mapping[str, Sequence[float]]],
    future_features: Optional[Mapping[str, Sequence[float]]],
) -> dict[str, dict[str, list[float]]]:
    """Fail-closed валидация regressor-канала (тот же стандарт, что у Prophet).

    Канал либо пуст целиком, либо симметричен: одинаковые множества колонок,
    train-длина == len(y_train), future-длина == horizon, все значения
    конечны.  Любое нарушение -- ошибка fold'а.
    """
    train = dict(train_features or {})
    future = dict(future_features or {})
    if future and not train:
        raise ValueError(
            "future_features переданы без train_features: регрессоры обязаны "
            "покрывать train и future симметрично"
        )
    if train and not future:
        raise ValueError(
            "train_features переданы без future_features: модель требует "
            f"будущие значения каждого регрессора на весь horizon={horizon}"
        )
    if not train:
        return {}
    if set(train) != set(future):
        missing_in_train = sorted(set(future) - set(train))
        missing_in_future = sorted(set(train) - set(future))
        raise ValueError(
            "Наборы train_features/future_features расходятся: "
            f"нет в train: {missing_in_train}; нет в future: {missing_in_future}"
        )
    validated: dict[str, dict[str, list[float]]] = {}
    for name in sorted(train):
        validated[name] = {
            "train": _finite_column(
                name, train[name], len(y_train),
                f"train length {len(train[name])} не равна len(y_train)={len(y_train)}",
            ),
            "future": _finite_column(
                name, future[name], horizon,
                f"future length {len(future[name])} не равна horizon={horizon}",
            ),
        }
    return validated


def _finite_column(
    name: str, values: Sequence[float], expected_length: int, mismatch_label: str,
) -> list[float]:
    if len(values) != expected_length:
        raise ValueError(f"Регрессор '{name}': {mismatch_label}")
    column: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Регрессор '{name}': нечисловое значение {value!r}") from exc
        if not math.isfinite(number):
            raise ValueError(f"Регрессор '{name}': NaN/Inf запрещены (fail-closed)")
        column.append(number)
    return column


def matrix_digest(payload: Mapping[str, Any]) -> str:
    """matrix_hash точной X-матрицы -- та же схема, что у FeaturePlan
    (canonical JSON + sha256), чтобы lineage-записи были однородны."""
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def widen_intervals(
    forecast: Sequence[float],
    lower: Sequence[float],
    upper: Sequence[float],
) -> tuple[list[float], list[float]]:
    """Расширить границы до point-прогноза (инвариант реестра
    lower <= point <= upper обязан держаться и на скошенных распределениях)."""
    widened_lower: list[float] = []
    widened_upper: list[float] = []
    for point, low, high in zip(forecast, lower, upper, strict=True):
        widened_lower.append(min(float(low), float(point)))
        widened_upper.append(max(float(high), float(point)))
    return widened_lower, widened_upper
