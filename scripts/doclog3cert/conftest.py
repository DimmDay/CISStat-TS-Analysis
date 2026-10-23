# scripts/doclog3cert/conftest.py
"""DOCLOG-3-CERT: изоляция оракульного корпуса сертификации.

Корпус ДИЗЪЮНКТЕН repo-корпусу и корпусам прошлых сертификаций
(DOCLOG-0-CERT: RUN-DCAC0Axx/dca-*; DOCLOG-1-CERT: RUN-D1C*/d1cert-*;
DOCLOG-2-CERT: RUN-D2C*/d2cert-*; repo: RUN-D0/D1/D2/D3*, d3-*):
- запуски RUN-D3CERT11/RUN-D3CERT22/... (валидная форма RUN-XXXXXXXX);
- cookie-сессии d3cert-sess-*;
- админ-ключ d3cert-admin-key-*;
- соль псевдонимизации d3cert-salt-*;
- сентинелы AC10 -- собственные значения (truffle-swine-77-d3cert,
  mysql://...pivot-goose-88..., AKIA-D3CERT-IO-777-QQ, ...);
- имена событий d3cert.*; request-id d3certreq-*; traceparent-хексы свои.

Каждый тест: свой tmp_path/CISSTAT_DATA_DIR, сброс singleton-фабрик
(runs/dataset/session/telemetry/audit), удаление env-переменных контура.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# ── Дизъюнктный корпус сертификации (только здесь) ───────────────────

RUN_ID_OWNER = "RUN-D3CERT11"
RUN_ID_FOREIGN = "RUN-D3CERT22"
RUN_ID_MISSING = "RUN-D3CERT99"
SESSION_ID_OWNER = "d3cert-sess-owner-01"
SESSION_ID_FOREIGN = "d3cert-sess-foreign-01"
ADMIN_KEY = "d3cert-admin-key-a1b2c3"
IDENTITY_SALT = "d3cert-salt-oct2026-alpha"

# Сентинелы AC10 (свои; НЕ пересекаются с repo: hunter2-sentinel-d3 и пр.)
SENTINEL_PASSWORD = "truffle-swine-77-d3cert"
SENTINEL_DSN = (
    "mysql://svc-d3cert:pivot-goose-88@db.d3cert.internal:3307/warehouse"
)
SENTINEL_BEARER = "Bearer d3cert.jwt.payload.sig.999"
SENTINEL_KEY = "AKIA-D3CERT-IO-777-QQ"
SENTINEL_COOKIE = "d3cert-cookie-open-sesame-4242"
SENTINEL_SIGNED_URL = (
    "https://cdn.d3cert.example/obj/report.pdf?X-Sig=cafebabe777&X-Expires=999"
)
SENTINEL_URLENCODED = "page=1&password%3Dhornet-nest-55"
SENTINEL_MULTILINE = "line-A-d3cert\nBearer abcd1234efghJK\nline-C"
SENTINEL_SESSION = "d3cert-plain-session-31337"
SENTINEL_CRLF = "name=d3cert\r\nX-Injected-Header: yes\r\n"
SENTINEL_SQL = "SELECT password FROM analysts WHERE name='d3cert'"

EVENT_ALPHA = "d3cert.event.alpha"
EVENT_BETA = "d3cert.event.beta"
EVENT_GAMMA = "d3cert.event.gamma"
REQUEST_ID_1 = "d3certreq-0001"
REQUEST_ID_2 = "d3certreq-0002"
TRACEPARENT_OK = (
    "00-1a2b3c4d5e6f77889900112233445566-0af1b2c3d4e5f607-01"
)
TRACE_ID_OK = "1a2b3c4d5e6f77889900112233445566"
SPAN_ID_OK = "0af1b2c3d4e5f607"


@pytest.fixture(autouse=True)
def _isolated_cert_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_SALT", raising=False)
    monkeypatch.delenv("CISSTAT_TELEMETRY_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_AUDIT_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_TELEMETRY_DEBUG", raising=False)
    monkeypatch.delenv("CISSTAT_TELEMETRY_SAMPLE_RATE", raising=False)
    monkeypatch.delenv("CISSTAT_STORAGE_MODE", raising=False)
    monkeypatch.setenv("CISSTAT_IDENTITY_SALT", IDENTITY_SALT)

    from apps.api import research_runs, security_audit, telemetry
    from apps.api.session_store import reset_session_store_for_testing

    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    telemetry.reset_telemetry_for_testing()
    security_audit.reset_audit_for_testing()
    reset_session_store_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    telemetry.reset_telemetry_for_testing()
    security_audit.reset_audit_for_testing()
    reset_session_store_for_testing()


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client
