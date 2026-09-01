from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import SESSION_COOKIE_NAME, get_session_store, reset_session_store_for_testing


client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


def _upload() -> None:
    rng = np.random.default_rng(31)
    frame = pd.DataFrame({
        "Date": pd.date_range("2010-01-01", periods=180, freq="MS").strftime("%Y-%m-%d"),
        "Price": np.cumsum(rng.normal(size=180)),
    })
    buffer = io.BytesIO(frame.to_csv(index=False).encode())
    response = client.post("/v1/internal/upload", files={"file": ("walk.csv", buffer, "text/csv")})
    assert response.status_code == 200, response.text


def test_profile_exposes_consensus_candidate_comparison_and_visuals():
    _upload()
    response = client.get(
        "/v1/session/dataset/preprocessing/stationarity-profile",
        params={"column": "Price", "seasonal_period": 12},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "warning"
    assert body["profile"]["selected_method"] == "first_difference"
    assert body["profile"]["tests"]
    assert body["profile"]["points"]
    assert body["profile"]["acf"]


def test_preview_is_non_mutating_apply_drops_prefix_and_persists_inverse_metadata():
    _upload()
    payload = {
        "column": "Price", "method": "first_difference", "seasonal_period": 12,
        "confirm_non_causal": False, "apply": False,
    }
    preview = client.post(
        "/v1/session/dataset/preprocessing/stationarity-transformations", json=payload,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["rows_before"] == 180
    assert preview.json()["rows_after"] == 179
    assert preview.json()["output_column"] == "Price_diff1"

    assert client.get(
        "/v1/session/dataset/preprocessing/stationarity-profile",
        params={"column": "Price_diff1"},
    ).status_code == 422

    payload["apply"] = True
    applied = client.post(
        "/v1/session/dataset/preprocessing/stationarity-transformations", json=payload,
    )
    assert applied.status_code == 200, applied.text
    session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
    assert session is not None
    metadata = session.preprocessing_transformations["Price_diff1"]
    assert metadata["kind"] == "stationarity"
    assert metadata["regular_order"] == 1
    assert metadata["inverse_supported"] is True
    assert session.dataset.rows == 179


def test_offline_detrend_requires_separate_confirmation():
    _upload()
    payload = {
        "column": "Price", "method": "linear_detrend", "seasonal_period": 12,
        "confirm_non_causal": False, "apply": False,
    }
    blocked = client.post(
        "/v1/session/dataset/preprocessing/stationarity-transformations", json=payload,
    )
    assert blocked.status_code == 422
    assert "некаузаль" in blocked.text.lower()

    payload["confirm_non_causal"] = True
    assert client.post(
        "/v1/session/dataset/preprocessing/stationarity-transformations", json=payload,
    ).status_code == 200


def test_disabled_mode_is_skipped_but_profile_remains_available():
    _upload()
    assert client.put(
        "/v1/session/dataset/preprocessing-check-modes",
        json={"modes": {"stationarity": "disabled"}},
    ).status_code == 200
    body = client.get(
        "/v1/session/dataset/preprocessing/stationarity-profile",
        params={"column": "Price"},
    ).json()
    assert body["mode"] == "disabled"
    assert body["status"] == "skipped"
    assert body["status_reason"] == "disabled"


def test_routes_return_404_without_active_dataset():
    assert client.get(
        "/v1/session/dataset/preprocessing/stationarity-profile", params={"column": "Price"},
    ).status_code == 404
    assert client.post(
        "/v1/session/dataset/preprocessing/stationarity-transformations",
        json={"column": "Price", "method": "first_difference", "apply": False},
    ).status_code == 404
