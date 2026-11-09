"""Native PostgreSQL only: admission races, quotas, expiry and safe cleanup."""

import os
import secrets
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from fastapi import HTTPException

from apps.api.authentication.context import resolve_verified_context
from apps.api.authentication.demo_cleanup import DemoCleanup
from apps.api.authentication.demo_lifecycle import LifecycleService
from apps.api.authentication.demo_lifecycle_migrations import (
    apply_migration,
    check_schema,
)
from tests.integration import test_auth15_demo as previous


@unittest.skipUnless(
    os.environ.get("CISSTAT_AUTH_TEST_DSN"), "disposable PostgreSQL required"
)
class LifecycleSQLTests(unittest.TestCase):
    cmd = previous.CampaignSQLTests.cmd
    rows = previous.CampaignSQLTests.rows
    enter = previous.CampaignSQLTests.enter
    error = previous.CampaignSQLTests.error

    def setUp(self):
        previous.CampaignSQLTests.setUp(self)
        with self.store.transaction() as tx:
            apply_migration(tx.connection)
        self.life = LifecycleService(self.store, clock=lambda: self.now)

    def codes(self, n=1):
        return self.life.issue_codes(
            self.token,
            previous.ORIGIN,
            self.campaign["campaign_id"],
            self.campaign["policy_version"],
            n,
            self.now + timedelta(minutes=30),
            "test codes",
        )["codes"]

    def test_migration_repeat_and_admission_hash_only(self):
        with self.store.transaction() as tx:
            self.assertFalse(apply_migration(tx.connection))
            check_schema(tx.connection)
        code = self.codes()[0]
        self.assertNotIn(
            code,
            str(self.rows("auth_demo_admissions") + self.rows("auth_audit_outbox")),
        )

    def test_atomic_code_race_and_private_resume(self):
        self.cmd(
            "update", policy=self.policy.model_copy(update={"require_admission": True})
        )
        code = self.codes()[0]

        def enter(_):
            marker = "d1_" + secrets.token_urlsafe(32)
            try:
                return self.demo.enter(
                    "forum15", self.secret, marker, previous.ORIGIN, admission_code=code
                ), marker
            except HTTPException as e:
                return e.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(enter, range(2)))
        self.assertEqual(results.count(409), 1)
        self.assertEqual(len(self.rows("auth_demo_grants")), 1)
        _issued, marker = next(r for r in results if isinstance(r, tuple))
        self.demo.enter("forum15", self.secret, marker, previous.ORIGIN)
        self.assertEqual(len(self.rows("auth_demo_grants")), 1)

    def test_code_required_expired_and_foreign_fail(self):
        self.cmd(
            "update", policy=self.policy.model_copy(update={"require_admission": True})
        )
        self.error(lambda: self.enter(), 401)
        code = self.codes()[0]
        self.now += timedelta(minutes=30)
        self.error(
            lambda: self.demo.enter(
                "forum15",
                self.secret,
                "d1_" + secrets.token_urlsafe(32),
                previous.ORIGIN,
                admission_code=code,
            ),
            401,
        )
        self.assertFalse(self.rows("auth_demo_grants"))

    def test_audit_fault_rolls_back_code_and_grant(self):
        code = self.codes()[0]
        with patch.object(
            self.demo, "_audit_demo", side_effect=RuntimeError("audit fault")
        ):
            self.error(
                lambda: self.demo.enter(
                    "forum15",
                    self.secret,
                    "d1_" + secrets.token_urlsafe(32),
                    previous.ORIGIN,
                    admission_code=code,
                ),
                503,
            )
        self.assertIsNone(self.rows("auth_demo_admissions")[0]["redeemed_at"])
        self.assertFalse(self.rows("auth_demo_grants"))

    def test_quota_race_and_idempotency_payload_conflict(self):
        self.cmd(
            "update",
            policy=self.policy.model_copy(
                update={"participant_requests": 1, "campaign_requests": 1}
            ),
        )
        a, _ = self.enter()
        ctx = resolve_verified_context(self.sessions.verify(a.token), store=self.store)

        def claim(n):
            try:
                return self.life.claim_request(ctx, "test:operation", str(n), "a" * 64)
            except HTTPException as e:
                return e.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            r = list(pool.map(claim, range(2)))
        self.assertEqual(r.count(429), 1)
        row = next(x for x in r if isinstance(x, dict))
        self.life.finish(row["call_id"], {"test": "done"})
        key = next(str(n) for n in range(2) if isinstance(r[n], dict))
        self.assertEqual(
            self.life.claim_request(ctx, "test:operation", key, "a" * 64)["call_id"],
            row["call_id"],
        )
        self.error(
            lambda: self.life.claim_request(ctx, "test:operation", key, "b" * 64), 409
        )
        self.assertEqual(
            [r["requests"] for r in self.rows("auth_demo_http_usage")], [1, 1]
        )

    def core(self):
        import psycopg
        from psycopg.conninfo import make_conninfo

        from apps.api.research_runs import run_migrations

        dsn = make_conninfo(previous.DSN, options="-csearch_path=" + self.store.schema)
        self.store._dsn = dsn
        with psycopg.connect(dsn) as c:
            run_migrations(c)
        return dsn

    def expired(self):
        self.core()
        a, _ = self.enter()
        g = self.rows("auth_demo_grants")[0]
        self.now = g["expires_at"] + timedelta(hours=25)
        return a, g

    def test_cleanup_retains_minimal_audit_and_ledger(self):
        _, _g = self.expired()
        before = len(self.rows("auth_audit_outbox"))
        result = DemoCleanup(self.store, clock=lambda: self.now).sweep()
        self.assertEqual(result["cleaned"], 1)
        self.assertTrue(self.rows("auth_demo_grants"))
        self.assertTrue(self.rows("auth_budget_scopes"))
        self.assertGreater(len(self.rows("auth_audit_outbox")), before)
        self.assertEqual(
            DemoCleanup(self.store, clock=lambda: self.now).sweep()["cleaned"], 0
        )

    def test_cleanup_hold_and_uncertain_keep_data(self):
        _, g = self.expired()
        with self.store.transaction() as tx:
            c = tx.connection
            c.execute(
                "INSERT INTO research_runs(run_id,session_id,owner_account_id,tenant_id,ownership,ownership_version) VALUES ('RUN-AUTH16','test',%s,'test','bound',1)",
                (g["account_id"],),
            )
            c.execute(
                "INSERT INTO documents(document_id,run_id,kind_code) VALUES ('doc16','RUN-AUTH16','D01')"
            )
            c.execute(
                "INSERT INTO document_retention(document_id,run_id,hold) VALUES ('doc16','RUN-AUTH16',true)"
            )
        cleanup = DemoCleanup(self.store, clock=lambda: self.now)
        self.assertEqual(cleanup.sweep()["held"], 1)
        self.assertTrue(self.rows("research_runs"))
        with self.store.transaction() as tx:
            tx.connection.execute("UPDATE document_retention SET hold=false")
        self.assertEqual(cleanup.sweep()["cleaned"], 1)
        self.assertFalse(self.rows("research_runs"))

    def test_cleanup_audit_failure_rolls_back(self):
        _, _g = self.expired()
        with patch(
            "apps.api.authentication.demo_cleanup.audit",
            side_effect=RuntimeError("fault"),
        ):
            self.error(
                lambda: DemoCleanup(self.store, clock=lambda: self.now).sweep(), 503
            )
        self.assertFalse(self.rows("auth_demo_cleanup"))

    def test_cleanup_running_call_requires_quiesced_recovery(self):
        self.core()
        issued, _ = self.enter()
        ctx = resolve_verified_context(
            self.sessions.verify(issued.token), store=self.store
        )
        self.life.claim_request(ctx, "test:hold", "one", "a" * 64)
        g = self.rows("auth_demo_grants")[0]
        self.now = g["expires_at"] + timedelta(hours=25)
        cleanup = DemoCleanup(self.store, clock=lambda: self.now)
        self.assertEqual(cleanup.sweep()["running"], 1)
        self.error(lambda: cleanup.abandon_calls(), 503)
        self.assertEqual(cleanup.abandon_calls(quiesced=True)["abandoned"], 1)
        self.assertEqual(cleanup.sweep()["cleaned"], 1)
        self.assertEqual(self.rows("auth_demo_http_usage")[0]["requests"], 1)

    def test_quiesced_file_gc_keeps_shared_bytes_and_commits_audit_first(self):
        import tempfile
        from pathlib import Path

        from apps.api.artifact_store import ArtifactObjectStore

        self.core()
        self.enter()
        g = self.rows("auth_demo_grants")[0]
        with tempfile.TemporaryDirectory(
            dir=str(__import__("pathlib").Path(os.getcwd()).parent)
        ) as tmp:
            obj = ArtifactObjectStore(Path(tmp))
            staged = obj.stage_bytes(b"auth16 shared content", "application/json")
            key = obj.commit_staged(staged)
            path = obj.path_for_key(key)
            with self.store.transaction() as tx:
                c = tx.connection
                c.execute(
                    "INSERT INTO research_runs(run_id,session_id,owner_account_id,tenant_id,ownership,ownership_version) VALUES ('RUN-SHARED16','test',%s,'test','bound',1)",
                    (g["account_id"],),
                )
                c.execute(
                    "INSERT INTO research_artifacts(artifact_id,run_id,kind,producer_key,storage_key) VALUES ('A16','RUN-SHARED16','test','test',%s)",
                    (key,),
                )
                DemoCleanup._queue(c, "object", key)
            cleanup = DemoCleanup(self.store, clock=lambda: self.now)
            with patch(
                "apps.api.artifact_store.get_artifact_object_store", return_value=obj
            ):
                self.error(lambda: cleanup.collect_files(), 503)
                self.assertEqual(cleanup.collect_files(quiesced=True)["collected"], 0)
                self.assertTrue(path.exists())
                with self.store.transaction() as tx:
                    tx.connection.execute(
                        "DELETE FROM research_artifacts WHERE artifact_id='A16'"
                    )
                with patch(
                    "apps.api.authentication.demo_cleanup.audit",
                    side_effect=RuntimeError("fault"),
                ):
                    self.error(lambda: cleanup.collect_files(quiesced=True), 503)
                self.assertTrue(path.exists())
                self.assertEqual(cleanup.collect_files(quiesced=True)["collected"], 1)
                self.assertFalse(path.exists())
                self.assertEqual(cleanup.collect_files(quiesced=True)["collected"], 0)

    def test_resume_does_not_extend_expiry_or_bypass_expiration(self):
        _issued, marker = self.enter()
        before = self.rows("auth_demo_grants")[0]
        self.now += timedelta(minutes=5)
        self.demo.resume(marker, previous.ORIGIN)
        self.assertEqual(
            self.rows("auth_demo_grants")[0]["expires_at"], before["expires_at"]
        )
        self.now = before["expires_at"]
        self.error(lambda: self.demo.resume(marker, previous.ORIGIN), 403)
        self.error(
            lambda: self.demo.enter("forum15", self.secret, marker, previous.ORIGIN),
            403,
        )
        self.assertEqual(len(self.rows("auth_demo_grants")), 1)

    def test_expiry_fences_late_publication_and_uncertain_holds_slot(self):
        from apps.api.access_registry import ModelWorkload
        from apps.api.billing.contract import Admission, Cost
        from apps.api.workers.authority import WorkerAuthority
        from apps.api.workers.process import StopProof
        from apps.api.workers.services import WorkerServices

        self.core()
        self.demo.clock = lambda: previous.datetime.now(previous.timezone.utc)
        issued, _ = self.enter()
        ctx = resolve_verified_context(
            self.sessions.verify(issued.token), store=self.store
        )
        key = WorkerServices(self.store).issue(kinds=["modeling"], reason="auth16 test")
        worker = WorkerAuthority(self.store, key)
        now = previous.datetime.now(previous.timezone.utc)
        row = worker.admit(
            ctx,
            Admission(
                entry_id="api:POST:/v1/internal/models/backtest",
                resource_kind="stateless",
                resource_id="test16",
                idempotency_key="worker16",
                payload={"test": True},
                cost=Cost(micro_cu=0, version="demo16/1"),
                deadline=now + timedelta(minutes=10),
                workload=ModelWorkload(
                    model_ids=("naive",),
                    rows=80,
                    folds=1,
                    horizon=4,
                    seasonal_period=12,
                    custom_parameters=False,
                ),
            ),
            kind="modeling",
            external_id="test16",
            run_id="test16",
            descriptor={"family": "inline", "resource_kind": "stateless"},
        )
        self.assertLessEqual(row["deadline"], now + timedelta(seconds=61))
        claim = worker.claim(row["worker_id"])
        proof = worker.seal_stop(claim, StopProof(True, None, 0, "not_started"))
        g = self.rows("auth_demo_grants")[0]
        self.now = g["expires_at"] + timedelta(hours=25)
        cleanup = DemoCleanup(self.store, clock=lambda: self.now)
        self.assertEqual(cleanup.sweep()["running"], 1)
        self.error(
            lambda: worker.publish(
                claim,
                proof,
                publisher=lambda c: c.execute("SELECT 1"),
                result_digest="a" * 64,
            ),
            403,
        )
        worker.uncertain(claim.worker_id, expected_fence=claim.fence)
        self.assertEqual(cleanup.sweep()["running"], 1)
        budgets = [
            b
            for b in self.rows("auth_resource_budgets")
            if b["scope_id"] == g["grant_id"] and b["metric"] == "concurrency"
        ]
        self.assertEqual(budgets[0]["reserved"], 1)
        self.assertFalse(self.rows("auth_demo_cleanup"))

    def test_http_real_upload_replay_limits_and_expiry(self):
        import tempfile

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from apps.api import research_runs, session_store
        from apps.api.routers import (
            authentication,
            demo,
            forecasting_session,
            internal,
            modeling_session,
            models,
            progress,
            session,
        )
        from apps.api.trace_hook import TraceHookMiddleware

        self.cmd(
            "update",
            policy=self.policy.model_copy(
                update={"allow_upload": True, "max_upload_bytes": 1024}
            ),
        )
        dsn = self.core()
        from apps.api.workers.services import WorkerServices

        key = WorkerServices(self.store).issue(
            kinds=["modeling", "delivery"], reason="auth16 native"
        )
        with (
            tempfile.TemporaryDirectory(
                dir=str(__import__("pathlib").Path(os.getcwd()).parent)
            ) as tmp,
            patch.dict(
                os.environ,
                {
                    "DATABASE_URL": dsn,
                    "CISSTAT_WORKER_KEY": key,
                    "CISSTAT_WORKER_PROOF_DIR": tmp + "/proof",
                    "CISSTAT_STORAGE_MODE": "required",
                    "CISSTAT_SESSION_BACKEND": "postgres",
                    "CISSTAT_IDENTITY_MODE": "session_scoped",
                    "CISSTAT_DATA_DIR": tmp,
                },
            ),
        ):
            resets = (
                session_store.reset_session_store_for_testing,
                research_runs.reset_research_run_store_for_testing,
                research_runs.reset_dataset_file_store_for_testing,
            )
            for reset in resets:
                reset()
            try:
                app = FastAPI()
                app.state.auth_access_store = self.store
                for prefix, module in (
                    ("/v1", demo),
                    ("/v1/auth", authentication),
                    ("/v1/session", session),
                    ("/v1/progress", progress),
                    ("/v1/session/modeling", modeling_session),
                    ("/v1/session/modeling", forecasting_session),
                    ("/v1/models", models),
                    ("/v1/internal", internal),
                ):
                    app.include_router(module.router, prefix=prefix)
                app.add_middleware(TraceHookMiddleware)
                from apps.api import artifact_store, report_snapshot

                artifacts = artifact_store.PostgresArtifactRegistry(dsn)
                artifacts._schema_ready = True
                snapshots = report_snapshot.PostgresSnapshotRegistry(dsn)
                snapshots._schema_ready = True
                for module, name, value in [
                    (artifact_store, "_registry", artifacts),
                    (
                        artifact_store,
                        "_object_store",
                        artifact_store.ArtifactObjectStore(tmp + "/artifacts"),
                    ),
                    (report_snapshot, "_registry", snapshots),
                ]:
                    replacement = patch.object(module, name, value)
                    replacement.start()
                    self.addCleanup(replacement.stop)
                from pathlib import Path

                import pandas as pd

                csv = Path(tmp) / "fixture16.csv"
                pd.DataFrame(
                    {
                        "date": pd.date_range("2020-01-01", periods=120, freq="MS"),
                        "value": [100 + i + ((i % 12) - 6) * 2 for i in range(120)],
                    }
                ).to_csv(csv, index=False)
                with (
                    TestClient(app, base_url=previous.ORIGIN) as client,
                    patch.object(session, "DEMO_DATASET_PATH", csv),
                ):

                    def post(path, body=None, key=None):
                        print("AUTH16 HTTP", path, flush=True)
                        proof = client.get(
                            "/v1/auth/csrf", headers={"Origin": previous.ORIGIN}
                        ).json()["csrf_token"]
                        return client.post(
                            path,
                            json=body or {},
                            headers={
                                "Origin": previous.ORIGIN,
                                "X-CSRF-Token": proof,
                                **({"Idempotency-Key": key} if key else {}),
                            },
                        )

                    self.assertEqual(post("/v1/auth/demo/prepare").status_code, 200)
                    self.assertEqual(
                        post(
                            "/v1/auth/demo/enter",
                            {"login": "forum15", "password": self.secret},
                        ).status_code,
                        200,
                    )
                    r = post("/v1/session/demo", key="same-upload")
                    self.assertEqual(r.status_code, 200, r.text)
                    replay = post("/v1/session/demo", key="same-upload")
                    self.assertEqual(replay.status_code, 200, replay.text)
                    self.assertEqual(r.json(), replay.json())
                    # Actual baseline runs in supervised child, not an in-process mock.
                    result = post(
                        "/v1/internal/models/backtest",
                        {
                            "model_id": "naive",
                            "profile": {
                                "n_observations": 2,
                                "frequency": "M",
                                "has_seasonality": False,
                            },
                            "train_ratio": 0.8,
                        },
                    )
                    self.assertEqual(result.status_code, 200, result.text)
                    self.assertTrue(self.rows("auth_worker_jobs"))
                    self.assertEqual(
                        self.rows("auth_worker_jobs")[-1]["state"], "completed"
                    )
                    for path, body in [
                        (
                            "/v1/session/date-column",
                            {"column": "date", "confirmed": True},
                        ),
                        ("/v1/session/dataset/passport/start", {}),
                        ("/v1/session/dataset/passport/modeling_entry", {}),
                        (
                            "/v1/session/modeling/candidates",
                            {"horizon": 4, "n_splits": 3, "strategy": "expanding"},
                        ),
                        ("/v1/session/modeling/baselines", {}),
                        (
                            "/v1/session/modeling/compare",
                            {"model_ids": ["naive", "seasonal_naive", "drift"]},
                        ),
                    ]:
                        result = post(path, body)
                        self.assertEqual(result.status_code, 200, result.text)
                    result = post("/v1/session/modeling/selection/evaluate", {})
                    self.assertEqual(result.status_code, 200, result.text)
                    analysis = result.json()
                    result = post(
                        "/v1/session/modeling/select",
                        {
                            "model_id": analysis["recommended_single"]["model_id"],
                            "selection_analysis_id": analysis["selection_analysis_id"],
                            "selection_signature": analysis["selection_signature"],
                            "acknowledge_baseline_risk": True,
                            "acknowledge_selection_bias": True,
                        },
                    )
                    self.assertEqual(result.status_code, 200, result.text)
                    result = post("/v1/session/modeling/card", {})
                    self.assertEqual(result.status_code, 200, result.text)
                    result = post(
                        "/v1/session/modeling/forecast",
                        {"model_card_id": result.json()["card_id"], "horizon": 4},
                    )
                    self.assertEqual(result.status_code, 200, result.text)
                    forecast = result.json()["forecast_id"]
                    self.assertEqual(
                        client.get(
                            "/v1/session/modeling/forecast/" + forecast + "/export.csv"
                        ).status_code,
                        200,
                    )
                    spent = next(
                        b["spent"]
                        for b in self.rows("auth_resource_budgets")
                        if b["scope_id"] == self.rows("auth_demo_grants")[0]["grant_id"]
                        and b["metric"] == "analysis"
                    )
                    self.assertEqual(spent, 1)

                    def own_file(content, key):
                        proof = client.get(
                            "/v1/auth/csrf", headers={"Origin": previous.ORIGIN}
                        ).json()["csrf_token"]
                        return client.post(
                            "/v1/internal/upload",
                            files={"file": ("own.csv", content, "text/csv")},
                            headers={
                                "Origin": previous.ORIGIN,
                                "X-CSRF-Token": proof,
                                "Idempotency-Key": key,
                            },
                        )

                    before_requests = sum(
                        r["requests"] for r in self.rows("auth_demo_http_usage")
                    )
                    proof = client.get(
                        "/v1/auth/csrf", headers={"Origin": previous.ORIGIN}
                    ).json()["csrf_token"]
                    oversized_body = client.post(
                        "/v1/internal/upload",
                        content=b"x" * 66561,
                        headers={
                            "Origin": previous.ORIGIN,
                            "X-CSRF-Token": proof,
                            "Idempotency-Key": "oversized-body",
                            "Content-Type": "application/octet-stream",
                        },
                    )
                    self.assertEqual(
                        oversized_body.status_code, 413, oversized_body.text
                    )
                    self.assertEqual(
                        sum(r["requests"] for r in self.rows("auth_demo_http_usage")),
                        before_requests + 2,
                    )
                    oversized = own_file(b"x" * 1025, "oversized")
                    self.assertEqual(oversized.status_code, 413, oversized.text)
                    own = own_file(
                        b"date,value\n2026-01-01,1\n2026-02-01,2\n2026-03-01,3\n", "own"
                    )
                    self.assertEqual(own.status_code, 200, own.text)
                    self.assertTrue(
                        [r for r in self.rows("auth_demo_gc") if r["kind"] == "upload"]
                    )

                    self.assertEqual(
                        post("/v1/session/demo", key="third").status_code, 429
                    )
            finally:
                for reset in resets:
                    reset()
