# scripts/doclog0cert/test_doclog0cert_oracle_api.py
"""DOCLOG-0-CERT: API-оракулы сертификатора на живых маршрутах.

Закрытие блокера F08 (spec §15.1) на СВОИХ данных: владелец читает
СВОЙ запуск, чужая сессия/аноним -- uniform 404 (неотличим от
отсутствия), write-пути под тем же гейтом, restore-наследование,
гвард зеркала слоя 2, ops-блок. Корпус -- oracle_corpus.py
(RUN-DCAC0Axx / dca-cert-*), дизъюнктен repo-корпусу.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.session_store import SESSION_COOKIE_NAME

from scripts.doclog0cert import oracle_corpus as C
from scripts.doclog0cert.test_doclog0cert_oracle_unit import _bound_run

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_SALT", raising=False)
    from apps.api import research_runs
    from apps.api.session_store import reset_session_store_for_testing

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    reset_session_store_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    reset_session_store_for_testing()


@pytest.fixture()
def client():
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


def _app():
    from apps.api.main import app

    return app


def _demo_run_id(client: TestClient) -> str:
    resp = client.post("/v1/session/demo")
    assert resp.status_code == 200, resp.text
    trace = client.get("/v1/progress/trace")
    assert trace.status_code == 200, trace.text
    run_id = trace.json().get("run_id")
    assert run_id, "демо-загрузка фиксирует запуск (§5)"
    return run_id


# ── Привязка владельца при создании ──────────────────────────────────


class TestCertOwnerBinding:
    def test_oc36_demo_upload_binds_owner(self, client):
        run_id = _demo_run_id(client)
        cookie = client.cookies.get(SESSION_COOKIE_NAME)
        assert cookie, "cookie-сессия выдана"
        from apps.api import research_runs
        from apps.api.identity import subject_pseudonym

        run = research_runs.get_research_run_store().get_run(run_id)
        assert run is not None
        assert run.ownership == "bound", "новый запуск -- только bound (§15.1)"
        assert run.owner_subject == subject_pseudonym(cookie)
        assert run.owner_subject != cookie, "owner -- псевдоним, не cookie (T4)"
        assert run.tenant_id == "tenant-default"

    def test_oc37_db_upload_binds_owner_too(self, client):
        """ЕДИНАЯ точка register_uploaded_dataframe: БД-дорожка привязывает
        владельца так же, как файл (файл уже покрыт demo-оракулом)."""
        import sqlite3

        import pandas as pd

        from apps.api.session_store import SESSION_COOKIE_NAME

        db_path = REPO_ROOT.parent / "dca-cert-source.db"
        frame = pd.DataFrame(
            {"month": pd.date_range("2024-01-31", periods=14, freq="ME"),
             "cargo": [10.0 + i for i in range(14)]}
        )
        conn = sqlite3.connect(db_path)
        frame.to_sql("port_cargo", conn, if_exists="replace", index=False)
        conn.close()
        try:
            resp = client.post(
                "/v1/internal/upload/db/load",
                json={
                    "connection": {"db_type": "sqlite", "path": str(db_path)},
                    "sql": "SELECT * FROM port_cargo ORDER BY month",
                },
            )
            assert resp.status_code == 200, resp.text
            cookie = client.cookies.get(SESSION_COOKIE_NAME)
            trace = client.get("/v1/progress/trace")
            run_id = trace.json().get("run_id")
            assert run_id
            from apps.api import research_runs
            from apps.api.identity import subject_pseudonym

            run = research_runs.get_research_run_store().get_run(run_id)
            assert run is not None
            assert run.ownership == "bound"
            assert run.owner_subject == subject_pseudonym(cookie)
        finally:
            db_path.unlink(missing_ok=True)


# ── Чтение: владелец / чужой / аноним / админ ────────────────────────


class TestCertReadGate:
    def test_oc38_owner_reads_own_run_all_routes(self, client):
        run_id = _demo_run_id(client)
        assert client.get(f"/v1/progress/runs/{run_id}").status_code == 200
        assert client.get(f"/v1/progress/runs/{run_id}/report").status_code == 200
        assert (
            client.get(f"/v1/progress/runs/{run_id}/mentor/next-step").status_code
            == 200
        )
        assert client.get(f"/v1/progress/runs/{run_id}/delivery").status_code == 200

    def test_oc39_foreign_denied_uniform_404_no_leak(self, client):
        run_id = _demo_run_id(client)
        stranger = TestClient(_app())
        detail = stranger.get(f"/v1/progress/runs/{run_id}")
        unknown = stranger.get(f"/v1/progress/runs/{C.RUN_NOPE}")
        assert detail.status_code == 404
        assert unknown.status_code == 404
        assert detail.json() == unknown.json(), "uniform 404: тела совпадают"
        assert run_id not in detail.text, "run_id не дисклоужается чужому"
        assert (
            stranger.get(f"/v1/progress/runs/{run_id}/report").status_code == 404
        )
        assert (
            stranger.get(f"/v1/progress/runs/{run_id}/delivery").status_code == 404
        )
        assert (
            stranger.get(f"/v1/progress/runs/{run_id}/delivery/op-x").status_code
            == 404
        )
        assert (
            stranger.get(f"/v1/progress/runs/{run_id}/mentor/next-step").status_code
            == 404
        )

    def test_oc40_write_paths_denied_for_foreign(self, client):
        run_id = _demo_run_id(client)
        stranger = TestClient(_app())
        assert stranger.post(f"/v1/progress/runs/{run_id}/pause").status_code == 404
        assert stranger.post(f"/v1/progress/runs/{run_id}/resume").status_code == 404
        assert (
            stranger.post(
                f"/v1/progress/runs/{run_id}/checkpoints",
                json={"event_id": "dca-nope"},
            ).status_code
            == 404
        )
        assert stranger.get(f"/v1/progress/runs/{run_id}/restore").status_code == 404

    def test_oc41_anonymous_bare_request_denied(self, client):
        run_id = _demo_run_id(client)
        bare = TestClient(_app())
        assert bare.cookies.get(SESSION_COOKIE_NAME) is None
        resp = bare.get(f"/v1/progress/runs/{run_id}/report")
        assert resp.status_code == 404, (
            "знание run_id -- не право (R09): без носителя -- отказ"
        )

    def test_oc42_admin_key_reads_foreign_run(self, client, monkeypatch):
        monkeypatch.setenv("CISSTAT_API_KEYS", C.REGISTRY_LEGACY.replace(
            C.ANALYST_KEY, C.ADMIN_KEY
        ).replace("internal_analyst", "admin"))
        run_id = _demo_run_id(client)
        admin = TestClient(_app())
        resp = admin.get(
            f"/v1/progress/runs/{run_id}/report",
            headers={"X-API-Key": C.ADMIN_KEY},
        )
        assert resp.status_code == 200, resp.text

    def test_oc43_analyst_key_cannot_read_foreign_run(self, client, monkeypatch):
        """ADMIN-исключение не распространяется на не-admin ключи (мой
        дискриминационный случай: роль internal_analyst -- не admin)."""
        monkeypatch.setenv("CISSTAT_API_KEYS", C.REGISTRY_LEGACY)
        run_id = _demo_run_id(client)
        analyst = TestClient(_app())
        resp = analyst.get(
            f"/v1/progress/runs/{run_id}/report",
            headers={"X-API-Key": C.ANALYST_KEY},
        )
        assert resp.status_code == 404, (
            "не-admin ключ -- тот же отказ, что чужая сессия"
        )


# ── Legacy-континуитет и restore-наследование ────────────────────────


class TestCertLegacyAndRestore:
    def test_oc44_legacy_creator_continuity(self, client, monkeypatch):
        monkeypatch.setenv(
            "CISSTAT_API_KEYS", f"{C.ADMIN_KEY}:admin:"
        )
        client.get("/v1/session/current")
        cookie = client.cookies.get(SESSION_COOKIE_NAME)
        assert cookie
        from apps.api import research_runs
        from apps.api.research_runs import ResearchRun

        store = research_runs.get_research_run_store()
        store.upsert_run(ResearchRun(run_id=C.RUN_LEGACY, session_id=cookie))
        assert (
            client.get(f"/v1/progress/runs/{C.RUN_LEGACY}/report").status_code == 200
        ), "создавшая cookie-сессия продолжает читать легаси-запуск"
        stranger = TestClient(_app())
        assert (
            stranger.get(f"/v1/progress/runs/{C.RUN_LEGACY}/report").status_code
            == 404
        ), "чужая сессия легаси не читает"
        # ADMIN-исключение сохраняется и для легаси.
        admin = TestClient(_app())
        assert (
            admin.get(
                f"/v1/progress/runs/{C.RUN_LEGACY}/report",
                headers={"X-API-Key": C.ADMIN_KEY},
            ).status_code
            == 200
        )

    def test_oc45_restore_inherits_owner_and_fresh_session_reads(self, client):
        run_id = _demo_run_id(client)
        cookie_before = client.cookies.get(SESSION_COOKIE_NAME)
        assert cookie_before
        from apps.api.identity import subject_pseudonym

        original_owner = subject_pseudonym(cookie_before)
        restored = client.get(f"/v1/progress/runs/{run_id}/restore")
        assert restored.status_code == 200, restored.text
        new_cookie = client.cookies.get(SESSION_COOKIE_NAME)
        assert new_cookie and new_cookie != cookie_before, (
            "restore выдаёт НОВЫЙ cookie"
        )
        from apps.api import research_runs
        from apps.api.session_store import get_session_store

        run = research_runs.get_research_run_store().get_run(run_id)
        assert run is not None
        assert run.owner_subject == original_owner, (
            "владелец run НЕ переписывается на новый носитель (континуитет)"
        )
        new_session = get_session_store().get(new_cookie)
        assert new_session is not None
        assert new_session.owner_subject == run.owner_subject, (
            "НАСЛЕДОВАНИЕ: новая сессия несёт субъекта владельца запуска"
        )
        assert client.get(f"/v1/progress/runs/{run_id}/report").status_code == 200, (
            "наследовавший сеанс продолжает читать"
        )
        stranger = TestClient(_app())
        assert stranger.get(f"/v1/progress/runs/{run_id}/restore").status_code == 404

    def test_oc46_write_action_recorded_not_read(self, client, monkeypatch):
        """Контракт §4.2: write-действия проходят ту же таблицу с
        action="write" (факт решения -- серверному аудиту)."""
        run_id = _demo_run_id(client)
        import apps.api.routers.progress as progress_module

        captured: list[str] = []
        real = progress_module.authorize_run_access

        def _spy(run, subject, **kwargs):
            captured.append(kwargs.get("action", ""))
            return real(run, subject, **kwargs)

        monkeypatch.setattr(progress_module, "authorize_run_access", _spy)
        stranger = TestClient(_app())
        stranger.post(f"/v1/progress/runs/{run_id}/pause")
        stranger.get(f"/v1/progress/runs/{run_id}/restore")
        stranger.get(f"/v1/progress/runs/{run_id}")  # read-путь для контраста
        assert captured[:2] == ["write", "write"], (
            "pause/restore -- action=write в AccessDecision"
        )
        assert captured[2] == "read"


# ── Гвард зеркала слоя 2 (T2, эшелонирование) ────────────────────────


class TestCertMirrorGuard:
    def test_oc47_foreign_mirror_skipped_same_creator_allowed(self):
        """Двусторонний оракул: чужой субъект не пишет в bound-run;
        ТА ЖЕ создавшая сессия пишет свободно (легитимный путь жив)."""
        from apps.api import research_runs
        from apps.api.research_runs import record_run_event
        from apps.api.session_store import AnalysisSession
        from apps.api.trace_events import make_trace_event

        store = research_runs.get_research_run_store()
        store.upsert_run(_bound_run(C.RUN_GUARD, C.SUBJ_OWNER))
        event = make_trace_event(
            "validation_check_status",
            stage="validation",
            node_id="data_types",
            run_id=C.RUN_GUARD,
        )
        # Чужая сессия (свой субъект) -- зеркало отклонено.
        foreign_session = AnalysisSession(session_id=C.MATERIAL_COOKIE_B)
        foreign_session.run_id = C.RUN_GUARD
        foreign_session.ensure_owner_binding()
        record_run_event(foreign_session, event)
        assert len(store.list_events(C.RUN_GUARD)) == 0, (
            "чужое зеркало не пишет в bound-запуск"
        )
        # Та же создавшая сессия (creator continuity) -- зеркало пишется.
        creator_session = AnalysisSession(session_id=C.SESSION_CREATOR)
        creator_session.run_id = C.RUN_GUARD
        creator_session.ensure_owner_binding()
        record_run_event(creator_session, event)
        assert len(store.list_events(C.RUN_GUARD)) == 1, (
            "легитимное зеркало создавшей сессии работает"
        )

    def test_oc48_legacy_mirror_still_relinks(self):
        """Легаси-run (без полей) -- прежняя перелинковка §5 не сломана
        (гвард только для bound)."""
        from apps.api import research_runs
        from apps.api.research_runs import record_run_event
        from apps.api.research_runs import ResearchRun
        from apps.api.session_store import AnalysisSession
        from apps.api.trace_events import make_trace_event

        store = research_runs.get_research_run_store()
        store.upsert_run(ResearchRun(run_id=C.RUN_LEGACY, session_id="dca-old-sess"))
        session = AnalysisSession(session_id=C.MATERIAL_COOKIE_A)
        session.run_id = C.RUN_LEGACY
        event = make_trace_event(
            "upload_completed",
            stage="upload",
            node_id="overview",
            run_id=C.RUN_LEGACY,
        )
        record_run_event(session, event)
        reread = store.get_run(C.RUN_LEGACY)
        assert reread is not None
        assert reread.session_id == C.MATERIAL_COOKIE_A, (
            "легаси: перелинковка «последний известный» работает"
        )
        assert len(store.list_events(C.RUN_LEGACY)) == 1


# ── /health/ops identity-блок (T6) ───────────────────────────────────


class TestCertOpsIdentity:
    def test_oc49_ops_identity_honest_and_secret_free(self, client):
        resp = client.get("/health/ops")
        assert resp.status_code == 200
        identity = resp.json().get("identity")
        assert isinstance(identity, dict)
        assert identity["mode"] == "session_scoped"
        assert identity["run_ownership_enforcement"] == "owner_bound"
        assert identity["default_tenant"] == C.TENANT_DEFAULT
        assert identity["api_key_registry_configured"] is False
        assert C.ADMIN_KEY not in resp.text

    def test_oc50_ops_identity_registry_configured_flag(self, client, monkeypatch):
        monkeypatch.setenv("CISSTAT_API_KEYS", C.REGISTRY_EXTENDED)
        resp = client.get("/health/ops")
        identity = resp.json()["identity"]
        assert identity["api_key_registry_configured"] is True
        assert C.ADMIN_KEY not in resp.text, "bool без значения (T6)"
        assert C.REGISTRY_EXTENDED not in resp.text

    def test_oc51_ops_identity_dev_mode_labelled(self, client, monkeypatch):
        monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "dev_single_user")
        resp = client.get("/health/ops")
        assert resp.json()["identity"]["mode"] == "dev_single_user"

    def test_oc52_ops_identity_unknown_mode_fail_closed(self, client, monkeypatch):
        monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "dca-yolo")
        resp = client.get("/health/ops")
        assert resp.json()["identity"]["mode"] == "session_scoped"
