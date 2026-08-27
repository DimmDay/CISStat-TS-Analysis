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

import numpy as np
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


# ── Визуализации пропусков (перенос app.py "Визуализация пропусков",
#    ~строки 7843-7862: selectbox "Матрица пропусков" / "Тепловая карта
#    корреляции" / "Сравнение распределений (Boxplot)") ──


def missing_matrix(df: pd.DataFrame, max_bins: int = 200) -> dict[str, Any]:
    """Матрица пропусков по колонкам, забинованная по строкам.

    Легаси (px.imshow(df.isnull().T)) рисовал ОДИН пиксель на строку --
    нормально для Plotly в браузере со своим канвасом, но неприемлемо как
    JSON-полезная нагрузка при десятках тысяч строк. Вместо прореживания
    (потеряло бы короткие серии пропусков между сэмплированными точками)
    строки группируются в max_bins непрерывных смежных блоков, для каждого
    блока и каждой колонки считается ДОЛЯ пропущенных значений (0..1) --
    короткий контигуальный провал внутри блока по-прежнему поднимает его
    заливку выше нуля, а не исчезает между двумя случайно выбранными
    строками, как было бы при простом прореживании.
    """
    total_rows = len(df)
    columns = [str(c) for c in df.columns]
    if total_rows == 0 or not columns:
        return {"columns": columns, "bins": [], "rows_per_bin": 0, "total_rows": total_rows}

    null_mask = df.isnull()
    n_bins = min(max_bins, total_rows)
    # np.array_split распределяет остаток по первым бинам -- бины отличаются
    # не более чем на одну строку, не только "последний бин короче".
    bin_row_indices = np.array_split(np.arange(total_rows), n_bins)
    bins: list[dict[str, Any]] = []
    for bin_idx, row_positions in enumerate(bin_row_indices):
        if len(row_positions) == 0:
            continue
        chunk = null_mask.iloc[row_positions]
        bins.append({
            "bin_index": bin_idx,
            "row_start": int(df.index[row_positions[0]]) if total_rows else 0,
            "row_end": int(df.index[row_positions[-1]]) if total_rows else 0,
            "row_count": int(len(row_positions)),
            "missing_share": {
                column: round(float(chunk[col].mean()), 4)
                for column, col in zip(columns, df.columns)
            },
        })
    return {
        "columns": columns,
        "bins": bins,
        "rows_per_bin": int(round(total_rows / max(len(bins), 1))),
        "total_rows": total_rows,
    }


def missing_correlation(df: pd.DataFrame) -> dict[str, Any]:
    """Корреляция индикаторов пропуска между колонками (nullity correlation)
    -- перенос df.isnull().astype(int).corr() из легаси. Диагностирует MAR:
    если пропуск в колонке A систематически совпадает с пропуском в B
    (корреляция → 1), это одно совместное событие пропуска (например, оба
    поля пишет один и тот же отказавший датчик), а не два независимых.

    Колонки без вариативности пропуска (0% или 100% пропусков -- корреляция
    математически не определена, pandas вернул бы NaN) исключаются из
    матрицы, а не подставляются нулём -- ноль означал бы "доказанно нет
    связи", что для неопределённого случая неверно.
    """
    null_indicator = df.isnull().astype(int)
    varying_columns = [c for c in null_indicator.columns if null_indicator[c].nunique() > 1]
    if len(varying_columns) < 2:
        return {"columns": [], "matrix": []}

    corr = null_indicator[varying_columns].corr()
    columns = [str(c) for c in varying_columns]
    matrix = [
        [round(float(corr.iloc[i, j]), 4) if pd.notnull(corr.iloc[i, j]) else None for j in range(len(varying_columns))]
        for i in range(len(varying_columns))
    ]
    return {"columns": columns, "matrix": matrix}


def _five_number_summary(series: pd.Series) -> Optional[dict[str, float]]:
    valid = series.dropna()
    if valid.empty:
        return None
    return {
        "count": int(valid.shape[0]),
        "min": float(valid.min()),
        "q1": float(valid.quantile(0.25)),
        "median": float(valid.median()),
        "q3": float(valid.quantile(0.75)),
        "max": float(valid.max()),
        "mean": float(valid.mean()),
    }


def missing_distribution_comparison(
    df: pd.DataFrame, value_column: str, indicator_column: str
) -> dict[str, Any]:
    """Boxplot-сводка «влияет ли пропуск в indicator_column на распределение
    value_column» -- перенос px.box(df, x='Has_Miss', y=col_box) из легаси,
    но вместо сырых точек (которые пришлось бы гонять по сети) возвращается
    только пятичисловая сводка на группу -- этого достаточно для отрисовки
    box-and-whiskers на фронтенде и не тянет весь датасет в ответ API.

    Если распределение value_column заметно отличается между "пропуск
    есть"/"пропуска нет" по indicator_column -- это диагностика MNAR/MAR:
    пропуск в indicator_column НЕ является полностью случайным относительно
    value_column, и заполнение медианой/средним может сместить оценки.
    """
    if value_column not in df.columns:
        raise ValueError(f"Колонка '{value_column}' отсутствует в датасете")
    if indicator_column not in df.columns:
        raise ValueError(f"Колонка '{indicator_column}' отсутствует в датасете")
    if value_column == indicator_column:
        raise ValueError("Колонка сравнения и колонка-индикатор должны различаться")
    if not pd.api.types.is_numeric_dtype(df[value_column]):
        raise ValueError(f"Колонка '{value_column}' должна быть числовой для Boxplot")

    indicator_mask = df[indicator_column].isnull()
    with_missing = _five_number_summary(df.loc[indicator_mask, value_column])
    without_missing = _five_number_summary(df.loc[~indicator_mask, value_column])
    return {
        "value_column": value_column,
        "indicator_column": indicator_column,
        "with_missing": with_missing,
        "without_missing": without_missing,
    }
