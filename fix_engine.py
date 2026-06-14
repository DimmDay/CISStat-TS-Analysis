# fix_engine.py
import re

with open("validation/engine.py", "r", encoding="utf-8") as f:
    content = f.read()

# Находим начало второй (дублирующей) части validate_regular_step
# Ищем строку "# 5. Проверка для панельных или обычных данных"
# которая идёт ПОСЛЕ первого return results, violation_masks, freq_info

# Разбиваем на строки
lines = content.split('\n')

# Находим позиции ключевых строк
first_return_idx = None
second_part_start_idx = None

for i, line in enumerate(lines):
    if 'return results, violation_masks, freq_info' in line and first_return_idx is None:
        first_return_idx = i
    if '# 5. Проверка для панельных или обычных данных' in line and first_return_idx is not None and second_part_start_idx is None:
        second_part_start_idx = i

if first_return_idx and second_part_start_idx:
    # Удаляем всё между первым return и началом второй части
    # (включая саму вторую часть до следующей def)
    new_lines = lines[:first_return_idx + 1] + lines[second_part_start_idx:]
    
    # Теперь удаляем вторую часть (до следующей def validate_sufficiency)
    final_lines = []
    skip = False
    for line in new_lines:
        if '# 5. Проверка для панельных или обычных данных' in line:
            skip = True
            continue
        if skip and line.strip().startswith('def '):
            skip = False
        if not skip:
            final_lines.append(line)
    
    # Убираем лишние пустые строки (максимум 2 подряд)
    cleaned = []
    empty_count = 0
    for line in final_lines:
        if line.strip() == '':
            empty_count += 1
            if empty_count <= 2:
                cleaned.append(line)
        else:
            empty_count = 0
            cleaned.append(line)
    
    result = '\n'.join(cleaned)
    
    with open("validation/engine.py", "w", encoding="utf-8") as f:
        f.write(result)
    
    print(f"✅ Удалено {second_part_start_idx - first_return_idx - 1} строк дублирующего кода")
else:
    print("❌ Дублирующая часть не найдена")