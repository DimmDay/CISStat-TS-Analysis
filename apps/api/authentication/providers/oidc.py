"""AUTH-19 OIDC relying-party adapter. Deny-by-default; no email-based merge.

The platform is the RP: state/nonce/PKCE verifier are minted server-side and
consumed atomically by the authentication service. This adapter performs
bounded HTTPS discovery/JWKS/token calls and full RS256 id_token validation;
it never issues sessions, never trusts unsigned tokens and never merges
identities by the email claim.
"""

import base64
import binascii
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode, urlsplit

import httpx

MAX_DOCUMENT = 256 * 1024
TIMEOUT = 5.0
ALLOWED_ALGS = ("RS256",)
CLAIM_LEEWAY = 60
DEFAULT_SCOPES = "openid profile email"


class ProviderUnavailable(Exception):
    """Configuration/discovery/transport failure; safe 503 upstream."""


class ProviderMismatch(Exception):
    """Protocol forgery or contract drift; safe 401 upstream."""


def pkce_pair():
    verifier = secrets.token_urlsafe(96)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


def _b64url_int(value):
    return int.from_bytes(
        base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)), "big"
    )


def _https_url(value):
    if not isinstance(value, str) or not value.startswith("https://"):
        raise ProviderUnavailable("insecure provider endpoint")
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.password:
        raise ProviderUnavailable("insecure provider endpoint")
    return value


class OidcConfig:
    """Immutable endpoint configuration; enabled only with issuer+client_id."""

    def __init__(self, issuer, client_id, client_secret=None, scopes=None):
        issuer = issuer.strip().rstrip("/") if isinstance(issuer, str) else ""
        if not issuer.startswith("https://") or len(issuer) > 2048:
            raise ValueError("https issuer required")
        if not isinstance(client_id, str) or not client_id.strip() or len(client_id) > 255:
            raise ValueError("client id required")
        if client_secret is not None and (
            not isinstance(client_secret, str) or not client_secret or len(client_secret) > 1024
        ):
            raise ValueError("invalid client secret")
        scopes = DEFAULT_SCOPES if scopes is None else scopes
        if not isinstance(scopes, str) or "openid" not in scopes.split():
            raise ValueError("openid scope required")
        self.issuer = issuer
        self.client_id = client_id.strip()
        self.client_secret = client_secret
        self.scopes = scopes

    def __repr__(self):
        return "OidcConfig(issuer=" + self.issuer + ")"

    @classmethod
    def from_env(cls):
        issuer = os.environ.get("CISSTAT_AUTH_OIDC_ISSUER", "")
        client_id = os.environ.get("CISSTAT_AUTH_OIDC_CLIENT_ID", "")
        if not issuer or not client_id:
            return None
        # Invalid operator configuration fails loudly (503), never disabled-run.
        return cls(
            issuer,
            client_id,
            client_secret=os.environ.get("CISSTAT_AUTH_OIDC_CLIENT_SECRET") or None,
            scopes=os.environ.get("CISSTAT_AUTH_OIDC_SCOPES") or None,
        )


class OidcProvider:
    def __init__(self, config, *, transport=None, clock=time.time):
        self.config = config
        self._clock = clock
        if transport is not None:
            self._http = httpx.Client(
                transport=transport, timeout=TIMEOUT, follow_redirects=False
            )
        else:
            self._http = None

    def __repr__(self):
        return "OidcProvider(issuer=" + self.config.issuer + ")"

    def _client(self):
        if self._http is None:
            self._http = httpx.Client(timeout=TIMEOUT, follow_redirects=False)
        return self._http

    def _fetch_json(self, url):
        _https_url(url)
        try:
            response = self._client().get(url)
        except httpx.HTTPError:
            raise ProviderUnavailable("provider unreachable") from None
        if response.status_code != 200 or len(response.content) > MAX_DOCUMENT:
            raise ProviderUnavailable("provider response rejected")
        try:
            document = json.loads(response.content)
        except (ValueError, UnicodeDecodeError):
            raise ProviderUnavailable("provider document invalid") from None
        if not isinstance(document, dict):
            raise ProviderUnavailable("provider document invalid")
        return document

    def discovery(self):
        document = self._fetch_json(
            self.config.issuer + "/.well-known/openid-configuration"
        )
        if document.get("issuer") != self.config.issuer:
            raise ProviderUnavailable("issuer mismatch")
        for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            try:
                _https_url(document.get(field))
            except ProviderUnavailable:
                raise ProviderUnavailable("provider document incomplete") from None
        return document

    def jwks(self, discovery):
        return self._fetch_json(discovery["jwks_uri"])

    def authorization_url(self, *, redirect_uri, state, nonce, code_challenge, discovery=None):
        if discovery is None:
            discovery = self.discovery()
        params = [
            ("response_type", "code"),
            ("client_id", self.config.client_id),
            ("redirect_uri", redirect_uri),
            ("scope", self.config.scopes),
            ("state", state),
            ("nonce", nonce),
            ("code_challenge", code_challenge),
            ("code_challenge_method", "S256"),
        ]
        separator = "&" if "?" in discovery["authorization_endpoint"] else "?"
        return discovery["authorization_endpoint"] + separator + urlencode(params)

    def exchange(self, *, code, code_verifier, redirect_uri, discovery=None):
        if discovery is None:
            discovery = self.discovery()
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "client_id": self.config.client_id,
        }
        auth = None
        if self.config.client_secret:
            auth = (self.config.client_id, self.config.client_secret)
        try:
            response = self._client().post(
                discovery["token_endpoint"], data=form, auth=auth
            )
        except httpx.HTTPError:
            raise ProviderUnavailable("token endpoint unreachable") from None
        if response.status_code != 200 or len(response.content) > MAX_DOCUMENT:
            raise ProviderUnavailable("token response rejected")
        try:
            tokens = json.loads(response.content)
        except (ValueError, UnicodeDecodeError):
            raise ProviderUnavailable("token response invalid") from None
        if not isinstance(tokens, dict) or not isinstance(tokens.get("id_token"), str):
            raise ProviderMismatch("id_token missing")
        return tokens

    def _verify_signature(self, token, discovery):
        parts = token.split(".")
        if len(parts) != 3:
            raise ProviderMismatch("token format")
        header_b64, payload_b64, signature_b64 = parts
        try:
            header = json.loads(base64.urlsafe_b64decode(header_b64 + "=" * (-len(header_b64) % 4)))
            signature = base64.urlsafe_b64decode(signature_b64 + "=" * (-len(signature_b64) % 4))
        except (ValueError, binascii.Error, UnicodeDecodeError):
            raise ProviderMismatch("token encoding") from None
        if not isinstance(header, dict) or header.get("alg") not in ALLOWED_ALGS:
            # HS256/none would let an attacker mint tokens without the IdP key.
            raise ProviderMismatch("unsupported algorithm")
        if not isinstance(header.get("kid"), str) or header.get("crit"):
            raise ProviderMismatch("token header")
        keys = self.jwks(discovery).get("keys")
        if not isinstance(keys, list):
            raise ProviderMismatch("jwks invalid")
        selected = None
        for key in keys:
            if (
                isinstance(key, dict)
                and key.get("kty") == "RSA"
                and key.get("kid") == header["kid"]
                and key.get("use") in (None, "sig")
            ):
                selected = key
                break
        if selected is None:
            raise ProviderMismatch("signing key unknown")
        try:
            from cryptography.exceptions import InvalidSignature
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import padding, rsa

            numbers = rsa.RSAPublicNumbers(
                _b64url_int(selected["e"]), _b64url_int(selected["n"])
            )
            numbers.public_key().verify(
                signature,
                (header_b64 + "." + payload_b64).encode(),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (KeyError, ValueError, TypeError, InvalidSignature):
            raise ProviderMismatch("signature invalid") from None
        try:
            claims = json.loads(
                base64.urlsafe_b64decode(payload_b64 + "=" * (-len(payload_b64) % 4))
            )
        except (ValueError, binascii.Error, UnicodeDecodeError):
            raise ProviderMismatch("claims encoding") from None
        if not isinstance(claims, dict):
            raise ProviderMismatch("claims invalid")
        return claims

    def verify_id_token(self, token, *, nonce, discovery=None):
        if discovery is None:
            discovery = self.discovery()
        claims = self._verify_signature(token, discovery)
        now = self._clock()
        if claims.get("iss") != self.config.issuer:
            raise ProviderMismatch("issuer claim")
        aud = claims.get("aud")
        audiences = [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else []
        if self.config.client_id not in audiences:
            raise ProviderMismatch("audience claim")
        if "azp" in claims and claims.get("azp") != self.config.client_id:
            raise ProviderMismatch("authorized party")
        exp = claims.get("exp")
        if not isinstance(exp, (int, float)) or exp <= now - CLAIM_LEEWAY:
            raise ProviderMismatch("expiry claim")
        nbf = claims.get("nbf")
        if nbf is not None and (
            not isinstance(nbf, (int, float)) or nbf > now + CLAIM_LEEWAY
        ):
            raise ProviderMismatch("not-before claim")
        if claims.get("nonce") != nonce:
            raise ProviderMismatch("nonce claim")
        sub = claims.get("sub")
        if not isinstance(sub, str) or not 1 <= len(sub) <= 255:
            raise ProviderMismatch("subject claim")
        email = claims.get("email")
        if email is not None and (
            not isinstance(email, str) or not 1 <= len(email) <= 320
        ):
            raise ProviderMismatch("email claim")
        verified = claims.get("email_verified")
        if verified is not None and not isinstance(verified, bool):
            raise ProviderMismatch("email verification claim")
        return claims
