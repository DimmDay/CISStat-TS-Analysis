import pandas as pd
import numpy as np
from pathlib import Path

# Создаём директорию, если не существует
Path('tests/fixtures').mkdir(parents=True, exist_ok=True)

# Устанавливаем seed для воспроизводимости
np.random.seed(42)

# Параметры
n_points = 110
start_date = '2015-01-01'

# Создаём временную шкалу (месячная частота)
dates = pd.date_range(start=start_date, periods=n_points, freq='MS')

# Генерируем value с характеристиками из snapshot:
# - trend slope ≈ 0.45
# - seasonality strength ≈ 0.91
# - mean ≈ 124.8, std ≈ 15.8
# - min ≈ 92.8, max ≈ 155.8

# Базовый тренд (восходящий)
trend = np.linspace(100, 150, n_points)

# Сезонность (период 12 месяцев, амплитуда ~15)
seasonality = 15 * np.sin(2 * np.pi * np.arange(n_points) / 12)

# Шум (для создания нестационарности и реалистичности)
noise = np.random.normal(0, 6, n_points)

# Итоговое значение
value = trend + seasonality + noise

# Генерируем ковариаты
# covariate_1 должна сильно коррелировать с value (corr ≈ 0.94)
covariate_1 = value * 0.85 + np.random.normal(0, 4, n_points)

# covariate_2 должна слабо коррелировать с value (corr ≈ 0.05)
covariate_2 = np.random.normal(50, 10, n_points)

# Создаём DataFrame
df = pd.DataFrame({
    'date': dates,
    'value': value,
    'covariate_1': covariate_1,
    'covariate_2': covariate_2
})

# Проверяем характеристики
print(f"Количество точек: {len(df)}")
print(f"Диапазон дат: {df['date'].min()} - {df['date'].max()}")
print(f"\nСтатистики value:")
print(f"  Mean: {df['value'].mean():.2f}")
print(f"  Std: {df['value'].std():.2f}")
print(f"  Min: {df['value'].min():.2f}")
print(f"  Max: {df['value'].max():.2f}")
print(f"\nКорреляции:")
print(f"  value vs covariate_1: {df['value'].corr(df['covariate_1']):.3f}")
print(f"  value vs covariate_2: {df['value'].corr(df['covariate_2']):.3f}")

# Сохраняем в CSV
df.to_csv('tests/fixtures/golden_dataset.csv', index=False)
print(f"\n✅ Датасет сохранён в tests/fixtures/golden_dataset.csv")