# test_outliers.py
import pandas as pd
import numpy as np
from validation.outliers import detect_outliers, get_outliers_df

# Генерируем данные с явными выбросами
np.random.seed(42)
df_test = pd.DataFrame({
    "price": np.random.normal(100, 10, 200),  # Норма
    "quantity": np.random.randint(1, 50, 200),
    "rating": np.clip(np.random.normal(4.5, 0.5, 200), 1, 5)
})

# Добавляем выбросы вручную
df_test.loc[10, "price"] = 500   # IQR/Z-score поймают
df_test.loc[45, "quantity"] = -200
df_test.loc[120, "rating"] = 15

# Конфиг
config = {"method": "iqr", "iqr_multiplier": 1.5, "zscore_threshold": 3.0}

report = detect_outliers(df_test, config)
print("📊 Сводка:", report["summary"])
print("\n🔍 Найденные колонки с выбросами:")
for col, info in report["by_column"].items():
    print(f"  • {col}: {info['count']} шт. ({info['rate_pct']}%) | Границы: {info['bounds']}")

print("\n📋 Пример списка для эксперта (первые 5):")
print(get_outliers_df(report, df_test).head())