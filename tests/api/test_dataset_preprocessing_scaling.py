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
    x = np.arange(100, dtype=float)
    frame = pd.DataFrame({
        "Date": pd.date_range("2018-01-01", periods=len(x), freq="D"),
        "Price": 100 + x,
        "Volume": 10_000 + 250 * x,
        "Temperature": 5 + np.sin(x / 8),
    })
    buffer = io.BytesIO(frame.to_csv(index=False).encode())
    response = client.post("/v1/internal/upload", files={"file": ("scaling.csv", buffer, "text/csv")})
    assert response.status_code == 200, response.text


def _payload(apply: bool) -> dict:
    return {
        "target_column": "Price",
        "columns": ["Volume", "Temperature"],
        "method": "standard",
        "feature_range": [0.0, 1.0],
        "quantile_range": [25.0, 75.0],
        "output_distribution": "normal",
        "n_quantiles": 100,
        "confirm_nonlinear": False,
        "apply": apply,
    }


def test_profile_exposes_feature_matrix_and_five_visual_payloads():
    _upload()
    response = client.get(
        "/v1/session/dataset/preprocessing/scaling-profile", params={"column": "Price"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "warning"
    assert body["profile"]["suggested_columns"] == ["Volume", "Temperature"]
    assert body["profile"]["preview_points"]
    assert body["profile"]["range_points"]
    assert body["profile"]["methods"]


def test_preview_then_apply_saves_fold_safe_recipe_without_mutating_dataframe():
    _upload()
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    before = store.get(session_id).dataframe.copy(deep=True)

    preview = client.post(
        "/v1/session/dataset/preprocessing/scaling-recipes", json=_payload(False),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["applied"] is False

    applied = client.post(
        "/v1/session/dataset/preprocessing/scaling-recipes", json=_payload(True),
    )
    assert applied.status_code == 200, applied.text
    session = store.get(session_id)
    pd.testing.assert_frame_equal(session.dataframe, before)
    assert session.preprocessing_scaling_recipe["fit_policy"] == "per_train_fold"
    assert session.preprocessing_scaling_recipe["columns"] == ["Volume", "Temperature"]

    refreshed = client.get(
        "/v1/session/dataset/preprocessing/scaling-profile", params={"column": "Price"},
    ).json()
    assert refreshed["status"] == "done"
    assert refreshed["profile"]["configured"] is True


def test_quantile_gate_disabled_mode_and_missing_dataset_contracts():
    assert client.get(
        "/v1/session/dataset/preprocessing/scaling-profile", params={"column": "Price"},
    ).status_code == 404
    _upload()
    nonlinear = _payload(False) | {"method": "quantile"}
    response = client.post(
        "/v1/session/dataset/preprocessing/scaling-recipes", json=nonlinear,
    )
    assert response.status_code == 422
    assert "нелинейн" in response.json()["detail"].lower()

    assert client.put(
        "/v1/session/dataset/preprocessing-check-modes",
        json={"modes": {"scaling": "disabled"}},
    ).status_code == 200
    body = client.get(
        "/v1/session/dataset/preprocessing/scaling-profile", params={"column": "Price"},
    ).json()
    assert body["mode"] == "disabled"
    assert body["status"] == "skipped"

