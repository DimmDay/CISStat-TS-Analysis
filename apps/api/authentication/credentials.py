"""Bounded Argon2id password processing; no default user/password or auth fallback."""

import os
from pathlib import Path
import secrets
from threading import BoundedSemaphore
from argon2 import PasswordHasher, Type, extract_parameters
from argon2.exceptions import VerificationError, InvalidHashError
from .context import auth_error

PASSWORD_POLICY_VERSION = "auth.password/1"

_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1, type=Type.ID)
_HASH_SLOTS = BoundedSemaphore(4)


def normalize_login(login):
    import re

    value = login.strip().lower() if isinstance(login, str) else ""
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.@+\-]{2,127}", value):
        auth_error(401, "invalid_credential")
    return value


def validate_password(password):
    try:
        length = len(password.encode("utf-8")) if isinstance(password, str) else 0
    except UnicodeError:
        auth_error(422, "password_policy")
    if not isinstance(password, str) or len(password) < 15 or length > 1024:
        auth_error(422, "password_policy")
    paths = [Path(__file__).with_name("password_blocklist.txt")]
    if os.environ.get("CISSTAT_AUTH_PASSWORD_BLOCKLIST"):
        paths.append(Path(os.environ["CISSTAT_AUTH_PASSWORD_BLOCKLIST"]))
    try:
        for path in paths:
            with path.open(encoding="utf-8") as source:
                for line in source:
                    value = line.strip()
                    if (
                        value
                        and not value.startswith("#")
                        and password.strip().casefold() == value.casefold()
                    ):
                        auth_error(422, "password_policy")
    except OSError:
        auth_error(503, "auth_authority_unavailable")


class PasswordCodec:
    def __init__(self):
        self._dummy = None

    def hash(self, password):
        validate_password(password)
        return self._run(lambda: _HASHER.hash(password))

    @staticmethod
    def _run(work):
        if not _HASH_SLOTS.acquire(blocking=False):
            auth_error(429, "too_many_attempts")
        try:
            return work()
        finally:
            _HASH_SLOTS.release()

    def verify(self, encoded, password):
        def work():
            if self._dummy is None:
                self._dummy = _HASHER.hash(secrets.token_urlsafe(32))
            valid = False
            if isinstance(encoded, str) and len(encoded) <= 512:
                try:
                    p = extract_parameters(encoded)
                    valid = (
                        p.type == Type.ID
                        and 8 <= p.memory_cost <= 262144
                        and 1 <= p.time_cost <= 10
                        and 1 <= p.parallelism <= 4
                    )
                except (ValueError, InvalidHashError):
                    pass
            candidate = encoded if valid else self._dummy
            try:
                matched = _HASHER.verify(candidate, password)
            except (VerificationError, InvalidHashError, ValueError, TypeError):
                matched = False
            return bool(valid and matched)

        try:
            if not isinstance(password, str) or len(password.encode("utf-8")) > 1024:
                return False
        except UnicodeError:
            return False
        return self._run(work)

    def needs_rehash(self, encoded):
        return _HASHER.check_needs_rehash(encoded)
