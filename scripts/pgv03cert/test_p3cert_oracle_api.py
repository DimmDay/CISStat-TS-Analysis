# scripts/pgv03cert/test_p3cert_oracle_api.py
#
# PGV-03-CERT — Класс A: API-оракулы durable-слоя на СВОИХ данных.
# Freeze/CAS/идемпотентность/export без науки (AC06)/CAS экспорта (AC07)/
# best-effort «наука первична»/заголовки §6/sweep-добор.

from __future__ import annotations

import sys
from dataclasses import replace as dc_replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

CERT_DIR = Path(__file__).resolve().parent
REPO = CERT_DIR.parents[1]
sys.path.insert(0, str(CERT_DIR))

import pytest  # noqa: E402

import p3cases  # noqa: E402
from apps.api.artifact_store import (  # noqa: E402
    get_artifact_object_store,
    reset_artifact_object_store_for_testing,
)
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef  # noqa: E402
from apps.api.research_runs import (  # noqa: E402
    ResearchRun,
    get_research_run_store,
)
from apps.api.security_audit import reset_audit_for_testing  # noqa: E402
from apps.api.visual_artifacts import (  # noqa: E402
    PrintContextConflict,
    list_visual_results,
)
from apps.api.visual_producers import (  # noqa: E402
    VisualSourceUnavailable,
    VisualViewOutOfScope,
    freeze_saved_visual,
    freeze_visual_from_response,
    get_saved_visual_response,
    reset_visual_response_cache_for_testing,
    save_visual_response,
    visual_result_ref,
)

RUN_ID = "RUN-P3C0001A"
SESSION_ID = "p3cert-session"
OTHER_RUN_ID = "RUN-P3C0002B"

VIEW = "upload.chart.series"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _request() -> SimpleNamespace:
    """Свой дубль запроса: cookie-сессия == владелец seeded run.
    resolve_request_subject: cookie -> peek store (пусто после reset) ->
    детерминированный суррогат SubjectRef.from_session(SESSION_ID) --
    тот же субъект, что owner_subject seeded run."""
    from apps.api.session_store import SESSION_COOKIE_NAME

    return SimpleNamespace(
        cookies={SESSION_COOKIE_NAME: SESSION_ID}, headers={}
    )


def _seed_run(run_id: str = RUN_ID, *, context_id: str | None = "ctx-p3cert-1", data_revision: int = 3):
    store = get_research_run_store()
    subj = SubjectRef.from_session(SESSION_ID)
    run = ResearchRun(
        run_id=run_id,
        session_id=SESSION_ID,
        dataset_fingerprint="p3" * 16,
        dataset_name="p3cert-seed",
        target_column="value",
        created_at=_now(),
        last_active_at=_now(),
        status="active",
        owner_subject=subj.subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
        context_id=context_id,
        data_revision=data_revision,
    )
    store.upsert_run(run)
    return run


def _subject(session_id: str = SESSION_ID) -> SubjectRef:
    return SubjectRef.from_session(session_id)


class _Session:
    """Свой дубль сессии (duck-type контракта save_visual_response)."""

    def __init__(self, run_id: str = RUN_ID, *, context_id: str | None = "ctx-p3cert-1", data_revision: int = 3):
        self.run_id = run_id
        self.session_id = SESSION_ID
        self.dataset = SimpleNamespace(dataset_id="p3cert-ds")
        self.data_revision = data_revision
        self._context_id = context_id

    def current_context_id(self) -> str | None:
        return self._context_id


def _saved_artifacts(run_id: str = RUN_ID, view_id: str = VIEW):
    return [a for a in list_visual_results(run_id) if a.refs.get("view_id") == view_id]


# ── 1. Freeze в момент фиксации (producer_freeze) ────────────────────


class TestFreezeAtResponse:
    def test_freeze_registers_artifact_with_honest_payload(self):
        _seed_run()
        response = p3cases.timeseries_response(sampled=True, n_points=6)
        artifact = freeze_visual_from_response(
            RUN_ID, _subject(), view_id=VIEW, response=response, session_id=SESSION_ID,
            params={"selected_column": "value"}, computed_at=None,
        )
        assert artifact is not None
        stored = _saved_artifacts()
        assert len(stored) == 1
        payload = __import__("json").loads(
            get_artifact_object_store().read_bytes(stored[0].storage_key).decode("utf-8")
        )
        assert payload["payload"]["digest"] == p3cases.sha256_hex(payload["payload"]["data"])
        assert payload["execution"]["computed_at"] is None
        assert payload["execution"]["computed_at_reason"] == "producer_not_reported"

    def test_producer_key_idempotency_same_response_no_new_artifact(self):
        _seed_run()
        response = p3cases.timeseries_response()
        freeze_visual_from_response(RUN_ID, _subject(), view_id=VIEW, response=response, session_id=SESSION_ID)
        freeze_visual_from_response(RUN_ID, _subject(), view_id=VIEW, response=response, session_id=SESSION_ID)
        assert len(_saved_artifacts()) == 1  # §11: тот же ref -- no-op

    def test_recalculated_result_is_new_immutable_artifact(self):
        _seed_run()
        freeze_visual_from_response(
            RUN_ID, _subject(), view_id=VIEW,
            response=p3cases.timeseries_response(), session_id=SESSION_ID,
        )
        freeze_visual_from_response(
            RUN_ID, _subject(), view_id=VIEW,
            response=p3cases.timeseries_response(n_points=9), session_id=SESSION_ID,
        )
        assert len(_saved_artifacts()) == 2  # §8: новый ref -- новый артефакт

    def test_explicit_cas_conflict_registers_nothing(self):
        _seed_run(context_id="ctx-OLD", data_revision=3)
        get_research_run_store().upsert_run(
            dc_replace(get_research_run_store().get_run(RUN_ID), context_id="ctx-NEW")
        )
        with pytest.raises(PrintContextConflict):
            freeze_visual_from_response(
                RUN_ID, _subject(), view_id=VIEW,
                response=p3cases.timeseries_response(), session_id=SESSION_ID,
                expected_context_id="ctx-OLD",
            )
        assert list_visual_results(RUN_ID) == []  # НИЧЕГО не зарегистрировано

    def test_noncanonical_slice_refused_nothing_registered(self):
        _seed_run()
        bad = p3cases.timeseries_response()
        bad["points"] = [{"x": 1, "y": float("nan")}]
        with pytest.raises(Exception):
            freeze_visual_from_response(
                RUN_ID, _subject(), view_id=VIEW, response=bad, session_id=SESSION_ID,
            )
        assert list_visual_results(RUN_ID) == []  # честный отказ гейта (§8)

    def test_unwired_view_refused_with_honest_gap(self):
        _seed_run()
        for view_id in sorted(("preprocessing.spectral.periodogram", "forecasting.accuracy.metrics")):
            with pytest.raises(VisualViewOutOfScope):
                freeze_visual_from_response(
                    RUN_ID, _subject(), view_id=view_id,
                    response=p3cases.timeseries_response(), session_id=SESSION_ID,
                )
        assert list_visual_results(RUN_ID) == []


# ── 2. Export из кэша (producer_first_export): AC06/AC07 ─────────────


class TestExportFromCache:
    def test_export_freezes_saved_response_after_session_loss(self):
        """AC06: renderer не вызывает GET -- export работает ИСКЛЮЧИТЕЛЬНО
        из кэша сохранённых ответов."""
        _seed_run()
        session = _Session()
        response = p3cases.timeseries_response(sampled=True, n_points=5)
        ref = save_visual_response(session, response=response, params={"selected_column": "v"})
        assert ref is not None
        from apps.api.session_store import reset_session_store_for_testing

        reset_session_store_for_testing()  # сессия утрачена
        artifact = freeze_saved_visual(
            RUN_ID, _subject(), view_id=VIEW, result_ref=ref, session_id=SESSION_ID,
        )
        assert artifact is not None
        payload = __import__("json").loads(
            get_artifact_object_store().read_bytes(artifact.storage_key).decode("utf-8")
        )
        assert payload["payload"]["data"] == {
            "series": response["points"],
            "was_resorted": False,
            "column": "value",
            "date_column": "date",
        }
        # origin первого экспорта -- producer_first_export (§6)
        assert payload["parameters"]["origin"] == "producer_first_export"
        # computed_at -- момент фиксации сохранённого ответа
        assert payload["execution"]["computed_at"] is not None

    def test_export_after_cache_eviction_is_source_unavailable_no_science(self):
        _seed_run()
        with pytest.raises(VisualSourceUnavailable):
            freeze_saved_visual(
                RUN_ID, _subject(), view_id=VIEW,
                result_ref="vr-" + "0" * 32, session_id=SESSION_ID,
            )
        assert list_visual_results(RUN_ID) == []  # пересчёта науки нет

    def test_export_of_other_run_response_is_unavailable(self):
        _seed_run(RUN_ID)
        _seed_run(OTHER_RUN_ID)
        response = p3cases.timeseries_response()
        ref = save_visual_response(_Session(RUN_ID), response=response)
        # чужой запуск: тот же ref не отдаётся (run-scope кэша)
        assert get_saved_visual_response(OTHER_RUN_ID, ref) is None
        with pytest.raises(VisualSourceUnavailable):
            freeze_saved_visual(
                OTHER_RUN_ID, _subject("p3cert-other"), view_id=VIEW,
                result_ref=ref, session_id=SESSION_ID,
            )

    def test_export_cas_conflict_after_data_change_registers_nothing(self):
        """AC07: смена данных между показом и export -> 409, НИЧЕГО."""
        _seed_run(context_id="ctx-p3cert-1", data_revision=3)
        session = _Session(context_id="ctx-p3cert-1", data_revision=3)
        ref = save_visual_response(session, response=p3cases.timeseries_response())
        assert ref is not None
        # данные сменились: durable-зеркало отражает новую ревизию
        store = get_research_run_store()
        store.upsert_run(dc_replace(store.get_run(RUN_ID), data_revision=4))
        with pytest.raises(PrintContextConflict):
            freeze_saved_visual(
                RUN_ID, _subject(), view_id=VIEW, result_ref=ref, session_id=SESSION_ID,
            )
        assert list_visual_results(RUN_ID) == []

    def test_export_cas_conflict_after_context_change_registers_nothing(self):
        """AC07 (контекстное измерение, изолированно): смена КОНТЕКСТА
        запуска между показом и экспортом (ревизия не тронута) ->
        PrintContextConflict, НИЧЕГО не зарегистрировано. «CAS ВСЕГДА
        сверяет контекст сохранённого ответа» (док поставки §3.4)."""
        _seed_run(context_id="ctx-p3cert-1", data_revision=3)
        session = _Session(context_id="ctx-p3cert-1", data_revision=3)
        ref = save_visual_response(session, response=p3cases.timeseries_response())
        assert ref is not None
        store = get_research_run_store()
        store.upsert_run(
            dc_replace(store.get_run(RUN_ID), context_id="ctx-p3cert-2")
        )
        with pytest.raises(PrintContextConflict):
            freeze_saved_visual(
                RUN_ID, _subject(), view_id=VIEW, result_ref=ref, session_id=SESSION_ID,
            )
        assert list_visual_results(RUN_ID) == []


# ── 3. Кэш сохранённых ответов ───────────────────────────────────────


class TestResponseCache:
    def test_save_requires_run(self):
        session = _Session()
        session.run_id = ""
        assert save_visual_response(session, response=p3cases.timeseries_response()) is None

    def test_save_requires_dataset(self):
        session = _Session()
        session.dataset = None
        assert save_visual_response(session, response=p3cases.timeseries_response()) is None

    def test_lru_cap_256_enforced(self):
        _seed_run()
        session = _Session()
        refs = []
        for i in range(260):
            ref = save_visual_response(session, response=p3cases.timeseries_response(n_points=i + 1))
            refs.append(ref)
        # первые вытеснены: их export честно недоступен
        assert get_saved_visual_response(RUN_ID, refs[0]) is None
        assert get_saved_visual_response(RUN_ID, refs[-1]) is not None

    def test_same_content_same_ref_cache_refreshed(self):
        _seed_run()
        session = _Session()
        r1 = save_visual_response(session, response=p3cases.timeseries_response())
        r2 = save_visual_response(session, response=p3cases.timeseries_response())
        assert r1 == r2  # идемпотентность §11

    def test_cached_context_is_session_moment(self):
        _seed_run()
        session = _Session(context_id="ctx-moment", data_revision=7)
        ref = save_visual_response(session, response=p3cases.timeseries_response())
        saved = get_saved_visual_response(RUN_ID, ref)
        assert saved is not None
        assert saved.context_id == "ctx-moment"
        assert saved.data_revision == 7
        assert saved.computed_at is not None  # момент фиксации


# ── 4. Best-effort «наука первична» + receipt ────────────────────────


class TestBestEffort:
    def test_notify_freeze_failure_does_not_break_outcome(self, monkeypatch):
        from apps.api import promotion_integration, visual_producers

        _seed_run()
        session = _Session()
        monkeypatch.setattr(
            visual_producers,
            "freeze_visual_from_response",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("durable down")),
        )
        request = _request()
        outcome = promotion_integration.notify_visual_result(
            request, session, view_ids=(VIEW,),
            response=p3cases.timeseries_response(), params={"selected_column": "v"},
        )
        assert outcome is not None  # ответ/исход жив -- наука первична
        assert outcome.artifacts[VIEW] is None  # freeze честно не удался

    def test_notify_failure_records_audit_receipt(self, monkeypatch):
        from apps.api import promotion_integration, visual_producers
        from apps.api.security_audit import audit_records

        _seed_run()
        session = _Session()
        monkeypatch.setattr(
            visual_producers,
            "freeze_visual_from_response",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("durable down")),
        )
        request = _request()
        promotion_integration.notify_visual_result(
            request, session, view_ids=(VIEW,),
            response=p3cases.timeseries_response(),
        )
        records = audit_records()
        # receipt -- standard-запись artifact_promotion_failed (§14.1)
        kinds = [str(r.get("action", r.get("kind", ""))) for r in records]
        assert any("artifact_promotion_failed" in k for k in kinds), kinds[:5]

    def test_notify_without_run_is_honest_skip(self):
        from apps.api import promotion_integration

        session = _Session()
        session.run_id = ""
        outcome = promotion_integration.notify_visual_result(
            _request(), session, view_ids=(VIEW,),
            response=p3cases.timeseries_response(),
        )
        assert outcome is None
        assert list_visual_results(RUN_ID) == []

    def test_notify_registers_artifact_and_returns_ref(self):
        from apps.api import promotion_integration

        _seed_run()
        session = _Session()
        response = p3cases.timeseries_response()
        outcome = promotion_integration.notify_visual_result(
            _request(), session, view_ids=(VIEW,),
            response=response, params={"selected_column": "v"},
        )
        assert outcome is not None
        assert outcome.result_ref == visual_result_ref({"selected_column": "v"}, response)
        assert len(_saved_artifacts()) == 1


class TestVisualHeaders:
    """§6: «Response содержит result_ref/context/version token»."""

    def _notify(self):
        from apps.api import promotion_integration

        _seed_run()
        session = _Session()
        response = p3cases.timeseries_response()
        http = SimpleNamespace(headers={})
        outcome = promotion_integration.notify_visual_result(
            _request(), session, view_ids=(VIEW,),
            response=response, http_response=http,
        )
        return outcome, http

    def test_result_ref_header(self):
        outcome, http = self._notify()
        assert http.headers["X-Visual-Result-Ref"] == outcome.result_ref

    def test_context_header(self):
        _, http = self._notify()
        assert http.headers["X-Visual-Context-Id"] == "ctx-p3cert-1"

    def test_revision_header(self):
        _, http = self._notify()
        assert http.headers["X-Visual-Data-Revision"] == "3"

    def test_headers_degrade_honestly_without_response(self):
        from apps.api import promotion_integration

        promotion_integration.apply_visual_headers(None, None)  # не бросает


# ── 5. Sweep modeling (добор без науки) ──────────────────────────────


class TestSweepVisuals:
    def test_sweep_freezes_comparison_and_oof_from_saved_backtests(self):
        from apps.api import promotion_integration

        _seed_run()
        session = _Session()
        session.modeling_artifacts = {"backtests": p3cases.backtests_response()["backtests"]}
        counts = promotion_integration.notify_modeling_artifacts_updated(
            _request(), session
        )
        assert counts["visual_result"] == 2
        views = {a.refs.get("view_id") for a in list_visual_results(RUN_ID)}
        assert views == {"modeling.backtest.comparison", "modeling.backtest.oof"}

    def test_sweep_repeat_is_noop_idempotent(self):
        from apps.api import promotion_integration

        _seed_run()
        session = _Session()
        session.modeling_artifacts = {"backtests": p3cases.backtests_response()["backtests"]}
        promotion_integration.notify_modeling_artifacts_updated(_request(), session)
        counts2 = promotion_integration.notify_modeling_artifacts_updated(
            _request(), session
        )
        assert counts2["visual_result"] == 0  # AC09: повтор no-op

    def test_sweep_without_backtests_is_zero(self):
        from apps.api import promotion_integration

        _seed_run()
        session = _Session()
        session.modeling_artifacts = {}
        counts = promotion_integration.notify_modeling_artifacts_updated(
            _request(), session
        )
        assert counts["visual_result"] == 0


# ── 6. Скоуп-гварды ──────────────────────────────────────────────────


class TestScopeGuards:
    def test_unknown_view_refused(self):
        from apps.api.visual_producers import UnknownVisualView, resolve_producer_view

        with pytest.raises(UnknownVisualView):
            resolve_producer_view("p3cert.unknown.view")

    def test_static_demo_refused(self):
        from apps.api.print_schema import load_visual_registry
        from apps.api.visual_producers import (
            resolve_producer_view,
            static_demo_view_ids,
        )

        demos = static_demo_view_ids()
        assert len(demos) == 16
        with pytest.raises(VisualViewOutOfScope):
            resolve_producer_view(demos[0])

    def test_out_of_scope_error_names_followup_task(self):
        from apps.api.visual_producers import resolve_producer_view

        with pytest.raises(VisualViewOutOfScope) as exc:
            resolve_producer_view("forecasting.accuracy.metrics")  # unwired → PGV-12
        assert "PGV-12" in str(exc.value) or "PGV-10/11/12" in str(exc.value)

    def test_wired_view_resolves(self):
        from apps.api.visual_producers import resolve_producer_view, wired_view_ids

        site = resolve_producer_view(sorted(wired_view_ids())[0])
        assert site["view_id"] == sorted(wired_view_ids())[0]
