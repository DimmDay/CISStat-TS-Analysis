"""
Общие фикстуры для тестов валидации.
Используются всеми тестовыми файлами в папке tests/.
"""
import pytest
import pandas as pd
import numpy as np


@pytest.fixture
def sample_panel_df():
    """
    Панельные данные: 5 стран × 5 лет (1994-1998).
    Правильный хронологический порядок.
    """
    data = {
        'Country': ['Азербайджан', 'Беларусь', 'Казахстан', 'Кыргызстан', 'Молдова'] * 5,
        'Year': [1994, 1994, 1994, 1994, 1994,
                 1995, 1995, 1995, 1995, 1995,
                 1996, 1996, 1996, 1996, 1996,
                 1997, 1997, 1997, 1997, 1997,
                 1998, 1998, 1998, 1998, 1998],
        'Price': [65.9, 30.7, 85.3, 40.6, 28.9,
                  65.0, 49.9, 81.9, 40.7, 27.0,
                  63.6, 53.4, 46.2, 41.3, 23.2,
                  56.0, 68.1, 34.0, 29.1, 17.7,
                  52.2, 67.6, 21.7, 20.1, 16.2],
        'usd/tonne': ['usd'] * 25
    }
    return pd.DataFrame(data)


@pytest.fixture
def unsorted_panel_df():
    """Панельные данные с НАРУШЕНИЕМ хронологии: 2016 идёт перед 2015."""
    countries = ['Азербайджан', 'Беларусь', 'Казахстан', 'Кыргызстан', 'Молдова']
    years_order = [2014, 2016, 2015, 2017, 2018]  # Намеренно меняем 2015 и 2016 местами
    
    # Генерируем данные: для каждой страны все годы подряд (как в реальном датасете)
    data = {
        'Country': [country for country in countries for _ in years_order],
        'Year': [year for country in countries for year in years_order],
        'Price': list(np.random.uniform(20, 100, 25)),
        'usd/tonne': ['usd'] * 25
    }
    return pd.DataFrame(data)


@pytest.fixture
def simple_timeseries_df():
    """
    Простой временной ряд (без группировки).
    Правильный порядок.
    """
    data = {
        'Year': list(range(1994, 2025)),  # 1994-2024
        'Value': np.random.randn(31).cumsum() + 100
    }
    return pd.DataFrame(data)


@pytest.fixture
def unsorted_timeseries_df():
    """
    Простой временной ряд с нарушением порядка.
    """
    years = list(range(1994, 2025))
    # Меняем местами 2015 и 2016
    years[21], years[22] = years[22], years[21]
    
    data = {
        'Year': years,
        'Value': np.random.randn(31).cumsum() + 100
    }
    return pd.DataFrame(data)


@pytest.fixture
def timeseries_with_gaps_df():
    """
    Временной ряд с пропуском года 2015.
    """
    years = list(range(1994, 2015)) + list(range(2016, 2025))
    data = {
        'Year': years,
        'Value': np.random.randn(len(years)).cumsum() + 100
    }
    return pd.DataFrame(data)


@pytest.fixture
def empty_df():
    """Пустой DataFrame."""
    return pd.DataFrame({'Year': [], 'Value': []})


@pytest.fixture
def single_row_df():
    """DataFrame с одной строкой."""
    return pd.DataFrame({'Year': [2020], 'Value': [100.0]})


@pytest.fixture
def df_with_nans():
    """DataFrame с NaN значениями."""
    data = {
        'Country': ['A', 'A', 'A', 'B', 'B', 'B'],
        'Year': [2020, 2021, 2022, 2020, 2021, 2022],
        'Value': [10.0, np.nan, 30.0, 40.0, 50.0, np.nan]
    }
    return pd.DataFrame(data)


@pytest.fixture
def default_rules():
    """Правила валидации по умолчанию (пустые)."""
    return {
        "consistency": [],
        "completeness": [],
        "regularity": []
    }