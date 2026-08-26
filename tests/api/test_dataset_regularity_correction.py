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


def _upload() -> None:
    buffer = io.BytesIO()
    pd.DataFrame({
        "Country": ["A", "A", "A", "B", "B", "B"],
        "Date": ["2024-01-01", "2024-01-03", "2024-01-04", "2024-01-01", "2024-01-02", "2024-01-03"],
        "Value": [1, 3, 4, 10, 20, 30],
    }).to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post("/v1/internal/upload", files={"file": ("panel.csv", buffer, "text/csv")})
    assert response.status_code == 200, response.text


def _save_rules() -> None:
    response = client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "system", "overrides": {"regularity": {
            "date_column": "Date", "entity_column": "Country", "frequency": "D",
            "gap_threshold_multiplier": 1.5,
        }}},
    )
    assert response.status_code == 200, response.text


def test_profile_preview_apply_and_revalidation_share_one_contract():
    _upload(); _save_rules()

    profile = client.get("/v1/session/dataset/regularity-profile")
    assert profile.status_code == 200, profile.text
    assert profile.json()["rule_source"] == "session"
    assert profile.json()["profile"]["gap_count"] == 1

    preview = client.post(
        "/v1/session/dataset/regularity-corrections",
        json={"strategy": "interpolate", "frequency": "D", "apply": False},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["rows_added"] == 1
    assert preview.json()["total_violations_after"] == 0
    assert client.get("/v1/session/dataset/regularity-profile").json()["profile"]["gap_count"] == 1

    applied = client.post(
        "/v1/session/dataset/regularity-corrections",
        json={"strategy": "interpolate", "frequency": "D", "apply": True},
    )
    assert applied.status_code == 200, applied.text
    validation = client.get("/v1/session/dataset/validate").json()
    assert validation["checks"]["regularity"]["status"] == "done"
    assert validation["checks"]["regularity"]["count"] == 0


def test_rule_validation_rejects_missing_columns_frequency_and_multiplier():
    _upload()
    cases = [
        ({"date_column": "Missing"}, "отсутствует"),
        ({"date_column": "Date", "entity_column": "Missing"}, "отсутствует"),
        ({"date_column": "Date", "frequency": "INVALID"}, "частот"),
        ({"date_column": "Date", "gap_threshold_multiplier": 1.0}, "больше 1"),
    ]
    for rules, message in cases:
        response = client.put(
            "/v1/session/dataset/validation-rules",
            json={"template_id": "system", "overrides": {"regularity": rules}},
        )
        assert response.status_code == 422
        assert message in response.json()["detail"]


def test_missing_dataset_returns_404():
    assert client.get("/v1/session/dataset/regularity-profile").status_code == 404
