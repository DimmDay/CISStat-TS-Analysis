"""
Фиксит баг PhillipsPerron в app/preprocessing/transforms.py::run_stationarity_tests.
 
Проблема: `from statsmodels.tsa.stattools import PhillipsPerron` стоял в общем
try/except вместе с adfuller/kpss. PhillipsPerron не существует в statsmodels
(это класс из библиотеки arch.unitroot) -- импорт ВСЕГДА кидал ImportError,
который ловился внешним except ImportError и обрушивал ВСЮ функцию до
{'error': ...}, не доходя до ADF/KPSS/консенсуса.
 
Фикс:
1. Убирает строку "from statsmodels.tsa.stattools import PhillipsPerron"
   из общего блока импорта.
2. Добавляет "from arch.unitroot import PhillipsPerron" внутрь уже
   существующего локального try/except для PP (тот же паттерн, что уже
   применён для Zivot-Andrews несколькими строками ниже).
 
Запись через временный файл + os.replace (атомарная замена) -- избегаем
проблем с блокировкой файла, которые уже дважды ловили при прямом
Get-Content | Set-Content в PowerShell.
 
Запуск: python tools/fix_phillips_perron.py
"""
import os
import tempfile
 
TRANSFORMS_PY = "app/preprocessing/transforms.py"
 
OLD_IMPORT_LINE = "        from statsmodels.tsa.stattools import PhillipsPerron\n"
 
OLD_PP_CALL = "            pp_result = PhillipsPerron(series.dropna(), lags=max_lag_adf)\n"
NEW_PP_CALL = (
    "            from arch.unitroot import PhillipsPerron\n"
    "            pp_result = PhillipsPerron(series.dropna(), lags=max_lag_adf)\n"
)
 
 
def main():
    with open(TRANSFORMS_PY, encoding="utf-8-sig") as f:
        lines = f.readlines()
 
    # Шаг 1: убрать битый импорт из общего блока.
    if OLD_IMPORT_LINE in lines:
        idx = lines.index(OLD_IMPORT_LINE)
        del lines[idx]
        print(f"Удалена строка {idx + 1}: битый импорт PhillipsPerron из statsmodels.")
    else:
        print("⚠️ Строка с 'from statsmodels.tsa.stattools import PhillipsPerron' не найдена "
              "-- возможно, уже исправлено. Продолжаю без изменений на этом шаге.")
 
    # Шаг 2: вставить правильный импорт перед использованием PhillipsPerron.
    content = "".join(lines)
    if OLD_PP_CALL in content:
        content = content.replace(OLD_PP_CALL, NEW_PP_CALL, 1)
        print("Добавлен корректный импорт 'from arch.unitroot import PhillipsPerron' "
              "внутрь локального try/except для PP.")
    else:
        print("⚠️ Строка вызова PhillipsPerron(...) не найдена в ожидаемом виде -- "
              "возможно, уже исправлено или структура файла отличается.")
 
    # Атомарная запись: во временный файл в той же директории, затем os.replace.
    dir_name = os.path.dirname(os.path.abspath(TRANSFORMS_PY))
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig") as tmp_f:
            tmp_f.write(content)
        os.replace(tmp_path, TRANSFORMS_PY)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
 
    print(f"\nГотово. Итоговый размер файла: {os.path.getsize(TRANSFORMS_PY)} байт.")
    print("Проверьте: python -m py_compile app/preprocessing/transforms.py")
    print("           Select-String -Path app/preprocessing/transforms.py -Pattern PhillipsPerron")
 
 
if __name__ == "__main__":
    main()
 