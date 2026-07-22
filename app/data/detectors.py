# app/data/detectors.py
"""
Модуль детекции и конвертации типов данных.
Содержит функции для автоматического определения временных колонок, числовых признаков и т.д.
"""
import logging
from typing import List, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

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

    # ─ РАСШИРЕННЫЕ ПАТТЕРНЫ ДАТ ──────────────────────────────
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

    for idx, col in enumerate(df_work.columns):
        # 1. Пропускаем уже datetime
        if pd.api.types.is_datetime64_any_dtype(df_work[col]):
            if col not in detected_cols:
                detected_cols.append(col)
                if potential_date_col is None:
                    potential_date_col = col
            continue

        col_str = str(col).lower()
        check_col = any(kw in col_str for kw in TIME_KEYWORDS)

        # Первая колонка — приоритетный кандидат
        if idx == 0 and not check_col:
            check_col = True

        # Дополнительная эвристика для числовых колонок
        if not check_col and df_work[col].dtype in ['int64', 'float64', 'object']:
            sample_check = df_work[col].dropna().head(100)
            if len(sample_check) > 0:
                if sample_check.astype(str).str.match(r'^\d{4}$').mean() > 0.8:
                    check_col = True
                elif sample_check.astype(str).str.contains(r'\d{1,2}[./-]\d{1,2}[./-]\d{2,4}').mean() > 0.8:
                    check_col = True

        if not check_col:
            continue

        # 2. Сэмплирование для анализа
        sample = df_work[col].dropna()
        if len(sample) == 0:
            continue

        sample_vals = sample.head(min(500, len(sample)))
        sample_str = sample_vals.astype(str).str.strip()
        is_numeric = pd.api.types.is_numeric_dtype(sample_vals)

        best_fmt = None
        best_match_ratio = 0

        # 3. Определение формата
        if is_numeric:
            year_like = sample_vals.between(1800, 2100) & (sample_vals % 1 == 0)
            if year_like.mean() >= 0.8 and len(sample_vals[year_like]) >= 2:
                best_fmt = 'year_only'
                best_match_ratio = year_like.mean()
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
                    test_parse = pd.to_datetime(sample_vals, infer_datetime_format=True, errors='coerce')
                    success = test_parse.notna().mean()
                    if success >= min_confidence and success > best_match_ratio:
                        best_fmt = 'auto_infer'
                        best_match_ratio = success
                except Exception as e:
                    logger.warning(f"Auto-infer failed for column '{col}': {e}")

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