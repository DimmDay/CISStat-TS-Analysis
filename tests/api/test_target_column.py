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
    """Контракт: set_dataset сбрасывает target_column в None (новый
    датасет может не содержать старую колонку — устаревшее имя
    небезопасно, приведёт к 404 в backtest).

    PROGR-25-A (spec_progress_target_column.md §4-A): observable-итог
    re-upload изменён — сразу после сброса правило авто-фиксации
    (target_column_rule.auto_fix_and_seed) фиксирует признак нового
    фрейма при ровно одном кандидате с source="auto"; при 2+
    кандидатах — честное «не выбран». Безопасность контракта сохранена:
    авто-фиксация выбирает ТОЛЬКО из числовых колонок нового фрейма.
    """

    def test_reupload_autofixes_single_numeric_of_new_dataset(self):
        _upload_csv(CSV_WITH_NUMERIC)
        client.post("/v1/session/target-column", json={"column": "value"})
        assert client.get("/v1/session/target-column").json()["target_column"] == "value"

        # Загружаем ДРУГОЙ датасет (без колонки value) -- одна числовая:
        # сброс + авто-фиксация новой цели (PROGR-25-A)
        other_csv = (
            "ts,price\n"
            "2023-01-01,100\n"
            "2023-01-02,200\n"
            "2023-01-03,300\n"
        )
        _upload_csv(other_csv, "other.csv")

        resp = client.get("/v1/session/target-column")
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_column"] == "price"
        assert data["target_column_source"] == "auto"

    def test_reupload_with_two_numerics_honest_ambiguity(self):
        """Даже если новый датасет содержит ту же колонку value --
        сброс + правило заново: одна числовая → авто-фиксация (PROGR-25-A);
        две и более → честное «не выбран» (фиксации нет)."""
        _upload_csv(CSV_WITH_NUMERIC)
        client.post("/v1/session/target-column", json={"column": "value"})

        # Две числовые: value,price -- фиксации нет (честная неоднозначность)
        two_numeric_csv = (
            "date,value,price\n"
            "2023-01-01,10.5,100\n"
            "2023-01-02,20.1,200\n"
            "2023-01-03,30.2,300\n"
        )
        _upload_csv(two_numeric_csv, "another.csv")

        resp = client.get("/v1/session/target-column")
        data = resp.json()
        assert data["target_column"] is None
        assert data["target_column_source"] is None

    def test_reupload_single_numeric_autofixes_value_again(self):
        """PROGR-25-A: re-upload с той же единственной числовой --
        авто-фиксация применяется заново (новый датасет = новый анализ)."""
        _upload_csv(CSV_WITH_NUMERIC)
        client.post("/v1/session/target-column", json={"column": "value"})

        _upload_csv(CSV_WITH_NUMERIC, "another.csv")

        resp = client.get("/v1/session/target-column")
        data = resp.json()
        assert data["target_column"] == "value"
        assert data["target_column_source"] == "auto"

    def test_set_target_after_reupload_works(self):
        """После re-upload можно установить target_column заново
        (ручной выбор -- source=user, last-wins после авто)."""
        _upload_csv(CSV_WITH_NUMERIC)
        client.post("/v1/session/target-column", json={"column": "value"})

        other_csv = "ts,price\n2023-01-01,100\n2023-01-02,200\n2023-01-03,300\n"
        _upload_csv(other_csv, "other.csv")

        # Устанавливаем уже для нового датасета
        resp = client.post("/v1/session/target-column", json={"column": "price"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_column"] == "price"
        assert data["target_column_source"] == "user"


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


# ────────────────────────────────────────────────────────────────────
# suggested_column (2026-08-14) -- эвристический дефолт "первая числовая,
# исключая date/year-похожие имена", единый источник для всех фронтендов
# (Загрузка/Валидация), а не независимая логика в каждом компоненте.
# ────────────────────────────────────────────────────────────────────


class TestSuggestedColumnHeuristic:
    """PROGR-25-A: рекомендация = первый кандидат единого правила
    (target_column_rule): числовые минус session.date_column и реестр
    производных. Имя-исключение date-подобных СНЯТО (правка R4 акта
    сертификации: канон PROGR-24 -- не по суффиксу); семантика даты
    определяется фактом session.date_column.
    """

    def test_fao_style_year_is_candidate_no_silent_fixation(self):
        """Бывший кейс эвристики: Country/Year/Price. По R4 имя-исключение
        снято: Year -- полноценный кандидат, рекомендация = первый
        кандидат (Year); ДВЕ числовые → честная неоднозначность:
        тихой фиксации нет (target_column=None, source=None)."""
        df = pd.DataFrame({
            "Country": ["RU", "US", "DE"],
            "Year": [2020, 2021, 2022],
            "Price": [65.9, 30.7, 85.3],
        })
        buf = io.BytesIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        client.post("/v1/internal/upload", files={"file": ("data.csv", buf, "text/csv")})

        resp = client.get("/v1/session/target-column")
        assert resp.status_code == 200
        data = resp.json()
        assert data["suggested_column"] == "Year"
        assert data["target_column"] is None
        assert data["target_column_source"] is None

    def test_registered_date_column_restores_unambiguous_case(self):
        """R4 в положительную сторону: [Country,Year,Price] + факт
        session.date_column=Year (через POST /date-column) → единственный
        кандидат Price → авто-фиксация возможна ТОЛЬКО в точке загрузки;
        после загрузки фиксация не выполняется (точки -- upload+demo),
        но рекомендация сужается на Price."""
        df = pd.DataFrame({
            "Country": ["RU", "US", "DE"],
            "Year": [2020, 2021, 2022],
            "Price": [65.9, 30.7, 85.3],
        })
        buf = io.BytesIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        client.post("/v1/internal/upload", files={"file": ("data.csv", buf, "text/csv")})
        assert client.get("/v1/session/current").json()["target_column"] is None

        resp = client.post("/v1/session/date-column", json={"column": "Year"})
        assert resp.status_code == 200, resp.text

        body = client.get("/v1/session/target-column").json()
        assert body["suggested_column"] == "Price"
        assert body["target_column"] is None  # фиксация -- только upload/demo (§4-A)

    def test_suggested_column_does_not_mutate_actual_target_column(self):
        """suggested_column -- подсказка для UI, не побочный эффект:
        при честной неоднозначности target_column остаётся None
        (источники фиксации -- только upload/demo, §4-A)."""
        df = pd.DataFrame({"Year": [2020, 2021], "Price": [10.0, 20.0]})
        buf = io.BytesIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        client.post("/v1/internal/upload", files={"file": ("data.csv", buf, "text/csv")})

        resp = client.get("/v1/session/target-column")
        body = resp.json()
        assert body["suggested_column"] == "Year"
        assert body["target_column"] is None  # 2 кандидата -- честная неоднозначность
        assert body["target_column_source"] is None

    def test_suggested_column_null_when_no_dataset(self):
        resp = client.get("/v1/session/target-column")
        assert resp.json()["suggested_column"] is None

    def test_suggested_column_falls_back_to_first_when_all_columns_date_like(self):
        """Все числовые похожи на дату/год по имени, date_column не
        зарегистрирована: это ДВА кандидата -- рекомендация = первый
        кандидат (Year), фиксации нет (честная неоднозначность)."""
        df = pd.DataFrame({"Year": [2020, 2021], "Period": [1, 2], "label": ["a", "b"]})
        buf = io.BytesIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        client.post("/v1/internal/upload", files={"file": ("data.csv", buf, "text/csv")})

        resp = client.get("/v1/session/target-column")
        data = resp.json()
        assert data["suggested_column"] == "Year"
        assert data["target_column"] is None

    def test_suggested_column_present_in_post_response_too(self):
        df = pd.DataFrame({"Year": [2020, 2021], "Price": [10.0, 20.0]})
        buf = io.BytesIO()
        df.to_csv(buf, index=False)
        buf.seek(0)
        client.post("/v1/internal/upload", files={"file": ("data.csv", buf, "text/csv")})

        resp = client.post("/v1/session/target-column", json={"column": "Price"})
        # Пользователь ЯВНО выбрал Price (второй кандидат) -- рекомендация
        # НЕ подстраивается под фактический выбор: первый кандидат (Year).
        data = resp.json()
        assert data["target_column"] == "Price"
        assert data["target_column_source"] == "user"
        assert data["suggested_column"] == "Year"
