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


def _upload_df(df: pd.DataFrame) -> None:
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    buf.seek(0)
    response = client.post("/v1/internal/upload", files={"file": ("formats.csv", buf, "text/csv")})
    assert response.status_code == 200, response.text


def _save_email_rule() -> None:
    response = client.put(
        "/v1/session/dataset/validation-rules",
        json={
            "template_id": "system",
            "overrides": {
                "formats": {
                    "Email": {"pattern": r"^[^@\s]+@[^@\s]+\.[^@\s]+$", "threshold": 100}
                }
            },
        },
    )
    assert response.status_code == 200, response.text


def test_profile_and_preview_use_active_session_format_rules_without_mutation():
    _upload_df(pd.DataFrame({"Email": ["ok@example.com", "broken", None]}))
    _save_email_rule()

    profile = client.get("/v1/session/dataset/format-profile")
    assert profile.status_code == 200, profile.text
    assert profile.json()["rule_source"] == "session"
    assert profile.json()["columns"][0]["invalid_count"] == 1
    assert profile.json()["columns"][0]["invalid_examples"] == ["broken"]

    preview = client.post(
        "/v1/session/dataset/format-corrections",
        json={"columns": ["Email"], "strategy": "replace_null", "apply": False},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["applied"] is False
    assert preview.json()["total_changed"] == 1

    unchanged = client.get("/v1/session/dataset/format-profile").json()
    assert unchanged["columns"][0]["invalid_count"] == 1


def test_apply_persists_correction_and_revalidation_passes():
    _upload_df(pd.DataFrame({"Email": ["ok@example.com", "broken"]}))
    _save_email_rule()

    applied = client.post(
        "/v1/session/dataset/format-corrections",
        json={"columns": ["Email"], "strategy": "replace_null", "apply": True},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] is True
    assert applied.json()["profile"][0]["invalid_count"] == 0

    validation = client.get("/v1/session/dataset/validate").json()
    assert validation["checks"]["formats"]["status"] == "done"
    assert validation["checks"]["formats"]["count"] == 0


def test_missing_dataset_returns_404():
    response = client.get("/v1/session/dataset/format-profile")
    assert response.status_code == 404
