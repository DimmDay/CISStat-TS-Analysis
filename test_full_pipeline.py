# test_full_pipeline.py
import pandas as pd
from validation.engine import load_rules, validate_dataframe
from validation.missing import analyze_missing
from validation.outliers import detect_outliers

# 1. Тестовые данные
df = pd.DataFrame({
    "id": range(1, 51),
    "price": [10, 20, None, 30, -5] + list(range(40, 85)),  # пропуск + отрицательное
    "status": ["A"]*48 + ["INVALID", "B"],                   # доменная ошибка
    "created_at": pd.date_range("2024-01-01", periods=50),
    "score": [85, 90, None, 78, 950] + list(range(80, 125))  # пропуск + выброс
})

# 2. Загружаем правила (убедитесь, что rules/default_rules.yaml существует)
rules = load_rules()

# 3. Запуск пайплайна
val_res = validate_dataframe(df, rules)
miss_res = analyze_missing(df, rules.get("missing", {}))
outl_res = detect_outliers(df, rules.get("outliers", {}))

print("✅ ВАЛИДАЦИЯ СХЕМЫ:", "OK" if val_res["is_valid"] else f"Ошибок: {len(val_res['errors'])}")
print("📦 ПРОПУСКИ:", miss_res["summary"]["total_missing"], "шт.")
print("🔺 ВЫБРОСЫ:", outl_res["summary"]["total_outliers"], "шт.")
print("📊 СТОЛБЦЫ С ПРОБЛЕМАМИ:", list(set(list(miss_res["by_column"].keys()) + list(outl_res["by_column"].keys()))))