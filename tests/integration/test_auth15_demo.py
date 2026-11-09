"""Native PostgreSQL campaign/session/isolation/atomicity acceptance; no fake SQL."""

import base64
import json
import os
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from apps.api.authentication.storage import PostgresAccessStore
from apps.api.authentication.demo import DemoService, CampaignPolicy
from apps.api.authentication.demo_migrations import apply_migration, check_schema
from apps.api.authentication.sessions import SessionService
from apps.api.authentication.context import resolve_verified_context
from apps.api.authentication.mfa import MfaService
from apps.api.authentication.mfa_crypto import totp
from apps.api.billing.coordinator import ReservationCoordinator

ORIGIN = "https://standalone.example"
PASS = "AUTH15 disposable personal passphrase!"
DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")
WASM = os.environ.get("CISSTAT_AUTH15_WASM")


@unittest.skipUnless(DSN or WASM, "disposable PostgreSQL DSN mandatory")
class CampaignSQLTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        if WASM:
            from scripts.auth15.wasm_check import WasmStore

            self.store = WasmStore(WASM)
            self.addCleanup(self.store.close)
        else:
            import psycopg
            from psycopg import sql

            schema = "auth15_" + uuid4().hex
            with psycopg.connect(DSN, autocommit=True) as c:
                c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            self.store = PostgresAccessStore(DSN, schema=schema)

            def cleanup():
                with psycopg.connect(DSN, autocommit=True) as c:
                    c.execute(
                        sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                    )

            self.addCleanup(cleanup)
        with self.store.transaction() as tx:
            apply_migration(tx.connection)
        self.env = patch.dict(
            os.environ,
            {
                "CISSTAT_AUTH_MFA_KEYS": json.dumps(
                    {"test": base64.b64encode(b"k" * 32).decode()}
                ),
                "CISSTAT_AUTH_MFA_ACTIVE_KEY": "test",
                "CISSTAT_AUTH_ALLOWED_ORIGINS": ORIGIN,
                "CISSTAT_AUTH_CSRF_KEY": "auth15-disposable-csrf-key-" + "x" * 32,
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.demo = DemoService(self.store, clock=lambda: self.now)
        self.sessions = SessionService(self.store, clock=lambda: self.now)
        mfa = MfaService(self.store, clock=lambda: self.now)
        admin = mfa.bootstrap(mfa.prepare_bootstrap(), "admin15", PASS)
        challenge = self.sessions.login(
            "admin15", PASS, admin["account_id"], origin=ORIGIN
        )
        enroll = mfa.begin_enrollment(challenge.token, origin=ORIGIN)
        self.now += timedelta(seconds=30)
        self.token = mfa.complete(
            enroll.challenge.token,
            totp(base64.b32decode(enroll.secret), int(self.now.timestamp()) // 30),
            origin=ORIGIN,
        ).session.token
        self.policy = CampaignPolicy(
            starts_at=self.now - timedelta(minutes=1),
            ends_at=self.now + timedelta(hours=2),
            grant_minutes=60,
            max_grants=4,
            campaign_cu=1000,
            participant_cu=100,
            campaign_concurrency=2,
            participant_concurrency=1,
            campaign_analyses=8,
            participant_analyses=2,
            max_rows=1000,
            allowed_origins=[ORIGIN],
        )
        self.campaign = self.demo.create(
            self.token, ORIGIN, "forum15", self.policy, "disposable test"
        )
        self.secret = self.campaign["secret"]
        self.cmd("activate")

    def cmd(self, command, **kw):
        result = self.demo.command(
            self.token,
            ORIGIN,
            self.campaign["campaign_id"],
            command,
            kw.pop("version", self.campaign["policy_version"]),
            "test reason",
            **kw,
        )
        self.campaign = result
        return result

    def enter(self, marker=None):
        marker = marker or "d1_" + secrets.token_urlsafe(32)
        return self.demo.enter("forum15", self.secret, marker, ORIGIN), marker

    def rows(self, table):
        with self.store.transaction(readonly=True) as tx:
            return tx.connection.execute("SELECT * FROM " + table).fetchall()

    def error(self, fn, status):
        with self.assertRaises(HTTPException) as caught:
            fn()
        self.assertEqual(caught.exception.status_code, status, caught.exception.detail)
        return caught.exception

    def test_migration_retry_and_guards(self):
        with self.store.transaction() as tx:
            self.assertFalse(apply_migration(tx.connection))
            check_schema(tx.connection)
        a, _ = self.enter()
        grant = self.rows("auth_demo_grants")[0]

        def tamper():
            with self.store.transaction() as tx:
                tx.connection.execute(
                    "UPDATE auth_demo_grants SET expires_at=expires_at+interval '1 hour' WHERE grant_id=%s",
                    (grant["grant_id"],),
                )

        with self.assertRaises(Exception):
            tamper()
        self.assertEqual(
            self.rows("auth_demo_grants")[0]["expires_at"], grant["expires_at"]
        )

    def test_shared_pair_has_distinct_subject_account_tenant_grant(self):
        a, _ = self.enter()
        b, _ = self.enter()
        ea = self.sessions.verify(a.token)
        eb = self.sessions.verify(b.token)
        ca = resolve_verified_context(ea, store=self.store)
        cb = resolve_verified_context(eb, store=self.store)
        self.assertNotEqual(ca.subject_id, cb.subject_id)
        self.assertNotEqual(ca.account_id, cb.account_id)
        self.assertNotEqual(ca.tenant_id, cb.tenant_id)
        self.assertNotEqual(ca.demo_grant_id, cb.demo_grant_id)
        self.assertFalse(ca.platform_permissions)
        self.assertEqual(ca.role.value, "external_user")
        self.assertEqual(
            len(self.rows("auth_password_credentials")), 1
        )  # Only named admin, no copied shared password.
        self.assertEqual(
            {r["kind"] for r in self.rows("auth_budget_scopes")},
            {"sponsor", "campaign", "account", "grant"},
        )
        self.assertEqual(
            sum(r["kind"] == "sponsor" for r in self.rows("auth_budget_scopes")), 1
        )
        self.error(lambda: self.demo.list(a.token, ORIGIN), 403)

    def test_resume_keeps_expiry_usage_and_revokes_previous_session(self):
        a, marker = self.enter()
        g = self.rows("auth_demo_grants")[0]
        self.now += timedelta(minutes=2)
        b, _ = self.enter(marker)
        self.assertNotEqual(a.token, b.token)
        self.assertEqual(len(self.rows("auth_demo_grants")), 1)
        self.assertEqual(
            self.rows("auth_demo_grants")[0]["expires_at"], g["expires_at"]
        )
        self.error(lambda: self.sessions.verify(a.token), 401)
        self.sessions.logout(b.token)
        c = self.demo.resume(marker, ORIGIN)
        self.sessions.verify(c.token)
        self.assertEqual(self.rows("auth_demo_campaigns")[0]["issued_grants"], 1)

    def test_expiry_cannot_issue_new_grant_for_known_marker(self):
        _, marker = self.enter()
        self.now += timedelta(minutes=60)
        self.error(lambda: self.demo.enter("forum15", self.secret, marker, ORIGIN), 403)
        self.error(lambda: self.demo.resume(marker, ORIGIN), 403)
        self.assertEqual(len(self.rows("auth_demo_grants")), 1)

    def test_pause_resume_and_revoke_close_context_and_ledger_authority(self):
        a, _ = self.enter()
        ctx = resolve_verified_context(self.sessions.verify(a.token), store=self.store)
        self.cmd("pause")
        self.error(lambda: self.sessions.verify(a.token), 403)

        def authority():
            with self.store.transaction() as tx:
                ReservationCoordinator(self.store)._authority(tx.connection, ctx)

        self.error(authority, 403)
        self.cmd("resume")
        self.sessions.verify(a.token)
        self.cmd("revoke")
        self.error(lambda: self.sessions.verify(a.token), 403)

    def test_rotation_secret_once_old_password_denied_existing_grant_retained(self):
        a, marker = self.enter()
        result = self.cmd("rotate-credential")
        self.error(lambda: self.sessions.verify(a.token), 401)
        self.error(lambda: self.demo.enter("forum15", self.secret, marker, ORIGIN), 401)
        self.secret = result["secret"]
        self.enter(marker)
        self.assertEqual(len(self.rows("auth_demo_grants")), 1)
        self.assertNotIn("secret", str(self.demo.list(self.token, ORIGIN)))
        all_rows = str(
            self.rows("auth_demo_campaigns")
            + self.rows("auth_demo_grants")
            + self.rows("auth_sessions")
            + self.rows("auth_audit_outbox")
        )
        self.assertNotIn(self.secret, all_rows)
        self.assertNotIn(marker, all_rows)
        self.assertNotIn(a.token, all_rows)

    def test_cas_and_stale_mfa(self):
        self.error(lambda: self.cmd("pause", version=1), 409)
        self.now += timedelta(minutes=6)
        self.error(lambda: self.cmd("pause"), 403)
        self.assertEqual(self.rows("auth_demo_campaigns")[0]["status"], "active")

    def test_last_grant_bounded_and_retry_does_not_increment(self):
        p = self.policy.model_copy(update={"max_grants": 1})
        self.cmd("update", policy=p)
        a, marker = self.enter()
        self.enter(marker)
        self.error(lambda: self.enter(), 429)
        self.assertEqual(self.rows("auth_demo_campaigns")[0]["issued_grants"], 1)

    @unittest.skipIf(bool(WASM), "WASM is single connection; native locking required")
    def test_concurrent_last_grant_and_same_marker(self):
        self.cmd("update", policy=self.policy.model_copy(update={"max_grants": 1}))

        def attempt(_):
            try:
                return self.enter()[0]
            except HTTPException as e:
                return e.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(attempt, range(2)))
        self.assertEqual(sum(x == 429 for x in result), 1)
        self.assertEqual(len(self.rows("auth_demo_grants")), 1)

    def test_policy_clamps_demo_caps_and_own_upload(self):
        a, _ = self.enter()
        e = self.sessions.verify(a.token)
        ctx = resolve_verified_context(e, store=self.store)
        self.assertFalse(ctx.account_capabilities.can_upload_own_data)
        self.assertEqual(ctx.account_capabilities.max_dataset_rows, 1000)
        self.assertFalse(ctx.account_capabilities.can_use_api)
        self.cmd(
            "update",
            policy=self.policy.model_copy(
                update={"max_rows": 500, "allow_upload": True}
            ),
        )
        ctx = resolve_verified_context(e, store=self.store)
        self.assertTrue(ctx.account_capabilities.can_upload_own_data)
        self.assertEqual(ctx.account_capabilities.max_dataset_rows, 500)
        with self.store.transaction() as tx:
            account = tx.accounts.get(e.account_id)
            tx.accounts.update(
                account.account_id,
                expected_version=account.entitlement_version,
                plan="professional",
            )
        ctx = resolve_verified_context(e, store=self.store)
        self.assertFalse(ctx.account_capabilities.can_use_api)
        self.assertFalse(ctx.account_capabilities.can_tune_models)
        from apps.api.authentication.api_keys import APIKeyService

        def personal_key_access():
            with self.store.transaction() as tx:
                APIKeyService(self.store, clock=lambda: self.now)._session(
                    tx.connection, a.token, ORIGIN
                )

        self.error(personal_key_access, 403)

    def test_audit_fault_rolls_back_grant_and_account_and_counter(self):
        count = len(self.rows("auth_accounts"))
        before = len(self.rows("auth_sessions"))
        with patch.object(
            self.demo,
            "_audit_demo",
            side_effect=RuntimeError("mandatory audit unavailable"),
        ):
            self.error(lambda: self.enter(), 503)
        self.assertEqual(len(self.rows("auth_accounts")), count)
        self.assertEqual(len(self.rows("auth_sessions")), before)
        self.assertEqual(self.rows("auth_demo_campaigns")[0]["issued_grants"], 0)

    def test_audit_fault_rolls_back_pause_and_budgets(self):
        with patch.object(
            self.demo, "_audit_demo", side_effect=RuntimeError("audit unavailable")
        ):
            self.error(lambda: self.cmd("pause"), 503)
        self.assertEqual(self.rows("auth_demo_campaigns")[0]["status"], "active")
        self.assertTrue(
            all(r["status"] == "active" for r in self.rows("auth_budget_scopes"))
        )

    def test_wrong_origin_and_secret_and_invalid_resume_do_not_create(self):
        with patch.object(
            self.demo.codec, "hash", side_effect=AssertionError("unauthorized hash")
        ) as hashing:
            self.error(
                lambda: self.demo.create(
                    None, ORIGIN, "forged", self.policy, "forged caller"
                ),
                401,
            )
            hashing.assert_not_called()
        self.error(
            lambda: self.demo.enter(
                "forum15", "bad", "d1_" + secrets.token_urlsafe(32), ORIGIN
            ),
            401,
        )
        self.error(
            lambda: self.demo.enter(
                "forum15",
                self.secret,
                "d1_" + secrets.token_urlsafe(32),
                "https://evil.example",
            ),
            403,
        )
        self.error(
            lambda: self.demo.resume("d1_" + secrets.token_urlsafe(32), ORIGIN), 401
        )
        self.assertFalse(self.rows("auth_demo_grants"))

    def test_http_cookie_csrf_and_no_input_echo(self):
        from apps.api.routers.demo import router
        from apps.api.routers.authentication import router as auth_router

        app = FastAPI()
        app.state.auth_access_store = self.store
        app.include_router(router, prefix="/v1")
        app.include_router(auth_router, prefix="/v1/auth")
        with TestClient(app, base_url=ORIGIN) as client:
            client.cookies.set(
                "__Host-cisstat_auth", self.token, domain="standalone.example", path="/"
            )
            self.assertEqual(client.get("/v1/admin/demo-campaigns").status_code, 200)
            client.cookies.clear()
            r = client.post(
                "/v1/auth/demo/enter",
                json={"login": "forum15", "password": self.secret},
            )
            self.assertEqual(r.status_code, 403)

            def post(path, body=None):
                proof = client.get(
                    "/v1/auth/csrf", headers={"Origin": ORIGIN, "X-CSRF-Request": "1"}
                ).json()["csrf_token"]
                return client.post(
                    "/v1/" + path,
                    json=body,
                    headers={"Origin": ORIGIN, "X-CSRF-Token": proof},
                )

            self.assertEqual(post("auth/demo/prepare").status_code, 200)
            client.cookies.set(
                "cisstat_session_id",
                "foreign-research-pointer",
                domain="standalone.example",
                path="/",
            )
            r = post("auth/demo/enter", {"login": "forum15", "password": self.secret})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertIn("HttpOnly", r.headers["set-cookie"])
            self.assertIn("Secure", r.headers["set-cookie"])
            self.assertNotIn("cisstat_session_id", client.cookies)
            r = client.get("/v1/auth/demo/me", headers={"Origin": ORIGIN})
            self.assertEqual(r.status_code, 200, r.text)
            r = post(
                "auth/demo/enter",
                {"login": "forum15", "password": {"leak": "secret-sentinel"}},
            )
            self.assertEqual(r.status_code, 422)
            self.assertNotIn("secret-sentinel", r.text)

    @unittest.skipIf(bool(WASM), "native concurrent connections required")
    def test_concurrent_same_marker_has_one_grant_and_one_active_session(self):
        marker = "d1_" + secrets.token_urlsafe(32)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: self.enter(marker), range(2)))
        self.assertEqual(len(self.rows("auth_demo_grants")), 1)
        self.assertEqual(
            sum(
                r["demo_grant_id"] is not None and r["revoked_at"] is None
                for r in self.rows("auth_sessions")
            ),
            1,
        )

    def test_common_ledger_uses_single_sponsor_and_participant_limits(self):
        from apps.api.billing.contract import Admission, Cost

        # Ledger uses database clock; align this fixture before issuing the grant.
        self.now = datetime.now(timezone.utc)

        a, _ = self.enter()
        ctx = resolve_verified_context(self.sessions.verify(a.token), store=self.store)
        ledger = ReservationCoordinator(self.store)
        deadline = datetime.now(timezone.utc) + timedelta(minutes=1)

        def admit(key):
            return ledger.reserve(
                ctx,
                Admission(
                    entry_id="api:POST:/v1/session/demo",
                    resource_kind="run",
                    resource_id="RUN-AUTH15-" + key,
                    analysis_run_id="RUN-AUTH15-" + key,
                    idempotency_key=key,
                    payload={},
                    cost=Cost(micro_cu=1, version="native-synthetic/1"),
                    slots=1,
                    deadline=deadline,
                ),
            )

        first = admit("one")
        self.assertEqual(admit("one").reservation_id, first.reservation_id)
        self.error(lambda: admit("two"), 429)
        allocations = self.rows("auth_reservation_allocations")
        self.assertEqual(sum(r["metric"] == "cu" for r in allocations), 4)
        self.assertEqual(sum(r["metric"] == "analysis" for r in allocations), 4)

    def test_service_db_failure_is_safe_503(self):
        with patch.object(
            self.store,
            "transaction",
            side_effect=RuntimeError("private database error"),
        ):
            e = self.error(lambda: self.demo.list(self.token, ORIGIN), 503)
        self.assertNotIn("private database", str(e.detail))

    @unittest.skipIf(bool(WASM), "native scientific stores required")
    def test_real_demo_upload_foreign_run_document_and_pointer_are_denied(self):
        import tempfile
        from pathlib import Path
        from psycopg.conninfo import make_conninfo
        from apps.api import research_runs, session_store
        from apps.api.research_runs import run_migrations
        from apps.api.routers import (
            authentication,
            demo,
            session,
            progress,
            documentation,
        )
        from apps.api.trace_hook import TraceHookMiddleware

        dsn = make_conninfo(DSN, options="-csearch_path=" + self.store.schema)
        self.store._dsn = dsn  # AUTH-16 bound publication requires exact authority DSN parity.
        from apps.api.authentication.demo_lifecycle_migrations import apply_migration as apply_lifecycle
        with self.store.transaction() as tx: apply_lifecycle(tx.connection)
        import psycopg

        with psycopg.connect(dsn) as c:
            run_migrations(c)
        with (
            tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[3]) as tmp,
            patch.dict(
                os.environ,
                {
                    "DATABASE_URL": dsn,
                    "CISSTAT_STORAGE_MODE": "required",
                    "CISSTAT_SESSION_BACKEND": "postgres",
                    "CISSTAT_IDENTITY_MODE": "session_scoped",
                    "CISSTAT_DATA_DIR": tmp,
                },
            ),
        ):
            resets = (
                research_runs.reset_research_run_store_for_testing,
                session_store.reset_session_store_for_testing,
                research_runs.reset_dataset_file_store_for_testing,
            )
            for reset in resets:
                reset()
            try:
                app = FastAPI()
                app.state.auth_access_store = self.store
                for name, module in [
                    ("auth", authentication),
                    ("session", session),
                    ("progress", progress),
                    ("documentation", documentation),
                ]:
                    app.include_router(module.router, prefix="/v1/" + name)
                app.include_router(demo.router, prefix="/v1")
                app.add_middleware(TraceHookMiddleware)

                def post(client, path, body=None):
                    proof = client.get(
                        "/v1/auth/csrf", headers={"Origin": ORIGIN}
                    ).json()["csrf_token"]
                    return client.post(
                        path,
                        json=body or {},
                        headers={"Origin": ORIGIN, "X-CSRF-Token": proof},
                    )

                with (
                    TestClient(app, base_url=ORIGIN) as a,
                    TestClient(app, base_url=ORIGIN) as b,
                ):
                    for client in (a, b):
                        self.assertEqual(
                            post(client, "/v1/auth/demo/prepare").status_code, 200
                        )
                        r = post(
                            client,
                            "/v1/auth/demo/enter",
                            {"login": "forum15", "password": self.secret},
                        )
                        self.assertEqual(r.status_code, 200, r.text)
                        r = post(client, "/v1/session/demo")
                        self.assertEqual(r.status_code, 200, r.text)
                    sa = session_store.get_session_store().get(
                        a.cookies.get("cisstat_session_id")
                    )
                    sb = session_store.get_session_store().get(
                        b.cookies.get("cisstat_session_id")
                    )
                    self.assertNotEqual(sa.run_id, sb.run_id)
                    self.assertNotEqual(sa.owner_account_id, sb.owner_account_id)
                    self.assertEqual(
                        a.get("/v1/progress/runs/" + sa.run_id).status_code, 200
                    )
                    self.assertEqual(
                        b.get("/v1/progress/runs/" + sa.run_id).status_code, 404
                    )
                    self.assertEqual(
                        b.get(
                            "/v1/documentation/runs/" + sa.run_id + "/documents"
                        ).status_code,
                        404,
                    )
                    b.cookies.set(
                        "cisstat_session_id",
                        sa.session_id,
                        domain="standalone.example",
                        path="/",
                    )
                    self.assertEqual(b.get("/v1/session/dataset").status_code, 404)
                    self.cmd("pause")
                    self.assertEqual(
                        a.get("/v1/progress/runs/" + sa.run_id).status_code, 403
                    )
            finally:
                for reset in resets:
                    reset()

    def test_explicit_device_leave_revokes_only_own_grant_without_refund(self):
        a, marker = self.enter()
        b, other_marker = self.enter()
        self.demo.leave(marker, old_token=a.token)
        self.error(lambda: self.sessions.verify(a.token), 403)
        self.error(lambda: self.demo.resume(marker, ORIGIN), 403)
        self.sessions.verify(b.token)
        self.assertEqual(self.rows("auth_demo_campaigns")[0]["issued_grants"], 2)
        gid = next(
            g["grant_id"]
            for g in self.rows("auth_demo_grants")
            if g["status"] == "revoked"
        )
        self.assertEqual(
            next(
                scope["status"]
                for scope in self.rows("auth_budget_scopes")
                if scope["scope_id"] == gid
            ),
            "closed",
        )
