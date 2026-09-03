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


def test_context_reuses_the_last_eda_validation_plan_without_silent_defaults(client: TestClient):
    _prepare(client)
    eda = client.get(
        "/v1/session/dataset/eda-validation-strategy",
        params={
            "column": "value", "strategy": "sliding", "horizon": 6,
            "n_splits": 3, "gap": 2, "train_window": 40,
        },
    )
    assert eda.status_code == 200, eda.text

    response = client.get("/v1/session/modeling/context")

    assert response.status_code == 200, response.text
    contract = response.json()["validation_strategy"]
    assert contract["strategy"] == "sliding"
    assert contract["horizon"] == 6
    assert contract["gap"] == 2
    assert contract["train_window"] == 40
    assert contract["folds"] == eda.json()["folds"]
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    restored = session_from_dict(session_to_dict(get_session_store().get(session_id)))
    assert restored.eda_validation_strategy["strategy"] == "sliding"


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
    body = response.json()
    assert body["strategy"] == "expanding"
    assert body["horizon"] == 6
    assert body["n_folds"] == 3
    assert len(body["folds"]) == 3
    assert all(fold["n_test"] == 6 for fold in body["folds"])
    assert body["n_test"] == 18
    assert len(body["oof_predictions"]) == 18
    assert body["cohort_id"]


def test_candidates_preserve_sliding_eda_contract_for_backtest(client: TestClient):
    _prepare(client)

    candidates = client.post(
        "/v1/session/modeling/candidates",
        json={
            "strategy": "sliding", "horizon": 6, "n_splits": 3,
            "gap": 2, "train_window": 40,
        },
    )
    assert candidates.status_code == 200, candidates.text

    response = client.post("/v1/session/modeling/backtest", json={"model_id": "naive"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["strategy"] == "sliding"
    assert body["gap"] == 2
    assert body["n_folds"] == 3
    assert all(fold["n_train"] == 40 for fold in body["folds"])
    assert all(fold["test_start"] - fold["train_end"] - 1 == 2 for fold in body["folds"])


def test_tuning_reuses_exact_sliding_eda_plan_and_cohort(client: TestClient):
    _prepare(client)
    candidates = client.post(
        "/v1/session/modeling/candidates",
        json={
            "strategy": "sliding", "horizon": 2, "n_splits": 2,
            "gap": 1, "train_window": 40,
        },
    )
    assert candidates.status_code == 200, candidates.text

    tuned = client.post(
        "/v1/session/modeling/tune",
        json={"model_id": "ets", "max_trials": 1, "metric": "rmse"},
    )

    assert tuned.status_code == 200, tuned.text
    body = tuned.json()
    assert body["strategy"] == "sliding"
    assert body["cohort_id"]
    assert body["cv_config"] == {
        "n_splits": 2, "test_size": 2, "min_train_size": 40,
        "step": 2, "gap": 1,
    }
    assert [(fold["train_start"], fold["train_end"]) for fold in body["folds"]] == [
        (51, 90), (53, 92),
    ]
    assert all(trial["n_folds"] == 2 for trial in body["trials"])

    backtest = client.post("/v1/session/modeling/backtest", json={"model_id": "ets"})
    assert backtest.status_code == 200, backtest.text
    assert backtest.json()["cohort_id"] == body["cohort_id"]


def test_session_tuning_rejects_a_second_legacy_cv_contract(client: TestClient):
    _prepare(client)
    assert client.get("/v1/session/modeling/context?horizon=2&n_splits=2").status_code == 200

    response = client.post(
        "/v1/session/modeling/tune",
        json={"model_id": "ets", "cv": {"n_splits": 1, "test_size": 1}},
    )

    assert response.status_code == 422
    assert "BacktestPlan" in response.json()["detail"]


def test_diagnostics_reuses_out_of_fold_residuals_from_backtest(client: TestClient):
    _prepare(client)
    assert client.get("/v1/session/modeling/context?horizon=3&n_splits=3").status_code == 200
    backtest = client.post("/v1/session/modeling/backtest", json={"model_id": "naive"})
    assert backtest.status_code == 200, backtest.text

    response = client.post("/v1/session/modeling/diagnostics", json={"model_id": "naive"})

    assert response.status_code == 200, response.text
    assert response.json()["residuals_source"] == "backtest_oof"
    assert response.json()["residuals_count"] == len(backtest.json()["oof_predictions"])


def test_backtest_blocks_target_transform_fitted_on_full_history(client: TestClient):
    _prepare(client)
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    session.preprocessing_transformations["value"] = {
        "method": "box_cox", "lambda_value": 0.2, "fitted_on_n": 96,
    }
    store.save(session)

    response = client.post("/v1/session/modeling/backtest", json={"model_id": "naive"})

    assert response.status_code == 422
    assert "train fold" in response.json()["detail"]


def test_session_backtest_refits_and_inverts_saved_power_transform_per_fold(client: TestClient):
    uploaded = client.post(
        "/v1/internal/upload",
        files={"file": ("series.csv", io.BytesIO(_csv().encode()), "text/csv")},
    )
    assert uploaded.status_code == 200, uploaded.text
    transformed = client.post(
        "/v1/session/dataset/preprocessing/variance-transformations",
        json={
            "column": "value", "method": "box_cox",
            "lambda_value": None, "apply": True,
        },
    )
    assert transformed.status_code == 200, transformed.text
    assert client.post(
        "/v1/session/target-column", json={"column": "value_box_cox"},
    ).status_code == 200
    assert client.post("/v1/session/date-column", json={"column": "date"}).status_code == 200
    assert client.post("/v1/session/dataset/passport/start").status_code == 200
    assert client.post("/v1/session/dataset/passport/modeling_entry").status_code == 200
    assert client.get("/v1/session/modeling/context?horizon=2&n_splits=2").status_code == 200

    response = client.post("/v1/session/modeling/backtest", json={"model_id": "naive"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["preprocessing"]["fit_policy"] == "per_train_fold"
    assert body["preprocessing"]["source_column"] == "value"
    assert body["preprocessing"]["evaluation_scale"] == "value"
    original = pd.read_csv(io.StringIO(_csv()))["value"].to_list()
    assert [point["actual"] for point in body["oof_predictions"]] == pytest.approx(original[-4:])
    assert "train каждого EDA fold" in body["warnings"][0]


def test_backtests_compare_select_and_model_card_are_persisted(client: TestClient):
    _prepare(client)
    for model_id in ("naive", "drift"):
        response = client.post(
            "/v1/session/modeling/backtest",
            json={"model_id": model_id},
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
    assert card["training"]["preprocessing"]["fit_policy"] == "none"
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
        json={"model_id": "naive"},
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
