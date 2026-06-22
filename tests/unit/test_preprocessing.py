# tests/unit/test_preprocessing.py
import pytest
import pandas as pd
import numpy as np
from app.preprocessing.transforms import apply_differencing, apply_differencing_panel

# ──────────────────────────────────────────────
# 1. SNAPSHOT ТЕСТЫ (Фиксация эталонного поведения Single-Series)
# ──────────────────────────────────────────────

@pytest.fixture
def sample_series():
    # Генерируем ряд с трендом и сезонностью
    np.random.seed(42)
    # ИСПРАВЛЕНИЕ: В pandas 2.2.0+ 'M' заменен на 'ME' (Month End)
    idx = pd.date_range("2020-01-01", periods=50, freq="ME")
    trend = np.linspace(10, 20, 50)
    seasonality = 5 * np.sin(np.linspace(0, 8 * np.pi, 50))
    noise = np.random.normal(0, 0.5, 50)
    return pd.Series(trend + seasonality + noise, index=idx)

def test_diff_first_snapshot(sample_series, snapshot):
    res = apply_differencing(sample_series, method='first', d=1)
    # syrupy автоматически назовет снимок именем тестовой функции
    snapshot.assert_match(res.to_json())

def test_diff_seasonal_snapshot(sample_series, snapshot):
    res = apply_differencing(sample_series, method='seasonal', s=12)
    snapshot.assert_match(res.to_json())

def test_diff_fractional_snapshot(sample_series, snapshot):
    # Проверяем, что исправленный fractional работает и выдает эталон
    res = apply_differencing(sample_series, method='fractional', frac_d=0.5)
    snapshot.assert_match(res.to_json())

def test_diff_log_positive_only():
    s = pd.Series([1.0, 2.0, -1.0, 4.0])
    with pytest.raises(ValueError, match="положительных"):
        apply_differencing(s, method='log')


# ──────────────────────────────────────────────
# 2. ТЕСТЫ НА DATA LEAKAGE (Правило 15 - Panel Data)
# ──────────────────────────────────────────────

@pytest.fixture
def panel_df():
    # Создаем панель из 2 сущностей. 
    data = {
        'entity': ['A', 'A', 'A', 'B', 'B', 'B'],
        'date': pd.to_datetime(['2020-01-01', '2020-01-02', '2020-01-03'] * 2),
        'value': [10.0, 20.0, 30.0, 100.0, 200.0, 300.0]
    }
    return pd.DataFrame(data).set_index(['entity', 'date']).sort_index()

def test_panel_diff_no_leakage(panel_df):
    """
    Железный тест: При дифференцировании внутри Entity A, 
    значение в '2020-01-02' должно быть 20 - 10 = 10.
    """
    res_df = apply_differencing_panel(
        df=panel_df.reset_index(), 
        target_col='value', 
        entity_col='entity', 
        method='first'
    )
    
    # Проверяем Entity A
    val_a_2 = res_df[(res_df['entity'] == 'A') & (res_df['date'] == '2020-01-02')]['value'].iloc[0]
    assert val_a_2 == 10.0, "Data Leakage detected! Value leaked from Entity B to A."
    
    # Проверяем Entity B
    val_b_2 = res_df[(res_df['entity'] == 'B') & (res_df['date'] == '2020-01-02')]['value'].iloc[0]
    assert val_b_2 == 100.0, "Data Leakage detected! Value leaked from Entity A to B."

def test_panel_diff_preserves_index_alignment(panel_df):
    """
    Проверяем, что Panel-safe wrapper не ломает MultiIndex 
    и корректно формирует NaN на первых элементах.
    """
    res_df = apply_differencing_panel(
        df=panel_df.reset_index(), 
        target_col='value', 
        entity_col='entity', 
        method='first'
    )
    # Длина должна остаться ровно такой же, как у исходного df
    assert len(res_df) == len(panel_df)
    
    # ИСПРАВЛЕНИЕ: groupby().first() пропускает NaN! 
    # Используем .nth(0), чтобы получить именно первую строку (включая NaN).
    first_values = res_df.sort_values(['entity', 'date']).groupby('entity')['value'].nth(0)
    assert first_values.isna().all(), "First values in each group should be NaN after differencing."