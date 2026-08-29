"""Безопасный preview/apply для исправления выбросов (остановка «Выбросы»
модуля «Предобработка»).

Стратегии -- перенос легаси app.py (секция "Стратегии обработки выбросов",
~строки 8313-8410: "Удаление строк", "Кэпирование" (winsorize по границам
1.5×IQR), "Замена на медиану", "Только флаг"), тот же архитектурный выбор,
что и в apps/api/missing_correction.py: стратегия применяется только к
явно выбранным колонкам, drop_rows -- объединение масок только по ним же.

Обнаружение на остатке STL-декомпозиции (опционально, см. докстринг
app/preprocessing/outliers.py -- полное обоснование, почему это НЕ
единственный и не обязательный путь) реализовано здесь, а не в
outliers.py, потому что требует date_column и знания о сессионном
контракте декомпозиции (apps/api/decomposition_data.py), тогда как
outliers.py остаётся чистым и decomposition-agnostic.

Прогноз влияния на статистики и boxplot-группы добавлены в Task 65:
production-модуль не импортирует FastAPI-приложение или тестовый framework,
поэтому остаётся безопасным leaf dependency для session router.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import pandas as pd

from app.preprocessing.decomposition import apply_decomposition
from app.preprocessing.outliers import detect_outlier_mask, profile_outliers
from apps.api.decomposition_data import _NotApplicable, _prepare_decomposable_series

STRATEGIES = {"drop_rows", "cap", "median", "flag"}


def _safe_stat(
    series: pd.Series,
    operation: Callable[[pd.Series], Any],
) -> Optional[float]:
    """Возвращает конечную статистику или None для пустого результата."""
    valid = pd.to_numeric(series, errors="coerce").dropna()
    if valid.empty:
        return None
    try:
        value = operation(valid)
    except (TypeError, ValueError, FloatingPointError):
        return None
    return float(value) if pd.notnull(value) else None


def _column_stats(series: pd.Series) -> dict[str, Optional[float]]:
    """Mean/std/median в том же контракте, что missing-correction preview."""
    return {
        "mean": _safe_stat(series, lambda values: values.mean()),
        "std": _safe_stat(series, lambda values: values.std()),
        "median": _safe_stat(series, lambda values: values.median()),
    }


def _boxplot_group(series: pd.Series) -> Optional[dict[str, float | int]]:
    valid = pd.to_numeric(series, errors="coerce").dropna()
    if valid.empty:
        return None
    return {
        "count": int(len(valid)),
        "min": float(valid.min()),
        "q1": float(valid.quantile(0.25)),
        "median": float(valid.median()),
        "q3": float(valid.quantile(0.75)),
        "max": float(valid.max()),
        "mean": float(valid.mean()),
    }


def outlier_boxplot_groups(values: pd.Series, mask: pd.Series) -> dict[str, Optional[dict]]:
    """Строит точную boxplot-сводку отдельно для выбросов и нормы.

    Маска выравнивается по индексу значений; пропуски не попадают ни в одну
    группу. Возвращаемые словари напрямую соответствуют
    ``OutlierBoxplotGroupOut``.
    """
    aligned_mask = mask.reindex(values.index, fill_value=False).fillna(False).astype(bool)
    numeric = pd.to_numeric(values, errors="coerce")
    valid = numeric.notna()
    return {
        "outliers": _boxplot_group(numeric[valid & aligned_mask]),
        "normal": _boxplot_group(numeric[valid & ~aligned_mask]),
    }


def detect_mask_on_residual(
    df: pd.DataFrame,
    column: str,
    date_column: str,
    method: str,
    param: Any = None,
) -> pd.Series:
    """Обнаруживает выбросы на остатке STL-декомпозиции выбранного ряда.

    Возвращает маску, переиндексированную на ``df.index``. Значения вне
    декомпозируемого поднабора не объявляются выбросами: у них нет остатка,
    который можно было бы проверить.
    """
    if column not in df.columns:
        raise ValueError(f"Колонка '{column}' отсутствует в датасете")
    if date_column not in df.columns:
        raise ValueError(f"Колонка-дата '{date_column}' отсутствует в датасете")

    try:
        series, period, _inferred, _label = _prepare_decomposable_series(
            df[date_column], df[column]
        )
    except _NotApplicable as exc:
        raise ValueError(
            f"Декомпозиция недоступна для этой пары колонок: {exc.reason}"
        ) from exc

    decomposition = apply_decomposition(series, method="STL", period=period)
    residual = decomposition["resid"]
    residual_mask = detect_outlier_mask(residual, method, param)

    outlier_dates = set(residual.index[residual_mask])
    aligned_dates = pd.to_datetime(df[date_column], errors="coerce")
    return aligned_dates.isin(outlier_dates)


def preview_outlier_corrections(
    df: pd.DataFrame,
    columns: list[str],
    strategy: str,
    method: str = "iqr",
    param: Any = None,
    masks_override: Optional[dict[str, pd.Series]] = None,
) -> tuple[pd.DataFrame, list[dict[str, Any]], int]:
    """Выполняет выбранную стратегию на глубокой копии DataFrame.

    ``masks_override`` позволяет session router передать маску, рассчитанную
    по STL-остатку, не дублируя выбор сырой/остаточной шкалы внутри функции.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Неподдерживаемая стратегия исправления: {strategy}")
    if not columns:
        raise ValueError("Не выбрано ни одной колонки для исправления")
    if len(columns) != len(set(columns)):
        raise ValueError("Одна колонка не может повторяться в операции")

    missing_columns = [column for column in columns if column not in df.columns]
    if missing_columns:
        raise ValueError(f"Колонка '{missing_columns[0]}' отсутствует в датасете")
    non_numeric = [
        column for column in columns
        if not pd.api.types.is_numeric_dtype(df[column])
    ]
    if non_numeric:
        raise ValueError(
            f"Колонка '{non_numeric[0]}' не числовая -- обнаружение выбросов недоступно"
        )

    result_df = df.copy(deep=True)
    masks: dict[str, pd.Series] = {}
    for column in columns:
        raw_mask = (
            masks_override[column]
            if masks_override and column in masks_override
            else detect_outlier_mask(df[column], method, param)
        )
        masks[column] = raw_mask.reindex(df.index, fill_value=False).fillna(False).astype(bool)

    rows_removed = 0
    added_columns: dict[str, Optional[str]] = {column: None for column in columns}

    if strategy == "drop_rows":
        combined_mask = pd.Series(False, index=result_df.index)
        for mask in masks.values():
            combined_mask |= mask
        rows_removed = int(combined_mask.sum())
        result_df = result_df.loc[~combined_mask].reset_index(drop=True)
    else:
        for column in columns:
            mask = masks[column]
            if not mask.any():
                continue
            result_df[column] = result_df[column].astype(float)
            if strategy == "cap":
                valid = df[column].dropna()
                q1, q3 = valid.quantile(0.25), valid.quantile(0.75)
                iqr = q3 - q1
                lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
                result_df[column] = result_df[column].clip(lower=lower, upper=upper)
            elif strategy == "median":
                median = df.loc[~mask, column].median()
                result_df.loc[mask, column] = median
            else:  # flag
                flag_column = f"{column}_outlier_flag"
                if flag_column in result_df.columns:
                    raise ValueError(f"Колонка '{flag_column}' уже существует")
                result_df[flag_column] = mask.astype(int)
                added_columns[column] = flag_column

    results: list[dict[str, Any]] = []
    for column in columns:
        outlier_count = int(masks[column].sum())
        if strategy == "flag":
            still_outliers = outlier_count
            changed_count = 0
        elif strategy == "drop_rows":
            still_outliers = 0
            changed_count = 0
        else:
            recomputed_mask = detect_outlier_mask(result_df[column], method, param)
            still_outliers = int(recomputed_mask.sum())
            changed_count = outlier_count

        results.append({
            "column": column,
            "outlier_count": outlier_count,
            "changed_count": changed_count,
            "still_outliers": still_outliers,
            "outlier_examples": [
                int(index) for index in df.index[masks[column]][:5].tolist()
            ],
            "flag_column": added_columns[column],
            "stats_before": _column_stats(df[column]),
            "stats_after": _column_stats(result_df[column]),
        })

    return result_df, results, rows_removed


def outlier_correction_profile(
    df: pd.DataFrame,
    method: str = "iqr",
    param: Any = None,
) -> list[dict[str, Any]]:
    """Тонкая обёртка профиля для preview/apply response."""
    return profile_outliers(df, method=method, param=param)
