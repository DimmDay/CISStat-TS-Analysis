# tests/unit/test_correlation.py
"""
Characterization-тесты для find_significant_correlations.
Правило: сначала тест, потом перенос.
"""
import pytest
import numpy as np
import pandas as pd


class TestFindSignificantCorrelations:
    """Тесты для функции поиска значимых корреляций."""

    def test_basic_correlation_detection(self):
        """Должна находить сильные корреляции."""
        from app.eda.correlation import find_significant_correlations
        
        # Создаём данные с сильной корреляцией
        np.random.seed(42)
        df = pd.DataFrame({
            'a': np.random.randn(100),
            'b': np.random.randn(100),
        })
        df['c'] = df['a'] * 2 + np.random.randn(100) * 0.1  # Сильная корреляция с 'a'
        
        result = find_significant_correlations(df, ['a', 'b', 'c'], threshold=0.5)
        
        assert isinstance(result, list)
        assert len(result) > 0
        # Должна найти корреляцию между a и c
        pairs = [item['pair'] for item in result]
        assert any('a' in pair and 'c' in pair for pair in pairs)

    def test_no_significant_correlations(self):
        """Не должна находить значимых связей при слабой корреляции."""
        from app.eda.correlation import find_significant_correlations
        
        np.random.seed(42)
        df = pd.DataFrame({
            'a': np.random.randn(100),
            'b': np.random.randn(100),
            'c': np.random.randn(100),
        })
        
        result = find_significant_correlations(df, ['a', 'b', 'c'], threshold=0.5)
        
        assert isinstance(result, list)
        # Случайные данные не должны иметь сильных корреляций
        assert len(result) == 0

    def test_custom_threshold(self):
        """Должна поддерживать пользовательский порог."""
        from app.eda.correlation import find_significant_correlations
        
        np.random.seed(42)
        df = pd.DataFrame({
            'a': np.random.randn(100),
            'b': np.random.randn(100),
        })
        df['c'] = df['a'] * 0.6 + np.random.randn(100) * 0.5  # Умеренная корреляция
        
        # С низким порогом найдёт
        result_low = find_significant_correlations(df, ['a', 'b', 'c'], threshold=0.3)
        # С высоким порогом не найдёт
        result_high = find_significant_correlations(df, ['a', 'b', 'c'], threshold=0.8)
        
        assert len(result_low) >= len(result_high)

    def test_structure_of_results(self):
        """Результаты должны иметь правильную структуру."""
        from app.eda.correlation import find_significant_correlations
        
        np.random.seed(42)
        df = pd.DataFrame({
            'a': np.random.randn(100),
            'b': np.random.randn(100),
        })
        df['c'] = df['a'] * 2 + np.random.randn(100) * 0.1
        
        result = find_significant_correlations(df, ['a', 'b', 'c'], threshold=0.5)
        
        if len(result) > 0:
            item = result[0]
            assert 'pair' in item
            assert 'val' in item
            assert 'desc' in item
            assert isinstance(item['pair'], str)
            assert isinstance(item['val'], (int, float))
            assert isinstance(item['desc'], str)

    def test_negative_correlation(self):
        """Должна находить отрицательные корреляции."""
        from app.eda.correlation import find_significant_correlations
        
        np.random.seed(42)
        df = pd.DataFrame({
            'a': np.random.randn(100),
            'b': np.random.randn(100),
        })
        df['c'] = -df['a'] * 2 + np.random.randn(100) * 0.1  # Отрицательная корреляция
        
        result = find_significant_correlations(df, ['a', 'b', 'c'], threshold=0.5)
        
        assert len(result) > 0
        # Должна найти отрицательную корреляцию
        negative_links = [item for item in result if item['val'] < 0]
        assert len(negative_links) > 0

    def test_empty_dataframe(self):
        """Должна обрабатывать пустой DataFrame."""
        from app.eda.correlation import find_significant_correlations
        
        df = pd.DataFrame()
        result = find_significant_correlations(df, [], threshold=0.5)
        
        assert result == []

    def test_single_column(self):
        """Должна обрабатывать одну колонку."""
        from app.eda.correlation import find_significant_correlations
        
        df = pd.DataFrame({'a': [1, 2, 3, 4, 5]})
        result = find_significant_correlations(df, ['a'], threshold=0.5)
        
        assert result == []

    def test_with_nan_values(self):
        """Должна обрабатывать NaN значения."""
        from app.eda.correlation import find_significant_correlations
        
        np.random.seed(42)
        df = pd.DataFrame({
            'a': np.random.randn(100),
            'b': np.random.randn(100),
        })
        df['c'] = df['a'] * 2 + np.random.randn(100) * 0.1
        df.loc[::10, 'a'] = np.nan  # Каждое 10-е значение NaN
        
        result = find_significant_correlations(df, ['a', 'b', 'c'], threshold=0.5)
        
        assert isinstance(result, list)

    def test_high_threshold_multicollinearity(self):
        """Должна находить мультиколлинеарность при высоком пороге."""
        from app.eda.correlation import find_significant_correlations
        
        np.random.seed(42)
        df = pd.DataFrame({
            'a': np.random.randn(100),
            'b': np.random.randn(100),
        })
        df['c'] = df['a'] * 1.5 + np.random.randn(100) * 0.01  # Очень сильная корреляция
        
        result = find_significant_correlations(df, ['a', 'b', 'c'], threshold=0.85)
        
        assert len(result) > 0
        # Все связи должны быть очень сильными
        for item in result:
            assert abs(item['val']) > 0.85


if __name__ == "__main__":
    pytest.main([__file__, "-v"])