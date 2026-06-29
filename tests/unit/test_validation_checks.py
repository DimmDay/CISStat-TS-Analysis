# tests/unit/test_validation_checks.py
"""
Characterization-тесты для validation checks (C.1).
"""
import pytest
import pandas as pd
import numpy as np


class TestCheckUniqueness:
    """Тесты для check_uniqueness."""

    def test_no_duplicates(self):
        """DataFrame без дубликатов."""
        from validation.uniqueness import check_uniqueness
        
        df = pd.DataFrame({
            'date': pd.date_range('2020-01-01', periods=5),
            'value': [1, 2, 3, 4, 5]
        })
        
        result = check_uniqueness(df, date_col='date')
        
        assert result['duplicate_count'] == 0
        assert result['status'] == '✅ Соблюдено'

    def test_with_duplicates_by_date(self):
        """DataFrame с дубликатами по дате."""
        from validation.uniqueness import check_uniqueness
        
        df = pd.DataFrame({
            'date': ['2020-01-01', '2020-01-01', '2020-01-02'],
            'value': [1, 2, 3]
        })
        
        result = check_uniqueness(df, date_col='date')
        
        assert result['duplicate_count'] == 2  # обе строки с 2020-01-01
        assert result['status'] == '⚠️ Нарушено'

    def test_full_duplicates(self):
        """Полные дубликаты строк."""
        from validation.uniqueness import check_uniqueness
        
        df = pd.DataFrame({
            'a': [1, 1, 2],
            'b': [3, 3, 4]
        })
        
        result = check_uniqueness(df, date_col=None)
        
        assert result['duplicate_count'] == 2
        assert result['status'] == '⚠️ Нарушено'

    def test_empty_dataframe(self):
        """Пустой DataFrame."""
        from validation.uniqueness import check_uniqueness
        
        df = pd.DataFrame()
        result = check_uniqueness(df, date_col=None)
        
        assert result['duplicate_count'] == 0
        assert result['status'] == '✅ Соблюдено'


class TestCheckInclusion:
    """Тесты для check_inclusion."""

    def test_no_violations(self):
        """Все значения в справочнике."""
        from validation.inclusion import check_inclusion
        
        df = pd.DataFrame({
            'country': ['Russia', 'USA', 'China'],
            'value': [1, 2, 3]
        })
        rules = {'country': ['Russia', 'USA', 'China', 'Germany']}
        
        results, masks = check_inclusion(df, rules)
        
        assert len(results) == 0
        assert len(masks) == 0

    def test_with_violations(self):
        """Есть значения вне справочника."""
        from validation.inclusion import check_inclusion
        
        df = pd.DataFrame({
            'country': ['Russia', 'USA', 'France'],
            'value': [1, 2, 3]
        })
        rules = {'country': ['Russia', 'USA', 'China']}
        
        results, masks = check_inclusion(df, rules)
        
        assert len(results) == 1
        assert results[0]['Колонка'] == 'country'
        assert results[0]['Нарушений'] == 1
        assert 'country' in masks

    def test_multiple_columns(self):
        """Нарушения в нескольких колонках."""
        from validation.inclusion import check_inclusion
        
        df = pd.DataFrame({
            'country': ['Russia', 'France'],
            'status': ['Active', 'Unknown'],
            'value': [1, 2]
        })
        rules = {
            'country': ['Russia', 'USA'],
            'status': ['Active', 'Inactive']
        }
        
        results, masks = check_inclusion(df, rules)
        
        assert len(results) == 2
        assert len(masks) == 2

    def test_empty_rules(self):
        """Пустые правила."""
        from validation.inclusion import check_inclusion
        
        df = pd.DataFrame({'a': [1, 2, 3]})
        results, masks = check_inclusion(df, {})
        
        assert len(results) == 0
        assert len(masks) == 0

    def test_nan_values_ignored(self):
        """NaN значения игнорируются."""
        from validation.inclusion import check_inclusion
        
        df = pd.DataFrame({
            'country': ['Russia', None, 'USA'],
            'value': [1, 2, 3]
        })
        rules = {'country': ['Russia', 'USA']}
        
        results, masks = check_inclusion(df, rules)
        
        assert len(results) == 0  # NaN не считается нарушением


class TestCheckTsProperties:
    """Тесты для check_ts_properties."""

    def test_basic_ts_checks(self):
        """Базовая проверка TS-свойств."""
        from validation.ts_checks import check_ts_properties
        
        # Создаём DataFrame с колонкой date (не index!)
        df = pd.DataFrame({
            'date': pd.date_range('2020-01-01', periods=30),
            'value': np.random.randn(30)
        })
        
        result = check_ts_properties(df, 'date', 'value')
        
        assert 'adf_pvalue' in result
        assert 'is_stationary' in result
        assert 'frequency' in result
        assert 'max_gap' in result

    def test_insufficient_data(self):
        """Недостаточно данных (< 10)."""
        from validation.ts_checks import check_ts_properties
        
        df = pd.DataFrame({
            'date': pd.date_range('2020-01-01', periods=5),
            'value': [1, 2, 3, 4, 5]
        })
        
        result = check_ts_properties(df, 'date', 'value')
        
        assert 'error' in result
        assert 'Недостаточно данных' in result['error']

    def test_no_date_column(self):
        """Нет колонки с датами."""
        from validation.ts_checks import check_ts_properties
        
        df = pd.DataFrame({'value': [1, 2, 3]})
        
        result = check_ts_properties(df, 'date', 'value')
        
        assert 'error' in result

    def test_frequency_detection(self):
        """Определение частоты."""
        from validation.ts_checks import check_ts_properties
        
        df = pd.DataFrame({
            'date': pd.date_range('2020-01-01', periods=30, freq='D'),
            'value': np.random.randn(30)
        })
        
        result = check_ts_properties(df, 'date', 'value')
        
        assert result['frequency'] == 'D'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# tests/unit/test_validation_checks.py - добавить к существующим тестам

class TestComputeDuplicateMask:
    """Тесты для compute_duplicate_mask."""

    def test_cross_sectional_data(self):
        """Кросс-секционные данные (не панельные)."""
        from validation.uniqueness import compute_duplicate_mask
        
        df = pd.DataFrame({
            'a': [1, 1, 2],
            'b': [3, 3, 4]
        })
        
        mask = compute_duplicate_mask(df, is_panel_data=False, check_cols=None)
        
        assert mask.sum() == 2  # обе строки с дубликатами
        assert mask.tolist() == [True, True, False]

    def test_panel_data(self):
        """Панельные данные (проверка по subset)."""
        from validation.uniqueness import compute_duplicate_mask
        
        df = pd.DataFrame({
            'country': ['Russia', 'Russia', 'USA'],
            'year': [2020, 2020, 2020],
            'value': [1, 2, 3]
        })
        
        mask = compute_duplicate_mask(df, is_panel_data=True, check_cols=['country', 'year'])
        
        assert mask.sum() == 2  # обе строки Russia-2020
        assert mask.tolist() == [True, True, False]

    def test_no_duplicates(self):
        """Нет дубликатов."""
        from validation.uniqueness import compute_duplicate_mask
        
        df = pd.DataFrame({
            'a': [1, 2, 3],
            'b': [4, 5, 6]
        })
        
        mask = compute_duplicate_mask(df, is_panel_data=False, check_cols=None)
        
        assert mask.sum() == 0
        assert mask.tolist() == [False, False, False]

    def test_empty_dataframe(self):
        """Пустой DataFrame."""
        from validation.uniqueness import compute_duplicate_mask
        
        df = pd.DataFrame()
        mask = compute_duplicate_mask(df, is_panel_data=False, check_cols=None)
        
        assert len(mask) == 0


class TestComputeInclusionViolations:
    """Тесты для compute_inclusion_violations."""

    def test_no_violations(self):
        """Все значения в справочнике."""
        from validation.inclusion import compute_inclusion_violations
        
        df = pd.DataFrame({
            'country': ['Russia', 'USA', 'China'],
            'value': [1, 2, 3]
        })
        rules = {'country': ['Russia', 'USA', 'China', 'Germany']}
        
        violations = compute_inclusion_violations(df, rules)
        
        assert len(violations) == 0

    def test_with_violations(self):
        """Есть значения вне справочника."""
        from validation.inclusion import compute_inclusion_violations
        
        df = pd.DataFrame({
            'country': ['Russia', 'USA', 'France'],
            'value': [1, 2, 3]
        })
        rules = {'country': ['Russia', 'USA', 'China']}
        
        violations = compute_inclusion_violations(df, rules)
        
        assert len(violations) == 1
        assert violations[0]['column'] == 'country'
        assert violations[0]['count'] == 1
        assert 'France' in violations[0]['invalid_values']
        assert 'mask' in violations[0]

    def test_multiple_columns(self):
        """Нарушения в нескольких колонках."""
        from validation.inclusion import compute_inclusion_violations
        
        df = pd.DataFrame({
            'country': ['Russia', 'France'],
            'status': ['Active', 'Unknown'],
            'value': [1, 2]
        })
        rules = {
            'country': ['Russia', 'USA'],
            'status': ['Active', 'Inactive']
        }
        
        violations = compute_inclusion_violations(df, rules)
        
        assert len(violations) == 2

    def test_empty_rules(self):
        """Пустые правила."""
        from validation.inclusion import compute_inclusion_violations
        
        df = pd.DataFrame({'a': [1, 2, 3]})
        violations = compute_inclusion_violations(df, {})
        
        assert len(violations) == 0

    def test_nan_values_ignored(self):
        """NaN значения игнорируются."""
        from validation.inclusion import compute_inclusion_violations
        
        df = pd.DataFrame({
            'country': ['Russia', None, 'USA'],
            'value': [1, 2, 3]
        })
        rules = {'country': ['Russia', 'USA']}
        
        violations = compute_inclusion_violations(df, rules)
        
        assert len(violations) == 0  # NaN не считается нарушением

    def test_mask_structure(self):
        """Маска должна быть pd.Series с правильным индексом."""
        from validation.inclusion import compute_inclusion_violations
        
        df = pd.DataFrame({
            'country': ['Russia', 'France', 'USA'],
            'value': [1, 2, 3]
        })
        rules = {'country': ['Russia', 'USA']}
        
        violations = compute_inclusion_violations(df, rules)
        
        assert len(violations) == 1
        mask = violations[0]['mask']
        assert isinstance(mask, pd.Series)
        assert len(mask) == len(df)
        assert mask.tolist() == [False, True, False]