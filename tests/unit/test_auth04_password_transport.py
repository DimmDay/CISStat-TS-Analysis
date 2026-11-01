"""AUTH-04 cryptographic/transport negative contracts, no database fallback."""

from datetime import datetime, timezone
from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from fastapi import HTTPException
from starlette.requests import Request
from apps.api.authentication.credentials import PasswordCodec, validate_password
from apps.api.authentication.csrf import (
    issue_csrf,
    check_csrf,
    auth_cookie,
    AUTH_COOKIE,
)
from apps.api.authentication.sessions import SessionService, token_digest

PASS = "A durable passphrase for AUTH04!"


def req(method="POST", headers=None, cookies=""):
    h = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if cookies:
        h.append((b"cookie", cookies.encode()))
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/v1/auth/login",
            "headers": h,
            "query_string": b"",
        }
    )


class PasswordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.codec = PasswordCodec()

    def test_argon2id_random_salt_and_verify(self):
        a = self.codec.hash(PASS)
        b = self.codec.hash(PASS)
        self.assertTrue(a.startswith("$argon2id$"))
        self.assertIn("m=65536,t=3,p=1", a)
        self.assertNotEqual(a, b)
        self.assertTrue(self.codec.verify(a, PASS))
        self.assertFalse(self.codec.verify(a, "wrong"))
        self.assertNotIn(PASS, a)

    def test_malformed_hash_never_authenticates(self):
        for value in ("plain-password", "$argon2id$broken", ""):
            self.assertFalse(self.codec.verify(value, PASS))

    def test_long_password_not_truncated_or_stripped(self):
        p = " " + ("Яд" * 100) + " trailing "
        h = self.codec.hash(p)
        self.assertTrue(self.codec.verify(h, p))
        self.assertFalse(self.codec.verify(h, p.strip()))

    def test_policy_length_and_blocklist(self):
        for p in ("short", "correct horse battery staple", "x" * 1025):
            with self.subTest(password_length=len(p)), self.assertRaises(HTTPException):
                validate_password(p)
        validate_password(PASS)

    def test_invalid_unicode_is_policy_denial_not_server_error(self):
        value = "x" * 15 + chr(0xD800)
        with self.assertRaises(HTTPException) as e:
            validate_password(value)
        self.assertEqual(e.exception.status_code, 422)
        self.assertFalse(self.codec.verify(None, value))

    def test_no_dummy_password_is_a_real_account(self):
        self.assertFalse(self.codec.verify(None, PASS))


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "CISSTAT_AUTH_CSRF_KEY": "test-only-auth04-csrf-secret-" + "a" * 32,
                "CISSTAT_AUTH_ALLOWED_ORIGINS": "https://standalone.example,https://embedded.example",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def proof(self, auth=""):
        return issue_csrf(
            req(
                "GET",
                {"Origin": "https://standalone.example"},
                f"{AUTH_COOKIE}={auth}" if auth else "",
            )
        )

    def protected(
        self, proof, auth="", origin="https://standalone.example", site="same-origin"
    ):
        cookies = (
            "__Host-cisstat_csrf=" + proof + (f"; {AUTH_COOKIE}={auth}" if auth else "")
        )
        return req(
            headers={"Origin": origin, "Sec-Fetch-Site": site, "X-CSRF-Token": proof},
            cookies=cookies,
        )

    def test_valid_csrf_both_exact_origins(self):
        for origin in ("https://standalone.example", "https://embedded.example"):
            proof = issue_csrf(req("GET", {"Origin": origin}))
            check_csrf(self.protected(proof, origin=origin))

    def test_missing_cross_origin_and_cross_site_fail(self):
        proof = self.proof()
        for r in (
            req(),
            self.protected(proof, origin="https://standalone.example.evil"),
            self.protected(proof, site="cross-site"),
        ):
            with self.assertRaises(HTTPException) as e:
                check_csrf(r)
            self.assertEqual(e.exception.status_code, 403)

    def test_signature_cookie_header_and_session_binding(self):
        proof = self.proof(auth="s1_" + "A" * 43)
        check_csrf(self.protected(proof, auth="s1_" + "A" * 43))
        for r in (
            self.protected(proof + "x", auth="s1_" + "A" * 43),
            self.protected(proof, auth="s1_" + "B" * 43),
        ):
            with self.assertRaises(HTTPException):
                check_csrf(r)

    def test_expired_csrf_and_future_issue_are_denied(self):
        with patch("apps.api.authentication.csrf.time.time", return_value=1000):
            p = self.proof()
        for clock in (999, 1600):
            with (
                patch("apps.api.authentication.csrf.time.time", return_value=clock),
                self.assertRaises(HTTPException),
            ):
                check_csrf(self.protected(p))

    def test_no_default_key_or_wildcard_origin(self):
        for changes in (
            {"CISSTAT_AUTH_CSRF_KEY": ""},
            {"CISSTAT_AUTH_ALLOWED_ORIGINS": "*"},
        ):
            with patch.dict(os.environ, changes), self.assertRaises(HTTPException) as e:
                self.proof()
            self.assertEqual(e.exception.status_code, 503)

    def test_duplicate_auth_cookie_is_invalid(self):
        with self.assertRaises(HTTPException):
            auth_cookie(req(cookies=f"{AUTH_COOKIE}=one; {AUTH_COOKIE}=two"))

    def test_invalid_opaque_tokens_rejected_before_db(self):
        class Broken:
            def transaction(self, **kw):
                raise AssertionError("DB must not be used")

        service = SessionService(store=Broken())
        for value in ("", "chosen-by-client", "s1_short", "s1_" + ("A" * 44)):
            with self.assertRaises(HTTPException) as e:
                service.verify(value)
            self.assertEqual(e.exception.status_code, 401)

    def test_verifier_domain_separated_and_deterministic(self):
        token = "s1_" + ("A" * 43)
        value = token_digest(token)
        self.assertEqual(value, token_digest(token))
        self.assertNotIn(token, value)
        self.assertEqual(len(value), 64)


if __name__ == "__main__":
    unittest.main()
