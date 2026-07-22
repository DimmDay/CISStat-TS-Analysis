# tests/unit/test_classifier.py
"""
Characterization-тесты для classify_columns.
Правило: сначала тест, потом перенос.
"""
import pytest
import numpy as np
import pandas as pd


class TestClassifyColumns:
    """Тесты для функции классификации колонок."""

    def test_basic_classification(self):
        """Должна правильно классифицировать базовые типы."""
        from app.classification.classifier import classify_columns
        
        df = pd.DataFrame({
            'num1': [1, 2, 3],
            'num2': [1.5, 2.5, 3.5],
            'cat1': ['a', 'b', 'c'],
            'cat2': ['x', 'y', 'z'],
            'date1': pd.to_datetime(['2020-01-01', '2020-01-02', '2020-01-03'])
        })
        
        result = classify_columns(df)
        
        assert isinstance(result, dict)
        assert 'num' in result
        assert 'cat' in result
        assert 'date' in result
        
        assert set(result['num']) == {'num1', 'num2'}
        assert set(result['cat']) == {'cat1', 'cat2'}
        assert set(result['date']) == {'date1'}

    def test_numeric_with_few_unique_as_categorical(self):
        """Числовые колонки с малым количеством уникальных значений не должны быть категориальными."""
        from app.classification.classifier import classify_columns
        
        df = pd.DataFrame({
            'id': list(range(100)),  # 100 уникальных - числовая
            'category': [1, 2] * 50,  # 2 уникальных - всё равно числовая (не object/string)
            'many_values': np.random.randn(100)  # много уникальных - числовая
        })
        
        result = classify_columns(df)
        
        # Все числовые колонки должны быть в 'num', даже если мало уникальных значений
        assert 'id' in result['num']
        assert 'category' in result['num']
        assert 'many_values' in result['num']
        # Ни одна не должна быть в 'cat', так как они числовые, а не object/string
        assert 'category' not in result['cat']

    def test_empty_dataframe(self):
        """Должна обрабатывать пустой DataFrame."""
        from app.classification.classifier import classify_columns
        
        df = pd.DataFrame()
        result = classify_columns(df)
        
        assert result == {'num': [], 'cat': [], 'date': []}

    def test_datetime_detection(self):
        """Должна обнаруживать datetime колонки."""
        from app.classification.classifier import classify_columns
        
        df = pd.DataFrame({
            'date1': pd.to_datetime(['2020-01-01', '2020-01-02']),
            'date2': pd.date_range('2020-01-01', periods=2),
            'not_date': ['2020-01-01', '2020-01-02']  # строки, не datetime
        })
        
        result = classify_columns(df)
        
        assert 'date1' in result['date']
        assert 'date2' in result['date']
        assert 'not_date' not in result['date']

    def test_categorical_with_many_unique(self):
        """Категориальные колонки с >100 уникальными значениями не должны попадать в cat."""
        from app.classification.classifier import classify_columns
        
        df = pd.DataFrame({
            'high_cardinality': [f'val_{i}' for i in range(150)],
            'low_cardinality': ['a', 'b', 'c'] * 50
        })
        
        result = classify_columns(df)
        
        assert 'high_cardinality' not in result['cat']
        assert 'low_cardinality' in result['cat']

    def test_categorical_with_single_unique(self):
        """Колонки с 1 уникальным значением не должны попадать в cat."""
        from app.classification.classifier import classify_columns
        
        df = pd.DataFrame({
            'constant': ['same'] * 10,
            'variable': ['a', 'b'] * 5
        })
        
        result = classify_columns(df)
        
        assert 'constant' not in result['cat']
        assert 'variable' in result['cat']

    def test_mixed_types(self):
        """Должна правильно обрабатывать смешанные типы данных."""
        from app.classification.classifier import classify_columns
        
        df = pd.DataFrame({
            'int_col': [1, 2, 3],
            'float_col': [1.1, 2.2, 3.3],
            'str_col': ['a', 'b', 'c'],
            'bool_col': [True, False, True],
            'datetime_col': pd.to_datetime(['2020-01-01', '2020-01-02', '2020-01-03'])
        })
        
        result = classify_columns(df)
        
        assert 'int_col' in result['num']
        assert 'float_col' in result['num']
        assert 'str_col' in result['cat']
        assert 'datetime_col' in result['date']

    def test_with_nan_values(self):
        """Должна обрабатывать колонки с NaN значениями."""
        from app.classification.classifier import classify_columns
        
        df = pd.DataFrame({
            'num_with_nan': [1, np.nan, 3],
            'cat_with_nan': ['a', None, 'c'],
            'date_with_nan': pd.to_datetime(['2020-01-01', None, '2020-01-03'])
        })
        
        result = classify_columns(df)
        
        assert 'num_with_nan' in result['num']
        assert 'cat_with_nan' in result['cat']
        assert 'date_with_nan' in result['date']

    def test_return_structure(self):
        """Результат должен иметь правильную структуру."""
        from app.classification.classifier import classify_columns
        
        df = pd.DataFrame({'a': [1, 2, 3]})
        result = classify_columns(df)
        
        assert isinstance(result, dict)
        assert all(key in result for key in ['num', 'cat', 'date'])
        assert all(isinstance(result[key], list) for key in ['num', 'cat', 'date'])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])