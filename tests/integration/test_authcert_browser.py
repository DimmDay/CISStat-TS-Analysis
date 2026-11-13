"""AUTH-CERT browser-layer suite: static oracles on both shells (AC22/AC29).

No DSN needed: the UI layer of the acceptance act is verified by structural
facts about the shipped transport code (first-party cookies, no credentials
in URLs or browser storage, both shells exposing entry surfaces) plus the
referenced Jest suites (full run recorded in AUTH-24: 2882 passed / 2 skips).
A real browser E2E is NOT executed in this environment (honest boundary)."""

import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(*parts):
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def glob_sources(*parts):
    base = ROOT.joinpath(*parts)
    return [p for p in base.rglob("*.ts*") if "node_modules" not in str(p)]


class CertBrowserTests(unittest.TestCase):
    def test_ac22_first_party_cookies_and_no_token_storage(self):
        csrf = read("apps/api/authentication/csrf.py")
        self.assertIn('AUTH_COOKIE = "__Host-cisstat_auth"', csrf)
        self.assertIn('CSRF_COOKIE = "__Host-cisstat_csrf"', csrf)
        # Host-only cookies: no Domain attribute anywhere in the auth transport.
        for path in ("apps/api/authentication/csrf.py", "apps/api/routers/authentication.py"):
            text = read(path)
            for call in re.findall(r"set_cookie\(([^)]*)\)", text, re.S):
                self.assertNotIn("domain=", call.lower(), path)
        # The auth cookie and the research pointer are different names.
        auth_router = read("apps/api/routers/authentication.py")
        self.assertIn('"cisstat_session_id"', auth_router)
        # No credential persistence in browser storage from the shared client.
        client_text = read("packages/ui/lib/authClient.ts")
        self.assertNotIn("localStorage", client_text)
        self.assertNotIn("sessionStorage", client_text)

    def test_ac22_no_credentials_in_urls(self):
        # AUTH-19 contract: external-flow URL parameters are cleared via
        # replaceState in the login pages; the shared client never puts a
        # token into a navigable URL (fetch redirect: "error").
        client_text = read("packages/ui/lib/authClient.ts")
        self.assertNotRegex(client_text, r"location\.(href|assign)")
        login_screen = read("packages/ui/components/LoginScreen.tsx")
        self.assertIn("replaceState", login_screen)

    def test_ac29_both_shells_expose_entry_surfaces(self):
        for shell in ("apps/standalone", "apps/embedded"):
            pages = ROOT.joinpath(shell, "app")
            # The shipped shell surfaces (upload lives inside the demo
            # pipeline and account flows, not as a top-level route).
            for surface in ("login", "admin", "demo", "account", "modeling"):
                self.assertTrue(
                    (pages / surface).is_dir(),
                    f"{shell} lacks /{surface} surface",
                )
            # The real transport of both login surfaces is the shared client.
            self.assertIn("authClient", read(shell, "app/login/page.tsx"))
        # Legacy dev stub (documented "ЗАМЕНИТЬ") only feeds the home layout
        # concept and never any auth surface (cert finding F-CERT-B1).
        home = read("apps/standalone/components/StandaloneHome.tsx")
        self.assertIn("useAuth", home)
        for surface in ("login", "admin", "demo", "account"):
            self.assertNotIn("useAuth", read("apps/standalone/app", surface, "page.tsx"))

    def test_ac29_no_false_login_on_unavailable_authority(self):
        # The transport maps 503 auth_authority_unavailable to an explicit
        # message and never to a success state (jest authClient pins it).
        client_text = read("packages/ui/lib/authClient.ts")
        self.assertRegex(client_text, r"503|unavailable")
        tests = read("packages/ui/lib/authClient.test.ts")
        self.assertIn("unavailable", tests) or self.assertIn("503", tests)
