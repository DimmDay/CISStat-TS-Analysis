from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.modeling_tuning import oof_signature
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


def _backtest_and_diagnose(client: TestClient, *model_ids: str) -> None:
    for model_id in model_ids:
        backtest = client.post("/v1/session/modeling/backtest", json={"model_id": model_id})
        assert backtest.status_code == 200, backtest.text
        diagnostics = client.post(
            "/v1/session/modeling/diagnostics", json={"model_id": model_id},
        )
        assert diagnostics.status_code == 200, diagnostics.text


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


def test_baseline_bootstrap_atomically_populates_comparable_cohort(client: TestClient):
    _prepare(client)
    candidates = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "sliding", "horizon": 2, "n_splits": 2, "gap": 1, "train_window": 40},
    )
    assert candidates.status_code == 200, candidates.text

    response = client.post("/v1/session/modeling/baselines")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success"
    assert "naive" in body["backtests"]
    assert body["cohort_id"]
    assert {
        item["cohort_id"] for item in body["backtests"].values()
    } == {body["cohort_id"]}
    assert all(item["family_id"] == "baselines" for item in body["backtests"].values())

    state = client.get("/v1/session/modeling/state").json()
    assert state["pipeline"]["baseline_estimation"] == "done"
    assert "naive" in state["artifacts"]["backtests"]

    repeated = client.post("/v1/session/modeling/baselines")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["reused"] is True
    assert repeated.json()["backtests"]["naive"]["run_id"] == body["backtests"]["naive"]["run_id"]


def test_resumable_tuning_executes_one_trial_per_step_and_promotes_best(client: TestClient):
    _prepare(client)
    candidates = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "sliding", "horizon": 2, "n_splits": 2, "gap": 1, "train_window": 40},
    )
    assert candidates.status_code == 200, candidates.text

    started = client.post(
        "/v1/session/modeling/tuning/start",
        json={"model_id": "ets", "max_trials": 2, "metric": "rmse"},
    )
    assert started.status_code == 200, started.text
    job = started.json()
    assert job["status"] == "in_progress"
    assert job["completed_trials"] == 0
    assert job["total_trials"] == 2
    assert "ets" not in client.get("/v1/session/modeling/state").json()["artifacts"]["tuning"]

    first = client.post(
        "/v1/session/modeling/tuning/step",
        json={"job_id": job["job_id"], "expected_trial_index": 0},
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "in_progress"
    assert first.json()["completed_trials"] == 1
    assert first.json()["tuning_response"] is None

    stale = client.post(
        "/v1/session/modeling/tuning/step",
        json={"job_id": job["job_id"], "expected_trial_index": 0},
    )
    assert stale.status_code == 409

    final = client.post(
        "/v1/session/modeling/tuning/step",
        json={"job_id": job["job_id"], "expected_trial_index": 1},
    )
    assert final.status_code == 200, final.text
    result = final.json()
    assert result["status"] == "completed"
    assert result["completed_trials"] == 2
    tuning = result["tuning_response"]
    assert tuning["n_trials"] == 2
    assert tuning["promoted_backtest"]["cohort_id"] == tuning["cohort_id"]
    assert tuning["promoted_backtest"]["params"] == tuning["best_params"]

    state = client.get("/v1/session/modeling/state").json()
    assert state["artifacts"]["tuning"]["ets"]["tuning_id"] == tuning["tuning_id"]
    assert state["artifacts"]["backtests"]["ets"]["run_id"] == tuning["promoted_backtest"]["run_id"]

    repeated = client.post(
        "/v1/session/modeling/tuning/step",
        json={"job_id": job["job_id"], "expected_trial_index": 2},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["tuning_response"]["tuning_id"] == tuning["tuning_id"]


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

    assert body["tuning_id"]
    assert body["parameter_signature"]
    promoted = body["promoted_backtest"]
    assert promoted["params_source"] == "tuning"
    assert promoted["params"] == body["best_params"]
    assert promoted["parameter_signature"] == body["parameter_signature"]
    assert promoted["tuning_id"] == body["tuning_id"]
    assert promoted["cohort_id"] == body["cohort_id"]

    backtest = client.post("/v1/session/modeling/backtest", json={"model_id": "ets"})
    assert backtest.status_code == 200, backtest.text
    assert backtest.json()["cohort_id"] == body["cohort_id"]


def test_diagnostics_are_bound_to_promoted_tuned_oof_lineage(client: TestClient):
    _prepare(client)
    assert client.get("/v1/session/modeling/context?horizon=2&n_splits=4").status_code == 200
    initial = client.post("/v1/session/modeling/backtest", json={"model_id": "ets"})
    assert initial.status_code == 200, initial.text
    assert initial.json()["params_source"] == "model_default"

    tuned = client.post(
        "/v1/session/modeling/tune",
        json={"model_id": "ets", "max_trials": 1, "metric": "rmse"},
    )
    assert tuned.status_code == 200, tuned.text
    tuning = tuned.json()
    state = client.get("/v1/session/modeling/state").json()
    promoted = state["artifacts"]["backtests"]["ets"]
    assert promoted["run_id"] == tuning["promoted_backtest"]["run_id"]
    assert promoted["oof_signature"] == tuning["promoted_backtest"]["oof_signature"]

    response = client.post("/v1/session/modeling/diagnostics", json={"model_id": "ets"})

    assert response.status_code == 200, response.text
    diagnostics = response.json()
    assert diagnostics["residuals_source"] == "tuned_backtest_oof"
    assert diagnostics["params_source"] == "tuning"
    assert diagnostics["params"] == tuning["best_params"]
    assert diagnostics["parameter_signature"] == tuning["parameter_signature"]
    assert diagnostics["tuning_id"] == tuning["tuning_id"]
    assert diagnostics["backtest_run_id"] == promoted["run_id"]
    assert diagnostics["residuals_signature"] == promoted["oof_signature"]
    assert {item["test"] for item in diagnostics["diagnostics"]} == {
        "ljung_box", "jarque_bera", "arch_lm", "durbin_watson",
    }


def test_diagnostics_rejects_tampered_promoted_oof_lineage(client: TestClient):
    _prepare(client)
    assert client.get("/v1/session/modeling/context?horizon=2&n_splits=4").status_code == 200
    tuned = client.post(
        "/v1/session/modeling/tune",
        json={"model_id": "ets", "max_trials": 1, "metric": "rmse"},
    )
    assert tuned.status_code == 200, tuned.text
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    session.modeling_artifacts["backtests"]["ets"]["oof_predictions"][0]["residual"] += 1
    store.save(session)

    response = client.post("/v1/session/modeling/diagnostics", json={"model_id": "ets"})

    assert response.status_code == 409
    assert "OOF lineage" in response.json()["detail"]


def test_repeated_tuning_invalidates_stale_downstream_artifacts(client: TestClient):
    _prepare(client)
    assert client.get("/v1/session/modeling/context?horizon=2&n_splits=4").status_code == 200
    for model_id in ("naive", "ets"):
        response = client.post("/v1/session/modeling/backtest", json={"model_id": model_id})
        assert response.status_code == 200, response.text
    for model_id in ("naive", "ets"):
        assert client.post(
            "/v1/session/modeling/diagnostics", json={"model_id": model_id},
        ).status_code == 200
    comparison = client.post("/v1/session/modeling/compare", json={})
    assert comparison.status_code == 200, comparison.text
    selected_id = comparison.json()["ranking"][0]["model_id"]
    evaluation = client.post(
        "/v1/session/modeling/selection/evaluate", json={"min_oof_points": 4},
    ).json()
    assert client.post(
        "/v1/session/modeling/select",
        json={
            "model_id": selected_id,
            "selection_analysis_id": evaluation["selection_analysis_id"],
            "selection_signature": evaluation["selection_signature"],
            "acknowledge_baseline_risk": True,
            "acknowledge_selection_bias": True,
        },
    ).status_code == 200
    assert client.post("/v1/session/modeling/card", json={}).status_code == 200

    tuned = client.post(
        "/v1/session/modeling/tune",
        json={"model_id": "ets", "max_trials": 1},
    )

    assert tuned.status_code == 200, tuned.text
    state = client.get("/v1/session/modeling/state").json()
    artifacts = state["artifacts"]
    assert "ets" not in artifacts["diagnostics"]
    assert "comparison" not in artifacts
    assert "selection" not in artifacts
    assert artifacts["model_cards"] == {}
    assert state["pipeline"]["diagnostics"] == "in_progress"
    assert state["pipeline"]["comparison"] == "pending"
    assert state["pipeline"]["selection"] == "pending"
    assert state["pipeline"]["model_card"] == "pending"


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
    assert response.json()["params_source"] == "model_default"
    assert response.json()["parameter_signature"] == backtest.json()["parameter_signature"]
    assert response.json()["residuals_signature"] == backtest.json()["oof_signature"]


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
        diagnostics = client.post(
            "/v1/session/modeling/diagnostics", json={"model_id": model_id},
        )
        assert diagnostics.status_code == 200, diagnostics.text

    comparison = client.post("/v1/session/modeling/compare", json={})
    assert comparison.status_code == 200, comparison.text
    ranking = comparison.json()["ranking"]
    assert len(ranking) == 2
    assert [item["rank"] for item in ranking] == [1, 2]
    assert all(0 <= item["weighted_score"] <= 1 for item in ranking)

    evaluated = client.post(
        "/v1/session/modeling/selection/evaluate",
        json={"primary_metric": "rmse", "min_oof_points": 4},
    )
    assert evaluated.status_code == 200, evaluated.text
    evaluation = evaluated.json()
    assert evaluation["selection_signature"]
    assert evaluation["comparison_signature"] == comparison.json()["comparison_signature"]
    assert evaluation["evaluation_contract"]["estimate_status"] == "selection_oof_reused"
    assert evaluation["best_baseline"]["model_id"] in {"naive", "drift"}
    assert evaluation["recommended_candidate"]["kind"] in {"single", "ensemble"}

    selected_id = ranking[0]["model_id"]
    unacknowledged = client.post(
        "/v1/session/modeling/select",
        json={
            "model_id": selected_id,
            "selection_analysis_id": evaluation["selection_analysis_id"],
            "selection_signature": evaluation["selection_signature"],
            "acknowledge_baseline_risk": True,
        },
    )
    assert unacknowledged.status_code == 409
    assert "независим" in unacknowledged.json()["detail"].lower()
    selected = client.post(
        "/v1/session/modeling/select",
        json={
            "model_id": selected_id,
            "selection_analysis_id": evaluation["selection_analysis_id"],
            "selection_signature": evaluation["selection_signature"],
            "acknowledge_baseline_risk": True,
            "acknowledge_selection_bias": True,
        },
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["selected_model_id"] == selected_id
    assert selected.json()["comparison_signature"] == comparison.json()["comparison_signature"]
    assert selected.json()["selection_signature"] == evaluation["selection_signature"]
    assert selected.json()["independent_holdout"] is False

    created = client.post("/v1/session/modeling/card", json={})
    assert created.status_code == 200, created.text
    card = created.json()["card"]
    card_id = created.json()["card_id"]
    assert card["model_info"]["model_id"] == selected_id
    assert card["data_summary"]["source_checkpoint"]
    assert card["performance"]["backtest_metrics"]
    ranked = next(
        item for item in comparison.json()["ranking"] if item["model_id"] == selected_id
    )
    assert card["model_info"]["applicability_level"] == ranked["applicability_level"]
    assert card["training"]["preprocessing"]["fit_policy"] == "none"
    assert card["traceability"]["total_sources"] == 30
    assert card["traceability"]["comparison_signature"] == comparison.json()["comparison_signature"]
    assert card["traceability"]["diagnostics_signature"]
    assert card["traceability"]["selection_signature"] == evaluation["selection_signature"]
    assert any("независим" in item.lower() for item in card["limitations"])

    downloaded = client.get(f"/v1/session/modeling/card/{card_id}")
    assert downloaded.status_code == 200
    assert downloaded.json()["card"] == card

    state = client.get("/v1/session/modeling/state").json()
    assert state["pipeline"]["comparison"] == "done"
    assert state["pipeline"]["selection"] == "done"
    assert state["pipeline"]["model_card"] == "done"


def test_comparison_requires_current_diagnostics_for_every_backtest(client: TestClient):
    _prepare(client)
    assert client.get("/v1/session/modeling/context?horizon=3&n_splits=3").status_code == 200
    for model_id in ("naive", "drift"):
        response = client.post("/v1/session/modeling/backtest", json={"model_id": model_id})
        assert response.status_code == 200, response.text

    missing_all = client.post("/v1/session/modeling/compare", json={})
    assert missing_all.status_code == 409
    assert set(missing_all.json()["detail"]["missing_diagnostics"]) == {"naive", "drift"}

    assert client.post(
        "/v1/session/modeling/diagnostics", json={"model_id": "naive"},
    ).status_code == 200
    missing_one = client.post("/v1/session/modeling/compare", json={})
    assert missing_one.status_code == 409
    assert missing_one.json()["detail"]["missing_diagnostics"] == ["drift"]

    assert client.post(
        "/v1/session/modeling/diagnostics", json={"model_id": "drift"},
    ).status_code == 200
    assert client.post("/v1/session/modeling/compare", json={}).status_code == 200


def test_comparison_rejects_duplicate_unknown_and_baselineless_pool(client: TestClient):
    _prepare(client)
    assert client.get("/v1/session/modeling/context?horizon=2&n_splits=2").status_code == 200
    _backtest_and_diagnose(client, "naive", "drift")

    duplicate = client.post(
        "/v1/session/modeling/compare", json={"model_ids": ["naive", "naive"]},
    )
    assert duplicate.status_code == 422
    assert "дублик" in duplicate.json()["detail"].lower()

    unknown = client.post(
        "/v1/session/modeling/compare", json={"model_ids": ["naive", "missing"]},
    )
    assert unknown.status_code == 409
    assert unknown.json()["detail"]["missing_backtests"] == ["missing"]

    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    for model_id in ("naive", "drift"):
        session.modeling_artifacts["backtests"][model_id]["family_id"] = "not_baseline"
    store.save(session)
    no_baseline = client.post("/v1/session/modeling/compare", json={})
    assert no_baseline.status_code == 409
    assert "baseline" in no_baseline.json()["detail"].lower()


def test_comparison_has_reproducible_lineage_stability_and_error_correlation(client: TestClient):
    _prepare(client)
    assert client.get("/v1/session/modeling/context?horizon=3&n_splits=3").status_code == 200
    _backtest_and_diagnose(client, "naive", "drift")

    first = client.post(
        "/v1/session/modeling/compare", json={"model_ids": ["drift", "naive"]},
    )
    second = client.post(
        "/v1/session/modeling/compare", json={"model_ids": ["naive", "drift"]},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    body = first.json()
    assert len(body["comparison_signature"]) == 64
    assert body["comparison_signature"] == second.json()["comparison_signature"]
    assert body["comparison_id"] != second.json()["comparison_id"]
    assert body["ranking_policy"] == "forecast_metrics_only_diagnostics_separate"
    assert body["diagnostics_policy"] == "current_oof_report_required_not_scored"
    assert [item["model_id"] for item in body["ranking"]] == [
        item["model_id"] for item in second.json()["ranking"]
    ]
    assert sum(body["metric_weights"].values()) == pytest.approx(1.0, abs=1e-5)
    for item in body["ranking"]:
        assert item["backtest_run_id"]
        assert item["applicability_level"] in {
            "RECOMMENDED", "CONDITIONALLY_APPLICABLE", "NOT_RECOMMENDED", "NOT_APPLICABLE",
        }
        assert set(item["normalized_metrics"]) == set(body["metric_weights"])
        assert item["diagnostics"]["diagnostics_signature"]
        assert sum(len(item["diagnostics"][key]) for key in (
            "passed", "warnings", "failed", "not_applicable",
        )) == 4
        assert item["fold_stability"]["metric"] == "rmse"
        assert len(item["fold_stability"]["fold_values"]) == 3
        assert len(item["fold_stability"]["fold_ranks"]) == 3
        assert 0 <= item["fold_stability"]["top1_rate"] <= 1
    correlations = body["error_correlation"]
    assert correlations["model_ids"] == sorted(["naive", "drift"])
    assert correlations["n_points"] == 9
    assert len(correlations["values"]) == 2
    assert correlations["values"][0][1] == correlations["values"][1][0]


def test_comparison_rejects_individually_signed_but_misaligned_oof(client: TestClient):
    _prepare(client)
    assert client.get("/v1/session/modeling/context?horizon=3&n_splits=3").status_code == 200
    _backtest_and_diagnose(client, "naive", "drift")
    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    drift = session.modeling_artifacts["backtests"]["drift"]
    drift["oof_predictions"][0]["index"] += 1000
    drift["oof_signature"] = oof_signature(drift["oof_predictions"])
    session.modeling_artifacts["diagnostics"].pop("drift")
    store.save(session)
    assert client.post(
        "/v1/session/modeling/diagnostics", json={"model_id": "drift"},
    ).status_code == 200

    response = client.post("/v1/session/modeling/compare", json={})

    assert response.status_code == 409
    assert "OOF" in response.json()["detail"]


def test_rerun_diagnostics_invalidates_comparison_selection_and_cards(client: TestClient):
    _prepare(client)
    assert client.get("/v1/session/modeling/context?horizon=3&n_splits=3").status_code == 200
    _backtest_and_diagnose(client, "naive", "drift")
    comparison = client.post("/v1/session/modeling/compare", json={})
    assert comparison.status_code == 200, comparison.text
    selected_id = comparison.json()["ranking"][0]["model_id"]
    evaluation = client.post(
        "/v1/session/modeling/selection/evaluate", json={"min_oof_points": 4},
    ).json()
    assert client.post(
        "/v1/session/modeling/select",
        json={
            "model_id": selected_id,
            "selection_analysis_id": evaluation["selection_analysis_id"],
            "selection_signature": evaluation["selection_signature"],
            "acknowledge_baseline_risk": True,
            "acknowledge_selection_bias": True,
        },
    ).status_code == 200
    assert client.post("/v1/session/modeling/card", json={}).status_code == 200

    rerun = client.post(
        "/v1/session/modeling/diagnostics",
        json={"model_id": "naive", "alpha": 0.1},
    )

    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["diagnostics_signature"]
    state = client.get("/v1/session/modeling/state").json()
    assert "comparison" not in state["artifacts"]
    assert "selection" not in state["artifacts"]
    assert state["artifacts"]["model_cards"] == {}
    assert state["pipeline"]["comparison"] == "in_progress"
    assert state["pipeline"]["selection"] == "pending"
    assert state["pipeline"]["model_card"] == "pending"


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
