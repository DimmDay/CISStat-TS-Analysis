# tests/api/test_dataset_rows.py
"""
Интеграционные тесты GET /v1/session/dataset/rows -- эндпоинт окон
(пагинации) ПОЛНОГО датасета для новой вкладки «Весь датасет» остановки
«Превью датасета» (UI-UPLOAD-FULL-1, 2026-10-14, постановка тимлида).

Контракт:
- окна строк по offset/limit поверх session.dataframe;
- строковое представление ячеек -- ТОТ ЖЕ str(cell), что и в превью
  /dataset (паритет значений вкладки «Превью» и «Весь датасет»);
- честная пагинация: total_rows/returned/has_more;
- капа лимита страницы (защита бэкенда и браузера) -- 422 при limit>1000;
- 404 без активного датасета; 422 на отрицательный offset.
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


# ── Контракт окна: пагинация и честные счётчики ──────────────────────


def test_rows_first_window_and_counters():
    df = pd.DataFrame({"idx": range(25), "val": [f"v{i}" for i in range(25)]})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/rows", params={"offset": 0, "limit": 10})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["columns"] == ["idx", "val"]
    assert body["total_rows"] == 25
    assert body["returned"] == 10
    assert body["offset"] == 0
    assert body["limit"] == 10
    assert body["has_more"] is True
    assert len(body["rows"]) == 10
    assert body["rows"][0] == ["0", "v0"]
    assert body["rows"][9] == ["9", "v9"]


def test_rows_second_window_and_tail():
    df = pd.DataFrame({"idx": range(25), "val": [f"v{i}" for i in range(25)]})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/rows", params={"offset": 20, "limit": 10})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["returned"] == 5
    assert body["has_more"] is False
    assert body["rows"][0] == ["20", "v20"]
    assert body["rows"][-1] == ["24", "v24"]


def test_rows_default_limit_is_200():
    df = pd.DataFrame({"idx": range(250)})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/rows")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["returned"] == 200
    assert body["limit"] == 200
    assert body["has_more"] is True


def test_rows_offset_beyond_end_returns_empty_window():
    df = pd.DataFrame({"idx": range(25)})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/rows", params={"offset": 100, "limit": 10})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rows"] == []
    assert body["returned"] == 0
    assert body["has_more"] is False


def test_rows_limit_over_cap_422():
    df = pd.DataFrame({"idx": range(5)})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/rows", params={"limit": 2000})
    assert resp.status_code == 422


def test_rows_negative_offset_422():
    df = pd.DataFrame({"idx": range(5)})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/rows", params={"offset": -1})
    assert resp.status_code == 422


def test_rows_zero_limit_422():
    df = pd.DataFrame({"idx": range(5)})
    _upload_df(df)
    resp = client.get("/v1/session/dataset/rows", params={"limit": 0})
    assert resp.status_code == 422


def test_rows_no_active_dataset_404():
    resp = client.get("/v1/session/dataset/rows")
    assert resp.status_code == 404


# ── Паритет значений с превью /dataset (один str(cell)) ──────────────


def test_rows_values_match_preview_parity():
    """Значения ячеек «Весь датасет» совпадают с превью посимвольно:
    один и тот же DataFrame -> один и тот же str(cell), включая NaN
    (превью показывает 'nan' -- вкладка полного просмотра не изобретает
    своё представление)."""
    df = pd.DataFrame({
        "date": pd.date_range("2020-01-01", periods=12, freq="D").astype(str),
        "value": [10.5, np.nan, 12.25, 13.0] * 3,
        "label": ["a", "b", None] * 4,
    })
    _upload_df(df)

    preview = client.get("/v1/session/dataset").json()
    rows = client.get("/v1/session/dataset/rows", params={"offset": 0, "limit": 5}).json()

    head_rows = preview["preview"]["head"][1:]  # без строки заголовков
    for full_row, preview_row in zip(rows["rows"], head_rows):
        assert full_row == preview_row


def test_rows_columns_order_matches_dataframe():
    df = pd.DataFrame({
        "z_col": [1, 2],
        "a_col": ["x", "y"],
        "m_col": [0.5, 1.5],
    })
    _upload_df(df)
    body = client.get("/v1/session/dataset/rows", params={"limit": 2}).json()
    assert body["columns"] == ["z_col", "a_col", "m_col"]


def test_rows_single_row_dataset_window():
    df = pd.DataFrame({"only": [42]})
    _upload_df(df)
    body = client.get("/v1/session/dataset/rows", params={"limit": 200}).json()
    assert body["total_rows"] == 1
    assert body["returned"] == 1
    assert body["has_more"] is False
    assert body["rows"] == [["42"]]
