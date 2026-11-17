"""Full-app HTTP E2E: email OTP + browser cookie jar + real UI demo CSVs.

Only SMTP transport is controlled. PostgreSQL, proof, session, ownership,
parsing, trace, quota and lifetime are real. This is not a browser click test.
"""

import json
import os
from pathlib import Path
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests.integration import test_personal_demo_http as fixture


@unittest.skipUnless(os.environ.get("CISSTAT_AUTH_TEST_DSN"), "disposable PostgreSQL required")
class EmailUploadE2ETests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.PersonalDemoHTTPTests("test_verified_email_starts_research_without_operator_provisioning")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.dep = self.fixture.dep
        # A lifespan warms process-wide registries. Do not leave a registry
        # pointing at this test's dropped database for later HTTP suites.
        from apps.api.document_jobs import reset_document_registry_for_testing
        from apps.api.document_lifecycle import reset_document_lifecycle_registry_for_testing
        from apps.api.report_snapshot import reset_snapshot_registry_for_testing
        from apps.api.artifact_store import reset_artifact_registry_for_testing

        for reset in (
            reset_document_registry_for_testing,
            reset_document_lifecycle_registry_for_testing,
            reset_snapshot_registry_for_testing,
            reset_artifact_registry_for_testing,
        ):
            reset()
            self.addCleanup(reset)
        root = Path(__file__).resolve().parents[2]
        self.demos = json.loads(subprocess.check_output(
            ["node", str(root / "scripts/email_upload_fix/demo_files.js")], cwd=root, text=True, encoding="utf-8"
        ))
        self.assertEqual(len(self.demos), 4)
        self.letters = []
        self.env = patch.dict(os.environ, {
            "CISSTAT_PERSONAL_DEMO_ENABLED": "1",
            "CISSTAT_AUTH_EMAIL_KEY": "test-only-email-key-" + "x" * 40,
            "CISSTAT_DEMO_ADMIN_NOTIFICATIONS_ENABLED": "0",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        delivery = patch("apps.api.authentication.providers.email_delivery.SmtpEmailDelivery.from_env", return_value=SimpleNamespace(send=lambda to, subject, body: self.letters.append(body)))
        delivery.start()
        self.addCleanup(delivery.stop)

    def login(self, client, email, *, link=False):
        response = fixture.Deployment.post(client, "/v1/auth/email/start", json={"email": email, "purpose": "trial_login"})
        self.assertEqual(response.status_code, 200, response.text)
        letter = self.letters[-1]
        payload = ({"token": letter.split("email_challenge=")[1].split("&")[0]} if link else {"email": email, "code": letter.splitlines()[0].rsplit(" ", 1)[-1]})
        response = fixture.Deployment.post(client, "/v1/auth/email/consume", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "authenticated")
        me = client.get("/v1/auth/me", headers={"Origin": fixture.STANDALONE})
        self.assertEqual(me.status_code, 200, me.text)
        return me.json()

    def upload(self, client, demo):
        response = client.post("/v1/internal/upload", files={"file": (demo["name"], demo["csv"].encode(), "text/csv")}, headers={"Origin": fixture.STANDALONE, "X-CSRF-Token": fixture.Deployment.csrf(client)})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["name"], demo["name"])
        self.assertGreater(response.json()["rows"], 0)
        return response.json()

    def assert_workspace_ready(self, client, *, empty):
        current = client.get("/v1/session/current", headers={"Origin": fixture.STANDALONE})
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(current.json()["has_active_dataset"], not empty)
        trace = client.get("/v1/progress/trace", headers={"Origin": fixture.STANDALONE})
        self.assertEqual(trace.status_code, 200, trace.text)
        if not empty:
            dataset = client.get("/v1/session/dataset", headers={"Origin": fixture.STANDALONE})
            self.assertEqual(dataset.status_code, 200, dataset.text)
            self.assertTrue(trace.json()["run_id"])

    def test_otp_after_previous_user_research_loads_all_four_demo_cards(self):
        self.dep.personal_user("previous-user")
        with self.dep.http() as client:
            fixture.Deployment.login(client, "previous-user")
            fixture.Deployment.upload(client)
            old_pointer = client.cookies.get("cisstat_session_id")
            old_session = self.dep.rows("analysis_sessions")
            old_runs = self.dep.rows("research_runs")
            # Auth cookie lasts 8h, the research pointer 30d: an anonymous
            # login screen can legitimately have the previous user's pointer.
            client.cookies.delete("__Host-cisstat_auth", domain="datasetup.ru", path="/")
            self.assertEqual(client.get("/v1/auth/me", headers={"Origin": fixture.STANDALONE}).status_code, 401)
            self.login(client, "new-reader@example.test")
            # This assertion reproduces the reported visible failure first.
            self.assert_workspace_ready(client, empty=True)
            self.assertNotEqual(client.cookies.get("cisstat_session_id"), old_pointer)
            for demo in self.demos:
                with self.subTest(demo=demo["id"]):
                    self.upload(client, demo)
                    self.assert_workspace_ready(client, empty=False)
            self.assertEqual(len(self.dep.rows("auth_personal_trials")), 1)
            self.assertEqual(len(self.dep.rows("auth_analysis_claims")), 4)
            # Successful new login never migrates/deletes the previous owner's data.
            self.assertIn(old_session[0], self.dep.rows("analysis_sessions"))
            self.assertIn(old_runs[0], self.dep.rows("research_runs"))
            # Knowing the old pointer still gives exactly the original uniform 404.
            new_pointer = client.cookies.get("cisstat_session_id")
            client.cookies.set("cisstat_session_id", old_pointer, domain="datasetup.ru", path="/")
            denied = client.post("/v1/internal/upload", content=b"not-multipart", headers={"Origin": fixture.STANDALONE, "X-CSRF-Token": fixture.Deployment.csrf(client), "Content-Type": "multipart/form-data; boundary=broken"})
            self.assertEqual(denied.status_code, 404, denied.text)
            self.assertEqual(denied.json()["detail"]["code"], "scientific_object_not_found")
            self.assertEqual(len(self.dep.rows("auth_analysis_claims")), 4)
            client.cookies.set("cisstat_session_id", new_pointer, domain="datasetup.ru", path="/")
            self.assert_workspace_ready(client, empty=False)

    def test_clean_otp_and_repeat_magic_link_do_not_refill_trial(self):
        with self.dep.http() as client:
            first = self.login(client, "returning-reader@example.test")
            self.assert_workspace_ready(client, empty=True)
            self.upload(client, self.demos[0])
            trials = self.dep.rows("auth_personal_trials")
            lots = self.dep.rows("auth_wallet_lots")
            second = self.login(client, "returning-reader@example.test", link=True)
            self.assertEqual(second["account_id"], first["account_id"])
            self.assert_workspace_ready(client, empty=True)
            self.assertEqual(self.dep.rows("auth_personal_trials"), trials)
            self.assertEqual(self.dep.rows("auth_wallet_lots"), lots)
            self.upload(client, self.demos[0])
            self.assert_workspace_ready(client, empty=False)
            self.assertEqual(len(self.dep.rows("auth_analysis_claims")), 2)
