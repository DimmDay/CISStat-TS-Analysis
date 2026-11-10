"""AUTH-19 exact HTTP/source map: four new POST routes on the shared auth router."""

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.testclient import TestClient

ADDED = {
    "POST:/v1/auth/oidc/start",
    "POST:/v1/auth/oidc/callback",
    "POST:/v1/auth/email/start",
    "POST:/v1/auth/email/consume",
}


class RouteTests(unittest.TestCase):
    def app(self):
        from apps.api.routers.authentication import router

        app = FastAPI()
        app.include_router(router, prefix="/v1/auth")
        return app

    def test_new_routes_present_and_post_only(self):
        doc = self.app().openapi()
        methods = {}
        for path, ops in doc["paths"].items():
            for method in ops:
                methods[method.upper() + ":" + path] = True
        for route in ADDED:
            self.assertIn(route, methods)
        # Mail scanners must not be able to consume anything by GET.
        for path in ("/v1/auth/oidc/callback", "/v1/auth/email/consume"):
            self.assertNotIn("GET:" + path, methods)

    def test_csrf_flags_declared(self):
        report = json.loads(
            (ROOT / "docs/auth00/inventory.json").read_text(encoding="utf-8")
        )
        recorded = {
            e["id"][4:]
            for e in report["entries"]
            if e["kind"] == "api"
            and (e["path"].startswith("/v1/auth/oidc/") or e["path"].startswith("/v1/auth/email/"))
        }
        self.assertEqual(recorded, ADDED)


if __name__ == "__main__":
    unittest.main()
