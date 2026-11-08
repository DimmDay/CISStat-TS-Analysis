"""AUTH-14 real PostgreSQL pricing/atomic publication/physical-unit accounting."""

import os, unittest
from pathlib import Path
from unittest.mock import patch
from tests.integration import test_auth13_workers as previous
from apps.api.billing.compute_profile import Profile, machine, kernel_digest
from apps.api.billing.compute_units import Coefficient, Workload
from apps.api.billing.contract import Cost
from apps.api.workers.process import run_bounded


def attempted_failure():
    from apps.api.billing.compute_meter import tick

    tick("tuning:ets")
    raise ValueError("known failed attempt")


def attempted_hang():
    import time
    from apps.api.billing.compute_meter import tick

    tick("tuning:ets")
    while True:
        time.sleep(0.02)


@unittest.skipUnless(
    os.environ.get("CISSTAT_AUTH_TEST_DSN"), "disposable PostgreSQL required"
)
class ComputeSQLTests(unittest.TestCase):
    cleanup = previous.WorkerSQLTests.cleanup
    client = previous.WorkerSQLTests.client
    post = previous.WorkerSQLTests.post
    demo = previous.WorkerSQLTests.demo
    rows = previous.WorkerSQLTests.rows
    budget = previous.WorkerSQLTests.budget
    error = previous.WorkerSQLTests.error
    request = previous.WorkerSQLTests.request

    def setUp(self):
        previous.WorkerSQLTests.setUp(self)
        self.policy.set_budget(
            self.account.account_id,
            "cu",
            limit_units=10**8,
            expected_version=self.budget("cu")["version"],
            reason="synthetic SQL-only tariff",
        )
        coefficients = tuple(
            Coefficient(
                key=key,
                base_micro_cu="0.01",
                exponent="1",
                max_rows=1000,
                max_columns=10,
                max_units=128,
                max_horizon=100,
                max_period=365,
                max_folds=20,
                max_trials=64,
                wall_ms=20000,
                memory_mb=1024,
            )
            for key in ("pelt", "tuning:ets")
        )
        self.profile = Profile(
            environment=machine(),
            kernels=kernel_digest(),
            evidence_digest="0" * 64,
            coefficients=coefficients,
            max_concurrency=1,
        )
        self.path = Path(self.temp.name) / "test-only-synthetic-profile.json"
        self.path.write_text(self.profile.model_dump_json())
        env = patch.dict(
            os.environ,
            {
                "CISSTAT_CU_PROFILE": str(self.path),
                "CISSTAT_CU_PROFILE_SHA256": self.profile.digest,
            },
        )
        env.start()
        self.addCleanup(env.stop)

    def queued(self, key="metered", context=None, run=None):
        work = Workload(
            key="tuning:ets", rows=80, columns=1, units=2, folds=2, trials=1
        )
        quote = self.profile.quote(work)
        request = self.request(key).model_copy(
            update={
                "cost": Cost(micro_cu=quote.reserved_micro_cu, version=quote.version)
            }
        )
        if run:
            request = request.model_copy(update={"resource_id": run})
        row = self.work.admit(
            context or self.ctx,
            request,
            kind="modeling",
            external_id=key,
            run_id=run or self.r.run_id,
            descriptor={
                "compute_quote": quote.model_dump(mode="json"),
                "compute_work": work.model_dump(mode="json"),
            },
        )
        return row, quote

    def stopped_attempt(self, claim, *, hang=False):
        from apps.api.workers.process import WorkFailed, WorkStopped

        try:
            run_bounded(
                attempted_hang if hang else attempted_failure,
                timeout=1 if hang else 10,
                work_key="tuning:ets",
                work_limit=2,
                memory_mb=1024,
            )
        except (WorkFailed, WorkStopped) as error:
            return self.work.seal_stop(claim, error.proof)
        self.fail("attempt should fail or stop")

    def test_failure_and_retry_charge_attempted_unit_once(self):
        row, quote = self.queued()
        claim = self.work.claim(row["worker_id"])
        proof = self.stopped_attempt(claim)
        self.work.stopped(claim, proof)
        self.work.stopped(claim, proof)
        self.assertEqual(self.budget("cu")["spent"], quote.unit_micro_cu)
        self.assertEqual(self.budget("cu")["reserved"], 0)

    def test_stopped_timeout_uses_progress_before_fit(self):
        row, quote = self.queued()
        claim = self.work.claim(row["worker_id"])
        proof = self.stopped_attempt(claim, hang=True)
        self.assertEqual(proof["usage"]["units"], 1)
        self.work.stopped(claim, proof)
        self.assertEqual(self.budget("cu")["spent"], quote.unit_micro_cu)

    def test_saved_quote_survives_current_profile_removal(self):
        row, quote = self.queued()
        claim = self.work.claim(row["worker_id"])
        proof = self.stopped_attempt(claim)
        with patch.dict(
            os.environ, {"CISSTAT_CU_PROFILE": "", "CISSTAT_CU_PROFILE_SHA256": ""}
        ):
            self.work.stopped(claim, proof)
        self.assertEqual(self.budget("cu")["spent"], quote.unit_micro_cu)
        self.assertEqual(
            self.rows("auth_reservations")[0]["quote_version"], quote.version
        )

    def test_global_capacity_counts_uncertain_and_queued_can_retry(self):
        first, _ = self.queued("one")
        from dataclasses import replace

        other_client = self.client(self.other)
        other_session, other_run = self.demo(other_client)
        evidence = self.auth.verify(other_client.cookies.get("__Host-cisstat_auth"))
        other_context = replace(
            self.ctx,
            account_id=str(self.other.account_id),
            tenant_id=str(self.other.tenant_id),
            credential_id=evidence.credential_id,
            auth_session_id=evidence.auth_session_id,
        )
        self.policy.create_scope(
            "account",
            account_id=self.other.account_id,
            reason="second synthetic test Account",
        )
        self.policy.set_budget(
            self.other.account_id,
            "cu",
            limit_units=1000000,
            reason="second synthetic test budget",
        )
        second, _ = self.queued("two", other_context, other_run.run_id)
        claim = self.work.claim(first["worker_id"])
        self.error(
            lambda: self.work.claim(second["worker_id"]),
            429,
            "compute_capacity_exceeded",
        )
        self.work.uncertain(first["worker_id"], expected_fence=claim.fence)
        self.error(lambda: self.work.claim(second["worker_id"]), 429)
        self.work.stopped(
            claim,
            self.work.seal_stop(
                claim,
                __import__(
                    "apps.api.workers.process", fromlist=["StopProof"]
                ).StopProof(True, None, 0, "not_started"),
            ),
        )
        self.work.claim(second["worker_id"])

    def test_real_aliases_use_same_paid_tariff_and_no_duplicate_settle(self):
        previous.WorkerSQLTests.test_real_model_job_and_legacy_tuning_alias_publish_under_fence(
            self
        )
        reservations = self.rows("auth_reservations")
        self.assertTrue(
            all(
                r["quote_version"]
                == self.profile.quote(
                    Workload(key="tuning:ets", rows=80, columns=1, units=2)
                ).version
                for r in reservations
            )
        )
        self.assertGreater(self.budget("cu")["spent"], 0)
        self.assertEqual(self.budget("cu")["reserved"], 0)

    def test_stateless_inline_tuning_is_reserved_and_settled(self):
        from apps.api.routers import models
        from tests.integration.test_auth09_objects import ORIGIN

        self.app.include_router(models.router, prefix="/v1/models")
        # /v1/models uses a durable scoped programmatic credential, never a cookie substitute.
        from apps.api.authentication.api_keys import APIKeyService
        from apps.api.authentication.api_key_contract import IssueKeyBody

        keys = APIKeyService(self.access)
        self.app.state.auth_api_key_service = keys
        with self.access.transaction() as tx:
            svc = tx.identities.create(kind="service")
            account = tx.accounts.get(self.account.account_id)
            account = tx.accounts.update(
                account.account_id,
                expected_version=account.entitlement_version,
                seats=3,
            )
            tx.accounts.add_member(
                account.account_id,
                svc.subject_id,
                expected_version=account.entitlement_version,
            )
        key = keys.operator_issue(
            svc.subject_id,
            self.account.account_id,
            IssueKeyBody(label="native14", scopes=["api.compute"], expires_in_days=1),
            reason="native14",
        )
        series = [100 + 0.1 * i + 3 * __import__("math").sin(i / 2) for i in range(80)]
        from fastapi.testclient import TestClient

        client = TestClient(self.app, base_url=ORIGIN)
        response = client.post(
            "/v1/models/tune",
            json={
                "model_id": "ets",
                "series": series,
                "cv": {
                    "n_splits": 2,
                    "test_size": 4,
                    "min_train_size": 40,
                    "step": 4,
                    "gap": 0,
                },
                "max_trials": 1,
                "random_state": 1,
            },
            headers={
                "X-API-Key": key.secret,
                "Origin": ORIGIN,
                "Idempotency-Key": "stateless-native-14",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.rows("auth_worker_jobs")[0]["state"], "completed")
        self.assertGreater(self.budget("cu")["spent"], 0)
        import json

        body = json.loads(response.request.content)
        spent = self.budget("cu")["spent"]
        headers = {
            "X-API-Key": key.secret,
            "Origin": ORIGIN,
            "Idempotency-Key": "stateless-native-14",
        }
        replay = client.post("/v1/models/tune", json=body, headers=headers)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), response.json())
        self.assertEqual(self.budget("cu")["spent"], spent)
        body["max_trials"] = 2
        conflict = client.post("/v1/models/tune", json=body, headers=headers)
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(len(self.rows("auth_worker_jobs")), 1)

    def test_profile_corruption_has_no_zero_price_fallback(self):
        self.path.write_text("{}")
        self.error(
            lambda: self.work.claim(self.queued()[0]["worker_id"]),
            503,
            "compute_profile_unavailable",
        )

    def prepare_session(self, modeling=False, missing=False):
        from apps.api.routers import internal, modeling_session
        from tests.integration.test_auth09_objects import ORIGIN
        import pandas as pd, math

        self.app.include_router(internal.router, prefix="/v1/internal")
        if modeling:
            self.app.include_router(
                modeling_session.router, prefix="/v1/session/modeling"
            )
        proof = self.owner.get("/v1/auth/csrf", headers={"Origin": ORIGIN}).json()[
            "csrf_token"
        ]
        csv = "date,v\n" + "\n".join(
            f"{date.date().isoformat()},{'' if missing and i == 5 else 100 + i * 0.2 + 4 * math.sin(i / 3)}"
            for i, date in enumerate(pd.date_range("2020-01-01", periods=80))
        )
        response = self.owner.post(
            "/v1/internal/upload",
            files={"file": ("auth14.csv", csv, "text/csv")},
            headers={"Origin": ORIGIN, "X-CSRF-Token": proof},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.s = self.sessions.get(self.owner.cookies.get("cisstat_session_id"))
        self.r = self.runs.get_run(self.s.run_id)
        if modeling:
            for path, body in (
                ("target-column", {"column": "v"}),
                ("date-column", {"column": "date", "confirmed": True}),
            ):
                response = self.post(self.owner, "/v1/session/" + path, body)
                self.assertEqual(response.status_code, 200, response.text)
            for stage in ("start", "modeling_entry"):
                response = self.post(
                    self.owner, "/v1/session/dataset/passport/" + stage
                )
                self.assertEqual(response.status_code, 200, response.text)
            response = self.post(
                self.owner,
                "/v1/session/modeling/candidates",
                {"horizon": 4, "n_splits": 2},
            )
            self.assertEqual(response.status_code, 200, response.text)

    def test_pelt_actual_fits_are_charged_and_get_rejects_corrupted_profile(self):
        self.prepare_session()
        response = self.owner.get(
            "/v1/session/dataset/eda-structural-breaks", params={"column": "v"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["applicable"])
        row = self.rows("auth_worker_jobs")[0]
        self.assertEqual(row["state"], "completed")
        self.assertGreater(row["stop_proof"]["usage"]["units"], 0)
        self.assertEqual(self.budget("cu")["spent"], row["accrued_cu"])
        self.assertGreater(row["accrued_cu"], 0)
        spent = self.budget("cu")["spent"]
        replay = self.owner.get(
            "/v1/session/dataset/eda-structural-breaks", params={"column": "v"}
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(self.budget("cu")["spent"], spent)
        self.path.write_text("{}")
        response = self.owner.get(
            "/v1/session/dataset/eda-structural-breaks",
            params={"column": "v", "min_segment": 21},
        )
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(len(self.rows("auth_worker_jobs")), 1)

    def test_synchronous_session_tuning_saves_result_with_settlement(self):
        self.prepare_session(modeling=True)
        # Explicit request key makes lost-response POST retry return the committed result.
        self.owner.headers["Idempotency-Key"] = "sync-native-14"
        response = self.post(
            self.owner,
            "/v1/session/modeling/tune",
            {"model_id": "ets", "max_trials": 2, "random_state": 1},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.rows("auth_worker_jobs")[0]["state"], "completed")
        current = self.sessions.get(self.owner.cookies.get("cisstat_session_id"))
        self.assertIn("ets", current.modeling_artifacts["tuning"])
        self.assertGreater(self.budget("cu")["spent"], 0)
        self.assertEqual(self.budget("cu")["reserved"], 0)
        spent = self.budget("cu")["spent"]
        replay = self.post(
            self.owner,
            "/v1/session/modeling/tune",
            {"model_id": "ets", "max_trials": 2, "random_state": 1},
        )
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.json(), response.json())
        self.assertEqual(self.budget("cu")["spent"], spent)
        self.assertEqual(
            self.sessions.get(current.session_id).modeling_artifacts,
            current.modeling_artifacts,
        )

    def test_missing_work_progress_retains_hold(self):
        from apps.api.workers.process import StopProof

        row, quote = self.queued()
        claim = self.work.claim(row["worker_id"])
        proof = self.work.seal_stop(claim, StopProof(True, None, 0, "completed"))
        self.error(lambda: self.work.stopped(claim, proof), 409, "worker_uncertain")
        self.assertEqual(self.budget("cu")["reserved"], quote.reserved_micro_cu)

    def test_mandatory_audit_fault_rolls_back_charge_and_result(self):
        row, quote = self.queued()
        claim = self.work.claim(row["worker_id"])
        proof = self.stopped_attempt(claim)
        with self.access.transaction() as tx:
            tx.connection.execute(
                "CREATE FUNCTION fail14() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.payload->>'action'='auth_worker_changed' THEN RAISE EXCEPTION 'audit fault' USING ERRCODE='23514'; END IF; RETURN NEW; END $$"
            )
            tx.connection.execute(
                "CREATE TRIGGER fail14 BEFORE INSERT ON auth_audit_outbox FOR EACH ROW EXECUTE FUNCTION fail14()"
            )
        self.error(
            lambda: self.work.publish(
                claim,
                proof,
                publisher=lambda c: c.execute(
                    "INSERT INTO worker_probe(value) VALUES ('result')"
                ),
                result_digest="a" * 64,
            ),
            503,
        )
        self.assertEqual(self.rows("worker_probe"), [])
        self.assertEqual(self.budget("cu")["spent"], 0)
        self.assertEqual(self.budget("cu")["reserved"], quote.reserved_micro_cu)

    def test_nonapplicable_pelt_does_not_create_a_compute_charge(self):
        self.prepare_session(missing=True)
        response = self.owner.get(
            "/v1/session/dataset/eda-structural-breaks", params={"column": "v"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["applicable"])
        self.assertEqual(self.rows("auth_worker_jobs"), [])
        self.assertEqual(self.budget("cu")["spent"], 0)
