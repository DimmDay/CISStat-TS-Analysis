"""Fresh-upload Path A on real required-mode PostgreSQL/AuthSession/AUTH-13.

The worker is disabled: these tests prove real managed admission, not PNG pixels.
No export builder/registry/auth/renderer response is mocked.
"""
import os
import unittest

from tests.integration import test_personal_demo_http as fixture

Deployment = fixture.Deployment


def reset_document_stores():
    from apps.api.document_jobs import reset_document_registry_for_testing
    from apps.api.document_lifecycle import reset_document_lifecycle_registry_for_testing
    from apps.api.report_snapshot import reset_snapshot_registry_for_testing
    from apps.api.artifact_store import reset_artifact_registry_for_testing, reset_artifact_object_store_for_testing
    from apps.api.routers.documentation import reset_documentation_service_for_testing
    from apps.api.doc_profiles import reset_org_profile_registry_for_testing
    from apps.api.visual_producers import reset_visual_response_cache_for_testing
    from apps.api.admin_logs import reset_support_grant_registry_for_testing
    from apps.api.monitoring import reset_monitoring_registry_for_testing
    from apps.api.security_audit import reset_audit_for_testing
    from apps.api.telemetry import reset_telemetry_for_testing
    for reset in (reset_document_registry_for_testing, reset_document_lifecycle_registry_for_testing,
                  reset_snapshot_registry_for_testing, reset_artifact_registry_for_testing,
                  reset_artifact_object_store_for_testing, reset_documentation_service_for_testing,
                  reset_org_profile_registry_for_testing, reset_visual_response_cache_for_testing,
                  reset_support_grant_registry_for_testing, reset_monitoring_registry_for_testing,
                  reset_audit_for_testing, reset_telemetry_for_testing):
        reset()


@unittest.skipUnless(os.environ.get("CISSTAT_AUTH_TEST_DSN"), "disposable PostgreSQL required")
class FreshUploadPngTests(unittest.TestCase):
    def setUp(self):
        reset_document_stores()
        self.fixture = fixture.PersonalDemoHTTPTests("test_verified_email_starts_research_without_operator_provisioning")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.addCleanup(reset_document_stores)
        self.dep = self.fixture.dep
        self.dep.personal_user("pgv-png-owner")

    def prepare(self, client):
        Deployment.login(client, "pgv-png-owner")
        uploaded = Deployment.upload(client)
        response = Deployment.post(client, "/v1/session/date-column", json={"column": "date", "confirmed": True})
        self.assertEqual(response.status_code, 200, response.text)
        trace = client.get("/v1/progress/trace").json()
        return uploaded, trace

    def export(self, client, trace, view, svg=None):
        payload = {"view_id": view, "expected_context_id": trace["context_id"]}
        if svg:
            payload["screen_svg"] = svg
        return Deployment.post(client, f'/v1/documentation/runs/{trace["run_id"]}/visuals', json=payload)

    def cancel(self, client, job_id):
        response = Deployment.post(client, f"/v1/documentation/jobs/{job_id}/cancel")
        self.assertEqual(response.status_code, 200, response.text)

    def test_fresh_upload_first_export_no_dataset_reopen_and_idempotent_retry(self):
        with self.dep.http() as client:
            _, trace = self.prepare(client)
            results = [r for r in self.dep.rows("research_artifacts") if r["kind"] == "visual_result"]
            self.assertEqual({r["refs"]["view_id"] for r in results}, {
                "upload.overview.preview", "upload.overview.tech_table", "upload.quality.teaser",
            })
            self.assertEqual({r["data_revision"] for r in results}, {0})
            # No GET /dataset or other producer refresh before the very first export.
            first = self.export(client, trace, "upload.overview.tech_table")
            self.assertEqual(first.status_code, 202, first.text)
            second = self.export(client, trace, "upload.overview.tech_table")
            self.assertEqual(second.status_code, 202, second.text)
            self.assertEqual(first.json()["job"]["job_id"], second.json()["job"]["job_id"])
            self.assertEqual(first.json()["snapshot_artifact_id"], second.json()["snapshot_artifact_id"])
            self.assertEqual(len(self.dep.rows("auth_worker_jobs")), 1)
            self.assertEqual(len(self.dep.rows("document_jobs")), 1)
            self.assertEqual(len([r for r in self.dep.rows("research_artifacts") if r["kind"] == "visual_result"]), 3)
            self.cancel(client, first.json()["job"]["job_id"])
            run_id = trace["run_id"]
            # Authenticated access to an unrelated account cannot export the known ID.
            self.dep.personal_user("pgv-png-foreign")
            Deployment.login(client, "pgv-png-foreign")
            denied = Deployment.post(client, f"/v1/documentation/runs/{run_id}/visuals",
                                      json={"view_id": "upload.overview.tech_table"})
            self.assertEqual(denied.status_code, 404, denied.text)
            self.assertEqual(len(self.dep.rows("document_jobs")), 1)

    def test_zero_revision_exports_across_three_modules(self):
        with self.dep.http() as client:
            _, trace = self.prepare(client)
            cases = [
                ("upload.chart.series", "/v1/session/dataset/timeseries?column=value&date_column=date",
                 '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="300"><path d="M0 200 L600 0"/></svg>'),
                ("eda.descriptive.stats", "/v1/session/dataset/stats", None),
                ("preprocessing.missing.overview", "/v1/session/dataset/missing-profile", None),
            ]
            for view, endpoint, svg in cases:
                with self.subTest(view=view):
                    source = client.get(endpoint)
                    self.assertEqual(source.status_code, 200, source.text)
                    self.assertTrue(source.headers.get("X-Visual-Result-Ref"))
                    queued = self.export(client, trace, view, svg)
                    self.assertEqual(queued.status_code, 202, queued.text)
                    self.assertEqual(queued.json()["job"]["state"], "queued")
                    self.cancel(client, queued.json()["job"]["job_id"])
            runs = self.dep.rows("research_runs")
            self.assertEqual(next(r["data_revision"] for r in runs if r["run_id"] == trace["run_id"]), 0)
