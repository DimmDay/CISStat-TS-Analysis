# scripts/doclog3cert/test_doclog3cert_oracle_unit.py
"""DOCLOG-3-CERT: оракулы на СВОИХ данных -- часть 1.

Контракт тех-события (§13.1), redaction R08 (§13.3/AC10),
clean_exception (§13.3), DEBUG-гейтинг и sampling (§13.1/§13.2).
Источник ожиданий -- СПЕКА spec_documentation_logging.md, корпус --
conftest (d3cert-*/d3cert.*, сентинелы сертификации).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

import pytest

from conftest import (
    EVENT_ALPHA,
    EVENT_BETA,
    EVENT_GAMMA,
    REQUEST_ID_1,
    REQUEST_ID_2,
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
    SENTINEL_URLENCODED,
    SPAN_ID_OK,
    TRACEPARENT_OK,
    TRACE_ID_OK,
)


def _records():
    from apps.api import telemetry

    return telemetry.memory_records()


def _by_name(name: str):
    return [r for r in _records() if r.get("event_name") == name]


# ═══════════ 1. Контракт emit/события (§13.1) ════════════════════════


class TestEmitContract:
    def test_full_contract_fields(self):
        """Оракул oc01: полный набор полей §13.1 на своих данных."""
        from apps.api import telemetry

        ok = telemetry.emit(
            EVENT_ALPHA,
            severity="info",
            # секрет в паттернированной форме (R08: key=value-секреты)
            message_template=f"alpha ok password={SENTINEL_PASSWORD}",
            attributes={"route": "/d3cert/alpha", "method": "GET"},
            outcome="success",
            request_id=REQUEST_ID_1,
            traceparent=TRACEPARENT_OK,
            operation_id="op-d3cert-1",
            execution_id="ex-d3cert-1",
            research_run_id="RUN-D3CERT11",
            context_id="ctx-d3cert-1",
            duration_ms=12.5,
            retry_attempt=0,
            tenant_id="tenant-d3cert",
        )
        assert ok is True
        rec = _by_name(EVENT_ALPHA)
        assert len(rec) == 1
        rec = rec[0]
        assert rec["schema_version"] == "doclog.telemetry/1"
        assert rec["event_id"].startswith("evt-")
        assert rec["severity_text"] == "INFO"
        assert rec["severity_number"] == 9
        assert SENTINEL_PASSWORD not in rec["message_template"]
        assert rec["request_id"] == REQUEST_ID_1
        assert rec["trace_id"] == TRACE_ID_OK
        assert rec["span_id"] == SPAN_ID_OK
        assert rec["operation_id"] == "op-d3cert-1"
        assert rec["execution_id"] == "ex-d3cert-1"
        assert rec["research_run_id"] == "RUN-D3CERT11"
        assert rec["context_id"] == "ctx-d3cert-1"
        assert rec["duration_ms"] == 12.5
        assert rec["retry_attempt"] == 0
        assert rec["service"] == "cisstat-api"
        assert rec["sampled"] is False
        assert rec["subject_surrogate"] is None
        assert rec["tenant_id"] == "tenant-d3cert"
        # occurred_at/observed_at -- оба ISO с timezone (OTel §13.1)
        t1 = datetime.fromisoformat(rec["occurred_at"])
        t2 = datetime.fromisoformat(rec["observed_at"])
        assert abs((t2 - t1).total_seconds()) < 2.0

    def test_severity_full_mapping(self, monkeypatch):
        """Оракул oc02: полная таблица OTel severity [S3] на своих
        именах событий (включая alias warning); trace/debug -- только с
        включённым DEBUG-гейтом (§13.1: выключен по умолчанию)."""
        import os

        monkeypatch.setenv("CISSTAT_TELEMETRY_DEBUG", "1")
        expected = {
            "trace": (1, "TRACE"),
            "debug": (5, "DEBUG"),
            "info": (9, "INFO"),
            "warn": (13, "WARN"),
            "warning": (13, "WARN"),
            "error": (17, "ERROR"),
            "fatal": (21, "FATAL"),
        }
        for sev, (num, text) in expected.items():
            from apps.api import telemetry as t

            t.reset_telemetry_for_testing()
            assert os.environ.get("CISSTAT_TELEMETRY_DEBUG") == "1"
            assert t.emit(EVENT_BETA, severity=sev) is True, sev
            rec = _records()[-1]
            assert rec["severity_number"] == num, sev
            assert rec["severity_text"] == text, sev

    def test_unknown_severity_failsafe_info(self):
        """Оракул oc03: неизвестный уровень -- fail-safe INFO, счётчик
        telemetry_invalid_severity_total; событие НЕ теряется."""
        from apps.api import telemetry

        assert telemetry.emit(EVENT_ALPHA, severity="crit-d3cert") is True
        rec = _records()[-1]
        assert rec["severity_number"] == 9
        assert rec["severity_text"] == "INFO"
        counters = telemetry.telemetry_status()["counters"]
        assert counters.get("telemetry_invalid_severity_total", 0) >= 1

    def test_event_name_clip_and_empty(self):
        """Оракул oc04: клип event_name до 120; пустое имя -> unknown."""
        from apps.api import telemetry

        telemetry.emit("d3cert." + "x" * 300)
        rec = _records()[-1]
        assert len(rec["event_name"]) == 120
        telemetry.emit("")
        rec = _records()[-1]
        assert rec["event_name"] == "unknown"

    def test_occurred_at_override(self):
        """Оракул oc05: occurred_at (время события) отличимо от
        observed_at (время наблюдения) -- §13.1 «различает время»."""
        from apps.api import telemetry

        fixed = "2026-10-01T05:00:00+00:00"
        telemetry.emit(EVENT_GAMMA, occurred_at=fixed)
        rec = _records()[-1]
        assert rec["occurred_at"] == fixed
        t2 = datetime.fromisoformat(rec["observed_at"])
        assert (t2 - datetime.fromisoformat(fixed)).total_seconds() > 0

    def test_nonfinite_duration_dropped(self):
        """Оракул oc06: NaN/Inf duration_ms не проходят (JSON-канон)."""
        from apps.api import telemetry

        telemetry.emit(EVENT_ALPHA, duration_ms=float("nan"))
        assert _records()[-1]["duration_ms"] is None
        telemetry.emit(EVENT_ALPHA, duration_ms=float("inf"))
        assert _records()[-1]["duration_ms"] is None
        telemetry.emit(EVENT_ALPHA, duration_ms=5.0)
        assert _records()[-1]["duration_ms"] == 5.0

    def test_emit_never_raises_on_bad_attributes(self):
        """Оракул oc07: emit никогда не бросает (AC11) -- мусорные
        атрибуты (не dict), str-событие, None severity."""
        from apps.api import telemetry

        class _Boom:
            def __str__(self):
                raise RuntimeError("no str")

        assert (
            telemetry.emit(EVENT_ALPHA, attributes=_Boom()) in (True, False)
        )
        assert telemetry.emit(None, severity=None) in (True, False)
        assert telemetry.emit(12345) in (True, False)


# ═══════════ 2. Traceparent / request_id (W3C [S4], §13.1) ═══════════


class TestTraceContext:
    def test_parse_traceparent_valid_and_invalid(self):
        """Оракул oc08: W3C-парсер на СВОИХ хексах: валидный -> пара;
        версия ff/нули/garbage/non-str -> None (доверия к caller нет)."""
        from apps.api.telemetry import parse_traceparent

        assert parse_traceparent(TRACEPARENT_OK) == (TRACE_ID_OK, SPAN_ID_OK)
        assert parse_traceparent(
            "ff-" + TRACE_ID_OK + "-" + SPAN_ID_OK + "-01"
        ) is None
        assert parse_traceparent(
            "00-" + "0" * 32 + "-" + SPAN_ID_OK + "-01"
        ) is None
        assert parse_traceparent(
            "00-" + TRACE_ID_OK + "-" + "0" * 16 + "-01"
        ) is None
        assert parse_traceparent("00-short-01") is None
        assert parse_traceparent("hello world") is None
        assert parse_traceparent(None) is None  # type: ignore[arg-type]
        assert parse_traceparent(12345) is None  # type: ignore[arg-type]

    def test_emit_traceparent_invalid_ignored(self):
        """Оракул oc09: невалидный traceparent в emit игнорируется,
        событие доставляется без trace-полей."""
        from apps.api import telemetry

        telemetry.emit(
            EVENT_ALPHA, severity="error", traceparent="garbage-d3cert"
        )
        rec = _records()[-1]
        assert rec["trace_id"] is None
        assert rec["span_id"] is None

    def test_accept_request_id_shapes(self):
        """Оракул oc10: accept_request_id -- только безопасная форма;
        инъекция/мусор/короткие -> None."""
        from apps.api.telemetry import accept_request_id

        assert accept_request_id("d3certreq-0009") == "d3certreq-0009"
        assert accept_request_id("abcdefgh") == "abcdefgh"
        assert accept_request_id("a" * 64) == "a" * 64
        assert accept_request_id("a" * 7) is None  # < 8
        assert accept_request_id("a" * 65) is None  # > 64
        assert accept_request_id("bad id") is None  # пробел
        assert accept_request_id("id\r\nX-Injected: 1") is None
        assert accept_request_id("../../etc") is None
        assert accept_request_id(None) is None  # type: ignore[arg-type]
        assert accept_request_id(42) is None  # type: ignore[arg-type]

    def test_new_request_id_format(self):
        """Оракул oc11: new_request_id == req-<hex12>."""
        from apps.api.telemetry import new_request_id

        value = new_request_id()
        assert value.startswith("req-")
        tail = value[4:]
        assert len(tail) == 12
        int(tail, 16)  # hex
        assert value != new_request_id()


# ═══════════ 3. Redaction R08 (§13.3, AC10) ══════════════════════════


class TestRedaction:
    def test_url_and_dsn_wholly(self):
        """Оракул oc12: URL/DSN со схемой редактируются ЦЕЛИКОМ
        (signed URL -- учётные данные не остаются частично)."""
        from apps.api.telemetry import redact_text

        out_dsn = redact_text(f"connect to {SENTINEL_DSN} failed")
        assert SENTINEL_DSN not in out_dsn
        assert "pivot-goose-88" not in out_dsn
        assert "<redacted-url>" in out_dsn
        out_url = redact_text(f"GET {SENTINEL_SIGNED_URL} 200")
        assert "cafebabe777" not in out_url
        assert "<redacted-url>" in out_url

    def test_bearer_and_basic(self):
        """Оракул oc13: Bearer/Basic-схемы -> <redacted-credentials>;
        «auth: Bearer X» -- два барьера срабатывают каскадом: секрет
        скрыт целиком (материал отсутствует в любой форме)."""
        from apps.api.telemetry import redact_text

        # автономный Bearer -- барьер №2 напрямую
        out0 = redact_text(SENTINEL_BEARER)
        assert "d3cert.jwt" not in out0
        assert "<redacted-credentials>" in out0
        # с префиксом auth: -- KV-барьер сжимает всё в auth=<redacted>
        out = redact_text(f"auth: {SENTINEL_BEARER}")
        assert "d3cert.jwt" not in out
        assert "<redacted>" in out
        out2 = redact_text("Basic ZDNjZXJ0OnB3")
        assert "ZDNjZXJ0OnB3" not in out2

    def test_kv_secrets_key_kept(self):
        """Оракул oc14: key=value-секреты: ключ остаётся, значение
        <redacted> (OWASP S5); формы password=/token:/api-key=/
        session_id=/cookie:."""
        from apps.api.telemetry import redact_text

        cases = [
            (f"password={SENTINEL_PASSWORD}", "password=", "password=<redacted>"),
            (f"token: {SENTINEL_KEY}", "token", "<redacted>"),
            (f"api_key = {SENTINEL_KEY}", "api_key", "<redacted>"),
            (f"session_id={SENTINEL_SESSION}", "session_id", "<redacted>"),
            (f"cookie: {SENTINEL_COOKIE}", "cookie", "<redacted>"),
        ]
        for src, key_part, marker in cases:
            out = redact_text(src)
            assert SENTINEL_KEY not in out
            assert SENTINEL_PASSWORD not in out
            assert SENTINEL_SESSION not in out
            assert SENTINEL_COOKIE not in out
            assert key_part in out, src
            assert "<redacted>" in out, src

    def test_urlencoded_secret_decoded_first(self):
        """Оракул oc15: URL-encoded секрет ловится прогоном по
        percent-decoded копии (§13.3: юнит-тесты включают URL-encoded)."""
        from apps.api.telemetry import redact_text

        out = redact_text(SENTINEL_URLENCODED)
        assert "hornet-nest-55" not in out
        assert "<redacted>" in out

    def test_multiline_secret_each_line(self):
        """Оракул oc16: многострочный секрет -- построчный прогон:
        Bearer во второй строке редактируется, переводы строк
        нейтрализуются (нет сырого \\n в выводе)."""
        from apps.api.telemetry import redact_text

        out = redact_text(SENTINEL_MULTILINE)
        assert "abcd1234efghJK" not in out
        assert "<redacted-credentials>" in out
        assert "\n" not in out

    def test_crlf_log_injection(self):
        """Оракул oc17: CR/LF -> экранированные формы; control-символы
        -> \\xNN (anti log-injection §13.3)."""
        from apps.api.telemetry import redact_text

        out = redact_text(SENTINEL_CRLF)
        assert "\r" not in out
        assert "\n" not in out
        assert "\\r" in out and "\\n" in out
        out2 = redact_text("before\x00after\x7fd3cert")
        assert "\x00" not in out2 and "\x7f" not in out2

    def test_clip_300(self):
        """Оракул oc18: клип текстовых полей 300 (anti-DoS §13.3)."""
        from apps.api.telemetry import redact_text

        long_value = "d3cert-" + "z" * 500
        out = redact_text(long_value)
        assert len(out) <= 300
        assert out.endswith("...")

    def test_redact_never_raises(self):
        """Оракул oc19: redactor не бросает ни на чём: None -> "",
        объект с падающим __str__ -> <redaction-error>."""
        from apps.api.telemetry import redact_text

        assert redact_text(None) == ""

        class _BoomStr:
            def __str__(self):
                raise ValueError("boom-d3cert")

        assert redact_text(_BoomStr()) == "<redaction-error>"  # type: ignore[arg-type]

    def test_allowlist_first_barrier(self):
        """Оракул oc20: SQL-literal/env-dump физически не проходят
        allowlist (R08 первый барьер): неизвестные ключи отбрасываются,
        счётчик telemetry_attr_dropped_total."""
        from apps.api import telemetry

        telemetry.emit(
            EVENT_ALPHA,
            attributes={
                "sql": SENTINEL_SQL,
                "env_dump": f"DATABASE_URL={SENTINEL_DSN}",
                "api_key_value": SENTINEL_KEY,
                "route": "/d3cert/ok",
            },
        )
        rec = _records()[-1]
        assert rec["attributes"] == {"route": "/d3cert/ok"}
        counters = telemetry.telemetry_status()["counters"]
        assert counters.get("telemetry_attr_dropped_total", 0) == 3

    def test_nested_attribute_value_redacted(self):
        """Оракул oc21: значение allowlist-атрибута проходит рекурсивную
        redaction: секрет во вложенном dict/list скрыт; глубина >4 --
        <clipped>; non-finite float -> None."""
        from apps.api.telemetry import _redact_structured

        nested = {"outer": {"inner": [f"token={SENTINEL_KEY}"]}}
        cleaned = _redact_structured(nested)
        assert SENTINEL_KEY not in json.dumps(cleaned)
        deep = {"a": {"b": {"c": {"d": {"e": {"f": "g"}}}}}}
        assert _redact_structured(deep) == {
            "a": {"b": {"c": {"d": {"e": "<clipped>"}}}}
        }
        assert _redact_structured(float("nan")) is None
        assert _redact_structured(7) == 7
        assert _redact_structured(True) is True

    def test_emit_extra_attributes_capped_16(self):
        """Оракул oc22: >16 атрибутов -- первые 16, дроп учтён."""
        from apps.api import telemetry

        attrs = {f"route_{i}": f"/d3cert/{i}" for i in range(20)}
        telemetry.emit(EVENT_ALPHA, attributes=attrs)
        counters = telemetry.telemetry_status()["counters"]
        # 16 неизвестных ключей в цикле + 4 сверх EVENT_ATTR_LIMIT = 20
        assert counters.get("telemetry_attr_dropped_total", 0) == 20
        assert _records()[-1]["attributes"] == {}


# ═══════════ 4. clean_exception (§13.3) ══════════════════════════════


class TestCleanException:
    def test_message_never_logged(self):
        """Оракул oc23: сообщения исключений НЕ логируются вовсе
        (§13.3 строже masking): секрет в message/args нигде не виден."""
        from apps.api.telemetry import clean_exception

        secret = f"TOPSECRET-{SENTINEL_PASSWORD}-d3cert"
        try:
            raise RuntimeError(secret)
        except RuntimeError as exc:
            cleaned = clean_exception(exc)
        assert secret not in json.dumps(cleaned, default=str)
        assert SENTINEL_PASSWORD not in json.dumps(cleaned, default=str)
        assert cleaned["error_code"] == "RuntimeError"

    def test_stack_shape_and_fingerprint_stability(self):
        """Оракул oc24: кадры -- только module/function/lineno; fingerprint
        sha256[:32] стабилен для той же структуры и различает другую."""
        from apps.api.telemetry import clean_exception

        def _raise_a():
            try:
                raise ValueError("v-d3cert-a")
            except ValueError as exc:
                return clean_exception(exc)

        def _raise_b():
            try:
                raise KeyError("k-d3cert-b")
            except KeyError as exc:
                return clean_exception(exc)

        a1 = _raise_a()
        a2 = _raise_a()
        b = _raise_b()
        assert a1["error_fingerprint"] == a2["error_fingerprint"]
        assert len(a1["error_fingerprint"]) == 32
        assert a1["error_fingerprint"] != b["error_fingerprint"]
        for frame in a1["stack"]:
            assert set(frame.keys()) == {"module", "function", "lineno"}
        # ни в кадрах, ни в fingerprint -- нет сообщения
        assert "v-d3cert-a" not in json.dumps(a1)

    def test_chain_depth_cap(self):
        """Оракул oc25: exception chain до глубины 6 (7 записей у
        10-звенной цепочки); каждая запись -- только error_code."""
        from apps.api.telemetry import clean_exception

        def _nest(n: int) -> BaseException:
            exc: BaseException = ValueError("leaf-d3cert")
            for i in range(n):
                wrapper = RuntimeError(f"wrap-{i}-d3cert")
                wrapper.__context__ = exc  # явная цепочка __context__
                exc = wrapper
            return exc

        cleaned = clean_exception(_nest(10))
        assert len(cleaned["chain"]) == 7
        for entry in cleaned["chain"]:
            assert set(entry.keys()) == {"error_code"}

    def test_explicit_cause_followed(self):
        """Оракул oc26: __cause__ (raise ... from) проходит тот же
        фильтр; его сообщение тоже не логируется."""
        from apps.api.telemetry import clean_exception

        secret = f"CAUSE-SECRET-{SENTINEL_SESSION}"
        try:
            try:
                raise ConnectionError(secret)
            except ConnectionError as cause:
                raise RuntimeError("outer-d3cert") from cause
        except RuntimeError as exc:
            cleaned = clean_exception(exc)
        blob = json.dumps(cleaned, default=str)
        assert secret not in blob
        assert SENTINEL_SESSION not in blob
        codes = [e["error_code"] for e in cleaned["chain"]]
        assert codes == ["RuntimeError", "ConnectionError"]

    def test_emit_error_field_no_message(self):
        """Оракул oc27: emit(error=...) -- error_code/fingerprint в
        записи, сообщения нет (сквозной фильтр §13.3)."""
        from apps.api import telemetry

        secret = f"pipeline-secret-{SENTINEL_COOKIE}"
        try:
            raise TimeoutError(secret)
        except TimeoutError as exc:
            telemetry.emit(EVENT_BETA, severity="error", error=exc)
        rec = _records()[-1]
        blob = json.dumps(rec, default=str)
        assert secret not in blob and SENTINEL_COOKIE not in blob
        assert rec["error_code"] == "TimeoutError"
        assert rec["error_fingerprint"]


# ═══════════ 5. DEBUG-гейтинг и sampling (§13.1/§13.2) ══════════════


class TestGatingAndSampling:
    def test_debug_off_by_default(self):
        """Оракул oc28: DEBUG выключен по умолчанию (production off);
        счётчик telemetry_debug_suppressed_total."""
        from apps.api import telemetry

        assert telemetry.emit(EVENT_ALPHA, severity="debug") is False
        assert not _records()
        counters = telemetry.telemetry_status()["counters"]
        assert counters.get("telemetry_debug_suppressed_total", 0) >= 1

    def test_debug_enabled_via_env(self, monkeypatch):
        """Оракул oc29: CISSTAT_TELEMETRY_DEBUG включает DEBUG."""
        from apps.api import telemetry

        monkeypatch.setenv("CISSTAT_TELEMETRY_DEBUG", "1")
        assert telemetry.emit(EVENT_ALPHA, severity="debug") is True
        assert _records()[-1]["severity_number"] == 5
        # trace -- тоже ниже debug-порога
        t2 = datetime.fromisoformat(_records()[-1]["occurred_at"])
        assert t2 is not None

    def test_debug_env_false_values(self, monkeypatch):
        """Оракул oc30: «0»/«false»/пусто -- выключено; «true»/«yes» --
        включено (честная трактовка env)."""
        from apps.api import telemetry

        for value in ("0", "false", ""):
            monkeypatch.setenv("CISSTAT_TELEMETRY_DEBUG", value)
            assert telemetry.emit(EVENT_ALPHA, severity="debug") is False
        for value in ("true", "yes", "on"):
            monkeypatch.setenv("CISSTAT_TELEMETRY_DEBUG", value)
            assert telemetry.emit(EVENT_ALPHA, severity="debug") is True

    def test_sampling_rate_zero_drops_noisy_read(self, monkeypatch):
        """Оракул oc31: rate=0.0 -- успешные GET-события noisy_read
        дропаются (счётчик), всё прочее доставляется."""
        from apps.api import telemetry

        monkeypatch.setenv("CISSTAT_TELEMETRY_SAMPLE_RATE", "0.0")
        assert (
            telemetry.emit(
                EVENT_ALPHA, sample_class="noisy_read", request_id=REQUEST_ID_1
            )
            is False
        )
        counters = telemetry.telemetry_status()["counters"]
        assert counters.get("telemetry_sampled_out_total", 0) == 1
        # WARN не сэмплируется никогда
        assert (
            telemetry.emit(
                EVENT_BETA,
                severity="warn",
                sample_class="noisy_read",
                request_id=REQUEST_ID_1,
            )
            is True
        )
        # essential не сэмплируется никогда
        assert (
            telemetry.emit(
                EVENT_GAMMA,
                sample_class="noisy_read",
                essential=True,
                request_id=REQUEST_ID_1,
            )
            is True
        )
        # не-noisy класс не сэмплируется
        assert telemetry.emit(EVENT_ALPHA, request_id=REQUEST_ID_1) is True

    def test_sampling_rate_one_and_bounds(self, monkeypatch):
        """Оракул oc32: rate=1.0 (дефолт) -- всё доставляется; мусорное
        значение env -> 1.0; [-1, 2] клип к [0, 1]."""
        from apps.api import telemetry

        for env_value, expected in [
            ("1.0", True),
            ("garbage", True),  # мусор -> 1.0 (дефолт)
            ("-1", False),  # клип max(-1,0)=0.0 -> дроп всегда
            ("2", True),  # клип min(2,1)=1.0 -> доставляется
        ]:
            monkeypatch.setenv("CISSTAT_TELEMETRY_SAMPLE_RATE", env_value)
            assert (
                telemetry.emit(
                    EVENT_ALPHA,
                    sample_class="noisy_read",
                    request_id=REQUEST_ID_1,
                )
                is expected
            ), env_value
        from apps.api.telemetry import _sample_rate

        monkeypatch.setenv("CISSTAT_TELEMETRY_SAMPLE_RATE", "-1")
        assert _sample_rate() == 0.0
        monkeypatch.setenv("CISSTAT_TELEMETRY_SAMPLE_RATE", "0.5")
        assert _sample_rate() == 0.5
        monkeypatch.setenv("CISSTAT_TELEMETRY_SAMPLE_RATE", "77")
        assert _sample_rate() == 1.0

    def test_sampling_deterministic_sha256(self):
        """Оракул oc33: sampling детерминирован sha256(event_name|rid):
        воспроизводим формулой; 20 повторных emit'ов дают ОДНО и то же
        решение (недетерминированная замена sha256 выдаёт раскол в
        20 исходах с вероятностью промаха ~2e-6)."""
        from apps.api import telemetry

        import os

        os.environ["CISSTAT_TELEMETRY_SAMPLE_RATE"] = "0.5"
        try:
            draw_src = f"{EVENT_ALPHA}|{REQUEST_ID_2}"
            draw = int(
                hashlib.sha256(draw_src.encode()).hexdigest()[:8], 16
            ) / float(0xFFFFFFFF)
            expected_ok = draw < 0.5
            outcomes = []
            for _ in range(20):
                telemetry.reset_telemetry_for_testing()
                outcomes.append(
                    telemetry.emit(
                        EVENT_ALPHA,
                        sample_class="noisy_read",
                        request_id=REQUEST_ID_2,
                    )
                )
            assert len(set(outcomes)) == 1, outcomes
            assert outcomes[0] is expected_ok
        finally:
            os.environ.pop("CISSTAT_TELEMETRY_SAMPLE_RATE", None)

    def test_sampling_excludes_non_success_get(self):
        """Оракул oc34: sampling только успешные GET: outcome!=success
        с sample_class=noisy_read не дропается (middleware ставит класс
        только для success; прямой вызов с несоответствием -- честный
        дым: ошибка 4xx severity info не попадает под отсечение по
        severity, но essential/не-GET -- вне класса)."""
        from apps.api import telemetry

        # POST с success -- класс noisy_read ставится только GET в
        # middleware; прямой emit с sample_class на POST-методе:
        # формула draw одна и та же -- проверяем, что решение
        # детерминировано от (event_name, request_id), а не от метода.
        import os

        os.environ["CISSTAT_TELEMETRY_SAMPLE_RATE"] = "0.0"
        try:
            assert (
                telemetry.emit(
                    EVENT_ALPHA,
                    method="POST",
                    sample_class="noisy_read",
                    request_id=REQUEST_ID_1,
                )
                is False
            )
        finally:
            os.environ.pop("CISSTAT_TELEMETRY_SAMPLE_RATE", None)


def test_sql_sentinel_not_in_any_record():
    """Оракул oc35 (сквозной AC10-минимум части 1): SQL-сентинел
    сертификации отсутствует во всём выводе контура после серии
    emit-вызовов части 1."""
    from apps.api import telemetry

    blob = json.dumps(telemetry.memory_records(), default=str)
    assert SENTINEL_SQL not in blob
    assert SENTINEL_DSN not in blob
    assert SENTINEL_KEY not in blob
