# validation/text_quality.py
import pandas as pd
from typing import Dict, Any, Tuple, List

def compute_text_violations(
    df: pd.DataFrame, 
    col: str, 
    rules: Dict[str, Any]
) -> Tuple[pd.Series, Dict[str, Any]]:
    """
    Вычисляет нарушения качества текста (длина, спецсимволы, паттерны).
    
    Args:
        df: Исходный DataFrame.
        col: Имя текстовой колонки.
        rules: Словарь правил (например, {'max_length': 100, 'allow_special_chars': False}).
        
    Returns:
        Tuple из (mask_violations, dict с деталями нарушений).
    """
    # TODO: Перенести тело из legacy _compute_text_violations (строки ~7299-7485)
    # ВАЖНО: Использовать safe_stat из app.core.utils, если там считается средняя длина и т.д.
    raise NotImplementedError("Ожидается перенос из app.py")


def apply_text_strategy(
    df: pd.DataFrame, 
    col: str, 
    strategy: str, 
    params: Dict[str, Any] = None
) -> pd.DataFrame:
    """
    Применяет стратегию очистки текста (lowercase, strip, remove_special_chars и т.д.).
    
    Args:
        df: DataFrame с нарушениями.
        col: Имя колонки.
        strategy: Название стратегии.
        params: Доп. параметры стратегии.
        
    Returns:
        DataFrame с примененной стратегией (копия, оригинал не мутируется).
    """
    # TODO: Перенести тело из legacy _apply_text_strategy (строки ~7486-7557)
    raise NotImplementedError("Ожидается перенос из app.py")


# validation/text_quality.py
"""
Модуль для проверки качества текстовых данных.
Часть Data Quality Dashboard (C.3 в EXTRACTION_PLAN.md).
"""
import pandas as pd
from typing import List, Dict, Any


def compute_text_violations(df_to_check: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Вычисляет нарушения качества текста для DataFrame.
    
    Проверяет три типа нарушений:
    1. Garbage — управляющие символы и Unicode replacement character
    2. Short — пустые строки после strip()
    3. Long — строки длиннее 500 символов
    
    Args:
        df_to_check: DataFrame для проверки
        
    Returns:
        Список словарей с информацией о нарушениях для каждой текстовой колонки.
        Каждый словарь содержит:
        - column: имя колонки
        - count: общее количество нарушений
        - mask: pandas Series с булевой маской нарушений
        - garbage_count: количество мусорных символов
        - short_count: количество пустых строк
        - long_count: количество длинных строк
        - sample_values: первые 3 примера нарушений
        
    Architectural invariants:
        - Явная адресация данных: принимает df явно через аргумент
        - Нет st.* вызовов (чистая бизнес-логика)
        - Нет побочных эффектов
    """
    violations = []
    text_cols = df_to_check.select_dtypes(include=['object', 'string']).columns.tolist()
    
    for col in text_cols:
        # ИСПРАВЛЕНИЕ: Обычная строка (не raw), чтобы \ufffd интерпретировался
        garbage_mask = df_to_check[col].astype(str).str.contains(
            '[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]', na=False, regex=True
        )
        short_mask = df_to_check[col].astype(str).str.strip().str.len() < 1
        long_mask = df_to_check[col].astype(str).str.len() > 500
        combined = garbage_mask | short_mask | long_mask
        
        if combined.any():
            sample_values = df_to_check.loc[combined, col].head(3).tolist()
            violations.append({
                'column': col,
                'count': int(combined.sum()),
                'mask': combined,
                'garbage_count': int(garbage_mask.sum()),
                'short_count': int(short_mask.sum()),
                'long_count': int(long_mask.sum()),
                'sample_values': sample_values
            })
    
    return violations


# validation/text_quality.py (дополнение)
import pandas as pd
import numpy as np
from typing import List, Dict, Any


def apply_text_strategy(
    df_input: pd.DataFrame,
    text_violations: List[Dict[str, Any]],
    strategy: str
) -> pd.DataFrame:
    """
    Применяет стратегию обработки текстовых нарушений.
    
    Args:
        df_input: Исходный DataFrame.
        text_violations: Список нарушений от compute_text_violations.
        strategy: Название стратегии:
            - "Очистить" — lowercase, strip, удаление спецсимволов
            - "Удалить" — удаление строк с нарушениями
            - "NaN" — замена нарушений на NaN
            - "Неизвестно" — замена нарушений на строку "Неизвестно"
            - "флагом" — добавление колонки с булевой маской
        
    Returns:
        DataFrame с применённой стратегией (копия, оригинал не мутируется).
        
    Architectural invariants:
        - Явная адресация данных: принимает df и violations явно через аргументы
        - Нет st.* вызовов (чистая бизнес-логика)
        - Нет побочных эффектов (оригинал не мутируется)
    """
    df_result = df_input.copy()
    
    if "Очистить" in strategy:
        for v in text_violations:
            col = v['column']
            if col in df_result.columns:
                # Упрощённый regex (без r-префикса не нужен, т.к. нет \ufffd)
                df_result.loc[v['mask'], col] = (
                    df_result.loc[v['mask'], col]
                    .astype(str)
                    .str.strip()
                    .str.lower()
                    .str.replace(r'[^\w\s\-]', '', regex=True)
                    .str.replace(r'\s+', ' ', regex=True)
                    .str.strip()
                )
                
                # Обрабатываем пустые строки после очистки
                empty_after = df_result[col].astype(str).str.strip() == ''
                if empty_after.any():
                    df_result.loc[empty_after, col] = np.nan
                    
    elif "Удалить" in strategy:
        # Объединяем маски всех нарушений
        combined_mask = pd.Series(False, index=df_result.index)
        for v in text_violations:
            if v['column'] in df_result.columns:
                combined_mask = combined_mask | v['mask']
        df_result = df_result[~combined_mask].reset_index(drop=True)
        
    elif "NaN" in strategy:
        for v in text_violations:
            col = v['column']
            if col in df_result.columns:
                df_result.loc[v['mask'], col] = np.nan
                
    elif "Неизвестно" in strategy:
        for v in text_violations:
            col = v['column']
            if col in df_result.columns:
                df_result.loc[v['mask'], col] = "Неизвестно"
                
    elif "флагом" in strategy:
        # Реализация стратегии "только флаг"
        for v in text_violations:
            col = v['column']
            if col in df_result.columns:
                flag_col = f"{col}_text_valid"
                df_result[flag_col] = ~v['mask']
    
    return df_result