# tests/unit/test_rolling.py
"""
Unit-тесты для app/features/rolling.py.

Исторически apply_wma использовал fillna(method='bfill'), несовместимый с
pandas 3. Затем вызов заменили на bfill(), но это оставило методологическую
утечку: начало заполнялось значением будущего полного окна. Task 83 считает
каждый префикс по доступной истории и сохраняет совместимость с pandas 2/3.
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
 
    def test_leading_values_use_available_history_not_future_backfill(self):
        """
        Префикс считается на доступной истории. Backward fill запрещён:
        он подставлял бы значение, рассчитанное по будущему полному окну.
        """
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = apply_wma(series, window=3)
        assert not result.isna().any(), f"Остались NaN: {result.tolist()}"
        assert result.iloc[0] == pytest.approx(1.0)
        assert result.iloc[1] == pytest.approx(5 / 3)
 
    def test_weighted_average_values_correct(self):
        """
        Проверка конкретных значений: на префиксе веса 1..k, затем
        линейно-взвешенное среднее с весами [1, 2, 3] (сумма 6).
        Ожидаемые числа посчитаны и перепроверены отдельно перед фиксом.
        """
        series = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = apply_wma(series, window=3)
        expected = [
            1.0,
            5 / 3,
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
