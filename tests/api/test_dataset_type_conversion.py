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
    response = client.post("/v1/internal/upload", files={"file": ("types.csv", buf, "text/csv")})
    assert response.status_code == 200, response.text


def _payload(*, apply: bool, invalid_policy: str = "reject") -> dict:
    return {
        "conversions": [{"column": "Amount", "target_type": "float"}],
        "invalid_policy": invalid_policy,
        "apply": apply,
    }


def test_preview_reports_impact_without_mutating_session_dataframe():
    _upload_df(pd.DataFrame({"Amount": ["10.5", "bad", "30"], "Label": ["a", "b", "c"]}))

    response = client.post("/v1/session/dataset/convert-types", json=_payload(apply=False))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] is False
    assert body["total_invalid"] == 1
    assert body["columns"][0]["invalid_examples"] == ["bad"]

    profile = client.get("/v1/session/dataset/validate").json()["type_profile"]
    amount = next(column for column in profile if column["name"] == "Amount")
    assert amount["dtype"] == "object"


def test_reject_policy_is_atomic_and_does_not_apply_invalid_conversion():
    _upload_df(pd.DataFrame({"Amount": ["10.5", "bad", "30"]}))

    response = client.post("/v1/session/dataset/convert-types", json=_payload(apply=True))
    assert response.status_code == 422
    assert "1 значений не удалось преобразовать" in response.json()["detail"]

    profile = client.get("/v1/session/dataset/validate").json()["type_profile"]
    assert profile[0]["dtype"] == "object"


def test_coerce_policy_applies_conversion_and_persists_new_profile():
    _upload_df(pd.DataFrame({"Amount": ["10.5", "bad", "30"]}))

    response = client.post(
        "/v1/session/dataset/convert-types",
        json=_payload(apply=True, invalid_policy="coerce"),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] is True
    assert body["type_profile"][0]["dtype"] == "Float64"
    assert body["type_profile"][0]["nulls"] == 1

    persisted = client.get("/v1/session/dataset/validate").json()["type_profile"]
    assert persisted[0]["dtype"] == "Float64"
    assert persisted[0]["nulls"] == 1

    validation = client.get("/v1/session/dataset/validate").json()
    assert validation["rules_source"] == "session"
    assert validation["type_validation_mode"] == "schema"
    assert validation["checks"]["data_types"]["status"] == "done"
    assert validation["type_profile"][0]["expected_type"] == "float"
    assert validation["type_profile"][0]["validation_status"] == "matched"


def test_missing_dataset_returns_404():
    response = client.post("/v1/session/dataset/convert-types", json=_payload(apply=False))
    assert response.status_code == 404
