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
        files={"file": ("validation-strategy.csv", data, "text/csv")},
    )
    assert response.status_code == 200, response.text


def test_endpoint_returns_visual_validation_plan():
    size = 100
    _upload(pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=size, freq="D"),
        "Price": np.arange(size, dtype=float),
    }))

    response = client.get(
        "/v1/session/dataset/eda-validation-strategy",
        params={
            "column": "Price",
            "strategy": "sliding",
            "horizon": 10,
            "n_splits": 3,
            "gap": 2,
            "train_window": 40,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["strategy"] == "sliding"
    assert body["applicable"] is True
    assert len(body["folds"]) == 3
    assert len(body["alternatives"]) == 3
    assert body["folds"][-1]["test_end"] == 99


def test_endpoint_validates_session_column_and_parameters():
    assert client.get(
        "/v1/session/dataset/eda-validation-strategy",
        params={"column": "Price"},
    ).status_code == 404

    _upload(pd.DataFrame({"Date": pd.date_range("2024-01-01", periods=40), "Label": ["x"] * 40}))
    assert client.get(
        "/v1/session/dataset/eda-validation-strategy",
        params={"column": "Label"},
    ).status_code == 422
    assert client.get(
        "/v1/session/dataset/eda-validation-strategy",
        params={"column": "Label", "horizon": 0},
    ).status_code == 422
