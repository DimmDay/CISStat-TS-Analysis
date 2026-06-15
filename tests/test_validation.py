"""
Тесты для функций валидации временных рядов.
Проверяют корректность работы модуля validation.engine.
"""
import pytest
import pandas as pd
import numpy as np
import sys
import os

# Добавляем корень проекта в path для импорта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validation.engine import validate_consistency, validate_regular_step


# ═══════════════════════════════════════════════════════════
# ТЕСТЫ ДЛЯ validate_consistency
# ═══════════════════════════════════════════════════════════

class TestValidateConsistency:
    """Тесты проверки согласованности и хронологии."""

    def test_sorted_panel_data_no_violations(self, sample_panel_df, default_rules):
        """Панельные данные в правильном порядке — нарушений нет."""
        results = validate_consistency(sample_panel_df, default_rules)
        
        # Должна быть хотя бы одна проверка
        assert len(results) > 0
        
        # Все проверки должны показать 0 нарушений
        for r in results:
            assert r.get('Нарушений', 0) == 0, f"Ожидалось 0 нарушений, получено {r}"

    def test_unsorted_panel_data_detects_violations(self, unsorted_panel_df, default_rules):
        """Панельные данные с нарушением порядка (2016→2015) — должны быть нарушения."""
        results = validate_consistency(unsorted_panel_df, default_rules)
        
        # Должны быть найдены нарушения
        total_violations = sum(r.get('Нарушений', 0) for r in results)
        assert total_violations > 0, "Функция не обнаружила нарушения хронологии!"
        
        # Должно быть 5 нарушений (по одному на каждую страну)
        assert total_violations == 5, f"Ожидалось 5 нарушений, получено {total_violations}"

    def test_sorted_timeseries_no_violations(self, simple_timeseries_df, default_rules):
        """Отсортированный временной ряд — нарушений нет."""
        results = validate_consistency(simple_timeseries_df, default_rules)
        
        total_violations = sum(r.get('Нарушений', 0) for r in results)
        assert total_violations == 0

    def test_unsorted_timeseries_detects_violations(self, unsorted_timeseries_df, default_rules):
        """Неотсортированный временной ряд — должно быть нарушение."""
        results = validate_consistency(unsorted_timeseries_df, default_rules)
        
        total_violations = sum(r.get('Нарушений', 0) for r in results)
        assert total_violations > 0, "Не обнаружено нарушение порядка в обычном ряду"

    def test_empty_dataframe(self, empty_df, default_rules):
        """Пустой DataFrame — не должно быть ошибок."""
        results = validate_consistency(empty_df, default_rules)
        
        # Должен вернуть пустой список или список без нарушений
        assert isinstance(results, list)

    def test_single_row(self, single_row_df, default_rules):
        """Одна строка — нарушений быть не может."""
        results = validate_consistency(single_row_df, default_rules)
        
        total_violations = sum(r.get('Нарушений', 0) for r in results)
        assert total_violations == 0

    def test_dataframe_with_nans(self, df_with_nans, default_rules):
        """DataFrame с NaN — не должно падать."""
        results = validate_consistency(df_with_nans, default_rules)
        
        assert isinstance(results, list)

    def test_explicit_rules(self, sample_panel_df):
        """Явно переданные правила должны работать."""
        rules = {
            "consistency": [
                {
                    "name": "Хронологический порядок",
                    "type": "chronology",
                    "description": "Проверка порядка лет",
                    "columns": ["Year"],
                    "severity": "error"
                }
            ]
        }
        
        results = validate_consistency(sample_panel_df, rules)
        assert len(results) > 0


# ═══════════════════════════════════════════════════════════
# ТЕСТЫ ДЛЯ validate_regular_step
# ═══════════════════════════════════════════════════════════

class TestValidateRegularStep:
    """Тесты проверки регулярности временного шага."""

    def test_regular_annual_series(self, simple_timeseries_df, default_rules):
        """Регулярный годовой ряд — 0 пропусков."""
        results, masks, freq_info, sort_info = validate_regular_step(
            simple_timeseries_df, default_rules, date_col='Year'
        )
        
        # Данные отсортированы
        assert sort_info.get('is_sorted') is True
        
        # Частота должна быть определена
        assert freq_info.get('inferred_freq') is not None

    def test_unsorted_series_returns_sort_info(self, unsorted_timeseries_df, default_rules):
        """Неотсортированный ряд — функция должна вернуть is_sorted=False."""
        results, masks, freq_info, sort_info = validate_regular_step(
            unsorted_timeseries_df, default_rules, date_col='Year'
        )
        
        assert sort_info.get('is_sorted') is False
        assert sort_info.get('sort_violations', 0) > 0

    def test_panel_data_sorted(self, sample_panel_df, default_rules):
        """Панельные данные отсортированы — 5 групп."""
        results, masks, freq_info, sort_info = validate_regular_step(
            sample_panel_df, default_rules, date_col='Year'
        )
        
        assert sort_info.get('is_sorted') is True
        assert sort_info.get('group_col') == 'Country'
        assert len(results) == 5  # 5 стран

    def test_panel_data_unsorted(self, unsorted_panel_df, default_rules):
        """Панельные данные не отсортированы — должна быть информация о сортировке."""
        results, masks, freq_info, sort_info = validate_regular_step(
            unsorted_panel_df, default_rules, date_col='Year'
        )
        
        assert sort_info.get('is_sorted') is False
        assert sort_info.get('sort_violations', 0) > 0
        assert sort_info.get('group_col') == 'Country'

    def test_series_with_gaps(self, timeseries_with_gaps_df, default_rules):
        """Ряд с пропуском года — должны быть обнаружены пропуски."""
        results, masks, freq_info, sort_info = validate_regular_step(
            timeseries_with_gaps_df, default_rules, date_col='Year'
        )
        
        if sort_info.get('is_sorted'):
            # Если отсортировано — должны быть пропуски
            total_gaps = sum(r.get('Пропусков', 0) for r in results)
            assert total_gaps > 0, "Не обнаружен пропуск года 2015"

    def test_empty_dataframe(self, empty_df, default_rules):
        """Пустой DataFrame — не должно падать."""
        results, masks, freq_info, sort_info = validate_regular_step(
            empty_df, default_rules, date_col='Year'
        )
        
        assert isinstance(results, list)
        assert isinstance(sort_info, dict)

    def test_auto_detect_date_col(self, simple_timeseries_df, default_rules):
        """Автоопределение временной колонки."""
        results, masks, freq_info, sort_info = validate_regular_step(
            simple_timeseries_df, default_rules, date_col=None
        )
        
        assert sort_info.get('date_col') == 'Year'

    def test_returns_four_values(self, simple_timeseries_df, default_rules):
        """Функция должна возвращать ровно 4 значения."""
        result = validate_regular_step(simple_timeseries_df, default_rules, date_col='Year')
        
        assert len(result) == 4
        results, masks, freq_info, sort_info = result
        
        assert isinstance(results, list)
        assert isinstance(masks, dict)
        assert isinstance(freq_info, dict)
        assert isinstance(sort_info, dict)


# ═══════════════════════════════════════════════════════════
# ИНТЕГРАЦИОННЫЕ ТЕСТЫ
# ══════════════════════════════════════════════════════════

class TestIntegration:
    """Интеграционные тесты — проверка взаимодействия модулей."""

    def test_consistency_then_regularity(self, unsorted_panel_df, default_rules):
        """
        Сценарий: сначала проверка согласованности, потом регулярности.
        Обе должны обнаружить проблемы с сортировкой.
        """
        # 1. Проверка согласованности
        consistency_results = validate_consistency(unsorted_panel_df, default_rules)
        consistency_violations = sum(r.get('Нарушений', 0) for r in consistency_results)
        
        # 2. Проверка регулярности
        reg_results, reg_masks, reg_freq, reg_sort = validate_regular_step(
            unsorted_panel_df, default_rules, date_col='Year'
        )
        
        # Обе должны показать проблемы
        assert consistency_violations > 0, "Consistency не обнаружила нарушений"
        assert reg_sort.get('is_sorted') is False, "Regularity не обнаружила проблем с сортировкой"

    def test_sorted_then_clean(self, sample_panel_df, default_rules):
        """
        Сценарий: отсортированные данные — обе проверки проходят.
        """
        consistency_results = validate_consistency(sample_panel_df, default_rules)
        reg_results, reg_masks, reg_freq, reg_sort = validate_regular_step(
            sample_panel_df, default_rules, date_col='Year'
        )
        
        consistency_violations = sum(r.get('Нарушений', 0) for r in consistency_results)
        assert consistency_violations == 0
        assert reg_sort.get('is_sorted') is True


# ═══════════════════════════════════════════════════════════
# ГРАНИЧНЫЕ СЛУЧАИ
# ═══════════════════════════════════════════════════════════

class TestEdgeCases:
    """Тесты граничных случаев."""

    def test_duplicate_years(self, default_rules):
        """Дублирующиеся годы в одной группе."""
        data = {
            'Country': ['A', 'A', 'A'],
            'Year': [2020, 2020, 2021],
            'Value': [10, 20, 30]
        }
        df = pd.DataFrame(data)
        
        results = validate_consistency(df, default_rules)
        assert isinstance(results, list)

    def test_negative_values(self, default_rules):
        """Отрицательные значения (как в реальном датасете)."""
        data = {
            'Country': ['A', 'A', 'A'],
            'Year': [2020, 2021, 2022],
            'Price': [100, -50, 80]
        }
        df = pd.DataFrame(data)
        
        results = validate_consistency(df, default_rules)
        assert isinstance(results, list)

    def test_large_dataset(self, default_rules):
        """Большой датасет (1000 строк)."""
        n = 1000
        data = {
            'Year': list(range(2000, 2000 + n)),
            'Value': np.random.randn(n).cumsum()
        }
        df = pd.DataFrame(data)
        
        results, masks, freq_info, sort_info = validate_regular_step(
            df, default_rules, date_col='Year'
        )
        
        assert sort_info.get('is_sorted') is True

    def test_string_years(self, default_rules):
        """Годы как строки."""
        data = {
            'Year': ['2020', '2021', '2022'],
            'Value': [10, 20, 30]
        }
        df = pd.DataFrame(data)
        
        results = validate_consistency(df, default_rules)
        assert isinstance(results, list)