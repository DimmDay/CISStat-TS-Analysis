"""
Тесты для проверки масок нарушений согласованности.
Воспроизводит баг: нарушения найдены, но таблица пустая.
"""
import pytest
import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validation.engine import validate_consistency


@pytest.fixture
def unsorted_panel_df():
    """
    Панельные данные с нарушением хронологии: 2016 идёт перед 2015.
    Точная копия структуры реального датасета.
    """
    countries = ['Азербайджан', 'Беларусь', 'Казахстан', 'Кыргызстан', 'Молдова']
    years_order = [2014, 2016, 2015, 2017, 2018]  # Нарушение: 2016 перед 2015
    
    data = {
        'Country': [c for c in countries for _ in years_order],
        'Year': [y for c in countries for y in years_order],
        'Price': list(np.random.uniform(20, 100, len(countries) * len(years_order))),
    }
    return pd.DataFrame(data)


def test_consistency_detects_violations(unsorted_panel_df):
    """
    Тест доказывает, что функция находит 5 нарушений.
    """
    results = validate_consistency(unsorted_panel_df, {})
    
    total_violations = sum(r.get('Нарушений', 0) for r in results)
    
    print(f"\n=== РЕЗУЛЬТАТЫ ВАЛИДАЦИИ ===")
    print(f"Количество правил: {len(results)}")
    for r in results:
        print(f"  - {r.get('Правило')}: {r.get('Нарушений')} нарушений")
    
    print(f"Всего нарушений: {total_violations}")
    
    assert total_violations == 5, f"Ожидалось 5 нарушений, получено {total_violations}"


def test_consistency_returns_masks(unsorted_panel_df):
    """
    Тест проверяет, что функция возвращает маски строк с нарушениями.
    
    ОЖИДАЕМЫЙ РЕЗУЛЬТАТ:
    - Функция должна вернуть не только количество нарушений,
      но и маски строк, где эти нарушения находятся.
    - Маски нужны для отображения таблицы в пайплайне.
    """
    results = validate_consistency(unsorted_panel_df, {})
    
    print(f"\n=== ПРОВЕРКА МАСОК ===")
    print(f"Тип results: {type(results)}")
    print(f"Содержимое results: {results}")
    
    # Проверяем, есть ли маски в результатах
    has_masks = any('mask' in r or 'indices' in r for r in results)
    
    print(f"Есть маски в результатах: {has_masks}")
    
    # Если масок нет — это баг!
    if not has_masks:
        print("⚠️ БАГ: Функция не возвращает маски строк с нарушениями!")
        print("   Таблица в пайплайне будет пустой!")
    
    # Этот тест должен провалиться, пока мы не исправим функцию
    assert has_masks, "Функция должна возвращать маски строк с нарушениями!"


def test_consistency_mask_points_to_violations(unsorted_panel_df):
    """
    Тест проверяет, что маски указывают на ОБЕ строки нарушения.
    
    ЛОГИКА: Когда последовательность [2014, 2016, 2015, 2017, 2018],
    нарушают порядок ОБЕ строки: 2016 и 2015.
    """
    results = validate_consistency(unsorted_panel_df, {})
    
    # Находим строки с нарушениями
    violation_indices = []
    for r in results:
        if 'mask' in r:
            mask = r['mask']
            indices = unsorted_panel_df[mask].index.tolist()
            violation_indices.extend(indices)
    
    print(f"\n=== ИНДЕКСЫ НАРУШЕНИЙ ===")
    print(f"Индексы: {violation_indices}")
    
    # Проверяем, что индексы указывают на строки с 2016 ИЛИ 2015 годом
    for idx in violation_indices:
        year = unsorted_panel_df.loc[idx, 'Year']
        print(f"  Строка {idx}: Year={year}")
        # Маска должна указывать на 2016 или 2015 (обе строки нарушения)
        assert year in [2016, 2015], f"Маска должна указывать на 2016 или 2015, найдено {year}"
    
    # Должно быть 10 строк (5 пар нарушений: 2016 и 2015 для каждой страны)
    assert len(violation_indices) == 10, f"Должно быть 10 строк (5 пар), найдено {len(violation_indices)}"
    
    print(f"✅ Маска правильно указывает на обе строки нарушения (2016 и 2015)")