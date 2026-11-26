"""Fresh-upload Path A on real required-mode PostgreSQL/AuthSession/AUTH-13.

The background loop is disabled. One case explicitly runs the real AUTH-13
worker/isolated child with a renderer HTTP protocol double and verifies byte
delivery/slot release. This does not certify Chromium pixels or production UDS.
Export builders, registries and authorization/storage are not mocked.
"""
import os
import unittest
from unittest.mock import patch

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

    def test_missing_service_then_provisioned_render_download_and_slot_release(self):
        """Only the renderer HTTP bytes are a protocol double; managed lifecycle is real."""
        import base64
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from apps.api.workers.bootstrap import ensure_service_credential, generate_key
        from apps.api.workers.authority import WorkerAuthority
        from apps.api.document_render_worker import DocumentRenderWorker
        from apps.api.document_jobs import DocumentDeliveryService
        from apps.api.png_renderer_client import PngRendererClient

        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5N0AAAAASUVORK5CYII=")

        class Renderer(BaseHTTPRequestHandler):
            def do_POST(inner):
                inner.rfile.read(int(inner.headers["Content-Length"]))
                inner.send_response(200)
                inner.send_header("Content-Type", "image/png")
                inner.send_header("Content-Length", str(len(png)))
                inner.end_headers()
                inner.wfile.write(png)
            def log_message(inner, *args):
                pass

        with self.dep.http() as client:
            _, trace = self.prepare(client)
            with patch.dict(os.environ, {"CISSTAT_WORKER_KEY": ""}):
                refused = self.export(client, trace, "upload.overview.tech_table")
                self.assertEqual(refused.status_code, 503, refused.text)
                self.assertEqual(refused.json()["detail"]["code"], "worker_service_unavailable")
            self.assertEqual(self.dep.rows("document_jobs"), [])
            self.assertEqual(self.dep.rows("auth_reservations"), [])
            key = generate_key()  # synthetic test credential, never logged
            provision = ensure_service_credential(self.dep.store, key)
            self.assertEqual(provision["state"], "registered")
            with patch.dict(os.environ, {"CISSTAT_WORKER_KEY": key}):
                queued = self.export(client, trace, "upload.overview.tech_table")
                self.assertEqual(queued.status_code, 202, queued.text)
                server = ThreadingHTTPServer(("127.0.0.1", 0), Renderer)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    worker = DocumentRenderWorker(
                        service=DocumentDeliveryService.create_default(),
                        worker_authority=WorkerAuthority(self.dep.store, key),
                        png_renderer=PngRendererClient(base_url=f"http://127.0.0.1:{server.server_port}", enabled=True),
                    )
                    report = worker.run_once()
                    self.assertEqual(report["ready"], 1, (report, worker.status()))
                finally:
                    server.shutdown(); server.server_close(); thread.join(5)
                self.assertEqual(self.dep.rows("auth_worker_jobs")[0]["state"], "completed")
                self.assertTrue(all(r["reserved"] == 0 for r in self.dep.rows("auth_resource_budgets") if r["metric"] == "concurrency"))
                rendition = self.dep.rows("document_renditions")[0]
                download = client.get(f'/v1/documentation/renditions/{rendition["rendition_id"]}/content')
                self.assertEqual(download.status_code, 200, download.text)
                self.assertEqual(download.content, png)
                second = self.export(client, trace, "upload.quality.teaser")
                self.assertEqual(second.status_code, 202, second.text)
                self.cancel(client, second.json()["job"]["job_id"])

    def test_full_slot_is_explicit_429_and_no_second_job(self):
        with self.dep.http() as client:
            _, trace = self.prepare(client)
            first = self.export(client, trace, "upload.overview.tech_table")
            self.assertEqual(first.status_code, 202, first.text)
            second = self.export(client, trace, "upload.quality.teaser")
            self.assertEqual(second.status_code, 429, second.text)
            self.assertEqual(second.json()["detail"]["code"], "concurrency_exceeded")
            self.assertEqual(len(self.dep.rows("document_jobs")), 1)
            self.assertEqual(len(self.dep.rows("auth_reservations")), 1)
            self.cancel(client, first.json()["job"]["job_id"])
