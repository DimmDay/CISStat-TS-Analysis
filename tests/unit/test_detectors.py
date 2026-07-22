# tests/unit/test_detectors.py
import pandas as pd
import pytest
from app.data.detectors import detect_and_convert_datetime

def test_iso_date_detection():
    """Проверяет детекцию стандартного ISO формата (YYYY-MM-DD)."""
    df = pd.DataFrame({'date': ['2020-01-01', '2020-01-02', '2020-01-03'], 'value': [1, 2, 3]})
    df_res, detected, ts_active, primary = detect_and_convert_datetime(df)
    
    assert ts_active is True
    assert primary == 'date'
    assert 'date' in detected
    assert pd.api.types.is_datetime64_any_dtype(df_res['date'])

def test_russian_keywords_and_format():
    """Проверяет детекцию по русскому ключевому слову и формату DD.MM.YYYY."""
    df = pd.DataFrame({'дата': ['01.01.2020', '02.01.2020'], 'значение': [10, 20]})
    df_res, detected, ts_active, primary = detect_and_convert_datetime(df)
    
    assert ts_active is True
    assert primary == 'дата'
    assert pd.api.types.is_datetime64_any_dtype(df_res['дата'])

def test_unix_timestamp_detection():
    """Проверяет детекцию Unix timestamp (секунды)."""
    df = pd.DataFrame({'timestamp': [1577836800, 1577923200], 'val': [1, 2]}) # 2020-01-01, 2020-01-02
    df_res, detected, ts_active, primary = detect_and_convert_datetime(df)
    
    assert ts_active is True
    assert primary == 'timestamp'
    assert pd.api.types.is_datetime64_any_dtype(df_res['timestamp'])

def test_no_date_columns():
    """Проверяет, что функция корректно работает, когда дат нет."""
    df = pd.DataFrame({'category': ['A', 'B'], 'value': [1, 2]})
    df_res, detected, ts_active, primary = detect_and_convert_datetime(df)
    
    assert ts_active is False
    assert primary is None
    assert len(detected) == 0

def test_multiple_date_columns_selects_best():
    """Проверяет, что из нескольких дат выбирается наиболее вероятная (с высоким confidence)."""
    df = pd.DataFrame({
        'date': ['2020-01-01', '2020-01-02', '2020-01-03'], # Хорошая дата
        'report_date': ['2020-01-01', '2020-01-02', '2020-01-03'], # Тоже хорошая, но 'date' короче и проще
        'value': [1, 2, 3]
    })
    df_res, detected, ts_active, primary = detect_and_convert_datetime(df)
    
    assert ts_active is True
    assert primary in ['date', 'report_date'] # Обе валидны, но одна должна быть выбрана
    assert len(detected) == 2

def test_low_confidence_rejected():
    """Проверяет, что колонка с низким confidence не признается датой."""
    df = pd.DataFrame({'date': ['not-a-date', 'also-not', '2020-01-01'], 'value': [1, 2, 3]})
    df_res, detected, ts_active, primary = detect_and_convert_datetime(df, min_confidence=0.8)
    
    # Только 1 из 3 значений распарсилось -> success_rate = 0.33 < 0.8
    assert ts_active is False
    assert primary is None

def test_original_column_names_preserved():
    """Проверяет, что оригинальные имена колонок (с пробелами, заглавными буквами) сохраняются."""
    df = pd.DataFrame({'My Date Column': ['2020-01-01', '2020-01-02'], 'Value': [1, 2]})
    df_res, detected, ts_active, primary = detect_and_convert_datetime(df)
    
    assert 'My Date Column' in df_res.columns
    assert primary == 'My Date Column'