"""AUTH-03 smoke on actual mounted API handlers and existing object policy."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from apps.api.main import app
from apps.api import research_runs, session_store
from apps.api.research_runs import ResearchRun

KEY = "auth03-live-model-key-sentinel"
OWNER = "subj-1030103010301030"


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    for name in ("DATABASE_URL", "REDIS_URL", "CISSTAT_AUTH_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "session_scoped")
    monkeypatch.setenv(
        "CISSTAT_API_KEYS", f"{KEY}:admin::{OWNER}:tenant-auth03:logs.read+audit.read"
    )
    research_runs.reset_research_run_store_for_testing()
    session_store.reset_session_store_for_testing()
    with TestClient(app) as c:
        yield c
    research_runs.reset_research_run_store_for_testing()
    session_store.reset_session_store_for_testing()


def test_actual_models_train_never_echoes_api_secret(client):
    r = client.post("/v1/models/train", headers={"X-API-Key": KEY})
    assert r.status_code == 200, r.text
    assert r.json()["principal_id"] == OWNER
    assert KEY not in r.text


def test_missing_key_in_actual_public_and_admin_routes_is_401(client):
    assert client.get("/v1/public/rules/templates").status_code == 401
    assert client.get("/v1/progress/admin/overview").status_code == 401
    assert client.get("/v1/logs/access").status_code == 401


def test_invalid_key_blocks_cookie_on_actual_run_route(client):
    sid = "auth03-live-pointer"
    session = session_store.get_session_store().get_or_create(sid)
    session.owner_subject = OWNER
    session.tenant_id = "tenant-auth03"
    client.cookies.set(session_store.SESSION_COOKIE_NAME, sid)
    research_runs.get_research_run_store().upsert_run(
        ResearchRun(
            run_id="RUN-AUTH0301",
            session_id=sid,
            owner_subject=OWNER,
            tenant_id="tenant-auth03",
            ownership="bound",
        )
    )
    r = client.get("/v1/progress/runs/RUN-AUTH0301", headers={"X-API-Key": "invalid"})
    absent = client.get(
        "/v1/progress/runs/RUN-AUTH0302", headers={"X-API-Key": "invalid"}
    )
    assert absent.status_code == r.status_code == 401
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["code"] == "invalid_credential"


def test_existing_foreign_and_absent_run_stay_uniform_404(client):
    store = research_runs.get_research_run_store()
    run = ResearchRun(
        run_id="RUN-AUTH0301",
        session_id="other-session",
        owner_subject="subj-eeeeeeeeeeeeeeee",
        tenant_id="tenant-auth03",
        ownership="bound",
    )
    store.upsert_run(run)
    a = client.get("/v1/progress/runs/RUN-AUTH0301")
    b = client.get("/v1/progress/runs/RUN-AUTH0302")
    assert a.status_code == b.status_code == 404
    assert a.json()["detail"] == b.json()["detail"]
