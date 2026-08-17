# tests/api/test_timeseries_decomposition.py
"""
Интеграционные тесты для GET /v1/session/dataset/timeseries и
GET /v1/session/dataset/decomposition -- остановка «График» вкладки
«Загрузка» (согласовано с тимлидом 2026-08-14).
"""
from __future__ import annotations

import io

import numpy as np
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


# ── /dataset/timeseries ──

def test_timeseries_basic():
    df = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=20, freq="D").astype(str),
        "price": range(20),
    })
    _upload_df(df)
    resp = client.get("/v1/session/dataset/timeseries", params={"column": "price", "date_column": "date"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["points"]) == 20
    assert body["sampled"] is False
    assert body["was_resorted"] is False
    assert body["points"][0]["x"] == "2020-01-01T00:00:00"


def test_timeseries_missing_column_404():
    df = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=5).astype(str), "price": range(5)})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/timeseries", params={"column": "does_not_exist", "date_column": "date"})
    assert resp.status_code == 404


def test_timeseries_missing_date_column_404():
    df = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=5).astype(str), "price": range(5)})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/timeseries", params={"column": "price", "date_column": "does_not_exist"})
    assert resp.status_code == 404


def test_timeseries_non_numeric_column_422():
    df = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=5).astype(str), "label": ["a", "b", "c", "d", "e"]})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/timeseries", params={"column": "label", "date_column": "date"})
    assert resp.status_code == 422


def test_timeseries_no_active_dataset_404():
    resp = client.get("/v1/session/dataset/timeseries", params={"column": "price", "date_column": "date"})
    assert resp.status_code == 404


def test_timeseries_unsorted_rows_flagged_and_resorted():
    df = pd.DataFrame({
        "date": ["2020-01-03", "2020-01-01", "2020-01-02"],
        "price": [3.0, 1.0, 2.0],
    })
    _upload_df(df)
    resp = client.get("/v1/session/dataset/timeseries", params={"column": "price", "date_column": "date"})
    body = resp.json()
    assert body["was_resorted"] is True
    assert [p["y"] for p in body["points"]] == [1.0, 2.0, 3.0]


# ── /dataset/decomposition ──

def test_decomposition_annual_data_not_applicable():
    """Регресс на воспроизведённый вручную баг: годовые данные (как FAO
    price dataset) не должны давать фейковую 'сезонность'."""
    n = 30
    df = pd.DataFrame({
        "date": pd.date_range("1994-01-01", periods=n, freq="YS").astype(str),
        "price": 65.9 + np.arange(n) * 2.0,
    })
    _upload_df(df)
    resp = client.get("/v1/session/dataset/decomposition", params={"column": "price", "date_column": "date"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applicable"] is False
    assert body["reason"] is not None
    assert body["trend_pct"] is None


def test_decomposition_panel_data_duplicate_dates_not_applicable():
    """Реальный кейс FAO-датасета: несколько стран на один год."""
    n_years = 10
    df = pd.DataFrame({
        "date": list(pd.date_range("2014-01-01", periods=n_years, freq="YS").astype(str)) * 3,
        "country": ["RU"] * n_years + ["US"] * n_years + ["DE"] * n_years,
        "price": np.random.default_rng(1).normal(100, 10, size=n_years * 3),
    })
    _upload_df(df)
    resp = client.get("/v1/session/dataset/decomposition", params={"column": "price", "date_column": "date"})
    body = resp.json()
    assert body["applicable"] is False
    assert "панельные" in body["reason"].lower() or "несколько значений" in body["reason"].lower()


def test_decomposition_monthly_data_applicable():
    n = 48
    dates = pd.date_range("2018-01-01", periods=n, freq="MS")
    seasonal = 10 * np.sin(np.arange(n) * 2 * np.pi / 12)
    rng = np.random.default_rng(2)
    df = pd.DataFrame({
        "date": dates.astype(str),
        "price": 100 + np.arange(n) * 0.5 + seasonal + rng.normal(size=n),
    })
    _upload_df(df)
    resp = client.get("/v1/session/dataset/decomposition", params={"column": "price", "date_column": "date"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applicable"] is True
    assert body["method"] == "STL"
    total = body["trend_pct"] + body["seasonal_pct"] + body["cyclical_pct"] + body["resid_pct"]
    assert 99.0 <= total <= 101.0


def test_decomposition_missing_column_404():
    df = pd.DataFrame({"date": pd.date_range("2020-01-01", periods=30, freq="D").astype(str), "price": range(30)})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/decomposition", params={"column": "does_not_exist", "date_column": "date"})
    assert resp.status_code == 404


def test_decomposition_no_active_dataset_404():
    resp = client.get("/v1/session/dataset/decomposition", params={"column": "price", "date_column": "date"})
    assert resp.status_code == 404


def test_decomposition_never_returns_500_on_insufficient_data():
    """Регресс: любой edge case (мало точек, константа) должен давать
    честный applicable=False, 200 OK -- никогда не 500."""
    df = pd.DataFrame({
        "date": pd.date_range("2023-01-01", periods=5, freq="MS").astype(str),
        "price": [5.0] * 5,
    })
    _upload_df(df)
    resp = client.get("/v1/session/dataset/decomposition", params={"column": "price", "date_column": "date"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["applicable"] is False
