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
        files={"file": ("seasonality.csv", buffer, "text/csv")},
    )
    assert response.status_code == 200, response.text


def test_eda_seasonality_uses_time_order_and_returns_all_visualizations():
    size = 240
    time = np.arange(size, dtype=float)
    values = 3 * np.sin(2 * np.pi * time / 12) + np.sin(2 * np.pi * time / 5)
    _upload(pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=size, freq="D")[::-1],
        "Price": values[::-1],
    }))

    response = client.get(
        "/v1/session/dataset/eda-seasonality",
        params={"column": "Price", "min_cycles": 3, "max_candidates": 6},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applicable"] is True
    assert body["order_source"] == "time_column"
    assert body["order_column"] == "Date"
    assert body["frequency"] == "D"
    assert body["fft"]
    assert body["periodogram"]
    assert body["phase_profile"]
    assert any(abs(item["period"] - 12) < 0.7 for item in body["candidates"])


def test_eda_seasonality_refuses_irregular_time_grid():
    dates = pd.date_range("2024-01-01", periods=60, freq="D").delete(17)
    _upload(pd.DataFrame({"Date": dates, "Price": np.arange(len(dates), dtype=float)}))

    response = client.get(
        "/v1/session/dataset/eda-seasonality", params={"column": "Price"}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applicable"] is False
    assert "нерегуляр" in body["reason"].lower()


def test_eda_seasonality_refuses_panel_duplicates_and_missing_values():
    dates = pd.date_range("2020-01-01", periods=24, freq="MS")
    _upload(pd.DataFrame({
        "Date": np.repeat(dates, 2),
        "Country": ["A", "B"] * len(dates),
        "Price": np.arange(len(dates) * 2, dtype=float),
    }))
    duplicate_response = client.get(
        "/v1/session/dataset/eda-seasonality", params={"column": "Price"}
    )
    assert duplicate_response.status_code == 200
    assert "панель" in duplicate_response.json()["reason"].lower()

    reset_session_store_for_testing()
    values = np.sin(2 * np.pi * np.arange(48) / 12)
    values[7] = np.nan
    _upload(pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=48, freq="MS"),
        "Price": values,
    }))
    missing_response = client.get(
        "/v1/session/dataset/eda-seasonality", params={"column": "Price"}
    )
    assert missing_response.status_code == 200
    assert missing_response.json()["missing_count"] == 1


def test_eda_seasonality_validates_session_column_and_parameters():
    assert client.get(
        "/v1/session/dataset/eda-seasonality", params={"column": "Price"}
    ).status_code == 404

    _upload(pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=30),
        "Label": [f"v{index}" for index in range(30)],
    }))
    assert client.get(
        "/v1/session/dataset/eda-seasonality", params={"column": "Label"}
    ).status_code == 422
    assert client.get(
        "/v1/session/dataset/eda-seasonality",
        params={"column": "Label", "min_cycles": 1},
    ).status_code == 422

