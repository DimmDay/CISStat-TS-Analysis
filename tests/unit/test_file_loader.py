"""
tests/unit/test_file_loader.py
 
Характеризационные тесты для read_uploaded_file (app/data/file_loader.py).
 
Воспроизводит РЕАЛЬНЫЙ баг: CSV с обычным текстовым заголовком (Row ID,
Order ID, ..., Sales) читается с header=None, из-за чего заголовок попадает
в данные как строка значений, и числовые колонки (например Sales) становятся
dtype=object вместо float64/int64.
 
Обнаружено через tools/debug_ct_f.py на реальном датасете train.csv —
ct_f["num"] оказывался пустым, кнопка "Рассчитать свойства ряда" пропадала
из UI без единой ошибки.
"""
import io
import pandas as pd
import pytest
 
from app.data.file_loader import read_uploaded_file
 
 
class _FakeUploadedFile:
    """Имитирует streamlit UploadedFile для read_uploaded_file."""
    def __init__(self, content: bytes, name: str):
        self.name = name
        self._buf = io.BytesIO(content)
        self.mode = "rb"  # некоторые пути pandas проверяют .mode у файлового объекта
 
    def __getattr__(self, attr):
        return getattr(self._buf, attr)
 
 
CSV_WITH_HEADER = (
    "Row ID,Order ID,Order Date,Ship Date,Category,Sales\n"
    "1,CA-2017-152156,08/11/2017,11/11/2017,Furniture,261.96\n"
    "2,CA-2017-152156,08/11/2017,11/11/2017,Furniture,731.94\n"
    "3,CA-2017-138688,12/06/2017,16/06/2017,Office Supplies,14.62\n"
).encode("utf-8-sig")
 
 
class TestReadUploadedFileCsvHeader:
    """
    Тесты для read_uploaded_file: CSV с заголовком должен использовать его
    как имена колонок; CSV без заголовка -- по-прежнему получать col_0/col_1/...
 
    Баг обнаружен через tools/debug_ct_f.py на реальном train.csv: header=None
    стоял безусловно, заголовок попадал в данные, числовые колонки (Sales)
    получали dtype=object, из-за чего ct_f["num"] был пуст, а кнопка
    "Рассчитать свойства ряда" пропадала из UI без единой ошибки.
    """
 
    def test_header_row_correctly_used_as_column_names(self):
        """
        КРИТЕРИЙ ПРИЁМКИ ФИКСА: заголовок CSV должен становиться именами
        колонок, а не строкой данных. Числовые колонки (Sales) должны
        получать числовой dtype, а не object/str.
        """
        fake_file = _FakeUploadedFile(CSV_WITH_HEADER, "train.csv")
        df, ext = read_uploaded_file(fake_file)
 
        assert ext == "csv"
        assert len(df) == 3  # 3 строки данных, заголовок больше не считается строкой
        assert list(df.columns) == [
            "Row ID", "Order ID", "Order Date", "Ship Date", "Category", "Sales"
        ]
        assert pd.api.types.is_numeric_dtype(df["Sales"])
        assert df["Sales"].tolist() == [261.96, 731.94, 14.62]
        assert pd.api.types.is_numeric_dtype(df["Row ID"])
 
    def test_headerless_data_still_detected_as_headerless(self):
        """
        Регрессия: CSV, где первая строка УЖЕ данные (числа/даты, не текстовые
        лейблы), не должен ошибочно принять эту строку за заголовок.
        """
        headerless_numeric = (
            "1,100.5,2020-01-01\n"
            "2,200.3,2020-01-02\n"
            "3,150.7,2020-01-03\n"
        ).encode("utf-8-sig")
        fake_file = _FakeUploadedFile(headerless_numeric, "no_header.csv")
        df, ext = read_uploaded_file(fake_file)
 
        assert len(df) == 3  # не 2 -- первая строка НЕ должна быть съедена как заголовок
        assert pd.api.types.is_numeric_dtype(df["col_0"])
        assert pd.api.types.is_numeric_dtype(df["col_1"])
 