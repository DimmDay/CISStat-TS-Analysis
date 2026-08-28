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
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from app.preprocessing.decomposition import apply_decomposition
from app.preprocessing.outliers import detect_outlier_mask, profile_outliers
from apps.api.decomposition_data import _NotApplicable, _prepare_decomposable_series

STRATEGIES = {"drop_rows", "cap", "median", "flag"}


def detect_mask_on_residual(
    df: pd.DataFrame,
    column: str,
    date_column: str,
    method: str,
    param: Any = None,
) -> pd.Series:
    """Обнаруживает выбросы НЕ на сырых значениях column, а на остатке
    STL-декомпозиции пары (date_column, column) -- см. позицию в
    app/preprocessing/outliers.py: это ОПЦИЯ мастера, доступная только
    когда декомпозиция для конкретной пары колонок применима (тот же
    гейт _prepare_decomposable_series, что и у бейджей/графика
    декомпозиции -- честно "неприменимо", если частота нерегулярна или
    датасет панельный).

    Возвращает маску, переиндексированную на df.index (значения вне
    декомпозируемого поднабора -- например, строки с пропуском в
    date_column -- считаются НЕ выбросами: у них попросту нет остатка).
    """
    if column not in df.columns:
        raise ValueError(f"Колонка '{column}' отсутствует в датасете")
    if date_column not in df.columns:
        raise ValueError(f"Колонка-дата '{date_column}' отсутствует в датасете")

    try:
        series, period, _inferred, _label = _prepare_decomposable_series(df[date_column], df[column])
    except _NotApplicable as ex:
        raise ValueError(f"Декомпозиция недоступна для этой пары колонок: {ex.reason}") from ex

    decomposition = apply_decomposition(series, method="STL", period=period)
    resid = decomposition["resid"]
    resid_outlier_mask = detect_outlier_mask(resid, method, param)

    # resid проиндексирован по датам (после сортировки/дедупликации в
    # _prepare_decomposable_series), а не по исходным позициям строк --
    # сопоставляем обратно через дату, а не через позицию.
    outlier_dates = set(resid.index[resid_outlier_mask])
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

    masks_override -- если задан, использует ГОТОВЫЕ маски по колонкам
    (например, посчитанные detect_mask_on_residual) вместо пересчёта
    method/param на сырых значениях -- так preview/apply не дублируют
    логику выбора "сырые значения или остаток", это делает вызывающий
    роут один раз.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Неподдерживаемая стратегия исправления: {strategy}")
    if not columns:
        raise ValueError("Не выбрано ни одной колонки для исправления")
    if len(columns) != len(set(columns)):
        raise ValueError("Одна колонка не может повторяться в операции")

    missing_columns = [c for c in columns if c not in df.columns]
    if missing_columns:
        raise ValueError(f"Колонка '{missing_columns[0]}' отсутствует в датасете")
    non_numeric = [c for c in columns if not pd.api.types.is_numeric_dtype(df[c])]
    if non_numeric:
        raise ValueError(f"Колонка '{non_numeric[0]}' не числовая -- обнаружение выбросов недоступно")

    result_df = df.copy(deep=True)
    masks: dict[str, pd.Series] = {}
    for column in columns:
        mask = masks_override[column] if masks_override and column in masks_override else detect_outlier_mask(df[column], method, param)
        masks[column] = mask

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
            recomputed_mask = detect_outlier_mask(result_df[column], method, param) if column in result_df.columns else pd.Series(dtype=bool)
            still_outliers = int(recomputed_mask.sum())
            changed_count = outlier_count
        results.append({
            "column": column,
            "outlier_count": outlier_count,
            "changed_count": changed_count,
            "still_outliers": still_outliers,
            "outlier_examples": [int(i) for i in df.index[masks[column]][:5].tolist()],
            "flag_column": added_columns[column],
        })

    return result_df, results, rows_removed


def outlier_correction_profile(df: pd.DataFrame, method: str = "iqr", param: Any = None) -> list[dict[str, Any]]:
    """Тонкая обёртка над profile_outliers для переиспользования в ответе
    /dataset/outlier-corrections (профиль после preview/apply)."""
    return profile_outliers(df, method=method, param=param)
