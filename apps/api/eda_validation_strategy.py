"""Read-only план временной валидации для остановки EDA."""
from __future__ import annotations

from typing import Any, Literal

import pandas as pd

from app.data.detectors import detect_column_frequency, score_all_columns_as_date, smart_to_datetime
from apps.api.cv import ExpandingWindowCV, SlidingWindowCV


DATE_CONFIDENCE_THRESHOLD = 0.7
MIN_TRAIN_OBSERVATIONS = 20
ValidationStrategy = Literal["expanding", "sliding", "single"]


def _required(strategy: ValidationStrategy, horizon: int, n_splits: int, gap: int, train_window: int) -> int:
    if strategy == "single":
        return MIN_TRAIN_OBSERVATIONS + gap + horizon
    train_size = MIN_TRAIN_OBSERVATIONS if strategy == "expanding" else train_window
    return train_size + gap + horizon * n_splits


def _label(labels: list[str], index: int | None) -> str | None:
    return labels[index] if index is not None and 0 <= index < len(labels) else None


def _fold_out(split, labels: list[str], gap: int, offset: int = 0) -> dict[str, Any]:
    train = [index + offset for index in split.train_idx]
    test = [index + offset for index in split.test_idx]
    gap_start = train[-1] + 1 if gap else None
    gap_end = test[0] - 1 if gap else None
    return {
        "fold": split.fold + 1,
        "train_start": train[0], "train_end": train[-1], "train_size": len(train),
        "gap_start": gap_start, "gap_end": gap_end, "gap_size": gap,
        "test_start": test[0], "test_end": test[-1], "test_size": len(test),
        "train_start_label": _label(labels, train[0]), "train_end_label": _label(labels, train[-1]),
        "test_start_label": _label(labels, test[0]), "test_end_label": _label(labels, test[-1]),
    }


def build_eda_validation_strategy(
    df: pd.DataFrame,
    column: str,
    strategy: ValidationStrategy = "expanding",
    horizon: int = 12,
    n_splits: int = 5,
    gap: int = 0,
    train_window: int = 60,
) -> dict[str, Any]:
    candidates = [
        item for item in score_all_columns_as_date(df)
        if item["name"] != column and item["score"] >= DATE_CONFIDENCE_THRESHOLD
    ]
    order_source, order_column, frequency = "row_order", None, None
    order_warning: str | None = "Временная ось не определена: границы показаны в текущем порядке строк."
    comparable_duration = False
    ordered = df.reset_index(drop=True).copy()

    if candidates:
        order_column = str(candidates[0]["name"])
        dates = smart_to_datetime(df[order_column])
        order_source = "time_column"
        if dates.isna().any():
            return _not_applicable(df, column, strategy, horizon, n_splits, gap, train_window,
                                   order_source, order_column, None,
                                   f"В колонке «{order_column}» есть нераспознанные даты.")
        if dates.duplicated().any():
            return _not_applicable(df, column, strategy, horizon, n_splits, gap, train_window,
                                   order_source, order_column, None,
                                   f"В колонке «{order_column}» повторяются даты: это похоже на панельные данные; выберите одну сущность.")
        ordered = df.assign(__eda_date=dates).sort_values("__eda_date", kind="stable").reset_index(drop=True)
        frequency = detect_column_frequency(dates)["code"]
        comparable_duration = frequency is not None
        order_warning = None if frequency else (
            "Временная сетка нерегулярна: folds корректны по порядку, но одинаковый горизонт в наблюдениях "
            "не означает одинаковую календарную длительность."
        )

    numeric = pd.to_numeric(ordered[column], errors="coerce")
    missing_count = int(numeric.isna().sum())
    usable = ordered.loc[numeric.notna()].copy().reset_index(drop=True)
    n = len(usable)
    if order_column:
        label_dates = smart_to_datetime(usable[order_column])
        labels = [value.isoformat() for value in label_dates]
    else:
        labels = [str(index + 1) for index in range(n)]

    effective_splits = 1 if strategy == "single" else n_splits
    required_observations = _required(strategy, horizon, n_splits, gap, train_window)
    warnings: list[str] = []
    if order_warning:
        warnings.append(order_warning)
    if missing_count:
        warnings.append(
            f"Исключено пропусков цели: {missing_count}; горизонт и gap измеряются в доступных наблюдениях."
        )
    if n < required_observations:
        return {
            **_base(column, strategy, horizon, n_splits, effective_splits, gap, train_window,
                    n, missing_count, required_observations, order_source, order_column,
                    order_warning, frequency, comparable_duration),
            "applicable": False,
            "reason": f"Недостаточно наблюдений: нужно не менее {required_observations}, доступно {n}.",
            "initial_train_size": 0, "unused_observations": 0, "test_coverage": 0.0,
            "folds": [], "alternatives": _alternatives(n, horizon, n_splits, gap, train_window),
            "recommendation": "Уменьшите горизонт/число folds либо накопите больше истории.",
            "recommendations": ["Не сокращайте train ниже технического минимума автоматически."],
            "warnings": warnings,
        }

    if strategy == "single":
        initial_train = n - gap - horizon
        cv = ExpandingWindowCV(1, horizon, min_train_size=initial_train, step=horizon, gap=gap)
        raw_splits, offset = cv.split(n), 0
        recommendation = "Используйте этот последний интервал как финальный holdout после выбора модели; одного split недостаточно для устойчивого сравнения моделей."
    elif strategy == "sliding":
        cv = SlidingWindowCV(n_splits, train_window, horizon, step=horizon, gap=gap)
        offset = n - cv.min_samples()
        raw_splits = cv.split(cv.min_samples())
        initial_train = train_window
        recommendation = "Sliding window ограничивает обучение свежим режимом. Сопоставьте размер окна со структурными сдвигами и циклом переобучения."
    else:
        initial_train = n - gap - horizon * n_splits
        cv = ExpandingWindowCV(n_splits, horizon, min_train_size=initial_train, step=horizon, gap=gap)
        raw_splits, offset = cv.split(n), 0
        recommendation = "Expanding window использует всю доступную историю и является базовой схемой, если далёкие наблюдения остаются релевантными."

    folds = [_fold_out(split, labels, gap, offset) for split in raw_splits]
    test_indices = {index for fold in folds for index in range(fold["test_start"], fold["test_end"] + 1)}
    unused = offset if strategy == "sliding" else 0
    recommendations = [
        "Горизонт должен совпадать с реальным горизонтом эксплуатации модели.",
        "Все преобразования и отбор признаков обучайте заново внутри каждого train fold.",
    ]
    if gap:
        recommendations.append("Gap моделирует задержку доступности признаков и защищает от пограничной утечки.")
    return {
        **_base(column, strategy, horizon, n_splits, effective_splits, gap, train_window,
                n, missing_count, required_observations, order_source, order_column,
                order_warning, frequency, comparable_duration),
        "applicable": True, "reason": None, "initial_train_size": initial_train,
        "unused_observations": unused, "test_coverage": round(100 * len(test_indices) / n, 2),
        "folds": folds, "alternatives": _alternatives(n, horizon, n_splits, gap, train_window),
        "recommendation": recommendation, "recommendations": recommendations, "warnings": warnings,
    }


def _base(column, strategy, horizon, requested_splits, effective_splits, gap, train_window,
          n, missing_count, required, order_source, order_column, order_warning, frequency,
          comparable_duration) -> dict[str, Any]:
    return {
        "column": column, "strategy": strategy, "horizon": horizon,
        "requested_splits": requested_splits, "effective_splits": effective_splits,
        "gap": gap, "train_window": train_window, "min_train_observations": MIN_TRAIN_OBSERVATIONS,
        "n_observations": n, "missing_count": missing_count, "required_observations": required,
        "order_source": order_source, "order_column": order_column, "order_warning": order_warning,
        "frequency": frequency, "comparable_duration": comparable_duration,
    }


def _alternatives(n: int, horizon: int, n_splits: int, gap: int, train_window: int) -> list[dict[str, Any]]:
    labels = {
        "expanding": ("Расширяющееся окно", "Максимум истории; базовый вариант при стабильной релевантности прошлого."),
        "sliding": ("Скользящее окно", "Фиксированная свежая история; полезно при дрейфе и смене режимов."),
        "single": ("Финальный holdout", "Один честный финальный тест, но высокая дисперсия оценки."),
    }
    result = []
    for item in ("expanding", "sliding", "single"):
        required = _required(item, horizon, n_splits, gap, train_window)
        result.append({"strategy": item, "label": labels[item][0], "suitable": n >= required,
                       "required_observations": required, "reason": labels[item][1]})
    return result


def _not_applicable(df, column, strategy, horizon, n_splits, gap, train_window,
                    order_source, order_column, frequency, reason) -> dict[str, Any]:
    n = int(pd.to_numeric(df[column], errors="coerce").notna().sum())
    effective = 1 if strategy == "single" else n_splits
    required = _required(strategy, horizon, n_splits, gap, train_window)
    return {
        **_base(column, strategy, horizon, n_splits, effective, gap, train_window, n,
                len(df) - n, required, order_source, order_column, reason, frequency, False),
        "applicable": False, "reason": reason, "initial_train_size": 0,
        "unused_observations": 0, "test_coverage": 0.0, "folds": [],
        "alternatives": _alternatives(n, horizon, n_splits, gap, train_window),
        "recommendation": "Сначала сформируйте один упорядоченный временной ряд.",
        "recommendations": [], "warnings": [reason],
    }
