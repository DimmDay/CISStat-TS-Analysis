# tests/unit/test_utils.py
"""Unit-тесты для app/core/utils.py"""
import numpy as np
import pandas as pd
import pytest

from app.core.utils import safe_stat, _safe_nunique


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


"""
Unit-тесты для _safe_nunique — безопасный подсчёт уникальных значений.
Правило: сначала тест, потом перенос (EXTRACTION_PLAN.md, Этап 3, A.12).
"""


class TestSafeNunique:
    """Тесты для функции _safe_nunique."""

    def test_basic_case_in_range(self):
        """Обычный случай: уникальные значения в диапазоне (1, 100)."""
        from app.core.utils import _safe_nunique
        
        series = pd.Series([1, 2, 3, 4, 5, 1, 2, 3])
        assert _safe_nunique(series) is True

    def test_basic_case_out_of_range_high(self):
        """Слишком много уникальных значений (> max_val)."""
        from app.core.utils import _safe_nunique
        
        series = pd.Series(range(200))
        assert _safe_nunique(series, min_val=1, max_val=100) is False

    def test_basic_case_out_of_range_low(self):
        """Слишком мало уникальных значений (< min_val)."""
        from app.core.utils import _safe_nunique
        
        series = pd.Series([1, 1, 1, 1, 1])
        assert _safe_nunique(series, min_val=1, max_val=100) is False

    def test_empty_series(self):
        """Пустая серия → False."""
        from app.core.utils import _safe_nunique
        
        series = pd.Series([], dtype=float)
        assert _safe_nunique(series) is False

    def test_all_nan_series(self):
        """Серия со всеми NaN → False."""
        from app.core.utils import _safe_nunique
        
        series = pd.Series([np.nan, np.nan, np.nan])
        assert _safe_nunique(series) is False

    def test_custom_range(self):
        """Пользовательский диапазон min_val/max_val."""
        from app.core.utils import _safe_nunique
        
        series = pd.Series([1, 2, 3, 4, 5])
        # 5 уникальных значений: min_val=3, max_val=10 → 3 < 5 < 10 → True
        assert _safe_nunique(series, min_val=3, max_val=10) is True
        # min_val=5, max_val=10 → 5 < 5 < 10 → False (строгая проверка)
        assert _safe_nunique(series, min_val=5, max_val=10) is False

    def test_unhashable_type_dict(self):
        """Серия со словарями → False (нехэшируемый тип)."""
        from app.core.utils import _safe_nunique
        
        series = pd.Series([{'a': 1}, {'b': 2}, {'a': 1}])
        assert _safe_nunique(series) is False

    def test_unhashable_type_list(self):
        """Серия со списками → False (нехэшируемый тип)."""
        from app.core.utils import _safe_nunique
        
        series = pd.Series([[1, 2], [3, 4], [1, 2]])
        assert _safe_nunique(series) is False

    def test_unhashable_type_set(self):
        """Серия с множествами → False (нехэшируемый тип)."""
        from app.core.utils import _safe_nunique
        
        series = pd.Series([{1, 2}, {3, 4}, {1, 2}])
        assert _safe_nunique(series) is False

    def test_mixed_with_nan(self):
        """Серия с NaN и валидными значениями — NaN игнорируются."""
        from app.core.utils import _safe_nunique
        
        series = pd.Series([1, 2, 3, np.nan, np.nan, 1, 2])
        # Уникальные: {1, 2, 3} = 3 значения, диапазон (1, 100) → True
        assert _safe_nunique(series) is True

    def test_boundary_exactly_min_val(self):
        """Ровно min_val уникальных значений → False (строгая проверка <)."""
        from app.core.utils import _safe_nunique
        
        series = pd.Series([1, 1, 2, 2])  # 2 уникальных
        # min_val=2, max_val=10 → 2 < 2 < 10 → False
        assert _safe_nunique(series, min_val=2, max_val=10) is False

    def test_boundary_exactly_max_val(self):
        """Ровно max_val уникальных значений → False (строгая проверка <)."""
        from app.core.utils import _safe_nunique
        
        series = pd.Series(range(100))  # 100 уникальных
        # min_val=1, max_val=100 → 1 < 100 < 100 → False
        assert _safe_nunique(series, min_val=1, max_val=100) is False

    def test_mixed_types_in_series(self):
        """Серия со смешанными типами (int, str) — должна работать."""
        from app.core.utils import _safe_nunique
        
        series = pd.Series([1, 'a', 2, 'b', 1, 'a'])
        # Уникальные: {1, 'a', 2, 'b'} = 4 значения
        assert _safe_nunique(series) is True

    def test_single_unique_value(self):
        """Одно уникальное значение → False (min_val=1, строгая проверка)."""
        from app.core.utils import _safe_nunique
        
        series = pd.Series([42, 42, 42, 42])
        assert _safe_nunique(series, min_val=1, max_val=100) is False

    def test_large_series_performance(self):
        """Большая серия — должна работать быстро (head(100) оптимизация)."""
        from app.core.utils import _safe_nunique
        
        series = pd.Series(np.random.randint(0, 1000, size=100000))
        # Не должно зависнуть
        result = _safe_nunique(series)
        assert isinstance(result, bool)