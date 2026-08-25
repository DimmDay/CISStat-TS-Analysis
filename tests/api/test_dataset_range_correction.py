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


def _upload_prices() -> None:
    buffer = io.BytesIO()
    pd.DataFrame({"Price": [-5.0, 10.0, 150.0]}).to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("ranges.csv", buffer, "text/csv")},
    )
    assert response.status_code == 200, response.text


def _save_price_rule() -> None:
    response = client.put(
        "/v1/session/dataset/validation-rules",
        json={
            "template_id": "system",
            "overrides": {
                "ranges": [{"name": "Цена", "keywords": ["Price"], "min": 0, "max": 100}],
            },
        },
    )
    assert response.status_code == 200, response.text


def test_profile_and_preview_use_session_rules_without_mutation():
    _upload_prices()
    _save_price_rule()

    profile = client.get("/v1/session/dataset/range-profile")
    assert profile.status_code == 200, profile.text
    assert profile.json()["rule_source"] == "session"
    assert profile.json()["columns"][0]["invalid_count"] == 2

    preview = client.post(
        "/v1/session/dataset/range-corrections",
        json={"columns": ["Price"], "strategy": "clip", "apply": False},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_changed"] == 2
    assert preview.json()["profile"][0]["invalid_count"] == 0

    unchanged = client.get("/v1/session/dataset/range-profile").json()
    assert unchanged["columns"][0]["invalid_count"] == 2


def test_apply_persists_correction_and_revalidation_passes():
    _upload_prices()
    _save_price_rule()

    applied = client.post(
        "/v1/session/dataset/range-corrections",
        json={"columns": ["Price"], "strategy": "clip", "apply": True},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["profile"][0]["invalid_count"] == 0

    validation = client.get("/v1/session/dataset/validate").json()
    assert validation["checks"]["ranges"]["status"] == "done"
    assert validation["checks"]["ranges"]["count"] == 0


def test_row_deletion_updates_session_dataset_metadata():
    _upload_prices()
    _save_price_rule()

    applied = client.post(
        "/v1/session/dataset/range-corrections",
        json={"columns": ["Price"], "strategy": "drop_rows", "apply": True},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["rows_removed"] == 2

    current = client.get("/v1/session/current").json()
    assert current["dataset"]["rows"] == 1
    assert current["dataset"]["columns"] == 1


def test_missing_dataset_returns_404():
    assert client.get("/v1/session/dataset/range-profile").status_code == 404
