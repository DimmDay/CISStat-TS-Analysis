from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
    session_from_dict,
    session_to_dict,
)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_session_store_for_testing()
    yield
    reset_session_store_for_testing()


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _csv(n: int = 96) -> str:
    t = np.arange(n, dtype=float)
    frame = pd.DataFrame({
        "date": pd.date_range("2018-01-01", periods=n, freq="MS").astype(str),
        "value": 100 + 0.4 * t + 7 * np.sin(2 * np.pi * t / 12),
        "driver": 30 + 0.2 * t,
    })
    return frame.to_csv(index=False)


def _prepare(client: TestClient) -> None:
    uploaded = client.post(
        "/v1/internal/upload",
        files={"file": ("series.csv", io.BytesIO(_csv().encode()), "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert client.post("/v1/session/target-column", json={"column": "value"}).status_code == 200
    assert client.post("/v1/session/date-column", json={"column": "date"}).status_code == 200
    assert client.post("/v1/session/dataset/passport/start").status_code == 200
    assert client.post("/v1/session/dataset/passport/modeling_entry").status_code == 200


def test_context_requires_confirmed_modeling_entry(client: TestClient):
    uploaded = client.post(
        "/v1/internal/upload",
        files={"file": ("series.csv", io.BytesIO(_csv().encode()), "text/csv")},
    )
    assert uploaded.status_code == 200
    assert client.post("/v1/session/target-column", json={"column": "value"}).status_code == 200
    assert client.post("/v1/session/date-column", json={"column": "date"}).status_code == 200

    response = client.get("/v1/session/modeling/context")

    assert response.status_code == 409
    assert "modeling_entry" in response.json()["detail"]


def test_context_is_derived_from_real_handoff_and_covers_30_sources(client: TestClient):
    _prepare(client)

    response = client.get("/v1/session/modeling/context?horizon=6&n_splits=3")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ready"] is True
    assert body["data_source"] == "session"
    assert body["profile"]["n_observations"] == 96
    assert body["profile"]["frequency"] in {"M", "MS", "ME"}
    assert body["checkpoint"]["stage"] == "modeling_entry"
    assert body["traceability"]["summary"]["total"] == 30
    assert {item["group"] for item in body["traceability"]["nodes"]} == {
        "validation", "preprocessing", "eda",
    }
    assert "naive" in body["runnable_shortlist"]
    assert body["validation_strategy"]["horizon"] == 6
    assert body["validation_strategy"]["n_splits"] == 3


def test_workflow_rejects_catalog_only_model_instead_of_fabricating_metrics(client: TestClient):
    _prepare(client)

    response = client.post(
        "/v1/session/modeling/backtest",
        json={"model_id": "prophet", "train_ratio": 0.8},
    )

    assert response.status_code == 422
    assert "production" in response.json()["detail"].lower()


def test_backtest_defaults_to_the_horizon_confirmed_by_validation_strategy(client: TestClient):
    _prepare(client)
    context = client.get("/v1/session/modeling/context?horizon=6&n_splits=3")
    assert context.status_code == 200

    response = client.post("/v1/session/modeling/backtest", json={"model_id": "naive"})

    assert response.status_code == 200, response.text
    assert response.json()["n_test"] == 6
    assert response.json()["n_train"] == 90


def test_backtests_compare_select_and_model_card_are_persisted(client: TestClient):
    _prepare(client)
    for model_id in ("naive", "drift"):
        response = client.post(
            "/v1/session/modeling/backtest",
            json={"model_id": model_id, "train_ratio": 0.8},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data_source"] == "session"

    comparison = client.post("/v1/session/modeling/compare", json={})
    assert comparison.status_code == 200, comparison.text
    ranking = comparison.json()["ranking"]
    assert len(ranking) == 2
    assert [item["rank"] for item in ranking] == [1, 2]
    assert all(0 <= item["weighted_score"] <= 1 for item in ranking)

    selected_id = ranking[0]["model_id"]
    selected = client.post(
        "/v1/session/modeling/select",
        json={"model_id": selected_id, "acknowledge_baseline_risk": True},
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["selected_model_id"] == selected_id

    created = client.post("/v1/session/modeling/card", json={})
    assert created.status_code == 200, created.text
    card = created.json()["card"]
    card_id = created.json()["card_id"]
    assert card["model_info"]["model_id"] == selected_id
    assert card["data_summary"]["source_checkpoint"]
    assert card["performance"]["backtest_metrics"]
    assert card["traceability"]["total_sources"] == 30

    downloaded = client.get(f"/v1/session/modeling/card/{card_id}")
    assert downloaded.status_code == 200
    assert downloaded.json()["card"] == card

    state = client.get("/v1/session/modeling/state").json()
    assert state["pipeline"]["comparison"] == "done"
    assert state["pipeline"]["selection"] == "done"
    assert state["pipeline"]["model_card"] == "done"


def test_modeling_state_roundtrips_and_is_invalidated_by_target_change(client: TestClient):
    _prepare(client)
    response = client.post(
        "/v1/session/modeling/backtest",
        json={"model_id": "naive", "train_ratio": 0.8},
    )
    assert response.status_code == 200

    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    session = get_session_store().get(session_id)
    restored = session_from_dict(session_to_dict(session))
    assert restored.modeling_pipeline["backtest"] == "done"
    assert "naive" in restored.modeling_artifacts["backtests"]

    changed = client.post("/v1/session/target-column", json={"column": "driver"})
    assert changed.status_code == 200
    session = get_session_store().get(session_id)
    assert session.modeling_artifacts == {}
    assert all(status == "pending" for status in session.modeling_pipeline.values())
