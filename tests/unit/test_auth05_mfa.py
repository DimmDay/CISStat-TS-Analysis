"""Cryptographic primitives and narrow challenge/transport contract."""

import base64
import os
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from cryptography.exceptions import InvalidTag

from apps.api.authentication.context import AuthHTTPException


class MfaPrimitiveTests(unittest.TestCase):
    def test_rfc6238_sha1_vectors_and_replay(self):
        from apps.api.authentication.mfa_crypto import totp, verify_totp

        secret = b"12345678901234567890"
        for stamp, expected in [
            (59, "94287082"),
            (1111111109, "07081804"),
            (20000000000, "65353130"),
        ]:
            self.assertEqual(totp(secret, stamp // 30, digits=8), expected)
        now = datetime.fromtimestamp(59, UTC)
        code = totp(secret, 1)
        self.assertEqual(verify_totp(secret, code, now, -1), 1)
        self.assertIsNone(verify_totp(secret, code, now, 1))
        self.assertIsNone(verify_totp(secret, "１２３４５６", now, -1))

    def test_encryption_authenticates_identity_factor_and_key(self):
        from apps.api.authentication.mfa_crypto import seal, unseal

        key = base64.b64encode(b"x" * 32).decode()
        with patch.dict(
            os.environ,
            {
                "CISSTAT_AUTH_MFA_KEYS": '{"k1":"' + key + '"}',
                "CISSTAT_AUTH_MFA_ACTIVE_KEY": "k1",
            },
        ):
            kid, encrypted = seal(b"secret factor seed", "binding-a")
            self.assertNotIn("secret", encrypted)
            self.assertEqual(unseal(kid, encrypted, "binding-a"), b"secret factor seed")
            with self.assertRaises(InvalidTag):
                unseal(kid, encrypted, "binding-b")
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(KeyError):
            seal(b"seed", "binding")

    def test_opaque_types_are_disjoint(self):
        from apps.api.authentication.mfa import challenge_digest
        from apps.api.authentication.sessions import token_digest

        token = "c1_" + "A" * 43
        self.assertEqual(len(challenge_digest(token)), 64)
        with self.assertRaises(AuthHTTPException):
            token_digest(token)
        with self.assertRaises(AuthHTTPException):
            challenge_digest("s1_" + "A" * 43)

    def test_cli_requires_operator_terminal_and_dsn_gate_never_skips(self):
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, str(root / "scripts/auth05/bootstrap.py"), "prepare"],
            input="",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("protected interactive", result.stderr)
        with patch.dict(os.environ, {}, clear=True):
            result = subprocess.run(
                [sys.executable, str(root / "scripts/auth05/verify_postgres.py")],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("No tests ran", result.stderr)
