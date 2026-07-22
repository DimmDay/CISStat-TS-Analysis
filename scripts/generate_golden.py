# scripts/generate_golden.py
import pandas as pd
import numpy as np
from pathlib import Path

# Создаем папку fixtures, если её нет
fixtures_dir = Path(__file__).parent.parent / "tests" / "fixtures"
fixtures_dir.mkdir(parents=True, exist_ok=True)

# Генерируем эталонный временной ряд
np.random.seed(42)  # Жесткая фиксация seed для воспроизводимости!
dates = pd.date_range(start='2015-01-01', end='2023-12-01', freq='MS')  # Месячные данные
n = len(dates)

# Тренд + Сезонность + Шум
trend = np.linspace(100, 150, n)
seasonality = 10 * np.sin(2 * np.pi * dates.month / 12)
noise = np.random.normal(0, 2, n)
values = trend + seasonality + noise

df = pd.DataFrame({'date': dates, 'value': values})
output_path = fixtures_dir / "golden_dataset.csv"
df.to_csv(output_path, index=False)

print(f"✅ Golden Dataset создан: {output_path}")
print(f"   Размер: {len(df)} строк, {len(df.columns)} колонок")
print(f"   Период: {df['date'].min()} — {df['date'].max()}")