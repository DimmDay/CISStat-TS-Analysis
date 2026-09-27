# tests/api/test_admin_progress_api.py
"""REST-тесты Task PROGR-8 (plan_progress.md): Admin-панель (§10) +
офлайн-потребители (§9) -- namespace /v1/progress/admin/*.

Контур:

  1. Авторизация §10 дословно: «admin-эндпоинты должны требовать
     API-ключ с ролью ADMIN, а не cookie -- админ заходит другим путём».
     Та же ролевая модель (Role + get_current_principal), не новая
     система: 401 неверный ключ, 403 не-ADMIN, 500 ключи не настроены.
  2. GET /v1/progress/admin/overview -- агрегаты по корпусу (сборка
     роутером из хранилища; семантика движка покрыта
     test_admin_analytics.py); пустой корпус -- честные нули
     («не гейтится кодом», приёмка плана).
  3. GET /v1/progress/admin/case-bank/candidates -- отбор кандидатов
     банка кейсов (§9) с параметрами эвристики.
  4. Защитный контур: сбой долговременного слоя -- честный 503
     (паттерн PROGR-5/6/7); админ-эндпоинты не трассируются хуком.
  5. Запись наблюдений Наставника (источник частот §10):
     sanity-check -- run-контекст из cookie-сессии (фронтенд шлёт
     credentials: include, тело запроса НЕ меняется -- обратная
     совместимость); next-step -- run_id пути. Обе записи best-effort:
     сбой журнала не ломает ответ (предупреждения вспомогательны,
     §12 п.8); без run-контекста/без сработавших правил записей нет.
  6. Дополнение хука (аддитивно): dotted-ключ "metrics.mape" в
     whitelist backtest_run -- скор финального бэктеста попадает в
     корпус (доказательство для эвристики §9); плоские ключи работают
     как прежде.
"""
from __future__ import annotations

from datetime import timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.research_runs import (
    MentorObservation,
    ResearchRun,
    get_research_run_store,
    reset_research_run_store_for_testing,
)
from apps.api.session_store import (
    SESSION_COOKIE_NAME,
    get_session_store,
    reset_session_store_for_testing,
)
from apps.api.trace_events import make_trace_event

ADMIN_HEADERS = {"X-API-Key": "admin-key-000"}     # Role.ADMIN
USER_HEADERS = {"X-API-Key": "user-key-0001"}      # external_user (тариф demo)
ANALYST_HEADERS = {"X-API-Key": "analyst-key-00"}  # internal_analyst


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path, monkeypatch):
    """Изоляция КАЖДОГО теста (паттерн test_research_runs.py): свои
    каталоги данных, memory-бэкенд, чистые синглтоны, свой реестр
    API-ключей."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.setenv(
        "CISSTAT_API_KEYS",
        "admin-key-000:admin:,user-key-0001:external_user:demo,"
        "analyst-key-00:internal_analyst:",
    )
    reset_session_store_for_testing()
    from apps.api import research_runs

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    yield
    reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def _ts_ago(minutes: float = 0.0, days: float = 0.0) -> str:
    from datetime import datetime

    moment = datetime.now(timezone.utc) - timedelta(days=days, minutes=minutes)
    return moment.isoformat()


def _populate_run(
    run_id: str,
    *,
    status: str = "active",
    events: list[Any] | None = None,
    created_minutes_ago: float = 60.0,
) -> None:
    store = get_research_run_store()
    store.upsert_run(
        ResearchRun(
            run_id=run_id,
            session_id="sess-1",
            dataset_name="prices.csv",
            created_at=_ts_ago(minutes=created_minutes_ago),
            last_active_at=_ts_ago(minutes=max(created_minutes_ago - 10.0, 0.0)),
            status=status,
        )
    )
    for event in events or []:
        store.append_event(run_id, event)


def _previewed_event(run_id: str, node_id: str = "missing") -> Any:
    return make_trace_event(
        "correction_previewed",
        stage="preprocessing",
        node_id=node_id,
        run_id=run_id,
        ts=_ts_ago(days=1.0),
        strategy="interpolate",
        total_changed=0,
    )


def _backtest_event(run_id: str, mape: float) -> Any:
    return make_trace_event(
        "backtest_run",
        stage="modeling",
        node_id="backtest",
        run_id=run_id,
        ts=_ts_ago(days=0.5),
        model_id="ets",
        model_name="ETS",
        family_id="ets",
        n_train=100,
        n_test=20,
        mape=mape,
    )


# ── 1. Авторизация (§10: API-ключ с ролью ADMIN) ─────────────────────


class TestAdminAuth:
    def test_wrong_key_is_401(self, client):
        resp = client.get(
            "/v1/progress/admin/overview", headers={"X-API-Key": "wrong"}
        )
        assert resp.status_code == 401

    def test_external_user_is_403(self, client):
        resp = client.get("/v1/progress/admin/overview", headers=USER_HEADERS)
        assert resp.status_code == 403
        assert "ADMIN" in resp.json()["detail"]

    def test_internal_analyst_is_403(self, client):
        # Внутренний аналитик -- сотрудник, но НЕ администратор: админка
        # определяется идентичностью (§10), полные capabilities роли тут
        # не помогают (роль, не тарифная возможность).
        resp = client.get("/v1/progress/admin/overview", headers=ANALYST_HEADERS)
        assert resp.status_code == 403

    def test_keys_not_configured_is_500(self, client, monkeypatch):
        monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
        resp = client.get("/v1/progress/admin/overview", headers=ADMIN_HEADERS)
        assert resp.status_code == 500

    def test_admin_role_passes(self, client):
        resp = client.get("/v1/progress/admin/overview", headers=ADMIN_HEADERS)
        assert resp.status_code == 200


# ── 2. Agрегаты /v1/progress/admin/overview ──────────────────────────


class TestAdminOverview:
    def test_aggregates_populated_corpus(self, client):
        store = get_research_run_store()
        _populate_run("RUN-AAA00001", status="completed")
        _populate_run("RUN-BBB00002", status="active")
        store.append_event("RUN-AAA00001", _previewed_event("RUN-AAA00001"))
        store.append_mentor_observation(
            MentorObservation(
                run_id="RUN-AAA00001",
                obs_kind="sanity_warning",
                rule_id="no_effect",
                stage="preprocessing",
                node_id="missing",
                severity="warning",
            )
        )
        store.append_mentor_observation(
            MentorObservation(
                run_id="RUN-BBB00002",
                obs_kind="next_step",
                rule_id="preprocessing_missing_attention",
                stage="preprocessing",
                node_id=None,
                severity="",
            )
        )

        resp = client.get(
            "/v1/progress/admin/overview?days=30&top=10", headers=ADMIN_HEADERS
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["runs_total_all_time"] == 2
        assert data["runs_by_status"]["completed"] == 1
        assert data["runs_by_status"]["active"] == 1
        assert data["top_problem_nodes"][0]["node_id"] == "missing"
        assert data["top_problem_nodes"][0]["status"] == "warning"
        assert data["sanity_by_rule"][0]["rule_id"] == "no_effect"
        assert data["sanity_by_node"][0]["node_id"] == "missing"
        assert data["next_step_frequency"][0]["rule_id"] == (
            "preprocessing_missing_attention"
        )
        assert data["generated_at"]

    def test_empty_corpus_honest_zeros(self, client):
        resp = client.get("/v1/progress/admin/overview", headers=ADMIN_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["runs_total_all_time"] == 0
        assert data["runs_by_status"] == {
            "active": 0, "paused": 0, "completed": 0, "abandoned": 0,
        }
        assert data["stage_time"] == []
        assert data["sanity_by_rule"] == []

    def test_query_validation(self, client):
        assert client.get(
            "/v1/progress/admin/overview?days=0", headers=ADMIN_HEADERS
        ).status_code == 422
        assert client.get(
            "/v1/progress/admin/overview?top=0", headers=ADMIN_HEADERS
        ).status_code == 422
        assert client.get(
            "/v1/progress/admin/overview?days=100000", headers=ADMIN_HEADERS
        ).status_code == 422

    def test_outage_is_honest_503(self, client, monkeypatch):
        from apps.api import research_runs

        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
        research_runs.reset_research_run_store_for_testing()
        try:
            resp = client.get(
                "/v1/progress/admin/overview", headers=ADMIN_HEADERS
            )
            assert resp.status_code == 503
            assert resp.json()["detail"] == "Долговременный слой недоступен"
        finally:
            research_runs.reset_research_run_store_for_testing()

    def test_admin_endpoints_not_traced(self):
        from apps.api.trace_hook import resolve_trace_route

        assert resolve_trace_route("GET", "/v1/progress/admin/overview") is None
        assert (
            resolve_trace_route("GET", "/v1/progress/admin/case-bank/candidates")
            is None
        )


# ── 3. Банк кейсов /v1/progress/admin/case-bank/candidates ───────────


class TestCaseBankAPI:
    def test_candidates_with_evidence(self, client):
        store = get_research_run_store()
        _populate_run("RUN-AAA00001", status="completed")
        store.append_event("RUN-AAA00001", _backtest_event("RUN-AAA00001", 12.5))
        store.append_event("RUN-AAA00001", _previewed_event("RUN-AAA00001"))

        resp = client.get(
            "/v1/progress/admin/case-bank/candidates", headers=ADMIN_HEADERS
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_completed"] == 1
        assert len(data["candidates"]) == 1
        candidate = data["candidates"][0]
        assert candidate["run_id"] == "RUN-AAA00001"
        assert candidate["backtest_mape"] == pytest.approx(12.5)
        assert candidate["warning_nodes"] == 1
        assert candidate["sanity_warnings"] == 0
        assert data["criteria"]["max_backtest_mape"] == pytest.approx(30.0)

    def test_strict_threshold_excludes_run(self, client):
        store = get_research_run_store()
        _populate_run("RUN-AAA00001", status="completed")
        store.append_event("RUN-AAA00001", _backtest_event("RUN-AAA00001", 12.5))

        resp = client.get(
            "/v1/progress/admin/case-bank/candidates?max_backtest_mape=5",
            headers=ADMIN_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["candidates"] == []

    def test_requires_admin(self, client):
        resp = client.get(
            "/v1/progress/admin/case-bank/candidates", headers=USER_HEADERS
        )
        assert resp.status_code == 403


# ── 4. Запись наблюдений Наставника (источник частот §10) ────────────


class TestObservationRecording:
    def _session_with_run(self, client) -> str:
        client.get("/v1/session/current")  # выставляет cookie
        session_id = client.cookies.get(SESSION_COOKIE_NAME)
        store = get_session_store()
        session = store.get_or_create(session_id)
        run_id = session.ensure_run_id()
        store.save(session)
        return run_id

    def _sanity_payload(self) -> dict[str, Any]:
        # affected > 0 и changed == 0 -> правило no_effect срабатывает.
        return {
            "stage": "preprocessing",
            "node_id": "missing",
            "strategy": "interpolate",
            "affected_count_before": 5,
            "changed_count": 0,
            "still_affected_count": 5,
            "rows_before": 100,
            "rows_after": 100,
        }

    def test_sanity_check_records_warning_with_run_context(self, client):
        run_id = self._session_with_run(client)
        resp = client.post(
            "/v1/progress/mentor/sanity-check", json=self._sanity_payload()
        )
        assert resp.status_code == 200
        assert any(w["rule_id"] == "no_effect" for w in resp.json()["warnings"])

        observations = get_research_run_store().list_mentor_observations()
        assert len(observations) == 1
        obs = observations[0]
        assert obs.obs_kind == "sanity_warning"
        assert obs.rule_id == "no_effect"
        assert obs.run_id == run_id
        assert obs.stage == "preprocessing"
        assert obs.node_id == "missing"
        assert obs.severity == "warning"

    def test_sanity_check_without_cookie_records_nothing(self, client):
        # Запрос без cookie (нет run-контекста) -- предупреждения
        # вычисляются как прежде, журнал не пишется.
        resp = client.post(
            "/v1/progress/mentor/sanity-check", json=self._sanity_payload()
        )
        assert resp.status_code == 200
        assert get_research_run_store().list_mentor_observations() == []

    def test_sanity_check_without_warnings_records_nothing(self, client):
        self._session_with_run(client)
        payload = self._sanity_payload()
        payload["changed_count"] = 5  # правка сработала: предупреждений нет
        resp = client.post("/v1/progress/mentor/sanity-check", json=payload)
        assert resp.status_code == 200
        assert resp.json()["warnings"] == []
        assert get_research_run_store().list_mentor_observations() == []

    def test_sanity_recording_is_best_effort(self, client, monkeypatch):
        self._session_with_run(client)
        store = get_research_run_store()

        def _boom(obs):
            raise RuntimeError("журнал недоступен")

        monkeypatch.setattr(store, "append_mentor_observation", _boom)
        resp = client.post(
            "/v1/progress/mentor/sanity-check", json=self._sanity_payload()
        )
        # Сбой журнала НЕ ломает ответ: предупреждения вспомогательны.
        assert resp.status_code == 200
        assert any(w["rule_id"] == "no_effect" for w in resp.json()["warnings"])

    def test_next_step_records_served_recommendation(self, client):
        _populate_run("RUN-AAA00001", status="active")
        get_research_run_store().append_event(
            "RUN-AAA00001", _previewed_event("RUN-AAA00001")
        )
        resp = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step")
        assert resp.status_code == 200
        recommendation = resp.json()["recommendation"]
        assert recommendation is not None

        observations = get_research_run_store().list_mentor_observations()
        assert len(observations) == 1
        obs = observations[0]
        assert obs.obs_kind == "next_step"
        assert obs.rule_id == recommendation["rule_id"]
        assert obs.run_id == "RUN-AAA00001"
        assert obs.stage == recommendation["stage"]

        # Частота -- по ВЫДАЧАМ: повторный запрос накапливает наблюдение.
        client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step")
        assert len(get_research_run_store().list_mentor_observations()) == 2

    def test_next_step_without_recommendation_records_nothing(self, client):
        _populate_run("RUN-AAA00001", status="active")
        resp = client.get("/v1/progress/runs/RUN-AAA00001/mentor/next-step")
        assert resp.status_code == 200
        assert resp.json()["recommendation"] is None
        assert get_research_run_store().list_mentor_observations() == []


# ── 5. Дополнение хука: dotted-ключ metrics.mape (аддитивно) ─────────


class TestHookMapePayload:
    def test_extract_payload_supports_dotted_path(self):
        from apps.api.trace_hook import TraceRouteSpec, _extract_payload

        spec = TraceRouteSpec(
            "POST", "/x", "modeling", "backtest", "backtest_run",
            payload_keys=("model_id", "metrics.mape"),
        )
        body = {"model_id": "ets", "metrics": {"mae": 1.0, "mape": 12.5}}
        payload = _extract_payload(spec, body)
        # Dotted-ключ сохраняется в payload ПОД последним сегментом:
        # корпус хранит факты плоскими ключами (§4.1).
        assert payload == {"model_id": "ets", "mape": 12.5}

    def test_dotted_path_missing_key_is_skipped(self):
        from apps.api.trace_hook import TraceRouteSpec, _extract_payload

        spec = TraceRouteSpec(
            "POST", "/x", "modeling", "backtest", "backtest_run",
            payload_keys=("metrics.mape",),
        )
        assert _extract_payload(spec, {"metrics": None}) == {}
        assert _extract_payload(spec, {"metrics": {"mae": 1.0}}) == {}

    def test_backtest_route_whitelist_carries_mape(self):
        from apps.api.trace_hook import TRACE_ROUTES

        spec = next(
            item for item in TRACE_ROUTES
            if item.path_template == "/v1/session/modeling/backtest"
        )
        assert "metrics.mape" in spec.payload_keys

    def test_flat_keys_work_as_before(self):
        from apps.api.trace_hook import _extract_payload

        spec = type(
            "Spec", (), {"payload_keys": ("model_id", "n_train")}
        )()
        payload = _extract_payload(
            spec, {"model_id": "ets", "n_train": 100, "metrics": {"mape": 1.0}}
        )
        assert payload == {"model_id": "ets", "n_train": 100}
