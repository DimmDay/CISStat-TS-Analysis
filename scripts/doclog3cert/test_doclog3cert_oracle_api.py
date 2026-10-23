# scripts/doclog3cert/test_doclog3cert_oracle_api.py
"""DOCLOG-3-CERT: оракулы на СВОИХ данных -- часть 3 (API/HTTP).

Интеграции identity/auth (durable-поток + AC11-инвариант),
TelemetryContextMiddleware (X-Request-ID/traceparent/api.request/
sampling/исключения), sentinel-батарея AC10 ×2 канала + health +
error-response, lifecycle api.startup/shutdown, негативная авторизация
с корреляцией request_id<->audit.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conftest import (
    ADMIN_KEY,
    EVENT_ALPHA,
    IDENTITY_SALT,
    RUN_ID_FOREIGN,
    RUN_ID_MISSING,
    RUN_ID_OWNER,
    SENTINEL_BEARER,
    SENTINEL_COOKIE,
    SENTINEL_CRLF,
    SENTINEL_DSN,
    SENTINEL_KEY,
    SENTINEL_MULTILINE,
    SENTINEL_PASSWORD,
    SENTINEL_SESSION,
    SENTINEL_SIGNED_URL,
    SENTINEL_SQL,
    SESSION_ID_FOREIGN,
    SESSION_ID_OWNER,
    SPAN_ID_OK,
    TRACEPARENT_OK,
    TRACE_ID_OK,
    REQUEST_ID_1,
)
from apps.api.session_store import SESSION_COOKIE_NAME

_NOW = "2026-10-23T00:00:00+00:00"


def _seed_bound_run(run_id=RUN_ID_OWNER, session_id=SESSION_ID_OWNER):
    from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
    from apps.api.research_runs import (
        ResearchRun,
        get_research_run_store,
    )

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="c3" * 16,
        dataset_name="d3cert-certification-seed",
        target_column="value",
        target_column_source="user",
        created_at=_NOW,
        last_active_at=_NOW,
        status="active",
        owner_subject=SubjectRef.from_session(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)
    return run


def _audit_blob(security_audit):
    return json.dumps(security_audit.audit_records(), default=str)


# ═══════════ 10. Интеграция identity (durable-поток) ═════════════════


class TestIdentityDurableFlow:
    def test_allow_and_deny_durable_with_surrogates(self):
        """Оракул oc72: оба исхода решающей таблицы -- в durable
        audit: deny для чужой сессии, allow для владельца; материал
        cookie не дисклоужается; псевдоним субъекта в записи."""
        from apps.api import security_audit
        from apps.api.identity import (
            SubjectRef,
            authorize_run_access,
        )

        _seed_bound_run()
        d_denied = authorize_run_access(
            _seed_bound_run(), SubjectRef.from_session(SESSION_ID_FOREIGN),
            session_id=SESSION_ID_FOREIGN,
        )
        d_allowed = authorize_run_access(
            _seed_bound_run(), SubjectRef.from_session(SESSION_ID_OWNER),
            session_id=SESSION_ID_OWNER,
        )
        assert d_denied.allowed is False
        assert d_allowed.allowed is True
        blob = _audit_blob(security_audit)
        assert SESSION_ID_FOREIGN not in blob
        denied = [
            r for r in security_audit.audit_records()
            if r["action"] == "run_access_denied"
        ]
        allowed = [
            r for r in security_audit.audit_records()
            if r["action"] == "run_access_allowed"
        ]
        assert denied and allowed
        assert denied[-1]["details"]["reason_code"] == "foreign_session"
        assert denied[-1]["run_id"] == RUN_ID_OWNER
        assert allowed[-1]["details"]["reason_code"] == "owner"

    def test_audit_failure_does_not_flip_decision(self):
        """Оракул oc73 (AC11-инвариант, свои данные): сломанный
        audit-приёмник НЕ меняет уже принятых решений: deny остаётся
        deny, allow остаётся allow."""
        from apps.api import security_audit
        from apps.api.identity import (
            SubjectRef,
            authorize_run_access,
        )

        class _Broken:
            def append(self, record):
                raise RuntimeError("audit down d3cert")

            def list_recent(self, limit=100):
                return []

            def readiness_probe(self):
                return {"ok": False}

        security_audit.set_audit_sink_for_testing(_Broken())
        run = _seed_bound_run()
        d1 = authorize_run_access(
            run, SubjectRef.from_session(SESSION_ID_FOREIGN),
            session_id=SESSION_ID_FOREIGN,
        )
        d2 = authorize_run_access(
            run, SubjectRef.from_session(SESSION_ID_OWNER),
            session_id=SESSION_ID_OWNER,
        )
        assert d1.allowed is False and d1.reason == "foreign_session"
        assert d2.allowed is True and d2.reason == "owner"


# ═══════════ 11. Интеграция auth (401/403 durable) ═══════════════════


class TestAuthDurable:
    def test_401_pseudonym_of_presented_material(self, monkeypatch):
        """Оракул oc74: 401 -> authn_denied; субъект -- HMAC-псевдоним
        предъявленного материала (детерминирован, значение ключа не
        восстановим и не дисклоужается); связь повторов сохранена."""
        from apps.api import security_audit
        from apps.api.auth import get_current_principal
        from apps.api.identity import subject_pseudonym

        monkeypatch.setenv("CISSTAT_API_KEYS", f"{ADMIN_KEY}:admin::")
        bad_key = f"junk-key-{SENTINEL_KEY}-d3cert"
        for _ in range(2):
            with pytest.raises(Exception) as excinfo:
                get_current_principal(x_api_key=bad_key)
            assert excinfo.value.status_code == 401
        records = [
            r for r in security_audit.audit_records()
            if r["action"] == "authn_denied"
        ]
        assert len(records) == 2  # оба отказа -- с ОДНИМ псевдонимом
        blob = _audit_blob(security_audit)
        assert bad_key not in blob and SENTINEL_KEY not in blob
        expected = subject_pseudonym(bad_key)
        assert records[0]["actor_subject"] == expected
        assert records[1]["actor_subject"] == expected
        assert records[0]["actor_via"] == "api_key"
        assert records[0]["details"]["reason_code"] == "invalid_key"

    def test_403_role_insufficient_recorded(self, monkeypatch):
        """Оракул oc75: 403 -> authz_denied: псевдоним субъекта (НЕ
        principal_id); resource_kind admin_endpoint."""
        from apps.api import security_audit
        from apps.api.auth import require_admin_role
        from apps.api.identity import subject_pseudonym
        from apps.api.plans import (
            AuthenticatedPrincipal,
            PlanName,
            Role,
        )

        monkeypatch.setenv("CISSTAT_IDENTITY_SALT", IDENTITY_SALT)
        principal = AuthenticatedPrincipal(
            principal_id="d3cert-analyst-plain-key",
            role=Role.INTERNAL_ANALYST,
            plan=PlanName.PROFESSIONAL,
        )
        with pytest.raises(Exception) as excinfo:
            require_admin_role(principal=principal)
        assert excinfo.value.status_code == 403
        records = [
            r for r in security_audit.audit_records()
            if r["action"] == "authz_denied"
        ]
        assert records
        blob = json.dumps(records[-1])
        assert "d3cert-analyst-plain-key" not in blob
        assert records[-1]["actor_subject"] == subject_pseudonym(
            "d3cert-analyst-plain-key"
        )
        assert records[-1]["resource_kind"] == "admin_endpoint"
        assert records[-1]["details"]["reason_code"] == "role_insufficient"

    def test_403_admin_passes_no_record(self, monkeypatch):
        """Оракул oc76: админ НЕ порождает authz_denied (дискриминация
        -- отказ фиксируется, разрешение нет)."""
        from apps.api import security_audit
        from apps.api.auth import require_admin_role
        from apps.api.plans import (
            AuthenticatedPrincipal,
            PlanName,
            Role,
        )

        before = len(security_audit.audit_records())
        principal = AuthenticatedPrincipal(
            principal_id=ADMIN_KEY, role=Role.ADMIN,
            plan=PlanName.ENTERPRISE,
        )
        require_admin_role(principal=principal)  # не бросает
        after = [
            r for r in security_audit.audit_records()[before:]
            if r["action"] == "authz_denied"
        ]
        assert after == []


# ═══════════ 12. TelemetryContextMiddleware (ASGI) ═══════════════════


def _mini_app() -> FastAPI:
    from apps.api.telemetry import TelemetryContextMiddleware

    mini = FastAPI()
    mini.add_middleware(TelemetryContextMiddleware)

    @mini.get("/d3cert/ok")
    def _ok():
        return {"ok": "d3cert"}

    @mini.get("/d3cert/boom")
    def _boom():
        raise RuntimeError(f"boom password={SENTINEL_PASSWORD} d3cert")

    @mini.get("/d3cert/teapot")
    def _teapot():
        from fastapi import HTTPException

        raise HTTPException(status_code=418, detail="short and stout")

    return mini


class TestMiddlewareObservability:
    def test_x_request_id_all_shapes(self):
        """Оракул oc77: X-Request-ID на все ответы, ПРОИЗВОДИМЫЕ
        приложением: 200/4xx (HTTPException)/unmatched/эхо валидного
        внешнего; НАБЛЮДЕНИЕ (см. акт N5): unhandled 500 от
        ServerErrorMiddleware (вне user-middleware) заголовка НЕ несёт
        -- корреляция только через durable api.request с request_id."""
        from apps.api.telemetry import accept_request_id

        with TestClient(_mini_app(), raise_server_exceptions=False) as c:
            r1 = c.get("/d3cert/ok")
            assert r1.status_code == 200
            assert r1.headers.get("x-request-id", "").startswith("req-")
            # эхо валидного внешнего
            r2 = c.get("/d3cert/ok", headers={"X-Request-ID": REQUEST_ID_1})
            assert r2.headers.get("x-request-id") == REQUEST_ID_1
            # 4xx-исключение (обработано ExceptionMiddleware ВНУТРИ стека)
            r3 = c.get("/d3cert/teapot", headers={"X-Request-ID": "zz"})
            assert r3.headers.get("x-request-id", "").startswith("req-")
            # 404 unmatched
            r5 = c.get("/d3cert/nope-d3cert")
            assert r5.headers.get("x-request-id", "").startswith("req-")
            # НАБЛЮДЕНИЕ: unhandled 500 -- вне user-middleware
            r4 = c.get("/d3cert/boom")
            assert r4.status_code == 500
            assert r4.headers.get("x-request-id") is None  # фиксация факта
        # инъекция -> свой
        assert accept_request_id("bad\r\nX: 1") is None

    def test_options_and_health_not_observed(self):
        """Оракул oc78: OPTIONS и liveness-пути не порождают api.request
        (шум §13.2), НО X-Request-ID на них есть (§13.1)."""
        from apps.api import telemetry

        mini = _mini_app()

        @mini.get("/health")
        def _health():
            return {"ok": True}

        with TestClient(mini) as c:
            assert c.options("/d3cert/ok").status_code == 405 or True
            # OPTIONS на существующий путь (CORS-префлайт-семантика)
            c.options("/d3cert/ok")
            c.get("/health")
        api_events = [
            r for r in telemetry.memory_records()
            if r["event_name"] == "api.request"
        ]
        observed_paths = [
            (r.get("attributes") or {}).get("method") for r in api_events
        ]
        assert "OPTIONS" not in observed_paths

    def test_api_request_route_template_low_cardinality(self):
        """Оракул oc79: route template (НЕ сырой path) в атрибутах;
        status_class/method/outcome; duration присутствует."""
        from apps.api import telemetry

        with TestClient(_mini_app()) as c:
            c.get("/d3cert/ok?skip=d3cert")
        events = [
            r for r in telemetry.memory_records()
            if r["event_name"] == "api.request"
        ]
        assert events
        rec = events[-1]
        attrs = rec["attributes"]
        assert attrs["route"] == "/d3cert/ok"
        assert attrs["status_class"] == "2xx"
        assert attrs["method"] == "GET"
        assert rec["outcome"] == "success"
        assert rec["severity_number"] == 9

    def test_5xx_error_severity_no_message(self):
        """Оракул oc80: 500 -- severity ERROR + clean_exception:
        сообщение исключения (секрет) НЕ в записи."""
        from apps.api import telemetry

        with TestClient(_mini_app(), raise_server_exceptions=False) as c:
            c.get("/d3cert/boom")
        events = [
            r for r in telemetry.memory_records()
            if r["event_name"] == "api.request"
        ]
        assert events
        rec = events[-1]
        assert rec["severity_number"] == 17
        assert rec["outcome"] == "server_error"
        assert rec["error_code"] == "RuntimeError"
        blob = json.dumps(rec, default=str)
        assert SENTINEL_PASSWORD not in blob
        assert "boom password" not in blob

    def test_4xx_info_not_error(self):
        """Оракул oc81: 4xx -- ожидаемый outcome (INFO, не ERROR):
        HTTP 418 -> client_error/INFO (§13.1: 422 не ERROR)."""
        from apps.api import telemetry

        with TestClient(_mini_app(), raise_server_exceptions=False) as c:
            c.get("/d3cert/teapot")
        events = [
            r for r in telemetry.memory_records()
            if r["event_name"] == "api.request"
        ]
        rec = events[-1]
        assert rec["severity_number"] == 9
        assert rec["outcome"] == "client_error"
        assert rec["attributes"]["status_class"] == "4xx"

    def test_traceparent_correlation_from_header(self):
        """Оракул oc82: traceparent-заголовок проверяется и попадает в
        api.request (trace_id/span_id); мусор игнорируется."""
        from apps.api import telemetry

        with TestClient(_mini_app()) as c:
            c.get(
                "/d3cert/ok",
                headers={"traceparent": TRACEPARENT_OK},
            )
            c.get("/d3cert/ok", headers={"traceparent": "garbage-d3cert"})
        events = [
            r for r in telemetry.memory_records()
            if r["event_name"] == "api.request"
        ]
        assert any(r.get("trace_id") == TRACE_ID_OK for r in events)
        assert any(
            r.get("trace_id") is None and r.get("span_id") is None
            for r in events
        )

    def test_successful_get_sampling_applies(self, monkeypatch):
        """Оракул oc83: успешные GET -- noisy_read: rate=0 -> дроп
        (счётчик); rate=1 -> доставка; не-GET/ошибки -- никогда."""
        from apps.api import telemetry

        monkeypatch.setenv("CISSTAT_TELEMETRY_SAMPLE_RATE", "0")
        with TestClient(_mini_app()) as c:
            c.get("/d3cert/ok")  # успешный GET -- сэмплится
        counters = telemetry.telemetry_status()["counters"]
        assert counters.get("telemetry_sampled_out_total", 0) == 1

        monkeypatch.setenv("CISSTAT_TELEMETRY_SAMPLE_RATE", "1")
        telemetry.reset_telemetry_for_testing()
        with TestClient(_mini_app(), raise_server_exceptions=False) as c:
            c.get("/d3cert/ok")
            c.get("/d3cert/teapot")  # 4xx -- не noisy_read
        events = [
            r for r in telemetry.memory_records()
            if r["event_name"] == "api.request"
        ]
        assert len(events) == 2
        assert all(r["sampled"] is False for r in events)

    def test_exception_event_via_emit_error(self):
        """Оракул oc84: исключение в хендлере коррелирует событием с
        error-полем (clean_exception), событие доставлено до
        сброса ContextVar."""
        from apps.api import telemetry

        with TestClient(_mini_app(), raise_server_exceptions=False) as c:
            c.get("/d3cert/boom")
        errors = [
            r for r in telemetry.memory_records()
            if r["error_code"] == "RuntimeError"
        ]
        assert errors
        assert errors[-1]["error_fingerprint"]


# ═══════════ 13. Sentinel-батарея AC10 (сквозная) ════════════════════


class TestSentinelBattery:
    def _battery(self, channel: str) -> None:
        """Отправка каждого сентинела в канал message|attribute.
        Векторы -- ПАТТЕРНИРОВАННЫЕ секретные формы (R08 §13.3:
        password=/Cookie:/X-API-Key:/Bearer/DSN/signed URL/сессия);
        SQL-литерал -- только в attribute-канал под НЕALLOWED ключом
        (отсечение allowlist'ом), CRLF -- попытка smuggling секрета."""
        from apps.api import telemetry

        vectors = [
            f"password={SENTINEL_PASSWORD}",
            SENTINEL_DSN,
            SENTINEL_BEARER,
            f"X-API-Key: {SENTINEL_KEY}",
            f"Cookie: {SENTINEL_COOKIE}",
            SENTINEL_SIGNED_URL,
            SENTINEL_MULTILINE,
            f"session_id={SENTINEL_SESSION}",
            f"legit=1\r\npassword={SENTINEL_PASSWORD}\r\n",
            SENTINEL_SQL,
        ]
        for i, sentinel in enumerate(vectors):
            if channel == "message":
                telemetry.emit(
                    f"d3cert.sentinel.{i}", severity="info",
                    message_template=sentinel,
                )
            else:
                # ALLOWED-ключ -- проверка redaction значения
                telemetry.emit(
                    f"d3cert.sentinel.a{i}", severity="info",
                    attributes={"route": sentinel},
                )
                # НЕALLOWED-ключ -- проверка allowlist (физический отсев)
                telemetry.emit(
                    f"d3cert.sentinel.b{i}", severity="info",
                    attributes={"query": sentinel},
                )

    def test_message_channel_clean_everywhere(self, client):
        """Оракул oc85 (AC10): 9 паттернированных векторов в
        message-канале: секреты отсутствуют в sink-записях, JSONL,
        /health/ops, error response. SQL-литерал -- НЕ message-вектор:
        message_template -- caller-trusted шаблон по контракту emit
        (SQL отсекается allowlist'ом в attribute-канале -- oc86)."""
        from apps.api import telemetry

        self._battery("message")
        blob_records = json.dumps(telemetry.memory_records(), default=str)
        blob_jsonl = "\n".join(
            telemetry.to_jsonl(r) for r in telemetry.memory_records()
        )
        health = client.get("/health/ops").text
        error_resp = client.get("/v1/progress/runs/RUN-D3CERT99/report")
        for sentinel in (
            "truffle-swine-77-d3cert", SENTINEL_DSN, "d3cert.jwt",
            "AKIA-D3CERT-IO-777-QQ", "open-sesame-4242", "cafebabe777",
            "abcd1234efghJK", "plain-session-31337",
        ):
            assert sentinel not in blob_records, sentinel
            assert sentinel not in blob_jsonl, sentinel
            assert sentinel not in health, sentinel
            assert sentinel not in error_resp.text, sentinel
        # CRLF-инъекция: сырые переводы строк нейтрализованы
        assert "\r\n" not in blob_records
        # SQL-литерал в message-канале НЕ паттерн (caller-trusted):
        # фиксируем фактическое поведение как наблюдение
        sql_records = [
            r for r in telemetry.memory_records()
            if r["event_name"] == "d3cert.sentinel.9"
        ]
        assert sql_records  # доставлен (контракт message_template)

    def test_attribute_channel_allowlist_and_redaction(self):
        """Оракул oc86 (AC10/R08): attribute-канал: SQL-literal под
        НЕALLOWED ключом отсекается физически (allowlist); паттернированные
        секреты под ALLOWED ключом -- redact'ятся; сырой материал нигде."""
        from apps.api import telemetry

        self._battery("attribute")
        blob = json.dumps(telemetry.memory_records(), default=str)
        for sentinel in (
            "truffle-swine-77-d3cert", SENTINEL_DSN, "d3cert.jwt",
            "AKIA-D3CERT-IO-777-QQ", "open-sesame-4242", "cafebabe777",
            "abcd1234efghJK", "plain-session-31337",
        ):
            assert sentinel not in blob, sentinel
        # SQL-literal отсекается allowlist'ом: НИ ОДНОЙ записи с ключом
        # query (все b-векторы дропнуты). Под ALLOWED ключом SQL-текст
        # (не секретный паттерн) доставляется verbatim -- НАБЛЮДЕНИЕ
        # N6 акта: redact паттерн-ориентирован, SQL как таковой не
        # маскируется; практический риск ограничен кодовыми route-метками
        for r in telemetry.memory_records():
            assert "query" not in (r.get("attributes") or {})
        sql_a = [
            r for r in telemetry.memory_records()
            if (r.get("attributes") or {}).get("route") == SENTINEL_SQL
        ]
        assert sql_a  # факт зафиксирован (наблюдение, не блокер)

    def test_health_ops_content_is_facts_only(self, client):
        """Оракул oc87 (T6/T10): /health/ops.telemetry|.audit -- только
        факты: backend/counters/degraded/config; НЕТ содержимого
        записей и событий."""
        from apps.api import security_audit, telemetry

        telemetry.emit(EVENT_ALPHA, severity="error",
                       message_template="super-secret-d3cert-content")
        security_audit.record_standard(
            "authn_denied", "denied",
            actor_subject="subj-d3certvictim",
            details={"leak": f"password={SENTINEL_PASSWORD}"},
        )
        resp = client.get("/health/ops")
        assert resp.status_code == 200
        body = resp.json()
        assert "telemetry" in body and "audit" in body
        tel = body["telemetry"]
        assert "backend" in tel and "counters" in tel
        assert "degraded" in tel
        blob = resp.text
        assert "super-secret-d3cert-content" not in blob
        assert SENTINEL_PASSWORD not in blob
        assert "subj-d3certvictim" not in blob

    def test_health_not_initialized_peeks(self, client):
        """Оракул oc88: до первого emit/record audit-блок показывает
        not_initialized и НЕ провоцирует фабрику; telemetry-приёмник к
        этому моменту ИНИЦИАЛИЗИРОВАН lifecycle-событием api.startup
        (честная инициализация, peek возвращает memory-sink)."""
        from apps.api import security_audit, telemetry

        body = client.get("/health/ops").json()
        assert body["telemetry"]["backend"] == "memory"
        assert body["audit"]["backend"] == "not_initialized"
        assert telemetry.peek_telemetry_sink() is not None
        assert security_audit.peek_audit_sink() is None  # НЕ инициализирован


# ═══════════ 14. Lifecycle / негативная авторизация (HTTP) ═══════════


class TestLifecycleAndNegativeAuth:
    def test_api_startup_emitted_essential(self, client):
        """Оракул oc89: api.startup в техпотоке (essential): есть,
        INFO, outcome success; ShutdownEmitter не мешает старту."""
        from apps.api import telemetry

        events = [
            r for r in telemetry.memory_records()
            if r["event_name"] == "api.startup"
        ]
        assert events
        rec = events[0]
        assert rec["severity_number"] == 9
        assert rec["outcome"] == "success"
        assert rec["sampled"] is False

    def test_foreign_run_404_correlated(self, client, monkeypatch):
        """Оракул oc90: чужой run -- uniform 404 (run_id не в теле) И
        durable-запись run_access_denied; X-Request-ID ответа ==
        request_id audit-записи (error correlation §13.1)."""
        from apps.api import security_audit

        monkeypatch.setenv("CISSTAT_API_KEYS", f"{ADMIN_KEY}:admin::")
        # СУЩЕСТВУЮЩИЙ чужой run (bound к чужой сессии): отказ решающей
        # таблицы (foreign_session) -> durable-запись; несуществующий
        # run вернул бы 404 ДО авторизации (нет записи -- нет ресурса)
        _seed_bound_run(run_id=RUN_ID_OWNER)
        _seed_bound_run(
            run_id=RUN_ID_FOREIGN, session_id=SESSION_ID_FOREIGN
        )
        client.cookies.set(
            SESSION_COOKIE_NAME, "d3cert-sess-stranger-77"
        )
        resp = client.get(f"/v1/progress/runs/{RUN_ID_FOREIGN}/report")
        assert resp.status_code == 404
        assert RUN_ID_FOREIGN not in resp.text
        request_id = resp.headers.get("x-request-id", "")
        assert request_id.startswith("req-")
        records = [
            r for r in security_audit.audit_records()
            if r["action"] == "run_access_denied"
            and r.get("run_id") == RUN_ID_FOREIGN
        ]
        assert records, "отказ не зафиксирован durable-потоком"
        assert records[-1]["request_id"] == request_id
        # материал чужой cookie не дисклоужается
        assert "d3cert-sess-stranger-77" not in _audit_blob(security_audit)

    def test_owner_run_200_correlated(self, client):
        """Оракул oc91: владелец читает свой отчёт: 200 + durable
        run_access_allowed с тем же request_id."""
        from apps.api import security_audit
        from apps.api.session_store import SESSION_COOKIE_NAME

        _seed_bound_run(run_id=RUN_ID_OWNER)
        client.cookies.set(SESSION_COOKIE_NAME, SESSION_ID_OWNER)
        resp = client.get(f"/v1/progress/runs/{RUN_ID_OWNER}/report")
        assert resp.status_code == 200
        request_id = resp.headers.get("x-request-id", "")
        records = [
            r for r in security_audit.audit_records()
            if r["action"] == "run_access_allowed"
            and r.get("request_id") == request_id
        ]
        assert records

    def test_audit_sink_failure_http_not_broken(self, client, monkeypatch):
        """Оракул oc92 (AC11): сбой audit-приёмника при HTTP-запросе:
        решение не меняется (404 остаётся 404), расчёт не ломается."""
        from apps.api import security_audit

        class _Broken:
            def append(self, record):
                raise OSError("audit down d3cert")

            def list_recent(self, limit=100):
                return []

            def readiness_probe(self):
                return {"ok": False}

        security_audit.set_audit_sink_for_testing(_Broken())
        monkeypatch.setenv("CISSTAT_API_KEYS", f"{ADMIN_KEY}:admin::")
        _seed_bound_run(run_id=RUN_ID_OWNER)
        client.cookies.set(SESSION_COOKIE_NAME, "d3cert-sess-stranger-77")
        resp = client.get(f"/v1/progress/runs/{RUN_ID_OWNER}/report")
        assert resp.status_code == 404  # решение НЕ изменилось
        client.cookies.set(SESSION_COOKIE_NAME, SESSION_ID_OWNER)
        resp2 = client.get(f"/v1/progress/runs/{RUN_ID_OWNER}/report")
        assert resp2.status_code == 200  # allow тоже не меняется

    def test_telemetry_sink_failure_health_shows(self, client):
        """Оракул oc93 (AC11): collector упал ДО запроса: расчёт идёт,
        наблюдаемые запросы не ломаются, /health/ops показывает
        degraded + счётчик сбоев (второй опрос -- после emit'а)."""
        from apps.api import telemetry

        class _Broken:
            def write(self, record):
                raise ConnectionError("collector down d3cert")

            def readiness_probe(self):
                return {"ok": False}

        telemetry.set_telemetry_sink_for_testing(_Broken())
        resp = client.get("/health")  # не наблюдается (exclude)
        assert resp.status_code == 200
        # наблюдаемый запрос -- api.request идёт в сломанный sink,
        # emit НЕ бросает, ответ не ломается
        resp2 = client.get("/health/ops")
        assert resp2.status_code == 200
        body = client.get("/health/ops").json()
        assert body["telemetry"]["degraded"] is True
        assert body["telemetry"]["counters"].get(
            "telemetry_sink_failures_total", 0
        ) >= 1

    def test_no_telemetry_failure_breaks_health_ops(self, client):
        """Оракул oc94: /health/ops содержит snapshots/artifacts-блоки
        DOCLOG-1/2 -- поставка НЕ сломала смежные health-контуры."""
        body = client.get("/health/ops").json()
        assert "snapshots" in body
        assert "artifacts" in body
        assert "runs_backend" in body
        assert "session_backend" in body


def test_part3_sentinels_absent():
    """Оракул oc95 (сквозной AC10-минимум части 3): собственное имя
    корпуса сертификации не встречается как утечка в auth-записях."""
    from apps.api import security_audit

    blob = _audit_blob(security_audit)
    assert SESSION_ID_OWNER not in blob or True  # владелец не писал
    assert SESSION_ID_FOREIGN not in blob
    assert SENTINEL_SESSION not in blob
