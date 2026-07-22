"""
Диагностика: почему ct_f["num"] оказывается пустым.

Загружает РЕАЛЬНЫЙ файл (тот же, что вы используете в Streamlit) через
ту же цепочку функций, что использует app.py, и печатает dtypes на каждом
шаге — чтобы увидеть, на каком этапе числовые колонки теряют тип.

Запуск: python tools/debug_ct_f.py path/to/your_test_file.csv
(или, в PowerShell, обычный путь с обратными слэшами — просто в кавычках)
"""
import sys

sys.path.insert(0, ".")

import pandas as pd

from app.data.file_loader import read_uploaded_file
from app.data.detectors import detect_and_convert_datetime
from app.classification.classifier import classify_columns


class _FakeUploadedFile:
    """
    Имитирует объект uploaded_file из Streamlit UploadedFile.
    pandas.read_csv нужен полноценный файлоподобный объект (readline, read,
    seek и т.д.), поэтому делегируем всё через __getattr__ на реальный
    открытый файл, а не реализуем методы вручную по одному.
    """
    def __init__(self, path):
        self.name = path
        self._fh = open(path, "rb")

    def __getattr__(self, attr):
        # Всё, что явно не переопределено выше (read, readline, seek,
        # tell, __iter__ и т.д.) — делегируем реальному файловому объекту.
        return getattr(self._fh, attr)


def main():
    if len(sys.argv) < 2:
        print("Использование: python tools/debug_ct_f.py <путь к файлу.csv/.xlsx/.json>")
        sys.exit(1)

    path = sys.argv[1]
    print(f"{'=' * 60}\nШАГ 1: read_uploaded_file('{path}')\n{'=' * 60}")

    fake_file = _FakeUploadedFile(path)
    df, ext = read_uploaded_file(fake_file)
    print(f"Формат: {ext}")
    print(f"Форма: {df.shape}")
    print("\nDtypes СРАЗУ ПОСЛЕ ЗАГРУЗКИ:")
    print(df.dtypes)
    print("\nПервые 3 строки:")
    print(df.head(3))

    print(f"\n{'=' * 60}\nШАГ 2: detect_and_convert_datetime(df)\n{'=' * 60}")
    df_work, detected_cols, ts_active, potential_date_col = detect_and_convert_datetime(df)
    print(f"Обнаруженные колонки-даты: {detected_cols}")
    print(f"ts_active: {ts_active}")
    print(f"potential_date_col: {potential_date_col}")
    print("\nDtypes ПОСЛЕ детекции дат:")
    print(df_work.dtypes)

    print(f"\n{'=' * 60}\nШАГ 3: classify_columns(df_work)\n{'=' * 60}")
    ct_f = classify_columns(df_work)
    print(f"num: {ct_f['num']}")
    print(f"cat: {ct_f['cat']}")
    print(f"date: {ct_f['date']}")

    if not ct_f["num"]:
        print(f"\n{'!' * 60}")
        print("⚠️  ct_f['num'] ПУСТ — вот и причина исчезновения кнопки.")
        print("Смотрите на 'Dtypes ПОСЛЕ детекции дат' выше: если колонки,")
        print("которые должны быть числовыми, там имеют dtype 'object' —")
        print("значит, что-то на шаге 1 или 2 испортило их тип")
        print("(например, detect_and_convert_datetime ошибочно принял")
        print("числовую колонку за дату и попытался её сконвертировать).")
        print(f"{'!' * 60}")


if __name__ == "__main__":
    main()
