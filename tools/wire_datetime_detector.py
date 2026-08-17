"""
Заменяет полную локальную реализацию robust_datetime_detector в app.py
на тонкую @st.cache_data-обёртку над detect_and_convert_datetime
(app/data/detectors.py) -- по образцу read_uploaded_file/init_db_connection.
 
Паритет подтверждён отдельным скриптом (tools/datetime_detector_parity_check.py)
на 5 сценариях перед запуском этой замены.
 
Запуск: python tools/wire_datetime_detector.py
"""
import ast
 
APP_PY = "app.py"
FUNC_NAME = "robust_datetime_detector"
 
NEW_FUNCTION_SRC = '''@st.cache_data(show_spinner=" Анализ дат и конвертация...")
def robust_datetime_detector(df: pd.DataFrame, min_confidence: float = 0.7) -> Tuple[pd.DataFrame, List[str], bool, Optional[str]]:
    """
    UI-обёртка над бизнес-функцией detect_and_convert_datetime (app/data/detectors.py).
    Кэшируется: результат сохраняется, пока не изменится сам DataFrame.
    """
    return detect_and_convert_datetime(df, min_confidence)
'''
 
IMPORT_LINE = "from app.data.detectors import detect_and_convert_datetime\n"
 
 
def replace_function_with_wrapper():
    with open(APP_PY, encoding="utf-8-sig") as f:
        lines = f.readlines()
    source = "".join(lines)
    tree = ast.parse(source)
 
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == FUNC_NAME
    ]
    if not matches:
        print(f"Функция {FUNC_NAME} не найдена — возможно, уже заменена.")
        return False
    if len(matches) > 1:
        print(f"⚠️ Найдено {len(matches)} копий {FUNC_NAME} — беру первую, остальные не трогаю.")
 
    node = matches[0]
    # Учитываем декоратор(ы) -- node.lineno указывает на строку `def`,
    # а не на @decorator, поэтому берём самую раннюю строку из decorator_list.
    if node.decorator_list:
        start_line = min(d.lineno for d in node.decorator_list)
    else:
        start_line = node.lineno
    end_line = node.end_lineno
 
    already_imported = "detect_and_convert_datetime" in source
    prefix = "" if already_imported else IMPORT_LINE + "\n"
    if already_imported:
        print("detect_and_convert_datetime уже упоминается в файле — импорт отдельно не добавляю "
              "(проверьте вручную, что это действительно top-level импорт, а не локальный).")
    else:
        print("Добавляю выделенный top-level импорт прямо перед обёрткой (безопаснее, чем искать "
              "похожую строку в файле — рискуем попасть на локальный import внутри другой функции).")
 
    print(f"Заменяю {FUNC_NAME}: строки {start_line}-{end_line} ({end_line - start_line + 1} строк) "
          f"на тонкую обёртку ({len(NEW_FUNCTION_SRC.splitlines())} строк).")
 
    new_lines = lines[:start_line - 1] + [prefix + NEW_FUNCTION_SRC] + lines[end_line:]
 
    with open(APP_PY, "w", encoding="utf-8-sig") as f:
        f.writelines(new_lines)
    return True
 
 
if __name__ == "__main__":
    replaced = replace_function_with_wrapper()
    if replaced:
        print("\nГотово. Проверьте:")
        print("  python -m py_compile app.py")
        print("  Select-String -Path app.py -Pattern 'detect_and_convert_datetime'")
 