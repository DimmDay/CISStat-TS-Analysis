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


def _upload(df: pd.DataFrame) -> None:
    buffer = io.BytesIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("eda.csv", buffer, "text/csv")},
    )
    assert response.status_code == 200, response.text


def test_existing_stats_endpoint_covers_eda_descriptive_contract():
    _upload(pd.DataFrame({
        "Price": [10.0, 20.0, 30.0, 40.0],
        "Volume": [100.0, 200.0, 300.0, 400.0],
        "Region": ["A", "B", "A", "B"],
    }))

    response = client.get("/v1/session/dataset/stats")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["min_non_null_for_stats"] == 2
    columns = {item["name"]: item for item in body["columns"]}
    assert set(columns) == {"Price", "Volume"}
    assert columns["Price"]["non_null_count"] == 4
    assert columns["Price"]["stats"]["mean"] == pytest.approx(25.0)
    assert columns["Price"]["stats"]["median"] == pytest.approx(25.0)
    assert columns["Price"]["stats"]["std"] == pytest.approx(12.909944, rel=1e-5)
    assert columns["Price"]["stats"]["iqr"] == pytest.approx(15.0)


def test_existing_distribution_endpoint_supplies_all_visualization_tabs():
    _upload(pd.DataFrame({
        "Price": [float(value) for value in range(1, 41)],
        "Region": ["A", "B"] * 20,
    }))

    response = client.get("/v1/session/dataset/distribution", params={"column": "Price"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["column"] == "Price"
    assert body["non_null_count"] == 40
    assert body["scatter"]
    assert body["histogram"]
    assert body["kde"]


def test_stats_endpoint_serializes_short_numeric_columns_without_nan():
    _upload(pd.DataFrame({
        "Short": [1.0, 2.0, None, None],
        "Label": ["A", "B", "C", "D"],
    }))

    response = client.get("/v1/session/dataset/stats")
    assert response.status_code == 200, response.text
    stats = response.json()["columns"][0]["stats"]
    assert stats["mean"] == pytest.approx(1.5)
    assert stats["skewness"] is None
    assert stats["kurtosis"] is None
    assert stats["distribution_hint"] == "Недостаточно данных для оценки формы распределения"


def test_descriptive_endpoints_return_404_without_active_dataset():
    assert client.get("/v1/session/dataset/stats").status_code == 404
    assert client.get("/v1/session/dataset/distribution", params={"column": "Price"}).status_code == 404
