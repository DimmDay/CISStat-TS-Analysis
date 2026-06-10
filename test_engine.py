# test_engine.py
import pandas as pd
from validation.engine import load_rules, validate_dataframe

# Тестовые данные
df_test = pd.DataFrame({
    "id": [1, 2, 3, None],  # пропуск в required-поле
    "value": [100, -50, 200, 150],  # -50 нарушает min: 0
    "status": ["active", "unknown", "active", "pending"],  # unknown не в домене
    "created_at": ["2024-01-01", "2025-12-31", "invalid", "2024-06-15"]
})

# Загружаем правила (создайте тестовый rules/test_rules.yaml при необходимости)
rules = load_rules("rules/default_rules.yaml")

# Запускаем валидацию
result = validate_dataframe(df_test, rules)

print("✅ Валиден:", result["is_valid"])
print("❌ Ошибки:", len(result["errors"]))
print("⚠️ Предупреждения:", len(result["warnings"]))
if result["errors"]:
    print("\nДетали ошибок:")
    for err in result["errors"][:5]:
        print(f"  • {err}")