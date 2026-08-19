# app/data/detectors.py
"""
Модуль детекции и конвертации типов данных.
Содержит функции для автоматического определения временных колонок, числовых признаков и т.д.
"""
import logging
from typing import List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# ─ РАСШИРЕННЫЕ ПАТТЕРНЫ ДАТ (уровень модуля -- переиспользуются и
# detect_and_convert_datetime, и score_all_columns_as_date ниже, чтобы
# не дублировать таблицы паттернов/ключевых слов, см. docs/
# MIGRATION_ARCHITECTURE.md §7.2) ──────────────────────────────
DATE_PATTERNS = [
    (r'^\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}', 'iso_datetime'),
    (r'^\d{4}-\d{2}-\d{2}$', 'iso_date'),
    (r'^\d{2}\.\d{2}\.\d{4}$', 'dd.mm.yyyy'),
    (r'^\d{2}/\d{2}/\d{4}$', 'dd/mm/yyyy'),
    (r'^\d{4}/\d{2}/\d{2}$', 'yyyy/mm/dd'),
    (r'^\d{4}-\d{2}$', 'yyyy-mm'),
    (r'^\d{4}\.\d{2}$', 'yyyy.mm'),
    (r'^\d{2}\.\d{4}$', 'mm.yyyy'),
    (r'^\d{1,2}/\d{4}$', 'm/yyyy'),
    (r'^\d{1,2}-\d{4}$', 'm-yyyy'),
    (r'^\d{1,2}/\d{1,2}/\d{4}$', 'us_slash_flexible'),
    (r'^\d{1,2}-\d{1,2}-\d{4}$', 'us_dash_flexible'),
    (r'^\d{1,2}\.\d{1,2}\.\d{4}$', 'eu_dot_flexible'),
    (r'^\d{4}$', 'year_only'),
    (r'^\d{10}$', 'unix_s'),
    (r'^\d{13}$', 'unix_ms'),
]

# ── РАСШИРЕННЫЕ КЛЮЧЕВЫЕ СЛОВА ───────────────────────────
TIME_KEYWORDS = [
    'date', 'time', 'datetime', 'timestamp', 'year', 'month', 'day', 'period',
    'quarter', 'week', 'hour', 'minute', 'second', 'start', 'end', 'begin', 'finish',
    'report_date', 'reporting', 'fiscal', 'calendar', 'observation', 'record_date',
    'дата', 'время', 'год', 'месяц', 'день', 'период', 'квартал', 'неделя',
    'час', 'минута', 'секунда', 'отчетный', 'отчётный', 'начало', 'конец',
    'jahr', 'année', 'ano', 'anno', 'fecha', 'data', 'datum', 'dat', 'date_',
    'year_', 'yr', 'y_', 'mon', 'm_', 'd_', 'period_', 'time_',
    'reference_year', 'ref_year', 'report_year', 'data_year', 'observation_year'
]


def _score_column_as_date(idx: int, col: str, series: pd.Series, min_confidence: float = 0.7) -> tuple[Optional[str], float]:
    """Оценивает ОДНУ колонку на предмет "похожа ли на дату по содержимому"
    -- ядро скоринга, общее для detect_and_convert_datetime (которая
    дополнительно конвертирует df) и score_all_columns_as_date (которая
    только оценивает, без мутации df, для ранжированного списка
    кандидатов на фронте). Возвращает (best_fmt, best_match_ratio) --
    best_fmt=None, если колонка даже не прошла keyword/pattern-фильтр
    (check_col=False) -- в этом случае вызывающий код не должен
    предлагать её как кандидата вообще, не просто с низким score.

    idx -- позиция колонки: первая колонка в файле получает приоритет
    (check_col=True без keyword) -- тот же эвристика, что и в оригинале
    (частый паттерн: дата -- первая колонка в CSV, даже без "date" в имени).

    min_confidence -- порог, ниже которого запускается auto_infer
    fallback (pd.to_datetime без явного паттерна) -- ДОЛЖЕН совпадать с
    min_confidence вызывающей detect_and_convert_datetime, иначе
    поведение для нестандартных порогов (см. tests/unit/test_detectors.py::
    test_low_confidence_rejected, min_confidence=0.8) может разойтись."""
    col_str = str(col).lower()
    check_col = any(kw in col_str for kw in TIME_KEYWORDS)

    if idx == 0 and not check_col:
        check_col = True

    if not check_col and series.dtype in ['int64', 'float64', 'object']:
        sample_check = series.dropna().head(100)
        if len(sample_check) > 0:
            if sample_check.astype(str).str.match(r'^\d{4}$').mean() > 0.8:
                check_col = True
            elif sample_check.astype(str).str.contains(r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}').mean() > 0.8:
                check_col = True

    if not check_col:
        return None, 0.0

    sample = series.dropna()
    if len(sample) == 0:
        return None, 0.0

    sample_vals = sample.head(min(500, len(sample)))
    sample_str = sample_vals.astype(str).str.strip()
    is_numeric = pd.api.types.is_numeric_dtype(sample_vals)

    best_fmt = None
    best_match_ratio = 0.0

    if is_numeric:
        year_like = sample_vals.between(1800, 2100) & (sample_vals % 1 == 0)
        if year_like.mean() >= 0.8 and len(sample_vals[year_like]) >= 2:
            best_fmt = 'year_only'
            best_match_ratio = float(year_like.mean())
        elif sample_vals.min() > 1e9:
            best_fmt = 'unix_s' if sample_vals.max() < 1e12 else 'unix_ms'
            best_match_ratio = 1.0
    else:
        for pattern, fmt_name in DATE_PATTERNS:
            match_ratio = sample_str.str.match(pattern, case=False).mean()
            if match_ratio > best_match_ratio:
                best_match_ratio = match_ratio
                best_fmt = fmt_name

        if best_match_ratio < min_confidence:
            try:
                # Примечание: infer_datetime_format устарел в pandas 2.0+,
                # но оставлен для совместимости с legacy-поведением
                # (сохраняем точное поведение detect_and_convert_datetime).
                test_parse = pd.to_datetime(sample_vals, infer_datetime_format=True, errors='coerce')
                success = test_parse.notna().mean()
                if success >= min_confidence and success > best_match_ratio:
                    best_fmt = 'auto_infer'
                    best_match_ratio = float(success)
            except Exception as e:
                logger.warning(f"Auto-infer failed for column '{col}': {e}")

    return best_fmt, best_match_ratio


def score_all_columns_as_date(df: pd.DataFrame) -> list[dict]:
    """Возвращает РЕАЛЬНЫЙ (не позиционный) ранжированный список
    кандидатов в date-колонку для ВСЕХ колонок датасета -- адаптер для
    контракта фронтенда {selected, confidence, candidates: [{name, score}]}
    (см. TsAnalysisUpload.tsx, apps/api/upload_common.py -- комментарий
    "detect_and_convert_datetime уже есть, но не возвращает эту форму").

    В отличие от detect_and_convert_datetime: НЕ мутирует df, НЕ требует
    порога min_confidence (возвращает ВСЕ колонки с их реальным score,
    0.0 для явно непохожих -- сортировка и порог отсечения на стороне
    вызывающего кода/фронта). Использует ТОТ ЖЕ _score_column_as_date,
    что и detect_and_convert_datetime -- не отдельная копия regex/keyword
    таблиц (иначе они неизбежно разойдутся со временем).

    Возвращает [{"name": str, "score": float 0..1}], отсортировано по
    score убыв. Колонки, не прошедшие даже keyword/pattern-фильтр
    (best_fmt is None) -- score=0.0, а НЕ исключаются из списка: фронт
    решает, сколько кандидатов показывать (например, только score>0.3).
    """
    results = []
    for idx, col in enumerate(df.columns):
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            results.append({"name": str(col), "score": 1.0})
            continue
        _fmt, score = _score_column_as_date(idx, col, df[col])
        results.append({"name": str(col), "score": round(float(score), 4)})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


def detect_and_convert_datetime(
    df: pd.DataFrame, 
    min_confidence: float = 0.7
) -> Tuple[pd.DataFrame, List[str], bool, Optional[str]]:
    """
    Ищет и конвертирует временные колонки в DataFrame.
    
    Алгоритм:
    1. Нормализует имена колонок для поиска ключевых слов.
    2. Проверяет каждую колонку на соответствие паттернам дат (regex) или ключевым словам.
    3. Пытается конвертировать подходящие колонки в datetime.
    4. Выбирает наиболее вероятную временную колонку (primary_date_col) на основе confidence.
    5. Восстанавливает оригинальные имена колонок.
    
    Args:
        df: Исходный DataFrame.
        min_confidence: Минимальный порог уверенности (0.0-1.0) для признания колонки датой.
        
    Returns:
        Tuple containing:
            - df_work: DataFrame с конвертированными временными колонками (оригинальные имена сохранены).
            - detected_cols: Список названий колонок, распознанных как даты.
            - ts_active: True, если найдена хотя бы одна временная колонка.
            - potential_date_col: Название наиболее вероятной главной временной колонки (или None).
    """
    df_work = df.copy()
    original_columns = df_work.columns.tolist()
    
    # Нормализация имён для поиска ключевых слов
    df_work.columns = [str(c).strip().lower().replace(' ', '_').replace('-', '_').replace('.', '_') for c in df_work.columns]

    detected_cols = []
    potential_date_col = None
    max_confidence = 0

    for idx, col in enumerate(df_work.columns):
        # 1. Пропускаем уже datetime
        if pd.api.types.is_datetime64_any_dtype(df_work[col]):
            if col not in detected_cols:
                detected_cols.append(col)
                if potential_date_col is None:
                    potential_date_col = col
            continue

        # 2-3. Скоринг колонки (keyword/pattern-фильтр + определение формата)
        # -- вынесено в _score_column_as_date, общий с score_all_columns_as_date.
        best_fmt, best_match_ratio = _score_column_as_date(idx, col, df_work[col], min_confidence)
        if best_fmt is None:
            continue

        sample = df_work[col].dropna()
        sample_vals = sample.head(min(500, len(sample)))

        # 4. Конвертация
        if best_fmt and best_match_ratio >= min_confidence:
            try:
                converted = None

                if best_fmt == 'year_only':
                    converted = pd.to_datetime(sample_vals.astype(int).astype(str), format='%Y', errors='coerce')
                elif best_fmt == 'unix_s':
                    converted = pd.to_datetime(sample_vals, unit='s', errors='coerce')
                elif best_fmt == 'unix_ms':
                    converted = pd.to_datetime(sample_vals, unit='ms', errors='coerce')
                elif best_fmt == 'auto_infer':
                    converted = pd.to_datetime(sample_vals, infer_datetime_format=True, errors='coerce')
                else:
                    converted = pd.to_datetime(sample_vals, format='mixed', errors='coerce')

                success_rate = converted.notna().mean()

                if success_rate >= min_confidence:
                    if best_fmt == 'year_only':
                        df_work[col] = pd.to_datetime(df_work[col].astype(float).astype(int).astype(str), format='%Y', errors='coerce')
                    elif best_fmt in ['unix_s', 'unix_ms']:
                        unit = 's' if best_fmt == 'unix_s' else 'ms'
                        df_work[col] = pd.to_datetime(df_work[col], unit=unit, errors='coerce')
                    elif best_fmt == 'auto_infer':
                        df_work[col] = pd.to_datetime(df_work[col], infer_datetime_format=True, errors='coerce')
                    else:
                        df_work[col] = pd.to_datetime(df_work[col], format='mixed', errors='coerce')

                    detected_cols.append(col)

                    fill_rate = df_work[col].notna().sum() / max(len(df_work[col]), 1)
                    confidence = success_rate * fill_rate

                    if confidence > max_confidence:
                        max_confidence = confidence
                        potential_date_col = col

            except Exception as e:
                logger.warning(f"Conversion failed for column '{col}' with format '{best_fmt}': {e}")

    # 5. Восстановление оригинальных имён колонок
    rename_map = {}
    for orig_col, current_col in zip(original_columns, df_work.columns):
        if current_col in detected_cols:
            rename_map[current_col] = orig_col
    
    if rename_map:
        df_work = df_work.rename(columns=rename_map)
        detected_cols = [rename_map.get(c, c) for c in detected_cols]
        if potential_date_col in rename_map:
            potential_date_col = rename_map[potential_date_col]

    ts_active = len(detected_cols) > 0
    
    return df_work, detected_cols, ts_active, potential_date_col


def detect_panel_group_column(df: pd.DataFrame, date_col: str) -> Optional[str]:
    """
    Определяет группирующую колонку для панельных данных.
    
    Args:
        df: DataFrame с данными
        date_col: Название колонки с датами
    
    Returns:
        Название группирующей колонки или None, если не найдена
    
    Note:
        Критерии: колонка не является датой, имеет категориальный тип,
        содержит от 2 до 99 уникальных значений.
    """
    for c in df.columns:
        if c != date_col and df[c].dtype in ['object', 'string', 'category']:
            n_unique = df[c].nunique()
            if 1 < n_unique < 100:
                return c
    return None


def score_all_columns_as_entity_group(df: pd.DataFrame, date_col: Optional[str] = None) -> list[dict]:
    """Ранжированный список кандидатов в группирующую (entity/panel)
    колонку -- тот же адаптер-принцип, что и score_all_columns_as_date:
    ТЕ ЖЕ критерии, что и в detect_panel_group_column (категориальный
    dtype + 1 < nunique < 100), но для ВСЕХ колонок, не только первого
    совпадения -- фронт получает реальный, не позиционный список.

    score здесь БИНАРНЫЙ (1.0 / 0.0) -- в отличие от score_all_columns_as_date
    (непрерывный regex/keyword score), т.к. detect_panel_group_column
    сама не ранжирует кандидатов по "силе" совпадения, только фильтрует
    по dtype+nunique. Все прошедшие фильтр колонки равноценны с точки
    зрения этого критерия -- искусственная непрерывная шкала здесь
    добавила бы ложную точность, которой нет в исходной логике."""
    results = []
    for c in df.columns:
        if c == date_col:
            continue
        if df[c].dtype in ['object', 'string', 'category']:
            n_unique = df[c].nunique()
            if 1 < n_unique < 100:
                results.append({"name": str(c), "score": 1.0})
                continue
        results.append({"name": str(c), "score": 0.0})
    return results