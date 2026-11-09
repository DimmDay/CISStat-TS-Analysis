# tests/api/test_auth07_admin_sessions.py
"""AUTH-07 «Общая админка обеих оболочек» (spec_auth_architecture.md,
строка 196): миграция key-only admin-эндпоинтов на named-сессии со
свежим MFA.

Контракт задачи:

  1. Оракул дословно: «Named ADMIN+MFA управляет реальными API
     standalone/embedded; analyst/OWNER получают отказ». Named-сессия
     (auth_session) с platform_role=admin и верифицированным MFA
     проходит /v1/progress/admin/* и /v1/logs/*; internal_analyst и
     external_user (даже OWNER аккаунта) -- 403.
  2. auth.py (долг AUTH-03/07): «AUTH-07 owns migration of key-only
     admin endpoints to named sessions with fresh MFA». Сессия админа
     БЕЗ MFA-подтверждения -- 403 mfa_required (defense in depth:
     sessions._load уже принуждает MFA для admin, гвард проверяет
     проекцию контекста явно).
  3. Программный канал сохраняется: API-ключ администратора продолжает
     работать (прекращение ENV-ключей -- AUTH-10, миграционный план
     спеки; test_admin_progress_api.py остаётся зелёным).
  4. Session-суррогат research-cookie (session_scoped) и аноним --
     401 authentication_required: research-сессия не есть вход в
     платформу (AUTH-03/04).
  5. Logs-роутер (§15.1 «ADMIN-проверка сохраняется; scopes и support
     grants сужают область»): named-сессия допускается тем же
     resolve-путём; не-админ без scopes/grants -- 403 на потоках.

Фейковый verifier/store ставятся через app.state
(auth_credential_verifier / auth_access_store) -- это ЗАМЕРШЕННЫЕ
адаптеры контекста AUTH-03 (context._resolve_context); Postgres не
нужен. FakeVerifier.api_key делегирует реальному LegacyCredentialVerifier
(тот же паттерн, что SessionCredentialVerifier.api_key), чтобы
программный канал в тесте шёл настоящим кодом. Cookie/токен-граница
AUTH-04 покрыта собственными suites и здесь не дублируется.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from apps.api.authentication.context import VerifiedCredential
from apps.api.main import app

ADMIN_COOKIE = "__Host-cisstat_auth"
NOW = datetime.now(timezone.utc)

ADMIN_ID = str(uuid4())
ANALYST_ID = str(uuid4())
OWNER_ID = str(uuid4())
ACCOUNT_ID = str(uuid4())

# subject_id -> (platform_role, membership account_role)
ROLE_MAP = {
    ADMIN_ID: ("admin", "member"),
    ANALYST_ID: ("internal_analyst", "member"),
    OWNER_ID: ("external_user", "owner"),
}


def _evidence(subject_id: str, *, mfa: bool, scopes=()) -> VerifiedCredential:
    return VerifiedCredential(
        subject_id=subject_id,
        credential_id=str(uuid4()),
        auth_method="auth_session",
        account_id=ACCOUNT_ID,
        scopes=frozenset(scopes),
        auth_session_id=str(uuid4()),
        auth_time=NOW,
        mfa_verified_at=NOW if mfa else None,
    )


class _Tx:
    def __init__(self, roles):
        self._roles = roles
        # AUTH-15 resolver checks for optional demo authority in the same tx.
        self.connection = SimpleNamespace(execute=lambda *a, **kw: SimpleNamespace(fetchone=lambda: {"present": None}))
        self.identities = SimpleNamespace(get=self._identity)
        self.accounts = SimpleNamespace(
            get=self._account,
            memberships=self._memberships,
        )

    def _identity(self, subject_id):
        role = self._roles.get(str(subject_id), ("admin", "member"))[0]
        return SimpleNamespace(
            subject_id=subject_id,
            status="active",
            platform_role=role,
            subject_version=1,
            kind="person",
        )

    def _account(self, _account_id):
        return SimpleNamespace(
            account_id=_account_id,
            status="active",
            plan="starter",
            tenant_id="tenant-auth07",
            entitlement_version=1,
            account_type="multi",
            plan_expires_at=None,
        )

    def _memberships(self, _account_id):
        return [
            SimpleNamespace(
                subject_id=subject_id,
                status="active",
                account_role=self._roles.get(str(subject_id), ("", "member"))[1],
            )
            for subject_id in self._roles
        ]


class FakeStore:
    """PostgresAccessStore-подобный адаптер для resolve_verified_context."""

    def __init__(self, roles=ROLE_MAP):
        self._roles = roles

    @contextmanager
    def transaction(self, readonly=False):
        yield _Tx(self._roles)


class FakeVerifier:
    """SessionCredentialVerifier-подобный: cookie -> VerifiedCredential.

    Значение cookie == subject_id тестового субъекта (маркер); MFA-флаг
    задаётся при создании evidence. api_key делегируется реальному
    legacy-верификатору (программный канал идёт НАСТОЯЩИМ кодом).
    """

    def __init__(self, subjects: dict[str, VerifiedCredential]):
        self._subjects = subjects

    def session(self, request):
        token = request.cookies.get(ADMIN_COOKIE)
        if not token:
            return None
        return self._subjects.get(token)

    def api_key(self, key):
        from apps.api.authentication.legacy import LegacyCredentialVerifier

        return LegacyCredentialVerifier().api_key(key)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Изоляция + подмена AUTH-адаптеров через app.state (снятие в конце)."""
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.setenv("CISSTAT_IDENTITY_MODE", "session_scoped")
    monkeypatch.setenv("CISSTAT_API_KEYS", "admin-key-000:admin:")

    subjects = {
        ADMIN_ID: _evidence(ADMIN_ID, mfa=True, scopes=("logs.read", "audit.read", "logs.export")),
        # admin-сессия без MFA-подтверждения (маркер-токен != subject_id)
        "admin-nomfa": _evidence(ADMIN_ID, mfa=False),
        ANALYST_ID: _evidence(ANALYST_ID, mfa=True, scopes=()),
        OWNER_ID: _evidence(OWNER_ID, mfa=True, scopes=()),
    }
    app.state.auth_credential_verifier = FakeVerifier(subjects)
    app.state.auth_access_store = FakeStore()

    from apps.api import research_runs, session_store

    research_runs.reset_research_run_store_for_testing()
    session_store.reset_session_store_for_testing()
    with TestClient(app) as c:
        yield c
    for name in ("auth_credential_verifier", "auth_access_store"):
        if hasattr(app.state, name):
            delattr(app.state, name)
    research_runs.reset_research_run_store_for_testing()
    session_store.reset_session_store_for_testing()


def _auth(client, token: str):
    client.cookies.set(ADMIN_COOKIE, token)


# ── Позитив: named ADMIN+MFA управляет реальными API ─────────────────


def test_named_admin_session_with_mfa_reads_progress_admin(client):
    _auth(client, ADMIN_ID)
    r = client.get("/v1/progress/admin/overview?days=30&top=10")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["runs_total_all_time"] == 0  # пустой корпус -- честные нули
    assert body["period_days"] == 30


def test_named_admin_session_reads_case_bank(client):
    _auth(client, ADMIN_ID)
    r = client.get("/v1/progress/admin/case-bank/candidates")
    assert r.status_code == 200, r.text
    assert r.json()["candidates"] == []


def test_named_admin_session_reads_logs_access_and_telemetry(client):
    _auth(client, ADMIN_ID)
    access = client.get("/v1/logs/access")
    assert access.status_code == 200, access.text
    body = access.json()
    assert body["principal"]["role"] == "admin"
    assert body["access"]["telemetry"] is True
    telemetry = client.get("/v1/logs/telemetry?limit=10")
    assert telemetry.status_code == 200, telemetry.text


# ── Негатив: без MFA, analyst, OWNER-аккаунта, суррогат, аноним ───────


def test_admin_session_without_mfa_is_403_mfa_required(client):
    _auth(client, "admin-nomfa")
    r = client.get("/v1/progress/admin/overview")
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "mfa_required"


def test_named_analyst_session_is_403_on_progress_admin(client):
    _auth(client, ANALYST_ID)
    r = client.get("/v1/progress/admin/overview")
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "admin_role_required"


def test_named_analyst_session_is_denied_on_log_streams(client):
    _auth(client, ANALYST_ID)
    access = client.get("/v1/logs/access")
    assert access.status_code == 200  # справка о собственном доступе
    assert access.json()["access"]["telemetry"] is False
    r = client.get("/v1/logs/telemetry")
    assert r.status_code == 403, r.text


def test_account_owner_without_admin_role_is_403(client):
    # OWNER аккаунта -- НЕ платформенный админ (spec §3/§4: OWNER не ADMIN).
    _auth(client, OWNER_ID)
    r = client.get("/v1/progress/admin/overview")
    assert r.status_code == 403, r.text
    assert r.json()["detail"]["code"] == "admin_role_required"


def test_research_cookie_surrogate_is_401_on_admin(client):
    from apps.api import session_store

    pointer = "auth07-surrogate"
    session_store.get_session_store().get_or_create(pointer)
    client.cookies.set(session_store.SESSION_COOKIE_NAME, pointer)
    r = client.get("/v1/progress/admin/overview")
    assert r.status_code == 401, r.text


def test_anonymous_admin_route_is_401(client):
    assert client.get("/v1/progress/admin/overview").status_code == 401
    assert client.get("/v1/logs/telemetry").status_code == 401


# ── Программный канал: API-ключ сохраняется (до AUTH-10) ──────────────


def test_admin_api_key_path_unchanged(client):
    r = client.get("/v1/progress/admin/overview", headers={"X-API-Key": "admin-key-000"})
    assert r.status_code == 200, r.text
    denied = client.get("/v1/progress/admin/overview", headers={"X-API-Key": "user-key-0001"})
    assert denied.status_code == 401  # неизвестный ключ -- 401, как раньше


def test_ambiguous_key_plus_foreign_session_rejected(client):
    # Ключ + чужая named-сессия -- ambiguous (AUTH-03 контракт сохранён).
    client.cookies.set(ADMIN_COOKIE, ANALYST_ID)
    r = client.get(
        "/v1/progress/admin/overview",
        headers={"X-API-Key": "admin-key-000"},
    )
    assert r.status_code in (400, 401), r.text
