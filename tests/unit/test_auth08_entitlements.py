"""AUTH-08: Account authority, expiry, role separation and real me projection."""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from apps.api.authentication.context import resolve_verified_context
from apps.api.plans import AuthenticatedPrincipal, Role
from tests.unit.test_auth03_context import FakeAuthority

NOW = datetime(2026, 11, 7, 12, tzinfo=UTC)


class AccountEntitlementTests(unittest.TestCase):
    def setUp(self):
        self.store = FakeAuthority()
        self.store.account_record.account_type = "mono"
        self.store.account_record.plan_expires_at = None

    def context(self):
        return resolve_verified_context(self.store.evidence(), store=self.store)

    def test_admin_and_staff_do_not_upgrade_account_plan(self):
        for role in ("admin", "internal_analyst", "external_user"):
            with self.subTest(role=role):
                self.store.identity.platform_role = role
                caps = self.context().as_principal().capabilities
                self.assertFalse(caps.can_tune_models)
                self.assertFalse(caps.can_train_models)
                self.assertEqual(caps.max_dataset_rows, 50_000)

    def test_internal_is_account_entitlement_not_admin_permission(self):
        self.store.account_record.plan = "internal"
        ctx = self.context()
        self.assertTrue(ctx.as_principal().capabilities.can_tune_models)
        self.assertEqual(ctx.account_plan, "internal")
        self.assertFalse(ctx.platform_permissions)
        self.assertEqual(ctx.membership_role, "owner")

    def test_downgrade_next_resolution_and_no_shared_mutable_caps(self):
        self.store.account_record.plan = "professional"
        a = self.context().as_principal()
        self.assertTrue(a.capabilities.can_tune_models)
        copied = a.capabilities
        copied.can_tune_models = False
        self.assertTrue(a.capabilities.can_tune_models)
        self.store.account_record.plan = "demo"
        self.store.account_record.entitlement_version += 1
        b = self.context().as_principal()
        self.assertFalse(b.capabilities.can_tune_models)
        self.assertEqual(len(b.capabilities.restricted_stage_ids), 4)
        self.assertGreater(b.entitlement_version, a.entitlement_version)

    def test_exact_expiry_and_unknown_plan_fail_closed(self):
        from apps.api.accounts.entitlements import account_is_active

        a = self.store.account_record
        a.plan_expires_at = NOW
        self.assertTrue(account_is_active(a, now=NOW - timedelta(microseconds=1)))
        self.assertFalse(account_is_active(a, now=NOW))
        self.assertFalse(account_is_active(a, now=NOW + timedelta(microseconds=1)))
        a.plan_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        with self.assertRaises(HTTPException) as caught:
            self.context()
        self.assertEqual(caught.exception.detail["code"], "account_expired")
        a.plan_expires_at = None
        a.plan = "unknown"
        with self.assertRaises((ValueError, HTTPException)):
            self.context()

    def test_bound_principal_without_effective_projection_never_role_falls_back(self):
        p = AuthenticatedPrincipal(
            principal_id="safe",
            role=Role.ADMIN,
            account_id="bound",
            entitlement_version=1,
        )
        with self.assertRaises(ValueError):
            _ = p.capabilities

    def test_legacy_adapter_is_explicitly_preserved(self):
        p = AuthenticatedPrincipal(principal_id="legacy", role=Role.ADMIN)
        self.assertTrue(p.capabilities.can_tune_models)

    def test_real_me_returns_account_effective_dto_without_secrets(self):
        from apps.api.routers.authentication import router

        ctx = self.context()
        # The DTO must use real UUID refs, not client assertions.
        from dataclasses import replace
        from uuid import uuid4

        ctx = replace(ctx, auth_session_id=str(uuid4()), auth_time=NOW)
        app = FastAPI()
        app.include_router(router, prefix="/v1/auth")
        with patch(
            "apps.api.routers.authentication.resolve_request_context", return_value=ctx
        ):
            r = TestClient(app).get("/v1/auth/me")
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(data["account_plan"], "starter")
        self.assertEqual(data["account_type"], "mono")
        self.assertEqual(data["entitlement_version"], 12)
        self.assertIsNone(data["plan_expires_at"])
        self.assertFalse(data["capabilities"]["can_tune_models"])
        self.assertNotIn("credential_id", data)

    def test_patch_input_is_strict_and_cannot_edit_seats_or_owner(self):
        from pydantic import ValidationError

        from apps.api.accounts.lifecycle import AccountChange

        for body in (
            {},
            {"seats": 100},
            {"plan": "invalid"},
            {"plan": None},
            {"account_type": "mono"},
            {"plan_expires_at": "2026-11-07T00:00:00"},
        ):
            with self.subTest(body=body), self.assertRaises(ValidationError):
                AccountChange.model_validate(body)
        self.assertEqual(
            AccountChange(plan_expires_at=None).model_fields_set, {"plan_expires_at"}
        )

    def test_no_dsn_runner_and_noninteractive_writer_fail(self):
        import os
        import subprocess
        import sys

        env = dict(os.environ)
        env.pop("CISSTAT_AUTH_TEST_DSN", None)
        r = subprocess.run(
            [sys.executable, "scripts/auth08/verify_postgres.py"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        r = subprocess.run(
            [
                sys.executable,
                "scripts/auth08/manage_account.py",
                "apply",
                str(self.store.account),
                "--expected-version",
                "12",
                "--change",
                '{"plan":"demo"}',
                "--reason",
                "test",
            ],
            input="",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("interactive", r.stderr)

    def test_lifecycle_actions_are_mandatory_and_operator_cli_in_image(self):
        from pathlib import Path

        from apps.api.security_audit import AUDIT_REQUIREMENTS

        for action in ("auth_account_changed", "auth_membership_changed"):
            self.assertEqual(AUDIT_REQUIREMENTS[action], "mandatory")
        dockerfile = Path("apps/api/Dockerfile").read_text(encoding="utf-8")
        self.assertIn(
            "COPY scripts/auth08/manage_account.py ./scripts/auth08/manage_account.py",
            dockerfile,
        )


if __name__ == "__main__":
    unittest.main()
