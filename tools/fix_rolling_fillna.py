"""
Фиксит app/features/rolling.py::apply_wma -- smoothed.fillna(method='bfill')
заменяется на smoothed.bfill() (метод fillna(method=...) deprecated с
pandas 2.1, полностью удалён в pandas 3.0; FutureWarning уже показывается
на pandas 2.3.3, установленном в проекте).
 
Запись через временный файл + os.replace (атомарная замена) -- тот же
надёжный подход, что и в tools/fix_phillips_perron.py.
 
Запуск: python tools/fix_rolling_fillna.py
"""
import os
import tempfile
 
ROLLING_PY = "app/features/rolling.py"
 
OLD_LINE = "    return smoothed.fillna(method='bfill')"
NEW_LINE = "    return smoothed.bfill()"
 
 
def main():
    with open(ROLLING_PY, encoding="utf-8-sig") as f:
        content = f.read()
 
    if OLD_LINE not in content:
        print(f"⚠️ Строка '{OLD_LINE.strip()}' не найдена -- возможно, уже исправлено, "
              f"либо форматирование отличается (лишние пробелы/отступы).")
        return
 
    count = content.count(OLD_LINE)
    if count > 1:
        print(f"⚠️ Найдено {count} совпадений -- заменяю все.")
 
    content = content.replace(OLD_LINE, NEW_LINE)
 
    dir_name = os.path.dirname(os.path.abspath(ROLLING_PY))
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig") as tmp_f:
            tmp_f.write(content)
        os.replace(tmp_path, ROLLING_PY)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
 
    print(f"Готово. Заменено {count} вхождение(й). "
          f"Итоговый размер файла: {os.path.getsize(ROLLING_PY)} байт.")
    print("Проверьте: python -m py_compile app/features/rolling.py")
    print("           Select-String -Path app/features/rolling.py -Pattern 'fillna|bfill'")
 
 
if __name__ == "__main__":
    main()
 