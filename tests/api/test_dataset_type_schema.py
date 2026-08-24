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
    response = client.post("/v1/internal/upload", files={"file": ("schema.csv", buf, "text/csv")})
    assert response.status_code == 200, response.text


def _schema_payload() -> dict:
    return {"columns": [{"column": "Amount", "target_type": "float"}]}


def test_saved_type_schema_is_used_by_subsequent_validation():
    _upload_df(pd.DataFrame({"Amount": ["10.5", "bad", "30"]}))

    saved = client.put("/v1/session/dataset/type-schema", json=_schema_payload())
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"saved": True, **_schema_payload()}

    body = client.get("/v1/session/dataset/validate").json()
    assert body["rules_source"] == "session"
    assert body["type_validation_mode"] == "schema"
    assert body["checks"]["data_types"]["status"] == "warning"
    assert body["checks"]["data_types"]["count"] > 0
    assert body["type_profile"][0]["expected_type"] == "float"
    assert body["type_profile"][0]["validation_status"] == "mismatch"
    assert body["type_profile"][0]["violations"] > 0


def test_matching_saved_schema_returns_done():
    _upload_df(pd.DataFrame({"Amount": [10.5, 20.0, 30.0]}))
    assert client.put("/v1/session/dataset/type-schema", json=_schema_payload()).status_code == 200

    body = client.get("/v1/session/dataset/validate").json()
    assert body["checks"]["data_types"]["status"] == "done"
    assert body["checks"]["data_types"]["count"] == 0
    assert body["type_profile"][0]["validation_status"] == "matched"


def test_reupload_clears_saved_type_schema():
    _upload_df(pd.DataFrame({"Amount": [10.5, 20.0]}))
    assert client.put("/v1/session/dataset/type-schema", json=_schema_payload()).status_code == 200

    _upload_df(pd.DataFrame({"Amount": [1.0, 2.0]}))
    body = client.get("/v1/session/dataset/validate").json()
    assert body["rules_source"] == "auto"
    assert body["type_validation_mode"] == "profile"
    assert body["checks"]["data_types"]["status"] == "pending"


def test_type_schema_rejects_unknown_column_and_missing_dataset():
    missing = client.put("/v1/session/dataset/type-schema", json=_schema_payload())
    assert missing.status_code == 404

    _upload_df(pd.DataFrame({"Other": [1, 2]}))
    unknown = client.put("/v1/session/dataset/type-schema", json=_schema_payload())
    assert unknown.status_code == 422
