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
    client.cookies.clear()
    yield
    reset_session_store_for_testing()
    client.cookies.clear()


def _upload(frame: pd.DataFrame) -> None:
    data = io.BytesIO()
    frame.to_csv(data, index=False)
    data.seek(0)
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("model-matrix.csv", data, "text/csv")},
    )
    assert response.status_code == 200, response.text


def test_endpoint_returns_typed_matrix_for_current_session_dataset():
    index = np.arange(180, dtype=float)
    _upload(pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=180, freq="MS"),
        "Price": 10 + np.sin(2 * np.pi * index / 12),
        "Volume": index,
    }))

    response = client.get(
        "/v1/session/dataset/eda-model-matrix",
        params={"column": "Price", "task": "forecast", "horizon": 12},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["column"] == "Price"
    assert body["task"] == "forecast"
    assert body["horizon"] == 12
    assert body["summary"]["total_models"] == 24
    assert body["models"][0]["criteria"]


def test_endpoint_validates_session_column_and_parameters():
    assert client.get(
        "/v1/session/dataset/eda-model-matrix", params={"column": "Price"}
    ).status_code == 404

    _upload(pd.DataFrame({"Date": pd.date_range("2024-01-01", periods=40), "Label": ["x"] * 40}))
    assert client.get(
        "/v1/session/dataset/eda-model-matrix", params={"column": "Label"}
    ).status_code == 422
    assert client.get(
        "/v1/session/dataset/eda-model-matrix", params={"column": "Label", "horizon": 0}
    ).status_code == 422

