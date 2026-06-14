# fix_encoding.py
import chardet

# Читаем файл в текущей кодировке
with open("validation/engine.py", "rb") as f:
    raw_data = f.read()

# Определяем кодировку
result = chardet.detect(raw_data)
print(f"Текущая кодировка: {result['encoding']}")

# Пробуем прочитать в разных кодировках
for encoding in ['utf-8', 'windows-1251', 'cp1251', 'latin-1']:
    try:
        content = raw_data.decode(encoding)
        if 'Уникальность' in content or 'уникальность' in content:
            print(f"✅ Файл прочитан в кодировке: {encoding}")
            
            # Пересохраняем в UTF-8
            with open("validation/engine.py", "w", encoding="utf-8") as f:
                f.write(content)
            print("✅ Файл пересохранён в UTF-8")
            break
    except:
        continue
else:
    print("❌ Не удалось определить кодировку")