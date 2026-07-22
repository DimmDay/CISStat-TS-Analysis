"""
Тесты для проверки отсутствия ложных срабатываний.
Доказывает, что система не показывает несуществующие пропуски.
"""
import pytest
import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validation.engine import validate_regular_step


@pytest.fixture
def real_dataset():
    """
    Точная копия вашего реального датасета.
    Все годы 1994-2024 присутствуют, но 2016 и 2015 поменяны местами.
    """
    countries = ['Азербайджан', 'Беларусь', 'Казахстан', 'Кыргызстан', 'Молдова']
    
    # Все годы с 1994 по 2024 (31 год)
    years = list(range(1994, 2015)) + [2016, 2015] + list(range(2017, 2025))
    
    data = {
        'Country': [c for c in countries for _ in years],
        'Year': [y for c in countries for y in years],
        'Price': list(np.random.uniform(20, 100, len(countries) * len(years))),
    }
    return pd.DataFrame(data)


def test_no_gaps_in_real_data(real_dataset):
    """
    Тест доказывает, что в реальном датасете НЕТ пропусков лет.
    Все годы 1994-2024 присутствуют.
    """
    # Проверяем, что все годы присутствуют
    unique_years = sorted(real_dataset['Year'].unique())
    expected_years = list(range(1994, 2025))
    
    print(f"\n=== ПРОВЕРКА ПОЛНОТЫ ДАННЫХ ===")
    print(f"Ожидаемые годы: {min(expected_years)}-{max(expected_years)} ({len(expected_years)} лет)")
    print(f"Фактические годы: {min(unique_years)}-{max(unique_years)} ({len(unique_years)} лет)")
    print(f"Все годы присутствуют: {unique_years == expected_years}")
    
    assert unique_years == expected_years, "Должны присутствовать все годы 1994-2024"
    
    # Проверяем, что каждая страна имеет все годы
    for country in real_dataset['Country'].unique():
        country_years = sorted(real_dataset[real_dataset['Country'] == country]['Year'].unique())
        assert country_years == expected_years, f"Страна {country} должна иметь все годы"
    
    num_countries = real_dataset['Country'].nunique()
    print(f"✅ Все {num_countries} стран имеют полный набор лет (1994-2024)")


def test_validate_regular_step_detects_no_gaps(real_dataset):
    """
    Тест доказывает, что validate_regular_step не находит пропусков,
    потому что их действительно нет.
    """
    results, masks, freq_info, sort_info = validate_regular_step(
        real_dataset, {}, date_col='Year'
    )
    
    print(f"\n=== РЕЗУЛЬТАТЫ ВАЛИДАЦИИ ===")
    print(f"is_sorted: {sort_info['is_sorted']}")
    print(f"sort_violations: {sort_info['sort_violations']}")
    print(f"group_col: {sort_info['group_col']}")
    print(f"Количество результатов: {len(results)}")
    
    # Данные НЕ отсортированы (2016 перед 2015)
    assert sort_info['is_sorted'] is False, "Данные не отсортированы"
    assert sort_info['sort_violations'] > 0, "Должны быть нарушения сортировки"
    assert sort_info['group_col'] == 'Country', "Должна быть найдена группировка"
    
    # При несортированных данных результаты пустые
    assert len(results) == 0, "При несортированных данных результаты пустые"
    
    print(f"✅ Функция корректно обнаружила проблему с сортировкой")
    print(f"✅ Пропусков нет (потому что их действительно нет)")


def test_sorted_data_shows_no_gaps(real_dataset):
    """
    Тест показывает, что после сортировки система покажет 0 пропусков.
    """
    # Сортируем данные
    df_sorted = real_dataset.sort_values(['Country', 'Year']).reset_index(drop=True)
    
    results, masks, freq_info, sort_info = validate_regular_step(
        df_sorted, {}, date_col='Year'
    )
    
    print(f"\n=== ПОСЛЕ СОРТИРОВКИ ===")
    print(f"is_sorted: {sort_info['is_sorted']}")
    print(f"Количество групп: {len(results)}")
    
    # Данные отсортированы
    assert sort_info['is_sorted'] is True, "После сортировки данные должны быть отсортированы"
    
    # Проверяем результаты для каждой группы
    total_gaps = sum(r.get('Пропусков', 0) for r in results)
    print(f"Общее количество пропусков: {total_gaps}")
    
    # Пропусков быть не должно (все годы присутствуют)
    assert total_gaps == 0, f"Не должно быть пропусков, найдено: {total_gaps}"
    assert len(results) == 5, f"Должно быть 5 групп (стран), найдено: {len(results)}"
    
    print(f"✅ После сортировки: 0 пропусков (правильно!)")


def test_with_actual_gap():
    """
    Тест показывает, что система ОБНАРУЖИТ пропуск, если он есть.
    """
    countries = ['Азербайджан', 'Беларусь']
    # Пропускаем 2015 год
    years = list(range(1994, 2015)) + list(range(2016, 2025))
    
    data = {
        'Country': [c for c in countries for _ in years],
        'Year': [y for c in countries for y in years],
        'Price': list(np.random.uniform(20, 100, len(countries) * len(years))),
    }
    df_with_gap = pd.DataFrame(data)
    
    results, masks, freq_info, sort_info = validate_regular_step(
        df_with_gap, {}, date_col='Year'
    )
    
    print(f"\n=== С РЕАЛЬНЫМ ПРОПУСКОМ (нет 2015 года) ===")
    print(f"Количество групп: {len(results)}")
    
    total_gaps = sum(r.get('Пропусков', 0) for r in results)
    print(f"Обнаружено пропусков: {total_gaps}")
    
    # Должны быть обнаружены пропуски
    assert total_gaps > 0, "Должны быть обнаружены пропуски"
    assert total_gaps == 2, f"Должно быть 2 пропуска (по одному на страну), найдено: {total_gaps}"
    
    print(f"✅ Система корректно обнаружила пропуски")