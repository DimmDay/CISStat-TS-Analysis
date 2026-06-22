# tests/snapshot/test_legacy_passport.py
import pytest
import pandas as pd
import numpy as np
from pathlib import Path

# Импортируем "грязный" легаси-код
from tests.legacy_wrappers.legacy_metrics import calculate_ts_passport

@pytest.fixture
def golden_ts_series():
    """Загружает эталонный временной ряд из CSV."""
    path = Path(__file__).parent.parent / "fixtures" / "golden_dataset.csv"
    df = pd.read_csv(path, parse_dates=['date'])
    # Возвращаем как pd.Series с DatetimeIndex (стандарт для TS)
    return df.set_index('date')['value']

@pytest.fixture
def golden_ts_series_with_covariates():
    """Загружает эталонный ряд + фиктивные ковариаты для теста корреляций."""
    path = Path(__file__).parent.parent / "fixtures" / "golden_dataset.csv"
    df = pd.read_csv(path, parse_dates=['date'])
    df = df.set_index('date')
    
    # Добавляем фиктивные ковариаты
    np.random.seed(42)
    df['covariate_1'] = df['value'] * 0.8 + np.random.normal(0, 5, len(df))
    df['covariate_2'] = np.random.normal(100, 10, len(df))
    
    return df, {'num': ['value', 'covariate_1', 'covariate_2']}, 'value'

def test_passport_v1_0_snapshot(golden_ts_series, snapshot):
    """
    CHARACTERIZATION TEST:
    Фиксирует эталонное поведение легаси-функции calculate_ts_passport.
    Если при рефакторинге математика изменится хотя бы на 1e-6, тест упадет.
    """
    # Вызываем легаси-функцию. 
    # ВАЖНО: Мы передаем данные ЯВНО (Правило 14 ARCHITECTURE.md), 
    # никаких AppState или session_state!
    passport = calculate_ts_passport(golden_ts_series)
    
    # Удаляем timestamp, так как он меняется при каждом запуске
    passport.pop('timestamp', None)
    
    # Сравниваем результат с эталонным снэпшотом (syrupy)
    assert passport == snapshot

def test_passport_with_covariates_snapshot(golden_ts_series_with_covariates, snapshot):
    """
    Тест на расчет корреляций (блок "6. КОРРЕЛЯЦИЯ ПРИЗНАКОВ").
    """
    df, ct_f, target_col = golden_ts_series_with_covariates
    target_series = df[target_col]
    
    passport = calculate_ts_passport(
        analysis_series=target_series,
        df_filtered=df,
        ct_f=ct_f,
        target_col=target_col
    )
    
    # Удаляем timestamp
    passport.pop('timestamp', None)
    
    # Сравниваем с эталоном
    assert passport == snapshot

def test_passport_short_series_fallback(golden_ts_series, snapshot):
    """
    Тест на граничный случай: очень короткий ряд (< 30 точек).
    Легаси-код возвращает {"error": "Недостаточно данных (нужно > 30 точек)"}.
    Мы должны зафиксировать ЭТО поведение.
    """
    short_series = golden_ts_series.iloc[:10]  # Всего 10 месяцев
    passport = calculate_ts_passport(short_series)
    
    # Удаляем timestamp (если он есть)
    passport.pop('timestamp', None)
    
    assert passport == snapshot