import os
import unittest
from unittest.mock import patch

from tests.unit import test_auth04_password_transport as previous


class Auth06Contracts(unittest.TestCase):
    setUp = previous.TransportTests.setUp
    proof = previous.TransportTests.proof

    def test_csrf_reuse_is_bound_to_sid(self):
        from apps.api.authentication.csrf import issue_csrf

        token = self.proof(auth="s1_" + "A" * 43)
        cookies = (
            "__Host-cisstat_auth=s1_" + ("A" * 43) + "; __Host-cisstat_csrf=" + token
        )
        r = previous.req("GET", {"Origin": "https://standalone.example"}, cookies)
        self.assertEqual(issue_csrf(r), token)
        other = previous.req(
            "GET",
            {"Origin": "https://standalone.example"},
            cookies.replace("s1_" + "A" * 43, "s1_" + "B" * 43),
        )
        self.assertNotEqual(issue_csrf(other), token)

    def test_cors_exact_allowlist(self):
        from apps.api.authentication.csrf import configured_origins

        self.assertEqual(len(configured_origins()), 2)
        with patch.dict(
            os.environ, {"CISSTAT_AUTH_ALLOWED_ORIGINS": "https://*.vercel.app"}
        ), self.assertRaises(previous.HTTPException):
            configured_origins()

    def test_me_contract_is_generated(self):
        from apps.api.access_registry import contract_openapi

        schemas = contract_openapi()["components"]["schemas"]
        self.assertTrue("AuthMeResponse" in schemas)
        self.assertNotIn("token", schemas["AuthMeResponse"]["properties"])
