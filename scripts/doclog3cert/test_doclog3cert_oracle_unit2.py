# scripts/doclog3cert/test_doclog3cert_oracle_unit2.py
"""DOCLOG-3-CERT: оракулы на СВОИХ данных -- часть 2.

Отказоустойчивость pipeline/spool/emergency (§13.2/AC11), security
audit (§14.1): поля/каталог/классы обязательности/append-only/
fail-closed mandatory/best-effort standard, миграция 0009 и паритет
файл-каталог, счётчики/статусы.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from conftest import (
    ADMIN_KEY,
    EVENT_ALPHA,
    EVENT_BETA,
    EVENT_GAMMA,
    IDENTITY_SALT,
    RUN_ID_FOREIGN,
    RUN_ID_MISSING,
    RUN_ID_OWNER,
    SENTINEL_KEY,
    SENTINEL_PASSWORD,
    SESSION_ID_FOREIGN,
    SESSION_ID_OWNER,
)


# ═══════════ 6. Pipeline / spool / emergency (§13.2, AC11) ═══════════


class _AlwaysFailSink:
    def write(self, record):
        raise ConnectionError("collector down d3cert")

    def readiness_probe(self):
        return {"ok": False, "backend": "memory"}


class _RejectSink:
    def write(self, record):
        return False

    def readiness_probe(self):
        return {"ok": True, "backend": "memory"}


class TestPipelineResilience:
    def test_sink_exception_spools_and_never_raises(self):
        """Оракул oc36: исключение sink -> spool + счётчики + emergency;
        emit возвращает False и НЕ бросает (AC11)."""
        from apps.api import telemetry

        telemetry.set_telemetry_sink_for_testing(_AlwaysFailSink())
        assert telemetry.emit(EVENT_ALPHA, severity="info") is False
        status = telemetry.telemetry_status()
        assert status["spool_size"] == 1
        assert status["emergency_size"] == 1
        counters = status["counters"]
        assert counters.get("telemetry_sink_failures_total", 0) == 1
        assert counters.get("telemetry_emergency_total", 0) == 1
        assert status["degraded"] is True
        # в spool -- ОРИГИНАЛЬНАЯ запись (краспонированная), event_name тот же
        assert telemetry.emit(EVENT_BETA) is False
        assert telemetry.telemetry_status()["spool_size"] == 2

    def test_honest_false_is_dropped_not_spooled(self):
        """Оракул oc37: sink вернул False (переполнение memory) =
        запись ПОТЕРЯНА -> dropped; spool НЕ наполняется (§13.2
        «переполнение очереди видимо через dropped_records»)."""
        from apps.api import telemetry

        telemetry.set_telemetry_sink_for_testing(_RejectSink())
        assert telemetry.emit(EVENT_ALPHA) is False
        status = telemetry.telemetry_status()
        assert status["spool_size"] == 0
        counters = status["counters"]
        assert counters.get("telemetry_dropped_total", 0) == 1
        assert counters.get("telemetry_emergency_total", 0) == 0
        # сбой -> False тоже считаем sink_failure (наблюдаемость)
        assert counters.get("telemetry_sink_failures_total", 0) == 1

    def test_spool_bounded_500(self):
        """Оракул oc38: spool ограничен 500 (SPOOL_MAX); сверх --
        dropped."""
        from apps.api import telemetry

        telemetry.set_telemetry_sink_for_testing(_AlwaysFailSink())
        for _ in range(505):
            telemetry.emit(EVENT_ALPHA)
        status = telemetry.telemetry_status()
        assert status["spool_size"] == 500
        assert status["counters"].get("telemetry_dropped_total", 0) == 5

    def test_emergency_bounded_20(self):
        """Оракул oc39: emergency-фолбэк ограничен 20 (EMERGENCY_MAX)."""
        from apps.api import telemetry

        telemetry.set_telemetry_sink_for_testing(_AlwaysFailSink())
        for _ in range(30):
            telemetry.emit(EVENT_ALPHA)
        assert telemetry.telemetry_status()["emergency_size"] == 20

    def test_flush_after_recovery(self):
        """Оракул oc40: flush_spool после восстановления доставляет
        всё; недоставленное остаётся."""
        from apps.api import telemetry

        telemetry.set_telemetry_sink_for_testing(_AlwaysFailSink())
        telemetry.emit(EVENT_ALPHA)
        telemetry.emit(EVENT_BETA)
        assert telemetry.telemetry_status()["spool_size"] == 2
        telemetry.set_telemetry_sink_for_testing(None)  # к env-выбору (memory)
        flushed = telemetry.flush_spool()
        assert flushed == 2
        assert telemetry.telemetry_status()["spool_size"] == 0
        names = {r["event_name"] for r in telemetry.memory_records()}
        assert {EVENT_ALPHA, EVENT_BETA} <= names

    def test_flush_partial_keeps_remaining(self):
        """Оракул oc41: частичная доставка -- недоставленные остаются
        в spool (порядок сохраняется)."""
        from apps.api import telemetry

        telemetry.set_telemetry_sink_for_testing(_AlwaysFailSink())
        telemetry.emit(EVENT_ALPHA)
        telemetry.emit(EVENT_BETA)
        telemetry.emit(EVENT_GAMMA)

        class _SkipBeta:
            def write(self, record):
                if record.get("event_name") == EVENT_BETA:
                    return False
                return True

            def readiness_probe(self):
                return {"ok": True}

        telemetry.set_telemetry_sink_for_testing(_SkipBeta())
        flushed = telemetry.flush_spool()
        assert flushed == 2
        assert telemetry.telemetry_status()["spool_size"] == 1

    def test_set_sink_none_preserves_spool(self):
        """Оракул oc42: set_sink(None) не теряет spool/счётчики
        (восстановление collector не теряет буфер)."""
        from apps.api import telemetry

        telemetry.set_telemetry_sink_for_testing(_AlwaysFailSink())
        telemetry.emit(EVENT_ALPHA)
        before = telemetry.telemetry_status()["counters"][
            "telemetry_sink_failures_total"
        ]
        telemetry.set_telemetry_sink_for_testing(None)
        status = telemetry.telemetry_status()
        assert status["spool_size"] == 1
        assert status["counters"]["telemetry_sink_failures_total"] == before

    def test_status_not_initialized_and_peek(self):
        """Оракул oc43: peek без инициализации -- None; status --
        not_initialized; health-фабрика не провоцирует фабрику."""
        from apps.api import telemetry

        assert telemetry.peek_telemetry_sink() is None
        st = telemetry.telemetry_status()
        assert st["backend"] == "not_initialized"
        assert st["degraded"] is False
        from apps.api.storage_diagnostics import build_telemetry_health

        health = build_telemetry_health()
        assert health["backend"] == "not_initialized"
        assert telemetry.peek_telemetry_sink() is None  # НЕ инициализирован

    def test_jsonl_adapter(self):
        """Оракул oc44: to_jsonl -- одна строка, allow_nan=False,
        несериализуемое (падающий __str__ в default) -> честный
        serialize_error-фолбэк."""
        from apps.api import telemetry

        class _BoomRepr:
            def __str__(self):
                raise TypeError("no repr d3cert")

        telemetry.emit(EVENT_ALPHA)
        rec = telemetry.memory_records()[-1]
        line = telemetry.to_jsonl(rec)
        assert "\n" not in line
        assert json.loads(line)["event_name"] == EVENT_ALPHA
        weird = {"event_name": EVENT_ALPHA, "payload": _BoomRepr()}
        line2 = telemetry.to_jsonl(weird)
        assert json.loads(line2)["serialize_error"] is True
        nan_rec = {"event_name": EVENT_ALPHA, "value": float("nan")}
        line3 = telemetry.to_jsonl(nan_rec)
        assert json.loads(line3)["serialize_error"] is True

    def test_memory_records_hidden_for_non_memory(self):
        """Оракул oc45: содержимое durable-приёмника через health/
        memory_records НЕ выдаётся (T6): не-memory backend -> []."""
        from apps.api import telemetry

        telemetry.set_telemetry_sink_for_testing(_RejectSink())
        telemetry.emit(EVENT_ALPHA)
        assert telemetry.memory_records() == []


# ═══════════ 7. Security audit (§14.1) ═══════════════════════════════


class _AuditFailSink:
    def append(self, record):
        raise OSError("disk full d3cert")

    def list_recent(self, limit=100):
        return []

    def readiness_probe(self):
        return {"ok": False}


class TestAuditContract:
    def test_record_full_shape(self):
        """Оракул oc46: build_audit_record -- полный состав §14.1
        (кто/когда/tenant/resource/version/действие/решение/основание/
        корреляция); решение denied; audit_id aud-*."""
        from apps.api import security_audit

        rec = security_audit.build_audit_record(
            "run_access_denied",
            "denied",
            actor_subject="subj-0123456789abcdef",
            actor_via="session_cookie",
            tenant_id="tenant-d3cert",
            resource_kind="run",
            resource_id=RUN_ID_FOREIGN,
            resource_version="1",
            policy_basis="R09 object authorization",
            run_id=RUN_ID_FOREIGN,
            details={"reason_code": "foreign_session"},
        )
        assert rec["schema_version"] == "doclog.security_audit/1"
        assert rec["audit_id"].startswith("aud-")
        assert rec["action"] == "run_access_denied"
        assert rec["decision"] == "denied"
        assert rec["resource_id"] == RUN_ID_FOREIGN
        assert rec["policy_basis"] == "R09 object authorization"
        assert rec["details"]["reason_code"] == "foreign_session"
        for field in (
            "occurred_at", "actor_subject", "actor_via", "tenant_id",
            "resource_kind", "request_id", "operation_id", "run_id",
        ):
            assert field in rec

    def test_catalog_20_actions_and_triple(self):
        """Оракул oc47: AUDIT_ACTIONS == 20; тройка
        download_requested/response_stream_started/finished различается;
        human_read_confirmed НЕ существует (§14.1)."""
        from apps.api import security_audit

        actions = set(security_audit.AUDIT_ACTIONS)
        assert len(actions) == 20
        assert {
            security_audit.ACTION_DOWNLOAD_REQUESTED,
            security_audit.ACTION_RESPONSE_STREAM_STARTED,
            security_audit.ACTION_RESPONSE_STREAM_FINISHED,
        } <= actions
        assert len({
            security_audit.ACTION_DOWNLOAD_REQUESTED,
            security_audit.ACTION_RESPONSE_STREAM_STARTED,
            security_audit.ACTION_RESPONSE_STREAM_FINISHED,
        }) == 3
        assert "human_read_confirmed" not in actions

    def test_requirements_classes_complete(self):
        """Оракул oc48: каждый каталог имеет класс обязательности;
        mandatory == 9 защищённых действий; остальные standard."""
        from apps.api import security_audit

        actions = set(security_audit.AUDIT_ACTIONS)
        reqs = security_audit.AUDIT_REQUIREMENTS
        assert set(reqs.keys()) == actions  # без дыр и без лишних
        mandatory = {a for a, c in reqs.items() if c == "mandatory"}
        assert mandatory == {
            security_audit.ACTION_DOCUMENT_PUBLISHED,
            security_audit.ACTION_DOCUMENT_APPROVED,
            security_audit.ACTION_DOCUMENT_REVOKED,
            security_audit.ACTION_PROTECTED_DOCUMENT_VIEWED,
            security_audit.ACTION_DOWNLOAD_REQUESTED,
            security_audit.ACTION_RESPONSE_STREAM_STARTED,
            security_audit.ACTION_RESPONSE_STREAM_FINISHED,
            security_audit.ACTION_GRANT_CREATED,
            security_audit.ACTION_GRANT_REVOKED,
        }

    def test_unknown_action_or_decision_valueerror(self):
        """Оракул oc49: неизвестное действие/решение -> ValueError
        (fail-closed контракт сборки)."""
        from apps.api import security_audit

        with pytest.raises(ValueError):
            security_audit.build_audit_record("d3cert_unknown_action", "denied")
        with pytest.raises(ValueError):
            security_audit.build_audit_record("authn_denied", "maybe")

    def test_record_mandatory_fail_closed(self):
        """Оракул oc50 (AC11): сбой обязательной записи ->
        MandatoryAuditFailure ДО действия; действие не выполняется."""
        from apps.api import security_audit

        security_audit.set_audit_sink_for_testing(_AuditFailSink())
        performed = False

        def _protected_action():
            nonlocal performed
            security_audit.record_mandatory(
                "document_published", "allowed", actor_subject="subj-d3cert",
            )
            performed = True  # это место НЕ достигается

        with pytest.raises(security_audit.MandatoryAuditFailure):
            _protected_action()
        assert performed is False  # fail-closed: действие отменено
        status = security_audit.audit_status()
        assert status["degraded"] is True
        assert status["counters"].get("audit_write_failures_total", 0) >= 1

    def test_record_mandatory_success(self):
        """Оракул oc51: успешная mandatory-запись возвращает audit_id и
        сохраняется."""
        from apps.api import security_audit

        audit_id = security_audit.record_mandatory(
            "download_requested", "allowed",
            actor_subject="subj-fedcba0987654321",
            resource_kind="document", resource_id="doc-d3cert-1",
            policy_basis="owner with export scope",
        )
        assert audit_id and audit_id.startswith("aud-")
        records = security_audit.audit_records()
        assert records[-1]["audit_id"] == audit_id
        assert records[-1]["action"] == "download_requested"

    def test_record_standard_never_raises(self):
        """Оракул oc52 (AC11-инвариант): сбой standard-записи НЕ меняет
        решения и не бросает: None + счётчик + degraded."""
        from apps.api import security_audit

        security_audit.set_audit_sink_for_testing(_AuditFailSink())
        result = security_audit.record_standard(
            "authn_denied", "denied", actor_subject="subj-d3certbad",
        )
        assert result is None
        status = security_audit.audit_status()
        assert status["degraded"] is True
        assert status["counters"].get("audit_write_failures_total", 0) == 1

    def test_record_standard_invalid_action_counted(self):
        """Оракул oc53: некорректное действие в record_standard --
        счётчик audit_invalid_record_total, не ValueError."""
        from apps.api import security_audit

        assert (
            security_audit.record_standard("d3cert-bad-action", "denied")
            is None
        )
        counters = security_audit.audit_status()["counters"]
        assert counters.get("audit_invalid_record_total", 0) == 1

    def test_run_access_decision_mapping(self):
        """Оракул oc54: record_run_access_decision маппит AccessDecision
        в run_access_allowed/denied с reason_code и run_id."""
        from apps.api import security_audit
        from apps.api.identity import AccessDecision

        security_audit.record_run_access_decision(
            AccessDecision(
                allowed=False, reason="foreign_session",
                run_id=RUN_ID_FOREIGN, action="read",
                requester_subject="subj-0011223344556677",
                requester_via="session_cookie",
            )
        )
        security_audit.record_run_access_decision(
            AccessDecision(
                allowed=True, reason="owner", run_id=RUN_ID_OWNER,
                action="read", requester_subject="subj-8899aabbccddeeff",
                requester_via="session_cookie",
            )
        )
        records = security_audit.audit_records()
        denied = [r for r in records if r["action"] == "run_access_denied"]
        allowed = [r for r in records if r["action"] == "run_access_allowed"]
        assert denied and allowed
        assert denied[-1]["details"]["reason_code"] == "foreign_session"
        assert denied[-1]["run_id"] == RUN_ID_FOREIGN
        assert allowed[-1]["run_id"] == RUN_ID_OWNER
        # run_id в записи разрешён (серверный журнал), псевдоним субъекта
        assert allowed[-1]["actor_subject"].startswith("subj-")

    def test_minimal_decision_defaults(self):
        """Оракул oc55: AccessDecision без полей (getattr-дефолты) --
        честная denied-запись без исключения."""
        from types import SimpleNamespace

        from apps.api import security_audit

        result = security_audit.record_run_access_decision(
            SimpleNamespace()  # нет ни одного поля
        )
        assert result is None or result.startswith("aud-")
        records = [
            r for r in security_audit.audit_records()
            if r["action"] == "run_access_denied"
        ]
        assert records  # не-allowed маппится в denied

    def test_details_redacted_values_keys_kept(self):
        """Оракул oc56: details -- серверный журнал: ключи сохраняются,
        значения проходят redaction; не-dict -> {"value": ...}; >32
        ключей обрезаются."""
        from apps.api import security_audit

        rec = security_audit.build_audit_record(
            "authz_denied", "denied",
            details={
                "reason_code": "role_insufficient",
                "leak": f"api_key={SENTINEL_KEY}",
            },
        )
        assert rec["details"]["reason_code"] == "role_insufficient"
        assert SENTINEL_KEY not in json.dumps(rec)
        rec2 = security_audit.build_audit_record(
            "authz_denied", "denied", details="not-a-dict-d3cert"
        )
        assert "value" in rec2["details"]
        many = {f"k{i}": f"v{i}-d3cert" for i in range(40)}
        rec3 = security_audit.build_audit_record(
            "authz_denied", "denied", details=many
        )
        assert len(rec3["details"]) == 32

    def test_append_only_static(self):
        """Оракул oc57 (статический): в security_audit.py НЕТ операций
        изменения/удаления ЗАПИСЕЙ (append-only §14.1 по построению):
        нет UPDATE/DELETE SQL; контейнер записей не мутируется
        (счётчики -- отдельный словарь, его очистка в reset допустима)."""
        import apps.api.security_audit as sa

        src = Path(sa.__file__).read_text(encoding="utf-8")
        assert "UPDATE " not in src and "DELETE FROM" not in src
        assert "TRUNCATE" not in src
        for pattern in (
            "self._records.clear()",
            "del self._records",
            "self._records.pop",
            "self._records.remove",
            "del _records",
            "_records.clear()",
        ):
            assert pattern not in src, pattern

    def test_memory_sink_overflow_honest_false(self):
        """Оракул oc58: переполнение memory-приёмника -> честный False
        (НЕ молчаливое): счётчик + degraded."""
        from apps.api import security_audit

        security_audit.set_audit_sink_for_testing(
            security_audit.MemoryAuditSink(maxsize=2)
        )
        assert security_audit.record_standard(
            "authn_denied", "denied", actor_subject="subj-a1"
        )
        assert security_audit.record_standard(
            "authz_denied", "denied", actor_subject="subj-a2"
        )
        third = security_audit.record_standard(
            "authn_denied", "denied", actor_subject="subj-a3"
        )
        assert third is None
        status = security_audit.audit_status()
        assert status["counters"].get("audit_dropped_total", 0) == 1
        assert status["degraded"] is True

    def test_postgres_list_recent_not_implemented(self):
        """Оракул oc59: чтение durable-журнала -- DOCLOG-7
        (NotImplementedError с указанием контура; T6)."""
        from apps.api.security_audit import PostgresAuditSink

        sink = PostgresAuditSink(dsn="postgresql://d3cert:stub@nowhere/db")
        with pytest.raises(NotImplementedError):
            sink.list_recent()

    def test_record_mandatory_fail_closed_on_honest_false(self):
        """Оракул oc59b (пин M20, класс мутанта SURVIVED в repo+oracle):
        mandatory fail-closed при ЧЕСТНОМ отказе доставки (sink вернул
        False -- переполнение): MandatoryAuditFailure ДО действия."""
        from apps.api import security_audit

        class _RejectingSink:
            def append(self, record):
                return False

            def list_recent(self, limit=100):
                return []

            def readiness_probe(self):
                return {"ok": True}

        security_audit.set_audit_sink_for_testing(_RejectingSink())
        with pytest.raises(security_audit.MandatoryAuditFailure):
            security_audit.record_mandatory(
                "document_published", "allowed",
                actor_subject="subj-d3certpin",
            )
        counters = security_audit.audit_status()["counters"]
        assert counters.get("audit_dropped_total", 0) >= 1

    def test_audit_insert_sql_shape(self):
        """Оракул oc60 (статический): INSERT audit -- 16 колонок,
        ON CONFLICT DO NOTHING, только INSERT."""
        from apps.api.security_audit import PostgresAuditSink

        sql = PostgresAuditSink._INSERT_SQL
        assert sql.count("%s") == 16
        assert "ON CONFLICT (audit_id) DO NOTHING" in sql
        assert not re.search(r"UPDATE|DELETE", sql)

    def test_peek_and_status_before_init(self):
        """Оракул oc61: peek_audit_sink без инициализации -- None;
        audit_status -- not_initialized; сброс чистит счётчики."""
        from apps.api import security_audit

        assert security_audit.peek_audit_sink() is None
        st = security_audit.audit_status()
        assert st["backend"] == "not_initialized"
        security_audit._inc("audit_dropped_total", 3)
        security_audit.reset_audit_for_testing()
        assert security_audit.audit_status()["counters"] == {}


# ═══════════ 8. Subject surrogate (§13.3/§15.1) ══════════════════════


class TestSubjectSurrogate:
    def test_surrogate_stable_and_irreversible(self):
        """Оракул oc62: псевдоним стабилен (повтор -> тот же subj-*),
        материал не восстановим и не содержится; смена соли меняет
        псевдоним (ротация)."""
        from apps.api.identity import subject_pseudonym

        a1 = subject_pseudonym(ADMIN_KEY)
        a2 = subject_pseudonym(ADMIN_KEY)
        assert a1 == a2 and a1.startswith("subj-")
        assert ADMIN_KEY not in a1
        assert len(a1) == len("subj-") + 16
        # другая соль -- другой псевдоним (материал же тот же)
        a3 = subject_pseudonym(ADMIN_KEY, salt="d3cert-salt-other")
        assert a3 != a1

    def test_surrogate_even_for_invalid_key(self):
        """Оракул oc63: HMAC-псевдоним даже для НЕвалидных ключей:
        связь повторов сохранена, материал не восстановим."""
        from apps.api.identity import subject_pseudonym

        bad = "definitely-not-a-key-d3cert-777"
        p1 = subject_pseudonym(bad)
        p2 = subject_pseudonym(bad)
        assert p1 == p2 and p1.startswith("subj-")
        assert bad not in p1
        with pytest.raises(ValueError):
            subject_pseudonym("")  # пустой материал -- не фабрикуется


# ═══════════ 9. Миграция 0009 / паритет ══════════════════════════════


class TestMigration0009:
    def test_eight_statements_in_catalog(self):
        """Оракул oc64: MIGRATION_STATEMENTS_0009 == 8 (2 таблицы +
        6 индексов)."""
        from apps.api.research_runs import MIGRATION_STATEMENTS_0009

        assert len(MIGRATION_STATEMENTS_0009) == 8
        blob = " ".join(MIGRATION_STATEMENTS_0009).upper()
        assert blob.count("CREATE TABLE") == 2
        assert blob.count("CREATE INDEX") == 6

    def test_no_fk_to_research_runs(self):
        """Оракул oc65: FK на research_runs НЕТ (журналы переживают
        удаление run, §16.1)."""
        from apps.api.research_runs import MIGRATION_STATEMENTS_0009

        blob = " ".join(MIGRATION_STATEMENTS_0009).upper()
        assert "REFERENCES" not in blob

    def test_column_counts(self):
        """Оракул oc66: telemetry_events 29 колонок,
        security_audit_records 17 (контракт миграции 0009)."""
        from apps.api.research_runs import MIGRATION_STATEMENTS_0009

        blob = "\n".join(MIGRATION_STATEMENTS_0009)
        t = re.search(
            r"CREATE TABLE IF NOT EXISTS telemetry_events \((.*?)\n\s*\)",
            blob, re.S,
        ).group(1)
        s = re.search(
            r"CREATE TABLE IF NOT EXISTS security_audit_records \((.*?)\n\s*\)",
            blob, re.S,
        ).group(1)
        t_cols = [
            l for l in t.strip().split("\n")
            if l.strip() and l.strip().split()[0].isidentifier()
        ]
        s_cols = [
            l for l in s.strip().split("\n")
            if l.strip() and l.strip().split()[0].isidentifier()
        ]
        assert len(t_cols) == 29
        assert len(s_cols) == 17

    def test_file_catalog_parity(self):
        """Оракул oc67 (СВОЙ алгоритм): файл 0009.sql эквивалентен
        каталогу MIGRATION_STATEMENTS_0009 -- сравнение канонических
        DDL-предложений (strip комментариев; split по ';')."""
        import apps.api.research_runs as rr

        file_path = (
            Path(rr.__file__).parent
            / "migrations"
            / "0009_doclog3_telemetry_audit.sql"
        )
        text = file_path.read_text(encoding="utf-8")
        no_comments = re.sub(r"--[^\n]*", "", text)
        file_stmts = [
            re.sub(r"\s+", " ", s.strip())
            for s in no_comments.split(";")
            if s.strip()
        ]
        cat_stmts = [
            re.sub(r"\s+", " ", s.strip())
            for s in rr.MIGRATION_STATEMENTS_0009
            if s.strip()
        ]
        assert file_stmts == cat_stmts

    def test_catalog_totals_53_statements_9_files(self):
        """Оракул oc68: каталог миграций -- 53 statement / 9 файлов
        (аддитивно 45+8)."""
        from apps.api.research_runs import (
            MIGRATION_FILES,
            MIGRATION_STATEMENTS,
        )

        assert len(MIGRATION_STATEMENTS) == 53
        assert len(MIGRATION_FILES) == 9
        assert dict(MIGRATION_FILES)["0009_doclog3_telemetry_audit.sql"] == (
            __import__(
                "apps.api.research_runs", fromlist=["x"]
            ).MIGRATION_STATEMENTS_0009
        )

    def test_insert_only_telemetry_sql(self):
        """Оракул oc69 (статический): telemetry INSERT -- 29 параметров,
        ON CONFLICT DO NOTHING; UPDATE/DELETE отсутствуют."""
        from apps.api.telemetry import PostgresTelemetrySink

        sql = PostgresTelemetrySink._INSERT_SQL
        assert sql.count("%s") == 29
        assert "ON CONFLICT (event_id) DO NOTHING" in sql
        assert not re.search(r"UPDATE |DELETE FROM", sql)

    def test_no_new_http_routes(self):
        """Оракул oc70: FastAPI 183 маршрута (БЕЗ изменений, счёт с
        раскрытием _IncludedRouter.original_router); нет
        /v1/documentation, /v1/audit, /v1/logs (§19 граница)."""
        from apps.api.main import app

        paths: set[str] = set()
        total = 0
        for r in app.routes:
            if type(r).__name__ == "_IncludedRouter":
                sub = r.original_router.routes
                total += len(sub)
                paths |= {getattr(s, "path", "") for s in sub}
            else:
                total += 1
                paths.add(getattr(r, "path", ""))
        assert total == 183
        for forbidden in ("/v1/documentation", "/v1/audit", "/v1/logs"):
            assert not any(p.startswith(forbidden) for p in paths)


def test_part2_sentinels_absent():
    """Оракул oc71 (сквозной AC10-минимум части 2): сентинелы части 2
    отсутствуют в обоих контурах после серии вызовов."""
    from apps.api import security_audit, telemetry

    blob = json.dumps(
        telemetry.memory_records() + security_audit.audit_records(),
        default=str,
    )
    assert SENTINEL_KEY not in blob
    assert SENTINEL_PASSWORD not in blob
