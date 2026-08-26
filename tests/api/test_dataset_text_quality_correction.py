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
        "label": ["Clean", "  padded  ", "bad�", "   "],
        "value": [1, 2, 3, 4],
    }).to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("text-quality.csv", buffer, "text/csv")},
    )
    assert response.status_code == 200, response.text


def test_profile_preview_apply_and_revalidation_share_one_mask():
    _upload()

    profile = client.get("/v1/session/dataset/text-quality-profile")
    assert profile.status_code == 200, profile.text
    assert profile.json()["rule_source"] == "system"
    item = profile.json()["columns"][0]
    assert item["column"] == "label"
    assert item["invalid_count"] == 3

    preview = client.post(
        "/v1/session/dataset/text-quality-corrections",
        json={"columns": ["label"], "strategy": "replace_null", "apply": False},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_still_invalid"] == 0
    assert client.get("/v1/session/dataset/text-quality-profile").json()["columns"][0]["invalid_count"] == 3

    applied = client.post(
        "/v1/session/dataset/text-quality-corrections",
        json={"columns": ["label"], "strategy": "replace_null", "apply": True},
    )
    assert applied.status_code == 200, applied.text
    validation = client.get("/v1/session/dataset/validate").json()
    assert validation["checks"]["text_quality"]["status"] == "done"
    assert validation["checks"]["text_quality"]["count"] == 0


def test_profile_returns_all_clean_text_columns_and_numeric_only_is_not_applicable():
    _upload()
    clean = client.post(
        "/v1/session/dataset/text-quality-corrections",
        json={"columns": ["label"], "strategy": "replace_null", "apply": True},
    )
    assert clean.status_code == 200
    profile = client.get("/v1/session/dataset/text-quality-profile").json()
    assert profile["columns"][0]["invalid_count"] == 0

    reset_session_store_for_testing()
    buffer = io.BytesIO(b"value\n1\n2\n")
    client.post("/v1/internal/upload", files={"file": ("numeric.csv", buffer, "text/csv")})
    numeric_profile = client.get("/v1/session/dataset/text-quality-profile")
    assert numeric_profile.status_code == 200
    assert numeric_profile.json() == {"rule_source": "not_applicable", "columns": []}


def test_text_quality_rule_validation_rejects_invalid_limits_and_regex():
    _upload()
    cases = [
        ({"min_length": -1, "max_length": 10}, "неотрицательным"),
        ({"min_length": 10, "max_length": 2}, "не может превышать"),
        ({"allowed_patterns": {"label": "["}}, "regex"),
        ({"allowed_patterns": {"missing": ".*"}}, "отсутствует"),
    ]
    for rules, message in cases:
        response = client.put(
            "/v1/session/dataset/validation-rules",
            json={"template_id": "system", "overrides": {"text_quality": rules}},
        )
        assert response.status_code == 422
        assert message in response.json()["detail"]


def test_missing_dataset_returns_404():
    assert client.get("/v1/session/dataset/text-quality-profile").status_code == 404
