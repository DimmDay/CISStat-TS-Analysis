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


def _upload(frame: pd.DataFrame) -> None:
    buffer = io.BytesIO()
    frame.to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("distribution.csv", buffer, "text/csv")},
    )
    assert response.status_code == 200, response.text


def test_eda_distribution_returns_five_views_and_corrected_normality_tests():
    _upload(pd.DataFrame({
        "Price": np.random.default_rng(42).normal(size=320),
        "Region": ["A", "B"] * 160,
    }))

    response = client.get(
        "/v1/session/dataset/eda-distribution",
        params={"column": "Price", "alpha": 0.05, "bins": 20},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applicable"] is True
    assert body["normality_status"] == "compatible"
    assert len(body["histogram"]) == 20
    assert body["density"]
    assert body["qq"]
    assert body["cdf"]
    assert {item["id"] for item in body["tests"]} == {
        "shapiro", "jarque_bera", "lilliefors",
    }
    assert all("adjusted_p_value" in item for item in body["tests"])


def test_eda_distribution_detects_skew_and_refuses_missing_values():
    _upload(pd.DataFrame({
        "Price": np.random.default_rng(7).exponential(size=300),
        "Label": [f"v{index}" for index in range(300)],
    }))
    skewed = client.get(
        "/v1/session/dataset/eda-distribution", params={"column": "Price"}
    )
    assert skewed.status_code == 200
    assert skewed.json()["normality_status"] == "departed"

    reset_session_store_for_testing()
    values = np.arange(80, dtype=float)
    values[4] = np.nan
    _upload(pd.DataFrame({
        "Price": values,
        "Label": [f"v{index}" for index in range(80)],
    }))
    missing = client.get(
        "/v1/session/dataset/eda-distribution", params={"column": "Price"}
    )
    assert missing.status_code == 200
    assert missing.json()["applicable"] is False
    assert missing.json()["missing_count"] == 1


def test_eda_distribution_validates_session_column_and_parameters():
    assert client.get(
        "/v1/session/dataset/eda-distribution", params={"column": "Price"}
    ).status_code == 404

    _upload(pd.DataFrame({
        "Price": np.arange(40, dtype=float),
        "Label": [f"v{index}" for index in range(40)],
    }))
    assert client.get(
        "/v1/session/dataset/eda-distribution", params={"column": "Missing"}
    ).status_code == 404
    assert client.get(
        "/v1/session/dataset/eda-distribution", params={"column": "Label"}
    ).status_code == 422
    assert client.get(
        "/v1/session/dataset/eda-distribution",
        params={"column": "Price", "alpha": 0.5},
    ).status_code == 422
    assert client.get(
        "/v1/session/dataset/eda-distribution",
        params={"column": "Price", "bins": 2},
    ).status_code == 422
