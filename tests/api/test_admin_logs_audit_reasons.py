# tests/api/test_admin_logs_audit_reasons.py
#
# Task ID: DOCLOG-H29-UIHONEST-AUDITVIEW (2026-10-27) -- рекомендация
# «Наблюдаемость: админ-представление security-audit (reason_code по
# run)» из AUTH-SCENARIO-ANALYST-DOCS §6 (база a4277b9).
#
# Инцидент «у меня запрещён» должен разбираться по ФАКТИЧЕСКОЙ причине
# (reason_code из durable security-audit), а не по догадкам. Причины
# отказов доступа пишутся record_run_access_decision в details
# ({"reason_code": ..., "action": ...}); DOCLOG-7 читает audit
# (/v1/logs/audit, admin_logs.query_audit). Найденные разрывы:
#
#   1. PG-путь: _AUDIT_COLUMNS НЕ включает details -- reason_code
#      невидим в durable-режиме (memory/PG паритет обязателен);
#   2. memory-путь: фильтры run_id/tenant_id из whitelist молча
#      ИГНОРИРУЮТСЯ (PG применяет) -- «причины по run» на memory не
#      работали вовсе.
#
# Оракулы на СВОИХ данных (d8-*), корпус дизъюнктен DOCLOG-7 (d7-*).

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from apps.api import admin_logs
from apps.api.admin_logs import (
    EffectiveLogAccess,
    LogQuery,
    parse_query,
    query_audit,
)
from apps.api.security_audit import (
    ACTION_RUN_ACCESS_DENIED,
    build_audit_record,
    reset_audit_for_testing,
)
from apps.api.telemetry import reset_telemetry_for_testing

ADMIN_ACCESS = EffectiveLogAccess(
    telemetry=True,
    audit=True,
    delivery=True,
    export=True,
    grants_management=True,
)

RUN_A = "RUN-D8A00001"
RUN_B = "RUN-D8B00002"


@pytest.fixture(autouse=True)
def _isolated_audit(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CISSTAT_AUDIT_BACKEND", raising=False)
    reset_audit_for_testing()
    reset_telemetry_for_testing()
    yield
    reset_audit_for_testing()
    reset_telemetry_for_testing()


def _record_denied(run_id: str, reason: str) -> str:
    """run_access_denied ТОЧНО той же формы, что пишет
    record_run_access_decision (identity.py -> security_audit)."""
    record = build_audit_record(
        ACTION_RUN_ACCESS_DENIED,
        "denied",
        actor_subject="subj-d8aaaaaaaaaaaaaa",
        actor_via="session_cookie",
        resource_kind="run",
        resource_id=run_id,
        run_id=run_id,
        policy_basis="R09 object authorization",
        details={"reason_code": reason, "action": "list_documents"},
    )
    from apps.api.security_audit import _append_or_count

    assert _append_or_count(record), "запись должна попасть в memory-sink"
    return str(record["audit_id"])


def _query(**filters):
    parsed = parse_query(
        "audit",
        from_raw=None,
        to_raw=None,
        limit_raw=None,
        cursor_raw=None,
        filters=filters,
    )
    return query_audit(parsed, ADMIN_ACCESS)


class TestMemoryAuditReasons:
    def test_denied_records_carry_details_with_reason_code(self):
        """memory: reading returns details -- reason_code available to
        admin view (for the incident, the fact, not guesses)."""
        _record_denied(RUN_A, "foreign_session")
        _record_denied(RUN_B, "anonymous")
        payload = _query(action=ACTION_RUN_ACCESS_DENIED)
        reasons = {
            (row["run_id"], (row.get("details") or {}).get("reason_code"))
            for row in payload["records"]
        }
        assert (RUN_A, "foreign_session") in reasons
        assert (RUN_B, "anonymous") in reasons

    def test_memory_run_id_filter_is_applied(self):
        """memory: whitelist run_id filter WORKS (parity PG): only the
        requested run. Previously silently ignored -- 'reasons by run'
        did not work."""
        _record_denied(RUN_A, "foreign_session")
        _record_denied(RUN_B, "anonymous")
        payload = _query(run_id=RUN_A)
        assert payload["records"], "expected at least one record for RUN_A"
        assert all(row["run_id"] == RUN_A for row in payload["records"])
        assert all(
            (row.get("details") or {}).get("reason_code") == "foreign_session"
            for row in payload["records"]
        )

    def test_memory_tenant_id_filter_is_applied(self):
        """memory: tenant_id filter parity (whitelist declares it --
        ignoring is an honest contract violation)."""
        record = build_audit_record(
            ACTION_RUN_ACCESS_DENIED,
            "denied",
            actor_subject="subj-d8bbbbbbbbbbbbbb",
            actor_via="session_cookie",
            tenant_id="tenant-d8x",
            resource_kind="run",
            resource_id=RUN_A,
            run_id=RUN_A,
            policy_basis="R09 object authorization",
            details={"reason_code": "foreign_session"},
        )
        from apps.api.security_audit import _append_or_count

        assert _append_or_count(record)
        payload = _query(tenant_id="tenant-d8x")
        assert payload["records"]
        payload_empty = _query(tenant_id="tenant-d8y")
        assert payload_empty["records"] == []


class TestPostgresAuditReasons:
    def test_pg_columns_include_details(self):
        """PG: details SELECTed (reason_code visible in durable mode) --
        column exists in migration 0009 (INSERT includes details)."""
        assert "details" in admin_logs._AUDIT_COLUMNS

    def test_pg_query_selects_details(self, monkeypatch):
        """PG read SQL includes details; rows carry them into the page."""
        monkeypatch.setenv("CISSTAT_AUDIT_BACKEND", "postgres")
        captured = {}

        def _fake_fetch_all(sql, params):
            captured["sql"] = sql
            return [
                {
                    "audit_id": "d8-audit-1",
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                    "actor_subject": "subj-d8aaaaaaaaaaaaaa",
                    "actor_via": "session_cookie",
                    "tenant_id": None,
                    "action": ACTION_RUN_ACCESS_DENIED,
                    "decision": "denied",
                    "resource_kind": "run",
                    "resource_id": RUN_A,
                    "resource_version": None,
                    "policy_basis": "R09 object authorization",
                    "request_id": None,
                    "run_id": RUN_A,
                    "details": json.dumps(
                        {"reason_code": "foreign_session", "action": "list_documents"}
                    ),
                }
            ]

        monkeypatch.setattr(admin_logs, "_pg_fetch_all", _fake_fetch_all)
        payload = _query(action=ACTION_RUN_ACCESS_DENIED)
        assert "details" in captured["sql"]
        records = payload["records"]
        assert records, "PG row must reach the page"
        reason = (records[0].get("details") or {}).get("reason_code")
        assert reason == "foreign_session"
