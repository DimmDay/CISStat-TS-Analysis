# scripts/doclog3cert/test_doclog3cert_oracle_pgmirror.py
"""DOCLOG-3-CERT: PG-зеркальные оракулы класса F-D2C1 (часть 4).

Урок DOCLOG-2-CERT (блокер F-D2C1: несовпадение поля при обратной
сборке записи из строки Postgres -> TypeError на каждом чтении
реестра; repo-корпус Memory-only не ловил). Прецедент переносится на
контур DOCLOG-3: durable-приёмники telemetry_events /
security_audit_records.

Читающего пути в поставке НЕТ (list_recent -> DOCLOG-7), поэтому класс
F-D2C1 проверяется на WRITE-пути -- единственном доступном сегодня в
durable-режиме (production Render, storage-mode required):
  1. статика: INSERT-колонки == DDL-колонки миграции 0009
     (порядок/состав; для audit -- минус серверная recorded_at);
  2. динамика fake-psycopg: cur.execute(INSERT, params) перехватывается;
     каждый параметр сверяется с ожидаемым значением ПО ИМЕНИ колонки
     (сдвиг колонок -> несоответствие -> RED);
  3. NOT NULL-без-DEFAULT колонки DDL покрыты INSERT-списком;
  4. ON CONFLICT / append-only / отсутствие REFERENCES на research_runs /
     файл-паритет 0009.

Fake-psycopg -- прецедент fakeredis (DOCLOG-0-CERT) / fake-psycopg
(DOCLOG-2-CERT): модуль-подмена в sys.modules, фейки СВОИ.
"""
from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest

# ═══════════════════════ Фейки psycopg (СВОИ) ═══════════════════════


class _FakeCursor:
    def __init__(self, conn: "_FakeConnection") -> None:
        self._conn = conn
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.calls.append((sql, tuple(params or ())))

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConnection:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.cursors: list[_FakeCursor] = []

    def cursor(self) -> _FakeCursor:
        cur = _FakeCursor(self)
        self.cursors.append(cur)
        return cur

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if exc[0] is not None:
            self.rollback()
        return False


@pytest.fixture()
def fake_psycopg(monkeypatch: pytest.MonkeyPatch) -> list[_FakeConnection]:
    """Подмена модуля psycopg; возвращает список созданных соединений."""
    connections: list[_FakeConnection] = []

    fake = types.ModuleType("psycopg")

    def connect(dsn: str = "", autocommit: bool = False, **kwargs):
        conn = _FakeConnection()
        connections.append(conn)
        return conn

    fake.connect = connect  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    return connections


# ═══════════════════════ Разбор DDL/INSERT (свои парсеры) ═══════════


def _ddl_columns(statement: str) -> list[tuple[str, bool, bool]]:
    """Из CREATE TABLE: [(имя, not_null, has_default)] в порядке DDL."""
    body = re.search(r"\((.*)\)", statement, re.S).group(1)
    columns: list[tuple[str, bool, bool]] = []
    for raw in body.split(","):
        line = " ".join(raw.split())
        if not line or line.upper().startswith(
            ("PRIMARY KEY", "UNIQUE", "FOREIGN", "CHECK", "CONSTRAINT")
        ):
            continue
        name = line.split()[0]
        upper = line.upper()
        columns.append(
            (name, "NOT NULL" in upper, "DEFAULT" in upper)
        )
    return columns


def _insert_columns(insert_sql: str) -> list[str]:
    match = re.search(r"INSERT INTO (\w+)\s*\((.*?)\)\s*VALUES", insert_sql, re.S)
    return [c.strip() for c in match.group(2).split(",")]


def _ddl_table_statement(table: str) -> str:
    from apps.api.research_runs import MIGRATION_STATEMENTS_0009

    for stmt in MIGRATION_STATEMENTS_0009:
        if re.search(rf"CREATE TABLE IF NOT EXISTS {table}\b", stmt):
            return stmt
    raise AssertionError(f"таблица {table} не найдена в MIGRATION_STATEMENTS_0009")


def _last_insert(conn: _FakeConnection, table: str) -> tuple[str, tuple]:
    prefix = f"INSERT INTO {table.upper()}"
    for cur in reversed(conn.cursors):
        for sql, params in reversed(cur.calls):
            if sql.lstrip().upper().startswith(prefix):
                return sql, params
    raise AssertionError(f"INSERT INTO {table} не выполнен")


# ═══════════════ telemetry_events: DDL <-> INSERT <-> params ═════════


class TestTelemetryPostgresMirror:
    def test_pgm01_insert_columns_equal_ddl_order_full(self):
        """Оракул pgm01: порядок/состав INSERT-колонок == DDL (29/29).
        Сдвиг колонок -- класс F-D2C1 -- обнаруживается статически."""
        from apps.api.telemetry import PostgresTelemetrySink

        ddl_names = [c[0] for c in _ddl_columns(
            _ddl_table_statement("telemetry_events")
        )]
        insert_names = _insert_columns(PostgresTelemetrySink._INSERT_SQL)
        assert len(ddl_names) == 29
        assert insert_names == ddl_names, (
            "INSERT-порядок != DDL-порядку (класс F-D2C1)"
        )

    def test_pgm02_not_null_without_default_covered_by_insert(self):
        """Оракул pgm02: каждая NOT NULL-без-DEFAULT колонка DDL входит
        в INSERT (первая запись в required-режиме не падает)."""
        from apps.api.telemetry import PostgresTelemetrySink

        ddl = _ddl_columns(_ddl_table_statement("telemetry_events"))
        insert_names = set(_insert_columns(PostgresTelemetrySink._INSERT_SQL))
        for name, not_null, has_default in ddl:
            if not_null and not has_default:
                assert name in insert_names, f"{name} не покрыта INSERT"

    def test_pgm03_write_roundtrip_params_align_by_name(
        self, fake_psycopg: list[_FakeConnection]
    ):
        """Оракул pgm03 (динамика): каждый параметр INSERT соответствует
        значению СВОЕЙ колонки записи; attributes -> JSON-строка,
        sampled -> bool. Сдвиг колонок -> несоответствие -> RED.
        Запись собрана публичным emit-контрактом; значения ожиданий --
        СВОЙ независимый пересчёт (spy на sink.write)."""
        from apps.api import telemetry
        from apps.api.telemetry import PostgresTelemetrySink

        sink = PostgresTelemetrySink("postgres://d3cert-mirror/telemetry")
        captured: dict = {}
        orig_write = sink.write

        def spy_write(record):
            captured["rec"] = dict(record)
            return orig_write(record)

        sink.write = spy_write  # type: ignore[method-assign]
        telemetry.set_telemetry_sink_for_testing(sink)
        try:
            ok = telemetry.emit(
                "d3cert.mirror.alpha",
                severity="warn",
                message_template="d3cert mirror payload",
                attributes={"route": "/d3cert/mirror", "status_class": "4xx"},
                outcome="client_error",
                request_id="d3certreq-pgm03",
                research_run_id="RUN-D3CERT11",
                tenant_id="tenant-d3cert",
                method="GET",
            )
        finally:
            telemetry.reset_telemetry_for_testing()
        assert ok is True and "rec" in captured
        rec = captured["rec"]
        conn = fake_psycopg[-1]
        assert conn.commits >= 1
        sql, params = _last_insert(conn, "telemetry_events")
        cols = _insert_columns(sql)
        assert len(cols) == len(params) == 29
        expected: dict = dict(rec)  # identity-поля берём из самой записи
        expected.update({
            "schema_version": "doclog.telemetry/1",
            "event_name": "d3cert.mirror.alpha",
            "severity_text": "WARN",
            "severity_number": 13,
            "message_template": "d3cert mirror payload",
            "service": "cisstat-api",
            "service_version": "1.0.0",
            "request_id": "d3certreq-pgm03",
            "research_run_id": "RUN-D3CERT11",
            "tenant_id": "tenant-d3cert",
            "outcome": "client_error",
            "method": "GET",
            "sampled": False,
        })
        mismatched: list[str] = []
        for i, col in enumerate(cols):
            if col == "attributes":
                payload = json.loads(params[i])
                if payload != {"route": "/d3cert/mirror",
                               "status_class": "4xx"}:
                    mismatched.append(f"attributes: {payload!r}")
                continue
            if params[i] != expected.get(col, "__MISSING__"):
                mismatched.append(
                    f"col[{i}]={col}: got {params[i]!r}, "
                    f"want {expected.get(col)!r}"
                )
        assert not mismatched, "сдвиг колонок INSERT: " + "; ".join(mismatched)

    def test_pgm04_on_conflict_and_commit(self):
        """Оракул pgm04: идемпотентность INSERT (ON CONFLICT DO NOTHING)
        и транзакционный commit присутствуют на write-пути."""
        from apps.api.telemetry import PostgresTelemetrySink

        assert "ON CONFLICT (event_id) DO NOTHING" in (
            PostgresTelemetrySink._INSERT_SQL
        )


# ═══════════════ security_audit_records: DDL <-> INSERT <-> params ═══


class TestAuditPostgresMirror:
    def test_pgm05_insert_columns_equal_ddl_minus_recorded_at(self):
        """Оракул pgm05: INSERT (16) == DDL-колонки минус серверная
        recorded_at (DEFAULT now()), порядок == DDL-порядок."""
        from apps.api.security_audit import PostgresAuditSink

        ddl_names = [c[0] for c in _ddl_columns(
            _ddl_table_statement("security_audit_records")
        )]
        assert len(ddl_names) == 17
        insert_names = _insert_columns(PostgresAuditSink._INSERT_SQL)
        assert insert_names == [c for c in ddl_names if c != "recorded_at"]

    def test_pgm06_not_null_without_default_covered(self):
        """Оракул pgm06: NOT NULL-без-DEFAULT колонки audit-DDL покрыты
        INSERT (actor_via/action/decision/occurred_at/audit_id/
        schema_version)."""
        from apps.api.security_audit import PostgresAuditSink

        ddl = _ddl_columns(_ddl_table_statement("security_audit_records"))
        insert_names = set(_insert_columns(PostgresAuditSink._INSERT_SQL))
        for name, not_null, has_default in ddl:
            if not_null and not has_default:
                assert name in insert_names, f"{name} не покрыта INSERT"

    def test_pgm07_append_roundtrip_params_align_by_name(
        self, fake_psycopg: list[_FakeConnection]
    ):
        """Оракул pgm07 (динамика): параметры INSERT записи аудита
        соответствуют СВОИМ колонкам; details -> JSON-строка."""
        from apps.api import security_audit

        sink = security_audit.PostgresAuditSink("postgres://d3cert-mirror/audit")
        captured: dict = {}
        orig_append = sink.append

        def spy_append(record):
            captured["rec"] = dict(record)
            return orig_append(record)

        sink.append = spy_append  # type: ignore[method-assign]
        security_audit.set_audit_sink_for_testing(sink)
        try:
            audit_id = security_audit.record_standard(
                "authn_denied",
                "denied",
                actor_subject="subj-d3certmirror01",
                actor_via="api_key",
                tenant_id="tenant-d3cert",
                resource_kind="principal",
                policy_basis="API-key registry",
                request_id="d3certreq-pgm07",
                details={
                    "reason_code": "invalid_key",
                    "route": "/d3cert/mirror",
                },
            )
        finally:
            security_audit.set_audit_sink_for_testing(None)
        assert audit_id and audit_id.startswith("aud-")
        rec = captured["rec"]
        conn = fake_psycopg[-1]
        assert conn.commits >= 1
        sql, params = _last_insert(conn, "security_audit_records")
        cols = _insert_columns(sql)
        assert len(cols) == len(params) == 16
        expected: dict = dict(rec)
        expected.update({
            "schema_version": "doclog.security_audit/1",
            "action": "authn_denied",
            "decision": "denied",
            "actor_subject": "subj-d3certmirror01",
            "actor_via": "api_key",
            "tenant_id": "tenant-d3cert",
            "resource_kind": "principal",
            "policy_basis": "API-key registry",
            "request_id": "d3certreq-pgm07",
        })
        mismatched: list[str] = []
        for i, col in enumerate(cols):
            if col == "details":
                payload = json.loads(params[i])
                if payload.get("reason_code") != "invalid_key" or payload.get(
                    "route"
                ) != "/d3cert/mirror":
                    mismatched.append(f"details: {payload!r}")
                continue
            if col == "occurred_at":
                if not (isinstance(params[i], str) and "+00:00" in params[i]):
                    mismatched.append(f"occurred_at: {params[i]!r}")
                continue
            if params[i] != expected.get(col, "__MISSING__"):
                mismatched.append(
                    f"col[{i}]={col}: got {params[i]!r}, "
                    f"want {expected.get(col)!r}"
                )
        assert not mismatched, "сдвиг колонок INSERT: " + "; ".join(mismatched)

    def test_pgm08_list_recent_not_implemented_doclog7(self):
        """Оракул pgm08: чтения durable-журнала НЕТ (DOCLOG-7) --
        честная граница, не молчаливое чтение (T6)."""
        from apps.api.security_audit import PostgresAuditSink

        with pytest.raises(NotImplementedError):
            PostgresAuditSink("postgres://d3cert-mirror/audit").list_recent()


# ═══════════════ Общие DDL-гарантии миграции 0009 ════════════════════


class TestMigration0009Contract:
    def test_pgm09_no_references_to_research_runs(self):
        """Оракул pgm09: FK на research_runs НЕТ НАМЕРЕННО (журналы
        переживают удаление run, §16.1) -- контроль отсутствия."""
        from apps.api.research_runs import MIGRATION_STATEMENTS_0009

        for stmt in MIGRATION_STATEMENTS_0009:
            assert "REFERENCES" not in stmt.upper()

    def test_pgm10_six_indexes_present(self):
        """Оракул pgm10: 3 индекса telemetry + 3 индекса audit."""
        from apps.api.research_runs import MIGRATION_STATEMENTS_0009

        joined = " ".join(MIGRATION_STATEMENTS_0009).upper()
        assert joined.count("CREATE INDEX IF NOT EXISTS") == 6

    def test_pgm11_file_parity_with_catalog(self):
        """Оракул pgm11: файл-дубль 0009 == каталог MIGRATION_STATEMENTS
        (паттерн 0007/0008 -- нормализация пробелов/комментариев)."""
        from apps.api.research_runs import MIGRATION_STATEMENTS_0009

        sql_file = (
            Path(__file__).resolve().parents[2]
            / "apps" / "api" / "migrations"
            / "0009_doclog3_telemetry_audit.sql"
        )
        kept_lines = [
            line
            for line in sql_file.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith("--")
        ]
        chunks = " ".join(kept_lines).split(";")
        file_ddl = sorted(
            " ".join(c.split())
            for c in chunks
            if " ".join(c.split()).upper().startswith(
                ("CREATE TABLE", "CREATE INDEX")
            )
        )
        catalog_ddl = sorted(" ".join(s.split()) for s in MIGRATION_STATEMENTS_0009)
        assert file_ddl == catalog_ddl
