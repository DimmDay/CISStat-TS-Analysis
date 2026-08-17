# tests/unit/test_rolling.py
"""
Unit-тесты для app/features/rolling.py.
 
Обнаруженный баг: apply_wma использовал smoothed.fillna(method='bfill').
Параметр `method` в DataFrame/Series.fillna() был deprecated в pandas 2.1
и ПОЛНОСТЬЮ УДАЛЁН в pandas 3.0 -- на pandas 3.0.2 (версия из requirements.txt
и фактически установленная в .venv проекта) вызов гарантированно падает
с TypeError при каждом использовании метода сглаживания 'WMA'.
"""
import numpy as np
import pandas as pd
import pytest
 
from app.features.rolling import apply_wma, apply_smoothing
 
 
class TestApplyWma:
 
    def test_does_not_raise_typeerror_on_pandas3(self):
        """
        КРИТЕРИЙ ПРИЁМКИ ФИКСА: вызов не должен падать с TypeError
        из-за устаревшего аргумента method= в fillna().
        """
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = apply_wma(series, window=3)
        assert isinstance(result, pd.Series)
 
    def test_leading_values_backfilled_not_nan(self):
        """
        Ведущие NaN (от rolling с window=3, center=False) должны быть
        заполнены методом backward fill, а не остаться NaN.
        """
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = apply_wma(series, window=3)
        assert not result.isna().any(), f"Остались NaN: {result.tolist()}"
 
    def test_weighted_average_values_correct(self):
        """
        Проверка конкретных значений: линейно-взвешенное среднее с весами
        [1, 2, 3] (сумма 6) для window=3, плюс backward-fill ведущих NaN.
        Ожидаемые числа посчитаны и перепроверены отдельно перед фиксом.
        """
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = apply_wma(series, window=3)
        expected = [
            2 + 1 / 3,  # backfill от первого валидного значения (индекс 2)
            2 + 1 / 3,  # backfill
            2 + 1 / 3,  # (1*1 + 2*2 + 3*3) / 6
            3 + 1 / 3,  # (2*1 + 3*2 + 4*3) / 6
            4 + 1 / 3,  # (3*1 + 4*2 + 5*3) / 6
        ]
        for actual, exp in zip(result.tolist(), expected):
            assert actual == pytest.approx(exp, rel=1e-9)
 
    def test_via_apply_smoothing_dispatch(self):
        """Тот же сценарий, но через универсальную apply_smoothing (как вызывается в app.py)."""
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = apply_smoothing(series, method="WMA", window=3)
        assert isinstance(result, pd.Series)
        assert not result.isna().any()
 