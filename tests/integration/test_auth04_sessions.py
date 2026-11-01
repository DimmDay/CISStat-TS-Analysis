"""AUTH-04 real SQL and ASGI contracts. Mandatory runner forbids missing DSN."""

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from apps.api.authentication.storage import PostgresAccessStore
from apps.api.authentication.sessions import SessionService, token_digest
from apps.api.authentication.mfa_migrations import apply_migration
from apps.api.routers.authentication import router

DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")
PASS = "A durable passphrase for AUTH04!"
NEW = "A replacement secret passphrase!"
ORIGIN = "https://standalone.example"


@unittest.skipUnless(DSN, "Mandatory runner requires CISSTAT_AUTH_TEST_DSN")
class SessionSQLTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql

        self.pg, self.sql = psycopg, sql
        self.schema = "auth04_" + uuid4().hex
        with psycopg.connect(DSN, autocommit=True) as c:
            c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        self.addCleanup(self.cleanup)
        self.store = PostgresAccessStore(DSN, schema=self.schema)
        with self.store.transaction() as tx:
            apply_migration(tx.connection)
        with self.store.transaction() as tx:
            self.owner = tx.identities.create()
            self.account = tx.accounts.create(self.owner.subject_id)
        self.now = datetime.now(timezone.utc)
        self.service = SessionService(store=self.store, clock=lambda: self.now)
        self.credential = self.service.set_password(
            self.owner.subject_id, "alice04", PASS
        )

    def cleanup(self):
        with self.pg.connect(DSN, autocommit=True) as c:
            c.execute(
                self.sql.SQL("DROP SCHEMA {} CASCADE").format(
                    self.sql.Identifier(self.schema)
                )
            )

    def login(self, **changes):
        return self.service.login(
            "alice04", PASS, self.account.account_id, origin=ORIGIN, **changes
        )

    def error(self, work, status, code=None):
        with self.assertRaises(HTTPException) as result:
            work()
        self.assertEqual(result.exception.status_code, status)
        if code:
            self.assertEqual(result.exception.detail["code"], code)
        self.assertNotIn(PASS, str(result.exception.detail))

    def rows(self, table):
        with self.store.transaction(readonly=True) as tx:
            return tx.connection.execute("SELECT * FROM " + table).fetchall()

    def test_hash_only_persistence_and_safe_public_list(self):
        a = self.login()
        data = (
            self.rows("auth_password_credentials")
            + self.rows("auth_sessions")
            + self.rows("auth_audit_outbox")
        )
        text = str(data)
        self.assertNotIn(PASS, text)
        self.assertNotIn(a.token, text)
        self.assertEqual(
            self.rows("auth_sessions")[0]["token_hash"], token_digest(a.token)
        )
        self.assertNotIn(a.token, repr(a))
        listing = self.service.list_sessions(a.token)
        self.assertEqual(len(listing), 1)
        self.assertNotIn("hash", str(listing))

    def test_fixation_login_always_rotates_and_revokes_old(self):
        a = self.login()
        b = self.login(old_token=a.token)
        self.assertNotEqual(a.token, b.token)
        self.assertNotEqual(a.session["session_id"], b.session["session_id"])
        self.error(lambda: self.service.verify(a.token), 401)
        self.service.verify(b.token)

    def test_chosen_or_missing_sid_is_not_used_on_login(self):
        a = self.login(old_token="client-fixed-sid")
        self.assertTrue(a.token.startswith("s1_"))
        self.assertNotIn("client-fixed", a.token)

    def test_inclusive_idle_expiry(self):
        a = self.login()
        self.now += timedelta(minutes=15)
        self.error(lambda: self.service.verify(a.token), 401)

    def test_idle_touch_does_not_move_absolute_expiry(self):
        a = self.login()
        for _ in range(47):
            self.now += timedelta(minutes=10)
            self.service.verify(a.token)
        row = self.rows("auth_sessions")[0]
        self.assertEqual(
            row["absolute_expires_at"],
            datetime.fromisoformat(a.session["absolute_expires_at"]),
        )
        self.now = datetime.fromisoformat(a.session["absolute_expires_at"])
        self.error(lambda: self.service.verify(a.token), 401)

    def test_logout_idempotent_and_replay_rejected(self):
        a = self.login()
        self.service.logout(a.token)
        self.service.logout(a.token)
        self.error(lambda: self.service.verify(a.token), 401)

    def test_revoke_one_does_not_revoke_other(self):
        a = self.login()
        b = self.login()
        self.service.revoke(b.token, a.session["session_id"])
        self.error(lambda: self.service.verify(a.token), 401)
        self.service.verify(b.token)

    def test_revoke_all_is_subject_scoped_and_terminal(self):
        a = self.login()
        b = self.login()
        self.service.revoke(a.token, all_sessions=True)
        for token in (a.token, b.token):
            self.error(lambda: self.service.verify(token), 401)

    def test_password_change_revokes_all_and_rejects_old_password(self):
        a = self.login()
        b = self.login()
        self.service.change_password(a.token, PASS, NEW)
        for token in (a.token, b.token):
            self.error(lambda: self.service.verify(token), 401)
        self.error(self.login, 401)
        self.service.login("alice04", NEW, self.account.account_id, origin=ORIGIN)

    def test_wrong_current_password_does_not_mutate(self):
        a = self.login()
        before = self.rows("auth_password_credentials")[0]
        self.error(lambda: self.service.change_password(a.token, "wrong", NEW), 401)
        self.assertEqual(self.rows("auth_password_credentials")[0], before)
        self.service.verify(a.token)

    def test_suspend_then_reactivate_does_not_resurrect(self):
        a = self.login()
        with self.store.transaction() as tx:
            u = tx.identities.get(self.owner.subject_id)
            tx.identities.set_status(
                u.subject_id, "suspended", expected_version=u.subject_version
            )
        self.error(lambda: self.service.verify(a.token), 401)
        with self.store.transaction() as tx:
            u = tx.identities.get(self.owner.subject_id)
            tx.identities.set_status(
                u.subject_id, "active", expected_version=u.subject_version
            )
        self.error(lambda: self.service.verify(a.token), 401)

    def test_direct_role_change_invalidates_session_version(self):
        a = self.login()
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_identities SET platform_role='internal_analyst',subject_version=subject_version+1 WHERE subject_id=%s",
                (self.owner.subject_id,),
            )
        self.error(lambda: self.service.verify(a.token), 401)

    def test_admin_password_is_not_full_mfa_session(self):
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_identities SET platform_role='admin',subject_version=subject_version+1 WHERE subject_id=%s",
                (self.owner.subject_id,),
            )
        self.error(self.login, 403, "mfa_required")
        self.assertFalse(self.rows("auth_sessions"))

    def test_foreign_or_missing_account_not_adopted(self):
        self.error(
            lambda: self.service.login("alice04", PASS, uuid4(), origin=ORIGIN), 403
        )
        self.assertFalse(self.rows("auth_sessions"))

    def test_member_revoke_and_account_close_checked_online(self):
        a = self.login()
        with self.store.transaction() as tx:
            ac = tx.accounts.get(self.account.account_id)
            tx.accounts.update(
                ac.account_id, expected_version=ac.entitlement_version, status="closed"
            )
        self.error(lambda: self.service.verify(a.token), 401)

    def test_wrong_and_unknown_login_same_error(self):
        self.error(
            lambda: self.service.login(
                "unknown04", PASS, self.account.account_id, origin=ORIGIN
            ),
            401,
            "invalid_credential",
        )
        self.error(
            lambda: self.service.login(
                "alice04", "wrong", self.account.account_id, origin=ORIGIN
            ),
            401,
            "invalid_credential",
        )

    def test_durable_throttle_limits_attempts(self):
        for _ in range(10):
            self.error(
                lambda: self.service.login(
                    "alice04", "wrong", self.account.account_id, origin=ORIGIN
                ),
                401,
            )
        self.error(self.login, 429)

    def test_outbox_failure_rolls_back_issue_and_revoke(self):
        a = self.login()
        with patch.object(
            self.service, "_audit", side_effect=RuntimeError("injected audit failure")
        ):
            self.error(lambda: self.service.revoke(a.token, all_sessions=True), 503)
        self.service.verify(a.token)
        count = len(self.rows("auth_sessions"))
        with patch.object(
            self.service, "_audit", side_effect=RuntimeError("injected audit failure")
        ):
            self.error(self.login, 503)
        self.assertEqual(len(self.rows("auth_sessions")), count)

    def test_schema_outage_never_falls_back_or_exposes_driver_error(self):
        a = self.login()
        with self.store.transaction() as tx:
            tx.connection.execute("DROP TABLE auth_audit_outbox")
        self.error(lambda: self.service.logout(a.token), 503)
        # Failed command rolled back: revocation was not silently committed.
        self.assertIsNone(self.rows("auth_sessions")[0]["revoked_at"])

    def test_fresh_python_process_observes_persisted_session(self):
        import subprocess

        a = self.login()
        code = """import os
from apps.api.authentication.sessions import SessionService
from apps.api.authentication.storage import PostgresAccessStore
s=SessionService(store=PostgresAccessStore(os.environ['CISSTAT_AUTH_TEST_DSN'],schema=os.environ['AUTH04_TEST_SCHEMA']))
e=s.verify(os.environ['AUTH04_TEST_BEARER'])
assert e.subject_id==os.environ['AUTH04_TEST_OWNER']
print('fresh process persisted session verified')
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env={
                **os.environ,
                "AUTH04_TEST_SCHEMA": self.schema,
                "AUTH04_TEST_BEARER": a.token,
                "AUTH04_TEST_OWNER": str(self.owner.subject_id),
                "PYTHONIOENCODING": "utf-8",
            },
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(a.token, result.stdout + result.stderr)

    def test_revoked_member_loses_session_without_harming_owner(self):
        with self.store.transaction() as tx:
            account = tx.accounts.get(self.account.account_id)
            account = tx.accounts.update(
                account.account_id,
                expected_version=account.entitlement_version,
                account_type="multi",
                seats=2,
            )
            member = tx.identities.create()
            tx.accounts.add_member(
                account.account_id,
                member.subject_id,
                expected_version=account.entitlement_version,
            )
        self.service.set_password(member.subject_id, "member04", PASS)
        owner = self.login()
        member_session = self.service.login(
            "member04", PASS, self.account.account_id, origin=ORIGIN
        )
        with self.store.transaction() as tx:
            account = tx.accounts.get(self.account.account_id)
            tx.accounts.update_member(
                account.account_id,
                member.subject_id,
                expected_version=account.entitlement_version,
                status="revoked",
            )
        self.error(lambda: self.service.verify(member_session.token), 401)
        self.service.verify(owner.token)

    def test_same_identity_two_accounts_keep_server_bindings(self):
        with self.store.transaction() as tx:
            other = tx.accounts.create(self.owner.subject_id)
        first = self.login()
        second = self.service.login("alice04", PASS, other.account_id, origin=ORIGIN)
        self.assertEqual(
            self.service.verify(first.token).account_id, str(self.account.account_id)
        )
        self.assertEqual(
            self.service.verify(second.token).account_id, str(other.account_id)
        )

    def test_foreign_session_id_cannot_be_revoked(self):
        a = self.login()
        self.error(
            lambda: self.service.revoke(a.token, uuid4()), 404, "session_not_found"
        )
        self.service.verify(a.token)

    def test_family_revoke_does_not_affect_other_login(self):
        a = self.login()
        b = self.login()
        self.service.revoke(b.token, family_id=a.session["family_id"])
        self.error(lambda: self.service.verify(a.token), 401)
        self.service.verify(b.token)

    def test_credential_revoke_invalidates_sessions_and_password(self):
        a = self.login()
        self.service.revoke_password(
            self.owner.subject_id, expected_version=self.credential["version"]
        )
        self.error(lambda: self.service.verify(a.token), 401)
        self.error(self.login, 401)

    def test_schema_checksum_drift_denies_session_resolution(self):
        a = self.login()
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_schema_versions SET checksum='drift' WHERE version='0020_auth04_sessions'"
            )
        self.error(lambda: self.service.verify(a.token), 503)

    def test_password_change_during_verification_never_issues_stale_session(self):
        original = self.service.codec.verify

        def race(encoded, password):
            self.service.set_password(
                self.owner.subject_id,
                "alice04",
                NEW,
                expected_version=self.credential["version"],
            )
            return original(encoded, password)

        with patch.object(self.service.codec, "verify", side_effect=race):
            self.error(self.login, 401)
        self.assertFalse(self.rows("auth_sessions"))

    def test_outbox_replay_preserves_ids_across_partial_delivery_failure(self):
        from apps.api.authentication.audit_outbox import publish_pending

        self.login()

        class Sink:
            def __init__(self):
                self.records = {}
                self.fail = True

            def append(self, record):
                self.records[record["audit_id"]] = record
                if self.fail:
                    self.fail = False
                    return False
                return True

        sink = Sink()
        self.error(lambda: publish_pending(store=self.store, sink=sink), 503)
        self.assertTrue(
            all(r["delivered_at"] is None for r in self.rows("auth_audit_outbox"))
        )
        count = publish_pending(store=self.store, sink=sink)
        self.assertEqual(len(sink.records), count)
        self.assertEqual(publish_pending(store=self.store, sink=sink), 0)

    def test_existing_postgres_audit_sink_deduplicates_after_lost_ack(self):
        from apps.api.security_audit import PostgresAuditSink
        from apps.api.authentication.audit_outbox import publish_pending

        self.login()
        audit_dsn = os.environ.get("CISSTAT_AUTH_AUDIT_TEST_DSN") or DSN
        separate = audit_dsn != DSN
        if separate:
            with self.pg.connect(audit_dsn, autocommit=True) as conn:
                conn.execute(
                    self.sql.SQL("CREATE SCHEMA {}").format(
                        self.sql.Identifier(self.schema)
                    )
                )

            def clean_audit():
                with self.pg.connect(audit_dsn, autocommit=True) as conn:
                    conn.execute(
                        self.sql.SQL("DROP SCHEMA {} CASCADE").format(
                            self.sql.Identifier(self.schema)
                        )
                    )

            self.addCleanup(clean_audit)

        def connect():
            return self.pg.connect(
                audit_dsn, options="-c search_path=" + self.schema + ",pg_catalog"
            )

        with connect() as conn:
            conn.execute(
                (
                    ROOT / "apps/api/migrations/0009_doclog3_telemetry_audit.sql"
                ).read_text(encoding="utf-8"),
                prepare=False,
            )
        sink = PostgresAuditSink(audit_dsn)
        sink._schema_ready = True
        sink._connect = connect
        original = sink.append

        def lost_ack(record):
            original(record)
            raise RuntimeError("ack lost")

        with patch.object(sink, "append", side_effect=lost_ack):
            self.error(lambda: publish_pending(store=self.store, sink=sink), 503)
        count = publish_pending(store=self.store, sink=sink)
        with connect() as conn:
            actual = conn.execute(
                "SELECT count(*) FROM security_audit_records"
            ).fetchone()[0]
        self.assertEqual(actual, count)

    def test_concurrent_touch_logout_cannot_resurrect_sid(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        a = self.login()
        barrier = Barrier(2)

        def touch():
            barrier.wait(timeout=5)
            try:
                self.service.verify(a.token)
            except HTTPException as e:
                self.assertEqual(e.status_code, 401)

        def logout():
            barrier.wait(timeout=5)
            self.service.logout(a.token)

        with ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(touch)
            two = pool.submit(logout)
            one.result(timeout=20)
            two.result(timeout=20)
        self.error(lambda: self.service.verify(a.token), 401)

    def test_connection_outage_is_safe_503(self):
        a = self.login()
        broken = SessionService(
            store=PostgresAccessStore("malformed AUTH04_SECRET_DSN")
        )
        self.error(lambda: broken.verify(a.token), 503)

    def test_session_security_fields_cannot_be_rebound_or_unrevoked(self):
        from apps.api.authentication.errors import RepositoryConflict

        a = self.login()
        self.service.logout(a.token)
        for sql in (
            "UPDATE auth_sessions SET revoked_at=NULL",
            "UPDATE auth_sessions SET absolute_expires_at=absolute_expires_at+interval '1 day'",
        ):
            with self.assertRaises(RepositoryConflict):
                with self.store.transaction() as tx:
                    tx.connection.execute(sql)


@unittest.skipUnless(DSN, "Mandatory runner requires CISSTAT_AUTH_TEST_DSN")
class SessionHTTPTests(unittest.TestCase):
    cleanup = SessionSQLTests.cleanup

    # Reuse setup only; filter inherited SQL methods in the mandatory runner.
    def setUp(self):
        SessionSQLTests.setUp(self)
        self.env = patch.dict(
            os.environ,
            {
                "CISSTAT_AUTH_ALLOWED_ORIGINS": ORIGIN,
                "CISSTAT_AUTH_CSRF_KEY": "auth04-test-only-key-" + "z" * 32,
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.app = FastAPI()
        self.app.state.auth_session_service = self.service
        self.app.state.auth_access_store = self.store
        self.app.include_router(router, prefix="/v1/auth")
        self.client = TestClient(self.app, base_url=ORIGIN)

    def headers(self):
        r = self.client.get("/v1/auth/csrf", headers={"Origin": ORIGIN})
        self.assertEqual(r.status_code, 200, r.text)
        return {
            "Origin": ORIGIN,
            "X-CSRF-Token": r.json()["csrf_token"],
            "Sec-Fetch-Site": "same-origin",
        }

    def http_login(self):
        self.client.cookies.set(
            "cisstat_session_id",
            "old-research-pointer",
            domain="standalone.example",
            path="/",
        )
        r = self.client.post(
            "/v1/auth/login",
            headers=self.headers(),
            json={
                "login": "alice04",
                "password": PASS,
                "account_id": str(self.account.account_id),
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r

    def test_http_cookie_no_secret_body_and_research_pointer_removed(self):
        r = self.http_login()
        cookies = r.headers.get_list("set-cookie")
        auth = next(c for c in cookies if c.startswith("__Host-cisstat_auth="))
        for flag in ("Secure", "HttpOnly", "Path=/", "SameSite=lax"):
            self.assertIn(flag, auth)
        self.assertNotIn("Domain=", auth)
        self.assertNotIn(PASS, r.text)
        self.assertNotIn(self.client.cookies.get("__Host-cisstat_auth"), r.text)
        self.assertIn("no-store", r.headers["cache-control"])
        self.assertIsNone(self.client.cookies.get("cisstat_session_id"))

    def test_http_me_then_logout_and_invalid_replay(self):
        self.http_login()
        token = self.client.cookies.get("__Host-cisstat_auth")
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 200)
        r = self.client.post("/v1/auth/logout", headers=self.headers())
        self.assertEqual(r.status_code, 204, r.text)
        self.client.cookies.set("__Host-cisstat_auth", token)
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)

    def test_http_large_body_is_bounded(self):
        r = self.client.post(
            "/v1/auth/login", headers=self.headers(), json={"password": "x" * 20000}
        )
        self.assertEqual(r.status_code, 413, r.text)
        self.assertNotIn("xxxxx", r.text)

    def test_http_auth_db_down_never_uses_research_cookie(self):
        from fastapi import Request
        from apps.api.identity import resolve_request_subject

        @self.app.get("/db-outage")
        def subject(request: Request):
            return {"id": resolve_request_subject(request).subject_id}

        self.http_login()
        self.client.cookies.set("cisstat_session_id", "legacy")
        self.app.state.auth_session_service = SessionService(
            store=PostgresAccessStore(
                "postgresql://AUTH04_USER:AUTH04_SECRET@127.0.0.1:1/missing"
            )
        )
        r = self.client.get("/db-outage")
        self.assertEqual(r.status_code, 503, r.text)
        self.assertNotIn("AUTH04_SECRET", r.text)

    def test_http_csrf_protects_login_and_cookie_mutations(self):
        bad = self.client.post(
            "/v1/auth/login",
            json={
                "login": "alice04",
                "password": PASS,
                "account_id": str(self.account.account_id),
            },
        )
        self.assertEqual(bad.status_code, 403)
        self.http_login()
        self.assertEqual(self.client.post("/v1/auth/logout").status_code, 403)
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 200)

    def test_http_origin_binding_and_cross_site_reads(self):
        self.http_login()
        r = self.client.get("/v1/auth/me", headers={"Origin": "https://evil.example"})
        self.assertIn(r.status_code, (401, 403))
        r = self.client.get("/v1/auth/me", headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(r.status_code, 403)

    def test_http_unsafe_context_consumer_requires_csrf(self):
        from fastapi import Request
        from apps.api.identity import resolve_request_subject

        @self.app.post("/consumer")
        def consume(request: Request):
            return {"subject_id": resolve_request_subject(request).subject_id}

        self.http_login()
        self.assertEqual(self.client.post("/consumer").status_code, 403)
        self.assertEqual(
            self.client.post("/consumer", headers=self.headers()).status_code, 200
        )

    def test_http_validation_never_echoes_password_inputs(self):
        r = self.client.post(
            "/v1/auth/login",
            headers=self.headers(),
            json={
                "login": "alice04",
                "password": {"secret": PASS},
                "account_id": "invalid",
            },
        )
        self.assertEqual(r.status_code, 422, r.text)
        self.assertNotIn(PASS, r.text)

    def test_http_all_revoke_drops_cookie_and_next_request_denied(self):
        self.http_login()
        r = self.client.post("/v1/auth/sessions/revoke-all", headers=self.headers())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)

    def test_http_verifier_integrates_with_subject_context(self):
        from apps.api.identity import resolve_request_subject
        from fastapi import Request

        @self.app.get("/subject")
        def subject(request: Request):
            s = resolve_request_subject(request)
            return {"subject_id": s.subject_id, "tenant_id": s.tenant_id, "via": s.via}

        self.http_login()
        r = self.client.get("/subject")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["subject_id"], str(self.owner.subject_id))
        self.assertEqual(r.json()["via"], "auth_session")


if __name__ == "__main__":
    unittest.main()
