# scripts/doclog2cert/test_doclog2cert_oracle_api.py
# DOCLOG-2-CERT: API-оракулы сертификатора (TestClient; реальный
# owner-binding через POST /v1/session/demo, uniform-отказы, /health/ops,
# маршрутный контур DOCLOG-0 на run-читалках рядом со снимками).
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import (
    ADMIN_KEY, CTX_ALPHA, REV_ALPHA, RUN_FOREIGN, RUN_ID, RUN_MISSING,
    SESSION_B, SESSION_FOREIGN, SESSION_ID, UNIFORM_DENIAL_TEXT,
    admin_subject, append_event, foreign_subject, make_artifact,
    owner_subject, seed_bound_run, seed_session, section, service,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def client(orc_env):
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


def _demo_owner_session(client: TestClient) -> str:
    """Сессия-владелец через РЕАЛЬНЫЙ HTTP-маршрут демо (owner-binding
    DOCLOG-0 first-write-wins на сервере)."""
    resp = client.post("/v1/session/demo")
    assert resp.status_code == 200, resp.text
    return client.cookies.get("cisstat_session") or _any_cookie(client)


def _any_cookie(client: TestClient) -> str:
    for name, value in client.cookies.items():
        if "session" in name:
            return value
    raise AssertionError("session cookie не установлен демо-маршрутом")


class TestOrcApiOwnerFlow:
    def test_demo_session_owner_builds_and_reads(self, client):
        """Полный маршрут владельца: HTTP-демо -> owner_subject серверной
        записи -> bound run -> сборка/чтение снимка."""
        session_id = _demo_owner_session(client)
        from apps.api.session_store import get_session_store

        session = get_session_store().get(session_id)
        assert session is not None
        assert session.owner_subject

        from apps.api.research_runs import ResearchRun, get_research_run_store
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        run = ResearchRun(
            run_id=RUN_ID, session_id=session_id,
            dataset_fingerprint="d2c" * 16, dataset_name="api-d2c",
            target_column=session.target_column or "value",
            created_at=now, last_active_at=now, status="active",
            context_id="ctx-d2c-api", data_revision=2,
            owner_subject=session.owner_subject,
            tenant_id=session.tenant_id, ownership="bound",
        )
        get_research_run_store().upsert_run(run)

        svc = service()
        snapshot, created = svc.build_snapshot(
            RUN_ID, owner_subject(session_id), session_id=session_id,
            kinds=["D01", "D02"],
        )
        assert created is True
        assert snapshot.approval is None
        got = svc.get_snapshot(snapshot.snapshot_id,
                               owner_subject(session_id),
                               session_id=session_id)
        assert got.snapshot_id == snapshot.snapshot_id
        # D01: цель из run metadata (event-факт может отсутствовать)
        d01 = section(got, "D01")
        assert any("Целевая переменная" in c["text"] for c in d01["claims"])

    def test_foreign_cookie_cannot_read_others_snapshot(self, client):
        seed_session()
        seed_bound_run()
        svc = service()
        snapshot, _ = svc.build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        from apps.api.snapshot_builder import SnapshotAccessDenied

        with pytest.raises(SnapshotAccessDenied):
            svc.get_snapshot(snapshot.snapshot_id, foreign_subject(),
                             session_id=SESSION_FOREIGN)

    def test_admin_key_on_foreign_run_allowed(self, client, monkeypatch):
        seed_session(SESSION_B, target="alt")
        seed_bound_run(RUN_ID, SESSION_B, context_id="ctx-d2c-b",
                       data_revision=1, target="alt")
        monkeypatch.setenv("CISSTAT_API_KEYS", f"{ADMIN_KEY}:admin:pro")
        snapshot, created = service().build_snapshot(
            RUN_ID, admin_subject(), session_id="", kinds=["D02"]
        )
        assert created is True
        assert snapshot.research_run_id == RUN_ID


class TestOrcApiUniformDenial:
    def test_run_routes_uniform_404_unchanged(self, client):
        """Смежный контракт DOCLOG-0 не сломан поставкой снимков:
        отсутствующий и чужой run на run-маршрутах -- одинаковый 404."""
        seed_session(SESSION_FOREIGN)
        seed_bound_run(RUN_FOREIGN, SESSION_FOREIGN)
        # чужой (cookie другой сессии)
        resp_foreign = client.get(f"/v1/progress/runs/{RUN_FOREIGN}")
        # отсутствующий
        resp_missing = client.get(f"/v1/progress/runs/{RUN_MISSING}")
        assert resp_foreign.status_code == resp_missing.status_code == 404
        assert resp_foreign.json()["detail"] == \
            resp_missing.json()["detail"] == "Запуск не найден"

    def test_snapshot_denial_message_uniform_with_run_denial(self, client):
        """Текст отказа снимка -- uniform и не дисклоужает существование;
        семантика паритета с run-маршрутами (без run_id в тексте)."""
        from apps.api.snapshot_builder import SnapshotAccessDenied

        seed_session()
        with pytest.raises(SnapshotAccessDenied) as ei:
            service().build_snapshot(
                RUN_MISSING, owner_subject(), session_id=SESSION_ID,
                kinds=["D02"],
            )
        assert RUN_MISSING not in str(ei.value)
        assert str(ei.value) == UNIFORM_DENIAL_TEXT


class TestOrcApiHealth:
    def test_ops_health_snapshots_block(self, client):
        body = client.get("/health/ops").json()
        snap = body["snapshots"]            # верхний уровень контракта
        assert isinstance(snap, dict)
        assert snap["registry_backend"] in {
            "not_initialized", "memory", "postgres",
        }
        assert snap["object_store"] == "local_fs"
        assert isinstance(snap["data_root_configured"], bool)
        # T6/T10: ни путей, ни DSN в diagnostics
        raw = json.dumps(snap, ensure_ascii=False)
        assert "/" not in snap.get("object_store", "")
        assert "postgresql" not in raw.lower()
        assert "d2c-data" not in raw

    def test_health_ok_with_snapshot_contour_initialized(self, client):
        seed_session()
        seed_bound_run()
        snapshot, _ = service().build_snapshot(
            RUN_ID, owner_subject(), session_id=SESSION_ID, kinds=["D02"]
        )
        body = client.get("/health").json()
        assert body.get("status") in {"ok", "degraded"}  # среда Memory


class TestOrcApiNoScienceMutation:
    def test_demo_then_build_then_read_leaves_dataset_intact(self, client):
        """AC05-трипваер на живом HTTP-контуре: /current до и после
        сборки/чтения снимка -- байт-равный science-вид."""
        session_id = _demo_owner_session(client)
        from apps.api.research_runs import ResearchRun, get_research_run_store
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        get_research_run_store().upsert_run(ResearchRun(
            run_id=RUN_ID, session_id=session_id,
            dataset_fingerprint="d2c" * 16, dataset_name="api-d2c",
            target_column="value", created_at=now, last_active_at=now,
            status="active", context_id="ctx-d2c-api", data_revision=1,
            owner_subject=owner_subject(session_id).subject_id,
            ownership="bound",
        ))
        before = client.get("/v1/session/current").json()
        svc = service()
        snapshot, _ = svc.build_snapshot(
            RUN_ID, owner_subject(session_id), session_id=session_id,
            kinds=["D02", "D08"],
        )
        svc.get_snapshot(snapshot.snapshot_id, owner_subject(session_id),
                         session_id=session_id)
        svc.list_snapshots(RUN_ID, owner_subject(session_id),
                           session_id=session_id)
        after = client.get("/v1/session/current").json()
        # наука не тронута: датасет/этапы/паспорты равны
        assert after["dataset"] == before["dataset"]
        assert after["stages"] == before["stages"]
        assert len(after.get("passport_history", [])) == \
            len(before.get("passport_history", []))
