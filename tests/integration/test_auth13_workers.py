"""AUTH-13 actual PostgreSQL, credentials, object ownership, and execution races."""

import os
import unittest
import operator
from datetime import UTC, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from dataclasses import replace
from fastapi import HTTPException
from apps.api.workers.authority import WorkerAuthority
from apps.api.workers.services import WorkerServices
from apps.api.workers.migrations import apply_migration
from apps.api.workers.process import run_bounded
from apps.api.billing.contract import Admission, Cost, digest_payload
from apps.api.billing.policy import BudgetPolicy
from apps.api.authentication.context import RequestContext
from tests.integration import test_auth09_objects as previous


@unittest.skipUnless(
    os.environ.get("CISSTAT_AUTH_TEST_DSN"), "disposable PostgreSQL required"
)
class WorkerSQLTests(unittest.TestCase):
    cleanup = previous.OwnershipSQLTests.cleanup
    client = previous.OwnershipSQLTests.client
    post = previous.OwnershipSQLTests.post
    demo = previous.OwnershipSQLTests.demo

    def setUp(self):
        previous.OwnershipSQLTests.setUp(self)
        with self.access.transaction() as tx:
            apply_migration(tx.connection)
            tx.connection.execute("CREATE TABLE worker_probe(value TEXT NOT NULL)")
        # These real per-schema stores avoid legacy readiness probes hardcoded
        # to public.*; no fake storage/authority participates in the scenarios.
        from unittest.mock import patch
        from pathlib import Path
        from apps.api import (
            artifact_store,
            report_snapshot,
            document_jobs,
            doc_profiles,
        )
        from apps.api.routers import documentation

        stores = [
            (
                artifact_store,
                "_registry",
                artifact_store.PostgresArtifactRegistry(self.dsn),
            ),
            (
                artifact_store,
                "_object_store",
                artifact_store.ArtifactObjectStore(Path(self.temp.name) / "artifacts"),
            ),
            (
                report_snapshot,
                "_registry",
                report_snapshot.PostgresSnapshotRegistry(self.dsn),
            ),
            (
                document_jobs,
                "_registry",
                document_jobs.PostgresDocumentRegistry(self.dsn),
            ),
            (
                doc_profiles,
                "_ORG_PROFILE_REGISTRY",
                doc_profiles.PostgresOrgProfileRegistry(self.dsn),
            ),
            (documentation, "_SERVICE", None),
            (doc_profiles, "_ORG_PROFILE_SERVICE", None),
        ]
        for module, name, value in stores:
            if hasattr(value, "_schema_ready"):
                value._schema_ready = True
            replacement = patch.object(module, name, value)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.owner = self.client()
        self.token = self.owner.cookies.get("__Host-cisstat_auth")
        e = self.auth.verify(self.token)
        with self.access.transaction(readonly=True) as tx:
            a = tx.accounts.get(e.account_id)
            u = tx.identities.get(e.subject_id)
        self.ctx = RequestContext(
            subject_id=e.subject_id,
            account_id=e.account_id,
            tenant_id=str(a.tenant_id),
            auth_method=e.auth_method,
            credential_id=e.credential_id,
            auth_session_id=e.auth_session_id,
            subject_version=u.subject_version,
            entitlement_version=a.entitlement_version,
            request_id="worker-native",
        )
        self.s, self.r = self.demo(self.owner)
        self.key = WorkerServices(self.access).issue(
            kinds=["modeling", "render", "delivery"], reason="native test"
        )
        from unittest.mock import patch
        from pathlib import Path

        env = patch.dict(
            os.environ,
            {
                "CISSTAT_WORKER_KEY": self.key,
                "CISSTAT_WORKER_PROOF_DIR": str(Path(self.temp.name) / "worker-proofs"),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        self.work = WorkerAuthority(self.access, self.key)
        self.policy = BudgetPolicy(self.access)
        self.policy.create_scope("account", account_id=a.account_id, reason="test")
        self.policy.set_budget(
            a.account_id, "concurrency", limit_units=10, reason="test"
        )
        self.policy.set_budget(a.account_id, "cu", limit_units=100, reason="test")

    def request(self, key="one", cu=10):
        return Admission(
            entry_id="api:GET:/v1/internal/rules/templates",
            resource_kind="run",
            resource_id=self.r.run_id,
            idempotency_key=key,
            payload={"task": "native"},
            cost=Cost(micro_cu=cu, version="native-only/1"),
            deadline=datetime.now(UTC) + timedelta(minutes=10),
            slots=1,
        )

    def queued(self, key="one", kind="modeling"):
        return self.work.admit(
            self.ctx,
            self.request(key),
            kind=kind,
            external_id=key,
            run_id=self.r.run_id,
            session_id=self.s.session_id,
            context_id=self.s.current_context_id() if kind == "modeling" else None,
            descriptor={"test": True},
        )

    def proof(self, claim):
        _, proof = run_bounded(operator.add, (1, 1), timeout=5)
        return self.work.seal_stop(claim, proof)

    def rows(self, table):
        with self.access.transaction(readonly=True) as tx:
            return tx.connection.execute("SELECT * FROM " + table).fetchall()

    def budget(self, metric):
        return next(
            x for x in self.rows("auth_resource_budgets") if x["metric"] == metric
        )

    def error(self, fn, status, code=None):
        with self.assertRaises(HTTPException) as e:
            fn()
        self.assertEqual(e.exception.status_code, status, e.exception.detail)
        if code:
            self.assertEqual(e.exception.detail["code"], code)

    def publish(self, claim, proof, *, value="one", final=True, cu=0):
        return self.work.publish(
            claim,
            proof,
            publisher=lambda c: c.execute(
                "INSERT INTO worker_probe(value) VALUES (%s)", (value,)
            ),
            result_digest=digest_payload(value),
            final=final,
            actual_cu=cu,
        )

    def test_queue_logout_start_no_result_or_refund(self):
        q = self.queued()
        self.auth.logout(self.token)
        self.error(lambda: self.work.claim(q["worker_id"]), 401)
        self.assertEqual(self.rows("worker_probe"), [])
        self.assertEqual(self.budget("cu")["reserved"], 10)

    def test_queued_revoke_reconciles_once_without_execution(self):
        q = self.queued()
        self.auth.logout(self.token)
        self.assertEqual(self.work.reconcile()["pending_expired"], 1)
        postings = len(self.rows("auth_usage_postings"))
        self.assertEqual(self.work.reconcile()["pending_expired"], 0)
        self.assertEqual(len(self.rows("auth_usage_postings")), postings)
        self.assertEqual(self.budget("cu")["reserved"], 0)
        self.error(lambda: self.work.claim(q["worker_id"]), 401)

    def test_uncertain_job_does_not_starve_expired_queue_in_bounded_batch(self):
        import time

        first = self.queued("unknown")
        claim = self.work.claim(first["worker_id"])
        self.work.uncertain(first["worker_id"], expected_fence=claim.fence)
        req = self.request("expired").model_copy(
            update={"deadline": datetime.now(UTC) + timedelta(seconds=0.15)}
        )
        self.work.admit(
            self.ctx,
            req,
            kind="render",
            external_id="expired",
            run_id=self.r.run_id,
            descriptor={},
        )
        time.sleep(0.2)
        result = self.work.reconcile(limit=1)
        self.assertEqual(result["pending_expired"], 1, result)
        self.assertEqual(self.budget("cu")["reserved"], 10)

    def test_render_service_reconciles_its_kind_without_modeling_authority(self):
        import time

        self.queued("modeling-still-live")
        req = self.request("render-expired").model_copy(
            update={"deadline": datetime.now(UTC) + timedelta(seconds=0.15)}
        )
        self.work.admit(
            self.ctx,
            req,
            kind="render",
            external_id="render-expired",
            run_id=self.r.run_id,
            descriptor={},
        )
        key = WorkerServices(self.access).issue(
            kinds=["render"], reason="render-only recovery"
        )
        time.sleep(0.2)
        self.assertEqual(
            WorkerAuthority(self.access, key).reconcile()["pending_expired"], 1
        )
        self.assertEqual(self.budget("cu")["reserved"], 10)

    def test_service_replay_reservation_does_not_double_admit(self):
        first = self.queued()
        second = self.queued()
        self.assertEqual(first["worker_id"], second["worker_id"])
        self.assertEqual(len(self.rows("auth_reservations")), 1)
        self.assertEqual(self.budget("cu")["reserved"], 10)

    def test_proof_tampering_cannot_release_reservation(self):
        q = self.queued()
        claim = self.work.claim(q["worker_id"])
        proof = self.proof(claim)
        proof["outcome"] = "fabricated"
        self.error(lambda: self.work.stopped(claim, proof), 409, "worker_uncertain")
        self.assertEqual(self.budget("cu")["reserved"], 10)

    def test_running_revoke_before_publish_denies_output(self):
        q = self.queued()
        claim = self.work.claim(q["worker_id"])
        proof = self.proof(claim)
        self.auth.logout(self.token)
        self.error(lambda: self.publish(claim, proof, cu=5), 401)
        self.assertEqual(self.rows("worker_probe"), [])
        self.work.stopped(claim, proof, actual_cu=5)
        self.assertEqual(
            (self.budget("cu")["spent"], self.budget("cu")["reserved"]), (5, 0)
        )

    def test_claim_race_single_fence(self):
        q = self.queued()
        barrier = Barrier(2)

        def call(_):
            barrier.wait()
            try:
                return self.work.claim(q["worker_id"])
            except HTTPException as e:
                return e.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            out = list(pool.map(call, range(2)))
        self.assertEqual(sum(not isinstance(x, int) for x in out), 1, out)
        self.assertIn(409, out)

    def test_duplicate_publication_single_charge_and_projection(self):
        q = self.queued()
        claim = self.work.claim(q["worker_id"])
        proof = self.proof(claim)
        first = self.publish(claim, proof, cu=6)
        self.assertEqual(self.publish(claim, proof, cu=6), first)
        self.assertEqual(len(self.rows("worker_probe")), 1)
        self.assertEqual(
            (self.budget("cu")["spent"], self.budget("cu")["reserved"]), (6, 0)
        )

    def test_partial_checkpoints_accrue_once(self):
        q = self.queued()
        first = self.work.claim(q["worker_id"])
        proof = self.proof(first)
        a = self.publish(first, proof, final=False, cu=3)
        self.assertEqual(self.publish(first, proof, final=False, cu=3), a)
        second = self.work.claim(q["worker_id"], phase=1)
        self.publish(second, self.proof(second), value="two", cu=2)
        self.assertEqual(self.budget("cu")["spent"], 5)
        self.assertEqual(len(self.rows("worker_probe")), 2)

    def test_cancel_running_fences_then_positive_stop_settles(self):
        q = self.queued()
        claim = self.work.claim(q["worker_id"])
        proof = self.proof(claim)
        self.work.cancel(self.ctx, q["worker_id"])
        self.error(lambda: self.publish(claim, proof), 409)
        self.assertEqual(self.budget("cu")["reserved"], 10)
        self.work.stopped(claim, proof, actual_cu=4)
        self.assertEqual(self.budget("cu")["spent"], 4)
        self.assertEqual(self.rows("worker_probe"), [])

    def test_cancel_queued_releases_and_no_start(self):
        q = self.queued()
        self.work.cancel(self.ctx, q["worker_id"])
        self.error(lambda: self.work.claim(q["worker_id"]), 409)
        self.assertEqual(self.budget("cu")["reserved"], 0)

    def test_old_fence_cannot_publish_next_phase(self):
        q = self.queued()
        a = self.work.claim(q["worker_id"])
        p = self.proof(a)
        self.publish(a, p, final=False, cu=1)
        b = self.work.claim(q["worker_id"], phase=1)
        self.error(lambda: self.publish(a, p), 409)
        self.publish(b, self.proof(b), value="second", cu=1)
        self.assertEqual(self.budget("cu")["spent"], 2)

    def test_remote_unknown_proof_never_releases(self):
        q = self.queued(kind="render")
        claim = self.work.claim(q["worker_id"])
        _, proof = run_bounded(operator.add, (1, 1), timeout=5)
        sealed = self.work.seal_stop(claim, proof, remote_unknown=True)
        self.error(lambda: self.work.stopped(claim, sealed), 409, "worker_uncertain")
        self.work.uncertain(q["worker_id"], expected_fence=claim.fence)
        self.assertEqual(self.budget("cu")["reserved"], 10)

    def test_foreign_job_context_and_session_pointer_deny(self):
        req = self.request()
        self.error(
            lambda: self.work.admit(
                replace(self.ctx, tenant_id="foreign"),
                req,
                kind="modeling",
                external_id="bad",
                run_id=self.r.run_id,
            ),
            403,
        )
        q = self.queued()
        with self.access.transaction() as tx:
            tx.connection.execute(
                "UPDATE analysis_sessions SET payload=jsonb_set(payload,'{run_id}',to_jsonb('RUN-OTHER'::text)) WHERE session_id=%s",
                (self.s.session_id,),
            )
        self.error(lambda: self.work.claim(q["worker_id"]), 404)

    def test_service_credential_kind_revoke_and_safe_storage(self):
        q = self.queued()
        key = WorkerServices(self.access).issue(
            kinds=["delivery"], reason="least privilege"
        )
        self.error(lambda: WorkerAuthority(self.access, key).claim(q["worker_id"]), 503)
        self.assertNotIn(
            self.key,
            str(self.rows("auth_worker_services") + self.rows("auth_audit_outbox")),
        )
        with self.access.transaction(readonly=True) as tx:
            from apps.api.workers.services import verify

            sid = verify(tx.connection, self.key, "modeling")["service_id"]
        WorkerServices(self.access).revoke(sid, reason="revoked")
        self.error(lambda: self.work.claim(q["worker_id"]), 503)

    def test_legacy_settle_cannot_bypass_execution_fence(self):
        from apps.api.billing.coordinator import ReservationCoordinator

        q = self.queued()
        self.work.claim(q["worker_id"])
        self.error(
            lambda: ReservationCoordinator(self.access).settle(
                q["reservation_id"], expected_version=2, actual_cu=1
            ),
            409,
            "worker_managed_reservation",
        )

    def test_audit_fault_rolls_back_publish_and_settle(self):
        q = self.queued()
        claim = self.work.claim(q["worker_id"])
        proof = self.proof(claim)
        with self.access.transaction() as tx:
            tx.connection.execute(
                "CREATE FUNCTION fail13() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.payload->>'action'='auth_worker_changed' THEN RAISE EXCEPTION 'audit fault' USING ERRCODE='23514'; END IF; RETURN NEW; END $$"
            )
            tx.connection.execute(
                "CREATE TRIGGER fail13 BEFORE INSERT ON auth_audit_outbox FOR EACH ROW EXECUTE FUNCTION fail13()"
            )
        self.error(lambda: self.publish(claim, proof, cu=5), 503)
        self.assertEqual(self.rows("worker_probe"), [])
        self.assertEqual(self.budget("cu")["reserved"], 10)

    def test_real_model_job_and_legacy_tuning_alias_publish_under_fence(self):
        from apps.api.routers import modeling_session

        self.app.include_router(modeling_session.router, prefix="/v1/session/modeling")
        from apps.api.routers import internal
        from tests.integration.test_auth11_scientific import ScientificSQLTests

        self.app.include_router(internal.router, prefix="/v1/internal")
        self.s = ScientificSQLTests.upload(self)
        self.r = self.runs.get_run(self.s.run_id)
        target = "v"
        selected = self.post(
            self.owner, "/v1/session/target-column", {"column": target}
        )
        self.assertEqual(selected.status_code, 200, selected.text)
        date = "date"
        selected = self.post(
            self.owner, "/v1/session/date-column", {"column": date, "confirmed": True}
        )
        self.assertEqual(selected.status_code, 200, selected.text)
        for stage in ("start", "modeling_entry"):
            r = self.post(self.owner, "/v1/session/dataset/passport/" + stage)
            self.assertEqual(r.status_code, 200, r.text)
        r = self.post(
            self.owner, "/v1/session/modeling/candidates", {"horizon": 4, "n_splits": 2}
        )
        self.assertEqual(r.status_code, 200, r.text)
        for path in ("jobs", "tuning"):
            body = {"model_id": "ets", "max_trials": 1, "random_state": 1}
            if path == "jobs":
                body.update(operation="tuning", idempotency_key="native-model")
            queued = self.post(
                self.owner, "/v1/session/modeling/" + path + "/start", body
            )
            self.assertEqual(queued.status_code, 200, queued.text)
            jid = queued.json()["job_id"]
            url = (
                "/v1/session/modeling/jobs/" + jid + "/step"
                if path == "jobs"
                else "/v1/session/modeling/tuning/step"
            )
            payload = (
                {"expected_step": 0}
                if path == "jobs"
                else {"job_id": jid, "expected_trial_index": 0}
            )
            bad = {
                **payload,
                ("expected_step" if path == "jobs" else "expected_trial_index"): 7,
            }
            rejected = self.post(self.owner, url, bad)
            self.assertEqual(rejected.status_code, 409, rejected.text)
            self.assertEqual(
                next(
                    r for r in self.rows("auth_worker_jobs") if r["external_id"] == jid
                )["state"],
                "queued",
            )
            completed = self.post(self.owner, url, payload)
            self.assertEqual(completed.status_code, 200, completed.text)
            self.assertEqual(completed.json()["status"], "completed")
            rows = [r for r in self.rows("auth_worker_jobs") if r["external_id"] == jid]
            self.assertEqual(rows[0]["state"], "completed")
        self.assertEqual(self.budget("concurrency")["reserved"], 0)

    def test_real_delivery_mirror_and_ack_atomic(self):
        from apps.api.delivery_outbox import layer1_mirror_task
        from apps.api.trace_events import TraceEvent
        from apps.api.workers.delivery import deliver

        event = TraceEvent(
            node_id="upload", event_type="test.worker.delivery", run_id=self.r.run_id
        )
        task = layer1_mirror_task(
            session_id=self.s.session_id,
            run_id=self.r.run_id,
            events=[event],
            operation_id="native-projection",
        )
        self.runs.delivery_outbox.register(task)
        outcome = deliver(
            task,
            self.runs,
            self.sessions,
            at=datetime.now(UTC).isoformat(),
            worker=self.work,
        )
        self.assertEqual(outcome, "delivered")
        self.assertEqual(
            self.runs.delivery_outbox.get_task(task.operation_id).state, "delivered"
        )
        self.assertEqual(
            deliver(
                task,
                self.runs,
                self.sessions,
                at=datetime.now(UTC).isoformat(),
                worker=self.work,
            ),
            "delivered",
        )
        current = self.sessions.get(self.s.session_id)
        self.assertEqual(
            sum(x.get("event_id") == event.event_id for x in current.pipeline_trace), 1
        )

    def test_expired_running_lease_keeps_hold_until_positive_stop(self):
        import time

        req = self.request().model_copy(
            update={"deadline": datetime.now(UTC) + timedelta(seconds=0.8)}
        )
        q = self.work.admit(
            self.ctx,
            req,
            kind="modeling",
            external_id="expiry",
            run_id=self.r.run_id,
            session_id=self.s.session_id,
            context_id=self.s.current_context_id(),
            descriptor={},
        )
        claim = self.work.claim(q["worker_id"], lease_seconds=1)
        proof = self.proof(claim)
        time.sleep(0.9)
        result = self.work.reconcile()
        self.assertEqual(result["uncertain"], 1)
        self.assertEqual(self.budget("cu")["reserved"], 10)
        self.error(lambda: self.publish(claim, proof), 409)
        self.work.stopped(claim, proof, actual_cu=2)
        self.assertEqual(self.budget("cu")["spent"], 2)

    def test_signed_spool_reconciles_restart_without_reexecuting(self):
        from apps.api.workers import spool

        q = self.queued()
        claim = self.work.claim(q["worker_id"])
        proof = self.proof(claim)
        spool.save(claim, proof)
        self.work.uncertain(q["worker_id"], expected_fence=claim.fence)
        fresh = WorkerAuthority(self.access, self.key)
        self.assertEqual(fresh.reconcile()["confirmed_stopped"], 1)
        self.assertEqual(self.budget("cu")["reserved"], 0)
        self.assertEqual(self.rows("worker_probe"), [])

    def test_admission_job_projection_failure_rolls_back_reservation(self):
        def fail(row):
            raise RuntimeError("publisher failed")

        self.error(
            lambda: self.work.admit(
                self.ctx,
                self.request(),
                kind="modeling",
                external_id="failed-projection",
                run_id=self.r.run_id,
                session_id=self.s.session_id,
                descriptor={},
                publisher=fail,
            ),
            503,
        )
        self.assertEqual(self.rows("auth_worker_jobs"), [])
        self.assertEqual(self.rows("auth_reservations"), [])
        self.assertEqual(self.budget("concurrency")["reserved"], 0)

    def document_revision(self):
        response = self.post(
            self.owner,
            "/v1/documentation/runs/" + self.r.run_id + "/documents",
            {"kind": "D01"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["revision"]["revision_id"]

    def test_actual_sync_render_ready_and_settled_once(self):
        revision = self.document_revision()
        url = "/v1/documentation/revisions/" + revision + "/renditions"
        response = self.post(self.owner, url, {"format": "md"})
        self.assertEqual(response.status_code, 202, response.text)
        self.assertEqual(response.json()["job"]["state"], "ready", response.text)
        rid = response.json()["job"]["rendition"]["rendition_id"]
        self.assertEqual(
            self.owner.get(
                "/v1/documentation/renditions/" + rid + "/content"
            ).status_code,
            200,
        )
        replay = self.post(self.owner, url, {"format": "md"})
        self.assertEqual(replay.status_code, 202, replay.text)
        self.assertEqual(
            len([x for x in self.rows("auth_worker_jobs") if x["kind"] == "render"]), 1
        )
        self.assertEqual(self.budget("concurrency")["reserved"], 0)

    def test_actual_queued_render_revoke_cannot_start_or_reclaim(self):
        revision = self.document_revision()
        response = self.post(
            self.owner,
            "/v1/documentation/revisions/" + revision + "/renditions",
            {"format": "pdf"},
        )
        self.assertEqual(response.status_code, 202, response.text)
        self.auth.logout(self.token)
        from apps.api.document_render_worker import DocumentRenderWorker
        from apps.api.routers.documentation import _delivery_service

        worker = DocumentRenderWorker(
            service=_delivery_service(), worker_authority=self.work
        )
        worker.run_once()
        self.assertEqual(
            [r["state"] for r in self.rows("auth_worker_jobs")], ["failed"]
        )
        self.assertEqual(self.rows("document_renditions"), [])
        self.assertEqual(self.budget("concurrency")["reserved"], 0)

    def test_actual_queued_render_completes_with_service_and_no_request_cookie(self):
        revision = self.document_revision()
        response = self.post(
            self.owner,
            "/v1/documentation/revisions/" + revision + "/renditions",
            {"format": "pdf"},
        )
        self.assertEqual(response.status_code, 202, response.text)
        from apps.api.document_render_worker import DocumentRenderWorker
        from apps.api.routers.documentation import _delivery_service

        report = DocumentRenderWorker(
            service=_delivery_service(), worker_authority=self.work
        ).run_once()
        self.assertEqual(report["ready"], 1, report)
        self.assertEqual(self.rows("document_jobs")[0]["state"], "ready")
        self.assertEqual(self.rows("auth_worker_jobs")[0]["state"], "completed")
        self.assertEqual(self.budget("concurrency")["reserved"], 0)

    def test_render_missing_service_is_explicit_503_without_reservation(self):
        from unittest.mock import patch

        revision = self.document_revision()
        with patch.dict(os.environ, {"CISSTAT_WORKER_KEY": ""}):
            response = self.post(
                self.owner,
                "/v1/documentation/revisions/" + revision + "/renditions",
                {"format": "md"},
            )
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(
            response.json()["detail"]["code"], "worker_service_unavailable"
        )
        self.assertEqual(self.rows("auth_reservations"), [])

    def test_migration_replay_and_disabled_guard_are_detected(self):
        from apps.api.workers.migrations import check_schema
        from apps.api.authentication.errors import AuthSchemaNotReady

        with self.access.transaction() as tx:
            self.assertFalse(apply_migration(tx.connection))
            tx.connection.execute(
                "ALTER TABLE auth_worker_jobs DISABLE TRIGGER auth13_job_guard"
            )
            with self.assertRaises(AuthSchemaNotReady):
                check_schema(tx.connection)
