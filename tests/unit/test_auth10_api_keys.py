"""AUTH-10 codec, DTO and admission contracts; no live DB required."""

import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from apps.api.authentication.api_key_contract import (
    API_SCOPES,
    IssueKeyBody,
    RotateKeyBody,
)
from apps.api.authentication.api_key_policy import admit_request
from apps.api.authentication.api_keys import (
    IssuedKey,
    key_mode,
    new_secret,
    secret_digest,
)
from apps.api.authentication.context import VerifiedCredential


class APIKeyUnitTests(unittest.TestCase):
    def test_random_hash_only_repr(self):
        a, b = new_secret(), new_secret()
        self.assertNotEqual(a, b)
        self.assertEqual(len(a), 47)
        self.assertTrue(a.startswith("csk_"))
        self.assertEqual(len(secret_digest(a)), 64)
        self.assertNotIn(a, secret_digest(a))
        self.assertNotIn(a, repr(IssuedKey(a, {})))

    def test_malformed_token_denied(self):
        for value in (
            "",
            None,
            "a" * 10000,
            "csk_" + "a" * 42,
            "csk_" + "a" * 43 + "\n",
        ):
            with self.assertRaises(HTTPException):
                secret_digest(value)

    def test_strict_issue_body_scope_ceiling(self):
        self.assertEqual(len(API_SCOPES), 4)
        for payload in (
            {"label": "k", "expires_in_days": True, "scopes": ["api.read"]},
            {"label": "k", "expires_in_days": 1, "scopes": ["*"]},
            {"label": "k", "expires_in_days": 1, "scopes": ["policy.admin"]},
            {
                "label": "k",
                "expires_in_days": 1,
                "scopes": ["api.read"],
                "account_id": str(uuid4()),
            },
        ):
            with self.assertRaises(ValidationError):
                IssueKeyBody(**payload)

    def test_rotate_version_strict(self):
        for value in (True, 0, -1, "1"):
            with self.assertRaises(ValidationError):
                RotateKeyBody(expected_version=value)

    def test_required_mode_cannot_enable_env(self):
        with (
            patch.dict(
                os.environ,
                {
                    "CISSTAT_STORAGE_MODE": "required",
                    "CISSTAT_API_KEY_MODE": "legacy_dev",
                },
            ),
            self.assertRaises(HTTPException),
        ):
            key_mode()
        with patch.dict(
            os.environ, {"CISSTAT_STORAGE_MODE": "required", "CISSTAT_API_KEY_MODE": ""}
        ):
            self.assertEqual(key_mode(), "durable")

    def request(self, path, method="GET"):
        return Request(
            {
                "type": "http",
                "method": method,
                "path": path,
                "query_string": b"",
                "headers": [],
            }
        )

    def evidence(self, scopes):
        return VerifiedCredential(
            str(uuid4()), str(uuid4()), "api_key", str(uuid4()), frozenset(scopes)
        )

    def test_protected_malformed_key_rejected_before_store_creation(self):
        from apps.api.authentication.sessions import SessionCredentialVerifier

        with (
            patch.dict(
                os.environ,
                {"CISSTAT_STORAGE_MODE": "required", "CISSTAT_API_KEY_MODE": "durable"},
            ),
            patch("apps.api.authentication.api_keys.service_for_request") as service,
        ):
            with self.assertRaises(HTTPException) as error:
                SessionCredentialVerifier(
                    self.request("/v1/public/rules/templates")
                ).api_key("old-env-secret")
            self.assertEqual(error.exception.status_code, 401)
            service.assert_not_called()

    def test_public_scope_gate(self):
        from apps.api.access_registry import REGISTRY
        from apps.api.authentication.api_key_policy import OPERATION_SCOPES

        programmatic = {
            b.operation_id for b in REGISTRY.bindings.values() if b.programmatic_api
        }
        self.assertEqual(
            set(OPERATION_SCOPES), programmatic - {"validation.rules.update_rules"}
        )
        admit_request(
            self.request("/v1/public/rules/templates"), self.evidence({"api.read"})
        )
        with self.assertRaises(HTTPException):
            admit_request(
                self.request("/v1/public/passport", "POST"), self.evidence({"api.read"})
            )

    def test_no_admin_internal_or_global_rules_delegation(self):
        for path, method in (
            ("/v1/internal/passport", "POST"),
            ("/v1/admin/progress", "GET"),
            ("/v1/public/rules/update", "PATCH"),
        ):
            with self.assertRaises(HTTPException):
                admit_request(self.request(path, method), self.evidence(API_SCOPES))

    def test_scope_enum_matches_api_contract(self):
        from apps.api.identity import ALL_SCOPES, Scope

        self.assertTrue(API_SCOPES <= ALL_SCOPES)
        self.assertEqual({s.value for s in Scope}, ALL_SCOPES)

    def test_cli_and_native_runner_require_authority(self):
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "scripts/auth10/manage_keys.py",
                "issue-service",
                "--subject-id",
                str(uuid4()),
                "--account-id",
                str(uuid4()),
                "--label",
                "test",
                "--scopes",
                "api.read",
                "--expires-in-days",
                "1",
                "--reason",
                "test",
            ],
            capture_output=True,
            text=True,
            input="",
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("interactive", result.stderr)
        env = dict(os.environ)
        env.pop("CISSTAT_AUTH_TEST_DSN", None)
        result = subprocess.run(
            [sys.executable, "scripts/auth10/verify_postgres.py"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("disposable", result.stderr)

    def test_secret_redaction(self):
        from apps.api.telemetry import redact_text

        token = new_secret()
        self.assertNotIn(token, redact_text("key " + token))
        from apps.api.storage_diagnostics import safe_error

        self.assertNotIn(token, safe_error("failure " + token))


if __name__ == "__main__":
    unittest.main()
