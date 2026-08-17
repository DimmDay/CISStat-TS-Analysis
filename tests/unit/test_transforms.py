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

# tests/unit/test_transforms.py (добавить в существующий файл рядом с TestComputeRowPropertiesLongMemory)
"""
Тесты для run_stationarity_tests.
 
Обнаруженный баг: `from statsmodels.tsa.stattools import PhillipsPerron`
стоял в общем try/except вместе с adfuller/kpss. PhillipsPerron не
существует в statsmodels (это класс из библиотеки `arch.unitroot`) --
импорт ВСЕГДА кидал ImportError, который ловился внешним
`except ImportError` и обрушивал ВСЮ функцию до {'error': ...},
даже не доходя до ADF/KPSS/консенсуса.
 
Уже существующий fallback для PP ('если PP недоступен, используем ADF
как proxy') был написан правильно, но не мог сработать, потому что
импорт был вынесен за пределы своего локального try/except -- ровно
как уже сделано для Zivot-Andrews.
"""
import numpy as np
import pandas as pd
 
from app.preprocessing.transforms import run_stationarity_tests
 
 
class TestRunStationarityTests:
 
    def test_does_not_return_top_level_error_for_valid_series(self):
        """
        КРИТЕРИЙ ПРИЁМКИ ФИКСА: функция должна доходить до ADF/KPSS/консенсуса,
        а не обрываться на {'error': 'Не установлены необходимые библиотеки: ...'}
        из-за некорректного импорта PhillipsPerron.
        """
        rng = np.random.default_rng(42)
        white_noise = pd.Series(rng.normal(0, 1, 200))
        results = run_stationarity_tests(white_noise)
 
        assert "error" not in results, f"Функция обрушилась целиком: {results.get('error')}"
        assert "adf" in results
        assert "kpss" in results
        assert "pp" in results
        assert "consensus" in results
        assert "recommendation" in results
 
    def test_white_noise_detected_as_stationary(self):
        """Белый шум должен быть распознан как стационарный (ADF + KPSS согласны)."""
        rng = np.random.default_rng(1)
        white_noise = pd.Series(rng.normal(0, 1, 300))
        results = run_stationarity_tests(white_noise)
 
        assert bool(results["adf"]["is_stationary"]) is True
        assert results["consensus"] in ("stationary", "trend-stationary")
 
    def test_pp_result_has_expected_keys_regardless_of_arch_availability(self):
        """
        pp должен иметь валидную структуру независимо от того, установлен ли
        пакет arch: либо реальный расчёт (stat/pvalue/is_stationary), либо
        fallback на ADF (тоже stat/pvalue/is_stationary + note).
        """
        rng = np.random.default_rng(2)
        series = pd.Series(rng.normal(0, 1, 150))
        results = run_stationarity_tests(series)
 
        assert "pp" in results
        assert "stat" in results["pp"]
        assert "pvalue" in results["pp"]
        assert "is_stationary" in results["pp"]
 
    def test_za_present_with_fallback_note_or_real_result(self):
        """Zivot-Andrews (уже был защищён локальным try) должен быть на месте, как и раньше."""
        rng = np.random.default_rng(3)
        series = pd.Series(rng.normal(0, 1, 150))
        results = run_stationarity_tests(series)
        assert "za" in results
 
    def test_short_series_returns_error(self):
        """Ряд короче 30 точек -- это осознанная валидация, а не баг: error ожидаем."""
        series = pd.Series(np.arange(10.0))
        results = run_stationarity_tests(series)
        assert "error" in results
 
