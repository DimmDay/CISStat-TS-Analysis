# fix_metrics.py
import sys

def fix_file(filename):
    # Читаем файл
    with open(filename, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Счётчик исправлений
    fixed_count = 0
    
    # Исправляем строку 13481 (индекс 13480)
    if len(lines) > 13480:
        old_line = lines[13480]
        if "metrics['range_orig']" in old_line:
            lines[13480] = old_line.replace("metrics['range_orig']", "metrics_orig['range_orig']")
            fixed_count += 1
            print(f"✅ Строка 13481 исправлена")
            print(f"   Было: {old_line.strip()}")
            print(f"   Стало: {lines[13480].strip()}")
        else:
            print(f"️ Строка 13481 не содержит metrics['range_orig']")
            print(f"   Содержимое: {old_line.strip()}")
    
    # Записываем обратно
    if fixed_count > 0:
        with open(filename, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        print(f"\n✅ Исправлено {fixed_count} строк")
    else:
        print("\n❌ Нечего исправлять")
    
    return fixed_count

if __name__ == "__main__":
    fix_file("app.py")