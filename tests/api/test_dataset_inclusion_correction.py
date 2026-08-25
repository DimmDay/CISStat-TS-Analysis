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
    pd.DataFrame({"Country": ["A", "X", "B"], "Value": [1, 2, 3]}).to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("inclusion.csv", buffer, "text/csv")},
    )
    assert response.status_code == 200, response.text


def _save_rule() -> None:
    response = client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "system", "overrides": {"inclusion": {
            "Country": {"allowed_values": ["A", "B"], "default_value": "A"}
        }}},
    )
    assert response.status_code == 200, response.text


def test_profile_preview_apply_and_revalidation_share_the_same_domain():
    _upload()
    _save_rule()

    profile = client.get("/v1/session/dataset/inclusion-profile")
    assert profile.status_code == 200, profile.text
    assert profile.json()["rule_source"] == "session"
    assert profile.json()["columns"][0]["invalid_count"] == 1
    assert profile.json()["columns"][0]["invalid_values"] == [{"value": "X", "count": 1}]

    preview = client.post(
        "/v1/session/dataset/inclusion-corrections",
        json={"columns": ["Country"], "strategy": "replace_default", "apply": False},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_still_invalid"] == 0
    assert client.get("/v1/session/dataset/inclusion-profile").json()["columns"][0]["invalid_count"] == 1

    applied = client.post(
        "/v1/session/dataset/inclusion-corrections",
        json={"columns": ["Country"], "strategy": "replace_default", "apply": True},
    )
    assert applied.status_code == 200, applied.text
    validation = client.get("/v1/session/dataset/validate").json()
    assert validation["checks"]["inclusion"]["status"] == "done"
    assert validation["checks"]["inclusion"]["count"] == 0


def test_rule_validation_rejects_unknown_columns_empty_domains_and_bad_defaults():
    _upload()
    cases = [
        ({"Missing": {"allowed_values": ["A"]}}, "отсутствует"),
        ({"Country": {"allowed_values": []}}, "непустой список"),
        ({"Country": {"allowed_values": ["A"], "default_value": "Unknown"}}, "входить в допустимый набор"),
    ]
    for inclusion, message in cases:
        response = client.put(
            "/v1/session/dataset/validation-rules",
            json={"template_id": "system", "overrides": {"inclusion": inclusion}},
        )
        assert response.status_code == 422
        assert message in response.json()["detail"]


def test_missing_dataset_returns_404():
    assert client.get("/v1/session/dataset/inclusion-profile").status_code == 404

