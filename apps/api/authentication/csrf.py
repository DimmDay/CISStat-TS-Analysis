"""Host-only signed double-submit proof bound to the current opaque auth SID."""

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from urllib.parse import urlsplit
from .context import auth_error

AUTH_COOKIE = "__Host-cisstat_auth"
CSRF_COOKIE = "__Host-cisstat_csrf"
TTL = 600


def _cookie(request, name):
    headers = request.headers
    values = (
        headers.getlist("cookie")
        if hasattr(headers, "getlist")
        else [headers.get("cookie", "")]
    )
    hits = []
    for header in values:
        if len(header) > 8192:
            auth_error(401, "invalid_credential")
        for part in header.split(";"):
            key, sep, value = part.strip().partition("=")
            if key == name and sep:
                hits.append(value)
    if len(hits) > 1:
        auth_error(401, "invalid_credential")
    return hits[0] if hits else None


def auth_cookie(request):
    return _cookie(request, AUTH_COOKIE)


def _key():
    value = os.environ.get("CISSTAT_AUTH_CSRF_KEY", "").encode()
    if len(value) < 32:
        auth_error(503, "auth_authority_unavailable")
    return value


def configured_origins():
    raw = os.environ.get("CISSTAT_AUTH_ALLOWED_ORIGINS") or os.environ.get(
        "ALLOWED_ORIGINS", ""
    )
    origins = {s.strip().rstrip("/") for s in raw.split(",") if s.strip()}
    for origin in origins:
        p = urlsplit(origin)
        if (
            p.scheme != "https"
            or not p.netloc
            or "*" in origin
            or p.username
            or p.password
            or p.path
            or p.query
            or p.fragment
        ):
            auth_error(503, "auth_authority_unavailable")
    return origins


def trusted_origin(request, *, bootstrap=False):
    origins = configured_origins()
    if not origins:
        auth_error(503, "auth_authority_unavailable")
    headers = request.headers
    values = (
        headers.getlist("origin")
        if hasattr(headers, "getlist")
        else [headers.get("origin")]
    )
    if (not values or values == [None]) and bootstrap:
        # Same-origin GET fetch need not carry Origin. A non-simple header
        # plus browser-controlled Fetch Metadata protects this read-only proof
        # bootstrap; unsafe commands still require an exact Origin.
        if (
            getattr(request, "method", None) == "GET"
            and headers.get("x-csrf-request") == "1"
            and headers.get("sec-fetch-site") == "same-origin"
        ):
            return None
    if len(values) != 1 or values[0] not in origins:
        auth_error(403, "csrf_invalid")
    if headers.get("sec-fetch-site") not in (None, "same-origin", "same-site", "none"):
        auth_error(403, "csrf_invalid")
    return values[0]


def _mac(body, request):
    binding = hashlib.sha256((auth_cookie(request) or "").encode()).hexdigest()
    return hmac.new(
        _key(), ("csrf/1:" + binding + ":" + body).encode(), hashlib.sha256
    ).hexdigest()


def issue_csrf(request):
    trusted_origin(request, bootstrap=True)
    existing = _cookie(request, CSRF_COOKIE)
    if existing and _valid(existing, request):
        return existing
    body = "c1." + str(int(time.time())) + "." + secrets.token_urlsafe(24)
    return body + "." + _mac(body, request)


def check_csrf(request):
    trusted_origin(request)
    headers = request.headers
    values = (
        headers.getlist("x-csrf-token")
        if hasattr(headers, "getlist")
        else [headers.get("x-csrf-token")]
    )
    token = values[0] if len(values) == 1 else None
    cookie = _cookie(request, CSRF_COOKIE)
    if (
        not token
        or not cookie
        or len(token) > 180
        or not token.isascii()
        or not cookie.isascii()
        or not hmac.compare_digest(token, cookie)
    ):
        auth_error(403, "csrf_invalid")
    if not _valid(token, request):
        auth_error(403, "csrf_invalid")


def _valid(token, request):
    if len(token) > 180 or not re.fullmatch(
        r"c1\.[0-9]{1,12}\.[A-Za-z0-9_-]{32}\.[0-9a-f]{64}", token
    ):
        return False
    body, signature = token.rsplit(".", 1)
    age = int(time.time()) - int(token.split(".")[1])
    return 0 <= age < TTL and hmac.compare_digest(signature, _mac(body, request))
