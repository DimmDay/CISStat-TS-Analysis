"""AUTH-04 exact HTTP/source map and AUTH-01 external-policy bindings."""

import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from fastapi import FastAPI
from fastapi.testclient import TestClient
from apps.api.routers.authentication import router

EXPECTED = {
    "GET:/v1/auth/csrf",
    "POST:/v1/auth/login",
    "GET:/v1/auth/me",
    "GET:/v1/auth/sessions",
    "POST:/v1/auth/logout",
    "POST:/v1/auth/sessions/revoke-all",
    "POST:/v1/auth/sessions/{session_id}/revoke",
    "POST:/v1/auth/password",
    "POST:/v1/auth/mfa/enroll",
    "POST:/v1/auth/mfa/verify",
    "POST:/v1/auth/step-up",
    "POST:/v1/auth/mfa/replace",
    "POST:/v1/auth/recovery",
    "POST:/v1/auth/recovery/rotate",
    # AUTH-19 external entry commands (same router, same envelope).
    "POST:/v1/auth/oidc/start",
    "POST:/v1/auth/oidc/callback",
    "POST:/v1/auth/email/start",
    "POST:/v1/auth/email/consume",

}


class RouteTests(unittest.TestCase):
    def app(self):
        app = FastAPI()
        app.include_router(router, prefix="/v1/auth")
        return app

    def test_actual_openapi_routes_equal_reviewed_inventory(self):
        doc = self.app().openapi()
        actual = {
            method.upper() + ":" + path
            for path, ops in doc["paths"].items()
            for method in ops
            if method in ("get", "post")
        }
        self.assertEqual(actual, EXPECTED)
        report = json.loads(
            (ROOT / "docs/auth00/inventory.json").read_text(encoding="utf-8")
        )
        recorded = {
            e["id"][4:]
            for e in report["entries"]
            if e["kind"] == "api" and e["path"].startswith("/v1/auth/")
            and not e["path"].startswith("/v1/auth/demo/")  # Separate AUTH-15 router, verified there.
        }
        self.assertEqual(actual, recorded)

    def test_capabilities_cannot_authorize_any_auth_operation(self):
        from apps.api.access_registry import REGISTRY, evaluate_entry
        from apps.api.plans import INTERNAL_CAPABILITIES

        for entry in EXPECTED:
            binding = REGISTRY.bindings["api:" + entry]
            self.assertFalse(binding.programmatic_api)
            self.assertEqual(
                evaluate_entry(INTERNAL_CAPABILITIES, "api:" + entry).code,
                "external_policy_required",
            )

    def test_password_schema_is_write_only_and_has_no_default_secret(self):
        schemas = self.app().openapi()["components"]["schemas"]
        prop = schemas["LoginBody"]["properties"]["password"]
        self.assertTrue(prop["writeOnly"])
        self.assertEqual(prop["format"], "password")
        self.assertNotIn("default", prop)

    def test_no_header_identity_or_key_is_a_personal_session(self):
        client = TestClient(self.app(), base_url="https://standalone.example")
        for headers in (
            {"X-Subject-ID": "admin", "X-Role": "admin"},
            {"X-API-Key": "not-browser-auth"},
        ):
            r = client.get("/v1/auth/me", headers=headers)
            self.assertEqual(r.status_code, 401, r.text)
            self.assertIn("no-store", r.headers["cache-control"])

    def test_same_origin_browser_csrf_bootstrap_without_origin(self):
        with patch.dict(
            os.environ,
            {
                "CISSTAT_AUTH_CSRF_KEY": "a" * 40,
                "CISSTAT_AUTH_ALLOWED_ORIGINS": "https://standalone.example",
            },
        ):
            client = TestClient(self.app(), base_url="https://standalone.example")
            r = client.get(
                "/v1/auth/csrf",
                headers={"Sec-Fetch-Site": "same-origin", "X-CSRF-Request": "1"},
            )
            self.assertEqual(r.status_code, 200, r.text)
            r = client.post(
                "/v1/auth/logout",
                headers={
                    "Sec-Fetch-Site": "same-origin",
                    "X-CSRF-Token": r.json()["csrf_token"],
                },
            )
            self.assertEqual(r.status_code, 403)

    def test_safe_validation_and_origin_errors_on_actual_asgi(self):
        with patch.dict(
            os.environ,
            {
                "CISSTAT_AUTH_CSRF_KEY": "a" * 40,
                "CISSTAT_AUTH_ALLOWED_ORIGINS": "https://standalone.example",
            },
        ):
            client = TestClient(self.app(), base_url="https://standalone.example")
            r = client.post(
                "/v1/auth/login",
                json={"password": {"untrusted": "AUTH04_SECRET_PAYLOAD"}},
            )
            self.assertEqual(r.status_code, 422)
            self.assertNotIn("AUTH04_SECRET_PAYLOAD", r.text)
            r = client.get("/v1/auth/csrf", headers={"Origin": "https://evil.example"})
            self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
