"""AUTH-13 worker-credential bootstrap на реальном PostgreSQL (OPS-DIAG-1).

Воспроизведение дефекта 09.11.2026: compose-дефолт CISSTAT_WORKER_KEY=
(пусто) либо ключ без строки в auth_worker_services -> verify() отвечает
503 worker_service_unavailable на каждом цикле document_render_worker
(last_run_at=null, 887+ consecutive_errors) и на пользовательском admit().
Починка: идемпотентный ensure_service_credential (только sha256-дайджест
в БД, паритет WorkerServices.issue); revoked/expired НИКОГДА не
воскрешаются; после bootstrap воркер и service-врата открываются.
"""

import json
import os
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from apps.api.workers import bootstrap
from apps.api.workers.authority import WorkerAuthority
from apps.api.workers.migrations import apply_migration
from apps.api.workers.services import WorkerServices, digest
from tests.integration import test_auth09_objects as previous


class _StubRegistry:
    def list_open_jobs(self, limit):
        return []


class _StubDeliveryService:
    registry = _StubRegistry()


@unittest.skipUnless(
    os.environ.get("CISSTAT_AUTH_TEST_DSN"), "disposable PostgreSQL required"
)
class WorkerCredentialBootstrapTests(unittest.TestCase):
    cleanup = previous.OwnershipSQLTests.cleanup
    client = previous.OwnershipSQLTests.client
    post = previous.OwnershipSQLTests.post
    demo = previous.OwnershipSQLTests.demo

    def setUp(self):
        previous.OwnershipSQLTests.setUp(self)
        with self.access.transaction() as tx:
            apply_migration(tx.connection)
        bootstrap.reset_for_testing()
        self.addCleanup(bootstrap.reset_for_testing)
        self.key = bootstrap.generate_key()

    # -- helpers --

    def rows(self, sql, params=None):
        with self.access.transaction(readonly=True) as tx:
            return tx.connection.execute(sql, params or ()).fetchall()

    def error(self, fn, status, code=None):
        with self.assertRaises(HTTPException) as e:
            fn()
        self.assertEqual(e.exception.status_code, status, e.exception.detail)
        if code:
            self.assertEqual(e.exception.detail["code"], code)

    def _worker(self, key):
        from apps.api.document_render_worker import DocumentRenderWorker

        return DocumentRenderWorker(
            service=_StubDeliveryService(),
            worker_authority=WorkerAuthority(self.access, key),
            interval=1,
        )

    def _render_admission(self, ctx, run):
        from apps.api.billing.contract import Admission, Cost

        return Admission(
            entry_id="api:GET:/v1/internal/rules/templates",
            resource_kind="run",
            resource_id=run.run_id,
            idempotency_key="bootstrap-render",
            payload={"task": "native"},
            cost=Cost(micro_cu=0, version="bootstrap-only/1"),
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            slots=1,
        )

    def _ctx_and_run(self):
        from apps.api.authentication.context import RequestContext

        owner = self.client()
        token = owner.cookies.get("__Host-cisstat_auth")
        e = self.auth.verify(token)
        with self.access.transaction(readonly=True) as tx:
            a = tx.accounts.get(e.account_id)
            u = tx.identities.get(e.subject_id)
        ctx = RequestContext(
            subject_id=e.subject_id,
            account_id=e.account_id,
            tenant_id=str(a.tenant_id),
            auth_method=e.auth_method,
            credential_id=e.credential_id,
            auth_session_id=e.auth_session_id,
            subject_version=u.subject_version,
            entitlement_version=a.entitlement_version,
            request_id="bootstrap-test",
        )
        _session, run = self.demo(owner)
        return ctx, run

    # -- 1. воспроизведение дефекта --

    def test_defect_empty_env_key_worker_cycle_records_503(self):
        """Compose-дефолт CISSTAT_WORKER_KEY=: цикл воркера -- 503
        worker_service_unavailable, last_run_at остаётся None (симптом
        /health/ops 09.11.2026: 887+ consecutive_errors, last_run_at=null)."""
        with patch.dict(os.environ, {bootstrap.ENV_WORKER_KEY: ""}):
            auth = WorkerAuthority(self.access, "")
            self.error(
                auth.reconcile, 503, "worker_service_unavailable"
            )
        worker = self._worker("")
        with patch.dict(os.environ, {bootstrap.ENV_WORKER_KEY: ""}):
            worker.run_once()
        status = worker.status()
        self.assertEqual(status["consecutive_errors"], 1)
        self.assertIsNone(status["last_run_at"])
        self.assertIn("worker_service_unavailable", status["last_error"])
        self.assertEqual(
            status["last_error_code"], "worker_service_unavailable"
        )

    def test_defect_valid_key_without_row_blocks_reconcile_and_admit(self):
        """Ключ задан, но строки нет (потерянная/непроведённая выдача):
        пользовательский admit() тоже 503 -- рендер документов недоступен."""
        auth = WorkerAuthority(self.access, self.key)
        self.error(auth.reconcile, 503, "worker_service_unavailable")
        ctx, run = self._ctx_and_run()
        request = self._render_admission(ctx, run)
        self.error(
            lambda: auth.admit(
                ctx,
                request,
                kind="render",
                external_id="bootstrap-render",
                run_id=run.run_id,
                descriptor={"bootstrap": True},
            ),
            503,
            "worker_service_unavailable",
        )
        self.assertEqual(
            self.rows("SELECT count(*) AS n FROM auth_worker_services")[0]["n"],
            0,
        )

    # -- 2. починка --

    def test_bootstrap_registers_credential_and_heals_worker(self):
        auth = WorkerAuthority(self.access, self.key)
        self.error(auth.reconcile, 503, "worker_service_unavailable")
        outcome = bootstrap.ensure_service_credential(
            store=self.access, key=self.key
        )
        self.assertEqual(outcome["state"], "registered")
        self.assertEqual(
            sorted(outcome["kinds"]), ["delivery", "modeling", "render"]
        )
        self.assertTrue(outcome["service_id"])
        self.assertNotIn(self.key, json.dumps(outcome))
        # service-врата открыты: reconcile/find без 503
        summary = WorkerAuthority(self.access, self.key).reconcile()
        self.assertEqual(summary["pending_expired"], 0)
        self.assertIsNone(
            WorkerAuthority(self.access, self.key).find("render", "no-such-job")
        )
        # воркер восстанавливается: успешный цикл, счётчики чистые
        worker = self._worker(self.key)
        worker.run_once()
        status = worker.status()
        self.assertEqual(status["consecutive_errors"], 0)
        self.assertIsNotNone(status["last_run_at"])
        self.assertIsNone(status["last_error"])
        # строка в БД: kinds/expiry; аудит с transition service_bootstrapped
        rows = self.rows(
            "SELECT kinds, created_at, expires_at, revoked_at FROM auth_worker_services"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            sorted(rows[0]["kinds"]), ["delivery", "modeling", "render"]
        )
        self.assertGreater(rows[0]["expires_at"], rows[0]["created_at"])
        self.assertIsNone(rows[0]["revoked_at"])
        audit_blob = json.dumps(
            [r["payload"] for r in self.rows("SELECT payload FROM auth_audit_outbox")],
            default=str,
        )
        self.assertIn("service_bootstrapped", audit_blob)
        self.assertNotIn(self.key, audit_blob)

    def test_bootstrap_is_idempotent_single_row(self):
        first = bootstrap.ensure_service_credential(
            store=self.access, key=self.key
        )
        second = bootstrap.ensure_service_credential(
            store=self.access, key=self.key
        )
        self.assertEqual(first["state"], "registered")
        self.assertEqual(second["state"], "present")
        self.assertEqual(first["service_id"], second["service_id"])
        self.assertEqual(
            self.rows("SELECT count(*) AS n FROM auth_worker_services")[0]["n"],
            1,
        )

    def test_bootstrap_never_resurrects_revoked(self):
        outcome = bootstrap.ensure_service_credential(
            store=self.access, key=self.key
        )
        WorkerServices(self.access).revoke(
            outcome["service_id"], reason="ops revoke test"
        )
        again = bootstrap.ensure_service_credential(
            store=self.access, key=self.key
        )
        self.assertEqual(again["state"], "revoked")
        self.assertIsNotNone(again["revoked_at"])
        self.assertEqual(
            self.rows("SELECT count(*) AS n FROM auth_worker_services")[0]["n"],
            1,
        )
        self.error(
            WorkerAuthority(self.access, self.key).reconcile,
            503,
            "worker_service_unavailable",
        )

    def test_bootstrap_never_extends_expired(self):
        expired_key = bootstrap.generate_key()
        key_hash = digest(expired_key)
        with self.access.transaction() as tx:
            c = tx.connection
            now = c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
            c.execute(
                "INSERT INTO auth_worker_services"
                "(service_id,key_hash,kinds,created_at,expires_at) "
                "VALUES (%s,%s,%s,%s,%s)",
                (
                    uuid4(),
                    key_hash,
                    ["render"],
                    now - timedelta(days=400),
                    now - timedelta(days=30),
                ),
            )
        outcome = bootstrap.ensure_service_credential(
            store=self.access, key=expired_key
        )
        self.assertEqual(outcome["state"], "expired")
        self.assertIn("ротация", outcome["remediation"])
        rows = self.rows(
            "SELECT expires_at FROM auth_worker_services WHERE key_hash=%s",
            (key_hash,),
        )
        self.assertEqual(len(rows), 1)
        self.assertLess(rows[0]["expires_at"], datetime.now(UTC))
        self.error(
            WorkerAuthority(self.access, expired_key).reconcile,
            503,
            "worker_service_unavailable",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
