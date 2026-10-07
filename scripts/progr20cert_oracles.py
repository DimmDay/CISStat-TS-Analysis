# scripts/progr20cert_oracles.py
"""ORACLES of the PROGR-20-CERT auditor (own data, not colleagues' fixtures).

Certified task: PROGR-20 (commit 18e4871) -- expansion of the TRACE_ROUTES allowlist
with Modeling endpoints (spec_progress_v1.1.md §1, category A):
P0 candidates + selection/evaluate, P1 compare + diagnostics×2,
P2 skip-pair + jobs start/cancel; exceptions: validation-rules,
type-schema, jobs/{id}/step, out-of-table v1.1.

Own data (does not intersect with any fixture of colleagues):
cert20_weekly_demand_n156.csv -- WEEKLY demand series, 156 points (3 years,
2022-01-02..2024-12-29), date/sales columns; additive trend of 0.8/week,
triangular annual season with an amplitude of 30, deterministic
pseudo-noise ((i*37)%11-5)*0.6. Colleagues have: monthly monitor-150
(fixture), weekly sales-120 (PROGR-17-CERT), daily traffic-210
(PROGR-18-CERT), monthly MS-96 (PROGR-20 implementation).

Oracle groups:
  A -- footprints of own data: applicability-engine statistics on OWN
       dataset (24-model spec v1.3.1: pool 10 / catalog-only 5 /
       blocked 4; naive+ets are runnable) AND mirror of the event payload
       == to the response of OWN call.
  B -- allowlist mechanics on OWN probes: 9 rows, method-gate,
       {job_id}-template, empty segment, 8 negative probes (exclusions),
       §7 acceptance criterion (both P0), count 53.
  C -- payload shape on OWN response bodies: last-segment flattening,
       heavy arrays are cut off, missing intermediate levels are omitted.
  D -- e2e on own data: full Modeling loop in a live trace, layer 2
       mirror, "skipped"->"unchanged" skip-pending (e2e was not done by the
       implementer -- auditor addition), no-throttle, negative 4xx/405,
       panel (last_touched_at, reason is not set), §7 e2e.

Run: python -m pytest scripts/progr20cert_oracles.py -v
(from the repository root; DATABASE_URL/CISSTAT_RUNS_BACKEND are reset by the fixture).
"""
from __future__ import annotations

import io
import uuid

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)

client = TestClient(app)

DATASET_NAME = "cert20_weekly_demand_n156.csv"


@pytest.fixture(autouse=True)
def _reset_stores(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CISSTAT_RUNS_BACKEND", "memory")
    from apps.api import research_runs

    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    yield
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()


# ── own data ─────────────────────────────────────────────────────────


def _auditor_csv() -> str:
    """WEEKLY demand of 156 points: trend + annual season + deterministic noise."""
    n = 156
    idx = pd.date_range("2022-01-02", periods=n, freq="W-SUN")
    sales = []
    for i in range(n):
        season = 30.0 * (0.5 - (i % 52) / 52.0) if (i % 52) < 26 else 30.0 * ((i % 52) - 26) / 52.0
        noise = (((i * 37) % 11) - 5) * 0.6
        sales.append(200.0 + 0.8 * i + season + noise)
    frame = pd.DataFrame({"date": idx.strftime("%Y-%m-%d"), "sales": sales})
    return frame.to_csv(index=False)


def _upload() -> None:
    response = client.post(
        "/v1/internal/upload",
        files={"file": (DATASET_NAME, io.BytesIO(_auditor_csv().encode()), "text/csv")},
    )
    assert response.status_code == 200, response.text


def _modeling_ready() -> None:
    _upload()
    assert client.post("/v1/session/target-column", json={"column": "sales"}).status_code == 200
    assert client.post("/v1/session/date-column", json={"column": "date"}).status_code == 200
    assert client.post("/v1/session/dataset/passport/start").status_code == 200
    assert client.post("/v1/session/dataset/passport/modeling_entry").status_code == 200


def _session_id() -> str:
    sid = client.cookies.get(SESSION_COOKIE_NAME)
    assert sid, "no session cookie"
    return sid


def _session():
    session = get_session_store().get(_session_id())
    assert session is not None
    return session


def _events() -> list[dict]:
    return _session().pipeline_trace


def _by_type(event_type: str) -> list[dict]:
    return [e for e in _events() if e["event_type"] == event_type]


def _mirror_events(run_id: str) -> list:
    from apps.api.research_runs import get_research_run_store

    return get_research_run_store().list_events(run_id)


# ── A. footprints of own data ────────────────────────────────────────


def test_a1_applicability_statistics_are_footprint_of_my_data():
    """Applicability engine on OWN dataset: spec v1.3.1 -- catalog of 24 models,
    pool of 10 RECOMMENDED, catalog-only 5, blocked 4 (numbers are deterministic
    for a fixed spec+data -- pinned as data fingerprints); naive+ets in the pool."""
    _modeling_ready()
    response = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 4, "n_splits": 2},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    stats = body["statistics"]
    assert stats["total_models_in_spec"] == 24 == len(body["catalog"])
    assert stats["total_candidates"] == 10 == len(body["candidates"])
    assert stats["runnable_candidates"] == 10
    assert stats["catalog_only_candidates"] == 5
    assert stats["blocked_candidates"] == 4
    assert stats["by_level"] == {"RECOMMENDED": 10}
    runnable = {c["model_id"] for c in body["candidates"]}
    assert {"naive", "ets", "theta"} <= runnable
    # Semantics of the sum: pool + catalog-only + blocked -- non-recommended catalog without
    # production backtest remains outside the triple (19 < 24 is honest).
    assert stats["runnable_candidates"] + stats["catalog_only_candidates"] + stats["blocked_candidates"] == 19


def test_a2_event_payload_mirrors_my_own_response():
    """Payload of the candidates_generated event == statistics of MY OWN response
    (the event carries the fact of the result of own data, not a template)."""
    _modeling_ready()
    response = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 4, "n_splits": 2},
    )
    assert response.status_code == 200, response.text
    stats = response.json()["statistics"]
    event = _by_type("candidates_generated")[-1]
    payload = event["payload"]
    assert payload["runnable_candidates"] == stats["runnable_candidates"] == 10
    assert payload["catalog_only_candidates"] == stats["catalog_only_candidates"] == 5
    assert payload["blocked_candidates"] == stats["blocked_candidates"] == 4
    assert payload["spec_version"] == response.json()["spec_version"]
    assert "catalog" not in payload and "candidates" not in payload


# ── B. allowlist mechanics (own probes) ──────────────────────────────


_PROGR20_ROWS = (
    # (method, path, node, event_type) -- derived independently from the v1.1 §1 table
    # and by the fact of the routers/modeling_session.py endpoints.
    ("POST", "/v1/session/modeling/candidates", "candidate_generation", "candidates_generated"),
    ("POST", "/v1/session/modeling/selection/evaluate", "selection", "selection_evaluated"),
    ("POST", "/v1/session/modeling/compare", "comparison", "models_compared"),
    ("POST", "/v1/session/modeling/diagnostics", "diagnostics", "diagnostics_run"),
    ("POST", "/v1/session/modeling/diagnostics/ensure", "diagnostics", "diagnostics_run"),
    ("POST", "/v1/session/modeling/tuning/skip", "tuning", "tuning_skipped"),
    ("POST", "/v1/session/modeling/tuning/skip-pending", "tuning", "tuning_skipped"),
    ("POST", "/v1/session/modeling/jobs/start", "tuning", "tuning_job_started"),
    ("POST", "/v1/session/modeling/jobs/{job_id}/cancel", "tuning", "tuning_job_cancelled"),
)


def test_b1_all_nine_rows_resolve_with_exact_triple():
    from apps.api.trace_hook import resolve_trace_route

    for method, path, node, event_type in _PROGR20_ROWS:
        probe = path.replace("{job_id}", str(uuid.uuid4()))
        spec = resolve_trace_route(method, probe)
        assert spec is not None, path
        assert (spec.stage, spec.node_id, spec.event_type) == ("modeling", node, event_type), path


def test_b2_method_gate_is_strict():
    from apps.api.trace_hook import resolve_trace_route

    assert resolve_trace_route("GET", "/v1/session/modeling/candidates") is None
    assert resolve_trace_route("PUT", "/v1/session/modeling/compare") is None
    assert resolve_trace_route("DELETE", "/v1/session/modeling/jobs/abc/cancel") is None


def test_b3_job_id_template_semantics():
    from apps.api.trace_hook import resolve_trace_route

    matched = resolve_trace_route("POST", "/v1/session/modeling/jobs/J-123/cancel")
    assert matched is not None and matched.event_type == "tuning_job_cancelled"
    uuid_probe = resolve_trace_route(
        "POST", f"/v1/session/modeling/jobs/{uuid.uuid4()}/cancel"
    )
    assert uuid_probe is not None
    # Empty segment does not match {job_id} (the template does not degenerate).
    assert resolve_trace_route("POST", "/v1/session/modeling/jobs//cancel") is None
    # Extra segment -- another path.
    assert resolve_trace_route("POST", "/v1/session/modeling/jobs/a/b/cancel") is None


def test_b4_conscious_exclusions_and_offtable_stay_untraced():
    from apps.api.trace_hook import resolve_trace_route

    exclusions = (
        ("PUT", "/v1/session/dataset/validation-rules"),
        ("PUT", "/v1/session/dataset/type-schema"),
        ("POST", "/v1/session/modeling/jobs/any-job/step"),
        ("POST", "/v1/session/modeling/baselines"),
        ("POST", "/v1/session/modeling/backtest/exclude"),
        ("PUT", "/v1/session/modeling/feature-regressors"),
        ("POST", "/v1/session/modeling/tuning/start"),
        ("POST", "/v1/session/modeling/tuning/step"),
    )
    for method, path in exclusions:
        assert resolve_trace_route(method, path) is None, path


def test_b5_acceptance_v11_para7_both_p0_and_count_53():
    """Acceptance criterion v1.1 §7: TRACE_ROUTES includes at least both P0."""
    from apps.api.trace_hook import TRACE_ROUTES

    keys = {(s.method, s.path_template) for s in TRACE_ROUTES}
    assert ("POST", "/v1/session/modeling/candidates") in keys
    assert ("POST", "/v1/session/modeling/selection/evaluate") in keys
    assert len(TRACE_ROUTES) == 53


# ── C. payload shape on own bodies ───────────────────────────────────


def test_c1_dotted_keys_flatten_to_last_segment_only():
    from apps.api.trace_hook import TRACE_ROUTES, _extract_payload

    spec = [s for s in TRACE_ROUTES if s.path_template == "/v1/session/modeling/candidates"][0]
    body = {
        "candidates": [{"model_id": "m"}],
        "catalog": [{"model_id": "m"}, {"model_id": "n"}],
        "statistics": {"runnable_candidates": 7, "catalog_only_candidates": 5, "blocked_candidates": 4},
        "spec_version": "v1.3.1",
    }
    payload = _extract_payload(spec, body)
    # Flat keys -- under the LAST segment; full dotted keys don't leak.
    assert payload == {
        "runnable_candidates": 7,
        "catalog_only_candidates": 5,
        "blocked_candidates": 4,
        "spec_version": "v1.3.1",
    }
    assert "statistics.runnable_candidates" not in payload
    assert "statistics" not in payload


def test_c2_heavy_arrays_and_missing_levels_omitted_honestly():
    from apps.api.trace_hook import TRACE_ROUTES, _extract_payload

    selection_spec = [s for s in TRACE_ROUTES if s.path_template == "/v1/session/modeling/selection/evaluate"][0]
    heavy = {
        "selection_analysis_id": "selection-x1",
        "cohort_id": "cohort-cert20",
        "recommended_single": {"model_id": "theta", "oof": [[1.0] * 50] * 50},  # heavy
        "ensemble": {"status": "recommended", "member_ids": ["a", "b", "c"]},
        "baseline_comparisons": {"theta": {"relative_improvement": 0.12}},
    }
    payload = _extract_payload(selection_spec, heavy)
    assert payload == {
        "selection_analysis_id": "selection-x1",
        "cohort_id": "cohort-cert20",
        "model_id": "theta",
        "status": "recommended",
    }
    # Missing intermediate level -- the key is honestly omitted, no garbage.
    broken = {"recommended_single": None, "ensemble": {"status": "not_eligible"}}
    assert _extract_payload(selection_spec, broken) == {"status": "not_eligible"}

    cancel_spec = [s for s in TRACE_ROUTES if s.path_template == "/v1/session/modeling/jobs/{job_id}/cancel"][0]
    assert _extract_payload(cancel_spec, {"cancellation": "not-a-dict"}) == {}
    assert _extract_payload(cancel_spec, {}) == {}


def test_c3_jobs_start_total_steps_from_my_request():
    from apps.api.trace_hook import TRACE_ROUTES, _extract_payload

    start_spec = [s for s in TRACE_ROUTES if s.path_template == "/v1/session/modeling/jobs/start"][0]
    body = {
        "job_id": "J-cert20",
        "operation": "tuning",
        "model_id": "theta",
        "status": "in_progress",
        "progress": {"phase": "trials", "completed_steps": 0, "total_steps": 5},
    }
    payload = _extract_payload(start_spec, body)
    assert payload == {
        "operation": "tuning",
        "model_id": "theta",
        "status": "in_progress",
        "total_steps": 5,
    }


# ── D. e2e on own data ───────────────────────────────────────────────


def test_d1_full_modeling_flow_leaves_facts_in_live_trace():
    """Full loop of OWN research: P0 candidates -> backtests -> diagnostics
    (direct+ensure) -> compare -> selection/evaluate -> skip-pending
    (skipped -> unchanged) -> jobs start/cancel. Every fact -- in the trace
    with an exact (stage, node, type) and payload of own responses."""
    _modeling_ready()

    # P0: candidates (twice -- modeling facts are not throttled, D8 inside).
    first = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 4, "n_splits": 2},
    )
    assert first.status_code == 200, first.text
    # Baselines before backtests (scope setup, same as in the module's semantics).
    assert client.post("/v1/session/modeling/baselines").status_code == 200
    second = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 4, "n_splits": 2},
    )
    assert second.status_code == 200, second.text
    candidates_events = _by_type("candidates_generated")
    assert len(candidates_events) == 2, "modeling facts should not be throttled"
    run_id = _session().run_id
    assert run_id.startswith("RUN-")
    for event in candidates_events:
        assert (event["stage"], event["node_id"]) == ("modeling", "candidate_generation")
        assert event["run_id"] == run_id

    # Backtests of own pool (naive + ets).
    for model_id in ("naive", "ets"):
        backtest = client.post("/v1/session/modeling/backtest", json={"model_id": model_id})
        assert backtest.status_code == 200, backtest.text
        my_cohort = backtest.json()["cohort_id"]
        assert my_cohort, "backtest of own data should give a cohort fingerprint"

        # P1: direct diagnostics -- payload mirrors OWN response.
        diag = client.post("/v1/session/modeling/diagnostics", json={"model_id": model_id})
        assert diag.status_code == 200, diag.text
        diag_body = diag.json()
        diag_events = [
            e for e in _by_type("diagnostics_run")
            if e["payload"].get("model_id") == model_id
        ]
        assert diag_events, f"diagnostics_run of {model_id} not written"
        payload = diag_events[-1]["payload"]
        assert payload["backtest_run_id"] == diag_body["backtest_run_id"]
        assert payload["params_source"] in ("model_default", "tuning", "request")

    # P1: ensure -- re-diagnosis is honestly visible (reuse).
    ensure = client.post(
        "/v1/session/modeling/diagnostics/ensure",
        json={"model_ids": ["naive", "ets"]},
    )
    assert ensure.status_code == 200, ensure.text
    ensure_body = ensure.json()
    ensure_events = [
        e for e in _by_type("diagnostics_run") if "calculated_model_ids" in e["payload"]
    ]
    assert ensure_events, "diagnostics/ensure not written"
    ensure_payload = ensure_events[-1]["payload"]
    union = set(ensure_payload["calculated_model_ids"]) | set(ensure_payload["reused_model_ids"])
    assert {"naive", "ets"} <= union
    assert set(ensure_body["calculated_model_ids"]) | set(ensure_body["reused_model_ids"]) == union

    # P1: compare of own pool. Readiness gates honestly list pending backtests
    # AND pending tuning (409) -- closing the scope with this detail:
    # backtests -> exclusions, tuning -> explicit /tuning/skip (P2-facts of
    # "leaving defaults" happen BEFORE comparison -- legitimate analyst chronology).
    compare: object = None
    for _round in range(8):
        probe = client.post("/v1/session/modeling/compare", json={})
        if probe.status_code == 200:
            compare = probe
            break
        assert probe.status_code == 409, probe.text
        detail = probe.json()["detail"]
        for model_id in detail.get("pending_backtests", []):
            excluded = client.post(
                "/v1/session/modeling/backtest/exclude",
                json={"model_id": model_id, "decision": "exclude",
                      "reason": "Not included in the comparison", "acknowledge": True},
            )
            assert excluded.status_code == 200, excluded.text
        for model_id in detail.get("pending_tuning", []):
            skipped = client.post(
                "/v1/session/modeling/tuning/skip",
                json={"model_id": model_id, "reason": "Leave defaults before comparison",
                      "acknowledge": True},
            )
            assert skipped.status_code == 200, skipped.text
    assert compare is not None, "runnable scope did not close in 8 rounds"
    compare_body = compare.json()
    compare_event = _by_type("models_compared")[-1]
    assert (compare_event["stage"], compare_event["node_id"]) == ("modeling", "comparison")
    assert compare_event["payload"]["comparison_id"] == compare_body["comparison_id"]
    assert compare_event["payload"]["cohort_id"] == compare_body["cohort_id"]
    assert compare_event["payload"]["objective"] == "level_forecast"

    # P2: explicit skip of a single model from the closure loop -- traceable event.
    single_skip_events = [
        e for e in _by_type("tuning_skipped") if "model_id" in e["payload"]
    ]
    assert single_skip_events, "tuning/skip events from the closure loop not written"
    assert single_skip_events[-1]["payload"]["model_id"]

    # P0: selection/evaluate (compare is closed -- gate "do comparison first" passed;
    # 409-loops are kept as a defensive case of any re-invalidation).
    evaluation: object = None
    for _round in range(6):
        probe = client.post(
            "/v1/session/modeling/selection/evaluate", json={"min_oof_points": 4}
        )
        if probe.status_code == 200:
            evaluation = probe
            break
        assert probe.status_code == 409, probe.text
        detail = probe.json()["detail"]
        for model_id in detail.get("pending_backtests", []):
            excluded = client.post(
                "/v1/session/modeling/backtest/exclude",
                json={"model_id": model_id, "decision": "exclude",
                      "reason": "Not included in the comparison", "acknowledge": True},
            )
            assert excluded.status_code == 200, excluded.text
        for model_id in detail.get("pending_tuning", []):
            skipped = client.post(
                "/v1/session/modeling/tuning/skip",
                json={"model_id": model_id, "reason": "Leave defaults",
                      "acknowledge": True},
            )
            assert skipped.status_code == 200, skipped.text
    assert evaluation is not None, "evaluation did not pass in 6 rounds"
    eval_body = evaluation.json()
    selection_event = _by_type("selection_evaluated")[-1]
    assert (selection_event["stage"], selection_event["node_id"]) == ("modeling", "selection")
    assert selection_event["payload"]["selection_analysis_id"] == eval_body["selection_analysis_id"]
    assert selection_event["payload"]["model_id"] == eval_body["recommended_single"]["model_id"]
    assert selection_event["payload"]["status"] == eval_body["ensemble"]["status"]
    assert selection_event["payload"]["status"] in ("recommended", "not_eligible", "tested_no_gain")

    # P2: skip-pending AFTER full scope closure (compare closed backtests+tuning):
    # an honest "unchanged" -- there is nothing to skip, but the call took place and
    # the fact is traced (idempotent choice; the "skipped" branch is a separate D1b).
    skip_after = client.post(
        "/v1/session/modeling/tuning/skip-pending",
        json={"reason": "Auditor: repeated decision", "acknowledge": True},
    )
    assert skip_after.status_code == 200, skip_after.text
    assert skip_after.json()["status"] == "unchanged"
    last_skip = _by_type("tuning_skipped")[-1]
    assert (last_skip["stage"], last_skip["node_id"]) == ("modeling", "tuning")
    assert last_skip["payload"]["status"] == "unchanged"
    assert last_skip["payload"]["model_ids"] == []

    # P2: jobs start/cancel with OWN parameters (max_trials=3 -> total_steps=3);
    # model -- from tunable own pool (theta: "Production tuning не реализован").
    started = client.post(
        "/v1/session/modeling/jobs/start",
        json={"operation": "tuning", "model_id": "ets", "max_trials": 3,
              "metric": "rmse", "random_state": 20},
    )
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]
    start_event = _by_type("tuning_job_started")[-1]
    assert (start_event["stage"], start_event["node_id"]) == ("modeling", "tuning")
    assert start_event["payload"]["operation"] == "tuning"
    assert start_event["payload"]["model_id"] == "ets"
    assert start_event["payload"]["total_steps"] == 3

    my_reason = "Stopped by PROGR-20-CERT auditor"
    cancelled = client.post(
        f"/v1/session/modeling/jobs/{job_id}/cancel", json={"reason": my_reason}
    )
    assert cancelled.status_code == 200, cancelled.text
    cancel_event = _by_type("tuning_job_cancelled")[-1]
    assert (cancel_event["stage"], cancel_event["node_id"]) == ("modeling", "tuning")
    assert cancel_event["payload"]["model_id"] == "ets"
    assert cancel_event["payload"]["status"] == "cancelled"
    assert cancel_event["payload"]["reason"] == my_reason

    # Acceptance criterion v1.1 §7 in e2e: both P0 -- in the live trace.
    assert _by_type("candidates_generated") and _by_type("selection_evaluated")


def test_d1b_skip_pending_round_trip_skipped_then_unchanged():
    """Auditor's addition (implementation e2e was not run): skip-pending in a
    clean session (without comparison) -- first 'skipped' with a list of OWN
    pending tuning models, then 'unchanged'. The ONLY reason for the second
    event is the empty pending list -- honest trace of an idempotent choice."""
    _modeling_ready()
    assert client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 4, "n_splits": 2},
    ).status_code == 200
    assert client.post("/v1/session/modeling/baselines").status_code == 200
    for model_id in ("naive", "ets"):
        assert client.post(
            "/v1/session/modeling/backtest", json={"model_id": model_id}
        ).status_code == 200

    skip_first: object = None
    for _round in range(6):
        probe = client.post(
            "/v1/session/modeling/tuning/skip-pending",
            json={"reason": "Auditor: leave defaults", "acknowledge": True},
        )
        if probe.status_code == 200:
            skip_first = probe
            break
        assert probe.status_code == 409, probe.text
        pending = probe.json()["detail"]["pending_backtests"]
        assert pending, "409 without pending_backtests list"
        for model_id in pending:
            excluded = client.post(
                "/v1/session/modeling/backtest/exclude",
                json={"model_id": model_id, "decision": "exclude",
                      "reason": "Not included in the verification", "acknowledge": True},
            )
            assert excluded.status_code == 200, excluded.text
    assert skip_first is not None, "scope did not close in 6 rounds"
    body = skip_first.json()
    assert body["status"] == "skipped"
    assert body["model_ids"], "in own pool there are pending tuning models"

    skip_event = _by_type("tuning_skipped")[-1]
    assert (skip_event["stage"], skip_event["node_id"]) == ("modeling", "tuning")
    assert skip_event["payload"]["status"] == "skipped"
    assert set(skip_event["payload"]["model_ids"]) == set(body["model_ids"])

    skip_second = client.post(
        "/v1/session/modeling/tuning/skip-pending",
        json={"reason": "Repeated call", "acknowledge": True},
    )
    assert skip_second.status_code == 200, skip_second.text
    assert skip_second.json()["status"] == "unchanged"
    last_skip = _by_type("tuning_skipped")[-1]
    assert last_skip["payload"]["status"] == "unchanged"
    assert last_skip["payload"]["model_ids"] == []


def test_d2_layer2_mirror_receives_modeling_facts():
    """§5 layer 2: events of the new types are mirrored into research_runs --
    Mentor/admin-analytics see the facts through their own channel."""
    _modeling_ready()
    first = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 4, "n_splits": 2},
    )
    assert first.status_code == 200, first.text
    run_id = _session().run_id
    mirror = [e for e in _mirror_events(run_id) if e.event_type == "candidates_generated"]
    assert len(mirror) == 1
    assert mirror[0].node_id == "candidate_generation"
    assert mirror[0].payload["runnable_candidates"] == 10


def test_d3_unsuccessful_and_unmatched_calls_leave_no_facts():
    """The trace -- journal of decisions, not errors: 422 of an invalid strategy,
    405 of a wrong method, 409 of an unconfirmed skip -- no new events."""
    _modeling_ready()
    before = len(_events())
    assert before > 0

    bad_strategy = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "bogus", "horizon": 4, "n_splits": 2},
    )
    assert bad_strategy.status_code == 422
    wrong_method = client.get("/v1/session/modeling/candidates")
    assert wrong_method.status_code == 405
    unconfirmed = client.post(
        "/v1/session/modeling/tuning/skip-pending",
        json={"reason": "no acknowledge"},
    )
    assert unconfirmed.status_code == 409
    assert len(_events()) == before
    assert _by_type("candidates_generated") == []
    assert _by_type("tuning_skipped") == []


def test_d4_panel_touches_nodes_but_does_not_paint_statuses():
    """Consumers without contract changes: nodes[] panels get an honest
    last_touched_at by facts of the new types; statuses/reasons -- NOT from
    these events (the source of Modeling statuses -- modeling_pipeline,
    new types are not in EVENT_NODE_STATUS/PAYLOAD_STATUS_EVENT_TYPES)."""
    _modeling_ready()
    response = client.post(
        "/v1/session/modeling/candidates",
        json={"strategy": "expanding", "horizon": 4, "n_splits": 2},
    )
    assert response.status_code == 200, response.text

    trace = client.get("/v1/progress/trace")
    assert trace.status_code == 200, trace.text
    body = trace.json()
    nodes = {f"{n['stage']}/{n['node_id']}": n for n in body["nodes"]}
    node = nodes["modeling/candidate_generation"]
    assert node["last_touched_at"], "last_touched_at of the node not updated by the fact"
    assert node["status_reason"] is None, "new types do not set the reason"
    # The event does not paint the status (not in EVENT_NODE_STATUS).
    statuses = body["node_statuses"]
    assert statuses.get("modeling/candidate_generation") != "done"
    assert statuses.get("modeling/candidate_generation") != "warning"


def test_d5_offtable_old_route_backtest_still_traced():
    """The backtest route (PROGR-8, outside the v1.1 table) is not narrowed:
    the event carries metrics.mape -- regression check of the 'existing contracts
    are not narrowed' criterion (v1.1 §7)."""
    _modeling_ready()
    backtest = client.post("/v1/session/modeling/backtest", json={"model_id": "naive"})
    assert backtest.status_code == 200, backtest.text
    events = _by_type("backtest_run")
    assert events, "backtest_run not written"
    payload = events[-1]["payload"]
    assert payload["model_id"] == "naive"
    assert "mape" in payload, "dotted key metrics.mape is preserved"
    assert isinstance(payload["n_train"], int) and payload["n_train"] > 0
