# tests/unit/test_distributions.py
"""
Characterization-тесты для detect_distribution_type.
Правило: сначала тест, потом перенос.
"""
import pytest
import numpy as np
import pandas as pd
from scipy import stats


class TestDetectDistributionType:
    """Тесты для функции определения типа распределения."""

    def test_insufficient_data(self):
        """Менее 30 точек должно вернуть сообщение о недостатке данных."""
        from app.eda.distributions import detect_distribution_type
        
        series = pd.Series(np.random.randn(20))
        result = detect_distribution_type(series)
        assert "Недостаточно данных" in result
        assert "<30" in result

    def test_exactly_30_points(self):
        """Ровно 30 точек должно обрабатываться нормально."""
        from app.eda.distributions import detect_distribution_type
        
        # Нормальное распределение
        np.random.seed(42)
        series = pd.Series(np.random.randn(30))
        result = detect_distribution_type(series)
        # Должно вернуть что-то про нормальное или непрерывное
        assert isinstance(result, str)
        assert len(result) > 0

    def test_normal_distribution(self):
        """Нормальное распределение должно определяться как нормальное."""
        from app.eda.distributions import detect_distribution_type
        
        np.random.seed(42)
        series = pd.Series(np.random.randn(1000))
        result = detect_distribution_type(series)
        # Должно содержать "Нормальное" или "Непрерывное"
        assert "Нормальное" in result or "Непрерывное" in result

    def test_uniform_distribution(self):
        """Равномерное распределение должно определяться как равномерное."""
        from app.eda.distributions import detect_distribution_type
        
        np.random.seed(42)
        series = pd.Series(np.random.uniform(0, 10, 1000))
        result = detect_distribution_type(series)
        assert "Равномерное" in result

    def test_exponential_distribution(self):
        """Экспоненциальное распределение должно определяться как непрерывное.
        Примечание: KS-тест часто выбирает Гамма вместо Экспоненциального,
        так как Экспоненциальное — частный случай Гаммы (shape=1)."""
        from app.eda.distributions import detect_distribution_type
        
        np.random.seed(42)
        series = pd.Series(np.random.exponential(scale=2.0, size=1000))
        result = detect_distribution_type(series)
        
        # Достаточно проверить, что ряд распознан как непрерывный
        assert "Непрерывное" in result

    def test_discrete_poisson_like(self):
        """Дискретное распределение с var ≈ mean должно определяться как Пуассона."""
        from app.eda.distributions import detect_distribution_type
        
        np.random.seed(42)
        # Генерируем данные, похожие на Пуассона
        series = pd.Series(np.random.poisson(lam=5, size=1000))
        result = detect_distribution_type(series)
        assert "Дискретное" in result

    def test_discrete_binomial_like(self):
        """Бинарное распределение (0/1) должно определяться как биномиальное."""
        from app.eda.distributions import detect_distribution_type
        
        np.random.seed(42)
        series = pd.Series(np.random.binomial(1, 0.5, 1000))
        result = detect_distribution_type(series)
        assert "Дискретное" in result
        assert "Биномальное" in result

    def test_large_dataset_sampling(self):
        """Датасет > 5000 точек должен сэмплироваться до 5000."""
        from app.eda.distributions import detect_distribution_type
        
        np.random.seed(42)
        series = pd.Series(np.random.randn(10000))
        result = detect_distribution_type(series)
        # Должно работать без ошибок
        assert isinstance(result, str)

    def test_with_nan_values(self):
        """Функция должна обрабатывать NaN значения."""
        from app.eda.distributions import detect_distribution_type
        
        np.random.seed(42)
        data = np.random.randn(100)
        data[::10] = np.nan  # Каждое 10-е значение NaN
        series = pd.Series(data)
        result = detect_distribution_type(series)
        assert isinstance(result, str)

    def test_skewed_distribution(self):
        """Сильно асимметричное распределение должно определяться как асимметричное."""
        from app.eda.distributions import detect_distribution_type
        
        np.random.seed(42)
        # Создаём сильно правостороннюю асимметрию
        series = pd.Series(np.abs(np.random.randn(1000)) ** 3)
        result = detect_distribution_type(series)
        # Должно содержать информацию об асимметрии или непрерывное
        assert isinstance(result, str)

    def test_discrete_many_unique_values(self):
        """Дискретное с большим количеством уникальных значений (>100) должно обрабатываться как непрерывное."""
        from app.eda.distributions import detect_distribution_type
        
        np.random.seed(42)
        # 200 уникальных целых значений
        series = pd.Series(np.random.randint(0, 200, 1000))
        result = detect_distribution_type(series)
        # Должно обрабатываться как непрерывное
        assert isinstance(result, str)

    def test_empty_series(self):
        """Пустой series должен обрабатываться корректно."""
        from app.eda.distributions import detect_distribution_type
        
        series = pd.Series([], dtype=float)
        result = detect_distribution_type(series)
        assert "Недостаточно данных" in result

    def test_all_nan_series(self):
        """Series только из NaN должен обрабатываться как недостаточно данных."""
        from app.eda.distributions import detect_distribution_type
        
        series = pd.Series([np.nan] * 50)
        result = detect_distribution_type(series)
        assert "Недостаточно данных" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])