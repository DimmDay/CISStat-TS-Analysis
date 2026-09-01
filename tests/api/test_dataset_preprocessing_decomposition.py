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


def _upload() -> None:
    index = np.arange(60, dtype=float)
    frame = pd.DataFrame({
        "Date": pd.date_range("2020-01-01", periods=60, freq="MS").strftime("%Y-%m-%d"),
        "Price": 50 + index / 2 + 8 * np.sin(2 * np.pi * index / 12),
    })
    buffer = io.BytesIO(frame.to_csv(index=False).encode())
    response = client.post("/v1/internal/upload", files={"file": ("series.csv", buffer, "text/csv")})
    assert response.status_code == 200, response.text


def test_profile_uses_target_and_exposes_real_diagnostics():
    _upload()
    response = client.get(
        "/v1/session/dataset/preprocessing/decomposition-profile",
        params={"column": "Price"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in {"done", "warning"}
    assert body["profile"]["applicable"] is True
    assert body["profile"]["period"] == 12
    assert body["profile"]["method"] == "STL"
    assert len(body["profile"]["seasonal_pattern"]) == 12


def test_preview_does_not_persist_but_apply_adds_columns_atomically():
    _upload()
    payload = {
        "column": "Price", "period": 12, "robust": True,
        "outputs": ["components", "seasonally_adjusted"], "apply": False,
    }
    preview = client.post("/v1/session/dataset/preprocessing/decomposition-outputs", json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["applied"] is False
    assert preview.json()["columns_before"] == 2
    assert preview.json()["columns_after"] == 6

    before_apply = client.get(
        "/v1/session/dataset/preprocessing/decomposition-profile",
        params={"column": "Price_trend"},
    )
    assert before_apply.status_code == 422

    payload["apply"] = True
    applied = client.post("/v1/session/dataset/preprocessing/decomposition-outputs", json=payload)
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] is True

    persisted = client.get(
        "/v1/session/dataset/preprocessing/decomposition-profile",
        params={"column": "Price_trend", "period": 12},
    )
    assert persisted.status_code == 200


def test_disabled_mode_is_skipped_but_profile_stays_available():
    _upload()
    assert client.put(
        "/v1/session/dataset/preprocessing-check-modes",
        json={"modes": {"decomposition": "disabled"}},
    ).status_code == 200
    body = client.get(
        "/v1/session/dataset/preprocessing/decomposition-profile",
        params={"column": "Price"},
    ).json()
    assert body["mode"] == "disabled"
    assert body["status"] == "skipped"
    assert body["status_reason"] == "disabled"
    assert body["profile"]["applicable"] is True


def test_routes_return_404_without_active_dataset():
    assert client.get(
        "/v1/session/dataset/preprocessing/decomposition-profile",
        params={"column": "Price"},
    ).status_code == 404
    assert client.post(
        "/v1/session/dataset/preprocessing/decomposition-outputs",
        json={"column": "Price", "outputs": ["components"], "apply": False},
    ).status_code == 404
