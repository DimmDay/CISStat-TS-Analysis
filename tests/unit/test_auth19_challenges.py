"""AUTH-19 contracts: OIDC adapter, email challenge secrets, route map.

No network, no DB: the IdP/SMTP are replaced by controlled fakes and the
RSA key pair is generated in-process. Native PostgreSQL flows live in
tests/integration/test_auth19_email_oidc.py.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from apps.api.authentication.context import AuthHTTPException


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
RSA_N = RSA_KEY.public_key().public_numbers().n
RSA_E = RSA_KEY.public_key().public_numbers().e
JWKS = {
    "keys": [
        {
            "kty": "RSA",
            "kid": "test-key",
            "use": "sig",
            "alg": "RS256",
            "n": b64url(RSA_N.to_bytes((RSA_N.bit_length() + 7) // 8, "big")),
            "e": b64url(RSA_E.to_bytes(3, "big")),
        }
    ]
}


def make_id_token(claims, *, alg="RS256", kid="test-key", key=RSA_KEY, tamper=None):
    header = {"alg": alg, "typ": "JWT"}
    if kid:
        header["kid"] = kid
    signing_input = (
        b64url(json.dumps(header).encode())
        + "."
        + b64url(json.dumps(claims).encode())
    )
    if alg == "RS256":
        signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    else:
        signature = b"not-a-real-signature"
    if tamper:
        signing_input = tamper(signing_input)
    return signing_input + "." + b64url(signature)


def resealed_payload_token(token, changes):
    """Original signature over modified payload: signature must fail."""
    header_b64, payload_b64, signature_b64 = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4)))
    claims.update(changes)
    return header_b64 + "." + b64url(json.dumps(claims).encode()) + "." + signature_b64


DISCOVERY = {
    "issuer": "https://idp.example.test",
    "authorization_endpoint": "https://idp.example.test/authorize",
    "token_endpoint": "https://idp.example.test/token",
    "jwks_uri": "https://idp.example.test/jwks",
}


class FakeTransport(httpx.MockTransport):
    def __init__(self, discovery=None, jwks=None, id_token="dummy.header.value"):
        self.discovery = discovery or DISCOVERY
        self.jwks = jwks or JWKS
        self.id_token = id_token
        self.calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.calls.append(request)
            if request.url.path.endswith("/jwks"):
                return httpx.Response(200, json=self.jwks)
            if request.url.path.endswith("/token"):
                return httpx.Response(200, json={"access_token": "a", "id_token": self.id_token})
            if request.url.path.endswith("/.well-known/openid-configuration"):
                return httpx.Response(200, json=self.discovery)
            return httpx.Response(404)

        super().__init__(handler)


CONFIG = {
    "CISSTAT_AUTH_OIDC_ISSUER": "https://idp.example.test",
    "CISSTAT_AUTH_OIDC_CLIENT_ID": "cisstat-platform",
    "CISSTAT_AUTH_EMAIL_KEY": "k" * 40,
}


class PkceTests(unittest.TestCase):
    def test_pair_shape_and_s256_challenge(self):
        from apps.api.authentication.providers.oidc import pkce_pair

        verifier, challenge = pkce_pair()
        self.assertTrue(43 <= len(verifier) <= 128)
        self.assertRegex(verifier, r"^[A-Za-z0-9_-]+$")
        expected = b64url(hashlib.sha256(verifier.encode()).digest())
        self.assertEqual(challenge, expected)
        self.assertNotEqual(pkce_pair()[0], verifier)


class ConfigTests(unittest.TestCase):
    def test_disabled_without_env(self):
        from apps.api.authentication.providers.oidc import OidcConfig

        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(OidcConfig.from_env())

    def test_enabled_and_https_only(self):
        from apps.api.authentication.providers.oidc import OidcConfig

        with patch.dict(os.environ, CONFIG, clear=True):
            config = OidcConfig.from_env()
        self.assertEqual(config.issuer, "https://idp.example.test")
        self.assertEqual(config.client_id, "cisstat-platform")
        self.assertIsNone(config.client_secret)
        with patch.dict(
            os.environ,
            {"CISSTAT_AUTH_OIDC_ISSUER": "http://idp.example.test", "CISSTAT_AUTH_OIDC_CLIENT_ID": "x"},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                OidcConfig.from_env()
        with patch.dict(
            os.environ,
            {"CISSTAT_AUTH_OIDC_ISSUER": "https://idp.example.test", "CISSTAT_AUTH_OIDC_CLIENT_ID": ""},
            clear=True,
        ):
            self.assertIsNone(OidcConfig.from_env())


class ProviderTests(unittest.TestCase):
    def provider(self, **kwargs):
        from apps.api.authentication.providers.oidc import OidcConfig, OidcProvider

        config = OidcConfig(
            "https://idp.example.test",
            "cisstat-platform",
            client_secret=kwargs.get("secret"),
        )
        return OidcProvider(config, transport=FakeTransport(**kwargs.get("fake", {})))

    def test_authorization_url_exact_params(self):
        p = self.provider()
        url = p.authorization_url(
            redirect_uri="https://datasetup.ru/login",
            state="o1_" + "a" * 43,
            nonce="nonce-value",
            code_challenge="ch",
        )
        self.assertTrue(url.startswith("https://idp.example.test/authorize?"))
        from urllib.parse import parse_qsl, urlsplit

        query = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
        self.assertEqual(query["response_type"], "code")
        self.assertEqual(query["client_id"], "cisstat-platform")
        self.assertEqual(query["redirect_uri"], "https://datasetup.ru/login")
        self.assertIn("openid", query["scope"].replace("%20", " ").split())
        self.assertEqual(query["code_challenge_method"], "S256")
        self.assertEqual(query["state"], "o1_" + "a" * 43)
        self.assertEqual(query["nonce"], "nonce-value")
        self.assertEqual(query["code_challenge"], "ch")

    def test_discovery_issuer_mismatch_and_https(self):
        p = self.provider(fake={"discovery": {**DISCOVERY, "issuer": "https://other.example.test"}})
        with self.assertRaises(Exception):
            p.discovery()
        insecure = self.provider(
            fake={"discovery": {**DISCOVERY, "token_endpoint": "http://idp.example.test/token"}}
        )
        with self.assertRaises(Exception):
            insecure.discovery()

    def test_exchange_bounded_and_basic_auth(self):
        transport = FakeTransport()
        p = self.provider(secret="top-secret", fake={"discovery": DISCOVERY})
        p._http = httpx.Client(transport=transport, timeout=5.0)
        tokens = p.exchange(
            code="abc", code_verifier="v" * 50, redirect_uri="https://datasetup.ru/login"
        )
        self.assertIn("id_token", tokens)
        request = [c for c in transport.calls if c.url.path.endswith("/token")][0]
        self.assertEqual(request.method, "POST")
        self.assertIn("code=abc", request.content.decode())
        self.assertIn("code_verifier=" + "v" * 50, request.content.decode())
        self.assertIn("grant_type=authorization_code", request.content.decode())
        self.assertIn("Basic ", request.headers["authorization"])

    def test_id_token_happy_path_and_nonce(self):
        p = self.provider()
        claims = {
            "iss": "https://idp.example.test",
            "sub": "user-24",
            "aud": "cisstat-platform",
            "exp": int(time.time()) + 300,
            "nonce": "nonce-value",
        }
        token = make_id_token(claims)
        verified = p.verify_id_token(token, nonce="nonce-value")
        self.assertEqual(verified["sub"], "user-24")

    def test_id_token_rejects_forgery_and_contract_drift(self):
        p = self.provider()
        now = int(time.time())
        base = {
            "iss": "https://idp.example.test",
            "sub": "user-24",
            "aud": "cisstat-platform",
            "exp": now + 300,
            "nonce": "nonce-value",
        }
        wrong_nonce = make_id_token({**base, "nonce": "evil"})
        with self.assertRaises(Exception):
            p.verify_id_token(wrong_nonce, nonce="nonce-value")
        wrong_iss = make_id_token({**base, "iss": "https://evil.example.test"})
        with self.assertRaises(Exception):
            p.verify_id_token(wrong_iss, nonce="nonce-value")
        wrong_aud = make_id_token({**base, "aud": "another-client"})
        with self.assertRaises(Exception):
            p.verify_id_token(wrong_aud, nonce="nonce-value")
        expired = make_id_token({**base, "exp": now - 300})
        with self.assertRaises(Exception):
            p.verify_id_token(expired, nonce="nonce-value")
        future_nbf = make_id_token({**base, "nbf": now + 600})
        with self.assertRaises(Exception):
            p.verify_id_token(future_nbf, nonce="nonce-value")
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        foreign = make_id_token(base, key=other_key)
        with self.assertRaises(Exception):
            p.verify_id_token(foreign, nonce="nonce-value")
        tampered = resealed_payload_token(make_id_token(base), {"sub": "user-99"})
        with self.assertRaises(Exception):
            p.verify_id_token(tampered, nonce="nonce-value")
        alg_none = make_id_token(base, alg="none", kid=None)
        with self.assertRaises(Exception):
            p.verify_id_token(alg_none, nonce="nonce-value")
        alg_hs = make_id_token(base, alg="HS256", kid=None)
        with self.assertRaises(Exception):
            p.verify_id_token(alg_hs, nonce="nonce-value")
        unknown_kid = make_id_token(base, kid="rogue")
        with self.assertRaises(Exception):
            p.verify_id_token(unknown_kid, nonce="nonce-value")
        missing_sub = make_id_token({k: v for k, v in base.items() if k != "sub"})
        with self.assertRaises(Exception):
            p.verify_id_token(missing_sub, nonce="nonce-value")

    def test_no_secret_in_repr(self):
        p = self.provider(secret="top-secret-value")
        self.assertNotIn("top-secret-value", repr(p))


class EmailSecretTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {"CISSTAT_AUTH_EMAIL_KEY": "k" * 40})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_normalize_email(self):
        from apps.api.authentication.email_challenges import normalize_email

        self.assertEqual(normalize_email(" User.Name+tag@Sub.Example.RU "), "user.name+tag@sub.example.ru")
        for bad in ("", "a@b", "user@@example.ru", "user@nodot", "@example.ru", "user name@example.ru", "x" * 330 + "@example.ru"):
            with self.assertRaises(AuthHTTPException):
                normalize_email(bad)

    def test_keyed_digests_domain_separated(self):
        from apps.api.authentication.email_challenges import email_code_digest, email_token_digest

        token = "e1_" + "A" * 43
        digest = email_token_digest(token)
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        with patch.dict(os.environ, {"CISSTAT_AUTH_EMAIL_KEY": "other-key" * 8}, clear=False):
            self.assertNotEqual(email_token_digest(token), digest)
        code_a = email_code_digest("user@example.ru", "12345678")
        code_b = email_code_digest("other@example.ru", "12345678")
        self.assertNotEqual(code_a, code_b)
        self.assertNotEqual(email_code_digest("user@example.ru", "87654321"), code_a)

    def test_token_format_gate(self):
        from apps.api.authentication.email_challenges import email_token_digest

        for bad in ("", "wrong_prefix", "e1_short", "e1_" + "*" * 43):
            with self.assertRaises(AuthHTTPException):
                email_token_digest(bad)

    def test_otp_code_shape(self):
        from apps.api.authentication.email_challenges import generate_code

        codes = {generate_code() for _ in range(50)}
        self.assertTrue(all(len(c) == 8 and c.isdigit() for c in codes))
        self.assertGreater(len(codes), 1)

    def test_email_issuer_is_not_an_idp(self):
        from apps.api.authentication.email_challenges import EMAIL_ISSUER

        self.assertEqual(EMAIL_ISSUER, "cisstat.email/1")


class DeliveryConfigTests(unittest.TestCase):
    def test_disabled_without_host(self):
        from apps.api.authentication.providers.email_delivery import SmtpEmailDelivery

        with patch.dict(os.environ, {k: v for k, v in os.environ.items() if k != "CISSTAT_AUTH_SMTP_HOST"}, clear=False):
            self.assertIsNone(SmtpEmailDelivery.from_env())

    def test_env_config(self):
        from apps.api.authentication.providers.email_delivery import SmtpEmailDelivery

        env = {
            "CISSTAT_AUTH_SMTP_HOST": "smtp.example.test",
            "CISSTAT_AUTH_SMTP_PORT": "2587",
            "CISSTAT_AUTH_SMTP_USER": "platform",
            "CISSTAT_AUTH_SMTP_PASSWORD": "mail-secret",
            "CISSTAT_AUTH_SMTP_FROM": "CISStat <no-reply@datasetup.ru>",
            "CISSTAT_AUTH_SMTP_TLS": "starttls",
        }
        with patch.dict(os.environ, env, clear=False):
            delivery = SmtpEmailDelivery.from_env()
        self.assertEqual(delivery.host, "smtp.example.test")
        self.assertEqual(delivery.port, 2587)
        self.assertNotIn("mail-secret", repr(delivery))

    def test_send_failure_is_safe(self):
        from apps.api.authentication.providers.email_delivery import DeliveryUnavailable, SmtpEmailDelivery

        delivery = SmtpEmailDelivery(host="127.0.0.1", port=1, sender="no-reply@datasetup.ru", timeout=1.0)
        with self.assertRaises(DeliveryUnavailable):
            delivery.send("user@example.ru", "Тема", "Тело письма")


if __name__ == "__main__":
    unittest.main()
