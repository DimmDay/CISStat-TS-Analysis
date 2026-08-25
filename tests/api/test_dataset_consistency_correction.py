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


def _upload_unsorted() -> None:
    buffer = io.BytesIO()
    pd.DataFrame({
        "Country": ["A", "A", "A", "B", "B"],
        "Year": [2020, 2022, 2021, 2020, 2021],
        "Price": [10.0, 20.0, 30.0, 40.0, 50.0],
    }).to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("consistency.csv", buffer, "text/csv")},
    )
    assert response.status_code == 200, response.text


def _save_chronology_rule() -> None:
    response = client.put(
        "/v1/session/dataset/validation-rules",
        json={
            "template_id": "system",
            "overrides": {"consistency": [{
                "name": "Хронология по странам",
                "type": "chronology",
                "columns": ["Year"],
                "group_column": "Country",
            }]},
        },
    )
    assert response.status_code == 200, response.text


def test_profile_and_preview_use_session_rules_without_mutation():
    _upload_unsorted()
    _save_chronology_rule()

    profile = client.get("/v1/session/dataset/consistency-profile")
    assert profile.status_code == 200, profile.text
    assert profile.json()["rule_source"] == "session"
    assert profile.json()["rules"][0]["invalid_count"] == 1
    assert profile.json()["rules"][0]["affected_rows"] == 2

    preview = client.post(
        "/v1/session/dataset/consistency-corrections",
        json={"rule_indices": [0], "strategy": "sort_chronology", "apply": False},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["rules"][0]["still_invalid"] == 0
    assert preview.json()["profile"][0]["invalid_count"] == 0

    unchanged = client.get("/v1/session/dataset/consistency-profile").json()
    assert unchanged["rules"][0]["invalid_count"] == 1


def test_apply_persists_sort_updates_metadata_and_revalidation_passes():
    _upload_unsorted()
    _save_chronology_rule()

    applied = client.post(
        "/v1/session/dataset/consistency-corrections",
        json={"rule_indices": [0], "strategy": "sort_chronology", "apply": True},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["profile"][0]["invalid_count"] == 0

    validation = client.get("/v1/session/dataset/validate").json()
    assert validation["checks"]["consistency"]["status"] == "done"
    assert validation["checks"]["consistency"]["count"] == 0

    current = client.get("/v1/session/current").json()
    assert current["dataset"]["rows"] == 5
    assert current["dataset"]["columns"] == 3


def test_consistency_rule_validation_rejects_unknown_columns_and_operators():
    _upload_unsorted()

    valid = client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "system", "overrides": {"consistency": [{
            "name": "Цена ниже года",
            "type": "comparison",
            "columns": ["Price", "Year"],
            "operator": "<",
        }]}},
    )
    assert valid.status_code == 200, valid.text

    missing = client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "system", "overrides": {"consistency": [{
            "name": "Missing",
            "type": "chronology",
            "columns": ["Missing"],
        }]}},
    )
    assert missing.status_code == 422
    assert "отсутствует" in missing.json()["detail"]

    operator = client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "system", "overrides": {"consistency": [{
            "name": "Bad operator",
            "type": "comparison",
            "columns": ["Price", "Year"],
            "operator": "contains",
        }]}},
    )
    assert operator.status_code == 422
    assert "оператор" in operator.json()["detail"]


def test_missing_dataset_returns_404():
    assert client.get("/v1/session/dataset/consistency-profile").status_code == 404
