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
    x = np.arange(120, dtype=float)
    frame = pd.DataFrame({
        "Date": pd.date_range("2015-01-01", periods=len(x), freq="MS"),
        "Price": 50 + 0.2 * x + 4 * np.sin(2 * np.pi * x / 12),
    })
    buffer = io.BytesIO(frame.to_csv(index=False).encode())
    response = client.post("/v1/internal/upload", files={"file": ("features.csv", buffer, "text/csv")})
    assert response.status_code == 200, response.text


def _payload(apply: bool) -> dict:
    return {
        "column": "Price", "lags": [1, 12], "rolling_windows": [3],
        "rolling_statistics": ["mean", "std"], "difference_lags": [1],
        "calendar_features": ["month_cyclic", "year"],
        "fourier_periods": [12], "fourier_harmonics": 1,
        "include_time_index": True, "drop_warmup_rows": True, "apply": apply,
    }


def test_profile_exposes_recommendations_and_visual_payloads():
    _upload()
    response = client.get(
        "/v1/session/dataset/preprocessing/feature-generation-profile",
        params={"column": "Price"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "warning"
    assert body["profile"]["preview_points"]
    assert body["profile"]["lag_correlations"]
    assert body["profile"]["catalog"]


def test_preview_then_apply_adds_features_drops_warmup_and_persists_metadata():
    _upload()
    preview = client.post(
        "/v1/session/dataset/preprocessing/feature-generations", json=_payload(False),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["rows_dropped"] == 12
    assert preview.json()["applied"] is False

    applied = client.post(
        "/v1/session/dataset/preprocessing/feature-generations", json=_payload(True),
    )
    assert applied.status_code == 200, applied.text
    session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
    assert session is not None
    assert session.dataset.rows == 108
    assert "Price_lag_12" in session.dataframe.columns
    assert session.preprocessing_feature_generation["target_shift"] == 1

    refreshed = client.get(
        "/v1/session/dataset/preprocessing/feature-generation-profile",
        params={"column": "Price"},
    ).json()
    assert refreshed["status"] == "done"
    assert "Price_lag_12" in refreshed["profile"]["saved_feature_names"]


def test_disabled_mode_and_missing_dataset_contracts():
    assert client.get(
        "/v1/session/dataset/preprocessing/feature-generation-profile",
        params={"column": "Price"},
    ).status_code == 404
    _upload()
    assert client.put(
        "/v1/session/dataset/preprocessing-check-modes",
        json={"modes": {"feature_eng": "disabled"}},
    ).status_code == 200
    body = client.get(
        "/v1/session/dataset/preprocessing/feature-generation-profile",
        params={"column": "Price"},
    ).json()
    assert body["mode"] == "disabled"
    assert body["status"] == "skipped"

