# tests/api/test_target_column.py
"""
Интеграционные тесты для target_column в AnalysisSession (Phase 0.5).

Покрывает:
  1. POST /v1/session/target-column — установка (валидная/невалидная колонка)
  2. GET  /v1/session/target-column — получить текущую + список доступных
  3. GET  /v1/session/current       — содержит target_column в ответе
  4. Upload нового датасета → target_column сбрасывается в None
  5. Cookie-based roundtrip: установка → F5 (новый запрос) → сохраняется
"""
from __future__ import annotations

import io
import json
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import reset_session_store_for_testing


@pytest.fixture(autouse=True)
def _reset_store():
    """Изолируем тесты — каждый стартует с пустым Memory store."""
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


client = TestClient(app)


def _upload_csv(csv_content: str, filename: str = "test.csv"):
    """Хелпер: загрузить CSV через internal endpoint, вернуть ответ и cookie."""
    file = io.BytesIO(csv_content.encode("utf-8"))
    resp = client.post(
        "/v1/internal/upload",
        files={"file": (filename, file, "text/csv")},
    )
    assert resp.status_code == 200, resp.text
    return resp


# ────────────────────────────────────────────────────────────────────
# Фикстуры данных
# ────────────────────────────────────────────────────────────────────

CSV_WITH_NUMERIC = (
    "date,value,category\n"
    "2023-01-01,10.5,A\n"
    "2023-01-02,20.1,B\n"
    "2023-01-03,30.2,A\n"
    "2023-01-04,40.7,B\n"
    "2023-01-05,50.0,A\n"
    "2023-01-06,60.3,B\n"
    "2023-01-07,70.8,A\n"
    "2023-01-08,80.1,B\n"
)


# ────────────────────────────────────────────────────────────────────
# GET /v1/session/target-column (без датасета)
# ────────────────────────────────────────────────────────────────────


class TestTargetColumnGetEmpty:
    """GET без загруженного датасета."""

    def test_get_without_dataset_returns_none_and_empty_columns(self):
        """Сессия без датасета: target_column=None, available_columns=[]."""
        resp = client.get("/v1/session/target-column")
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_column"] is None
        assert data["available_columns"] == []
        assert data["has_dataset"] is False


# ────────────────────────────────────────────────────────────────────
# POST /v1/session/target-column
# ────────────────────────────────────────────────────────────────────


class TestTargetColumnSet:
    """Установка target_column — основной path."""

    def test_set_valid_numeric_column(self):
        """Валидная числовая колонка → 200, сохраняется в сессии."""
        _upload_csv(CSV_WITH_NUMERIC)

        resp = client.post(
            "/v1/session/target-column",
            json={"column": "value"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["target_column"] == "value"
        assert "value" in data["available_columns"]

    def test_set_persists_across_requests(self):
        """Установка → новый GET возвращает то же значение (cookie roundtrip)."""
        _upload_csv(CSV_WITH_NUMERIC)

        set_resp = client.post(
            "/v1/session/target-column",
            json={"column": "value"},
        )
        assert set_resp.status_code == 200

        get_resp = client.get("/v1/session/target-column")
        assert get_resp.status_code == 200
        assert get_resp.json()["target_column"] == "value"

    def test_set_reflected_in_current_session(self):
        """GET /v1/session/current должен включать target_column."""
        _upload_csv(CSV_WITH_NUMERIC)
        client.post("/v1/session/target-column", json={"column": "value"})

        resp = client.get("/v1/session/current")
        assert resp.status_code == 200
        assert resp.json()["target_column"] == "value"

    def test_set_nonexistent_column_returns_404(self):
        """Колонки нет в df → 404."""
        _upload_csv(CSV_WITH_NUMERIC)
        resp = client.post(
            "/v1/session/target-column",
            json={"column": "nonexistent_col"},
        )
        assert resp.status_code == 404
        assert "nonexistent_col" in resp.json()["detail"]

    def test_set_non_numeric_column_returns_422(self):
        """Колонка есть, но не числовая → 422 (target должен быть числовым)."""
        _upload_csv(CSV_WITH_NUMERIC)
        resp = client.post(
            "/v1/session/target-column",
            json={"column": "category"},
        )
        assert resp.status_code == 422
        assert "category" in resp.json()["detail"].lower() or "числ" in resp.json()["detail"].lower()

    def test_set_without_dataset_returns_400(self):
        """Нет загруженного датасета → 400 (нечего выбирать)."""
        resp = client.post(
            "/v1/session/target-column",
            json={"column": "value"},
        )
        assert resp.status_code == 400
        assert "датасет" in resp.json()["detail"].lower() or "dataset" in resp.json()["detail"].lower()

    def test_set_missing_column_in_body_returns_422(self):
        """FastAPI pydantic валидация: поле column обязательное."""
        _upload_csv(CSV_WITH_NUMERIC)
        resp = client.post("/v1/session/target-column", json={})
        assert resp.status_code == 422


# ────────────────────────────────────────────────────────────────────
# Re-upload сбрасывает target_column
# ────────────────────────────────────────────────────────────────────


class TestTargetColumnResetOnReupload:
    """Контракт: set_dataset должен сбрасывать target_column в None.

    Причина: новый датасет может не содержать старую колонку —
    оставлять target_column устаревшим небезопасно (приведёт к 404 в backtest).
    """

    def test_reupload_clears_target_column(self):
        _upload_csv(CSV_WITH_NUMERIC)
        client.post("/v1/session/target-column", json={"column": "value"})
        assert client.get("/v1/session/target-column").json()["target_column"] == "value"

        # Загружаем ДРУГОЙ датасет (без колонки value)
        other_csv = (
            "ts,price\n"
            "2023-01-01,100\n"
            "2023-01-02,200\n"
            "2023-01-03,300\n"
        )
        _upload_csv(other_csv, "other.csv")

        # target_column должен сброситься
        resp = client.get("/v1/session/target-column")
        assert resp.status_code == 200
        assert resp.json()["target_column"] is None

    def test_reupload_with_same_column_name_also_resets(self):
        """Даже если новый датасет содержит колонку с тем же именем —
        target_column сбрасывается (новый датасет = новый анализ).
        """
        _upload_csv(CSV_WITH_NUMERIC)
        client.post("/v1/session/target-column", json={"column": "value"})

        # Загружаем датасет с той же колонкой value, но другим содержимым
        _upload_csv(CSV_WITH_NUMERIC, "another.csv")

        resp = client.get("/v1/session/target-column")
        assert resp.json()["target_column"] is None

    def test_set_target_after_reupload_works(self):
        """После re-upload можно установить target_column заново."""
        _upload_csv(CSV_WITH_NUMERIC)
        client.post("/v1/session/target-column", json={"column": "value"})

        other_csv = "ts,price\n2023-01-01,100\n2023-01-02,200\n2023-01-03,300\n"
        _upload_csv(other_csv, "other.csv")

        # Устанавливаем уже для нового датасета
        resp = client.post("/v1/session/target-column", json={"column": "price"})
        assert resp.status_code == 200
        assert resp.json()["target_column"] == "price"


# ────────────────────────────────────────────────────────────────────
# Available columns — только числовые
# ────────────────────────────────────────────────────────────────────


class TestTargetColumnAvailableColumns:
    """available_columns должен содержать ТОЛЬКО числовые колонки
    (target_column для TS — это прогнозируемая числовая величина)."""

    def test_available_columns_excludes_text_and_datetime(self):
        csv_content = (
            "date,value,category,price\n"
            "2023-01-01,10.5,A,100\n"
            "2023-01-02,20.1,B,200\n"
            "2023-01-03,30.2,A,300\n"
        )
        _upload_csv(csv_content)
        resp = client.get("/v1/session/target-column")
        assert resp.status_code == 200

        data = resp.json()
        assert data["has_dataset"] is True
        # value и price — числовые
        assert "value" in data["available_columns"]
        assert "price" in data["available_columns"]
        # category — текстовая, не должна быть
        assert "category" not in data["available_columns"]
        # date — datetime, не должна быть (хотя pandas может её прочитать как object)
        assert "date" not in data["available_columns"]


# ────────────────────────────────────────────────────────────────────
# Cookie roundtrip (симуляция переключения вкладки)
# ────────────────────────────────────────────────────────────────────


class TestTargetColumnCookiePersistence:
    """target_column должен переживать «ушёл и вернулся» — то есть
    сохраняться в Redis/Memory и восстанавливаться при следующем запросе
    по той же cookie."""

    def test_target_column_survives_new_request_same_cookie(self):
        _upload_csv(CSV_WITH_NUMERIC)
        client.post("/v1/session/target-column", json={"column": "value"})

        # Симулируем "переключение вкладки": новый запрос с той же cookie
        # (TestClient сам управляет cookies через cookie jar)
        resp1 = client.get("/v1/session/current")
        assert resp1.json()["target_column"] == "value"

        resp2 = client.get("/v1/session/target-column")
        assert resp2.json()["target_column"] == "value"

        resp3 = client.get("/v1/session/current")
        assert resp3.json()["target_column"] == "value"
