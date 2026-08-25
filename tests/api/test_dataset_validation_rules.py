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


def _upload(df: pd.DataFrame) -> None:
    buffer = io.BytesIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)
    response = client.post(
        "/v1/internal/upload",
        files={"file": ("rules.csv", buffer, "text/csv")},
    )
    assert response.status_code == 200, response.text


def _fao_df() -> pd.DataFrame:
    return pd.DataFrame({
        "Country": ["Беларусь", "Беларусь", "Казахстан", "Казахстан"],
        "Year": [2020, 2021, 2020, 2021],
        "Price": [100.0, 110.0, 120.0, 130.0],
        "usd/tonne": ["usd", "usd", "usd", "usd"],
    })


def test_rules_endpoint_defaults_to_system():
    response = client.get("/v1/session/dataset/validation-rules")
    assert response.status_code == 200
    assert response.json() == {"template_id": "system", "overrides": {}}


def test_selected_template_is_saved_and_used_by_global_validation():
    _upload(_fao_df())
    saved = client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "fao_prices", "overrides": {}},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"template_id": "fao_prices", "overrides": {}}

    validation = client.get("/v1/session/dataset/validate")
    assert validation.status_code == 200, validation.text
    body = validation.json()
    assert body["rules_source"] == "template"
    assert body["validation_template_id"] == "fao_prices"
    for check_id in ("data_types", "formats", "ranges", "consistency", "uniqueness", "inclusion", "referential"):
        assert body["checks"][check_id]["rule_source"] == "template"
    assert body["checks"]["uniqueness"]["status"] == "done"
    assert body["checks"]["formats"] == {
        "status": "done",
        "count": 0,
        "items": [],
        "scope": "column",
        "error": None,
        "rule_source": "template",
    }

    profile = client.get("/v1/session/dataset/format-profile")
    assert profile.status_code == 200, profile.text
    assert profile.json()["rule_source"] == "template"
    assert [item["column"] for item in profile.json()["columns"]] == [
        "Country", "Year", "usd/tonne"
    ]
    assert all(item["invalid_count"] == 0 for item in profile.json()["columns"])


def test_session_override_has_priority_over_template():
    _upload(_fao_df())
    saved = client.put(
        "/v1/session/dataset/validation-rules",
        json={
            "template_id": "fao_prices",
            "overrides": {
                "ranges": [{"name": "Узкая цена", "keywords": ["price"], "min": 0, "max": 105}],
            },
        },
    )
    assert saved.status_code == 200, saved.text

    body = client.get("/v1/session/dataset/validate").json()
    assert body["rules_source"] == "session"
    assert body["checks"]["ranges"]["rule_source"] == "session"
    assert body["checks"]["ranges"]["status"] == "warning"
    assert body["checks"]["ranges"]["count"] == 3


def test_reupload_resets_template_and_overrides():
    _upload(_fao_df())
    assert client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "macro", "overrides": {"sufficiency": {"min_obs_trend": 20}}},
    ).status_code == 200

    _upload(_fao_df())
    assert client.get("/v1/session/dataset/validation-rules").json() == {
        "template_id": "system",
        "overrides": {},
    }


def test_rules_reject_unknown_section_and_require_dataset_for_write():
    missing = client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "system", "overrides": {}},
    )
    assert missing.status_code == 404

    _upload(_fao_df())
    invalid = client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "system", "overrides": {"unknown": {}}},
    )
    assert invalid.status_code == 422

    malformed = client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "system", "overrides": {"ranges": {"min": 0}}},
    )
    assert malformed.status_code == 422


def test_empty_override_sections_are_normalized_away():
    _upload(_fao_df())
    response = client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "fao_prices", "overrides": {"ranges": []}},
    )
    assert response.status_code == 200
    assert response.json() == {"template_id": "fao_prices", "overrides": {}}
    assert client.get("/v1/session/dataset/validate").json()["rules_source"] == "template"


def test_format_overrides_require_an_existing_column_and_valid_regex():
    _upload(_fao_df())

    missing_column = client.put(
        "/v1/session/dataset/validation-rules",
        json={
            "template_id": "system",
            "overrides": {"formats": {"Unknown": {"pattern": "^[A-Z]+$", "threshold": 100}}},
        },
    )
    assert missing_column.status_code == 422
    assert "отсутствует в датасете" in missing_column.json()["detail"]

    invalid_regex = client.put(
        "/v1/session/dataset/validation-rules",
        json={
            "template_id": "system",
            "overrides": {"formats": {"Country": {"pattern": "[", "threshold": 100}}},
        },
    )
    assert invalid_regex.status_code == 422
    assert "Некорректный regex" in invalid_regex.json()["detail"]


def test_range_overrides_require_keywords_and_consistent_bounds():
    _upload(_fao_df())

    missing_keywords = client.put(
        "/v1/session/dataset/validation-rules",
        json={
            "template_id": "system",
            "overrides": {"ranges": [{"keywords": [], "min": 0, "max": 100}]},
        },
    )
    assert missing_keywords.status_code == 422
    assert "ключевое слово" in missing_keywords.json()["detail"]

    inverted = client.put(
        "/v1/session/dataset/validation-rules",
        json={
            "template_id": "system",
            "overrides": {"ranges": [{"keywords": ["Price"], "min": 100, "max": 0}]},
        },
    )
    assert inverted.status_code == 422
    assert "минимум не может превышать максимум" in inverted.json()["detail"]


def test_unmatched_template_range_is_reported_as_no_applicable_reference():
    _upload(pd.DataFrame({"Metric": [1.0, 2.0, 3.0]}))
    assert client.put(
        "/v1/session/dataset/validation-rules",
        json={"template_id": "fao_prices", "overrides": {}},
    ).status_code == 200

    ranges = client.get("/v1/session/dataset/validate").json()["checks"]["ranges"]
    assert ranges["status"] == "pending"
    assert ranges["count"] is None
    assert ranges["rule_source"] == "not_applicable"
