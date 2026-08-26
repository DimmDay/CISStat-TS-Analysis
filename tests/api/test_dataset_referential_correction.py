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
    pd.DataFrame({"CountryCode": ["BY", "XX", "KZ"], "Value": [1, 2, 3]}).to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("referential.csv", buffer, "text/csv")},
    )
    assert response.status_code == 200, response.text


def _save_rule() -> None:
    response = client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "system", "overrides": {"referential": [{
            "name": "Код страны существует",
            "child_column": "CountryCode",
            "allowed_values": ["BY", "KZ"],
            "default_value": "BY",
        }]}},
    )
    assert response.status_code == 200, response.text


def test_profile_preview_apply_and_revalidation_share_the_same_reference():
    _upload()
    _save_rule()

    profile = client.get("/v1/session/dataset/referential-profile")
    assert profile.status_code == 200, profile.text
    assert profile.json()["rule_source"] == "session"
    assert profile.json()["rules"][0]["invalid_count"] == 1
    assert profile.json()["rules"][0]["invalid_values"] == [{"value": "XX", "count": 1}]

    preview = client.post(
        "/v1/session/dataset/referential-corrections",
        json={"rule_indices": [0], "strategy": "replace_default", "apply": False},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_still_invalid"] == 0
    assert client.get("/v1/session/dataset/referential-profile").json()["rules"][0]["invalid_count"] == 1

    applied = client.post(
        "/v1/session/dataset/referential-corrections",
        json={"rule_indices": [0], "strategy": "replace_default", "apply": True},
    )
    assert applied.status_code == 200, applied.text
    validation = client.get("/v1/session/dataset/validate").json()
    assert validation["checks"]["referential"]["status"] == "done"
    assert validation["checks"]["referential"]["count"] == 0


def test_rule_validation_rejects_unknown_columns_empty_references_and_bad_defaults():
    _upload()
    cases = [
        ([{"name": "FK", "child_column": "Missing", "allowed_values": ["A"]}], "отсутствует"),
        ([{"name": "FK", "child_column": "CountryCode", "allowed_values": []}], "непустой список"),
        ([{"name": "FK", "child_column": "CountryCode", "allowed_values": ["BY"], "default_value": "XX"}], "входить в справочник"),
    ]
    for rules, message in cases:
        response = client.put(
            "/v1/session/dataset/validation-rules",
            json={"template_id": "system", "overrides": {"referential": rules}},
        )
        assert response.status_code == 422
        assert message in response.json()["detail"]


def test_missing_dataset_returns_404():
    assert client.get("/v1/session/dataset/referential-profile").status_code == 404

