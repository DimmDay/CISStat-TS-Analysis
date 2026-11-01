"""RFC 6238 TOTP (SHA1/6 digits/30s), AEAD encrypted seeds; no default key."""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct


def totp(secret, step, *, digits=6):
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 15
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % (10**digits)).zfill(digits)


def verify_totp(secret, code, now, last_step):
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        return None
    step = int(now.timestamp()) // 30
    matches = [
        n
        for n in (step - 1, step, step + 1)
        if n >= 0 and n > last_step and hmac.compare_digest(totp(secret, n), code)
    ]
    return max(matches) if matches else None


def _keys():
    values = json.loads(os.environ["CISSTAT_AUTH_MFA_KEYS"])
    if not isinstance(values, dict) or not 1 <= len(values) <= 8:
        raise ValueError("invalid MFA keyring")
    keys = {
        kid: base64.b64decode(value, validate=True) for kid, value in values.items()
    }
    if any(
        not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", kid) or len(key) != 32
        for kid, key in keys.items()
    ):
        raise ValueError("invalid MFA keyring")
    return keys


def seal(secret, binding):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    kid = os.environ["CISSTAT_AUTH_MFA_ACTIVE_KEY"]
    key = _keys()[kid]
    nonce = secrets.token_bytes(12)
    data = nonce + AESGCM(key).encrypt(
        nonce, secret, ("cisstat.mfa/1:" + binding).encode()
    )
    return kid, base64.b64encode(data).decode()


def unseal(kid, ciphertext, binding):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    data = base64.b64decode(ciphertext, validate=True)
    return AESGCM(_keys()[kid]).decrypt(
        data[:12], data[12:], ("cisstat.mfa/1:" + binding).encode()
    )
