from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)


client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


def _upload() -> None:
    x = np.arange(96, dtype=float)
    frame = pd.DataFrame({
        "Date": pd.date_range("2018-01-01", periods=len(x), freq="MS").strftime("%Y-%m-%d"),
        "Price": np.exp(2 + 0.02 * x) * (1 + 0.2 * np.sin(2 * np.pi * x / 12)),
    })
    buffer = io.BytesIO(frame.to_csv(index=False).encode())
    response = client.post("/v1/internal/upload", files={"file": ("series.csv", buffer, "text/csv")})
    assert response.status_code == 200, response.text


def test_profile_exposes_selected_transform_diagnostics_and_visual_data():
    _upload()
    response = client.get(
        "/v1/session/dataset/preprocessing/variance-profile",
        params={"column": "Price"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in {"done", "warning"}
    assert body["profile"]["applicable"] is True
    assert body["profile"]["selected_method"] == "box_cox"
    assert body["profile"]["diagnostics_before"]["levene_pvalue"] is not None
    assert body["profile"]["diagnostics_after"] is not None
    assert body["profile"]["points"]
    assert body["profile"]["histogram"]


def test_preview_does_not_persist_apply_adds_column_and_saves_inverse_metadata():
    _upload()
    payload = {"column": "Price", "method": "box_cox", "lambda_value": None, "apply": False}
    preview = client.post("/v1/session/dataset/preprocessing/variance-transformations", json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["applied"] is False
    assert preview.json()["output_column"] == "Price_box_cox"
    assert preview.json()["metadata"]["inverse_supported"] is True

    not_persisted = client.get(
        "/v1/session/dataset/preprocessing/variance-profile",
        params={"column": "Price_box_cox"},
    )
    assert not_persisted.status_code == 422

    payload["apply"] = True
    applied = client.post("/v1/session/dataset/preprocessing/variance-transformations", json=payload)
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] is True
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    assert session is not None
    assert session.preprocessing_transformations["Price_box_cox"]["lambda_value"] is not None

    persisted = client.get(
        "/v1/session/dataset/preprocessing/variance-profile",
        params={"column": "Price_box_cox"},
    )
    assert persisted.status_code == 200

def test_disabled_mode_is_skipped_but_profile_stays_available():
    _upload()
    assert client.put(
        "/v1/session/dataset/preprocessing-check-modes",
        json={"modes": {"variance_stab": "disabled"}},
    ).status_code == 200
    body = client.get(
        "/v1/session/dataset/preprocessing/variance-profile",
        params={"column": "Price"},
    ).json()
    assert body["mode"] == "disabled"
    assert body["status"] == "skipped"
    assert body["status_reason"] == "disabled"


def test_routes_return_404_without_active_dataset():
    assert client.get(
        "/v1/session/dataset/preprocessing/variance-profile",
        params={"column": "Price"},
    ).status_code == 404
    assert client.post(
        "/v1/session/dataset/preprocessing/variance-transformations",
        json={"column": "Price", "method": "log", "apply": False},
    ).status_code == 404
