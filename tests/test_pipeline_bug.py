"""
Тест, который воспроизводит баг: противоречие между карточкой и пайплайном.
"""
import pytest
import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validation.engine import validate_regular_step


@pytest.fixture
def panel_df_with_sort_issue():
    """
    Панельные данные с нарушением сортировки (2016 перед 2015).
    Это точная копия структуры вашего датасета.
    """
    countries = ['Азербайджан', 'Беларусь', 'Казахстан', 'Кыргызстан', 'Молдова']
    years_order = [1994, 1995, 1996, 1997, 1998, 1999, 2000, 2001, 2002, 2003,
                   2004, 2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013,
                   2014, 2016, 2015, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024]
    
    data = {
        'Country': [c for c in countries for _ in years_order],
        'Year': [y for c in countries for y in years_order],
        'Price': list(np.random.uniform(20, 100, len(countries) * len(years_order))),
    }
    return pd.DataFrame(data)


def test_pipeline_vs_card_contradiction(panel_df_with_sort_issue):
    """
    Тест воспроизводит противоречие:
    - validate_regular_step (карточка) возвращает 0 пропусков
    - _compute_regularity_violations (пайплайн) возвращает 30 пропусков
    
    Проблема: пайплайн не учитывает группировку по Country.
    """
    df = panel_df_with_sort_issue
    
    # 1. Вызываем validate_regular_step (как в карточке)
    results, masks, freq_info, sort_info = validate_regular_step(
        df, {}, date_col='Year'
    )
    
    # 2. Проверяем, что функция обнаружила проблему с сортировкой
    assert sort_info['is_sorted'] is False, "Данные не отсортированы!"
    assert sort_info['sort_violations'] > 0, "Должны быть нарушения сортировки"
    assert sort_info['group_col'] == 'Country', "Должна быть найдена группирующая колонка"
    
    # 3. Симулируем логику пайплайна (НЕПРАВИЛЬНУЮ)
    # Пайплайн делает: df.sort_values('Year').diff() > modal * 1.5
    # Это НЕ учитывает группировку по Country!
    df_temp = df.copy()
    df_temp['Year'] = pd.to_datetime(df_temp['Year'], format='%Y')
    df_sorted = df_temp.sort_values('Year')
    intervals = df_sorted['Year'].diff()
    modal = intervals.mode().iloc[0]
    gaps_wrong = (intervals > modal * 1.5).sum()
    
    # 4. Показываем противоречие
    print(f"\n=== ПРОТИВОРЕЧИЕ ===")
    print(f"Карточка (validate_regular_step):")
    print(f"  - is_sorted: {sort_info['is_sorted']}")
    print(f"  - sort_violations: {sort_info['sort_violations']}")
    print(f"  - group_col: {sort_info['group_col']}")
    print(f"  - Пропусков: {sum(r.get('Пропусков', 0) for r in results)}")
    
    print(f"\nПайплайн (_compute_regularity_violations):")
    print(f"  - 'Пропусков': {gaps_wrong}")
    print(f"  - Проблема: не учитывает группировку по Country!")
    
    # 5. Правильная логика (с группировкой)
    gaps_correct = 0
    for country, group in df.groupby('Country'):
        group_sorted = group.sort_values('Year')
        group_intervals = pd.to_datetime(group_sorted['Year'], format='%Y').diff()
        group_modal = group_intervals.mode().iloc[0]
        gaps_correct += (group_intervals > group_modal * 1.5).sum()
    
    print(f"\nПравильный подсчёт (с группировкой):")
    print(f"  - Пропусков: {gaps_correct}")
    
    # 6. Доказываем, что пайплайн считает неправильно
    assert gaps_wrong > gaps_correct, "Пайплайн должен давать больше ложных срабатываний!"
    assert gaps_correct == 0, "При правильной логике пропусков быть не должно!"


def test_correct_pipeline_logic(panel_df_with_sort_issue):
    """
    Тест показывает, как ДОЛЖНА работать функция в пайплайне.
    """
    df = panel_df_with_sort_issue
    
    # Правильная логика: сначала проверить сортировку, потом считать пропуски внутри групп
    results, masks, freq_info, sort_info = validate_regular_step(
        df, {}, date_col='Year'
    )
    
    # Если данные не отсортированы — пайплайн НЕ ДОЛЖЕН показывать пропуски
    if not sort_info['is_sorted']:
        # Пайплайн должен показать предупреждение и кнопку сортировки
        # А не считать ложные пропуски
        assert len(results) == 0, "При несортированных данных результатов быть не должно"
        assert sort_info['sort_violations'] > 0, "Должны быть нарушения сортировки"