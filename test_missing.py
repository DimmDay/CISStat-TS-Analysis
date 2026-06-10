# test_missing.py
import pandas as pd
from validation.missing import analyze_missing, get_expert_list_df

# Тестовые данные с разными паттернами пропусков
df_test = pd.DataFrame({
    "id": range(1, 21),
    "value": [10, 20, None, None, None, None, None, 80, 90, 100, 
              None, None, None, None, None, 160, 170, 180, 190, 200],
    "status": ["A", "B", None, "D", "E", None, None, None, None, None,
               "K", "L", "M", "N", "O", "P", None, None, None, None],
    "date": pd.date_range("2024-01-01", periods=20)
})

# Конфиг из YAML (можно подгрузить через load_rules)
config = {
    "report_only": True,
    "critical_threshold": 0.1,
    "critical_columns": ["id", "value"]
}

report = analyze_missing(df_test, config)

print("📊 Сводка:", report["summary"])
print("🚨 Критические алерты:", report["critical_alerts"])
print("📋 Паттерны:", [p["description"] for p in report["patterns"]])
print("\n📝 Список для эксперта (первые 5 записей):")
print(get_expert_list_df(report).head())