# fix_all_metrics.py
import re

def fix_metrics_in_block(filename, start_line=13475, end_line=13500):
    """
    Исправляет все вхождения metrics['..._orig'] на metrics_orig['..._orig']
    в указанном диапазоне строк (блок "До масштабирования")
    """
    with open(filename, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    fixed_count = 0
    fixed_lines = []
    
    # Обрабатываем только строки в диапазоне блока "До масштабирования"
    for i in range(start_line - 1, min(end_line, len(lines))):
        line = lines[i]
        
        # Ищем паттерн metrics['..._orig']
        pattern = r"metrics\['(\w+_orig)'\]"
        replacement = r"metrics_orig['\1']"
        
        new_line = re.sub(pattern, replacement, line)
        
        if new_line != line:
            fixed_count += 1
            fixed_lines.append((i + 1, line.rstrip(), new_line.rstrip()))
            lines[i] = new_line
    
    # Записываем исправленный файл
    if fixed_count > 0:
        with open(filename, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        
        print(f"✅ Исправлено {fixed_count} строк:\n")
        for line_num, old, new in fixed_lines:
            print(f"Строка {line_num}:")
            print(f"  Было: {old.strip()}")
            print(f"  Стало: {new.strip()}")
            print()
    else:
        print("❌ Нечего исправлять в указанном диапазоне")
    
    return fixed_count

if __name__ == "__main__":
    # Исправляем строки 13475-13500 (блок "До масштабирования")
    fix_metrics_in_block("app.py", start_line=13475, end_line=13500)