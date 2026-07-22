"""
Проверка паритета: robust_datetime_detector (локальная копия в app.py)
             vs     detect_and_convert_datetime (app/data/detectors.py)
 
По коду обе функции выглядят идентично (те же DATE_PATTERNS, TIME_KEYWORDS,
алгоритм), кроме обработки исключений (app.py: тихий `except: pass`,
detectors.py: `logger.warning`). Этот скрипт подтверждает численный паритет
на нескольких сценариях перед тем, как заменить локальную копию в app.py
на тонкую обёртку над detect_and_convert_datetime (по образцу read_uploaded_file).
 
Запуск: python tools/datetime_detector_parity_check.py
"""
import ast
import sys
 
import numpy as np
import pandas as pd
 
sys.path.insert(0, ".")
 
from app.data.detectors import detect_and_convert_datetime as NEW_impl
 
 
def extract_old_function(app_py_path="app.py", func_name="robust_datetime_detector"):
    """Достаёт исходный код функции верхнего уровня из app.py через AST."""
    with open(app_py_path, encoding="utf-8-sig") as f:
        source = f.read()
    tree = ast.parse(source)
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == func_name
    ]
    if not matches:
        raise RuntimeError(f"Функция {func_name} не найдена в {app_py_path}.")
    if len(matches) > 1:
        print(f"⚠️ Найдено {len(matches)} копий {func_name} — беру первую.")
    return ast.get_source_segment(source, matches[0])
 
 
def build_old_function():
    old_src = extract_old_function()
    from typing import Tuple, List, Optional
    namespace = {"pd": pd, "np": np, "Tuple": Tuple, "List": List, "Optional": Optional}
    exec(compile(old_src, "<old_robust_datetime_detector>", "exec"), namespace)
    return namespace["robust_datetime_detector"]
 
 
def compare_result(old_result, new_result, scenario_name):
    old_df, old_cols, old_active, old_primary = old_result
    new_df, new_cols, new_active, new_primary = new_result
 
    diffs = []
    if sorted(old_cols) != sorted(new_cols):
        diffs.append(f"detected_cols: OLD={sorted(old_cols)} vs NEW={sorted(new_cols)}")
    if old_active != new_active:
        diffs.append(f"ts_active: OLD={old_active} vs NEW={new_active}")
    if old_primary != new_primary:
        diffs.append(f"primary_date_col: OLD={old_primary!r} vs NEW={new_primary!r}")
    if list(old_df.columns) != list(new_df.columns):
        diffs.append(f"columns: OLD={list(old_df.columns)} vs NEW={list(new_df.columns)}")
    else:
        for col in old_df.columns:
            if not old_df[col].equals(new_df[col]):
                diffs.append(f"данные в колонке '{col}' различаются")
 
    print(f"\n{'=' * 60}\nСЦЕНАРИЙ: {scenario_name}\n{'=' * 60}")
    if not diffs:
        print("✅ ПАРИТЕТ ПОДТВЕРЖДЁН.")
    else:
        print(f"❌ РАСХОЖДЕНИЯ ({len(diffs)}):")
        for d in diffs:
            print(f"   - {d}")
    return diffs
 
 
def main():
    old_func = build_old_function()
    all_diffs = []
 
    # Сценарий 1: ISO-даты + числовой признак + категория
    df1 = pd.DataFrame({
        "Дата отчёта": pd.date_range("2020-01-01", periods=50, freq="D").astype(str),
        "value": np.random.default_rng(1).normal(0, 1, 50),
        "category": ["A", "B"] * 25,
    })
    all_diffs += compare_result(old_func(df1.copy()), NEW_impl(df1.copy()), "ISO-даты как строки")
 
    # Сценарий 2: год как число (year_only эвристика)
    df2 = pd.DataFrame({
        "year": list(range(1990, 2040)),
        "sales": np.random.default_rng(2).normal(100, 10, 50),
    })
    all_diffs += compare_result(old_func(df2.copy()), NEW_impl(df2.copy()), "Числовой год (year_only)")
 
    # Сценарий 3: Unix timestamp (секунды)
    base = pd.Timestamp("2020-01-01")
    df3 = pd.DataFrame({
        "ts": [(base + pd.Timedelta(days=i)).timestamp() for i in range(50)],
        "value": np.random.default_rng(3).normal(0, 1, 50),
    })
    all_diffs += compare_result(old_func(df3.copy()), NEW_impl(df3.copy()), "Unix timestamp (секунды)")
 
    # Сценарий 4: без дат вообще
    df4 = pd.DataFrame({
        "a": np.random.default_rng(4).normal(0, 1, 30),
        "b": ["x", "y", "z"] * 10,
    })
    all_diffs += compare_result(old_func(df4.copy()), NEW_impl(df4.copy()), "Без дат вообще")
 
    # Сценарий 5: русские ключевые слова + формат dd.mm.yyyy
    df5 = pd.DataFrame({
        "Отчётная дата": [f"{d:02d}.06.2023" for d in range(1, 29)],
        "показатель": np.random.default_rng(5).normal(50, 5, 28),
    })
    all_diffs += compare_result(old_func(df5.copy()), NEW_impl(df5.copy()), "Русские ключевые слова + dd.mm.yyyy")
 
    print(f"\n{'=' * 60}")
    if not all_diffs:
        print("✅ ИТОГ: все 5 сценариев совпадают. Можно заменять robust_datetime_detector")
        print("   на тонкую обёртку над detect_and_convert_datetime.")
    else:
        print(f"❌ ИТОГ: суммарно {len(all_diffs)} расхождений — НЕ заменять, пока не разберём.")
    print("=" * 60)
 
 
if __name__ == "__main__":
    main()
 