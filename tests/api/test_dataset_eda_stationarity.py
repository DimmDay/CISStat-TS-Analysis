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
        files={"file": ("stationarity.csv", buffer, "text/csv")},
    )
    assert response.status_code == 200, response.text


def test_eda_stationarity_returns_tests_rolling_views_and_real_pp():
    rng = np.random.default_rng(42)
    size = 240
    _upload(pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=size, freq="D")[::-1],
        "Price": rng.normal(size=size)[::-1],
    }))

    response = client.get(
        "/v1/session/dataset/eda-stationarity",
        params={"column": "Price", "alpha": 0.05, "rolling_window": 12},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applicable"] is True
    assert body["consensus"] == "stationary"
    assert body["order_source"] == "time_column"
    assert body["frequency"] == "D"
    assert len(body["tests"]) == 6
    pp = next(item for item in body["tests"] if item["id"] == "pp")
    assert pp["available"] is True
    assert pp["p_value"] is not None
    assert body["rolling"]
    assert body["recommendations"]


def test_eda_stationarity_detects_random_walk_as_non_stationary():
    rng = np.random.default_rng(7)
    size = 400
    _upload(pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=size, freq="D"),
        "Price": np.cumsum(rng.normal(size=size)),
    }))

    response = client.get(
        "/v1/session/dataset/eda-stationarity", params={"column": "Price"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["consensus"] == "non-stationary"


def test_eda_stationarity_refuses_irregular_panel_and_missing_series():
    dates = pd.date_range("2024-01-01", periods=80, freq="D").delete(11)
    _upload(pd.DataFrame({"Date": dates, "Price": np.arange(len(dates), dtype=float)}))
    irregular = client.get(
        "/v1/session/dataset/eda-stationarity", params={"column": "Price"}
    )
    assert irregular.status_code == 200
    assert "нерегуляр" in irregular.json()["reason"].lower()

    reset_session_store_for_testing()
    dates = pd.date_range("2024-01-01", periods=40, freq="D")
    _upload(pd.DataFrame({"Date": np.repeat(dates, 2), "Price": np.arange(80.0)}))
    panel = client.get(
        "/v1/session/dataset/eda-stationarity", params={"column": "Price"}
    )
    assert panel.status_code == 200
    assert "панель" in panel.json()["reason"].lower()

    reset_session_store_for_testing()
    values = np.arange(80, dtype=float)
    values[9] = np.nan
    _upload(pd.DataFrame({"Date": pd.date_range("2024-01-01", periods=80), "Price": values}))
    missing = client.get(
        "/v1/session/dataset/eda-stationarity", params={"column": "Price"}
    )
    assert missing.status_code == 200
    assert missing.json()["missing_count"] == 1
    assert missing.json()["applicable"] is False


def test_eda_stationarity_validates_session_column_and_query_parameters():
    assert client.get(
        "/v1/session/dataset/eda-stationarity", params={"column": "Price"}
    ).status_code == 404

    _upload(pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=40),
        "Label": [f"v{index}" for index in range(40)],
    }))
    assert client.get(
        "/v1/session/dataset/eda-stationarity", params={"column": "Label"}
    ).status_code == 422
    assert client.get(
        "/v1/session/dataset/eda-stationarity",
        params={"column": "Label", "alpha": 0.2},
    ).status_code == 422
    assert client.get(
        "/v1/session/dataset/eda-stationarity",
        params={"column": "Label", "rolling_window": 2},
    ).status_code == 422
