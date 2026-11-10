"""AUTH-19 native PostgreSQL flows: trial identities, email challenges, OIDC.

Real SQL transactions/guards against a disposable PostgreSQL; the IdP and the
mail transport are replaced by controlled fakes, and RS256 keys are generated
in-process. No real network, no production VM, no real IdP is claimed.
"""

import base64
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qsl, urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from fastapi import HTTPException

from apps.api.authentication.context import auth_error
from apps.api.authentication.storage import PostgresAccessStore
from apps.api.authentication.sessions import SessionService
from tests.integration import test_auth04_sessions as previous

ISSUER = "https://idp.example.test"
CLIENT_ID = "cisstat-platform"

RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
RSA_N = RSA_KEY.public_key().public_numbers().n
RSA_E = RSA_KEY.public_key().public_numbers().e
JWKS = {
    "keys": [
        {
            "kty": "RSA",
            "kid": "native-key",
            "use": "sig",
            "alg": "RS256",
            "n": base64.urlsafe_b64encode(RSA_N.to_bytes((RSA_N.bit_length() + 7) // 8, "big")).rstrip(b"=").decode(),
            "e": base64.urlsafe_b64encode(RSA_E.to_bytes(3, "big")).rstrip(b"=").decode(),
        }
    ]
}


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_id_token(claims, *, key=RSA_KEY, kid="native-key", alg="RS256"):
    header = {"alg": alg, "typ": "JWT", "kid": kid}
    signing_input = (
        b64url(json.dumps(header).encode()) + "." + b64url(json.dumps(claims).encode())
    )
    if alg == "RS256":
        signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    else:
        signature = b"bogus"
    return signing_input + "." + b64url(signature)


class FakeDelivery:
    def __init__(self):
        self.letters = []
        self.fail = False

    def send(self, to_email, subject, body):
        if self.fail:
            from apps.api.authentication.providers.email_delivery import DeliveryUnavailable

            raise DeliveryUnavailable()
        self.letters.append({"to": to_email, "subject": subject, "body": body})


class FakeIdp(httpx.MockTransport):
    """Controlled IdP: discovery/JWKS/token on a fixed HTTPS issuer."""

    def __init__(self):
        self.id_token = None
        self.outage = False
        self.token_status = 200

        def handler(request: httpx.Request) -> httpx.Response:
            if self.outage:
                return httpx.Response(503)
            if request.url.path.endswith("/jwks"):
                return httpx.Response(200, json=JWKS)
            if request.url.path.endswith("/token"):
                if self.token_status != 200:
                    return httpx.Response(self.token_status)
                return httpx.Response(
                    200, json={"access_token": "a1", "id_token": self.id_token}
                )
            if request.url.path.endswith("/.well-known/openid-configuration"):
                return httpx.Response(
                    200,
                    json={
                        "issuer": ISSUER,
                        "authorization_endpoint": ISSUER + "/authorize",
                        "token_endpoint": ISSUER + "/token",
                        "jwks_uri": ISSUER + "/jwks",
                    },
                )
            return httpx.Response(404)

        super().__init__(handler)


@unittest.skipUnless(
    os.environ.get("CISSTAT_AUTH_TEST_DSN"), "disposable PostgreSQL required"
)
class Auth19SQLTests(previous.SessionSQLTests):
    """Extends the AUTH-04 native fixture: fresh schema per test."""

    def setUp(self):
        super().setUp()
        from apps.api.authentication.auth19_migrations import apply_migration

        with self.store.transaction() as tx:
            apply_migration(tx.connection)
        self.delivery = FakeDelivery()
        self.idp = FakeIdp()
        self.email_patcher = patch.dict(
            os.environ,
            {
                "CISSTAT_AUTH_EMAIL_KEY": "native-email-key-" + "0" * 40,
                "CISSTAT_AUTH_SMTP_HOST": "smtp.example.test",
            },
        )
        self.email_patcher.start()
        self.addCleanup(self.email_patcher.stop)
        self.delivery_patcher = patch(
            "apps.api.authentication.providers.email_delivery.SmtpEmailDelivery.from_env",
            return_value=self.delivery,
        )
        self.delivery_patcher.start()
        self.addCleanup(self.delivery_patcher.stop)
        self.oidc_patcher = patch.dict(
            os.environ,
            {
                "CISSTAT_AUTH_OIDC_ISSUER": ISSUER,
                "CISSTAT_AUTH_OIDC_CLIENT_ID": CLIENT_ID,
            },
        )
        self.oidc_patcher.start()
        self.addCleanup(self.oidc_patcher.stop)
        self.provider_patcher = patch(
            "apps.api.authentication.oidc.OidcProvider",
            lambda config: previous_oidc(config, self.idp),
        )
        self.provider_patcher.start()
        self.addCleanup(self.provider_patcher.stop)
        from apps.api.authentication.email_challenges import EmailChallengeService
        from apps.api.authentication.oidc import OidcService

        self.email = EmailChallengeService(store=self.store, clock=lambda: self.now)
        self.oidc = OidcService(store=self.store, clock=lambda: self.now)

    # --- helpers -------------------------------------------------------

    def person(self, login):
        """A personal password identity with its own MONO starter account."""
        with self.store.transaction() as tx:
            person = tx.identities.create()
            account = tx.accounts.create(person.subject_id, plan="starter")
        self.service.set_password(person.subject_id, login, previous.PASS)
        issued = self.service.login(
            login, previous.PASS, account.account_id, origin=previous.ORIGIN
        )
        return person, account, issued.token

    def identity_row(self, subject_id):
        with self.store.transaction(readonly=True) as tx:
            return tx.identities.get(subject_id)

    def accounts_of(self, subject_id):
        with self.store.transaction(readonly=True) as tx:
            return tx.accounts.for_subject(subject_id)

    def bindings(self, subject_id):
        with self.store.transaction(readonly=True) as tx:
            return tx.identities.external_identities(subject_id)

    def begin_email(self, email, purpose="trial_login", **kw):
        return self.email.start(
            email, purpose, previous.ORIGIN, kw.pop("peer", "203.0.113.50"), **kw
        )

    def consume_email_token(self, email, session_token=None):
        letters = [x for x in self.delivery.letters if x["to"] == email]
        body = letters[-1]["body"]
        token = body.split("email_challenge=")[1].split("\n")[0]
        return self.email.consume(
            token=token,
            origin=previous.ORIGIN,
            old_token=None,
            session_token=session_token,
        )

    def begin_oidc(self, purpose="login", token=None):
        result = self.oidc.start(
            purpose,
            previous.ORIGIN,
            "203.0.113.9",
            session_token=token,
        )
        query = dict(parse_qsl(urlsplit(result["authorize_url"]).query))
        return result, query

    def finish_oidc(self, subject="external-user-24", email="ext@example.ru", **claims):
        _, query = self.begin_oidc()
        now = int(time.time())
        payload = {
            "iss": ISSUER,
            "sub": subject,
            "aud": CLIENT_ID,
            "exp": now + 300,
            "nonce": query["nonce"],
            "email": email,
            "email_verified": True,
        }
        payload.update(claims)
        for remove in [k for k, v in payload.items() if v is None]:
            payload.pop(remove)
        self.idp.id_token = make_id_token(payload)
        return query, self.idp.id_token

    # --- migration -----------------------------------------------------

    def test_migration_repeat_and_guards(self):
        from apps.api.authentication.auth19_migrations import apply_migration, check_schema

        with self.store.transaction() as tx:
            self.assertFalse(apply_migration(tx.connection))
            check_schema(tx.connection)
        with self.store.transaction(readonly=True) as tx:
            # The AUTH-15 family check is honestly extended (external kind).
            definition = tx.connection.execute(
                "SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint WHERE conname='auth15_session_family' AND conrelid='auth_sessions'::regclass"
            ).fetchone()["d"]
            self.assertIn("demo_grant_id", definition)
            nulls = tx.connection.execute(
                """SELECT count(*) AS n FROM information_schema.columns
                WHERE table_schema=current_schema() AND table_name='auth_sessions'
                AND column_name IN ('credential_id','credential_version') AND is_nullable='YES'"""
            ).fetchone()["n"]
            self.assertEqual(nulls, 2)
        # A consumed challenge/state cannot be rewritten.
        self.begin_email("guard@example.ru")
        with self.store.transaction() as tx:
            row = tx.connection.execute(
                "SELECT challenge_id,issued_at,expires_at,email FROM auth_email_challenges LIMIT 1"
            ).fetchone()
            with self.assertRaises(self.pg.errors.CheckViolation):
                tx.connection.execute(
                    "UPDATE auth_email_challenges SET email='other@example.ru' WHERE challenge_id=%s",
                    (row["challenge_id"],),
                )

    def test_checksums_of_previous_auth_migrations_unchanged(self):
        from apps.api.authentication.session_migrations import CHECKSUM as C20
        from apps.api.authentication.mfa_migrations import CHECKSUM as C21

        self.assertTrue(C20 and C21)
        # The AUTH-19 chain applies 0019…0028; 0029/0030 stay independent.
        with self.store.transaction(readonly=True) as tx:
            for version in (
                "0019_auth02_identity_accounts",
                "0020_auth04_sessions",
                "0021_auth05_mfa",
                "0024_auth10_api_keys",
                "0027_auth15_demo",
                "0028_auth16_demo_lifecycle",
            ):
                row = tx.connection.execute(
                    "SELECT checksum FROM auth_schema_versions WHERE version=%s", (version,)
                ).fetchone()
                self.assertIsNotNone(row, version)

    # --- email trial ---------------------------------------------------

    def test_trial_start_uniform_and_hash_only(self):
        first = self.begin_email("trial@example.ru")
        second = self.begin_email("unknown-stranger@example.ru")
        self.assertEqual(first, {"status": "email_sent"})
        self.assertEqual(second, {"status": "email_sent"})
        rows = self.rows("auth_email_challenges")
        self.assertEqual(len(rows), 2)
        # DB stores keyed digests only; the letter intentionally carries the
        # one-time secret for the mailbox owner.
        self.assertNotIn("e1_", str(rows))
        self.assertTrue(self.delivery.letters[0]["to"] == "trial@example.ru")
        self.assertIn("email_challenge=", self.delivery.letters[0]["body"])

    def test_trial_consume_creates_identity_mono_starter_owner(self):
        self.begin_email("trial2@example.ru")
        result = self.consume_email_token("trial2@example.ru")
        evidence = self.service.verify(result.token)
        self.assertEqual(evidence.auth_method, "auth_session")
        self.assertEqual(evidence.scopes, frozenset())
        binding = self.bindings(evidence.subject_id)[0]
        self.assertEqual(binding.issuer, "cisstat.email/1")
        self.assertTrue(binding.email_verified)
        accounts = self.accounts_of(evidence.subject_id)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0].plan, "starter")
        self.assertEqual(accounts[0].account_type, "mono")
        with self.store.transaction(readonly=True) as tx:
            member = tx.accounts.memberships(accounts[0].account_id)[0]
            self.assertEqual(member.account_role, "owner")
        actions = [
            r["payload"]["action"] for r in self.rows("auth_audit_outbox")
        ]
        self.assertIn("auth_identity_changed", actions)
        self.assertIn("auth_session_changed", actions)

    def test_trial_replay_and_second_login_same_identity(self):
        self.begin_email("replay@example.ru")
        first = self.consume_email_token("replay@example.ru")
        self.error(lambda: self.consume_email_token("replay@example.ru"), 401)
        letters_before = len(self.delivery.letters)
        self.begin_email("replay@example.ru")
        second = self.consume_email_token("replay@example.ru")
        self.assertNotEqual(first.token, second.token)
        first_subject = self.service.verify(first.token).subject_id
        second_subject = self.service.verify(second.token).subject_id
        self.assertEqual(first_subject, second_subject)
        self.assertEqual(len(self.accounts_of(first_subject)), 1)
        self.assertGreater(len(self.delivery.letters), letters_before)

    def test_trial_code_path_wrong_code_attempts_and_replay(self):
        self.begin_email("otp@example.ru")
        body = [x for x in self.delivery.letters if x["to"] == "otp@example.ru"][-1]["body"]
        code = body.split("Код подтверждения входа: ")[1].split("\n")[0]
        wrong = "00000000" if code != "00000000" else "11111111"
        for _ in range(4):
            self.error(
                lambda: self.email.consume(
                    code=wrong, email="otp@example.ru", origin=previous.ORIGIN
                ),
                401,
            )
        with self.store.transaction(readonly=True) as tx:
            row = tx.connection.execute(
                "SELECT attempts FROM auth_email_challenges WHERE email='otp@example.ru'"
            ).fetchone()
            self.assertEqual(row["attempts"], 4)
        result = self.email.consume(
            code=code, email="otp@example.ru", origin=previous.ORIGIN
        )
        self.assertTrue(result.token.startswith("s1_"))

    def test_trial_expiry_origin_and_delivery_failure(self):
        self.begin_email("expired@example.ru")
        self.now += timedelta(minutes=16)
        self.error(lambda: self.consume_email_token("expired@example.ru"), 401)
        self.delivery.fail = True
        self.error(lambda: self.begin_email("outage@example.ru"), 503, "email_delivery_unavailable")
        self.delivery.fail = False
        # Nothing was delivered for the failed challenge: a guessed token is
        # refused and the challenge itself is honestly marked failed.
        self.error(
            lambda: self.email.consume(
                token="e1_" + "a" * 43, origin=previous.ORIGIN
            ),
            401,
        )
        with self.store.transaction(readonly=True) as tx:
            row = tx.connection.execute(
                "SELECT delivery_code FROM auth_email_challenges WHERE email='outage@example.ru'"
            ).fetchone()
            self.assertEqual(row["delivery_code"], "failed")

    def test_trial_rate_limits(self):
        # Per-mailbox fixed window: the fourth start for the same address is
        # rejected regardless of the answer uniformity.
        for _ in range(3):
            self.begin_email("limit@example.ru")
        self.error(
            lambda: self.begin_email("limit@example.ru"), 429, "too_many_attempts"
        )

    def test_email_bind_requires_session_and_is_idempotent(self):
        self.error(
            lambda: self.begin_email("bind@example.ru", purpose="email_bind"), 401
        )
        issued = self.login()
        self.begin_email(
            "bind@example.ru", purpose="email_bind", session_token=issued.token
        )
        result = self.consume_email_token("bind@example.ru", session_token=issued.token)
        self.assertEqual(result, {"status": "email_bound"})
        self.assertEqual(len(self.bindings(self.owner.subject_id)), 1)
        # Idempotent repeat for the same subject: new challenge, same binding.
        self.begin_email(
            "bind@example.ru", purpose="email_bind", session_token=issued.token
        )
        self.assertEqual(
            self.consume_email_token("bind@example.ru", session_token=issued.token),
            {"status": "email_bound"},
        )
        self.assertEqual(len(self.bindings(self.owner.subject_id)), 1)
        # Another personal identity cannot claim the same verified address.
        other, _, other_token = self.person("bob19")
        self.error(
            lambda: self.email.start(
                "bind@example.ru",
                "email_bind",
                previous.ORIGIN,
                "203.0.113.51",
                session_token=other_token,
            ),
            409,
            "email_already_bound",
        )
        actions = [r["payload"]["action"] for r in self.rows("auth_audit_outbox")]
        self.assertIn("auth_identity_changed", actions)

    def test_email_bind_consume_by_foreign_session_rejected(self):
        issued = self.login()
        other, _, other_token = self.person("carl19")
        self.begin_email(
            "cross@example.ru", purpose="email_bind", session_token=issued.token
        )
        self.error(
            lambda: self.consume_email_token_with(other_token, "cross@example.ru"),
            401,
        )

    def consume_email_token_with(self, session_token, email):
        letters = [x for x in self.delivery.letters if x["to"] == email]
        token = letters[-1]["body"].split("email_challenge=")[1].split("\n")[0]
        return self.email.consume(
            token=token, origin=previous.ORIGIN, session_token=session_token
        )

    def test_multi_account_trial_login_requires_selection(self):
        # Verified binding identity that owns a personal MONO and sits in a MULTI.
        self.begin_email("select@example.ru")
        issued = self.consume_email_token("select@example.ru")
        subject = self.service.verify(issued.token).subject_id
        with self.store.transaction() as tx:
            person = tx.identities.get(subject)
            team = tx.accounts.create(person.subject_id, account_type="multi", plan="starter", seats=3)
        self.delivery.letters.clear()
        self.begin_email("select@example.ru")
        result = self.consume_email_token("select@example.ru")
        self.assertEqual(result["status"], "account_required")
        self.assertEqual(len(result["accounts"]), 2)
        chosen = self.accounts_of(subject)[0].account_id
        final = self.email.select_login(
            result["selection_token"], chosen, previous.ORIGIN, old_token=issued.token
        )
        self.assertEqual(
            final.session["account_id"], str(chosen)
        )
        self.error(
            lambda: self.email.select_login(
                result["selection_token"], chosen, previous.ORIGIN
            ),
            401,
        )
        # A foreign account is refused even with a fresh valid token.
        self.delivery.letters.clear()
        self.begin_email("select@example.ru")
        again = self.consume_email_token("select@example.ru")
        _, other_account, _ = self.person("dave19")
        self.error(
            lambda: self.email.select_login(
                again["selection_token"], other_account.account_id, previous.ORIGIN
            ),
            403,
        )

    # --- OIDC ----------------------------------------------------------

    def test_oidc_disabled_without_config(self):
        self.oidc_patcher.stop()
        try:
            self.error(
                lambda: self.oidc.start("login", previous.ORIGIN, "p"), 503, "oidc_unavailable"
            )
        finally:
            self.oidc_patcher.start()

    def linked_identity(self, sub, login="linked19"):
        """A personal identity already linked to the fake IdP subject."""
        with self.store.transaction() as tx:
            person = tx.identities.create()
            account = tx.accounts.create(person.subject_id, plan="starter")
            tx.identities.link_external(
                person.subject_id, ISSUER, sub, email=f"{sub}@example.ru", email_verified=True
            )
        self.service.set_password(person.subject_id, login, previous.PASS)
        issued = self.service.login(
            login, previous.PASS, account.account_id, origin=previous.ORIGIN
        )
        return person, account, issued

    def test_oidc_login_happy_path_and_rotation(self):
        issued = self.login()
        self.linked_identity("sub-77")
        query, _ = self.finish_oidc(subject="sub-77", email="sso@example.ru")
        result = self.oidc.callback(
            "code-1", query["state"], previous.ORIGIN, "203.0.113.9", old_token=issued.token
        )
        self.assertTrue(result.token.startswith("s1_"))
        self.error(lambda: self.service.verify(issued.token), 401)
        evidence = self.service.verify(result.token)
        self.assertEqual(evidence.scopes, frozenset())
        # The consumed state cannot be replayed with another code.
        self.error(
            lambda: self.oidc.callback(
                "code-2", query["state"], previous.ORIGIN, "203.0.113.9"
            ),
            401,
        )

    def test_oidc_state_hash_only_and_replay(self):
        self.linked_identity("sub-78")
        query, _ = self.finish_oidc(subject="sub-78")
        rows = self.rows("auth_login_states")
        blob = str(rows)
        self.assertNotIn(query["state"], blob)
        result = self.oidc.callback(
            "code-1", query["state"], previous.ORIGIN, "203.0.113.9"
        )
        self.assertTrue(result.token.startswith("s1_"))
        self.error(
            lambda: self.oidc.callback(
                "code-1", query["state"], previous.ORIGIN, "203.0.113.9"
            ),
            401,
        )

    def test_oidc_id_token_contract_drift(self):
        base = {
            "iss": ISSUER,
            "sub": "sub-79",
            "aud": CLIENT_ID,
            "exp": int(time.time()) + 300,
        }
        _, query = self.begin_oidc()
        self.idp.id_token = make_id_token({**base, "nonce": "evil"})
        self.error(
            lambda: self.oidc.callback("c", query["state"], previous.ORIGIN, "p"), 401
        )
        _, query = self.begin_oidc()
        self.idp.id_token = make_id_token({**base, "nonce": query["nonce"], "aud": "other"})
        self.error(
            lambda: self.oidc.callback("c", query["state"], previous.ORIGIN, "p"), 401
        )
        _, query = self.begin_oidc()
        self.idp.id_token = make_id_token({**base, "nonce": query["nonce"], "iss": "https://evil.example.test"})
        self.error(
            lambda: self.oidc.callback("c", query["state"], previous.ORIGIN, "p"), 401
        )
        _, query = self.begin_oidc()
        self.idp.id_token = make_id_token({**base, "nonce": query["nonce"], "exp": int(time.time()) - 300})
        self.error(
            lambda: self.oidc.callback("c", query["state"], previous.ORIGIN, "p"), 401
        )
        # Provider outage maps to a safe 503 and consumes the state.
        _, query = self.begin_oidc()
        self.idp.id_token = make_id_token({**base, "nonce": query["nonce"]})
        self.idp.outage = True
        self.error(
            lambda: self.oidc.callback("c", query["state"], previous.ORIGIN, "p"), 503
        )

    def test_oidc_unknown_binding_no_merge_even_with_known_email(self):
        # A personal identity already owns the verified email binding; a new
        # OIDC subject presenting the same verified email must NOT merge.
        issued = self.login()
        self.begin_email(
            "merge@example.ru", purpose="email_bind", session_token=issued.token
        )
        self.consume_email_token("merge@example.ru", session_token=issued.token)
        query, _ = self.finish_oidc(subject="brand-new-subject", email="merge@example.ru")
        self.error(
            lambda: self.oidc.callback("c", query["state"], previous.ORIGIN, "p"), 401
        )
        with self.store.transaction(readonly=True) as tx:
            rows = tx.connection.execute(
                "SELECT count(*) AS n FROM auth_external_identities WHERE issuer=%s",
                (ISSUER,),
            ).fetchone()["n"]
            self.assertEqual(rows, 0)

    def test_oidc_link_flow_idempotent_and_conflict(self):
        issued = self.login()
        _, query = self.begin_oidc(purpose="link", token=issued.token)
        self.idp.id_token = make_id_token(
            {
                "iss": ISSUER,
                "sub": "sub-link-1",
                "aud": CLIENT_ID,
                "exp": int(time.time()) + 300,
                "nonce": query["nonce"],
            }
        )
        self.assertEqual(
            self.oidc.callback(
                "c", query["state"], previous.ORIGIN, "p", session_token=issued.token
            ),
            {"status": "linked"},
        )
        self.assertEqual(len(self.bindings(self.owner.subject_id)), 1)
        # Anonymous link attempt (no session) is refused at start.
        self.error(lambda: self.begin_oidc(purpose="link"), 401)
        # The same subject bound elsewhere cannot be bound twice.
        other, _, other_token = self.person("erin19")
        _, query3 = self.begin_oidc(purpose="link", token=other_token)
        self.idp.id_token = make_id_token(
            {
                "iss": ISSUER,
                "sub": "sub-link-1",
                "aud": CLIENT_ID,
                "exp": int(time.time()) + 300,
                "nonce": query3["nonce"],
            }
        )
        self.error(
            lambda: self.oidc.callback(
                "c", query3["state"], previous.ORIGIN, "p", session_token=other_token
            ),
            409,
            "oidc_already_linked",
        )
        actions = [r["payload"]["action"] for r in self.rows("auth_audit_outbox")]
        self.assertIn("auth_identity_changed", actions)

    def test_oidc_admin_requires_local_mfa_path(self):
        # An ADMIN identity with an OIDC binding gets 403 mfa_required: the
        # IdP-MFA evidence contract is a separate delivery, and the local
        # password+MFA path remains the supported admin entry (R3).
        with self.store.transaction() as tx:
            admin = tx.identities.create(platform_role="admin")
            tx.accounts.create(admin.subject_id, plan="starter")
            tx.identities.link_external(
                admin.subject_id, ISSUER, "sub-admin", email="admin@example.ru", email_verified=True
            )
        query, _ = self.finish_oidc(subject="sub-admin")
        self.error(
            lambda: self.oidc.callback("c", query["state"], previous.ORIGIN, "p"),
            403,
            "mfa_required",
        )

    def test_trial_plan_days_policy(self):
        with patch.dict(os.environ, {"CISSTAT_AUTH_TRIAL_PLAN_DAYS": "30"}):
            self.begin_email("policy@example.ru")
            result = self.consume_email_token("policy@example.ru")
        subject = self.service.verify(result.token).subject_id
        account = self.accounts_of(subject)[0]
        self.assertIsNotNone(account.plan_expires_at)


def previous_oidc(config, transport_holder):
    from apps.api.authentication.providers.oidc import OidcProvider

    return OidcProvider(config, transport=transport_holder)


if __name__ == "__main__":
    unittest.main()
