# tests/api/test_upload.py
"""
Тесты для эндпоинтов загрузки файлов:
- POST /v1/internal/upload
- POST /v1/public/upload
"""
import io
import pytest
from fastapi.testclient import TestClient
from apps.api.main import app

# Создаём клиент для тестирования
client = TestClient(app)

# --- Тесты для /v1/internal/upload ---
class TestInternalUpload:
    """Тесты для внутреннего эндпоинта (без авторизации)."""

    def test_upload_csv(self):
        """Тест загрузки CSV-файла."""
        csv_content = "date,value\n2023-01-01,10\n2023-01-02,20\n2023-01-03,30\n2023-01-04,40\n2023-01-05,50\n2023-01-06,60"
        file = io.BytesIO(csv_content.encode('utf-8'))
        response = client.post(
            "/v1/internal/upload",
            files={"file": ("test.csv", file, "text/csv")}
        )
        assert response.status_code == 200
        data = response.json()
        assert "dataset_id" in data
        assert data["name"] == "test.csv"
        assert data["rows"] == 6
        assert data["columns"] == 2
        assert "preview" in data
        assert len(data["preview"]["head"]) == 6  # Заголовок + 5 строк
        assert len(data["preview"]["tail"]) == 5

    def test_upload_xlsx(self):
        """Тест загрузки XLSX-файла."""
        import pandas as pd
        df = pd.DataFrame({
            "date": ["2023-01-01", "2023-01-02", "2023-01-03"],
            "value": [10, 20, 30]
        })
        buffer = io.BytesIO()
        df.to_excel(buffer, index=False, engine="openpyxl")
        buffer.seek(0)

        response = client.post(
            "/v1/internal/upload",
            files={"file": ("test.xlsx", buffer, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["rows"] == 3
        assert data["columns"] == 2

    def test_upload_json(self):
        """Тест загрузки JSON-файла."""
        json_content = '[{"date": "2023-01-01", "value": 10}, {"date": "2023-01-02", "value": 20}]'
        file = io.BytesIO(json_content.encode('utf-8'))
        response = client.post(
            "/v1/internal/upload",
            files={"file": ("test.json", file, "application/json")}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["rows"] == 2

    def test_upload_invalid_format(self):
        """Тест загрузки файла неверного формата (например, .txt)."""
        txt_content = "Это просто текст"
        file = io.BytesIO(txt_content.encode('utf-8'))
        response = client.post(
            "/v1/internal/upload",
            files={"file": ("test.txt", file, "text/plain")}
        )
        assert response.status_code == 400
        assert "не поддерживается" in response.json()["detail"].lower()

    def test_upload_empty_file(self):
        """Тест загрузки пустого файла."""
        file = io.BytesIO(b"")
        response = client.post(
            "/v1/internal/upload",
            files={"file": ("empty.csv", file, "text/csv")}
        )
        assert response.status_code == 400
        detail = response.json()["detail"].lower()
        assert "пуст" in detail or "empty" in detail or "не содержит" in detail or "данных" in detail