"""AUTH-10 real PostgreSQL + real HTTP credential lifecycle and negative oracles."""

import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient

from apps.api.accounts.lifecycle import AccountChange, AccountLifecycle
from apps.api.authentication.api_key_contract import (
    IssueKeyBody,
    RotateKeyBody,
    VersionBody,
)
from apps.api.authentication.api_key_migrations import apply_migration
from apps.api.authentication.api_keys import APIKeyService, secret_digest
from tests.integration import test_auth09_objects as previous

ORIGIN = previous.ORIGIN
DSN = os.environ.get("CISSTAT_AUTH_TEST_DSN")


@unittest.skipUnless(DSN, "Mandatory AUTH-10 runner requires disposable PostgreSQL")
class KeySQLTests(unittest.TestCase):
    cleanup = previous.OwnershipSQLTests.cleanup
    client = previous.OwnershipSQLTests.client
    post = previous.OwnershipSQLTests.post

    def setUp(self):
        previous.OwnershipSQLTests.setUp(self)
        with self.access.transaction() as tx:
            apply_migration(tx.connection)
        self.keys = APIKeyService(self.access)
        self.app.state.auth_api_key_service = self.keys
        from apps.api.routers import api_keys, public, upload_db

        self.app.include_router(api_keys.router, prefix="/v1/api-keys")
        self.app.include_router(public.router, prefix="/v1/public")
        self.app.include_router(upload_db.public_router, prefix="/v1/public/upload/db")
        self.owner = self.client()
        self.token = self.owner.cookies.get("__Host-cisstat_auth")

    def body(self, scopes=None):
        return IssueKeyBody(
            label="native test", scopes=scopes or ["api.read"], expires_in_days=7
        )

    def issue(self, client=None, scopes=None):
        r = self.post(
            client or self.owner, "/v1/api-keys", self.body(scopes).model_dump()
        )
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def api(self, key):
        c = TestClient(self.app, base_url=ORIGIN)
        c.headers["X-API-Key"] = key
        return c

    def error(self, fn, status, code=None):
        with self.assertRaises(HTTPException) as e:
            fn()
        self.assertEqual(e.exception.status_code, status, e.exception.detail)
        if code:
            self.assertEqual(e.exception.detail["code"], code)
        return e.exception

    def rows(self, table):
        with self.access.transaction(readonly=True) as tx:
            return tx.connection.execute("SELECT * FROM " + table).fetchall()

    def current_account(self):
        with self.access.transaction(readonly=True) as tx:
            return tx.accounts.get(self.account.account_id)

    def change(self, **patches):
        return AccountLifecycle(self.access).change(
            self.account.account_id,
            expected_version=self.current_account().entitlement_version,
            change=AccountChange(**patches),
            reason="AUTH10 test",
        )

    def fault(self):
        with self.access.transaction() as tx:
            tx.connection.execute("""CREATE FUNCTION api10_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                IF NEW.payload->>'action'='auth_api_key_changed' THEN RAISE EXCEPTION 'intent fault' USING ERRCODE='23514'; END IF;
                RETURN NEW; END $$""")
            tx.connection.execute(
                "CREATE TRIGGER api10_fault BEFORE INSERT ON auth_audit_outbox FOR EACH ROW EXECUTE FUNCTION api10_fault()"
            )

    def test_hash_only_secret_once_safe_metadata(self):
        result = self.issue()
        value = result["secret"]
        record = self.rows("auth_api_keys")[0]
        self.assertEqual(record["token_hash"], secret_digest(value))
        self.assertNotIn(
            value, str(self.rows("auth_api_keys") + self.rows("auth_audit_outbox"))
        )
        listing = self.owner.get("/v1/api-keys")
        self.assertEqual(listing.status_code, 200, listing.text)
        self.assertNotIn("secret", listing.text)
        self.assertNotIn("token_hash", listing.text)
        self.assertNotIn(value, listing.text)
        self.assertEqual(listing.headers["cache-control"], "private, no-store")

    def test_programmatic_scope_and_current_subject(self):
        result = self.issue()
        c = self.api(result["secret"])
        self.assertEqual(c.get("/v1/public/rules/templates").status_code, 200)
        self.assertEqual(c.get("/v1/public/rules/load/default").status_code, 200)
        self.assertEqual(
            c.post("/v1/public/passport", json={"series": []}).status_code, 403
        )
        e = self.keys.verify(result["secret"])
        self.assertEqual(e.subject_id, str(self.person.subject_id))
        self.assertEqual(e.account_id, str(self.account.account_id))
        self.assertEqual(e.credential_id, result["key"]["key_id"])

    def test_rotation_stable_identity_expiry_and_old_invalid(self):
        a = self.issue(scopes=["api.read", "api.compute"])
        r = self.post(
            self.owner,
            f"/v1/api-keys/{a['key']['key_id']}/rotate",
            {"expected_version": 1, "scopes": ["api.read"]},
        )
        self.assertEqual(r.status_code, 200, r.text)
        b = r.json()
        for field in ("subject_id", "account_id", "family_id", "expires_at"):
            self.assertEqual(a["key"][field], b["key"][field])
        self.assertNotEqual(a["secret"], b["secret"])
        self.assertNotEqual(a["key"]["key_id"], b["key"]["key_id"])
        self.error(lambda: self.keys.verify(a["secret"]), 401)
        self.assertEqual(
            self.api(b["secret"]).get("/v1/public/rules/templates").status_code, 200
        )

    def test_rotation_cannot_widen_scope(self):
        a = self.issue()
        r = self.post(
            self.owner,
            f"/v1/api-keys/{a['key']['key_id']}/rotate",
            {"expected_version": 1, "scopes": ["api.database"]},
        )
        self.assertEqual(r.status_code, 403, r.text)
        self.assertEqual(len(self.rows("auth_api_keys")), 1)
        self.keys.verify(a["secret"])

    def test_revoke_terminal_and_no_secret_recovery(self):
        a = self.issue()
        path = f"/v1/api-keys/{a['key']['key_id']}/revoke"
        r = self.post(self.owner, path, {"expected_version": 1})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn(a["secret"], r.text)
        self.error(lambda: self.keys.verify(a["secret"]), 401)
        self.assertEqual(
            self.post(self.owner, path, {"expected_version": 1}).status_code, 409
        )
        self.assertEqual(
            self.post(self.owner, path, {"expected_version": 2}).status_code, 200
        )
        self.assertEqual(
            self.post(
                self.owner, path.replace("revoke", "rotate"), {"expected_version": 2}
            ).status_code,
            409,
        )

    def test_expiry_exact_deadline(self):
        a = self.issue()
        deadline = datetime.fromisoformat(a["key"]["expires_at"])
        self.keys.clock = lambda: deadline
        self.error(lambda: self.keys.verify(a["secret"]), 401)

    def test_plan_disabled_issue_and_rotation(self):
        a = self.issue()
        self.change(plan="demo")
        self.error(
            lambda: self.keys.issue(self.token, self.body(), origin=ORIGIN),
            403,
            "api_not_allowed",
        )
        self.error(
            lambda: self.keys.rotate(
                self.token,
                a["key"]["key_id"],
                RotateKeyBody(expected_version=1),
                origin=ORIGIN,
            ),
            403,
        )
        self.assertEqual(self.owner.get("/v1/api-keys").status_code, 200)
        self.change(plan="starter")
        self.error(lambda: self.keys.verify(a["secret"]), 401)

    def test_runtime_capability_reloaded_without_key_cache(self):
        from apps.api.plans import PLAN_DEFINITIONS, PlanName

        a = self.issue()
        caps = PLAN_DEFINITIONS[PlanName.PROFESSIONAL].model_copy(
            update={"can_use_api": False}
        )
        with patch.dict(PLAN_DEFINITIONS, {PlanName.PROFESSIONAL: caps}):
            r = self.api(a["secret"]).get("/v1/public/rules/templates")
            self.assertEqual(r.status_code, 403, r.text)

    def test_membership_revoke_restore_does_not_revive_key(self):
        c = self.client(member=True)
        a = self.issue(c)
        for status in ("revoked", "active"):
            AccountLifecycle(self.access).membership(
                self.account.account_id,
                self.member.subject_id,
                expected_version=self.current_account().entitlement_version,
                status=status,
                reason="AUTH10 membership test",
            )
        self.error(lambda: self.keys.verify(a["secret"]), 401)
        fresh = self.issue(self.client(member=True))
        self.keys.verify(fresh["secret"])

    def test_account_suspension_scoped_and_terminal(self):
        a = self.issue()
        b = self.issue(self.client(self.other))
        self.change(status="suspended")
        self.change(status="active")
        self.error(lambda: self.keys.verify(a["secret"]), 401)
        self.keys.verify(b["secret"])

    def test_identity_reactivation_does_not_revive_key(self):
        a = self.issue()
        for status in ("suspended", "active"):
            with self.access.transaction() as tx:
                u = tx.identities.get(self.person.subject_id)
                tx.identities.set_status(
                    u.subject_id, status, expected_version=u.subject_version
                )
        self.error(lambda: self.keys.verify(a["secret"]), 401)

    def test_cross_person_and_same_person_other_account_uniform404(self):
        a = self.issue()
        path = f"/v1/api-keys/{a['key']['key_id']}/revoke"
        for c in (self.client(member=True), self.client(self.other)):
            foreign = self.post(c, path, {"expected_version": 1})
            missing = self.post(
                c, f"/v1/api-keys/{uuid4()}/revoke", {"expected_version": 1}
            )
            self.assertEqual(foreign.status_code, 404, foreign.text)
            self.assertEqual(
                foreign.json()["detail"]["code"], missing.json()["detail"]["code"]
            )

    def test_cookie_mutations_csrf_origin_and_no_input_echo(self):
        self.assertEqual(
            self.owner.post("/v1/api-keys", json=self.body().model_dump()).status_code,
            403,
        )
        r = self.post(
            self.owner,
            "/v1/api-keys",
            {**self.body().model_dump(), "account_id": str(self.other.account_id)},
        )
        self.assertEqual(r.status_code, 422, r.text)
        self.assertNotIn(str(self.other.account_id), r.text)
        proof = self.owner.get("/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
            "csrf_token"
        ]
        r = self.owner.post(
            "/v1/api-keys",
            json=self.body().model_dump(),
            headers={"Origin": "https://foreign.example", "X-CSRF-Token": proof},
        )
        self.assertEqual(r.status_code, 403, r.text)

    def test_key_cannot_manage_keys_or_admin_paths(self):
        a = self.issue(scopes=["api.read", "api.write", "api.compute", "api.database"])
        c = self.api(a["secret"])
        self.assertEqual(c.get("/v1/api-keys").status_code, 401)
        self.assertEqual(c.post("/v1/session/demo", json={}).status_code, 403)
        self.assertEqual(c.patch("/v1/public/rules/update", json={}).status_code, 403)

    def test_bad_key_never_falls_back_to_valid_cookie_and_conflicting_accounts(self):
        a = self.issue()
        headers = {"X-API-Key": "csk_" + "x" * 43}
        self.assertEqual(
            self.owner.get("/v1/public/rules/templates", headers=headers).status_code,
            401,
        )
        other = self.client(self.other)
        self.assertEqual(
            other.get(
                "/v1/public/rules/templates", headers={"X-API-Key": a["secret"]}
            ).status_code,
            400,
        )
        c = self.api(a["secret"])
        self.assertEqual(
            c.get(
                "/v1/public/rules/templates",
                headers=[("X-API-Key", a["secret"]), ("X-API-Key", a["secret"])],
            ).status_code,
            400,
        )

    def test_required_env_removal_no_revocation_resurrection(self):
        a = self.issue()
        self.keys.revoke(
            self.token,
            a["key"]["key_id"],
            VersionBody(expected_version=1),
            origin=ORIGIN,
        )
        env = {
            "CISSTAT_API_KEYS": a["secret"] + ":admin:enterprise",
            "CISSTAT_API_KEY_MODE": "durable",
        }
        with patch.dict(os.environ, env):
            self.assertEqual(
                self.api(a["secret"]).get("/v1/public/rules/templates").status_code, 401
            )
        with patch.dict(
            os.environ, {"CISSTAT_API_KEYS": "legacy-secret:admin:enterprise"}
        ):
            self.assertEqual(
                self.api("legacy-secret").get("/v1/public/rules/templates").status_code,
                401,
            )

    def test_database_probe_and_load_gate_before_connector(self):
        a = self.issue()
        read = self.api(a["secret"])
        payload = {"connection": {"db_type": "sqlite", "path": "/not-opened.db"}}
        with patch("apps.api.routers.upload_db.init_db_connection") as connector:
            for tail, body in (
                ("test", payload),
                ("load", {**payload, "sql": "SELECT 1"}),
            ):
                r = read.post("/v1/public/upload/db/" + tail, json=body)
                self.assertEqual(r.status_code, 403, r.text)
            connector.assert_not_called()
        b = self.issue(scopes=["api.database"])
        with patch(
            "apps.api.routers.upload_db.init_db_connection",
            side_effect=ConnectionError("test unavailable"),
        ) as connector:
            r = self.api(b["secret"]).post("/v1/public/upload/db/test", json=payload)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertFalse(r.json()["ok"])
            connector.assert_called_once()

    def test_two_rotations_one_winner(self):
        a = self.issue()
        barrier = Barrier(2)

        def work(_):
            barrier.wait(timeout=10)
            try:
                return self.keys.rotate(
                    self.token,
                    a["key"]["key_id"],
                    RotateKeyBody(expected_version=1),
                    origin=ORIGIN,
                )
            except HTTPException as e:
                return e.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(work, [0, 1]))
        self.assertEqual(sum(r == 409 for r in results if isinstance(r, int)), 1)
        self.assertEqual(len(self.rows("auth_api_keys")), 2)
        self.error(lambda: self.keys.verify(a["secret"]), 401)

    def test_revoke_rotation_race(self):
        a = self.issue()
        barrier = Barrier(2)

        def work(rotate):
            barrier.wait(timeout=10)
            try:
                if rotate:
                    self.keys.rotate(
                        self.token,
                        a["key"]["key_id"],
                        RotateKeyBody(expected_version=1),
                        origin=ORIGIN,
                    )
                else:
                    self.keys.revoke(
                        self.token,
                        a["key"]["key_id"],
                        VersionBody(expected_version=1),
                        origin=ORIGIN,
                    )
                return 200
            except HTTPException as e:
                return e.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(work, [True, False])), [200, 409])
        self.error(lambda: self.keys.verify(a["secret"]), 401)

    def test_issue_audit_fault_atomic(self):
        self.fault()
        self.error(lambda: self.keys.issue(self.token, self.body(), origin=ORIGIN), 503)
        self.assertEqual(self.rows("auth_api_keys"), [])

    def test_rotation_audit_fault_keeps_old_key(self):
        a = self.issue()
        self.fault()
        self.error(
            lambda: self.keys.rotate(
                self.token,
                a["key"]["key_id"],
                RotateKeyBody(expected_version=1),
                origin=ORIGIN,
            ),
            503,
        )
        self.keys.verify(a["secret"])
        self.assertEqual(len(self.rows("auth_api_keys")), 1)

    def test_revoke_audit_fault_keeps_old_key(self):
        a = self.issue()
        self.fault()
        self.error(
            lambda: self.keys.revoke(
                self.token,
                a["key"]["key_id"],
                VersionBody(expected_version=1),
                origin=ORIGIN,
            ),
            503,
        )
        self.keys.verify(a["secret"])

    def test_sql_immutable_history_and_no_reactivation(self):
        from apps.api.authentication.errors import RepositoryConflict

        a = self.issue()
        key_id = a["key"]["key_id"]
        for sql in (
            "UPDATE auth_api_keys SET label='other' WHERE key_id=%s",
            "DELETE FROM auth_api_keys WHERE key_id=%s",
        ):
            with self.assertRaises(RepositoryConflict), self.access.transaction() as tx:
                tx.connection.execute(sql, (key_id,))
        self.keys.revoke(
            self.token, key_id, VersionBody(expected_version=1), origin=ORIGIN
        )
        with self.assertRaises(RepositoryConflict), self.access.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_api_keys SET revoked_at=NULL,version=version+1 WHERE key_id=%s",
                (key_id,),
            )

    def test_fresh_process_same_subject_and_revoke_persistence(self):
        a = self.issue()
        code = "import os;from apps.api.authentication.api_keys import APIKeyService;from apps.api.authentication.storage import PostgresAccessStore;s=PostgresAccessStore(os.environ['DATABASE_URL'],schema=os.environ['AUTH10_TEST_SCHEMA']);print(APIKeyService(s).verify(os.environ['AUTH10_TEST_TOKEN']).subject_id)"
        env = {
            **os.environ,
            "AUTH10_TEST_SCHEMA": self.schema,
            "AUTH10_TEST_TOKEN": a["secret"],
        }
        r = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(r.stdout.strip(), str(self.person.subject_id))
        self.assertNotIn(a["secret"], r.stdout + r.stderr)

    def test_service_key_operator_requires_existing_service_membership(self):
        with self.access.transaction() as tx:
            svc = tx.identities.create(kind="service")
            account = tx.accounts.get(self.account.account_id)
            account = tx.accounts.update(
                account.account_id,
                expected_version=account.entitlement_version,
                seats=3,
            )
            tx.accounts.add_member(
                account.account_id,
                svc.subject_id,
                expected_version=account.entitlement_version,
            )
        result = self.keys.operator_issue(
            svc.subject_id,
            self.account.account_id,
            self.body(),
            reason="Reviewed service ownership",
        )
        self.assertEqual(
            self.keys.verify(result.secret).subject_id, str(svc.subject_id)
        )
        rotated = self.keys.operator_rotate(
            svc.subject_id,
            self.account.account_id,
            result.key["key_id"],
            RotateKeyBody(expected_version=1),
            reason="Service rotation evidence",
        )
        self.assertEqual(
            self.keys.verify(rotated.secret).subject_id, str(svc.subject_id)
        )
        self.error(lambda: self.keys.verify(result.secret), 401)

        self.error(
            lambda: self.keys.operator_issue(
                self.person.subject_id,
                self.account.account_id,
                self.body(),
                reason="test",
            ),
            403,
        )

    def test_upload_ownership_survives_key_rotation(self):
        from apps.api.authentication.context import resolve_verified_context
        from apps.api.identity import authorize_run_access

        a = self.issue(scopes=["api.write"])
        c = self.api(a["secret"])
        r = c.post(
            "/v1/public/upload",
            files={
                "file": (
                    "series.csv",
                    b"date,value\n2024-01-01,1\n2024-01-02,2\n2024-01-03,3\n2024-01-04,4\n",
                    "text/csv",
                )
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        session = self.sessions.get(c.cookies.get("cisstat_session_id"))
        run = self.runs.get_run(session.run_id)
        self.assertEqual(run.owner_subject, str(self.person.subject_id))
        b = self.keys.rotate(
            self.token,
            a["key"]["key_id"],
            RotateKeyBody(expected_version=1),
            origin=ORIGIN,
        )
        ctx = resolve_verified_context(self.keys.verify(b.secret), store=self.access)
        self.assertTrue(
            authorize_run_access(
                run, ctx.as_subject(), session_id=session.session_id
            ).allowed
        )
        self.assertEqual(self.runs.get_run(run.run_id).owner_subject, run.owner_subject)

    def test_suspend_races_issue_without_live_survivor(self):
        barrier = Barrier(2)

        def work(issue):
            barrier.wait(timeout=10)
            if issue:
                try:
                    self.keys.issue(self.token, self.body(), origin=ORIGIN)
                except HTTPException as e:
                    self.assertEqual(e.status_code, 401)
            else:
                self.change(status="suspended")

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(work, [True, False]))
        self.assertTrue(
            all(row["revoked_at"] is not None for row in self.rows("auth_api_keys"))
        )

    def test_membership_revoke_races_issue_without_live_survivor(self):
        member = self.client(member=True)
        token = member.cookies.get("__Host-cisstat_auth")
        barrier = Barrier(2)

        def work(issue):
            barrier.wait(timeout=10)
            if issue:
                try:
                    self.keys.issue(token, self.body(), origin=ORIGIN)
                except HTTPException as e:
                    self.assertEqual(e.status_code, 401)
            else:
                AccountLifecycle(self.access).membership(
                    self.account.account_id,
                    self.member.subject_id,
                    expected_version=self.current_account().entitlement_version,
                    status="revoked",
                    reason="AUTH10 race",
                )

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(work, [True, False]))
        self.assertTrue(
            all(row["revoked_at"] is not None for row in self.rows("auth_api_keys"))
        )

    def test_key_count_bound(self):
        for _ in range(20):
            self.keys.issue(self.token, self.body(), origin=ORIGIN)
        self.error(
            lambda: self.keys.issue(self.token, self.body(), origin=ORIGIN),
            409,
            "api_key_limit",
        )
        self.assertEqual(len(self.rows("auth_api_keys")), 20)

    def test_recent_auth_required_while_session_is_active(self):
        from apps.api.authentication.sessions import SessionService

        now = datetime.now(UTC)
        SessionService(self.access, clock=lambda: now + timedelta(minutes=14)).verify(
            self.token, origin=ORIGIN
        )
        self.keys.clock = lambda: now + timedelta(minutes=16)
        self.keys.list(self.token, origin=ORIGIN)
        self.error(
            lambda: self.keys.issue(self.token, self.body(), origin=ORIGIN),
            403,
            "reauthentication_required",
        )

    def test_readiness_guard_drop_fail_closed(self):
        self.assertTrue(self.keys.readiness()["ok"])
        with self.access.transaction() as tx:
            tx.connection.execute("DROP TRIGGER auth10_key_guard ON auth_api_keys")
        self.error(lambda: self.keys.readiness(), 503)

    def test_migration_idempotence_and_checksum_fail_closed(self):
        from apps.api.authentication.api_key_migrations import VERSION

        with self.access.transaction() as tx:
            self.assertFalse(apply_migration(tx.connection))
            tx.connection.execute(
                "UPDATE auth_schema_versions SET checksum=%s WHERE version=%s",
                ("0" * 64, VERSION),
            )
        self.error(lambda: self.keys.readiness(), 503)
        self.error(lambda: self.keys.issue(self.token, self.body(), origin=ORIGIN), 503)
        from apps.api.authentication.errors import AuthSchemaNotReady

        with self.assertRaises(AuthSchemaNotReady), self.access.transaction() as tx:
            apply_migration(tx.connection)

    def test_account_deadline_caps_key_expiry(self):
        deadline = datetime.now(UTC) + timedelta(hours=1)
        self.change(plan_expires_at=deadline)
        # Account entitlement change doesn't revoke an otherwise active SID.
        result = self.issue()
        expires = datetime.fromisoformat(result["key"]["expires_at"])
        self.assertEqual(expires, deadline)


if __name__ == "__main__":
    unittest.main()
