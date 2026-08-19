# tests/api/test_structure_detection.py
"""
Интеграционные тесты для GET /v1/session/dataset/structure-detection.

Регресс на реальный баг, сообщённый пользователем: FAO-датасет
(Country, Year, Price) на клиентской позиционной заглушке показывал
абсурдные кандидаты в дату (Country score 0.90, Year 0.70, Price 0.50).
"""
from __future__ import annotations

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import reset_session_store_for_testing

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


def _upload_df(df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    resp = client.post("/v1/internal/upload", files={"file": ("data.csv", buf, "text/csv")})
    assert resp.status_code == 200, resp.text


def test_fao_dataset_selects_year_not_country_or_price():
    df = pd.DataFrame({
        "Country": ["Азербайджан", "Беларусь", "Казахстан"] * 10,
        "Year": list(range(1994, 2024)),
        "Price": [65.9 + i for i in range(30)],
    })
    _upload_df(df)
    resp = client.get("/v1/session/dataset/structure-detection")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["date_col"]["selected"] == "Year"
    assert body["date_col"]["confidence"] > 90

    scores_by_name = {c["name"]: c["score"] for c in body["date_col"]["candidates"]}
    assert scores_by_name["Country"] == 0.0
    assert scores_by_name["Price"] == 0.0

    assert body["entity_col"]["selected"] == "Country"


def test_iso_date_column_detected_directly():
    df = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=20, freq="D").astype(str),
        "value": range(20),
    })
    _upload_df(df)
    resp = client.get("/v1/session/dataset/structure-detection")
    body = resp.json()
    assert body["date_col"]["selected"] == "date"
    assert body["date_col"]["confidence"] > 90


def test_no_plausible_date_column_returns_placeholder():
    df = pd.DataFrame({"a": ["x", "y", "z"] * 5, "b": [1.1, 2.2, 3.3] * 5})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/structure-detection")
    body = resp.json()
    assert body["date_col"]["selected"] == "(не использовать)"
    assert body["date_col"]["confidence"] == 0


def test_no_active_dataset_404():
    resp = client.get("/v1/session/dataset/structure-detection")
    assert resp.status_code == 404


def test_candidates_include_all_columns_not_just_top():
    df = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=10).astype(str),
        "value": range(10),
        "label": ["x"] * 10,
    })
    _upload_df(df)
    resp = client.get("/v1/session/dataset/structure-detection")
    body = resp.json()
    names = {c["name"] for c in body["date_col"]["candidates"]}
    assert names == {"date", "value", "label"}
