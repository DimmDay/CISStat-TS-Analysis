"""
tests/test_pipeline_bug.py

Раньше этот файл вручную реализовывал ВНУТРИ теста две копии логики
(правильную и неправильную) и сравнивал их друг с другом — ни разу не
вызывая реальный код приложения. Такой тест истинен всегда, независимо
от состояния кода, и не может обнаружить регресс, если баг снова появится.

Переписано на вызов настоящих функций:
- validate_regular_step (validation/engine.py) -- "карточка"
- compute_regularity_violations (app/validation/regularity.py) -- "пайплайн"

Исторический баг ("пайплайн не учитывает entity_col") уже исправлен:
app.py вызывает compute_regularity_violations с явной передачей
entity_col=_current_entity_col. Эти тесты фиксируют это как
регрессионную защиту на уровне самой функции и на уровне интеграции
с app.py, а не документируют устаревшую проблему.
"""
import os
import re
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from validation.engine import validate_regular_step
from app.validation.regularity import compute_regularity_violations


@pytest.fixture
def panel_df_with_sort_issue():
    """
    Панельные данные с нарушением сортировки (2016 перед 2015).
    5 стран × 31 год, без реальных пропусков лет внутри каждой страны.
    """
    countries = ['Азербайджан', 'Беларусь', 'Казахстан', 'Кыргызстан', 'Молдова']
    years_order = [1994, 1995, 1996, 1997, 1998, 1999, 2000, 2001, 2002, 2003,
                   2004, 2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013,
                   2014, 2016, 2015, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024]

    data = {
        'Country': [c for c in countries for _ in years_order],
        'Year': [y for c in countries for y in years_order],
        'Price': list(np.random.default_rng(0).uniform(20, 100, len(countries) * len(years_order))),
    }
    return pd.DataFrame(data)


class TestCardDetectsSortIssue:
    """"Карточка" (validate_regular_step) должна замечать проблему с сортировкой."""

    def test_card_detects_unsorted_panel_data(self, panel_df_with_sort_issue):
        df = panel_df_with_sort_issue
        results, masks, freq_info, sort_info = validate_regular_step(df, {}, date_col='Year')

        assert sort_info['is_sorted'] is False, "Данные не отсортированы!"
        assert sort_info['sort_violations'] > 0, "Должны быть нарушения сортировки"
        assert sort_info['group_col'] == 'Country', "Должна быть найдена группирующая колонка"


class TestPipelineRespectsEntityGrouping:
    """
    "Пайплайн" (compute_regularity_violations) — регрессионная защита
    от исторического бага "не учитывает группировку по Country".
    """

    def test_with_entity_col_no_false_positive_gaps(self, panel_df_with_sort_issue):
        """
        КРИТЕРИЙ: при явной передаче entity_col='Country' панельные данные
        (без реальных пропусков лет внутри каждой страны) не должны давать
        ложных срабатываний — ровно то, что сейчас и передаётся в app.py.
        """
        df = panel_df_with_sort_issue
        result = compute_regularity_violations(df, date_col='Year', entity_col='Country')

        assert result['gaps_count'] == 0, (
            f"Ложные срабатывания при группировке по Country: {result['gaps_count']}. "
            f"Внутри каждой страны все 31 год присутствуют без пропусков."
        )

    def test_without_entity_col_shows_false_positives(self, panel_df_with_sort_issue):
        """
        ДЕМОНСТРАЦИЯ ПРИЧИНЫ, почему entity_col обязателен: без группировки
        строки разных стран за один и тот же год перемешиваются при сортировке
        по дате, ломая расчёт модального интервала — и почти каждая граница
        между годами ошибочно засчитывается как разрыв.

        Число 30 здесь не случайное: это тот же самый результат, что
        показывал старый (баговый) пайплайн до фикса — сохранено для
        исторической прослеживаемости находки.
        """
        df = panel_df_with_sort_issue
        result = compute_regularity_violations(df, date_col='Year', entity_col=None)

        assert result['gaps_count'] > 0, (
            "Ожидались ложные срабатывания без группировки — если их нет, "
            "поведение функции изменилось и этот тест нужно пересмотреть."
        )

    def test_app_py_always_passes_entity_col_to_pipeline(self):
        """
        Защита от регресса на уровне интеграции: КАЖДЫЙ вызов
        compute_regularity_violations в app.py должен передавать entity_col
        (даже если значение None для непанельных данных) -- а не быть
        переписан обратно на вызов без этого аргумента вообще, как это
        исторически и привело к найденному багу.
        """
        app_py_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"
        )
        with open(app_py_path, encoding="utf-8-sig") as f:
            content = f.read()

        call_positions = [m.start() for m in re.finditer(r"compute_regularity_violations\(", content)]
        assert call_positions, "compute_regularity_violations нигде не вызывается в app.py"

        missing_entity_col_lines = []
        for start in call_positions:
            block = content[start:start + 300]
            if "entity_col" not in block:
                line_no = content[:start].count("\n") + 1
                missing_entity_col_lines.append(line_no)

        assert not missing_entity_col_lines, (
            f"compute_regularity_violations вызывается БЕЗ entity_col на строках: "
            f"{missing_entity_col_lines} -- похоже, исторический баг "
            f"'пайплайн не учитывает группировку' вернулся."
        )
