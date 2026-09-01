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
    rng = np.random.default_rng(7)
    x = np.arange(96, dtype=float)
    frame = pd.DataFrame(
        {
            "Date": pd.date_range("2018-01-01", periods=len(x), freq="MS").strftime("%Y-%m-%d"),
            "Price": 15 + 0.05 * x + np.sin(2 * np.pi * x / 12) + rng.normal(0, 1.4, len(x)),
        }
    )
    buffer = io.BytesIO(frame.to_csv(index=False).encode())
    response = client.post("/v1/internal/upload", files={"file": ("series.csv", buffer, "text/csv")})
    assert response.status_code == 200, response.text


def test_profile_exposes_causal_default_comparison_and_visuals():
    _upload()
    response = client.get(
        "/v1/session/dataset/preprocessing/smoothing-profile",
        params={"column": "Price"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] in {"done", "warning"}
    assert body["profile"]["selected_method"] == "ema"
    assert body["profile"]["diagnostics_before"]["normalized_roughness"] is not None
    assert body["profile"]["points"]
    assert body["profile"]["spectrum"]


def test_preview_is_non_mutating_apply_persists_column_and_metadata():
    _upload()
    payload = {
        "column": "Price", "method": "ema", "window": 7, "span": 7,
        "frac": 0.2, "polyorder": 2, "confirm_non_causal": False, "apply": False,
    }
    preview = client.post("/v1/session/dataset/preprocessing/smoothing-transformations", json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()["output_column"] == "Price_ema"
    assert preview.json()["metadata"]["causal"] is True

    assert client.get(
        "/v1/session/dataset/preprocessing/smoothing-profile", params={"column": "Price_ema"}
    ).status_code == 422

    payload["apply"] = True
    applied = client.post("/v1/session/dataset/preprocessing/smoothing-transformations", json=payload)
    assert applied.status_code == 200, applied.text
    session = get_session_store().get(client.cookies.get(SESSION_COOKIE_NAME))
    assert session is not None
    assert session.preprocessing_transformations["Price_ema"]["kind"] == "smoothing"
    assert session.preprocessing_transformations["Price_ema"]["causal"] is True


def test_offline_apply_requires_explicit_confirmation():
    _upload()
    payload = {
        "column": "Price", "method": "lowess", "window": 7, "span": 7,
        "frac": 0.2, "polyorder": 2, "confirm_non_causal": False, "apply": False,
    }
    blocked = client.post("/v1/session/dataset/preprocessing/smoothing-transformations", json=payload)
    assert blocked.status_code == 422
    assert "некаузаль" in blocked.text.lower()

    payload["confirm_non_causal"] = True
    assert client.post(
        "/v1/session/dataset/preprocessing/smoothing-transformations", json=payload
    ).status_code == 200


def test_disabled_mode_is_skipped_but_profile_remains_available():
    _upload()
    assert client.put(
        "/v1/session/dataset/preprocessing-check-modes",
        json={"modes": {"smoothing": "disabled"}},
    ).status_code == 200
    body = client.get(
        "/v1/session/dataset/preprocessing/smoothing-profile", params={"column": "Price"}
    ).json()
    assert body["mode"] == "disabled"
    assert body["status"] == "skipped"
    assert body["status_reason"] == "disabled"


def test_routes_return_404_without_active_dataset():
    assert client.get(
        "/v1/session/dataset/preprocessing/smoothing-profile", params={"column": "Price"}
    ).status_code == 404
    assert client.post(
        "/v1/session/dataset/preprocessing/smoothing-transformations",
        json={"column": "Price", "method": "ema", "apply": False},
    ).status_code == 404

