"""AUTH-05 SQL authority and ASGI lifecycle; DSN is mandatory in the gate."""

import base64
import os
import unittest
from datetime import timedelta
from unittest.mock import patch

from tests.integration import test_auth04_sessions as previous

PASS, ORIGIN, DSN = previous.PASS, previous.ORIGIN, previous.DSN


@unittest.skipUnless(DSN, "Mandatory gate requires CISSTAT_AUTH_TEST_DSN")
class MfaSQLTests(unittest.TestCase):
    cleanup = previous.SessionSQLTests.cleanup
    error = previous.SessionSQLTests.error
    rows = previous.SessionSQLTests.rows

    def setUp(self):
        previous.SessionSQLTests.setUp(self)
        from apps.api.authentication.mfa import MfaService
        from apps.api.authentication.mfa_migrations import apply_migration

        with self.store.transaction() as tx:
            apply_migration(tx.connection)
        self.env = patch.dict(
            os.environ,
            {
                "CISSTAT_AUTH_MFA_KEYS": '{"test":"'
                + base64.b64encode(b"k" * 32).decode()
                + '"}',
                "CISSTAT_AUTH_MFA_ACTIVE_KEY": "test",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.mfa = MfaService(self.store, clock=lambda: self.now)
        self.bootstrap_secret = self.mfa.prepare_bootstrap()
        self.admin = self.mfa.bootstrap(self.bootstrap_secret, "named-admin", PASS)

    def login(self):
        return self.service.login(
            "named-admin", PASS, self.admin["account_id"], origin=ORIGIN
        )

    def enroll(self):
        from apps.api.authentication.mfa_crypto import totp

        initial = self.login()
        self.assertFalse(self.rows("auth_sessions"))
        enrollment = self.mfa.begin_enrollment(initial.token, origin=ORIGIN)
        self.seed = base64.b32decode(enrollment.secret)
        self.now += timedelta(seconds=30)
        result = self.mfa.complete(
            enrollment.challenge.token,
            totp(self.seed, int(self.now.timestamp()) // 30),
            origin=ORIGIN,
        )
        return result

    def next_code(self):
        from apps.api.authentication.mfa_crypto import totp

        self.now += timedelta(seconds=30)
        return totp(self.seed, int(self.now.timestamp()) // 30)

    def test_bootstrap_one_use_and_no_second_first_admin(self):
        self.error(
            lambda: self.mfa.bootstrap(self.bootstrap_secret, "attacker", PASS), 401
        )
        self.error(self.mfa.prepare_bootstrap, 409)
        self.assertEqual(
            sum(r["platform_role"] == "admin" for r in self.rows("auth_identities")), 1
        )
        record = next(
            r["payload"]
            for r in self.rows("auth_audit_outbox")
            if r["payload"]["details"].get("operation") == "bootstrap_admin_created"
        )
        self.assertEqual(record["actor_via"], "operator_cli")
        self.assertEqual(record["resource_id"], self.admin["subject_id"])

    def test_enrollment_challenge_never_session_and_replay_closed(self):
        challenge = self.login()
        self.error(lambda: self.service.verify(challenge.token), 401)
        self.error(
            lambda: self.mfa.begin_enrollment(
                challenge.token, origin="https://evil.example"
            ),
            401,
        )
        enrolled = self.mfa.begin_enrollment(challenge.token, origin=ORIGIN)
        self.error(
            lambda: self.mfa.begin_enrollment(challenge.token, origin=ORIGIN), 401
        )
        self.assertFalse(self.rows("auth_sessions"))
        self.assertNotIn(enrolled.secret, str(self.rows("auth_challenges")))

    def test_admin_login_mfa_context_and_totp_replay(self):
        result = self.enroll()
        self.assertEqual(len(result.recovery_codes), 10)
        verified = self.service.verify(result.session.token)
        self.assertIsNotNone(verified.mfa_verified_at)
        challenge = self.login()
        self.error(
            lambda: self.mfa.complete(
                challenge.token, self.next_code(), origin="https://evil.example"
            ),
            401,
        )
        code = self.next_code()
        session = self.mfa.complete(challenge.token, code, origin=ORIGIN).session
        self.service.verify(session.token)
        self.error(lambda: self.mfa.complete(challenge.token, code, origin=ORIGIN), 401)
        other = self.login()
        self.error(lambda: self.mfa.complete(other.token, code, origin=ORIGIN), 401)

    def test_attempt_budget_survives_failures_and_new_login(self):
        self.enroll()
        challenge = self.login()
        for _ in range(5):
            self.error(
                lambda challenge=challenge: self.mfa.complete(
                    challenge.token, "bad", origin=ORIGIN
                ),
                401,
            )
        row = next(r for r in self.rows("auth_challenges") if r["purpose"] == "login")
        self.assertEqual(row["attempts"], 5)
        self.error(
            lambda: self.mfa.complete(challenge.token, self.next_code(), origin=ORIGIN),
            401,
        )

    def test_expiry_credential_epoch_and_authority_failure(self):
        self.enroll()
        challenge = self.login()
        self.now += timedelta(minutes=5)
        self.error(
            lambda: self.mfa.complete(challenge.token, self.next_code(), origin=ORIGIN),
            401,
        )
        challenge = self.login()
        self.service.revoke_password(self.admin["subject_id"], expected_version=1)
        self.error(
            lambda: self.mfa.complete(challenge.token, self.next_code(), origin=ORIGIN),
            401,
        )

    def test_recovery_revokes_all_and_requires_new_enrollment(self):
        result = self.enroll()
        old = result.session.token
        challenge = self.login()
        recovered = self.mfa.recover(
            challenge.token, result.recovery_codes[0], origin=ORIGIN
        )
        self.error(lambda: self.service.verify(old), 401)
        self.error(
            lambda: self.mfa.recover(
                challenge.token, result.recovery_codes[0], origin=ORIGIN
            ),
            401,
        )
        new_login = self.login()
        self.assertEqual(new_login.purpose, "recovery")
        self.assertEqual(recovered.purpose, "enroll_start")
        self.assertTrue(all(r["revoked_at"] for r in self.rows("auth_sessions")))
        self.assertNotIn(
            result.recovery_codes[0], str(self.rows("auth_recovery_codes"))
        )

    def test_step_up_action_session_binding_and_single_use(self):
        result = self.enroll()
        token = result.session.token
        self.error(
            lambda: self.mfa.rotate_recovery(token, "c1_" + "A" * 43, origin=ORIGIN),
            401,
        )
        challenge = self.mfa.start_step_up(
            token, PASS, "recovery.rotate", origin=ORIGIN
        )
        proof = self.mfa.complete(
            challenge.token, self.next_code(), origin=ORIGIN, session_token=token
        ).proof
        self.error(
            lambda: self.mfa.replace_factor(token, proof.token, origin=ORIGIN), 401
        )
        codes = self.mfa.rotate_recovery(token, proof.token, origin=ORIGIN)
        self.assertEqual(len(codes), 10)
        self.error(
            lambda: self.mfa.rotate_recovery(token, proof.token, origin=ORIGIN), 401
        )

    def test_step_up_expiry_and_wrong_session(self):
        result = self.enroll()
        token = result.session.token
        challenge = self.mfa.start_step_up(token, PASS, "mfa.replace", origin=ORIGIN)
        proof = self.mfa.complete(
            challenge.token, self.next_code(), origin=ORIGIN, session_token=token
        ).proof
        login = self.login()
        other = self.mfa.complete(
            login.token, self.next_code(), origin=ORIGIN
        ).session.token
        self.error(
            lambda: self.mfa.replace_factor(other, proof.token, origin=ORIGIN), 401
        )
        self.now += timedelta(minutes=5)
        self.error(
            lambda: self.mfa.replace_factor(token, proof.token, origin=ORIGIN), 401
        )

    def test_mandatory_audit_failure_rolls_back_recovery(self):
        result = self.enroll()
        challenge = self.login()
        with patch.object(self.mfa, "_audit", side_effect=RuntimeError("sink")):
            self.error(
                lambda: self.mfa.recover(
                    challenge.token, result.recovery_codes[0], origin=ORIGIN
                ),
                503,
            )
        self.service.verify(result.session.token)
        self.mfa.recover(challenge.token, result.recovery_codes[0], origin=ORIGIN)

    def test_membership_and_role_change_fence_challenges(self):
        self.enroll()
        challenge = self.login()
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_identities SET status='suspended',subject_version=subject_version+1 WHERE subject_id=%s",
                (self.admin["subject_id"],),
            )
        self.error(
            lambda: self.mfa.complete(challenge.token, self.next_code(), origin=ORIGIN),
            401,
        )

    def test_missing_key_fails_closed_and_does_not_consume_challenge(self):
        challenge = self.login()
        with patch.dict(os.environ, {"CISSTAT_AUTH_MFA_KEYS": "{}"}):
            self.error(
                lambda: self.mfa.begin_enrollment(challenge.token, origin=ORIGIN), 503
            )
        self.mfa.begin_enrollment(challenge.token, origin=ORIGIN)

    def test_factor_replacement_requires_reenrollment_and_fences_sessions(self):
        result = self.enroll()
        token = result.session.token
        challenge = self.mfa.start_step_up(token, PASS, "mfa.replace", origin=ORIGIN)
        proof = self.mfa.complete(
            challenge.token, self.next_code(), origin=ORIGIN, session_token=token
        ).proof
        pending = self.mfa.replace_factor(token, proof.token, origin=ORIGIN)
        self.error(lambda: self.service.verify(token), 401)
        enrollment = self.mfa.begin_enrollment(pending.token, origin=ORIGIN)
        old_seed = self.seed
        self.seed = base64.b32decode(enrollment.secret)
        self.assertNotEqual(self.seed, old_seed)
        new = self.mfa.complete(
            enrollment.challenge.token, self.next_code(), origin=ORIGIN
        )
        self.service.verify(new.session.token)
        self.error(
            lambda: self.mfa.recover(
                self.login().token, result.recovery_codes[0], origin=ORIGIN
            ),
            401,
        )

    def test_concurrent_totp_accepts_exactly_one(self):
        from concurrent.futures import ThreadPoolExecutor

        self.enroll()
        a = self.login()
        b = self.login()
        code = self.next_code()

        def complete(token):
            from apps.api.authentication.context import AuthHTTPException

            try:
                self.mfa.complete(token, code, origin=ORIGIN)
                return 200
            except AuthHTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(complete, [a.token, b.token]))
        self.assertEqual(sorted(statuses), [200, 401])

    def test_new_process_verifies_durable_challenge(self):
        import json
        import subprocess
        import sys

        self.enroll()
        challenge = self.login()
        code = self.next_code()
        script = """import json,sys
from datetime import datetime
from apps.api.authentication.mfa import MfaService
from apps.api.authentication.storage import PostgresAccessStore
v=json.load(sys.stdin)
s=MfaService(PostgresAccessStore(v['dsn'],schema=v['schema']),clock=lambda:datetime.fromisoformat(v['now']))
r=s.complete(v['token'],v['code'],origin=v['origin'])
assert s.verify(r.session.token).mfa_verified_at
print('durable MFA verified')
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            input=json.dumps(
                {
                    "dsn": DSN,
                    "schema": self.schema,
                    "now": self.now.isoformat(),
                    "token": challenge.token,
                    "code": code,
                    "origin": ORIGIN,
                }
            ),
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("durable MFA verified", result.stdout)

    def test_migration_checksum_and_database_guards(self):
        from apps.api.authentication.errors import (
            RepositoryConflict,
        )
        from apps.api.authentication.mfa_migrations import apply_migration

        result = self.enroll()
        with self.store.transaction() as tx:
            self.assertFalse(apply_migration(tx.connection))
        for statement in [
            "UPDATE auth_mfa_factors SET last_step=last_step-1",
            "UPDATE auth_recovery_codes SET code_hash=repeat('a',64)",
            "UPDATE auth_session_mfa SET verified_at=verified_at+interval '1 second'",
            "UPDATE auth_bootstrap SET consumed_at=NULL",
        ]:
            with self.assertRaises(RepositoryConflict), self.store.transaction() as tx:
                tx.connection.execute(statement)
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_schema_versions SET checksum='bad' WHERE version='0021_auth05_mfa'"
            )
        self.error(lambda: self.service.verify(result.session.token), 503)

    def test_mfa_password_change_requires_action_step_up(self):
        from tests.integration.test_auth04_sessions import NEW

        result = self.enroll()
        token = result.session.token
        self.error(lambda: self.service.change_password(token, PASS, NEW), 401)
        challenge = self.mfa.start_step_up(
            token, PASS, "password.change", origin=ORIGIN
        )
        proof = self.mfa.complete(
            challenge.token, self.next_code(), origin=ORIGIN, session_token=token
        ).proof
        self.service.change_password(token, PASS, NEW, proof=proof.token, origin=ORIGIN)
        self.error(lambda: self.service.verify(token), 401)
        self.service.login("named-admin", NEW, self.admin["account_id"], origin=ORIGIN)

    def test_new_challenge_does_not_reset_subject_attempt_limit(self):
        self.enroll()
        for count in (5, 4):
            challenge = self.login()
            for _ in range(count):
                self.error(
                    lambda challenge=challenge: self.mfa.complete(
                        challenge.token, "bad", origin=ORIGIN
                    ),
                    401,
                )
        challenge = self.login()
        self.error(
            lambda: self.mfa.complete(challenge.token, self.next_code(), origin=ORIGIN),
            429,
        )

    def test_concurrent_recovery_codes_cannot_recover_twice(self):
        from concurrent.futures import ThreadPoolExecutor

        from apps.api.authentication.context import AuthHTTPException

        result = self.enroll()
        a = self.login()
        b = self.login()

        def recover(pair):
            try:
                self.mfa.recover(pair[0], pair[1], origin=ORIGIN)
                return 200
            except AuthHTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(
                pool.map(
                    recover,
                    [
                        (a.token, result.recovery_codes[0]),
                        (b.token, result.recovery_codes[1]),
                    ],
                )
            )
        self.assertEqual(sorted(statuses), [200, 401])
        self.assertEqual(
            sum(r["consumed_at"] is not None for r in self.rows("auth_recovery_codes")),
            1,
        )

    def test_account_membership_revocation_and_safe_storage(self):
        result = self.enroll()
        challenge = self.login()
        persisted = str(
            self.rows("auth_audit_outbox")
            + self.rows("auth_challenges")
            + self.rows("auth_recovery_codes")
            + self.rows("auth_mfa_factors")
        )
        for secret in (
            challenge.token,
            result.session.token,
            base64.b32encode(self.seed).decode(),
            *result.recovery_codes,
        ):
            self.assertNotIn(secret, persisted)
        with self.store.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_accounts SET status='closed',entitlement_version=entitlement_version+1 WHERE account_id=%s",
                (self.admin["account_id"],),
            )
        self.error(
            lambda: self.mfa.complete(challenge.token, self.next_code(), origin=ORIGIN),
            401,
        )
        self.error(lambda: self.service.verify(result.session.token), 401)

    def test_recovery_lost_response_never_reopens_password_only_enrollment(self):
        result = self.enroll()
        self.mfa.recover(self.login().token, result.recovery_codes[0], origin=ORIGIN)
        resumed = self.login()
        self.assertEqual(resumed.purpose, "recovery")
        self.error(lambda: self.mfa.begin_enrollment(resumed.token, origin=ORIGIN), 401)
        self.error(
            lambda: self.mfa.complete(resumed.token, self.next_code(), origin=ORIGIN),
            401,
        )
        self.error(
            lambda: self.mfa.recover(
                resumed.token, result.recovery_codes[0], origin=ORIGIN
            ),
            401,
        )
        pending = self.mfa.recover(
            resumed.token, result.recovery_codes[1], origin=ORIGIN
        )
        self.assertEqual(pending.purpose, "enroll_start")
        self.mfa.begin_enrollment(pending.token, origin=ORIGIN)


@unittest.skipUnless(DSN, "Mandatory gate requires CISSTAT_AUTH_TEST_DSN")
class MfaHTTPTests(unittest.TestCase):
    cleanup = MfaSQLTests.cleanup
    rows = MfaSQLTests.rows

    def setUp(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from apps.api.routers.authentication import router

        MfaSQLTests.setUp(self)
        env = patch.dict(
            os.environ,
            {
                "CISSTAT_AUTH_ALLOWED_ORIGINS": ORIGIN,
                "CISSTAT_AUTH_CSRF_KEY": "c" * 40,
                "CISSTAT_IDENTITY_MODE": "scoped",
            },
        )
        env.start()
        self.addCleanup(env.stop)
        app = FastAPI()
        app.include_router(router, prefix="/v1/auth")
        app.state.auth_access_store = self.store
        app.state.auth_session_service = self.service
        app.state.auth_mfa_service = self.mfa
        self.client = TestClient(app, base_url=ORIGIN)
        self.addCleanup(self.client.close)

    def post(self, path, body):
        csrf = self.client.get("/v1/auth/csrf", headers={"Origin": ORIGIN})
        self.assertEqual(csrf.status_code, 200, csrf.text)
        return self.client.post(
            "/v1/auth" + path,
            json=body,
            headers={"Origin": ORIGIN, "X-CSRF-Token": csrf.json()["csrf_token"]},
        )

    def login(self):
        r = self.post(
            "/login",
            {
                "login": "named-admin",
                "password": PASS,
                "account_id": self.admin["account_id"],
            },
        )
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["challenge_token"]

    def enroll(self):
        from apps.api.authentication.mfa_crypto import totp

        challenge = self.login()
        self.assertFalse(self.rows("auth_sessions"))
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)
        r = self.post("/mfa/enroll", {"challenge_token": challenge})
        self.assertEqual(r.status_code, 200, r.text)
        self.seed = base64.b32decode(r.json()["secret"])
        self.now += timedelta(seconds=30)
        result = self.post(
            "/mfa/verify",
            {
                "challenge_token": r.json()["challenge_token"],
                "code": totp(self.seed, int(self.now.timestamp()) // 30),
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("no-store", result.headers["cache-control"])
        return result.json()

    def test_full_http_enroll_login_me_logout_and_cookie(self):
        result = self.enroll()
        from apps.api.authentication.csrf import AUTH_COOKIE

        cookie = self.client.cookies.get(AUTH_COOKIE)
        self.assertTrue(cookie.startswith("s1_"))
        self.assertNotIn(cookie, str(result))
        r = self.client.get("/v1/auth/me")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["role"], "admin")
        self.assertTrue(r.json()["mfa_verified_at"])
        self.assertEqual(self.post("/logout", {}).status_code, 204)
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)

    def test_http_stepup_and_recovery_rotation_guard(self):
        from apps.api.authentication.mfa_crypto import totp

        self.enroll()
        bad = self.post("/recovery/rotate", {"proof": "c1_" + "A" * 43})
        self.assertEqual(bad.status_code, 401, bad.text)
        challenge = self.post(
            "/step-up", {"password": PASS, "action": "recovery.rotate"}
        )
        self.assertEqual(challenge.status_code, 200, challenge.text)
        self.now += timedelta(seconds=30)
        proof = self.post(
            "/mfa/verify",
            {
                "challenge_token": challenge.json()["challenge_token"],
                "code": totp(self.seed, int(self.now.timestamp()) // 30),
            },
        )
        self.assertEqual(proof.status_code, 200, proof.text)
        r = self.post("/recovery/rotate", {"proof": proof.json()["challenge_token"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(r.json()["recovery_codes"]), 10)
        self.assertEqual(
            self.post(
                "/recovery/rotate", {"proof": proof.json()["challenge_token"]}
            ).status_code,
            401,
        )

    def test_http_recovery_no_full_session_and_safe_validation(self):
        result = self.enroll()
        challenge = self.login()
        r = self.post(
            "/recovery",
            {"challenge_token": challenge, "code": result["recovery_codes"][0]},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["purpose"], "enroll_start")
        self.assertEqual(self.client.get("/v1/auth/me").status_code, 401)
        r = self.post(
            "/mfa/verify",
            {
                "challenge_token": r.json()["challenge_token"],
                "code": "SENSITIVE_INPUT",
                "mfa_verified": True,
            },
        )
        self.assertEqual(r.status_code, 422)
        self.assertNotIn("SENSITIVE_INPUT", r.text)

    def test_all_new_commands_require_csrf_and_exact_origin(self):
        payloads = {
            "/mfa/enroll": {"challenge_token": "c1_" + "A" * 43},
            "/mfa/verify": {"challenge_token": "c1_" + "A" * 43, "code": "123456"},
            "/step-up": {"password": PASS, "action": "mfa.replace"},
            "/mfa/replace": {"proof": "c1_" + "A" * 43},
            "/recovery": {"challenge_token": "c1_" + "A" * 43, "code": "r1_code"},
            "/recovery/rotate": {"proof": "c1_" + "A" * 43},
        }
        for path, body in payloads.items():
            r = self.client.post(
                "/v1/auth" + path, json=body, headers={"Origin": ORIGIN}
            )
            self.assertEqual(r.status_code, 403, (path, r.text))
        self.assertEqual(
            self.client.post("/v1/auth/bootstrap", json={}).status_code, 404
        )
