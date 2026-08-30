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
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("structural-breaks.csv", buffer, "text/csv")},
    )
    assert response.status_code == 200, response.text


def test_eda_structural_breaks_returns_complementary_diagnostics_and_views():
    rng = np.random.default_rng(42)
    _upload(pd.DataFrame({
        "Date": pd.date_range("2024-01-01", periods=180, freq="D"),
        "Price": np.r_[rng.normal(0, 0.2, 90), rng.normal(3, 0.2, 90)],
        "Label": [f"v{index}" for index in range(180)],
    }))

    response = client.get(
        "/v1/session/dataset/eda-structural-breaks",
        params={"column": "Price", "alpha": 0.05, "min_segment": 20, "penalty_multiplier": 2.0},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applicable"] is True
    assert body["status"] == "breaks_detected"
    assert body["cusum"]["reject_stability"] is True
    assert body["candidates"]
    assert body["segments"]
    assert body["series"]
    assert body["cusum_path"]
    assert body["sensitivity"]


def test_eda_structural_breaks_validates_session_column_and_parameters():
    assert client.get(
        "/v1/session/dataset/eda-structural-breaks", params={"column": "Price"}
    ).status_code == 404

    _upload(pd.DataFrame({
        "Price": np.arange(80, dtype=float),
        "Label": [f"v{index}" for index in range(80)],
    }))
    assert client.get(
        "/v1/session/dataset/eda-structural-breaks", params={"column": "Missing"}
    ).status_code == 404
    assert client.get(
        "/v1/session/dataset/eda-structural-breaks", params={"column": "Label"}
    ).status_code == 422
    assert client.get(
        "/v1/session/dataset/eda-structural-breaks",
        params={"column": "Price", "alpha": 0.5},
    ).status_code == 422
    assert client.get(
        "/v1/session/dataset/eda-structural-breaks",
        params={"column": "Price", "min_segment": 2},
    ).status_code == 422
    assert client.get(
        "/v1/session/dataset/eda-structural-breaks",
        params={"column": "Price", "penalty_multiplier": 0},
    ).status_code == 422

