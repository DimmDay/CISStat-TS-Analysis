from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api import session_store as session_store_module
from apps.api.main import app
from apps.api.modeling_tuning import oof_signature
from apps.api.session_store import (
    RedisSessionStore,
    SESSION_COOKIE_NAME,
    SessionConflictError,
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
        json={"model_id": "tbats", "train_ratio": 0.8},
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


def test_prophet_full_session_backtest_and_diagnostics_use_real_calendar_dates(client: TestClient):
    """Task 124 -- Prophet needs real fold-local dates end-to-end: this is the
    one place upstream (prepare_modeling_target) actually supplies them,
    unlike the synthetic-index fixtures used by the other 8 production models.
    """
    _prepare(client)

    backtest = client.post("/v1/session/modeling/backtest", json={"model_id": "prophet"})
    assert backtest.status_code == 200, backtest.text
    body = backtest.json()
    assert body["cohort_id"]
    assert len(body["oof_predictions"]) == body["n_test"]

    diagnostics = client.post("/v1/session/modeling/diagnostics", json={"model_id": "prophet"})
    assert diagnostics.status_code == 200, diagnostics.text


def test_baseline_bootstrap_atomically_populates_comparable_cohort(client: TestClient):
    _prepare(client)
    candidates = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "sliding", "horizon": 2, "n_splits": 2, "gap": 1, "train_window": 40},
    )
    assert candidates.status_code == 200, candidates.text
    runnable = {
        item["model_id"] for item in candidates.json()["candidates"]
        if "backtest" in item["available_actions"]
    }

    response = client.post("/v1/session/modeling/baselines")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "success"
    assert set(body["backtests"]) == {
        "naive", "seasonal_naive", "drift", "mean",
    }
    assert body["cohort_id"]
    assert {
        item["cohort_id"] for item in body["backtests"].values()
    } == {body["cohort_id"]}
    assert all(item["family_id"] == "baselines" for item in body["backtests"].values())

    state = client.get("/v1/session/modeling/state").json()
    assert state["pipeline"]["baseline_estimation"] == "done"
    assert state["pipeline"]["backtest"] == "in_progress"
    assert state["artifacts"]["execution_scope"]["pending_backtest_model_ids"] == sorted(
        runnable - {"naive", "seasonal_naive", "drift", "mean"},
    )
    assert "naive" in state["artifacts"]["backtests"]

    repeated = client.post("/v1/session/modeling/baselines")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["reused"] is True
    assert repeated.json()["backtests"]["naive"]["run_id"] == body["backtests"]["naive"]["run_id"]


def test_comparison_requires_complete_scope_or_explicit_backtest_exclusions(client: TestClient):
    _prepare(client)
    candidates = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 2, "n_splits": 2},
    )
    assert candidates.status_code == 200, candidates.text
    baselines = client.post("/v1/session/modeling/baselines")
    assert baselines.status_code == 200, baselines.text
    state = client.get("/v1/session/modeling/state").json()
    pending = state["artifacts"]["execution_scope"]["pending_backtest_model_ids"]
    assert pending

    incomplete = client.post("/v1/session/modeling/compare", json={})
    assert incomplete.status_code == 409
    assert incomplete.json()["detail"]["pending_backtests"] == pending

    for model_id in pending:
        excluded = client.post(
            "/v1/session/modeling/backtest/exclude",
            json={
                "model_id": model_id,
                "decision": "exclude",
                "reason": "Осознанно исключена из текущего comparison",
                "acknowledge": True,
            },
        )
        assert excluded.status_code == 200, excluded.text

    ready = client.get("/v1/session/modeling/state").json()
    assert ready["pipeline"]["backtest"] == "done"
    assert ready["artifacts"]["execution_scope"]["pending_backtest_model_ids"] == []
    compared = client.post("/v1/session/modeling/compare", json={})
    assert compared.status_code == 200, compared.text
    assert sorted(compared.json()["execution_scope"]["backtest_exclusions"]) == sorted(pending)
    assert compared.json()["execution_scope"]["capability_contract_version"] == (
        "model-capabilities-v1"
    )


def test_tuning_stage_requires_tune_or_explicit_skip_for_tunable_models(client: TestClient):
    _prepare(client)
    candidates = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 2, "n_splits": 2},
    )
    assert candidates.status_code == 200, candidates.text
    assert client.post("/v1/session/modeling/baselines").status_code == 200
    assert client.post("/v1/session/modeling/backtest", json={"model_id": "ets"}).status_code == 200

    scope = client.get("/v1/session/modeling/state").json()["artifacts"]["execution_scope"]
    for model_id in scope["pending_backtest_model_ids"]:
        response = client.post(
            "/v1/session/modeling/backtest/exclude",
            json={"model_id": model_id, "decision": "exclude", "reason": "Не входит в проверку", "acknowledge": True},
        )
        assert response.status_code == 200, response.text

    before = client.get("/v1/session/modeling/state").json()
    assert before["pipeline"]["tuning"] == "in_progress"
    assert before["artifacts"]["execution_scope"]["pending_tuning_model_ids"] == ["ets"]

    skipped = client.post(
        "/v1/session/modeling/tuning/skip",
        json={"model_id": "ets", "reason": "Оставить параметры по умолчанию", "acknowledge": True},
    )
    assert skipped.status_code == 200, skipped.text
    after = client.get("/v1/session/modeling/state").json()
    assert after["pipeline"]["tuning"] == "done"
    assert after["artifacts"]["execution_scope"]["pending_tuning_model_ids"] == []


def test_one_defaults_decision_atomically_closes_the_complete_tuning_scope(client: TestClient):
    """Exact UI regression: one global defaults action must cover every pending model."""
    _prepare(client)
    candidates = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 2, "n_splits": 2},
    )
    assert candidates.status_code == 200, candidates.text
    assert client.post("/v1/session/modeling/baselines").status_code == 200
    for model_id in ("arima", "ets", "ets_damped"):
        backtest = client.post(
            "/v1/session/modeling/backtest", json={"model_id": model_id},
        )
        assert backtest.status_code == 200, backtest.text

    scope = client.get("/v1/session/modeling/state").json()["artifacts"]["execution_scope"]
    for model_id in scope["pending_backtest_model_ids"]:
        excluded = client.post(
            "/v1/session/modeling/backtest/exclude",
            json={
                "model_id": model_id,
                "decision": "exclude",
                "reason": "Не входит в regression scope",
                "acknowledge": True,
            },
        )
        assert excluded.status_code == 200, excluded.text

    before = client.get("/v1/session/modeling/state").json()
    assert before["artifacts"]["execution_scope"]["pending_tuning_model_ids"] == [
        "arima", "ets", "ets_damped",
    ]
    expected_exclusions = sorted(
        before["artifacts"]["execution_scope"]["backtest_exclusions"],
    )

    skipped = client.post(
        "/v1/session/modeling/tuning/skip-pending",
        json={
            "reason": "Осознанно оставлены параметры моделей по умолчанию",
            "acknowledge": True,
        },
    )

    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["model_ids"] == ["arima", "ets", "ets_damped"]
    after = client.get("/v1/session/modeling/state").json()
    execution_scope = after["artifacts"]["execution_scope"]
    assert execution_scope["pending_tuning_model_ids"] == []
    assert sorted(execution_scope["tuning_skips"]) == ["arima", "ets", "ets_damped"]
    assert after["pipeline"]["tuning"] == "done"

    # Modeling refetches candidates on a fresh UI mount. That idempotent refresh
    # must not erase the already acknowledged defaults decisions.
    regenerated = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 2, "n_splits": 2},
    )
    assert regenerated.status_code == 200, regenerated.text
    after_regeneration = client.get("/v1/session/modeling/state").json()
    regenerated_scope = after_regeneration["artifacts"]["execution_scope"]
    assert regenerated_scope["pending_tuning_model_ids"] == []
    assert sorted(regenerated_scope["tuning_skips"]) == [
        "arima", "ets", "ets_damped",
    ]
    assert sorted(regenerated_scope["backtest_exclusions"]) == expected_exclusions

    repeated = client.post(
        "/v1/session/modeling/tuning/skip-pending",
        json={
            "reason": "Повтор той же подтверждённой операции",
            "acknowledge": True,
        },
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["model_ids"] == []
    assert repeated.json()["status"] == "unchanged"

    diagnostics = client.post("/v1/session/modeling/diagnostics/ensure", json={})
    assert diagnostics.status_code == 200, diagnostics.text
    comparison = client.post("/v1/session/modeling/compare", json={})
    assert comparison.status_code == 200, comparison.text


def test_redis_stale_snapshot_cannot_restore_pending_tuning_after_success(monkeypatch):
    """Exact production regression: pending ETS must not reappear after tuning."""
    fakeredis = pytest.importorskip("fakeredis")
    store = RedisSessionStore(client=fakeredis.FakeStrictRedis(), ttl_seconds=3600)
    monkeypatch.setattr(session_store_module, "_store", store)
    with TestClient(app) as redis_client:
        _prepare(redis_client)
        assert redis_client.post(
            "/v1/session/modeling/candidates",
            json={"strategy": "expanding", "horizon": 2, "n_splits": 2},
        ).status_code == 200
        assert redis_client.post("/v1/session/modeling/baselines").status_code == 200
        assert redis_client.post(
            "/v1/session/modeling/backtest", json={"model_id": "ets"},
        ).status_code == 200
        scope = redis_client.get(
            "/v1/session/modeling/state",
        ).json()["artifacts"]["execution_scope"]
        for model_id in scope["pending_backtest_model_ids"]:
            response = redis_client.post(
                "/v1/session/modeling/backtest/exclude",
                json={
                    "model_id": model_id, "decision": "exclude",
                    "reason": "Не входит в Redis regression scope", "acknowledge": True,
                },
            )
            assert response.status_code == 200, response.text

        session_id = redis_client.cookies.get(SESSION_COOKIE_NAME)
        stale_before_tuning = session_from_dict(session_to_dict(store.get(session_id)))
        assert stale_before_tuning.modeling_artifacts[
            "execution_scope"
        ]["pending_tuning_model_ids"] == ["ets"]

        started = redis_client.post(
            "/v1/session/modeling/tuning/start",
            json={"model_id": "ets", "max_trials": 1, "metric": "rmse"},
        )
        assert started.status_code == 200, started.text
        job = started.json()
        finished = redis_client.post(
            "/v1/session/modeling/tuning/step",
            json={"job_id": job["job_id"], "expected_trial_index": 0},
        )
        assert finished.status_code == 200, finished.text
        assert finished.json()["status"] == "completed"

        with pytest.raises(SessionConflictError):
            store.save(stale_before_tuning)

        state = redis_client.get("/v1/session/modeling/state").json()
        assert state["artifacts"]["execution_scope"]["pending_tuning_model_ids"] == []
        assert state["artifacts"]["execution_scope"]["completed_tuning_model_ids"] == ["ets"]
        stable_revision = store.get(session_id).storage_revision
        assert redis_client.get("/v1/session/modeling/state").status_code == 200
        assert store.get(session_id).storage_revision == stable_revision
        comparison = redis_client.post("/v1/session/modeling/compare", json={})
        assert comparison.status_code == 200, comparison.text


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


def test_universal_model_job_is_idempotent_resumable_and_compact(client: TestClient):
    _prepare(client)
    candidates = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "sliding", "horizon": 2, "n_splits": 2,
              "gap": 1, "train_window": 40},
    )
    assert candidates.status_code == 200, candidates.text
    request = {
        "operation": "tuning", "model_id": "ets", "max_trials": 2,
        "metric": "rmse", "random_state": 42,
        "idempotency_key": "ets-default-tuning",
    }

    started = client.post("/v1/session/modeling/jobs/start", json=request)
    repeated_start = client.post("/v1/session/modeling/jobs/start", json=request)

    assert started.status_code == 200, started.text
    assert repeated_start.status_code == 200, repeated_start.text
    job = started.json()
    assert repeated_start.json()["job_id"] == job["job_id"]
    assert repeated_start.json()["idempotent_replay"] is True
    assert job["contract_version"] == "model-job-v1"
    assert job["operation"] == "tuning"
    assert job["dependency_group"] == "classical"
    assert job["deterministic_seed"] == 42
    assert job["progress"] == {
        "phase": "trials", "completed_steps": 0, "total_steps": 2,
        "percent": 0.0,
        "trials": {"completed": 0, "total": 2},
        "folds": {"completed": 0, "total": 4},
        "epochs": {"completed": 0, "total": 0},
    }

    first = client.post(
        f"/v1/session/modeling/jobs/{job['job_id']}/step",
        json={"expected_step": 0},
    )
    assert first.status_code == 200, first.text
    assert first.json()["progress"]["trials"] == {"completed": 1, "total": 2}
    assert first.json()["progress"]["folds"] == {"completed": 2, "total": 4}

    replay = client.post(
        f"/v1/session/modeling/jobs/{job['job_id']}/step",
        json={"expected_step": 0},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["progress"]["completed_steps"] == 1

    status = client.get(f"/v1/session/modeling/jobs/{job['job_id']}")
    assert status.status_code == 200, status.text
    assert status.json()["progress"]["completed_steps"] == 1

    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    stored = get_session_store().get(session_id).modeling_artifacts["model_jobs"][job["job_id"]]
    assert "trial_backtests" not in stored
    assert "fitted_model" not in stored
    assert len(stored.get("best_backtest", {}).get("oof_predictions", [])) == 4

    final = client.post(
        f"/v1/session/modeling/jobs/{job['job_id']}/step",
        json={"expected_step": 1},
    )
    assert final.status_code == 200, final.text
    assert final.json()["status"] == "completed"
    assert final.json()["result"]["promoted_backtest"]["model_id"] == "ets"


def test_universal_model_job_cancel_is_persisted_and_blocks_steps(client: TestClient):
    _prepare(client)
    assert client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 2, "n_splits": 2},
    ).status_code == 200
    started = client.post(
        "/v1/session/modeling/jobs/start",
        json={"operation": "tuning", "model_id": "ets", "max_trials": 2},
    )
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]

    cancelled = client.post(
        f"/v1/session/modeling/jobs/{job_id}/cancel",
        json={"reason": "Остановлено аналитиком"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancellation"]["reason"] == "Остановлено аналитиком"

    step = client.post(
        f"/v1/session/modeling/jobs/{job_id}/step",
        json={"expected_step": 0},
    )
    assert step.status_code == 409
    assert client.get(
        f"/v1/session/modeling/jobs/{job_id}",
    ).json()["status"] == "cancelled"


def test_universal_model_job_enforces_memory_budget(
    client: TestClient, monkeypatch,
):
    from apps.api.routers import modeling_session as modeling_session_router

    _prepare(client)
    assert client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 2, "n_splits": 2},
    ).status_code == 200
    started = client.post(
        "/v1/session/modeling/jobs/start",
        json={"operation": "tuning", "model_id": "ets", "max_trials": 1},
    )
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]
    monkeypatch.setattr(modeling_session_router, "process_memory_mb", lambda: 1_000_000.0)

    step = client.post(
        f"/v1/session/modeling/jobs/{job_id}/step",
        json={"expected_step": 0},
    )

    assert step.status_code == 422
    status = client.get(f"/v1/session/modeling/jobs/{job_id}").json()
    assert status["status"] == "failed"
    assert "memory budget" in status["error"]


def test_universal_model_job_enforces_persisted_deadline(
    client: TestClient, monkeypatch,
):
    from apps.api.routers import modeling_session as modeling_session_router

    _prepare(client)
    assert client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 2, "n_splits": 2},
    ).status_code == 200
    started = client.post(
        "/v1/session/modeling/jobs/start",
        json={"operation": "tuning", "model_id": "ets", "max_trials": 1},
    )
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]
    monkeypatch.setattr(modeling_session_router, "deadline_expired", lambda _job: True)

    step = client.post(
        f"/v1/session/modeling/jobs/{job_id}/step",
        json={"expected_step": 0},
    )

    assert step.status_code == 408
    status = client.get(f"/v1/session/modeling/jobs/{job_id}").json()
    assert status["status"] == "failed"
    assert "timeout" in status["error"]


def test_universal_model_job_concurrent_redis_step_converges_via_cas(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    import apps.api.routers.modeling_session as modeling_session_router

    fakeredis = pytest.importorskip("fakeredis")
    store = RedisSessionStore(client=fakeredis.FakeStrictRedis(), ttl_seconds=3600)
    monkeypatch.setattr(session_store_module, "_store", store)
    original_execute = modeling_session_router.execute_tuning_trial
    barrier = Barrier(2)

    def synchronized_execute(*args, **kwargs):
        result = original_execute(*args, **kwargs)
        barrier.wait(timeout=15)
        return result

    monkeypatch.setattr(
        modeling_session_router, "execute_tuning_trial", synchronized_execute,
    )
    with TestClient(app) as redis_client:
        _prepare(redis_client)
        assert redis_client.post(
            "/v1/session/modeling/candidates",
            json={"strategy": "expanding", "horizon": 2, "n_splits": 2},
        ).status_code == 200
        started = redis_client.post(
            "/v1/session/modeling/jobs/start",
            json={"operation": "tuning", "model_id": "ets", "max_trials": 1},
        )
        assert started.status_code == 200, started.text
        job_id = started.json()["job_id"]

        def run_step():
            return redis_client.post(
                f"/v1/session/modeling/jobs/{job_id}/step",
                json={"expected_step": 0},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: run_step(), range(2)))

        assert [item.status_code for item in responses] == [200, 200]
        bodies = [item.json() for item in responses]
        assert all(item["status"] == "completed" for item in bodies)
        assert any(item["idempotent_replay"] for item in bodies)
        persisted = redis_client.get(
            f"/v1/session/modeling/jobs/{job_id}",
        ).json()
        assert persisted["progress"]["completed_steps"] == 1
        assert persisted["result"]["model_id"] == "ets"


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
    assert evaluation["policy"]["baseline_tolerance_ratio"] == 1.05
    assert set(evaluation["baseline_comparisons"]) == {"naive", "drift"}
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
    assert selected.json()["best_baseline_model_id"] in {"naive", "drift"}
    assert selected.json()["baseline_tolerance_ratio"] == 1.05
    assert selected.json()["baseline_loss_ratio"] is not None

    created = client.post("/v1/session/modeling/card", json={})
    assert created.status_code == 200, created.text
    card = created.json()["card"]
    card_id = created.json()["card_id"]
    assert card["model_info"]["model_id"] == selected_id
    assert card["data_summary"]["source_checkpoint"]
    assert card["performance"]["backtest_metrics"]
    baseline_comparison = card["performance"]["baseline_comparison"]
    assert baseline_comparison["source"] == "exact_aligned_selection_oof"
    assert baseline_comparison["best_baseline_model_id"] in {"naive", "drift"}
    assert baseline_comparison["loss_ratio"] is not None
    assert baseline_comparison["tolerance_ratio"] == 1.05
    assert baseline_comparison["mase_context"]["is_same_horizon_baseline_comparison"] is False
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


def test_comparison_atomically_prepares_current_diagnostics_for_every_backtest(client: TestClient):
    _prepare(client)
    assert client.get("/v1/session/modeling/context?horizon=3&n_splits=3").status_code == 200
    for model_id in ("naive", "drift"):
        response = client.post("/v1/session/modeling/backtest", json={"model_id": model_id})
        assert response.status_code == 200, response.text

    comparison = client.post("/v1/session/modeling/compare", json={})

    assert comparison.status_code == 200, comparison.text
    state = client.get("/v1/session/modeling/state").json()
    assert set(state["artifacts"]["diagnostics"]) == {"naive", "drift"}
    for model_id in ("naive", "drift"):
        report = state["artifacts"]["diagnostics"][model_id]
        backtest = state["artifacts"]["backtests"][model_id]
        assert report["backtest_run_id"] == backtest["run_id"]
        assert report["residuals_signature"] == backtest["oof_signature"]


def test_diagnostics_ensure_prepares_the_entire_comparable_pool(client: TestClient):
    _prepare(client)
    candidates = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 3, "n_splits": 3},
    )
    assert candidates.status_code == 200, candidates.text
    baselines = client.post("/v1/session/modeling/baselines")
    assert baselines.status_code == 200, baselines.text
    theta = client.post("/v1/session/modeling/backtest", json={"model_id": "theta"})
    assert theta.status_code == 200, theta.text
    model_ids = ["theta", *baselines.json()["backtests"]]

    ensured = client.post(
        "/v1/session/modeling/diagnostics/ensure",
        json={"model_ids": model_ids},
    )

    assert ensured.status_code == 200, ensured.text
    body = ensured.json()
    assert sorted(body["model_ids"]) == sorted(model_ids)
    assert sorted(body["calculated_model_ids"]) == sorted(model_ids)
    assert body["reused_model_ids"] == []
    assert set(body["diagnostics"]) == set(model_ids)

    repeated = client.post(
        "/v1/session/modeling/diagnostics/ensure",
        json={"model_ids": model_ids},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["calculated_model_ids"] == []
    assert sorted(repeated.json()["reused_model_ids"]) == sorted(model_ids)

    scope = client.get("/v1/session/modeling/state").json()["artifacts"]["execution_scope"]
    for model_id in scope["pending_backtest_model_ids"]:
        excluded = client.post(
            "/v1/session/modeling/backtest/exclude",
            json={
                "model_id": model_id, "decision": "exclude",
                "reason": "Не входит в diagnostics regression pool", "acknowledge": True,
            },
        )
        assert excluded.status_code == 200, excluded.text

    comparison = client.post(
        "/v1/session/modeling/compare", json={"model_ids": model_ids},
    )
    assert comparison.status_code == 200, comparison.text


def test_redis_stale_snapshot_cannot_overwrite_prepared_diagnostics(
    monkeypatch,
):
    """Task 107 lost-update window is closed before diagnostics can vanish."""
    fakeredis = pytest.importorskip("fakeredis")
    store = RedisSessionStore(client=fakeredis.FakeStrictRedis(), ttl_seconds=3600)
    monkeypatch.setattr(session_store_module, "_store", store)
    with TestClient(app) as redis_client:
        _prepare(redis_client)
        assert redis_client.get(
            "/v1/session/modeling/context?horizon=3&n_splits=3",
        ).status_code == 200
        for model_id in ("naive", "drift"):
            backtest = redis_client.post(
                "/v1/session/modeling/backtest", json={"model_id": model_id},
            )
            assert backtest.status_code == 200, backtest.text

        session_id = redis_client.cookies.get(SESSION_COOKIE_NAME)
        stale_request_snapshot = store.get(session_id)
        ensured = redis_client.post(
            "/v1/session/modeling/diagnostics/ensure",
            json={"model_ids": ["naive", "drift"]},
        )
        assert ensured.status_code == 200, ensured.text

        # A request that started before ensure may finish later, but optimistic
        # revision control must reject its stale whole-document write.
        with pytest.raises(SessionConflictError):
            store.save(stale_request_snapshot)
        assert set(store.get(session_id).modeling_artifacts["diagnostics"]) == {
            "naive", "drift",
        }

        comparison = redis_client.post(
            "/v1/session/modeling/compare",
            json={"model_ids": ["naive", "drift"]},
        )
        assert comparison.status_code == 200, comparison.text
        persisted = store.get(session_id)
        assert set(persisted.modeling_artifacts["diagnostics"]) == {"naive", "drift"}
        assert persisted.modeling_artifacts["comparison"]["comparison_id"]


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
    assert body["baseline_policy"]["source"] == "exact_aligned_oof"
    assert body["baseline_policy"]["metric"] == "rmse"
    assert body["baseline_policy"]["tolerance_ratio"] == 1.05
    assert body["mase_context"]["horizon"] == 3
    assert body["mase_context"]["seasonal_period"] >= 1
    assert len(body["mase_context"]["fold_scales"]) == 3
    assert body["mase_context"]["is_same_horizon_baseline_comparison"] is False
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
        assert item["baseline_comparison"]["source"] == "exact_aligned_oof"
        assert item["baseline_comparison"]["metric"] == "rmse"
        assert item["baseline_eligible"] == item["baseline_comparison"]["eligible"]
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


def test_state_migrates_legacy_unsigned_backtests_without_discarding_valid_baseline(
    client: TestClient,
):
    _prepare(client)
    assert client.get("/v1/session/modeling/context?horizon=2&n_splits=2").status_code == 200
    baseline = client.post("/v1/session/modeling/backtest", json={"model_id": "naive"})
    assert baseline.status_code == 200, baseline.text
    ets = client.post("/v1/session/modeling/backtest", json={"model_id": "ets"})
    assert ets.status_code == 200, ets.text

    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    session.modeling_artifacts.pop("artifact_schema_version", None)
    legacy_ets = session.modeling_artifacts["backtests"]["ets"]
    for key in ("run_id", "parameter_signature", "oof_signature"):
        legacy_ets.pop(key, None)
    legacy_auto = dict(legacy_ets)
    legacy_auto["model_id"] = "arima_auto"
    legacy_auto["model_name"] = "Auto-ARIMA"
    legacy_auto["family_id"] = "arima"
    session.modeling_artifacts["backtests"]["arima_auto"] = legacy_auto
    store.save(session)

    response = client.get("/v1/session/modeling/state")

    assert response.status_code == 200, response.text
    artifacts = response.json()["artifacts"]
    assert artifacts["artifact_schema_version"] == 6
    assert "naive" in artifacts["backtests"]
    assert "ets" not in artifacts["backtests"]
    assert "arima_auto" not in artifacts["backtests"]
    assert artifacts["artifact_migration"]["invalidated_backtests"] == [
        "arima_auto", "ets",
    ]
    assert response.json()["pipeline"]["baseline_estimation"] == "done"
    assert response.json()["pipeline"]["comparison"] == "pending"

    assert client.post(
        "/v1/session/modeling/diagnostics", json={"model_id": "naive"},
    ).status_code == 200
    recalculated = client.post(
        "/v1/session/modeling/backtest", json={"model_id": "ets"},
    )
    assert recalculated.status_code == 200, recalculated.text
    assert client.post(
        "/v1/session/modeling/diagnostics", json={"model_id": "ets"},
    ).status_code == 200
    comparison = client.post(
        "/v1/session/modeling/compare", json={"model_ids": ["naive", "ets"]},
    )
    assert comparison.status_code == 200, comparison.text


def test_state_v4_upgrade_preserves_valid_runs_and_invalidates_old_scope_verdict(
    client: TestClient,
):
    _prepare(client)
    assert client.get("/v1/session/modeling/context?horizon=3&n_splits=3").status_code == 200
    _backtest_and_diagnose(client, "naive", "drift")
    comparison = client.post("/v1/session/modeling/compare", json={})
    assert comparison.status_code == 200, comparison.text

    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    session.modeling_artifacts["artifact_schema_version"] = 4
    session.modeling_artifacts["selection_analysis"] = {"legacy": True}
    session.modeling_artifacts["selection"] = {"legacy": True}
    session.modeling_artifacts["model_cards"] = {"legacy": {}}
    store.save(session)

    state = client.get("/v1/session/modeling/state")

    assert state.status_code == 200, state.text
    artifacts = state.json()["artifacts"]
    assert artifacts["artifact_schema_version"] == 6
    assert set(artifacts["backtests"]) == {"naive", "drift"}
    assert set(artifacts["diagnostics"]) == {"naive", "drift"}
    assert "comparison" not in artifacts
    assert "selection_analysis" not in artifacts
    assert "selection" not in artifacts
    assert artifacts["model_cards"] == {}
    assert artifacts["artifact_migration"]["reason"] == "model_capability_scope_contract_upgrade"
    assert state.json()["pipeline"]["comparison"] == "pending"


def test_state_v5_upgrade_invalidates_runs_without_v2_lineage(client: TestClient):
    _prepare(client)
    assert client.get("/v1/session/modeling/context?horizon=3&n_splits=3").status_code == 200
    _backtest_and_diagnose(client, "naive")

    session_id = client.cookies.get(SESSION_COOKIE_NAME)
    store = get_session_store()
    session = store.get(session_id)
    session.modeling_artifacts["artifact_schema_version"] = 5
    backtest = session.modeling_artifacts["backtests"]["naive"]
    backtest.pop("objective", None)
    backtest.pop("cohort_contract", None)
    backtest["execution_contract"].pop("runtime_available", None)
    backtest["execution_contract"].pop("library_versions", None)
    store.save(session)

    state = client.get("/v1/session/modeling/state")

    assert state.status_code == 200, state.text
    artifacts = state.json()["artifacts"]
    assert artifacts["artifact_schema_version"] == 6
    assert artifacts["backtests"] == {}
    assert artifacts["diagnostics"] == {}
    assert artifacts["artifact_migration"]["invalidated_backtests"] == ["naive"]
    assert artifacts["artifact_migration"]["invalidated_diagnostics"] == ["naive"]
    assert artifacts["artifact_migration"]["reason"] == (
        "unsigned_or_stale_execution_oof_lineage"
    )
    assert state.json()["pipeline"]["backtest"] == "pending"

    candidates = client.post("/v1/session/modeling/candidates", json={})
    assert candidates.status_code == 200, candidates.text
