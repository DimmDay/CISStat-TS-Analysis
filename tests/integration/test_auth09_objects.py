"""AUTH-09 native PostgreSQL + actual HTTP boundary, no simulated durability."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.authentication.errors import RepositoryConflict, VersionConflict
from apps.api.authentication.mfa_migrations import apply_migration
from apps.api.authentication.sessions import SessionService
from apps.api.authentication.storage import PostgresAccessStore
from apps.api.research_runs import PostgresResearchRunStore, ResearchRun, run_migrations
from apps.api.session_store import (
    AnalysisSession,
    DatasetInfo,
    PostgresSessionStore,
    SessionConflictError,
)

DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")
ORIGIN = "https://ownership.example"
PASSWORD = "AUTH09 disposable local test passphrase!"


@unittest.skipUnless(DSN, "Mandatory runner requires disposable PostgreSQL DSN")
class OwnershipSQLTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo

        from apps.api import research_runs, session_store

        self.pg, self.sql = psycopg, sql
        self.schema = "auth09_" + uuid4().hex
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup)
        self.dsn = make_conninfo(DSN, options="-csearch_path=" + self.schema)
        with psycopg.connect(self.dsn) as c:
            run_migrations(c)
        self.access = PostgresAccessStore(self.dsn, schema=self.schema)
        with self.access.transaction() as tx:
            apply_migration(tx.connection)
            self.person = tx.identities.create()
            self.member = tx.identities.create()
            self.account = tx.accounts.create(
                self.person.subject_id,
                account_type="multi",
                plan="professional",
                seats=2,
            )
            tx.accounts.add_member(
                self.account.account_id,
                self.member.subject_id,
                expected_version=self.account.entitlement_version,
            )
            self.other = tx.accounts.create(self.person.subject_id, plan="starter")
        self.sessions = PostgresSessionStore(self.dsn)
        self.runs = PostgresResearchRunStore(self.dsn)
        self.auth = SessionService(self.access)
        self.auth.set_password(self.person.subject_id, "owner09", PASSWORD)
        self.auth.set_password(self.member.subject_id, "member09", PASSWORD)
        self.temp = tempfile.TemporaryDirectory(
            prefix="auth09-data-", dir=Path(__file__).resolve().parents[3]
        )
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(
            os.environ,
            {
                "DATABASE_URL": self.dsn,
                "CISSTAT_SESSION_BACKEND": "postgres",
                "CISSTAT_STORAGE_MODE": "required",
                "CISSTAT_DATA_DIR": self.temp.name,
                "CISSTAT_AUTH_CSRF_KEY": "ownership-disposable-test-key-" + "x" * 32,
                "CISSTAT_AUTH_ALLOWED_ORIGINS": ORIGIN,
                "CISSTAT_IDENTITY_MODE": "session_scoped",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        for reset in (
            session_store.reset_session_store_for_testing,
            research_runs.reset_research_run_store_for_testing,
            research_runs.reset_dataset_file_store_for_testing,
        ):
            reset()
            self.addCleanup(reset)
        from apps.api.routers import authentication, documentation, progress, session
        from apps.api.trace_hook import TraceHookMiddleware

        self.app = FastAPI()
        self.app.state.auth_access_store = self.access
        self.app.state.auth_session_service = self.auth
        for name, module in [
            ("auth", authentication),
            ("progress", progress),
            ("session", session),
            ("documentation", documentation),
        ]:
            self.app.include_router(module.router, prefix="/v1/" + name)
        self.app.add_middleware(TraceHookMiddleware)

    def cleanup(self):
        with self.pg.connect(DSN, autocommit=True) as c:
            c.execute(
                self.sql.SQL("DROP SCHEMA {} CASCADE").format(
                    self.sql.Identifier(self.schema)
                )
            )

    def client(self, account=None, member=False):
        account = account or self.account
        result = self.auth.login(
            "member09" if member else "owner09",
            PASSWORD,
            account.account_id,
            origin=ORIGIN,
        )
        client = TestClient(self.app, base_url=ORIGIN)
        client.cookies.set(
            "__Host-cisstat_auth", result.token, domain="ownership.example", path="/"
        )
        return client

    def post(self, client, path, payload=None):
        proof = client.get("/v1/auth/csrf", headers={"Origin": ORIGIN})
        self.assertEqual(proof.status_code, 200, proof.text)
        return client.post(
            path,
            json=payload or {},
            headers={"Origin": ORIGIN, "X-CSRF-Token": proof.json()["csrf_token"]},
        )

    def demo(self, client):
        r = self.post(client, "/v1/session/demo")
        self.assertEqual(r.status_code, 200, r.text)
        session = self.sessions.get(client.cookies.get("cisstat_session_id"))
        self.assertTrue(session.run_id)
        return session, self.runs.get_run(session.run_id)

    def legacy(self, owner=True):
        from apps.api.identity import subject_pseudonym

        pointer = uuid4().hex
        run = ResearchRun(
            run_id="RUN-" + uuid4().hex[:8].upper(),
            session_id=pointer,
            owner_subject=subject_pseudonym(pointer) if owner else None,
            tenant_id="tenant-default" if owner else None,
            ownership="bound" if owner else None,
        )
        s = AnalysisSession(
            pointer, owner_subject=run.owner_subject, tenant_id=run.tenant_id
        )
        s.set_dataset(
            DatasetInfo(str(uuid4()), "legacy.csv", 4, 1, "1KB"),
            pd.DataFrame({"v": [1, 2, 3, 4]}),
        )
        s.run_id = run.run_id
        self.sessions.save(s)
        self.runs.upsert_run(run)
        return s, run

    def migrate(self, run, account=None, **changes):
        from apps.api.accounts.ownership_migration import migrate_legacy_run

        account = account or self.account
        with self.access.transaction(readonly=True) as tx:
            current = tx.accounts.get(account.account_id)
        args = {
            "run_id": run.run_id,
            "account_id": account.account_id,
            "expected_account_version": current.entitlement_version,
            "expected_owner_subject": run.owner_subject,
            "expected_tenant_id": run.tenant_id,
            "expected_version": 0,
            "evidence": "TICKET-AUTH09-TEST",
            "reason": "Reviewed operator migration",
        }
        args.update(changes)
        return migrate_legacy_run(store=self.access, **args)

    def test_new_named_run_and_session_account(self):
        s, r = self.demo(self.client())
        self.assertEqual(s.owner_account_id, str(self.account.account_id))
        self.assertEqual(r.owner_account_id, str(self.account.account_id))
        self.assertEqual(r.owner_subject, str(self.person.subject_id))
        self.assertEqual(r.tenant_id, str(self.account.tenant_id))
        self.assertEqual(r.ownership_version, 1)

    def test_same_person_other_account_denied_session_trace_doclog_and_uniform404(self):
        _, r = self.demo(self.client())
        b = self.client(self.other)
        for path in ("/v1/session/current", "/v1/progress/trace"):
            b.cookies.set(
                "cisstat_session_id", r.session_id, domain="ownership.example", path="/"
            )
            response = b.get(path)
            self.assertEqual(response.status_code, 404, response.text)
        b.cookies.delete("cisstat_session_id", domain="ownership.example", path="/")
        for root, suffix in (
            ("/v1/progress/runs/", ""),
            ("/v1/documentation/runs/", "/documents"),
        ):
            foreign = b.get(root + r.run_id + suffix)
            missing = b.get(root + "RUN-FFFFFFFF" + suffix)
            self.assertEqual(foreign.status_code, 404, foreign.text)
            self.assertEqual(foreign.json(), missing.json())

    def test_legacy_cookie_no_auto_claim(self):
        s, r = self.legacy()
        c = self.client()
        c.cookies.set(
            "cisstat_session_id", s.session_id, domain="ownership.example", path="/"
        )
        response = c.get("/v1/session/current")
        self.assertEqual(response.status_code, 404, response.text)
        self.assertIsNone(self.runs.get_run(r.run_id).owner_account_id)

    def test_chosen_unknown_cookie_rotated_and_anonymous_cannot_reuse(self):
        c = self.client()
        c.cookies.set(
            "cisstat_session_id", "attacker-fixed", domain="ownership.example", path="/"
        )
        response = c.get("/v1/session/current")
        self.assertEqual(response.status_code, 200, response.text)
        pointer = c.cookies.get("cisstat_session_id")
        self.assertNotEqual(pointer, "attacker-fixed")
        anon = TestClient(self.app, base_url=ORIGIN)
        anon.cookies.set(
            "cisstat_session_id", pointer, domain="ownership.example", path="/"
        )
        self.assertEqual(anon.get("/v1/session/current").status_code, 404)

    def test_member_post_restore_csrf_and_author_preserved(self):
        s, r = self.demo(self.client())
        c = self.client(member=True)
        path = f"/v1/progress/runs/{r.run_id}/restore"
        self.assertEqual(c.get(path).status_code, 403)
        self.assertEqual(c.post(path).status_code, 403)
        restored = self.post(c, path)
        self.assertEqual(restored.status_code, 200, restored.text)
        new = self.sessions.get(c.cookies.get("cisstat_session_id"))
        self.assertNotEqual(new.session_id, s.session_id)
        self.assertEqual(new.owner_account_id, str(self.account.account_id))
        self.assertEqual(new.owner_subject, str(self.person.subject_id))
        self.assertEqual(
            self.runs.get_run(r.run_id).owner_subject, str(self.person.subject_id)
        )

    def test_account_switch_login_rotates_auth_and_clears_research(self):
        c = self.client()
        self.demo(c)
        old = c.cookies.get("__Host-cisstat_auth")
        result = self.post(
            c,
            "/v1/auth/login",
            {
                "login": "owner09",
                "password": PASSWORD,
                "account_id": str(self.other.account_id),
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertNotEqual(c.cookies.get("__Host-cisstat_auth"), old)
        self.assertFalse(c.cookies.get("cisstat_session_id"))

    def test_migration_preserves_data_provenance_and_fences_stale_save(self):
        s, r = self.legacy()
        before = self.sessions.get(s.session_id)
        data = before.dataframe.to_json()
        result = self.migrate(r)
        after = self.sessions.get(s.session_id)
        self.assertEqual(after.dataframe.to_json(), data)
        self.assertEqual(after.owner_subject, r.owner_subject)
        self.assertEqual(after.owner_account_id, str(self.account.account_id))
        self.assertEqual(result["ownership_version"], 1)
        with self.assertRaises(SessionConflictError):
            self.sessions.save(before)

    def test_unknown_author_not_invented(self):
        _, r = self.legacy(owner=False)
        self.migrate(r)
        self.assertIsNone(self.runs.get_run(r.run_id).owner_subject)

    def test_restore_unknown_author_preserves_tenant_and_source_bytes(self):
        from apps.api.research_runs import get_dataset_file_store

        _, r = self.legacy(owner=False)
        files = get_dataset_file_store()
        data = b"v\n1\n2\n3\n4\n"
        fp = files.save_upload(data, "legacy.csv", rows=4, columns=1, size_label="1KB")
        r = replace(r, dataset_name="legacy.csv", dataset_fingerprint=fp)
        self.runs.upsert_run(r)
        self.migrate(r)
        c = self.client(member=True)
        response = self.post(c, f"/v1/progress/runs/{r.run_id}/restore")
        self.assertEqual(response.status_code, 200, response.text)
        s = self.sessions.get(c.cookies.get("cisstat_session_id"))
        self.assertIsNone(s.owner_subject)
        self.assertEqual(s.tenant_id, str(self.account.tenant_id))
        self.assertEqual(c.get("/v1/session/current").status_code, 200)
        self.assertEqual(files.load(fp).data, data)

    def test_regular_sql_upsert_cannot_claim_legacy(self):
        _, r = self.legacy()
        with self.assertRaises(self.pg.IntegrityError):
            self.runs.upsert_run(
                replace(
                    r,
                    owner_account_id=str(self.account.account_id),
                    ownership_version=1,
                )
            )
        self.assertIsNone(self.runs.get_run(r.run_id).owner_account_id)

    def test_bound_account_and_provenance_immutable(self):
        _, r = self.demo(self.client())
        for change in (
            {"owner_account_id": str(self.other.account_id)},
            {"owner_subject": "rewritten"},
            {"tenant_id": str(self.other.tenant_id)},
        ):
            with self.assertRaises(self.pg.IntegrityError):
                self.runs.upsert_run(replace(r, **change))

    def test_one_time_and_expected_source(self):
        _, r = self.legacy()
        with self.assertRaises(VersionConflict):
            self.migrate(r, expected_owner_subject="wrong")
        self.migrate(r)
        with self.assertRaises(VersionConflict):
            self.migrate(r)

    def test_two_concurrent_targets_one_winner(self):
        _, r = self.legacy()
        barrier = Barrier(2)

        def work(account):
            barrier.wait(timeout=10)
            try:
                self.migrate(r, account=account)
                return "ok"
            except VersionConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(
                list(pool.map(work, [self.account, self.other])), ["ok", "conflict"]
            )

    def test_real_audit_insert_failure_rolls_back_everything(self):
        _, r = self.legacy()
        with self.access.transaction() as tx:
            tx.connection.execute(
                "CREATE FUNCTION a09_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit fault' USING ERRCODE='23514'; END $$"
            )
            tx.connection.execute(
                "CREATE TRIGGER a09_fault BEFORE INSERT ON auth_audit_outbox FOR EACH ROW EXECUTE FUNCTION a09_fault()"
            )
        with self.assertRaises(RepositoryConflict):
            self.migrate(r)
        self.assertIsNone(self.runs.get_run(r.run_id).owner_account_id)
        self.assertIsNone(self.sessions.get(r.session_id).owner_account_id)
        with self.access.transaction(readonly=True) as tx:
            self.assertEqual(
                tx.connection.execute(
                    "SELECT count(*) AS n FROM run_ownership_migrations"
                ).fetchone()["n"],
                0,
            )

    def test_receipt_immutable_and_no_raw_cookie_in_audit(self):
        _, r = self.legacy()
        self.migrate(r)
        with self.access.transaction(readonly=True) as tx:
            receipts = tx.connection.execute(
                "SELECT * FROM run_ownership_migrations"
            ).fetchall()
            audits = tx.connection.execute(
                "SELECT payload FROM auth_audit_outbox WHERE payload->>'action'='auth_ownership_migrated'"
            ).fetchall()
        self.assertEqual(len(audits), 1)
        self.assertNotIn(r.session_id, str(receipts) + str(audits))
        with self.assertRaises(RepositoryConflict), self.access.transaction() as tx:
            tx.connection.execute(
                "DELETE FROM run_ownership_migrations WHERE run_id=%s", (r.run_id,)
            )

    def test_stale_and_suspended_target_do_not_claim(self):
        _, r = self.legacy()
        with self.assertRaises(VersionConflict):
            self.migrate(r, expected_account_version=999)
        with self.access.transaction() as tx:
            a = tx.accounts.get(self.account.account_id)
            tx.accounts.update(
                a.account_id, expected_version=a.entitlement_version, status="suspended"
            )
        with self.assertRaises(RepositoryConflict):
            self.migrate(r)
        self.assertIsNone(self.runs.get_run(r.run_id).owner_account_id)

    def test_revoked_member_cannot_fallback_pointer(self):
        _, r = self.demo(self.client())
        c = self.client(member=True)
        result = self.post(c, f"/v1/progress/runs/{r.run_id}/restore")
        self.assertEqual(result.status_code, 200, result.text)
        with self.access.transaction() as tx:
            a = tx.accounts.get(self.account.account_id)
            tx.accounts.update_member(
                a.account_id,
                self.member.subject_id,
                expected_version=a.entitlement_version,
                status="revoked",
            )
        for path in (
            "/v1/session/current",
            f"/v1/documentation/runs/{r.run_id}/documents",
        ):
            denied = c.get(path)
            self.assertEqual(denied.status_code, 401, denied.text)
            self.assertEqual(denied.json()["detail"]["code"], "invalid_credential")

    def test_fresh_process_and_doclog_gate_after_migration(self):
        _, r = self.legacy()
        self.migrate(r)
        code = "import os,json;from apps.api.research_runs import PostgresResearchRunStore;r=PostgresResearchRunStore(os.environ['AUTH09_DSN']).get_run(os.environ['AUTH09_RUN']);print(json.dumps(r.to_dict()))"
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "AUTH09_DSN": self.dsn, "AUTH09_RUN": r.run_id},
        )
        self.assertEqual(
            json.loads(result.stdout)["owner_account_id"], str(self.account.account_id)
        )
        path = f"/v1/documentation/runs/{r.run_id}/documents"
        self.assertEqual(self.client(member=True).get(path).status_code, 200)
        self.assertEqual(self.client(self.other).get(path).status_code, 404)

    def test_sql_new_binding_cannot_have_null_ownership_state(self):
        with self.assertRaises(self.pg.IntegrityError), self.pg.connect(self.dsn) as c:
            c.execute(
                "INSERT INTO research_runs(run_id,owner_account_id,ownership_version,tenant_id) VALUES (%s,%s,1,%s)",
                ("RUN-A0999999", self.account.account_id, str(self.account.tenant_id)),
            )

    def test_reject_unsupported_non_atomic_topologies(self):
        _, r = self.legacy()
        for config in (
            {"CISSTAT_SESSION_BACKEND": "redis"},
            {"CISSTAT_STORAGE_MODE": "advisory"},
            {"DATABASE_URL": "postgresql://postgres@127.0.0.1:1/other"},
        ):
            with patch.dict(os.environ, config), self.assertRaises(RepositoryConflict):
                self.migrate(r)
        self.assertIsNone(self.runs.get_run(r.run_id).owner_account_id)


if __name__ == "__main__":
    unittest.main()
