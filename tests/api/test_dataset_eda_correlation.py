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


def _upload(df: pd.DataFrame) -> None:
    buffer = io.BytesIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("correlation.csv", buffer, "text/csv")},
    )
    assert response.status_code == 200, response.text


def _ar1(size: int = 80) -> np.ndarray:
    rng = np.random.default_rng(42)
    values = np.zeros(size)
    for index in range(1, size):
        values[index] = 0.8 * values[index - 1] + rng.normal()
    return values


def test_eda_correlation_uses_detected_time_order_and_returns_all_views():
    size = 80
    _upload(pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=size, freq="D")[::-1],
        "Price": _ar1(size)[::-1],
    }))

    response = client.get(
        "/v1/session/dataset/eda-correlation",
        params={"column": "Price", "max_lags": 20},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applicable"] is True
    assert body["column"] == "Price"
    assert body["order_source"] == "time_column"
    assert body["order_column"] == "Date"
    assert body["frequency"] == "D"
    assert body["max_lag"] == 20
    assert len(body["acf"]) == 21
    assert len(body["pacf"]) == 21
    assert body["ljung_box_pvalue"] is not None


def test_eda_correlation_refuses_panel_duplicates_without_aggregation():
    dates = pd.date_range("2020-01-01", periods=12, freq="MS")
    _upload(pd.DataFrame({
        "Date": np.repeat(dates, 2),
        "Country": ["A", "B"] * len(dates),
        "Price": np.arange(len(dates) * 2, dtype=float),
    }))

    response = client.get(
        "/v1/session/dataset/eda-correlation",
        params={"column": "Price"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applicable"] is False
    assert "панель" in body["reason"].lower()


def test_eda_correlation_refuses_gaps_instead_of_collapsing_lags():
    _upload(pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=12, freq="D"),
        "Price": [1, 2, 3, None, 5, 6, 7, 8, 9, 10, 11, 12],
    }))

    response = client.get(
        "/v1/session/dataset/eda-correlation",
        params={"column": "Price"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applicable"] is False
    assert body["missing_count"] == 1


def test_eda_correlation_validates_session_and_numeric_column():
    assert client.get(
        "/v1/session/dataset/eda-correlation",
        params={"column": "Price"},
    ).status_code == 404

    _upload(pd.DataFrame({"Date": pd.date_range("2024-01-01", periods=10), "Label": list("abcdefghij")}))
    response = client.get(
        "/v1/session/dataset/eda-correlation",
        params={"column": "Label"},
    )
    assert response.status_code == 422

