# tests/api/test_doclog7_logs_support.py
"""Task DOCLOG-7 (spec_documentation_logging.md §14.2, §15, §15.1, §19
строка DOCLOG-7, §20 AC10/AC11/AC17): журналы и поддержка.

Критерий завершения (§19): «нет данных/секретов вне grant, все действия
учитываются».

Поверхность:
  * чтение durable-журналов по whitelist-фильтрам (БЕЗ произвольного
    SQL/regex от браузера, §14.2): технические события (telemetry,
    migration 0009), аудит доступа (security_audit, 0009), доставка и
    документы (documents/jobs, 0010) -- cursor pagination, временной
    cutoff, лимиты, честный retention horizon (§16.1: 30/365 дней);
  * просмотр/экспорт журнала сам учитывается (audit_log_accessed,
    §14.2) без бесконечной рекурсии;
  * support grants (§14.2/§15): ticket/purpose, ограничение по
    run/tenant/времени (TTL <= 168h), scopes-whitelist
    {logs.read, audit.read, logs.export}, создание/отзыв -- mandatory
    audit fail-closed (§14.1: «создание/изменение прав и support
    grants»), grant_created/grant_revoked из каталога DOCLOG-3;
  * диагностический пакет (§14.2): redacted JSONL + manifest, версии
    сервисов и ops status, НИКОГДА env values/DSN/API-key/cookies/данные
    (AC10/AC19); детерминированный ZIP (урок DOCLOG-5);
  * авторизация (§15.1): ADMIN-проверка сохраняется; grants сужают
    область -- данные вне grant недостижимы (запрос вне grant -- 403,
    без фильтра -- честное сужение с раскрытием в meta).

Оракулы на СВОИХ данных: корпус дизъюнктен repo-корпусам 0..6
(RUN-D7xxxxxx, d7-*, tenant-d7*, subj-d7*); изоляция каждого теста --
паттерн test_doclog6_approvals_archive.py (свой tmp_path/CISSTAT_DATA_DIR,
сброс singleton-фабрик, memory-бекенды по умолчанию).
"""
from __future__ import annotations

import base64
import io
import json
import os
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api import research_runs
from apps.api.identity import SubjectRef
from apps.api.session_store import AnalysisSession

# ── Изоляция КАЖДОГО теста (паттерн test_doclog6_approvals_archive) ───

API_KEYS_ENV = (
    "d7-admin-key-1111:admin::subj-d7aaaaaaaaaaaaaa:tenant-d7core:,"
    "d7-support-key-2222:external_user:starter:subj-d7bbbbbbbbbbbbbb:tenant-d7support:,"
    "d7-other-key-3333:external_user:starter:subj-d7cccccccccccccc:tenant-d7other:"
)

ADMIN_KEY = "d7-admin-key-1111"
SUPPORT_KEY = "d7-support-key-2222"
OTHER_KEY = "d7-other-key-3333"
ADMIN_SUBJECT = "subj-d7aaaaaaaaaaaaaa"
SUPPORT_SUBJECT = "subj-d7bbbbbbbbbbbbbb"

TENANT_CORE = "tenant-d7core"
TENANT_OTHER = "tenant-d7other"
RUN_A = "RUN-D7A00001"
RUN_B = "RUN-D7B00002"


@pytest.fixture(autouse=True)
def _isolated_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CISSTAT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_RUNS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_MODE", raising=False)
    monkeypatch.delenv("CISSTAT_API_KEYS", raising=False)
    monkeypatch.delenv("CISSTAT_IDENTITY_SALT", raising=False)
    monkeypatch.delenv("CISSTAT_TELEMETRY_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_AUDIT_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_DOCUMENTS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_GRANTS_BACKEND", raising=False)
    monkeypatch.delenv("CISSTAT_D7_SECRET_SENTINEL", raising=False)
    monkeypatch.setenv("CISSTAT_API_KEYS", API_KEYS_ENV)
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    from apps.api import admin_logs, document_jobs
    from apps.api.routers import logs as logs_router
    from apps.api.security_audit import reset_audit_for_testing
    from apps.api.session_store import reset_session_store_for_testing
    from apps.api.telemetry import reset_telemetry_for_testing

    document_jobs.reset_document_registry_for_testing()
    admin_logs.reset_support_grant_registry_for_testing()
    logs_router.reset_logs_service_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()
    yield
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    document_jobs.reset_document_registry_for_testing()
    admin_logs.reset_support_grant_registry_for_testing()
    logs_router.reset_logs_service_for_testing()
    reset_session_store_for_testing()
    reset_audit_for_testing()
    reset_telemetry_for_testing()


@pytest.fixture()
def client():
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def admin_client(client: TestClient):
    client.headers.update({"X-API-Key": ADMIN_KEY})
    return client


# ── Сид-хелперы ───────────────────────────────────────────────────────

# Сид относительно РЕАЛЬНЫХ часов среды: дефолтное окно запроса —
# [now-24h, now]; «будущие» сиды честно фильтруются окном.
_T0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=2)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _seed_telemetry(
    count: int = 3,
    *,
    event_name: str = "d7.seed.event",
    severity: str = "info",
    outcome: str = "success",
    request_id: str = "req-d7-0001",
    run_id: str = RUN_A,
    tenant_id: str = TENANT_CORE,
    start: datetime = _T0,
) -> None:
    from apps.api import telemetry

    for i in range(count):
        telemetry.emit(
            event_name,
            severity,
            message_template=f"событие d7 #{i}",
            attributes={"index": i},
            outcome=outcome,
            request_id=request_id,
            research_run_id=run_id,
            tenant_id=tenant_id,
            occurred_at=_iso(start + timedelta(seconds=i)),
            essential=True,
        )


def _seed_audit(
    action: str = "run_access_allowed",
    decision: str = "allowed",
    *,
    actor_subject: str = SUPPORT_SUBJECT,
    tenant_id: str = TENANT_CORE,
    run_id: str = RUN_A,
    occurred_at: datetime = _T0,
) -> None:
    from apps.api import security_audit

    sink = security_audit.get_audit_sink()
    record = security_audit.build_audit_record(
        action,
        decision,
        actor_subject=actor_subject,
        actor_via="api_key",
        tenant_id=tenant_id,
        resource_kind="research_run",
        resource_id=run_id,
        run_id=run_id,
        policy_basis="membership",
        occurred_at=_iso(occurred_at),
        details={"note": "d7 audit seed"},
    )
    sink.append(record)


def _seed_delivery(*, state: str = "ready", tenant_id: str = TENANT_CORE) -> str:
    from apps.api.document_jobs import (
        DocumentJobRecord,
        DocumentRecord,
        DocumentRenditionRecord,
        DocumentRevisionRecord,
        get_document_registry,
        new_document_id,
        new_job_id,
        new_rendition_id,
        new_revision_id,
    )

    registry = get_document_registry()
    document = registry.register_document(
        DocumentRecord(
            document_id=new_document_id(),
            run_id=RUN_A,
            kind_code="D02",
        )
    )
    revision = registry.register_revision(
        DocumentRevisionRecord(
            revision_id=new_revision_id(),
            document_id=document.document_id,
            snapshot_id="rs-d7aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            run_id=RUN_A,
            version_no=1,
        )
    )
    rendition = registry.register_rendition(
        DocumentRenditionRecord(
            rendition_id=new_rendition_id(),
            revision_id=revision.revision_id,
            snapshot_id=revision.snapshot_id,
            run_id=RUN_A,
            format="pdf",
            state=state if state != "failed" else "ready",
        )
    )
    job = registry.register_job(
        DocumentJobRecord(
            job_id=new_job_id(),
            run_id=RUN_A,
            snapshot_id=revision.snapshot_id,
            format="pdf",
            revision_id=revision.revision_id,
            rendition_id=rendition.rendition_id,
            state=state,
            error_code="render_error" if state == "failed" else None,
            attempt=2 if state == "failed" else 1,
            tenant_id=tenant_id,
        )
    )
    return job.job_id


def _grant_body(**overrides) -> dict:
    body = {
        "ticket": "d7-ticket-42",
        "purpose": "разбор инцидента доставки",
        "subject_id": SUPPORT_SUBJECT,
        "tenant_id": TENANT_CORE,
        "scopes": ["logs.read"],
        "ttl_hours": 24,
    }
    body.update(overrides)
    return body


# ═════════════════ 1. RED на родителе: модуль существует ══════════════


class TestModuleSurface:
    def test_admin_logs_module_importable(self):
        """RED-оракул поставки: apps.api.admin_logs существует и несёт
        контракт (гранты/запросы/пакет)."""
        from apps.api import admin_logs

        for name in (
            "SupportGrantService",
            "SupportGrantRegistry",
            "MemorySupportGrantRegistry",
            "PostgresSupportGrantRegistry",
            "resolve_effective_log_access",
            "query_telemetry",
            "query_audit",
            "query_delivery",
            "build_diagnostic_bundle",
            "GRANT_SCOPES",
            "GRANT_TTL_MAX_HOURS",
        ):
            assert hasattr(admin_logs, name), name

    def test_pg_audit_list_recent_implemented(self):
        """Отложенный в DOCLOG-3 гэп: PostgresAuditSink.list_recent больше
        не NotImplementedError (чтение durable-журнала -- DOCLOG-7)."""
        from apps.api.security_audit import PostgresAuditSink

        sink = PostgresAuditSink(dsn="postgresql://d7-invalid:5432/none")
        with pytest.raises(Exception) as exc_info:
            sink.list_recent(limit=5)
        assert not isinstance(exc_info.value, NotImplementedError)

    def test_pg_telemetry_list_recent_implemented(self):
        from apps.api.telemetry import PostgresTelemetrySink

        sink = PostgresTelemetrySink(dsn="postgresql://d7-invalid:5432/none")
        with pytest.raises(Exception) as exc_info:
            sink.list_recent(limit=5)
        assert not isinstance(exc_info.value, NotImplementedError)


# ═════════════════ 2. Гранты: валидация и доступ ══════════════════════


class TestGrantValidation:
    def test_ttl_bounds(self):
        from apps.api import admin_logs

        assert admin_logs.GRANT_TTL_MAX_HOURS == 168
        service = admin_logs.SupportGrantService()
        with pytest.raises(admin_logs.GrantValidationError):
            service.create_grant(
                ticket="t", purpose="p", subject_id=SUPPORT_SUBJECT,
                tenant_id=TENANT_CORE, scopes=["logs.read"],
                ttl_hours=169, created_by=ADMIN_SUBJECT,
            )
        grant = service.create_grant(
            ticket="t", purpose="p", subject_id=SUPPORT_SUBJECT,
            tenant_id=TENANT_CORE, scopes=["logs.read"],
            ttl_hours=0.5, created_by=ADMIN_SUBJECT,
        )
        assert grant.grant_id

    def test_scopes_whitelist_fail_closed(self):
        from apps.api import admin_logs

        service = admin_logs.SupportGrantService()
        with pytest.raises(admin_logs.GrantValidationError):
            service.create_grant(
                ticket="t", purpose="p", subject_id=SUPPORT_SUBJECT,
                tenant_id=TENANT_CORE,
                scopes=["documentation.publish"],  # выдача publish через
                # support-grant запрещена (§14.2: пакет «без данных»)
                ttl_hours=24, created_by=ADMIN_SUBJECT,
            )

    def test_ticket_and_tenant_required(self):
        from apps.api import admin_logs

        service = admin_logs.SupportGrantService()
        with pytest.raises(admin_logs.GrantValidationError):
            service.create_grant(
                ticket="", purpose="p", subject_id=SUPPORT_SUBJECT,
                tenant_id=TENANT_CORE, scopes=["logs.read"],
                ttl_hours=24, created_by=ADMIN_SUBJECT,
            )
        with pytest.raises(admin_logs.GrantValidationError):
            service.create_grant(
                ticket="t", purpose="p", subject_id=SUPPORT_SUBJECT,
                tenant_id="", scopes=["logs.read"],
                ttl_hours=24, created_by=ADMIN_SUBJECT,
            )

    def test_revoke_and_expiry(self):
        from apps.api import admin_logs

        service = admin_logs.SupportGrantService()
        grant = service.create_grant(
            ticket="t", purpose="p", subject_id=SUPPORT_SUBJECT,
            tenant_id=TENANT_CORE, scopes=["logs.read"],
            ttl_hours=1, created_by=ADMIN_SUBJECT,
        )
        revoked = service.revoke_grant(
            grant.grant_id, revoked_by=ADMIN_SUBJECT, reason="инцидент закрыт"
        )
        assert revoked.revoked_at is not None
        access = admin_logs.resolve_effective_log_access(
            _principal(scopes=()),
            registry=service.registry,
        )
        assert access.telemetry is False  # истёк/отозван -> доступа нет


def _principal(scopes=(), role: str = "external_user"):
    from apps.api.plans import AuthenticatedPrincipal, Role

    return AuthenticatedPrincipal(
        principal_id="d7-key",
        role=Role(role),
        subject_id=SUPPORT_SUBJECT,
        tenant_id=TENANT_CORE,
        scopes=tuple(scopes),
    )


class TestEffectiveAccess:
    def test_admin_full_catalog(self):
        from apps.api import admin_logs

        access = admin_logs.resolve_effective_log_access(
            _principal(role="admin", scopes=()),
            registry=admin_logs.SupportGrantService().registry,
        )
        assert access.telemetry and access.audit and access.delivery
        assert access.export and access.grants_management
        assert access.tenants == frozenset()  # unrestricted

    def test_grant_narrows_scope(self):
        from apps.api import admin_logs

        service = admin_logs.SupportGrantService()
        service.create_grant(
            ticket="t", purpose="p", subject_id=SUPPORT_SUBJECT,
            tenant_id=TENANT_CORE, run_id=RUN_A,
            scopes=["logs.read", "logs.export"],
            ttl_hours=24, created_by=ADMIN_SUBJECT,
        )
        access = admin_logs.resolve_effective_log_access(
            _principal(scopes=()), registry=service.registry
        )
        assert access.telemetry and access.export
        assert access.audit is False  # audit.read не выдавался
        assert access.grants_management is False
        assert access.tenants == frozenset({TENANT_CORE})
        assert access.runs == frozenset({RUN_A})

    def test_expired_grant_denied(self):
        from apps.api import admin_logs

        service = admin_logs.SupportGrantService()
        service.create_grant(
            ticket="t", purpose="p", subject_id=SUPPORT_SUBJECT,
            tenant_id=TENANT_CORE, scopes=["logs.read"],
            ttl_hours=24, created_by=ADMIN_SUBJECT,
        )
        # Механически устареваем: expires_at в прошлом.
        registry = service.registry
        for record in registry.list_grants():
            stale = admin_logs.replace_grant_record(
                record, expires_at="2020-01-01T00:00:00+00:00"
            )
            registry.update_grant(stale)
        access = admin_logs.resolve_effective_log_access(
            _principal(scopes=()), registry=registry
        )
        assert access.telemetry is False


# ═════════════════ 3. API: доступ и uniform-отказы ════════════════════


class TestLogsAuth:
    def test_401_without_key(self, client: TestClient):
        response = client.get("/v1/logs/telemetry")
        assert response.status_code == 401

    def test_401_unknown_key(self, client: TestClient):
        response = client.get(
            "/v1/logs/telemetry", headers={"X-API-Key": "d7-unknown-key"}
        )
        assert response.status_code == 401

    def test_403_uniform_body_without_grant(self, client: TestClient):
        client.headers.update({"X-API-Key": OTHER_KEY})
        response = client.get("/v1/logs/telemetry")
        assert response.status_code == 403
        body = response.json()
        assert body["code"] == "logs_access_denied"
        assert "request_id" in body

    def test_access_summary(self, admin_client: TestClient):
        response = admin_client.get("/v1/logs/access")
        assert response.status_code == 200
        body = response.json()
        assert body["access"]["telemetry"] is True
        assert body["access"]["scope"] == "unrestricted"


# ═════════════════ 4. API: поток telemetry ════════════════════════════


class TestTelemetryStream:
    def test_query_returns_records_and_meta(
        self, admin_client: TestClient
    ):
        _seed_telemetry(count=3)
        response = admin_client.get(
            "/v1/logs/telemetry",
            params={"from": _iso(_T0 - timedelta(minutes=1)),
                    "to": _iso(_T0 + timedelta(minutes=5))},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["meta"]["stream"] == "telemetry"
        assert len(body["records"]) == 3
        assert body["meta"]["retention_horizon_days"] == 30
        assert body["next_cursor"] is None
        # Whitelist-поле, безопасное для UI:
        record = body["records"][0]
        assert record["event_name"] == "d7.seed.event"

    def test_filters_whitelist(self, admin_client: TestClient):
        # emit нормализует severity в канонические WARN/INFO/ERROR (§13.1);
        # фильтр -- точное совпадение с сохранённой формой.
        _seed_telemetry(count=2, severity="warning")
        _seed_telemetry(count=1, event_name="d7.other.event")
        response = admin_client.get(
            "/v1/logs/telemetry", params={"severity": "WARN"}
        )
        assert response.status_code == 200
        assert len(response.json()["records"]) == 2

    def test_cursor_pagination_stable_order(
        self, admin_client: TestClient
    ):
        _seed_telemetry(count=12)
        seen_ids: list[str] = []
        cursor = None
        for _page in range(4):
            params = {"limit": 4, "event_name": "d7.seed.event"}
            if cursor:
                params["cursor"] = cursor
            response = admin_client.get("/v1/logs/telemetry", params=params)
            assert response.status_code == 200
            body = response.json()
            seen_ids.extend(r["event_id"] for r in body["records"])
            cursor = body["next_cursor"]
            if cursor is None:
                break
        assert len(seen_ids) == 12
        assert len(set(seen_ids)) == 12  # без дублей и потерь

    def test_invalid_cursor_and_limit_422(self, admin_client: TestClient):
        response = admin_client.get(
            "/v1/logs/telemetry", params={"cursor": "%%%bad%%%"}
        )
        assert response.status_code == 422
        assert response.json()["code"] == "logs_validation_error"
        response = admin_client.get("/v1/logs/telemetry", params={"limit": 500})
        assert response.status_code == 422

    def test_window_validation_422(self, admin_client: TestClient):
        response = admin_client.get(
            "/v1/logs/telemetry",
            params={"from": _iso(_T0), "to": _iso(_T0 - timedelta(days=1))},
        )
        assert response.status_code == 422
        response = admin_client.get(
            "/v1/logs/telemetry",
            params={"from": _iso(_T0 - timedelta(days=40)),
                    "to": _iso(_T0)},
        )
        assert response.status_code == 422

    def test_grantee_narrowed_to_grant_tenant(
        self, admin_client: TestClient, client: TestClient
    ):
        _seed_telemetry(count=2, tenant_id=TENANT_CORE)
        _seed_telemetry(count=2, tenant_id=TENANT_OTHER)
        created = admin_client.post(
            "/v1/logs/grants", json=_grant_body()
        )
        assert created.status_code == 201, created.text
        client.headers.update({"X-API-Key": SUPPORT_KEY})
        # Без фильтра -- честное сужение до grant-тенанта.
        response = client.get("/v1/logs/telemetry")
        assert response.status_code == 200
        body = response.json()
        assert len(body["records"]) == 2
        assert all(
            r["tenant_id"] == TENANT_CORE for r in body["records"]
        )
        assert body["meta"]["effective_scope"]["tenants"] == [TENANT_CORE]
        # Явный запрос ЧУЖОГО тенанта -- 403: данных вне grant нет.
        response = client.get(
            "/v1/logs/telemetry", params={"tenant_id": TENANT_OTHER}
        )
        assert response.status_code == 403


# ═════════════════ 5. API: поток audit + саможурналирование ═══════════


class TestAuditStream:
    def test_audit_stream_filters(self, admin_client: TestClient):
        _seed_audit(action="run_access_allowed", decision="allowed")
        _seed_audit(action="authz_denied", decision="denied")
        response = admin_client.get(
            "/v1/logs/audit", params={"decision": "denied"}
        )
        assert response.status_code == 200
        records = response.json()["records"]
        assert len(records) == 1
        assert records[0]["action"] == "authz_denied"

    def test_journal_access_self_audited(
        self, admin_client: TestClient
    ):
        # 1) чтение telemetry -> audit_log_accessed (standard).
        admin_client.get("/v1/logs/telemetry")
        # 2) чтение audit-потока видит ПРЕДЫДУЩЕЕ чтение...
        response = admin_client.get("/v1/logs/audit")
        assert response.status_code == 200
        actions = [
            r["action"] for r in response.json()["records"]
        ]
        assert "audit_log_accessed" in actions
        record = next(
            r for r in response.json()["records"]
            if r["action"] == "audit_log_accessed"
        )
        assert record["details"]["stream"] == "telemetry"
        # ...и сам этот запрос добавил РОВНО одну запись (без рекурсии).
        response2 = admin_client.get("/v1/logs/audit")
        accessed = [
            r for r in response2.json()["records"]
            if r["action"] == "audit_log_accessed"
        ]
        assert len(accessed) == 2


# ═════════════════ 6. API: поток delivery ═════════════════════════════


class TestDeliveryStream:
    def test_delivery_summary_no_content(
        self, admin_client: TestClient
    ):
        job_id = _seed_delivery(state="ready")
        _seed_delivery(state="failed")
        response = admin_client.get("/v1/logs/delivery")
        assert response.status_code == 200
        body = response.json()
        assert len(body["records"]) == 2
        row = next(r for r in body["records"] if r["job_id"] == job_id)
        assert row["state"] == "ready"
        assert row["format"] == "pdf"
        assert row["tenant_id"] == TENANT_CORE
        # Ни одна строка доставки не несёт контентных байтов (§14.2).
        assert "content_bytes" not in json.dumps(body)

    def test_delivery_filter_state(self, admin_client: TestClient):
        _seed_delivery(state="ready")
        _seed_delivery(state="failed")
        response = admin_client.get(
            "/v1/logs/delivery", params={"state": "failed"}
        )
        assert response.status_code == 200
        records = response.json()["records"]
        assert len(records) == 1
        assert records[0]["error_code"] == "render_error"


# ═════════════════ 7. API: гранты (маршруты, mandatory audit) ═════════


class TestGrantsAPI:
    def test_grant_lifecycle_api(
        self, admin_client: TestClient, client: TestClient
    ):
        created = admin_client.post("/v1/logs/grants", json=_grant_body())
        assert created.status_code == 201
        grant = created.json()
        assert grant["ticket"] == "d7-ticket-42"
        assert grant["tenant_id"] == TENANT_CORE
        assert grant["revoked_at"] is None

        listing = admin_client.get("/v1/logs/grants")
        assert listing.status_code == 200
        assert any(g["grant_id"] == grant["grant_id"]
                   for g in listing.json()["grants"])

        client.headers.update({"X-API-Key": SUPPORT_KEY})
        # Grantee c грантом видит поток.
        assert client.get("/v1/logs/telemetry").status_code == 200

        # admin_client и client -- ОДИН TestClient: возвращаем админ-ключ.
        client.headers.update({"X-API-Key": ADMIN_KEY})
        revoked = admin_client.post(
            f"/v1/logs/grants/{grant['grant_id']}/revoke",
            json={"reason": "работа завершена"},
        )
        assert revoked.status_code == 200
        assert revoked.json()["revoked_at"] is not None
        # После отзыва -- 403: «нет данных вне grant».
        client.headers.update({"X-API-Key": SUPPORT_KEY})
        assert client.get("/v1/logs/telemetry").status_code == 403

        from apps.api.security_audit import audit_records
        actions = [r["action"] for r in audit_records()]
        assert "grant_created" in actions
        assert "grant_revoked" in actions

    def test_grant_validation_api_422(self, admin_client: TestClient):
        response = admin_client.post(
            "/v1/logs/grants", json=_grant_body(ttl_hours=1000)
        )
        assert response.status_code == 422
        response = admin_client.post(
            "/v1/logs/grants", json=_grant_body(scopes=["artifact.data.read"])
        )
        assert response.status_code == 422
        response = admin_client.post(
            "/v1/logs/grants", json=_grant_body(ticket="  ")
        )
        assert response.status_code == 422

    def test_grant_management_requires_scope(
        self, client: TestClient
    ):
        client.headers.update({"X-API-Key": SUPPORT_KEY})
        assert client.post(
            "/v1/logs/grants", json=_grant_body()
        ).status_code == 403
        assert client.get("/v1/logs/grants").status_code == 403

    def test_grant_create_mandatory_audit_fail_closed(
        self, admin_client: TestClient
    ):
        from apps.api import admin_logs, security_audit

        class _FailingSink(security_audit.AuditSink):
            def append(self, record):
                raise RuntimeError("d7 audit outage")

            def readiness_probe(self):
                return {"ok": False, "backend": "memory"}

        security_audit.set_audit_sink_for_testing(_FailingSink())
        try:
            response = admin_client.post(
                "/v1/logs/grants", json=_grant_body()
            )
            assert response.status_code == 503
            service = admin_logs.SupportGrantService()
            assert service.registry.list_grants() == []  # не создан
        finally:
            security_audit.reset_audit_for_testing()

    def test_revoke_unknown_grant_404(self, admin_client: TestClient):
        response = admin_client.post(
            "/v1/logs/grants/d7grant-unknown/revoke",
            json={"reason": "x"},
        )
        assert response.status_code == 404


# ═════════════════ 8. API: диагностический пакет ══════════════════════


class TestDiagnosticBundle:
    def test_bundle_zip_contract(self, admin_client: TestClient):
        _seed_telemetry(count=3)
        _seed_audit()
        monkey_key = ADMIN_KEY  # значение ключа НИКОГДА не в пакете
        os.environ["CISSTAT_D7_SECRET_SENTINEL"] = "d7-env-secret-value"
        try:
            response = admin_client.post(
                "/v1/logs/export",
                json={"from": _iso(_T0 - timedelta(hours=1)),
                      "to": _iso(_T0 + timedelta(hours=1))},
            )
        finally:
            os.environ.pop("CISSTAT_D7_SECRET_SENTINEL", None)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/zip"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "attachment" in response.headers["content-disposition"]

        archive = zipfile.ZipFile(io.BytesIO(response.content))
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "telemetry.jsonl" in names
        assert "audit.jsonl" in names

        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema_version"] == "doclog.diagbundle/1"
        assert "excluded" in manifest and manifest["excluded"]
        blob = response.content.decode("latin-1")
        # AC10: ни ключ, ни env-значение, ни DSN в пакете.
        assert monkey_key not in blob
        assert "d7-env-secret-value" not in blob
        assert "CISSTAT_D7_SECRET_SENTINEL" not in blob
        # Строки событий читаемы (redacted JSONL).
        lines = archive.read("telemetry.jsonl").decode("utf-8").splitlines()
        assert any("d7.seed.event" in line for line in lines)

    def test_bundle_requires_export_scope(
        self, admin_client: TestClient, client: TestClient
    ):
        admin_client.post("/v1/logs/grants", json=_grant_body())
        client.headers.update({"X-API-Key": SUPPORT_KEY})
        response = client.post(
            "/v1/logs/export",
            json={"from": _iso(_T0 - timedelta(hours=1)),
                  "to": _iso(_T0 + timedelta(hours=1))},
        )
        # logs.read есть, logs.export НЕ выдавался -> 403.
        assert response.status_code == 403

    def test_bundle_audited_with_download_triple(
        self, admin_client: TestClient
    ):
        admin_client.post(
            "/v1/logs/export",
            json={"from": _iso(_T0 - timedelta(hours=1)),
                  "to": _iso(_T0 + timedelta(hours=1))},
        )
        from apps.api.security_audit import audit_records
        actions = [r["action"] for r in audit_records()]
        assert "audit_log_accessed" in actions
        assert "download_requested" in actions
        assert "response_stream_started" in actions
        assert "response_stream_finished" in actions

    def test_bundle_deterministic(self, admin_client: TestClient):
        _seed_telemetry(count=2)
        body = {"from": _iso(_T0 - timedelta(hours=1)),
                "to": _iso(_T0 + timedelta(hours=1))}
        first = admin_client.post("/v1/logs/export", json=body).content
        second = admin_client.post("/v1/logs/export", json=body).content
        # manifest/bundle_id различаются, но ZIP-даты членов фиксированы
        # (урок DOCLOG-5: недетерминированный ZIP -- дефект).
        a = zipfile.ZipFile(io.BytesIO(first))
        b = zipfile.ZipFile(io.BytesIO(second))
        dates_a = [i.date_time for i in a.infolist()]
        dates_b = [i.date_time for i in b.infolist()]
        assert dates_a == dates_b
        assert all(dt[:3] == (2020, 1, 1) for dt in dates_a)


# ═════════════════ 9. Статические каталоги и миграция 0013 ════════════


class TestStaticCatalogs:
    def test_routes_present(self):
        from apps.api.main import app

        paths = {getattr(r, "path", "") for r in app.routes}
        for path in (
            "/v1/logs/access",
            "/v1/logs/telemetry",
            "/v1/logs/audit",
            "/v1/logs/delivery",
            "/v1/logs/export",
            "/v1/logs/grants",
            "/v1/logs/grants/{grant_id}/revoke",
        ):
            assert path in paths, path

    def test_audit_actions_catalog_membership(self):
        from apps.api import security_audit

        for action in (
            "grant_created",
            "grant_revoked",
            "audit_log_accessed",
        ):
            assert action in security_audit.AUDIT_ACTIONS, action

    def test_migration_catalog_counts(self):
        from apps.api.research_runs import MIGRATION_FILES, MIGRATION_STATEMENTS

        assert len(MIGRATION_FILES) == 15
        # DOCLOG-9 (честное обновление пина): 0013 пинуется по имени
        # (последний файл каталога -- 0015).
        assert "0013_doclog7_logs_support.sql" in [n for n, _ in MIGRATION_FILES]
        # 85 (0014) + 8 statement 0015 (2 ALTER + 3 таблицы + 3 индекса).
        assert len(MIGRATION_STATEMENTS) == 93

    def test_migration_file_parity(self):
        from apps.api.research_runs import MIGRATION_FILES

        name, statements = MIGRATION_FILES[-1]
        sql = (Path("apps/api/migrations") / name).read_text("utf-8")
        for statement in statements:
            compact = " ".join(statement.split())
            assert compact in " ".join(sql.split()), statement[:80]

    def test_grants_table_in_ddl(self):
        sql = (
            Path("apps/api/migrations/0013_doclog7_logs_support.sql")
            .read_text("utf-8")
        )
        for fragment in (
            "CREATE TABLE IF NOT EXISTS support_grants",
            "ticket TEXT NOT NULL",
            "expires_at TIMESTAMPTZ NOT NULL",
            "revoked_at TIMESTAMPTZ",
        ):
            assert fragment in sql, fragment
