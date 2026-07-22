# test_regular.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from validation.engine import validate_regular_step
import pandas as pd

#  ЯВНО УКАЗЫВАЕМ ПРАВИЛЬНЫЙ ФАЙЛ
file_path = "TEST_dataset_FAO_price_sweet_been_CIS_27.04.26_wide_long (1).xlsx"

if not os.path.exists(file_path):
    print(f"❌ Файл не найден: {file_path}")
    print(f"Текущая директория: {os.getcwd()}")
    print("Доступные xlsx файлы:")
    for f in os.listdir('.'):
        if f.endswith('.xlsx'):
            print(f"  - {f}")
    exit(1)

print(f"📄 Используем файл: {file_path}")

# Загружаем данные
df = pd.read_excel(file_path)
print(f" Загружено {len(df)} строк × {len(df.columns)} колонок")
print(f" Колонки: {list(df.columns)}")

# Проверяем порядок данных ДО сортировки
print("\n🔍 Порядок данных ДО сортировки (первые 15 строк):")
print(df[['Country', 'Year']].head(15).to_string())

# Вызываем функцию
result = validate_regular_step(df, {}, date_col='Year')

print(f"\n✅ Функция вернула {len(result)} значений")

if len(result) == 4:
    results, masks, freq_info, sort_info = result
    print(f"\n📊 Результаты:")
    print(f"  - Количество групп: {len(results)}")
    for r in results:
        print(f"    • {r['Группа']}: {r['Пропусков']} пропусков, статус: {r['Статус']}")
    
    print(f"\n🔍 Информация о сортировке:")
    print(f"  - is_sorted: {sort_info.get('is_sorted')}")
    print(f"  - sort_violations: {sort_info.get('sort_violations')}")
    print(f"  - group_col: {sort_info.get('group_col')}")
    print(f"  - date_col: {sort_info.get('date_col')}")
    
    if sort_info.get('is_sorted'):
        print("\n✅ Данные отсортированы корректно!")
    else:
        print(f"\n⚠️ Данные НЕ отсортированы! Найдено {sort_info.get('sort_violations')} нарушений порядка.")
        print("💡 Это означает, что в app.py должна появиться кнопка 'Отсортировать по дате'")
else:
    print(f"❌ ОЖИДАЛОСЬ 4 значения, получено {len(result)}")
    print(f"Типы: {[type(r).__name__ for r in result]}")