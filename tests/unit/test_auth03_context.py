"""AUTH-03 negative/compatibility oracles; isolated ASGI, no scientific startup."""

from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
import os
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest
from apps.api.authentication.context import (
    VerifiedCredential,
    resolve_request_context,
    resolve_verified_context,
)
from apps.api.auth import get_current_principal, require_api_key
from apps.api.identity import resolve_request_subject
from apps.api.authentication.errors import AuthStoreUnavailable, AuthSchemaNotReady

KEY = "auth03-secret-key-never-disclose"
SUBJECT = "subj-1029384756abcdef"
TENANT = "tenant-auth03"


def request(headers=None, cookies="", app=None):
    values = [(k.lower().encode(), v.encode()) for k, v in (headers or [])]
    if cookies:
        values.append((b"cookie", cookies.encode()))
    return StarletteRequest(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": values,
            "app": app or FastAPI(),
            "query_string": b"",
        }
    )


class FakeAuthority:
    """Test-owned records/transaction, not a production authority fallback."""

    def __init__(self):
        self.subject, self.account, self.tenant = uuid4(), uuid4(), uuid4()
        self.identity = SimpleNamespace(
            subject_id=self.subject,
            status="active",
            platform_role="external_user",
            subject_version=3,
        )
        self.account_record = SimpleNamespace(
            account_id=self.account,
            tenant_id=self.tenant,
            status="active",
            plan="starter",
            entitlement_version=12,
        )
        self.member = SimpleNamespace(
            subject_id=self.subject,
            account_id=self.account,
            status="active",
            account_role="owner",
        )
        self.calls = 0
        self.failure = None

    @contextmanager
    def transaction(self, *, readonly=False):
        assert readonly
        self.calls += 1
        if self.failure:
            raise self.failure
        yield SimpleNamespace(
            identities=SimpleNamespace(get=lambda sid: self.identity),
            accounts=SimpleNamespace(
                get=lambda aid: self.account_record,
                memberships=lambda aid, **kw: [self.member] if self.member else [],
            ),
        )

    def evidence(self, **overrides):
        values = dict(
            subject_id=str(self.subject),
            account_id=str(self.account),
            credential_id="cred-auth03-verified",
            auth_method="auth_session",
            scopes=frozenset({"documentation.read"}),
            auth_session_id="as-auth03-safe",
        )
        values.update(overrides)
        return VerifiedCredential(**values)


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "CISSTAT_API_KEYS": f"{KEY}:external_user:starter:{SUBJECT}:{TENANT}:documentation.read",
                "CISSTAT_IDENTITY_MODE": "session_scoped",
            },
            clear=False,
        )
        self.env.start()
        self.binding = patch(
            "apps.api.authentication.context._research_binding", return_value=None
        )
        self.binding.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.binding.stop)

    def assert_error(self, function, status, code):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as caught:
            function()
        self.assertEqual(caught.exception.status_code, status)
        self.assertEqual(caught.exception.detail["code"], code)
        self.assertNotIn(KEY, repr(caught.exception.detail))

    def test_key_principal_and_subject_are_same_safe_projection(self):
        req = request([("x-api-key", KEY)])
        ctx = resolve_request_context(req)
        p = get_current_principal(request=req)
        s = resolve_request_subject(req)
        self.assertIs(resolve_request_context(req), ctx)
        self.assertEqual(p.principal_id, SUBJECT)
        self.assertEqual(p.subject_id, s.subject_id)
        self.assertEqual(p.tenant_id, s.tenant_id)
        self.assertEqual(ctx.credential_id[:5], "cred-")
        self.assertEqual(s.scopes, frozenset({"documentation.read"}))
        self.assertNotIn(KEY, repr(ctx) + p.model_dump_json() + repr(s))

    def test_invalid_key_never_falls_back_to_owned_cookie(self):
        with patch(
            "apps.api.authentication.context._research_binding",
            return_value=(SUBJECT, TENANT),
        ) as peek:
            self.assert_error(
                lambda: resolve_request_subject(
                    request([("x-api-key", "invalid")], "cisstat_session_id=restored")
                ),
                401,
                "invalid_credential",
            )
            peek.assert_not_called()

    def test_empty_present_key_is_not_absent(self):
        self.assert_error(
            lambda: resolve_request_context(request([("x-api-key", "")])),
            401,
            "invalid_credential",
        )

    def test_duplicate_key_headers_rejected(self):
        self.assert_error(
            lambda: resolve_request_context(
                request([("x-api-key", KEY), ("X-API-Key", KEY)])
            ),
            400,
            "auth_ambiguous",
        )

    def test_cookie_and_key_conflicting_server_owner_rejected(self):
        with patch(
            "apps.api.authentication.context._research_binding",
            return_value=("subj-0000000000000000", TENANT),
        ):
            self.assert_error(
                lambda: resolve_request_context(
                    request([("x-api-key", KEY)], "cisstat_session_id=owned")
                ),
                400,
                "auth_ambiguous",
            )

    def test_cookie_and_key_conflicting_tenant_rejected(self):
        with patch(
            "apps.api.authentication.context._research_binding",
            return_value=(SUBJECT, "tenant-other"),
        ):
            self.assert_error(
                lambda: resolve_request_context(
                    request([("x-api-key", KEY)], "cisstat_session_id=owned")
                ),
                400,
                "auth_ambiguous",
            )

    def test_matching_research_pointer_cannot_add_scopes_or_role(self):
        with patch(
            "apps.api.authentication.context._research_binding",
            return_value=(SUBJECT, TENANT),
        ):
            ctx = resolve_request_context(
                request([("x-api-key", KEY)], "cisstat_session_id=owned")
            )
        self.assertEqual(ctx.scopes, frozenset({"documentation.read"}))
        self.assertEqual(ctx.role.value, "external_user")

    def test_unknown_pointer_does_not_replace_verified_key(self):
        self.assertEqual(
            resolve_request_subject(
                request([("x-api-key", KEY)], "cisstat_session_id=unknown")
            ).subject_id,
            SUBJECT,
        )

    def test_restored_cookie_continuity_without_role(self):
        with patch(
            "apps.api.authentication.context._research_binding",
            return_value=(SUBJECT, TENANT),
        ):
            ctx = resolve_request_context(
                request(cookies="cisstat_session_id=new-cookie")
            )
        self.assertEqual(ctx.subject_id, SUBJECT)
        self.assertEqual(ctx.tenant_id, TENANT)
        self.assertEqual(ctx.auth_method, "session_surrogate")
        self.assertFalse(ctx.is_authenticated)
        self.assertIsNone(ctx.role)

    def test_surrogate_is_not_key_protected_principal(self):
        self.assert_error(
            lambda: get_current_principal(
                request=request(cookies="cisstat_session_id=pointer")
            ),
            401,
            "authentication_required",
        )

    def test_missing_key_is_401_on_actual_dependency(self):
        app = FastAPI()

        @app.get("/protected")
        def protected(p=Depends(get_current_principal)):
            return p

        r = TestClient(app).get("/protected")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"]["code"], "authentication_required")

    def test_unconfigured_registry_is_503_without_config_disclosure(self):
        with patch.dict(os.environ, {"CISSTAT_API_KEYS": ""}):
            self.assert_error(
                lambda: get_current_principal(x_api_key=KEY),
                503,
                "auth_authority_unavailable",
            )

    def test_scope_and_request_cache_do_not_cross_requests(self):
        first = resolve_request_context(request([("x-api-key", KEY)]))
        with patch.dict(
            os.environ,
            {"CISSTAT_API_KEYS": f"{KEY}:external_user:demo:{SUBJECT}:{TENANT}:"},
        ):
            second = resolve_request_context(request([("x-api-key", KEY)]))
        self.assertEqual(first.plan.value, "starter")
        self.assertEqual(second.plan.value, "demo")
        self.assertFalse(second.scopes)

    def test_context_is_immutable(self):
        ctx = resolve_request_context(request([("x-api-key", KEY)]))
        with self.assertRaises(FrozenInstanceError):
            ctx.subject_id = "changed"

    def test_scoped_mode_never_uses_research_surrogate(self):
        with patch.dict(os.environ, {"CISSTAT_IDENTITY_MODE": "scoped"}):
            ctx = resolve_request_context(request(cookies="cisstat_session_id=owned"))
            self.assertFalse(ctx.subject_id)
            self.assert_error(
                lambda: resolve_request_context(request([("x-api-key", KEY)])),
                401,
                "durable_binding_required",
            )

    def test_unknown_auth_cookie_does_not_fall_back_to_research(self):
        self.assert_error(
            lambda: resolve_request_context(
                request(
                    cookies="__Host-cisstat_auth=unverified; cisstat_session_id=owned"
                )
            ),
            401,
            "invalid_credential",
        )

    def test_client_identity_account_role_mfa_headers_ignored(self):
        req = request(
            [
                ("x-api-key", KEY),
                ("x-subject-id", "admin"),
                ("x-tenant-id", "tenant-evil"),
                ("x-account-id", str(uuid4())),
                ("x-role", "admin"),
                ("x-mfa", "true"),
            ]
        )
        ctx = resolve_request_context(req)
        self.assertEqual(ctx.subject_id, SUBJECT)
        self.assertEqual(ctx.tenant_id, TENANT)
        self.assertIsNone(ctx.account_id)
        self.assertIsNone(ctx.mfa_verified_at)

    def test_require_api_key_returns_safe_string_and_revocation_rechecked(self):
        p = get_current_principal(x_api_key=KEY)
        self.assertEqual(require_api_key(principal=p), SUBJECT)
        with patch.dict(os.environ, {"CISSTAT_API_KEYS": "replacement:admin:"}):
            self.assert_error(
                lambda: get_current_principal(x_api_key=KEY), 401, "invalid_credential"
            )

    def test_explicit_subject_rotation_is_stable(self):
        from apps.api.auth import resolve_principal_for_key

        with patch.dict(
            os.environ,
            {
                "CISSTAT_API_KEYS": f"{KEY}:admin::{SUBJECT}:{TENANT},rotated:admin::{SUBJECT}:{TENANT}"
            },
        ):
            self.assertEqual(
                resolve_principal_for_key(KEY).principal_id,
                resolve_principal_for_key("rotated").principal_id,
            )

    def test_invalid_registry_subject_tenant_and_scopes_fail_closed(self):
        from apps.api.auth import resolve_principal_for_key

        for suffix in (
            "admin::bad subject:tenant-ok:",
            "admin::subj-invalid:tenant-ok:",
            "admin::safe:invalid-tenant:",
            "admin::safe:tenant-ok:invented.scope",
        ):
            with (
                self.subTest(suffix=suffix),
                patch.dict(os.environ, {"CISSTAT_API_KEYS": KEY + ":" + suffix}),
            ):
                self.assertIsNone(resolve_principal_for_key(KEY))

    def test_real_subject_projection_keeps_uniform_object_denial(self):
        from apps.api.identity import authorize_run_access

        ctx = resolve_request_context(request([("x-api-key", KEY)]))
        run = SimpleNamespace(
            run_id="RUN-AUTH0300",
            owner_subject="subj-0000000000000000",
            tenant_id=TENANT,
            ownership="bound",
            session_id="other",
        )
        self.assertFalse(
            authorize_run_access(run, ctx.as_subject(), action="read").allowed
        )


class DurableContextTests(unittest.TestCase):
    assert_error = ContextTests.assert_error

    def setUp(self):
        ContextTests.setUp(self)
        self.authority = FakeAuthority()

    def test_authority_data_is_current_and_owner_not_admin(self):
        a = self.authority
        evidence = a.evidence()
        one = resolve_verified_context(evidence, store=a, request_id="rid-auth03")
        self.assertEqual(one.account_id, str(a.account))
        self.assertEqual(one.tenant_id, str(a.tenant))
        self.assertEqual(one.membership_role, "owner")
        self.assertEqual(one.entitlement_version, 12)
        self.assertFalse(one.platform_permissions)
        a.account_record.entitlement_version = 13
        two = resolve_verified_context(evidence, store=a, request_id="next")
        self.assertEqual(two.entitlement_version, 13)
        self.assertEqual(a.calls, 2)

    def test_suspended_missing_identity_denied(self):
        a = self.authority
        for value in (None, SimpleNamespace(status="suspended")):
            a.identity = value
            self.assert_error(
                lambda: resolve_verified_context(a.evidence(), store=a),
                401,
                "invalid_credential",
            )

    def test_missing_suspended_closed_account_denied(self):
        a = self.authority
        for value in (
            None,
            SimpleNamespace(status="suspended"),
            SimpleNamespace(status="closed"),
        ):
            a.account_record = value
            self.assert_error(
                lambda: resolve_verified_context(a.evidence(), store=a),
                403,
                "account_access_denied",
            )

    def test_revoked_missing_membership_denied(self):
        a = self.authority
        for value in (None, SimpleNamespace(subject_id=a.subject, status="revoked")):
            a.member = value
            self.assert_error(
                lambda: resolve_verified_context(a.evidence(), store=a),
                403,
                "account_access_denied",
            )

    def test_missing_binding_never_auto_selects_account(self):
        a = self.authority
        self.assert_error(
            lambda: resolve_verified_context(a.evidence(account_id=None), store=a),
            403,
            "account_required",
        )
        self.assertEqual(a.calls, 0)

    def test_db_and_schema_outages_have_safe_503(self):
        a = self.authority
        for error in (AuthStoreUnavailable(), AuthSchemaNotReady()):
            a.failure = error
            self.assert_error(
                lambda: resolve_verified_context(a.evidence(), store=a),
                503,
                "auth_authority_unavailable",
            )

    def test_falsey_server_verifier_never_falls_back_to_env(self):
        app = FastAPI()

        class Broken:
            def __bool__(self):
                return False

            def api_key(self, key):
                raise RuntimeError("unavailable")

        app.state.auth_credential_verifier = Broken()
        self.assert_error(
            lambda: resolve_request_context(request([("x-api-key", KEY)], app=app)),
            503,
            "auth_authority_unavailable",
        )

    def test_verifier_http_error_cannot_disclose_secrets(self):
        from fastapi import HTTPException

        app = FastAPI()

        class Leaky:
            def api_key(self, key):
                raise HTTPException(status_code=503, detail="DSN " + KEY)

        app.state.auth_credential_verifier = Leaky()
        self.assert_error(
            lambda: resolve_request_context(request([("x-api-key", KEY)], app=app)),
            503,
            "auth_authority_unavailable",
        )

    def test_untrusted_verifier_failure_is_503_without_secret(self):
        app = FastAPI()

        class Broken:
            def api_key(self, key):
                raise RuntimeError("DSN " + KEY)

        app.state.auth_credential_verifier = Broken()
        self.assert_error(
            lambda: resolve_request_context(request([("x-api-key", KEY)], app=app)),
            503,
            "auth_authority_unavailable",
        )

    def test_verified_browser_and_key_must_match_subject_and_account(self):
        a = self.authority
        for other in (
            a.evidence(subject_id=str(uuid4())),
            a.evidence(account_id=str(uuid4())),
        ):
            app = FastAPI()
            app.state.auth_access_store = a
            app.state.auth_credential_verifier = SimpleNamespace(
                api_key=lambda key: a.evidence(auth_method="api_key"),
                session=lambda req: other,
            )
            self.assert_error(
                lambda: resolve_request_context(request([("x-api-key", KEY)], app=app)),
                400,
                "auth_ambiguous",
            )

    def test_matching_credentials_keep_key_scopes_ceiling(self):
        a = self.authority
        app = FastAPI()
        app.state.auth_access_store = a
        app.state.auth_credential_verifier = SimpleNamespace(
            api_key=lambda key: a.evidence(auth_method="api_key", scopes=frozenset()),
            session=lambda req: a.evidence(scopes=frozenset({"policy.admin"})),
        )
        ctx = resolve_request_context(request([("x-api-key", KEY)], app=app))
        self.assertFalse(ctx.scopes)
        self.assertEqual(ctx.auth_method, "api_key")
        self.assertIsNone(ctx.mfa_verified_at)

    def test_uuid_env_binding_reads_db_role_tenant_not_env(self):
        a = self.authority
        app = FastAPI()
        app.state.auth_access_store = a
        with patch.dict(
            os.environ,
            {
                "CISSTAT_API_KEYS": f"{KEY}:admin::{a.subject}:tenant-fake:documentation.read:{a.account}",
                "CISSTAT_IDENTITY_MODE": "scoped",
            },
        ):
            ctx = resolve_request_context(request([("x-api-key", KEY)], app=app))
        self.assertEqual(ctx.role.value, "external_user")
        self.assertEqual(ctx.tenant_id, str(a.tenant))
        self.assertEqual(ctx.plan.value, "starter")


if __name__ == "__main__":
    unittest.main()
