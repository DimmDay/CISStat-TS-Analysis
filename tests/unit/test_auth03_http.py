"""Actual ASGI dependencies/legacy routes; no fake authentication HTTP endpoints."""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from apps.api.auth import get_current_principal
from apps.api.identity import resolve_request_subject, subject_pseudonym

KEY = "auth03-http-secret-sentinel"
SUBJECT = "subj-0011001100110011"


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "CISSTAT_API_KEYS": f"{KEY}:admin::{SUBJECT}:tenant-http:logs.read+audit.read+logs.export",
                "CISSTAT_IDENTITY_MODE": "session_scoped",
            },
            clear=False,
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        from apps.api.session_store import MemorySessionStore

        self.store = MemorySessionStore()
        binding = patch(
            "apps.api.session_store.peek_session_store", return_value=self.store
        )
        binding.start()
        self.addCleanup(binding.stop)
        self.app = FastAPI()

        @self.app.get("/key")
        def key(p=Depends(get_current_principal)):
            return p.model_dump(mode="json")

        @self.app.get("/both")
        def both(request: Request, p=Depends(get_current_principal)):
            subject = resolve_request_subject(request)
            return {
                "principal_id": p.principal_id,
                "subject_id": subject.subject_id,
                "scopes": sorted(subject.scopes),
            }

        @self.app.get("/subject")
        def subject(request: Request):
            s = resolve_request_subject(request)
            return {"subject_id": s.subject_id, "via": s.via}

        self.client = TestClient(self.app)

    def test_error_request_id_matches_telemetry_response_header(self):
        from apps.api.telemetry import TelemetryContextMiddleware

        self.app.add_middleware(TelemetryContextMiddleware)
        r = self.client.get(
            "/subject",
            headers={"X-API-Key": "bad", "X-Request-ID": "auth03-correlation-001"},
        )
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.json()["detail"]["request_id"], r.headers["x-request-id"])

    def test_both_adapters_see_same_safe_identity_in_asgi(self):
        r = self.client.get("/both", headers={"X-API-Key": KEY})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["principal_id"], r.json()["subject_id"])
        self.assertNotIn(KEY, r.text)

    def test_invalid_empty_key_and_unsupported_bearer_rejected_even_with_cookie(self):
        self.client.cookies.set("cisstat_session_id", "pointer")
        for headers in (
            {"X-API-Key": "bad"},
            {"X-API-Key": ""},
            {"Authorization": "Bearer invalid"},
        ):
            r = self.client.get("/subject", headers=headers)
            self.assertEqual(r.status_code, 401, r.text)

    def test_research_cookie_legacy_continuity_and_lookup_outage(self):
        session = self.store.get_or_create("restore-pointer")
        session.owner_subject = SUBJECT
        session.tenant_id = "tenant-http"
        self.client.cookies.set("cisstat_session_id", "restore-pointer")
        r = self.client.get("/subject")
        self.assertEqual(r.json(), {"subject_id": SUBJECT, "via": "session_surrogate"})
        with patch.object(
            self.store, "get", side_effect=RuntimeError("redis secret " + KEY)
        ):
            r = self.client.get("/subject")
        self.assertEqual(r.status_code, 503)
        self.assertNotIn(KEY, r.text)

    def test_legacy_cookie_surrogate_stays_stable_when_unbound(self):
        self.client.cookies.set("cisstat_session_id", "unknown-pointer")
        self.assertEqual(
            self.client.get("/subject").json()["subject_id"],
            subject_pseudonym("unknown-pointer"),
        )
        self.assertEqual(self.client.get("/key").status_code, 401)

    def test_duplicate_key_detected_by_real_header_stack(self):
        r = self.client.get(
            "/subject", headers=[("x-api-key", KEY), ("x-api-key", "other")]
        )
        self.assertEqual(r.status_code, 400, r.text)

    def test_actual_logs_manual_adapter_uses_request_context(self):
        from apps.api.routers.logs import router

        self.app.include_router(router, prefix="/v1/logs")
        session = self.store.get_or_create("foreign-pointer")
        session.owner_subject = "subj-ffffffffffffffff"
        session.tenant_id = "tenant-http"
        self.client.cookies.set("cisstat_session_id", "foreign-pointer")
        r = self.client.get("/v1/logs/access", headers={"X-API-Key": KEY})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertEqual(r.json()["detail"]["code"], "auth_ambiguous")
        self.client.cookies.clear()
        self.assertEqual(
            self.client.get("/v1/logs/access", headers={"X-API-Key": KEY}).status_code,
            200,
        )
        self.assertEqual(self.client.get("/v1/logs/access").status_code, 401)

    def test_model_train_response_secret_contract_from_actual_source(self):
        # Execute the unchanged actual handler definition without importing the
        # unrelated heavy scientific model catalogue in this hermetic gate.
        import ast

        tree = ast.parse(
            (ROOT / "apps/api/routers/models.py").read_text(encoding="utf-8")
        )
        node = next(
            n
            for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "train_model"
        )
        node.decorator_list = []
        namespace = {
            "AuthenticatedPrincipal": object,
            "Depends": Depends,
            "get_current_principal": get_current_principal,
        }
        exec(
            compile(
                ast.Module(body=[node], type_ignores=[]), "<actual train_model>", "exec"
            ),
            namespace,
        )
        p = get_current_principal(x_api_key=KEY)
        payload = namespace["train_model"](principal=p)
        self.assertEqual(payload["principal_id"], SUBJECT)
        self.assertNotIn(KEY, str(payload))


if __name__ == "__main__":
    unittest.main()
