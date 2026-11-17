"""External login changes credentials; a prior research pointer must not follow."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.authentication.context import auth_error
from apps.api.routers import authentication as routes


class ExternalEntryPointerTests(unittest.TestCase):
    def test_only_issued_session_clears_pointer_for_all_external_login_paths(self):
        cases = [
            ("email", {"email": "reader@example.test", "code": "01234567"}),
            ("email", {"token": "e1_" + "x" * 43}),
            ("email", {"selection": "k1_" + "x" * 43, "account_id": "11111111-1111-4111-8111-111111111111"}),
            ("oidc", {"code": "test-authorization-code", "state": "o1_" + "x" * 43}),
            ("oidc", {"selection": "k1_" + "x" * 43, "account_id": "11111111-1111-4111-8111-111111111111"}),
        ]
        for kind, body in cases:
            for outcome in ("issued", "selection", "bound", "denied"):
                with self.subTest(kind=kind, body_keys=list(body), outcome=outcome):
                    self._check(kind, body, outcome)

    def _check(self, kind, body, outcome):
        issued = SimpleNamespace(token="s1_" + "n" * 43, session={"account_id": "new-account"})

        def result(*args, **kwargs):
            if outcome == "denied":
                auth_error(401, "invalid_credential")
            return issued if outcome == "issued" else {"status": "account_required" if outcome == "selection" else "email_bound"}

        service = SimpleNamespace(consume=result, callback=result, select_login=result)
        app = FastAPI()
        app.include_router(routes.router, prefix="/v1/auth")
        origin = "https://entry.example.test"
        with (
            patch.dict(os.environ, {"CISSTAT_AUTH_ALLOWED_ORIGINS": origin, "CISSTAT_AUTH_CSRF_KEY": "test-only-" + "c" * 40}),
            patch.object(routes, "email_service" if kind == "email" else "oidc_service", return_value=service),
            TestClient(app, base_url=origin) as client,
        ):
            client.cookies.set("cisstat_session_id", "previous-research", domain="entry.example.test", path="/")
            proof = client.get("/v1/auth/csrf", headers={"Origin": origin}).json()["csrf_token"]
            response = client.post(
                "/v1/auth/" + kind + ("/consume" if kind == "email" else "/callback"),
                json=body, headers={"Origin": origin, "X-CSRF-Token": proof},
            )
            self.assertEqual(response.status_code, 401 if outcome == "denied" else 200, response.text)
            if outcome == "issued":
                self.assertIsNone(client.cookies.get("cisstat_session_id"))
                self.assertEqual(client.cookies.get("__Host-cisstat_auth"), issued.token)
                cookies = response.headers.get_list("set-cookie")
                self.assertTrue(any("cisstat_session_id=" in c and "Max-Age=0" in c and "Path=/" in c for c in cookies))
                self.assertTrue(any("__Host-cisstat_auth=" in c and "Secure" in c and "HttpOnly" in c for c in cookies))
            else:
                self.assertEqual(client.cookies.get("cisstat_session_id"), "previous-research")
                self.assertFalse(response.headers.get_list("set-cookie"))
