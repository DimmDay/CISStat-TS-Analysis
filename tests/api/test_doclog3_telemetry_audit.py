# tests/api/test_doclog3_telemetry_audit.py
"""Task DOCLOG-3 (spec_documentation_logging.md §13, §14, §19 строка
DOCLOG-3, §19.1, §20 AC10/AC11): telemetry/audit foundation --
structured logging, redaction/error correlation, отдельный durable
security audit, ops counters.

Критерий завершения (§19, строка DOCLOG-3): sentinel/negative
auth/collector failure проверки.

Оракулы на СВОИХ данных: sentinel-значения дизъюнктны repo-корпусу
( hunter2 / s3cret-db-pass / sk-live-d3 / deadbeefsig ...); изоляция
каждого теста -- паттерн test_doclog2_snapshots.py (свой
tmp_path/CISSTAT_DATA_DIR, сброс singleton-фабрик ВКЛЮЧАЯ telemetry/
audit/session). AC10: пароль/DSN/API-key/cookie/SQL literal/nested
exception/CRLF/signed URL sentinel отсутствуют в sink-записях, JSONL,
health и error responses. AC11: ошибка collector не ломает успешный
расчёт (spool+dropped+degraded видны); обязательный security audit при
защищённой выдаче fail-closed (MandatoryAuditFailure ДО выполнения
действия). Negative auth: чужой run -- uniform 404 (без утечки run_id)
И durable-запись отказа (audit -- серверный контекст, run_id там
РАЗРЕШЁН, значение cookie/ключа -- НЕТ).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from apps.api.session_store import SESSION_COOKIE_NAME

from apps.api import research_runs
from apps.api.identity import DEFAULT_TENANT_ID, SubjectRef
from apps.api.research_runs import ResearchRun
from apps.api.session_store import AnalysisSession

# ── Изоляция КАЖДОГО теста (паттерн test_doclog2_snapshots.py) ────────


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
    monkeypatch.delenv("CISSTAT_TELEMETRY_DEBUG", raising=False)
    monkeypatch.delenv("CISSTAT_TELEMETRY_SAMPLE_RATE", raising=False)
    monkeypatch.delenv("CISSTAT_STORAGE_MODE", raising=False)
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    from apps.api import security_audit, telemetry
    from apps.api.session_store import reset_session_store_for_testing

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
    from apps.api.main import app

    with TestClient(app) as test_client:
        yield test_client


# ── Сентинелы (дизъюнктны repo-корпусу и другим поставкам) ───────────

SENTINEL_PASSWORD = "hunter2-sentinel-d3"
SENTINEL_DSN = "postgres://svc-admin:s3cret-db-pass@db.host:5432/cis"
SENTINEL_KEY = "sk-live-d3abc123secret"
SENTINEL_COOKIE = "sid-cookie-d3value0123456789"
SENTINEL_SIGNATURE = "deadbeefsig-d3"
SENTINEL_SESSION = "sess-d3plaintext1234567890"


def _all_sink_payload() -> str:
    """Весь наблюдаемый вывод telemetry-контура одной строкой (для
    sentinel-проверок AC10): records + JSONL + status/health."""
    from apps.api import security_audit, telemetry

    parts: list[str] = []
    for record in telemetry.memory_records():
        parts.append(json.dumps(record, ensure_ascii=False, default=str))
        parts.append(telemetry.to_jsonl(record))
    for record in security_audit.audit_records():
        parts.append(json.dumps(record, ensure_ascii=False, default=str))
    parts.append(json.dumps(telemetry.telemetry_status(), default=str))
    parts.append(json.dumps(security_audit.audit_status(), default=str))
    return "\n".join(parts)


# ═════════════════ 1. Контракт тех-события (§13.1) ═══════════════════


class TestTelemetryEventContract:
    def test_emit_delivers_contract_fields(self):
        from apps.api import telemetry

        ok = telemetry.emit(
            "test.contract", severity="info",
            message_template="Контракт события {x}",
            attributes={"stage": "unit"},
            outcome="success", duration_ms=12.5,
            request_id=telemetry.new_request_id(),
        )
        assert ok is True
        record = telemetry.memory_records()[-1]
        assert record["schema_version"] == "doclog.telemetry/1"
        assert record["event_name"] == "test.contract"
        assert record["severity_text"] == "INFO"
        assert record["severity_number"] == 9
        # occurred/observed различаются (OTel S3): оба ISO с зоной.
        for field in ("occurred_at", "observed_at"):
            value = record[field]
            assert isinstance(value, str) and value
            datetime.fromisoformat(value)  # парсится
        assert record["service"] == "cisstat-api"
        assert record["outcome"] == "success"
        assert record["duration_ms"] == 12.5
        assert record["request_id"].startswith("req-")

    def test_severity_map_otel_numbers(self):
        from apps.api import telemetry

        assert telemetry.SEVERITY_NUMBERS["trace"] == 1
        assert telemetry.SEVERITY_NUMBERS["debug"] == 5
        assert telemetry.SEVERITY_NUMBERS["info"] == 9
        assert telemetry.SEVERITY_NUMBERS["warn"] == 13
        assert telemetry.SEVERITY_NUMBERS["error"] == 17
        assert telemetry.SEVERITY_NUMBERS["fatal"] == 21

    def test_unknown_severity_fail_safe_to_info(self):
        from apps.api import telemetry

        ok = telemetry.emit("test.loud", severity="LOUD")
        assert ok is True
        record = telemetry.memory_records()[-1]
        assert record["severity_number"] == 9
        assert record["severity_text"] == "INFO"

    def test_trace_context_carried_when_valid(self):
        from apps.api import telemetry

        tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        telemetry.emit(
            "test.trace", traceparent=tp,
            request_id=telemetry.new_request_id(),
        )
        record = telemetry.memory_records()[-1]
        assert record["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert record["span_id"] == "00f067aa0ba902b7"

    def test_invalid_traceparent_not_trusted(self):
        """§13.1: доверие к внешнему caller не предполагается; мусорный
        traceparent игнорируется (событие не теряется, корреляции нет)."""
        from apps.api import telemetry

        for bad in (
            "", "garbage",
            "ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
            "00-4bf92f3577b34da6a3ce929d0e0e473-00f067aa0ba902b7-01",
            "00-4bf92f3577b34da6a3ce929d0e0e47zz-00f067aa0ba902b7-01",
            "00-4bf92f3577b34da6a3ce929d0e0e4736-not16hexspan-01",
        ):
            assert telemetry.parse_traceparent(bad) is None, bad

    def test_request_id_validation_boundary(self):
        from apps.api import telemetry

        rid = telemetry.new_request_id()
        assert rid.startswith("req-") and len(rid) == 4 + 12
        # Валидный внешний -- принимается (корреляция поддержки).
        assert telemetry.accept_request_id("abc-DEF_0123") == "abc-DEF_0123"
        # Невалидный (инъекция/длина/пустота) -- отклонён.
        for bad in ("", "short", "a" * 65, "bad id\r\nX-Inj: 1", " пробел"):
            assert telemetry.accept_request_id(bad) is None, bad

    def test_to_jsonl_roundtrip(self):
        from apps.api import telemetry

        telemetry.emit("test.jsonl", attributes={"route": "/x"},
                       request_id=telemetry.new_request_id())
        record = telemetry.memory_records()[-1]
        parsed = json.loads(telemetry.to_jsonl(record))
        assert parsed["event_name"] == "test.jsonl"

    def test_emitter_never_raises_on_garbage(self):
        """Эмиттер -- сквозной контур: мусорные входы не роняют расчёт."""
        from apps.api import telemetry

        assert telemetry.emit("test.garbage", attributes={"x": object()}) in (True, False)
        assert telemetry.emit("test.garbage", duration_ms=float("nan")) in (True, False)


# ═════════════════ 2. Redaction sentinels (R08, AC10) ════════════════


class TestRedactionSentinels:
    CASES: list[tuple[str, str]] = [
        ("kv-password", f"login failed: password={SENTINEL_PASSWORD}"),
        ("dsn", f"connect error at {SENTINEL_DSN}"),
        ("bearer", f"Authorization: Bearer {SENTINEL_KEY}"),
        ("api-key-header", f"X-API-Key: {SENTINEL_KEY}"),
        ("cookie", f"Cookie: session={SENTINEL_COOKIE}"),
        (
            "signed-url",
            "https://objects.example.com/report.pdf"
            f"?X-Amz-Signature={SENTINEL_SIGNATURE}&X-Amz-Expires=60",
        ),
        ("url-encoded", f"retry with password%3D{SENTINEL_PASSWORD}%26next=1"),
        ("multiline", f"a=1\npassword={SENTINEL_PASSWORD}\nb=2"),
        ("session-id", f"stale session_id={SENTINEL_SESSION}"),
        ("crlf-injection", f"ok\r\nINFO fake-event password={SENTINEL_PASSWORD}"),
    ]

    def _assert_absent(self) -> None:
        payload = _all_sink_payload()
        for secret in (
            SENTINEL_PASSWORD, "s3cret-db-pass", SENTINEL_KEY,
            SENTINEL_COOKIE, SENTINEL_SIGNATURE, SENTINEL_SESSION,
        ):
            assert secret not in payload, secret

    @pytest.mark.parametrize(("case", "message"), CASES, ids=[c[0] for c in CASES])
    def test_message_channel(self, case, message):
        from apps.api import telemetry

        telemetry.emit("test.redact", message_template=message,
                       request_id=telemetry.new_request_id())
        self._assert_absent()

    @pytest.mark.parametrize(("case", "message"), CASES, ids=[c[0] for c in CASES])
    def test_attribute_value_channel(self, case, message):
        """R08: allowlist-атрибут всё равно проходит redaction -- второй
        барьер после allowlist."""
        from apps.api import telemetry

        telemetry.emit("test.redact-attr", attributes={"detail": message},
                       request_id=telemetry.new_request_id())
        self._assert_absent()

    def test_sql_literal_attribute_dropped_by_allowlist(self):
        """SQL с literals не записывается: ключ 'sql' вне allowlist --
        атрибут целиком отброшен (первый барьер)."""
        from apps.api import telemetry

        ok = telemetry.emit(
            "test.sql", attributes={"sql": f"SELECT * FROM t WHERE pw='{SENTINEL_PASSWORD}'"},
            request_id=telemetry.new_request_id(),
        )
        assert ok is True
        record = telemetry.memory_records()[-1]
        assert "sql" not in (record.get("attributes") or {})
        self._assert_absent()

    def test_health_and_error_response_free_of_sentinels(self, client):
        """AC10: health и error response тоже чисты (X-Request-ID --
        единственная корреляция в ответе)."""
        resp = client.get("/health/ops")
        assert resp.status_code == 200
        body = json.dumps(resp.json(), ensure_ascii=False)
        for secret in (SENTINEL_PASSWORD, SENTINEL_KEY, SENTINEL_COOKIE):
            assert secret not in body
        missing = client.get("/v1/progress/runs/RUN-D3NOPE01")
        assert missing.status_code == 404
        assert SENTINEL_PASSWORD not in missing.text

    def test_subject_surrogate_not_material(self):
        """§13.3: лог использует независимый subject surrogate, не
        principal_id/API-key/cookie как есть."""
        from apps.api import telemetry

        raw_material = "raw-cookie-d3-material-9876543210"
        telemetry.emit(
            "test.subject", subject_material=raw_material,
            request_id=telemetry.new_request_id(),
        )
        record = telemetry.memory_records()[-1]
        assert record.get("subject_surrogate", "").startswith("subj-")
        payload = _all_sink_payload()
        assert raw_material not in payload

    def test_length_clip(self):
        from apps.api import telemetry

        huge = "x" * 100000
        telemetry.emit("test.huge", message_template=huge,
                       request_id=telemetry.new_request_id())
        record = telemetry.memory_records()[-1]
        assert len(record["message_template"] or "") <= 600


# ═════════════════ 3. Stack cleanup / error correlation (§13.3) ══════


class TestCleanException:
    def test_chain_walked_and_redacted(self):
        from apps.api import telemetry

        try:
            try:
                raise KeyError(f"inner password={SENTINEL_PASSWORD}")
            except KeyError as inner:
                raise ValueError(f"outer token={SENTINEL_KEY}") from inner
        except ValueError as exc:
            cleaned = telemetry.clean_exception(exc)
        assert cleaned["error_code"] == "ValueError"
        assert SENTINEL_KEY not in json.dumps(cleaned)
        assert SENTINEL_PASSWORD not in json.dumps(cleaned)
        assert len(cleaned["chain"]) == 2
        assert cleaned["chain"][1]["error_code"] == "KeyError"

    def test_no_locals_no_args_no_source(self):
        """Очищенный stack: без locals/аргументов/исходников; только
        модуль/функция/строка (§13.3)."""
        from apps.api import telemetry

        secret_local = f"local-secret-{SENTINEL_PASSWORD}"

        def _boom():
            payload = secret_local  # локальная переменная с секретом
            raise RuntimeError(f"boom {payload}")

        try:
            _boom()
        except RuntimeError as exc:
            cleaned = telemetry.clean_exception(exc)
        dumped = json.dumps(cleaned, ensure_ascii=False)
        assert SENTINEL_PASSWORD not in dumped
        assert "payload" not in dumped  # locals не сериализуются
        frames = cleaned["stack"]
        assert frames and all(
            set(frame) <= {"module", "function", "lineno"} for frame in frames
        )

    def test_fingerprint_stable_and_discriminating(self):
        from apps.api import telemetry

        def _raise_a():
            raise RuntimeError("a")

        def _raise_b():
            raise ValueError("b")

        def _capture(thrower) -> str:
            # Единый call-site: fingerprint стабилен для одного места
            # возникновения (кадры test-функции не различаются).
            try:
                thrower()
            except Exception as exc:
                return telemetry.clean_exception(exc)["error_fingerprint"]
            raise AssertionError("unreachable")  # pragma: no cover

        fp_a1 = _capture(_raise_a)
        fp_a2 = _capture(_raise_a)
        fp_b = _capture(_raise_b)
        assert fp_a1 == fp_a2
        assert fp_a1 != fp_b


# ═════════════════ 4. Allowlist (R08: первый барьер) ═════════════════


class TestAttributeAllowlist:
    def test_known_key_passes_unknown_dropped(self):
        from apps.api import telemetry

        before = telemetry.telemetry_status()["counters"].get(
            "telemetry_attr_dropped_total", 0
        )
        telemetry.emit(
            "test.allow",
            attributes={"route": "/v1/x", "evil_user_data": "nope-d3"},
            request_id=telemetry.new_request_id(),
        )
        record = telemetry.memory_records()[-1]
        assert record["attributes"]["route"] == "/v1/x"
        assert "evil_user_data" not in record["attributes"]
        after = telemetry.telemetry_status()["counters"].get(
            "telemetry_attr_dropped_total", 0
        )
        assert after == before + 1

    def test_allowlist_catalog_has_platform_keys(self):
        from apps.api import telemetry

        for key in ("route", "stage", "status_class", "kind", "outcome",
                    "reason_code", "service"):
            assert key in telemetry.ALLOWED_ATTRIBUTE_KEYS, key


# ═════════════════ 5. DEBUG-гейтинг и sampling (§13.1) ══════════════


class TestDebugGatingAndSampling:
    def test_debug_off_by_default(self):
        from apps.api import telemetry

        assert telemetry.emit("test.debug", severity="debug") is False
        counters = telemetry.telemetry_status()["counters"]
        assert counters.get("telemetry_debug_suppressed_total", 0) == 1
        assert telemetry.memory_records() == []

    def test_debug_enabled_by_env(self, monkeypatch):
        from apps.api import telemetry

        monkeypatch.setenv("CISSTAT_TELEMETRY_DEBUG", "1")
        assert telemetry.emit("test.debug", severity="debug") is True
        assert telemetry.memory_records()[-1]["severity_number"] == 5

    def test_noisy_read_sampling_rate_zero_drops_info_get(self, monkeypatch):
        from apps.api import telemetry

        monkeypatch.setenv("CISSTAT_TELEMETRY_SAMPLE_RATE", "0")
        assert telemetry.emit(
            "test.noisy", sample_class="noisy_read",
            request_id=telemetry.new_request_id(),
        ) is False
        counters = telemetry.telemetry_status()["counters"]
        assert counters.get("telemetry_sampled_out_total", 0) == 1

    def test_warn_never_sampled(self, monkeypatch):
        from apps.api import telemetry

        monkeypatch.setenv("CISSTAT_TELEMETRY_SAMPLE_RATE", "0")
        assert telemetry.emit(
            "test.warn", severity="warn", sample_class="noisy_read",
            request_id=telemetry.new_request_id(),
        ) is True
        assert telemetry.memory_records()[-1]["severity_number"] == 13

    def test_essential_never_sampled(self, monkeypatch):
        from apps.api import telemetry

        monkeypatch.setenv("CISSTAT_TELEMETRY_SAMPLE_RATE", "0")
        assert telemetry.emit(
            "test.essential", essential=True, sample_class="noisy_read",
            request_id=telemetry.new_request_id(),
        ) is True

    def test_default_rate_one_delivers_all(self):
        from apps.api import telemetry

        for i in range(5):
            assert telemetry.emit(
                f"test.noisy.{i}", sample_class="noisy_read",
                request_id=telemetry.new_request_id(),
            ) is True
        assert len(telemetry.memory_records()) == 5


# ═════════════════ 6. Collector failure / spool / dropped (AC11) ═════


class _BrokenSink:
    """Collector, который всегда недоступен (§13.2/§14.1)."""

    def write(self, record) -> bool:
        raise RuntimeError(f"collector down {SENTINEL_PASSWORD}")

    def readiness_probe(self) -> dict:
        return {"ok": False, "backend": "memory-broken"}


class TestCollectorFailure:
    def test_sink_failure_does_not_break_caller(self):
        """AC11: недоступность collector НЕ роняет расчёт: emit
        возвращает False, событие в bounded spool, деградация видна."""
        from apps.api import telemetry

        telemetry.set_telemetry_sink_for_testing(_BrokenSink())
        assert telemetry.emit("test.ac11", request_id=telemetry.new_request_id()) is False
        status = telemetry.telemetry_status()
        assert status["degraded"] is True
        assert status["counters"].get("telemetry_sink_failures_total", 0) >= 1
        assert status["spool_size"] == 1
        # Секрет из exception коллектора не просочился.
        assert SENTINEL_PASSWORD not in json.dumps(status)

    def test_spool_overflow_visible_as_dropped(self):
        """§13.2: переполнение очереди видимо через dropped_records."""
        from apps.api import telemetry

        telemetry.set_telemetry_sink_for_testing(_BrokenSink())
        emitted = 0
        for i in range(telemetry.SPOOL_MAX + 5):
            if telemetry.emit(f"test.overflow.{i}",
                              request_id=telemetry.new_request_id()):
                emitted += 1
        status = telemetry.telemetry_status()
        assert emitted == 0
        assert status["spool_size"] == telemetry.SPOOL_MAX
        assert status["counters"].get("telemetry_dropped_total", 0) == 5

    def test_flush_spool_after_recovery(self):
        from apps.api import telemetry

        telemetry.set_telemetry_sink_for_testing(_BrokenSink())
        telemetry.emit("test.flush", request_id=telemetry.new_request_id())
        assert telemetry.telemetry_status()["spool_size"] == 1
        telemetry.set_telemetry_sink_for_testing(None)  # восстановление
        flushed = telemetry.flush_spool()
        assert flushed == 1
        assert telemetry.telemetry_status()["spool_size"] == 0
        assert telemetry.memory_records()[-1]["event_name"] == "test.flush"

    def test_memory_sink_bounded_overflow_dropped(self):
        """§13.2: переполнение очереди видимо через dropped_records
        (свой bounded sink)."""
        from apps.api import telemetry

        telemetry.set_telemetry_sink_for_testing(
            telemetry.MemoryTelemetrySink(maxsize=3)
        )
        for i in range(5):
            telemetry.emit(f"test.bounded.{i}",
                           request_id=telemetry.new_request_id())
        assert len(telemetry.memory_records()) == 3
        status = telemetry.telemetry_status()
        assert status["counters"].get("telemetry_dropped_total", 0) >= 2

    def test_redaction_pipeline_failure_p0(self, monkeypatch):
        """§13.4 P0: сбой redaction pipeline -- событие заменяется
        минимальным безопасным, сырой контент нигде не появляется."""
        from apps.api import telemetry

        def _boom(value, limit=300):
            raise RuntimeError("redactor down")

        monkeypatch.setattr(telemetry, "redact_text", _boom)
        telemetry.emit("test.p0", message_template=f"secret {SENTINEL_PASSWORD}",
                       request_id=telemetry.new_request_id())
        payload = _all_sink_payload()
        assert SENTINEL_PASSWORD not in payload
        counters = telemetry.telemetry_status()["counters"]
        assert counters.get("telemetry_redaction_failures_total", 0) == 1
        names = [r["event_name"] for r in telemetry.memory_records()]
        assert "telemetry.redaction_failed" in names

    def test_emergency_sink_bounded(self, monkeypatch):
        """Рекурсивный «ошибка записи лога» ограничен fallback
        emergency sink + счётчиком (§13.2)."""
        from apps.api import telemetry

        def _boom(record):
            raise RuntimeError("sink exploded")

        monkeypatch.setattr(telemetry, "_dispatch_to_sink", _boom)
        for i in range(telemetry.EMERGENCY_MAX + 10):
            telemetry.emit(f"test.emergency.{i}",
                           request_id=telemetry.new_request_id())
        assert telemetry.telemetry_status()["counters"].get(
            "telemetry_emergency_total", 0
        ) == telemetry.EMERGENCY_MAX + 10

    def test_fatal_severity_carried(self):
        from apps.api import telemetry

        telemetry.emit("test.fatal", severity="fatal",
                       request_id=telemetry.new_request_id())
        assert telemetry.memory_records()[-1]["severity_number"] == 21


# ═════════════════ 7. Security audit -- контракт (§14.1) ═════════════


class TestAuditContract:
    def test_record_fields_complete(self):
        from apps.api import security_audit

        audit_id = security_audit.record_standard(
            "authz_denied", decision="denied",
            actor_subject="subj-aa11bb22cc33dd44", actor_via="session_surrogate",
            tenant_id=DEFAULT_TENANT_ID,
            resource_kind="run", resource_id="RUN-D3AUD0001",
            resource_version="ctx-1",
            policy_basis="R09 object authorization",
            request_id="req-0123456789ab", run_id="RUN-D3AUD0001",
            details={"reason_code": "foreign_session"},
        )
        assert audit_id and audit_id.startswith("aud-")
        record = security_audit.audit_records()[-1]
        assert record["schema_version"] == "doclog.security_audit/1"
        # §14.1: кто/когда/tenant/resource/version/действие/решение/
        # основание/корреляция.
        for field in (
            "occurred_at", "actor_subject", "actor_via", "tenant_id",
            "action", "decision", "resource_kind", "resource_id",
            "resource_version", "policy_basis", "request_id", "run_id",
        ):
            assert field in record, field
        assert record["decision"] == "denied"
        datetime.fromisoformat(record["occurred_at"])

    def test_download_triple_distinct_actions(self):
        """§14.1: download_requested / response_stream_started /
        response_stream_finished различаются; human_read_confirmed
        НЕ существует."""
        from apps.api import security_audit

        for action in ("download_requested", "response_stream_started",
                       "response_stream_finished"):
            assert action in security_audit.AUDIT_ACTIONS, action
        assert "human_read_confirmed" not in security_audit.AUDIT_ACTIONS

    def test_action_catalog_covers_subjects(self):
        """§14.1: каталог действий покрывает предмет аудита."""
        from apps.api import security_audit

        for action in (
            "authn_denied", "authz_denied", "grant_created", "grant_revoked",
            "protected_document_viewed", "download_requested",
            "document_approved", "document_published", "document_revoked",
            "template_changed", "retention_policy_changed",
            "audit_log_accessed", "cleanup_started", "restore_started",
            "integrity_verified", "integrity_failed",
        ):
            assert action in security_audit.AUDIT_ACTIONS, action

    def test_append_only_ordering(self):
        from apps.api import security_audit

        security_audit.record_standard("authn_denied", decision="denied",
                                       details={"attempt": 1})
        security_audit.record_standard("authn_denied", decision="denied",
                                       details={"attempt": 2})
        records = security_audit.audit_records()
        assert [r["details"]["attempt"] for r in records] == [1, 2]
        # Append-only: в коде sink'ов нет UPDATE/DELETE.
        module_text = Path(security_audit.__file__).read_text(encoding="utf-8")
        assert "UPDATE " not in module_text
        assert "DELETE FROM" not in module_text

    def test_details_redacted(self):
        """В аудит не копируются body документа и значение API-key
        (§14.1): details проходят тот же redaction."""
        from apps.api import security_audit

        security_audit.record_standard(
            "protected_document_viewed", decision="allowed",
            details={"note": f"key={SENTINEL_KEY} dsn={SENTINEL_DSN}"},
        )
        assert SENTINEL_KEY not in _all_sink_payload()
        assert "s3cret-db-pass" not in _all_sink_payload()

    def test_decision_aborted_supported(self):
        from apps.api import security_audit

        security_audit.record_standard("cleanup_started", decision="aborted")
        assert security_audit.audit_records()[-1]["decision"] == "aborted"

    def test_mandatory_fail_closed_on_sink_failure(self):
        """AC11: отсутствие возможности зафиксировать обязательный
        audit -- отказ ДО выполнения защищённого действия."""
        from apps.api import security_audit

        security_audit.set_audit_sink_for_testing(_BrokenAuditSink())
        with pytest.raises(security_audit.MandatoryAuditFailure):
            security_audit.record_mandatory(
                "document_published", decision="allowed",
                actor_subject="subj-aa11bb22cc33dd44",
            )

    def test_standard_best_effort_on_sink_failure(self):
        """Стандартные записи при сбое sink НЕ ломают поток решения
        (отказ уже принят/разрешён; деградация видна счётчиком)."""
        from apps.api import security_audit

        security_audit.set_audit_sink_for_testing(_BrokenAuditSink())
        result = security_audit.record_standard(
            "run_access_denied", decision="denied",
            details={"reason_code": "foreign_session"},
        )
        assert result is None
        status = security_audit.audit_status()
        assert status["counters"].get("audit_write_failures_total", 0) == 1

    def test_mandatory_classes_catalog(self):
        """§14.1: publication/approval/выдача защищённых данных --
        обязательный класс (fail-closed)."""
        from apps.api import security_audit

        for action in ("document_published", "document_approved",
                       "protected_document_viewed", "download_requested",
                       "grant_created"):
            assert security_audit.AUDIT_REQUIREMENTS[action] == "mandatory"

    def test_broken_sink_exception_not_leaked(self):
        from apps.api import security_audit

        security_audit.set_audit_sink_for_testing(_BrokenAuditSink())
        with pytest.raises(security_audit.MandatoryAuditFailure) as excinfo:
            security_audit.record_mandatory("download_requested",
                                            decision="allowed")
        # Сообщение отказа не несёт сырого exception коллектора.
        assert SENTINEL_PASSWORD not in str(excinfo.value)


class _BrokenAuditSink:
    def append(self, record) -> bool:
        raise RuntimeError(f"audit sink down {SENTINEL_PASSWORD}")

    def list_recent(self, limit: int = 100) -> list:
        return []

    def readiness_probe(self) -> dict:
        return {"ok": False, "backend": "memory-broken"}


# ═════════════════ 8. Audit-фабрики (паритет snapshot-фабрик) ════════


class TestAuditFactories:
    def test_default_memory_backend(self):
        from apps.api import security_audit

        sink = security_audit.get_audit_sink()
        assert isinstance(sink, security_audit.MemoryAuditSink)

    def test_peek_before_init_is_none(self):
        from apps.api import security_audit

        assert security_audit.peek_audit_sink() is None

    def test_explicit_memory_backend_env(self, monkeypatch):
        from apps.api import security_audit

        monkeypatch.setenv("CISSTAT_AUDIT_BACKEND", "memory")
        assert isinstance(security_audit.get_audit_sink(),
                          security_audit.MemoryAuditSink)

    def test_postgres_backend_selected_with_dsn(self, monkeypatch):
        from apps.api import security_audit

        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost/d3")
        sink = security_audit.get_audit_sink()
        assert isinstance(sink, security_audit.PostgresAuditSink)

    def test_postgres_from_env_requires_dsn(self):
        from apps.api import security_audit

        with pytest.raises(RuntimeError):
            security_audit.PostgresAuditSink.from_env()

    def test_memory_sink_bounded_not_silent(self):
        """Audit НЕ теряет записи молча: переполнение memory-приёмника
        -- счётчик + деградация в статусе."""
        from apps.api import security_audit

        security_audit.set_audit_sink_for_testing(
            security_audit.MemoryAuditSink(maxsize=2)
        )
        for i in range(4):
            security_audit.record_standard("authn_denied", decision="denied",
                                           details={"i": i})
        status = security_audit.audit_status()
        assert len(security_audit.audit_records()) == 2
        assert status["counters"].get("audit_dropped_total", 0) == 2
        assert status["degraded"] is True

    def test_audit_component_recorded_in_backend_state(self):
        from apps.api import security_audit
        from apps.api.storage_diagnostics import storage_backend_snapshot

        security_audit.get_audit_sink()
        snapshot = storage_backend_snapshot()
        assert "audit" in snapshot
        assert snapshot["audit"]["effective"] == "memory"


# ═════════════════ 9. Telemetry-фабрики ══════════════════════════════


class TestTelemetryFactories:
    def test_default_memory_backend(self):
        from apps.api import telemetry

        assert isinstance(telemetry.get_telemetry_sink(),
                          telemetry.MemoryTelemetrySink)

    def test_peek_before_init_is_none(self):
        from apps.api import telemetry

        assert telemetry.peek_telemetry_sink() is None

    def test_postgres_backend_selected_with_dsn(self, monkeypatch):
        from apps.api import telemetry

        monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost/d3")
        assert isinstance(telemetry.get_telemetry_sink(),
                          telemetry.PostgresTelemetrySink)

    def test_postgres_from_env_requires_dsn(self):
        from apps.api import telemetry

        with pytest.raises(RuntimeError):
            telemetry.PostgresTelemetrySink.from_env()

    def test_component_recorded_in_backend_state(self):
        from apps.api import telemetry
        from apps.api.storage_diagnostics import storage_backend_snapshot

        telemetry.get_telemetry_sink()
        snapshot = storage_backend_snapshot()
        assert snapshot["telemetry"]["effective"] == "memory"


# ═════════════════ 10. Интеграция identity → durable-поток ═══════════

RUN_ID = "RUN-D3A00001"
SESSION_ID = "d3-owner-session"
FOREIGN_SESSION_ID = "d3-foreign-session"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_bound_run(run_id: str = RUN_ID, session_id: str = SESSION_ID) -> ResearchRun:
    from apps.api.research_runs import get_research_run_store

    run = ResearchRun(
        run_id=run_id,
        session_id=session_id,
        dataset_fingerprint="d3" * 16,
        dataset_name="doclog3-seed",
        target_column="value",
        target_column_source="user",
        created_at=_now_iso(),
        last_active_at=_now_iso(),
        status="active",
        owner_subject=SubjectRef.from_session(session_id).subject_id,
        tenant_id=DEFAULT_TENANT_ID,
        ownership="bound",
    )
    get_research_run_store().upsert_run(run)
    return run


class TestIdentityAuditIntegration:
    def test_denial_recorded_durable(self):
        """DOCLOG-0 обещал: «DOCLOG-3 заменит logger на durable-поток».
        Отказ решающей таблицы фиксируется в audit-приёмнике."""
        from apps.api import security_audit
        from apps.api.identity import authorize_run_access

        run = _seed_bound_run()
        decision = authorize_run_access(
            run, SubjectRef.from_session(FOREIGN_SESSION_ID),
            session_id=FOREIGN_SESSION_ID,
        )
        assert decision.allowed is False
        records = [
            r for r in security_audit.audit_records()
            if r["action"] == "run_access_denied"
        ]
        assert records, "отказ не зафиксирован durable-потоком"
        record = records[-1]
        assert record["decision"] == "denied"
        assert record["details"]["reason_code"] == "foreign_session"
        # Audit -- серверный контекст: run_id РАЗРЕШЁН; материал
        # сессии/ключа -- НЕТ.
        assert record["run_id"] == RUN_ID
        assert FOREIGN_SESSION_ID not in json.dumps(record)
        assert record["actor_subject"].startswith("subj-")

    def test_allow_recorded_durable(self):
        from apps.api import security_audit
        from apps.api.identity import authorize_run_access

        run = _seed_bound_run()
        decision = authorize_run_access(
            run, SubjectRef.from_session(SESSION_ID),
            session_id=SESSION_ID,
        )
        assert decision.allowed is True
        records = [
            r for r in security_audit.audit_records()
            if r["action"] == "run_access_allowed"
        ]
        assert records and records[-1]["details"]["reason_code"] == "owner"

    def test_audit_failure_never_flips_decision(self):
        """AC11-инвариант: сбой записи аудита не меняет уже принятого
        решения (deny остаётся deny, allow остаётся allow)."""
        from apps.api import security_audit
        from apps.api.identity import authorize_run_access

        security_audit.set_audit_sink_for_testing(_BrokenAuditSink())
        run = _seed_bound_run()
        decision = authorize_run_access(
            run, SubjectRef.from_session(FOREIGN_SESSION_ID),
            session_id=FOREIGN_SESSION_ID,
        )
        assert decision.allowed is False
        assert decision.reason == "foreign_session"


# ═════════════════ 11. Интеграция auth: негативные auth-оракулы ══════


class TestAuthDenialAudit:
    def test_invalid_api_key_401_recorded(self, monkeypatch):
        """§14.1: аутентификационные отказы -- предмет аудита."""
        from apps.api import security_audit
        from apps.api.auth import get_current_principal

        monkeypatch.setenv("CISSTAT_API_KEYS", "d3-good-key:admin:")
        with pytest.raises(HTTPException) as excinfo:
            get_current_principal(x_api_key=f"bad-key-{SENTINEL_KEY}")
        assert excinfo.value.status_code == 401
        records = [
            r for r in security_audit.audit_records()
            if r["action"] == "authn_denied"
        ]
        assert records
        # Значение предъявленного ключа не дисклоужается (псевдоним).
        record = records[-1]
        assert SENTINEL_KEY not in json.dumps(record)
        assert record["actor_subject"].startswith("subj-")

    def test_non_admin_403_recorded(self):
        from apps.api import security_audit
        from apps.api.auth import require_admin_role
        from apps.api.plans import AuthenticatedPrincipal, PlanName, Role

        principal = AuthenticatedPrincipal(
            principal_id="d3-analyst-key",
            role=Role.INTERNAL_ANALYST, plan=PlanName.PROFESSIONAL,
        )
        with pytest.raises(HTTPException) as excinfo:
            require_admin_role(principal=principal)
        assert excinfo.value.status_code == 403
        records = [
            r for r in security_audit.audit_records()
            if r["action"] == "authz_denied"
        ]
        assert records
        assert "d3-analyst-key" not in json.dumps(records[-1])


# ═════════════════ 12. HTTP negative auth + X-Request-ID ════════════


class TestRunAccessHTTPAudit:
    def test_foreign_run_uniform_404_and_audit(self, client, monkeypatch):
        """Negative auth (§19): чужой run -- uniform 404 без run_id в
        теле И durable-запись отказа; X-Request-ID в ответе коррелирует
        с audit-записью (error correlation §13.1)."""
        from apps.api import security_audit

        monkeypatch.setenv("CISSTAT_API_KEYS", "d3-admin-key:admin:")
        _seed_bound_run()
        client.cookies.set(SESSION_COOKIE_NAME, FOREIGN_SESSION_ID)
        resp = client.get(f"/v1/progress/runs/{RUN_ID}/report")
        assert resp.status_code == 404
        assert RUN_ID not in resp.text
        request_id = resp.headers.get("x-request-id", "")
        assert request_id.startswith("req-")
        records = [
            r for r in security_audit.audit_records()
            if r["action"] == "run_access_denied"
            and r.get("run_id") == RUN_ID
        ]
        assert records
        # Корреляция request_id из ответа с durable-записью.
        assert records[-1].get("request_id") == request_id

    def test_owner_allowed_with_correlation(self, client, monkeypatch):
        from apps.api import security_audit

        monkeypatch.setenv("CISSTAT_API_KEYS", "d3-admin-key:admin:")
        _seed_bound_run()
        client.cookies.set(SESSION_COOKIE_NAME, SESSION_ID)
        resp = client.get(f"/v1/progress/runs/{RUN_ID}/report")
        assert resp.status_code == 200
        request_id = resp.headers.get("x-request-id", "")
        records = [
            r for r in security_audit.audit_records()
            if r["action"] == "run_access_allowed"
            and r.get("request_id") == request_id
        ]
        assert records


# ═════════════════ 13. Telemetry-запрос-контур (middleware) ══════════


def _mini_app() -> FastAPI:
    """Мини-приложение для юнит-проверки ASGI-middleware (без правки
    глобального main.app)."""
    from apps.api.telemetry import TelemetryContextMiddleware

    mini = FastAPI()
    mini.add_middleware(TelemetryContextMiddleware)

    @mini.get("/mini/ok")
    def _ok():
        return {"ok": True}

    @mini.get("/mini/boom")
    def _boom():
        raise RuntimeError(f"boom password={SENTINEL_PASSWORD}")

    return mini


class TestTelemetryMiddleware:
    def _client(self) -> TestClient:
        return TestClient(_mini_app(), raise_server_exceptions=False)

    def test_success_event_and_request_id_header(self):
        with self._client() as c:
            resp = c.get("/mini/ok")
        assert resp.status_code == 200
        assert resp.headers.get("x-request-id", "").startswith("req-")
        from apps.api import telemetry

        events = [r for r in telemetry.memory_records()
                  if r["event_name"] == "api.request"]
        assert events
        event = events[-1]
        assert event["attributes"]["route"] == "/mini/ok"
        assert event["attributes"]["status_class"] == "2xx"
        assert event["outcome"] == "success"
        assert event["duration_ms"] is not None
        assert event["request_id"] == resp.headers["x-request-id"]

    def test_incoming_valid_request_id_reused(self):
        with self._client() as c:
            resp = c.get("/mini/ok", headers={"X-Request-ID": "abc-DEF_0123"})
        assert resp.headers.get("x-request-id") == "abc-DEF_0123"

    def test_incoming_invalid_request_id_regenerated(self):
        with self._client() as c:
            resp = c.get("/mini/ok", headers={"X-Request-ID": "bad id\r\nX: y"})
        rid = resp.headers.get("x-request-id", "")
        assert rid.startswith("req-") and "\r" not in rid and "\n" not in rid

    def test_traceparent_validated(self):
        tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        with self._client() as c:
            c.get("/mini/ok", headers={"traceparent": tp})
        from apps.api import telemetry

        event = [r for r in telemetry.memory_records()
                 if r["event_name"] == "api.request"][-1]
        assert event["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
        assert event["span_id"] == "00f067aa0ba902b7"

    def test_unhandled_exception_error_event_redacted(self):
        with self._client() as c:
            resp = c.get("/mini/boom")
        assert resp.status_code == 500
        assert SENTINEL_PASSWORD not in resp.text
        from apps.api import telemetry

        events = [r for r in telemetry.memory_records()
                  if r["event_name"] == "api.request"]
        event = events[-1]
        assert event["severity_number"] == 17  # ERROR
        assert event["outcome"] == "server_error"
        assert event["error_code"] == "RuntimeError"
        assert SENTINEL_PASSWORD not in json.dumps(event)

    def test_unmatched_route_low_cardinality_label(self):
        with self._client() as c:
            c.get("/mini/missing")
        from apps.api import telemetry

        event = [r for r in telemetry.memory_records()
                 if r["event_name"] == "api.request"][-1]
        assert event["attributes"]["route"] == "unmatched"
        assert event["attributes"]["status_class"] == "4xx"

    def test_options_and_health_not_emitted(self):
        with self._client() as c:
            c.options("/mini/ok")
            c.get("/health")
        from apps.api import telemetry

        assert [r for r in telemetry.memory_records()
                if r["event_name"] == "api.request"] == []

    def test_noisy_get_sampled_post_not(self, monkeypatch):
        monkeypatch.setenv("CISSTAT_TELEMETRY_SAMPLE_RATE", "0")
        from apps.api.telemetry import TelemetryContextMiddleware

        mini = FastAPI()
        mini.add_middleware(TelemetryContextMiddleware)

        @mini.get("/mini/ok")
        def _ok():
            return {"ok": True}

        @mini.post("/mini/act")
        def _act():
            return {"ok": True}

        with TestClient(mini) as c:
            c.get("/mini/ok")
            c.post("/mini/act")
        from apps.api import telemetry

        names = [r["event_name"] for r in telemetry.memory_records()]
        assert "api.request" not in names or all(
            r["method"] == "POST"
            for r in telemetry.memory_records()
            if r["event_name"] == "api.request"
        )


# ═════════════════ 14. main.app wiring + /health/ops ═════════════════


class TestMainAppWiring:
    def test_request_id_header_on_main_app(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.headers.get("x-request-id", "").startswith("req-")

    def test_health_ops_blocks(self, client):
        resp = client.get("/health/ops")
        assert resp.status_code == 200
        body = resp.json()
        assert "telemetry" in body
        assert "audit" in body
        # Facts-only (T6/T10): никакого содержимого событий.
        assert "records" not in body["telemetry"]
        assert "records" not in body["audit"]

    def test_health_ops_free_of_sentinels_after_events(self, client):
        from apps.api import telemetry

        telemetry.emit("test.leak-probe",
                       message_template=f"secret {SENTINEL_PASSWORD}",
                       request_id=telemetry.new_request_id())
        body = json.dumps(client.get("/health/ops").json(), ensure_ascii=False)
        assert SENTINEL_PASSWORD not in body

    def test_no_new_http_surface(self, client):
        """Граница §19 (обновлено DOCLOG-4): маршруты /v1/documentation --
        ПЛАНОВАЯ поставка DOCLOG-4 (§17: «префикс нового API --
        /v1/documentation»); журналы UI -- DOCLOG-7 (/v1/audit|/v1/logs
        по-прежнему отсутствуют)."""
        from apps.api.main import app

        paths = {getattr(r, "path", "") for r in app.routes}
        # DOCLOG-4 (выполнено): выдача документов присутствует.
        assert any(p.startswith("/v1/documentation") for p in paths)
        # DOCLOG-7 (будущее): журналы/audit-UI ещё не выдаются.
        assert not any(p.startswith("/v1/audit") for p in paths)
        assert not any(p.startswith("/v1/logs") for p in paths)


# ═════════════════ 15. Миграция 0009 (паритет, append-only) ══════════


class TestMigrations:
    def test_catalog_contains_0009(self):
        from apps.api.research_runs import MIGRATION_FILES

        names = [name for name, _statements in MIGRATION_FILES]
        assert "0009_doclog3_telemetry_audit.sql" in names

    def test_migration_file_parity_with_catalog(self):
        """Паритет источников DDL (паттерн DOCLOG-1/2): файл-дубль
        каталога; проверяется КАЖДЫЙ файл каталога."""
        from apps.api.research_runs import MIGRATION_FILES

        def _norm(value: str) -> str:
            return " ".join(value.split())

        for name, statements in MIGRATION_FILES:
            text = (
                Path(__file__).resolve().parents[2]
                / "apps" / "api" / "migrations" / name
            ).read_text(encoding="utf-8")
            normalized = _norm(text)
            for statement in statements:
                assert _norm(statement) in normalized, (name, statement[:60])

    def test_ddl_is_append_only_no_fk_to_runs(self):
        """Audit/telemetry переживают удаление run (retention §16.1:
        365 дней аудита против lifecycle run) -- FK НЕТ намеренно."""
        from apps.api.research_runs import MIGRATION_STATEMENTS_0009

        ddl = "\n".join(MIGRATION_STATEMENTS_0009).lower()
        assert "create table if not exists telemetry_events" in ddl
        assert "create table if not exists security_audit_records" in ddl
        assert "references research_runs" not in ddl
        assert "on delete cascade" not in ddl
        # Append-only: ни одного UPDATE/DELETE в DDL.
        assert "update " not in ddl
        assert "delete from" not in ddl

    def test_indexes_present(self):
        from apps.api.research_runs import MIGRATION_STATEMENTS_0009

        ddl = "\n".join(MIGRATION_STATEMENTS_0009).lower()
        assert "idx_telemetry_events_time" in ddl
        assert "idx_security_audit_action" in ddl
        assert "idx_security_audit_request" in ddl

    def test_statement_counts(self):
        from apps.api.research_runs import MIGRATION_FILES, MIGRATION_STATEMENTS

        # DOCLOG-5 (обновлено): каталог пополнен 0011_doclog5_render_formats
        # (аддитивная: 4 ADD COLUMN + 1 CREATE INDEX = 5 statement;
        # 62 + 5 = 67).
        assert len(MIGRATION_FILES) == 11
        assert len(MIGRATION_STATEMENTS) == 67
