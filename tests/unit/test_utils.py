# tests/unit/test_utils.py
"""Unit-тесты для app/core/utils.py"""
import numpy as np
import pandas as pd
import pytest

from app.core.utils import safe_stat, safe_nunique


class TestSafeStat:
    """Тесты для safe_stat."""
    
    def test_basic_mean(self):
        df = pd.DataFrame({'price': [10, 20, 30, 40, 50]})
        assert safe_stat(df, 'price', np.mean) == 30.0
    
    def test_missing_column(self):
        df = pd.DataFrame({'price': [10, 20, 30]})
        assert safe_stat(df, 'nonexistent', np.mean) == 0.0
    
    def test_empty_dataframe(self):
        df = pd.DataFrame()
        assert safe_stat(df, 'price', np.mean) == 0.0
    
    def test_all_nan_column(self):
        df = pd.DataFrame({'price': [np.nan, np.nan, np.nan]})
        assert safe_stat(df, 'price', np.mean) == 0.0
    
    def test_with_nan_values(self):
        df = pd.DataFrame({'price': [10, np.nan, 30, np.nan, 50]})
        # np.mean на dropna() должен дать (10+30+50)/3 = 30
        assert safe_stat(df, 'price', np.mean) == 30.0
    
    def test_std_function(self):
        df = pd.DataFrame({'price': [10, 20, 30, 40, 50]})
        result = safe_stat(df, 'price', np.std)
        expected = np.std([10, 20, 30, 40, 50])
        assert abs(result - expected) < 1e-9
    
    def test_median_function(self):
        df = pd.DataFrame({'price': [10, 20, 30, 40, 50]})
        assert safe_stat(df, 'price', np.median) == 30.0


class TestSafeNunique:
    """Тесты для safe_nunique."""
    
    def test_categorical_series(self):
        s = pd.Series(['A', 'B', 'C', 'A', 'B'])
        assert safe_nunique(s, min_val=1, max_val=100) is True
    
    def test_too_many_unique(self):
        s = pd.Series(range(200))
        assert safe_nunique(s, min_val=1, max_val=100) is False
    
    def test_too_few_unique(self):
        s = pd.Series(['A', 'A', 'A'])
        assert safe_nunique(s, min_val=1, max_val=100) is False
    
    def test_unhashable_types(self):
        s = pd.Series([{'a': 1}, {'b': 2}, {'c': 3}])
        assert safe_nunique(s, min_val=1, max_val=100) is False
    
    def test_empty_series(self):
        s = pd.Series([], dtype=object)
        assert safe_nunique(s, min_val=1, max_val=100) is False
    
    def test_all_nan_series(self):
        s = pd.Series([np.nan, np.nan, np.nan])
        assert safe_nunique(s, min_val=1, max_val=100) is False
    
    def test_numeric_series(self):
        s = pd.Series([1, 2, 3, 4, 5])
        assert safe_nunique(s, min_val=1, max_val=100) is True