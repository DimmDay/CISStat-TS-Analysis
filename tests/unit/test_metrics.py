# tests/unit/test_metrics.py
import pytest
import pandas as pd
import numpy as np
from pathlib import Path

from app.core.metrics import calculate_ts_passport

@pytest.fixture
def golden_ts_series():
    """Загружает эталонный временной ряд из CSV."""
    path = Path(__file__).parent.parent / "fixtures" / "golden_dataset.csv"
    df = pd.read_csv(path, parse_dates=['date'])
    return df.set_index('date')['value']

@pytest.fixture
def golden_ts_series_with_covariates():
    """Загружает эталонный ряд + фиктивные ковариаты для теста корреляций."""
    path = Path(__file__).parent.parent / "fixtures" / "golden_dataset.csv"
    df = pd.read_csv(path, parse_dates=['date'])
    df = df.set_index('date')
    
    np.random.seed(42)
    df['covariate_1'] = df['value'] * 0.8 + np.random.normal(0, 5, len(df))
    df['covariate_2'] = np.random.normal(100, 10, len(df))
    
    return df, {'num': ['value', 'covariate_1', 'covariate_2']}, 'value'

# ⚠️ ИМЕНА ФУНКЦИЙ ДОЛЖНЫ СОВПАДАТЬ С LEGACY-ТЕСТАМИ, 
# ЧТОБЫ SYRUPY НАШОЛ СООТВЕТСТВУЮЩИЕ SNAPSHOT-КЛЮЧИ В .ambr ФАЙЛЕ

def test_passport_v1_0_snapshot(golden_ts_series, snapshot):
    """
    UNIT TEST:
    Проверяет, что новая функция calculate_ts_passport из app/core/metrics.py
    выдает результат, идентичный legacy-снэпшоту.
    """
    error_log = []
    passport = calculate_ts_passport(golden_ts_series, error_log=error_log)
    
    # Удаляем timestamp, так как он меняется при каждом запуске
    passport.pop('timestamp', None)
    
    # Сравниваем с тем же snapshot, что и для legacy-функции
    assert passport == snapshot
    
    # Проверяем, что критических ошибок не было
    critical_errors = [e for e in error_log if e['severity'] == 'critical']
    assert len(critical_errors) == 0

def test_passport_with_covariates_snapshot(golden_ts_series_with_covariates, snapshot):
    """
    UNIT TEST:
    Проверяет расчет корреляций в новой функции against legacy-snapshot.
    """
    df, ct_f, target_col = golden_ts_series_with_covariates
    target_series = df[target_col]
    
    error_log = []
    passport = calculate_ts_passport(
        analysis_series=target_series,
        df_filtered=df,
        ct_f=ct_f,
        target_col=target_col,
        error_log=error_log
    )
    
    passport.pop('timestamp', None)
    assert passport == snapshot

def test_passport_short_series_fallback(golden_ts_series, snapshot):
    """
    UNIT TEST:
    Проверяет граничный случай (короткий ряд) в новой функции.
    """
    short_series = golden_ts_series.iloc[:10]
    
    error_log = []
    passport = calculate_ts_passport(short_series, error_log=error_log)
    passport.pop('timestamp', None)
    
    assert passport == snapshot