"""Native F-CERT-H1 oracles (реальный disposable PostgreSQL 16.2, 0 skips).

1. Механизм-репро класса дедлока на «сыром» lazy-пути: незакрытая
   транзакция conn A на trace_events + ленивая миграция fresh audit-sink
   на conn B (ops-каталог с ALTER ... ACCESS EXCLUSIVE даже как no-op)
   -> lock_timeout конвертирует вечное ожидание в LockNotAvailable.
   Это доказательство механизма (почему прогрев обязателен), не гейт
   регрессии: после поставки lazy-путь сохранён как fallback.
2. Сквозной: fresh DB + цепочка 0019→0035 + ops-каталог (порядок
   «миграция до старта api», паритет harness AUTH-CERT) -> required ->
   настоящий lifespan TestClient -> /health/ops storage_warmup primed
   (12 слоёв) -> coexistence-оракул: незакрытая транзакция conn A на
   trace_events, audit-append успешен (DDL в запросном пути больше нет).
3. Идемпотентность: повторный lifespan -- снова primed.
4. advisory: честный no-op (state=skipped, слои не создавались).
"""

import os
import unittest
import uuid
from pathlib import Path
from unittest import mock

import psycopg

from tests.integration import authcert_harness as H

ROOT = Path(__file__).resolve().parents[2]

LOCK_TIMEOUT_MS = 2000


def _dsn_with_lock_timeout(dsn: str) -> str:
    sep = "&" if "?" in dsn else "?"
    return dsn + sep + f"options=-c%20lock_timeout%3D{LOCK_TIMEOUT_MS}"


def _reset_singletons() -> None:
    """Свежие экземпляры durable-слоёв (_schema_ready=False) -- паритет
    «процесс только что стартовал»."""
    from apps.api import (
        admin_logs,
        artifact_store,
        doc_profiles,
        document_jobs,
        document_lifecycle,
        monitoring,
        report_snapshot,
        research_runs,
        security_audit,
        session_store,
        storage_warmup,
        telemetry,
    )

    security_audit.reset_audit_for_testing()
    telemetry.reset_telemetry_for_testing()
    session_store.reset_session_store_for_testing()
    research_runs.reset_research_run_store_for_testing()
    research_runs.reset_dataset_file_store_for_testing()
    artifact_store.reset_artifact_registry_for_testing()
    report_snapshot.reset_snapshot_registry_for_testing()
    document_jobs.reset_document_registry_for_testing()
    document_lifecycle.reset_document_lifecycle_registry_for_testing()
    admin_logs.reset_support_grant_registry_for_testing()
    monitoring.reset_monitoring_registry_for_testing()
    doc_profiles.reset_org_profile_registry_for_testing()
    admin_logs._pg_schema_ready = False
    storage_warmup.reset_warmup_status_for_testing()


def _deployment_env(dsn: str) -> dict:
    env = {
        "CISSTAT_STORAGE_MODE": "required",
        "DATABASE_URL": dsn,
        "CISSTAT_SESSION_BACKEND": "postgres",
        "CISSTAT_AUTH_ALLOWED_ORIGINS": H.ORIGINS,
        "CISSTAT_TOPUP_REFUND_DAYS": "14",
        "CISSTAT_AUTH_CSRF_KEY": "warmup-csrf-key-0123456789abcdef-01234567",
    }
    env.update(H.mfa_env())
    return env


def _audit_record() -> dict:
    return {
        "audit_id": "warmup-" + uuid.uuid4().hex,
        "schema_version": 1,
        "occurred_at": "2026-11-13T00:00:00+00:00",
        "actor_subject": "warmup-tester",
        "actor_via": "test",
        "tenant_id": "warmup",
        "action": "warmup.coexistence_probe",
        "decision": "allow",
        "resource_kind": "test",
        "resource_id": "warmup",
        "details": {},
    }


def _seed_event(conn: psycopg.Connection, run_id: str, event_id: str) -> None:
    """research_runs + trace_events строки в НЕЗакрытой транзакции conn A
    (держит RowExclusive на trace_events -- окно запроса до коммита)."""
    conn.execute(
        "INSERT INTO research_runs (run_id) VALUES (%s) ON CONFLICT DO NOTHING",
        (run_id,),
    )
    conn.execute(
        "INSERT INTO trace_events (event_id, run_id, ts, stage, event_type)"
        " VALUES (%s, %s, now(), 'upload', 'warmup_probe')",
        (event_id, run_id),
    )


class WarmupNativeTest(unittest.TestCase):
    """Один disposable-деплой на класс (паритет harness AUTH-CERT)."""

    @classmethod
    def setUpClass(cls) -> None:
        base = H.pg().get_uri()
        assert "/postgres?" in base
        cls.db_name = "warmup_" + uuid.uuid4().hex[:16]
        with psycopg.connect(base, autocommit=True) as conn:
            conn.execute(
                psycopg.sql.SQL("CREATE DATABASE {}").format(
                    psycopg.sql.Identifier(cls.db_name)
                )
            )
        cls.dsn = base.replace("/postgres?", f"/{cls.db_name}?", 1)
        # Порядок «миграция до старта api» (docs/authcert/h1fix.md D3):
        # полная auth-цепочка + ops-каталог -- как в проде и как в
        # harness AUTH-CERT (required-фабрики fail-closed на
        # недокатанный каталог -- доктрина AUDIT-6C).
        from apps.api.billing.refund_migrations import apply_migration
        from apps.api.research_runs import run_migrations

        with psycopg.connect(cls.dsn, autocommit=True) as conn:
            apply_migration(conn)
            run_migrations(conn)

    # -- 1. Механизм-репро ------------------------------------------------

    def test_01_lazy_path_deadlock_class_is_real(self) -> None:
        """Fresh (не прогретый) audit-sink + незакрытая транзакция conn A
        на trace_events -> append блокируется lazy-DDL (ALTER ... ACCESS
        EXCLUSIVE) -> lock_timeout даёт LockNotAvailable. Класс
        F-CERT-H1 воспроизведён на реальном PG."""
        from apps.api.security_audit import PostgresAuditSink

        sink = PostgresAuditSink(dsn=_dsn_with_lock_timeout(self.dsn))
        run_id = "warmup-mech-" + uuid.uuid4().hex[:8]
        event_id = "warmup-mech-evt-" + uuid.uuid4().hex[:8]
        raised = None
        with psycopg.connect(self.dsn) as conn_a:
            _seed_event(conn_a, run_id, event_id)
            try:
                # Никакого ensure_schema -- сырой lazy-путь: первый append
                # обязан выполнить каталог и упереться в блокировку.
                sink.append(_audit_record())
            except Exception as exc:  # noqa: BLE001 -- оракул механизма
                raised = exc
            finally:
                conn_a.rollback()
        self.assertIsNotNone(
            raised,
            "ожидался LockNotAvailable от lazy-DDL против незакрытой "
            "транзакции conn A -- класс F-CERT-H1 не воспроизведён",
        )
        self.assertEqual(getattr(raised, "sqlstate", ""), "55P03")
        # Отказ НЕ кэшируется: флаг готовности не выставлен.
        self.assertFalse(sink._schema_ready)

    # -- 2. Сквозной прогрев + coexistence --------------------------------

    def test_02_lifespan_warmup_primes_and_request_path_has_no_ddl(
        self,
    ) -> None:
        from fastapi.testclient import TestClient

        import apps.api.main as main_module
        from apps.api import security_audit, storage_warmup

        env = _deployment_env(self.dsn)
        with mock.patch.dict(os.environ, env, clear=False):
            _reset_singletons()
            with TestClient(main_module.app, base_url=H.STANDALONE) as client:
                # Прогрев выполнен стартом lifespan -- ДО обслуживания.
                resp = client.get("/health/ops")
                self.assertEqual(resp.status_code, 200)
                warm = resp.json()["storage_warmup"]
                self.assertEqual(warm["state"], "primed")
                self.assertEqual(
                    len(warm["layers"]), 12, "полный реестр слоёв (D5)"
                )
                # Честная семантика: Postgres-бэкенды -- primed; слои,
                # чей фабричный контракт выбирает Memory без явного env
                # (support_grants/monitoring, _choose_* default memory) --
                # честный skipped (DDL к Memory неприменим). Ошибок нет.
                self.assertTrue(
                    all(v in ("primed", "skipped") for v in warm["layers"].values()),
                    f"недопустимые статусы слоёв: {warm['layers']}",
                )
                self.assertNotIn("error", set(warm["layers"].values()))
                # Обязательный аудит (субъект coexistence-оракула ниже)
                # прогрет: PostgresAuditSink выбран по DATABASE_URL.
                self.assertEqual(warm["layers"]["audit"], "primed")
                # peek-статус модуля == телу health (паритет).
                self.assertEqual(storage_warmup.last_warmup_status()["state"], "primed")

                # Coexistence-оракул: незакрытая транзакция conn A на
                # trace_events (то самое окно первого запроса) -- audit-
                # append обязан пройти БЕЗ lazy-DDL (класс дедлока закрыт).
                run_id = "warmup-e2e-" + uuid.uuid4().hex[:8]
                event_id = "warmup-e2e-evt-" + uuid.uuid4().hex[:8]
                record = _audit_record()
                with psycopg.connect(self.dsn) as conn_a:
                    _seed_event(conn_a, run_id, event_id)
                    self.assertTrue(security_audit.get_audit_sink().append(record))
                    conn_a.commit()
                # Факты закреплены: событие и аудит-запись на месте.
                with psycopg.connect(self.dsn, autocommit=True) as check:
                    events = check.execute(
                        "SELECT COUNT(*) FROM trace_events WHERE event_id = %s",
                        (event_id,),
                    ).fetchone()[0]
                    audits = check.execute(
                        "SELECT COUNT(*) FROM security_audit_records"
                        " WHERE audit_id = %s",
                        (record["audit_id"],),
                    ).fetchone()[0]
                self.assertEqual(events, 1)
                self.assertEqual(audits, 1)

    def test_03_rerun_lifespan_is_idempotent(self) -> None:
        """Повторный старт lifespan (рестарт процесса) -- снова primed,
        без ошибок прогрева (ensure_schema идемпотентен)."""
        from fastapi.testclient import TestClient

        import apps.api.main as main_module

        env = _deployment_env(self.dsn)
        with mock.patch.dict(os.environ, env, clear=False):
            _reset_singletons()
            with TestClient(main_module.app, base_url=H.STANDALONE) as client:
                resp = client.get("/health/ops")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json()["storage_warmup"]["state"], "primed")

    def test_04_advisory_mode_is_native_noop(self) -> None:
        """advisory + DATABASE_URL: прогрев не создаёт слои и не открывает
        соединений -- /health/ops показывает skipped (ленивый контракт
        dev/тестов сохранён; остаточный риск dev-режима задокументирован)."""
        from fastapi.testclient import TestClient

        import apps.api.main as main_module

        env = _deployment_env(self.dsn)
        env["CISSTAT_STORAGE_MODE"] = "advisory"
        with mock.patch.dict(os.environ, env, clear=False):
            _reset_singletons()
            with TestClient(main_module.app, base_url=H.STANDALONE) as client:
                resp = client.get("/health/ops")
                self.assertEqual(resp.status_code, 200)
                warm = resp.json()["storage_warmup"]
                self.assertEqual(warm["state"], "skipped")
                self.assertNotIn("layers", warm)


if __name__ == "__main__":
    unittest.main()
