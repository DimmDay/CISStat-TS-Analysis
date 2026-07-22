# tests/unit/test_transforms.py
"""
Unit-тесты для app/preprocessing/transforms.py::compute_row_properties.
 
Обнаруженный баг (два слоя):
1. hurst_exponent никогда не была импортирована в transforms.py -- NameError
   на каждом вызове, замаскированный `except Exception`, из-за чего
   props['long_memory'] ВСЕГДА показывал '⚠️ Не удалось вычислить'.
2. После добавления импорта выяснилось: _hurst_exponent из app/core/passport.py
   ожидает np.ndarray, а не pd.Series. При передаче Series операция
   np.subtract(series[lag:], series[:-lag]) выравнивает операнды ПО ИНДЕКСУ
   (а не позиционно), потому что series[lag:] и series[:-lag] имеют разные,
   несовпадающие индексы -- в результате Hurst считается неверно (H≈0 вместо
   ожидаемых ~0.5 для случайного блуждания), но БЕЗ ошибки -- то есть баг
   был бы "тихим" даже после фикса импорта, если бы не передать .values.
"""
import numpy as np
import pandas as pd
import pytest
 
from app.preprocessing.transforms import compute_row_properties
 
 
class TestComputeRowPropertiesLongMemory:
    """Тесты для блока 'ДОЛГАЯ ПАМЯТЬ (Hurst Exponent)' внутри compute_row_properties."""
 
    def test_long_memory_is_computed_not_error_placeholder(self):
        """
        КРИТЕРИЙ ПРИЁМКИ ФИКСА: long_memory больше не должен быть заглушкой
        '⚠️ Не удалось вычислить' на нормальных данных.
        """
        rng = np.random.default_rng(42)
        series = pd.Series(rng.normal(0, 1, 200))
        props = compute_row_properties(series, name="test")
 
        assert props["long_memory"] != "⚠️ Не удалось вычислить"
        assert any(
            marker in props["long_memory"]
            for marker in ["Персистентность", "Антиперсистентность", "Случайное блуждание"]
        )
 
    def test_random_walk_gives_sensible_hurst_near_half(self):
        """
        КРИТЕРИЙ ПРИЁМКИ ВТОРОГО СЛОЯ БАГА: для классического случайного
        блуждания H должен быть в разумной окрестности 0.5 (теоретическое
        значение), а не ~0 (что получалось при передаче pd.Series вместо
        .values из-за выравнивания по индексу в np.subtract).
        """
        rng = np.random.default_rng(7)
        random_walk = pd.Series(np.cumsum(rng.normal(0, 1, 300)))
        props = compute_row_properties(random_walk, name="random_walk")
 
        assert "H=" in props["long_memory"]
        h_str = props["long_memory"].split("H=")[1].rstrip(")")
        h_value = float(h_str)
        assert 0.3 < h_value < 0.7, (
            f"H={h_value} слишком далеко от ожидаемых ~0.5 для случайного блуждания -- "
            f"похоже, снова считается по неверно выровненным данным"
        )
 
    def test_long_memory_detail_empty_on_success(self):
        rng = np.random.default_rng(1)
        series = pd.Series(rng.normal(0, 1, 200))
        props = compute_row_properties(series, name="test")
        assert props["long_memory_detail"] == ""
 
    def test_short_series_returns_error(self):
        series = pd.Series([1.0, 2.0, 3.0])
        props = compute_row_properties(series)
        assert "error" in props
 