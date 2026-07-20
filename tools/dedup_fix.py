"""
Удаляет:
1. Дубль calculate_ts_passport в app.py (оставляя импорт из app.core.passport рабочим).
2. Вторую копию _compare_ts_props в app/core/passport.py (оставляя первую, с логированием).
"""
import ast


def remove_functions(path, func_name, keep_index=0, encoding="utf-8-sig"):
    with open(path, encoding=encoding) as f:
        lines = f.readlines()
    source = "".join(lines)
    tree = ast.parse(source)
    matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == func_name]

    if not matches:
        print(f"[{path}] Функция {func_name} не найдена — уже удалена?")
        return
    print(f"[{path}] Найдено {len(matches)} копий {func_name}.")

    if len(matches) <= keep_index:
        print(f"[{path}] keep_index={keep_index} вне диапазона, ничего не делаю.")
        return

    to_remove = [n for i, n in enumerate(matches) if i != keep_index]
    if not to_remove:
        print(f"[{path}] Только одна копия — нечего удалять.")
        return

    # удаляем с конца файла к началу, чтобы не сбить номера строк последующих узлов
    to_remove.sort(key=lambda n: n.lineno, reverse=True)
    for node in to_remove:
        start, end = node.lineno - 1, node.end_lineno
        print(f"[{path}] Удаляю {func_name}: строки {node.lineno}-{node.end_lineno}")
        lines = lines[:start] + lines[end:]

    with open(path, "w", encoding=encoding) as f:
        f.writelines(lines)
    print(f"[{path}] Готово.\n")


def remove_all(path, func_name, encoding="utf-8-sig"):
    with open(path, encoding=encoding) as f:
        lines = f.readlines()
    source = "".join(lines)
    tree = ast.parse(source)
    matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == func_name]
    if not matches:
        print(f"[{path}] Функция {func_name} не найдена — уже удалена?")
        return
    matches.sort(key=lambda n: n.lineno, reverse=True)
    for node in matches:
        start, end = node.lineno - 1, node.end_lineno
        print(f"[{path}] Удаляю {func_name}: строки {node.lineno}-{node.end_lineno}")
        lines = lines[:start] + lines[end:]
    with open(path, "w", encoding=encoding) as f:
        f.writelines(lines)
    print(f"[{path}] Готово.\n")


if __name__ == "__main__":
    # app.py: локальная копия calculate_ts_passport уже должна быть удалена предыдущим запуском.
    # remove_all безопасен для повторного запуска — если функция не найдена, просто выведет сообщение.
    remove_all("app.py", "calculate_ts_passport")

    # ⚠️ ИСПРАВЛЕНО: правильный путь — app/core/passport.py, а не passport.py в корне
    remove_functions("app/core/passport.py", "_compare_ts_props", keep_index=0)
