# app/preprocessing/missing.py
"""Чистое профилирование пропусков для остановки степпера «Пропуски»
(модуль «Предобработка», packages/ui/components/TsAnalysisPreprocessing.tsx).

Один источник истины для трёх потребителей -- стейт степпера (пройдено/
найдены проблемы), обзор (PreprocessingMissingOverview) и мастер исправления
(PreprocessingMissingPipeline, apps/api/missing_correction.py) -- та же
дисциплина, что и profile_ranges/profile_uniqueness в validation/engine.py:
один profile_missing(df) вместо нескольких независимых реализаций подсчёта.

Признак/рекомендация переносят эвристику из легаси app.py (секция "Проверка
на пропуски", col_stats-цикл): пустая колонка -- "Чисто"; >50% пропусков --
"Обработать столбец"; категориальная -- "Заполнить модой"; <5% пропусков --
"Обработать строки"; иначе -- "Заполнить медианой". Здесь это
recommended_strategy со значениями из STRATEGIES apps/api/missing_correction.py,
чтобы фронтенд мог сразу предзаполнить мастер рекомендованной стратегией.
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd

# Максимум примеров индексов строк с пропуском на колонку -- согласовано
# с тем же лимитом, что invalid_examples в profile_ranges (5).
_MAX_EXAMPLES = 5


def _semantic_class(series: pd.Series) -> str:
    """Грубая семантическая классификация -- аналог col_types в app.py,
    но без внешних побочных эффектов (не трогает st.session_state)."""
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    if isinstance(series.dtype, pd.CategoricalDtype):
        return "categorical"
    return "text"


def _recommend_strategy(pct_missing: float, semantic: str) -> str:
    """Переносит рекомендательную эвристику из app.py (строки ~7779-7787)
    один в один, но возвращает machine-readable ключ STRATEGIES вместо
    эмодзи-строки для UI."""
    if pct_missing == 0:
        return "none"
    if pct_missing > 50:
        return "drop_rows"  # "Обработать столбец" в легаси -- на практике
        # колонку с >50% пропусков разумнее просмотреть вручную, но как
        # безопасная авто-рекомендация ближе всего "удалить затронутые строки"
    if semantic in ("categorical", "text"):
        return "median_mode"
    if pct_missing < 5:
        return "drop_rows"
    return "median_mode"


def profile_missing(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Полный профиль пропусков по каждой колонке датасета, включая 0.

    Возвращает список по всем колонкам (не только с нарушениями) -- как
    profile_ranges/profile_uniqueness: степпер и обзор должны честно
    показать "проверка пройдена" даже когда пропусков нет, а не молчание.
    """
    profiles: list[dict[str, Any]] = []
    total_rows = len(df)
    for column in df.columns:
        series = df[column]
        missing_mask = series.isnull()
        missing_count = int(missing_mask.sum())
        non_missing_count = total_rows - missing_count
        missing_pct = (missing_count / total_rows * 100) if total_rows else None
        semantic = _semantic_class(series)
        examples = [int(i) for i in df.index[missing_mask][:_MAX_EXAMPLES].tolist()]
        profiles.append({
            "column": str(column),
            "dtype": str(series.dtype),
            "semantic": semantic,
            "total_count": total_rows,
            "missing_count": missing_count,
            "non_missing_count": non_missing_count,
            "missing_pct": round(missing_pct, 2) if missing_pct is not None else None,
            "recommended_strategy": _recommend_strategy(missing_pct or 0.0, semantic),
            "missing_examples": examples,
        })
    return profiles


def missing_summary(df: pd.DataFrame) -> dict[str, Any]:
    """Сводка по датасету в целом -- переиспользует ту же информацию,
    что validation.missing.analyze_missing()["summary"], но без
    expert_list/critical_alerts (тот функционал остаётся в модуле
    «Валидация» -- см. validation/missing.py, экспертный режим не
    дублируется здесь для остановки «Предобработки»)."""
    total_rows = len(df)
    total_cells = df.size
    total_missing = int(df.isnull().sum().sum())
    rows_with_missing = int(df.isnull().any(axis=1).sum()) if total_rows else 0
    empty_rows = int(df.isnull().all(axis=1).sum()) if total_rows else 0
    return {
        "total_rows": total_rows,
        "total_columns": int(df.shape[1]),
        "total_missing": total_missing,
        "missing_rate_pct": round((total_missing / total_cells) * 100, 2) if total_cells else None,
        "rows_with_missing": rows_with_missing,
        "rows_with_missing_pct": round((rows_with_missing / total_rows) * 100, 2) if total_rows else None,
        "empty_rows": empty_rows,
    }


def missing_per_row_histogram(df: pd.DataFrame, max_buckets: int = 20) -> list[dict[str, int]]:
    """Распределение количества пропусков в строке -- данные для обзорного
    графика (аналог fig_hist в app.py, "Распределение пропусков по строкам"),
    возвращены как обычные числа для JSON, без построения самого графика
    (рендер -- забота фронтенда)."""
    if df.empty:
        return []
    per_row = df.isnull().sum(axis=1)
    per_row = per_row[per_row > 0]
    if per_row.empty:
        return []
    counts = per_row.value_counts().sort_index()
    if len(counts) > max_buckets:
        counts = counts.iloc[:max_buckets]
    return [{"missing_in_row": int(k), "row_count": int(v)} for k, v in counts.items()]
