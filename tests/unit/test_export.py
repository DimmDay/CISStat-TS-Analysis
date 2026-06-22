# tests/unit/test_export.py
import pytest
import pandas as pd
from io import BytesIO
from openpyxl import load_workbook
from app.core.export import export_validation_passport_csv, export_validation_passport_excel


@pytest.fixture
def sample_passport_data():
    """Фикстура с тестовыми данными паспорта валидации."""
    df = pd.DataFrame({
        "Вид проверки": ["Стационарность", "Нормальность", "Пропуски"],
        "Метрика": ["ADF p-value", "Jarque-Bera", "% NaN"],
        "Значение": [0.03, 0.12, 2.5],
        "Статус": ["✅ Стационарен", "⚠️ Отклонение", "✅ Норма"]
    })
    metadata = {
        "document_title": "Паспорт валидации",
        "dataset_name": "test_dataset.csv",
        "platform_tagline": "CISStat TS Analysis",
        "verification": "Верифицировано",
        "generated_at": "2026-06-22 15:00:00",
        "n_rows": 1000,
        "n_cols": 10
    }
    recommendations = {
        "primary_recommendation": "ARIMA(1,1,1)",
        "available": ["ARIMA", "Exponential Smoothing"],
        "limited": ["Prophet"],
        "unavailable": ["LSTM"],
        "explanation": "DQ Score: 85.0%, Уровень качества: high"
    }
    return df, metadata, 85.0, recommendations


def test_export_csv_contains_headers(sample_passport_data):
    """Проверяем, что CSV содержит заголовки-комментарии и данные."""
    df, metadata, dq_score, _ = sample_passport_data
    csv_bytes = export_validation_passport_csv(df, metadata, dq_score)
    csv_text = csv_bytes.decode("utf-8-sig")
    
    # Проверяем наличие комментариев
    assert "# Паспорт валидации" in csv_text
    assert "# Датасет: test_dataset.csv" in csv_text
    assert "# DQ Score: 85.0%" in csv_text
    
    # Проверяем наличие данных
    assert "Стационарность" in csv_text
    assert "ADF p-value" in csv_text


def test_export_excel_has_two_sheets(sample_passport_data):
    """Проверяем, что Excel имеет два листа."""
    df, metadata, dq_score, recommendations = sample_passport_data
    excel_buffer = export_validation_passport_excel(df, metadata, dq_score, recommendations)
    
    # Загружаем Excel из буфера
    wb = load_workbook(excel_buffer)
    
    # Проверяем наличие листов
    assert "Паспорт валидации" in wb.sheetnames
    assert "Рекомендации по моделям" in wb.sheetnames


def test_export_excel_data_integrity(sample_passport_data):
    """Проверяем, что данные в Excel совпадают с исходным DataFrame."""
    df, metadata, dq_score, recommendations = sample_passport_data
    excel_buffer = export_validation_passport_excel(df, metadata, dq_score, recommendations)
    
    wb = load_workbook(excel_buffer)
    ws = wb["Паспорт валидации"]
    
    # Проверяем, что заголовки на месте (строка 5)
    assert ws.cell(row=5, column=1).value == "Вид проверки"
    assert ws.cell(row=5, column=2).value == "Метрика"
    
    # Проверяем, что данные на месте (строка 6+)
    assert ws.cell(row=6, column=1).value == "Стационарность"
    assert ws.cell(row=7, column=1).value == "Нормальность"


def test_export_excel_recommendations_structure(sample_passport_data):
    """Проверяем структуру листа рекомендаций."""
    df, metadata, dq_score, recommendations = sample_passport_data
    excel_buffer = export_validation_passport_excel(df, metadata, dq_score, recommendations)
    
    wb = load_workbook(excel_buffer)
    ws2 = wb["Рекомендации по моделям"]
    
    # Проверяем заголовок
    assert ws2['A1'].value == "РЕКОМЕНДАЦИИ ПО ВЫБОРУ МОДЕЛЕЙ"
    
    # Проверяем первичную рекомендацию
    assert "ARIMA(1,1,1)" in ws2['A3'].value
    
    # Проверяем, что модели записаны (строка 6+)
    assert ws2.cell(row=6, column=2).value == "ARIMA"
    assert ws2.cell(row=7, column=2).value == "Exponential Smoothing"