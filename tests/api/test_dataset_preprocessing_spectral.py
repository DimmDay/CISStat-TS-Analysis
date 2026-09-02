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
    size = 240
    time = np.arange(size, dtype=float)
    frame = pd.DataFrame({
        "Date": pd.date_range("2010-01-01", periods=size, freq="MS"),
        "Price": 3 * np.sin(2 * np.pi * time / 12) + np.sin(2 * np.pi * time / 5),
    })
    buffer = io.BytesIO(frame.to_csv(index=False).encode())
    response = client.post("/v1/internal/upload", files={"file": ("periodic.csv", buffer, "text/csv")})
    assert response.status_code == 200, response.text


def test_profile_exposes_global_robust_and_time_frequency_visuals():
    _upload()
    response = client.get(
        "/v1/session/dataset/preprocessing/spectral-profile",
        params={"column": "Price", "min_cycles": 3, "max_candidates": 6, "welch_segment_length": 64},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "done"
    assert body["profile"]["periodogram"]
    assert body["profile"]["welch"]
    assert body["profile"]["wavelet"]
    assert body["profile"]["candidates"]


def test_preview_then_apply_persists_selection_without_mutating_dataset():
    _upload()
    payload = {
        "column": "Price", "periods": [12], "min_cycles": 3, "max_candidates": 6,
        "welch_segment_length": 64, "confirm_unconfirmed": False, "apply": False,
    }
    preview = client.post("/v1/session/dataset/preprocessing/spectral-selections", json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["selected_periods"] == [12]
    assert preview.json()["applied"] is False

    payload["apply"] = True
    applied = client.post("/v1/session/dataset/preprocessing/spectral-selections", json=payload)
    assert applied.status_code == 200, applied.text
    session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
    assert session is not None
    assert session.dataset.rows == 240
    assert session.dataset.columns == 2
    assert session.preprocessing_spectral_selection["selected_periods"] == [12]

    refreshed = client.get(
        "/v1/session/dataset/preprocessing/spectral-profile", params={"column": "Price"},
    ).json()
    assert refreshed["profile"]["saved_periods"] == [12]


def test_disabled_mode_is_skipped_and_missing_dataset_is_404():
    assert client.get(
        "/v1/session/dataset/preprocessing/spectral-profile", params={"column": "Price"},
    ).status_code == 404
    _upload()
    assert client.put(
        "/v1/session/dataset/preprocessing-check-modes", json={"modes": {"spectral": "disabled"}},
    ).status_code == 200
    body = client.get(
        "/v1/session/dataset/preprocessing/spectral-profile", params={"column": "Price"},
    ).json()
    assert body["mode"] == "disabled"
    assert body["status"] == "skipped"
    assert body["status_reason"] == "disabled"
    invalid = client.get(
        "/v1/session/dataset/preprocessing/spectral-profile",
        params={"column": "Price", "welch_segment_length": 4096},
    )
    assert invalid.status_code == 422
    assert "длиннее ряда" in invalid.text
