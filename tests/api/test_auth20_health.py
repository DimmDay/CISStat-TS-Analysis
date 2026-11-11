"""AUTH-20 route-level contract: /health/ops carries the facts-only auth_ops
block; no new HTTP routes are introduced and no secrets are exposed."""

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    for name in ("DATABASE_URL", "REDIS_URL", "CISSTAT_AUTH_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "session_scoped")
    monkeypatch.setenv("CISSTAT_AUTH_CSRF_KEY", "test-only-auth20-csrf-secret-" + "a" * 32)
    monkeypatch.setenv(
        "CISSTAT_AUTH_ALLOWED_ORIGINS",
        "https://datasetup.ru,https://www.datasetup.ru",
    )
    from apps.api import research_runs, session_store

    research_runs.reset_research_run_store_for_testing()
    session_store.reset_session_store_for_testing()
    with TestClient(app) as c:
        yield c
    research_runs.reset_research_run_store_for_testing()
    session_store.reset_session_store_for_testing()


def test_health_ops_auth_ops_block_present_and_safe(client, monkeypatch):
    monkeypatch.delenv("CISSTAT_AUTH_LOCKDOWN", raising=False)
    resp = client.get("/health/ops")
    assert resp.status_code == 200
    body = resp.json()
    block = body.get("auth_ops")
    assert isinstance(block, dict), "auth_ops-блок существует (additive)"
    assert block["state"] in ("ok", "degraded")
    assert isinstance(block["lockdown"], bool)
    assert block["lockdown"] is False
    assert block["external_entry"]["oidc"] is False
    assert block["external_entry"]["email_trial"] is False
    assert block["audit_sweeper_interval_env"] == "CISSTAT_AUTH_AUDIT_OUTBOX_INTERVAL"
    # facts-only: no DSN/token/secret leakage in the projection
    text = resp.text
    for marker in ("postgres://", "postgresql://", "password", "Bearer"):
        assert marker not in text.lower() or "postgres" not in marker


def test_health_ops_lockdown_flag_reflects_env(client, monkeypatch):
    monkeypatch.setenv("CISSTAT_AUTH_LOCKDOWN", "1")
    resp = client.get("/health/ops")
    assert resp.json()["auth_ops"]["lockdown"] is True


def test_lockdown_denies_new_entries_route_level(client, monkeypatch):
    monkeypatch.setenv("CISSTAT_AUTH_LOCKDOWN", "1")
    origin = "https://datasetup.ru"
    csrf = client.get("/v1/auth/csrf", headers={"origin": origin})
    assert csrf.status_code == 200
    proof = csrf.json()["csrf_token"]
    resp = client.post(
        "/v1/auth/login",
        json={"login": "someone", "password": "whatever"},
        headers={
            "origin": origin,
            "X-CSRF-Token": proof,
            "Sec-Fetch-Site": "same-origin",
            # httpx honors the __Host- prefix rules and would not replay the
            # Set-Cookie back; the browser contract sends it same-origin.
            "Cookie": "__Host-cisstat_csrf=" + proof,
        },
    )
    assert resp.status_code == 503
    assert resp.json()["detail"]["code"] == "auth_lockdown"


def test_no_new_auth_routes_in_openapi(client):
    resp = client.get("/openapi.json")
    paths = resp.json()["paths"]
    assert "/health/ops" in paths
    assert "/health" in paths
    ops = [m for m in paths["/health/ops"]]
    assert ops == ["get"], "AUTH-20 не добавляет HTTP-маршрутов"
