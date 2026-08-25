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
        "Country": ["A", "A", "B"],
        "Year": [2020, 2020, 2021],
        "Price": [10.0, 14.0, 30.0],
    }).to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("duplicates.csv", buffer, "text/csv")},
    )
    assert response.status_code == 200, response.text


def test_profile_preview_apply_and_revalidation_share_one_key():
    _upload()
    saved = client.put(
        "/v1/session/dataset/validation-rules",
        json={
            "template_id": "system",
            "overrides": {"uniqueness": {"composite_key": ["Country", "Year"]}},
        },
    )
    assert saved.status_code == 200, saved.text

    profile = client.get("/v1/session/dataset/uniqueness-profile")
    assert profile.status_code == 200, profile.text
    assert profile.json()["rule_source"] == "session"
    assert profile.json()["profile"]["duplicate_rows"] == 2
    assert profile.json()["profile"]["redundant_rows"] == 1

    preview = client.post(
        "/v1/session/dataset/uniqueness-corrections",
        json={"strategy": "keep_first", "apply": False},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["rows_removed"] == 1
    assert preview.json()["profile"]["duplicate_rows"] == 0
    assert client.get("/v1/session/dataset/uniqueness-profile").json()["profile"]["duplicate_rows"] == 2

    applied = client.post(
        "/v1/session/dataset/uniqueness-corrections",
        json={"strategy": "keep_first", "apply": True},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["profile"]["duplicate_rows"] == 0
    validation = client.get("/v1/session/dataset/validate").json()
    assert validation["checks"]["uniqueness"]["status"] == "done"
    assert validation["checks"]["uniqueness"]["count"] == 0
    assert client.get("/v1/session/current").json()["dataset"]["rows"] == 2


def test_uniqueness_rule_rejects_unknown_and_repeated_key_columns():
    _upload()

    missing = client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "system", "overrides": {"uniqueness": {"composite_key": ["Missing"]}}},
    )
    assert missing.status_code == 422
    assert "отсутствует" in missing.json()["detail"]

    repeated = client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "system", "overrides": {"uniqueness": {"composite_key": ["Country", "Country"]}}},
    )
    assert repeated.status_code == 422
    assert "повторяться" in repeated.json()["detail"]

    system_fallback = client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "fao_prices", "overrides": {"uniqueness": {"composite_key": []}}},
    )
    assert system_fallback.status_code == 200, system_fallback.text
    assert system_fallback.json()["overrides"]["uniqueness"]["composite_key"] == []


def test_missing_dataset_returns_404():
    assert client.get("/v1/session/dataset/uniqueness-profile").status_code == 404
