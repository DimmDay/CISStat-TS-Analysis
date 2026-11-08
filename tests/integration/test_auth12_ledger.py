"""Native PostgreSQL transactional admission, financial races and rollback oracles."""

import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException

from apps.api.authentication.api_key_contract import IssueKeyBody
from apps.api.authentication.api_keys import APIKeyService
from apps.api.authentication.context import RequestContext
from apps.api.billing.contract import Admission, Cost
from apps.api.billing.coordinator import ReservationCoordinator
from apps.api.billing.migrations import apply_migration
from apps.api.billing.policy import BudgetPolicy
from apps.api.plans import PLAN_DEFINITIONS, PlanName
from tests.integration import test_auth09_objects as previous


@unittest.skipUnless(
    os.environ.get("CISSTAT_AUTH_TEST_DSN"), "disposable PostgreSQL required"
)
class LedgerSQLTests(unittest.TestCase):
    cleanup = previous.OwnershipSQLTests.cleanup
    client = previous.OwnershipSQLTests.client

    def setUp(self):
        previous.OwnershipSQLTests.setUp(self)
        with self.access.transaction() as tx:
            apply_migration(tx.connection)
        self.ledger = ReservationCoordinator(self.access)
        self.policy = BudgetPolicy(self.access)
        self.owner = self.client()
        self.token = self.owner.cookies.get("__Host-cisstat_auth")
        self.ctx = self.context(self.auth.verify(self.token))
        self.keys = APIKeyService(self.access)
        issued = self.keys.issue(
            self.token,
            IssueKeyBody(
                label="budget test",
                scopes=["api.read", "api.compute", "api.write", "api.database"],
                expires_in_days=1,
            ),
            origin=previous.ORIGIN,
        )
        self.key = issued.secret
        self.api = self.context(self.keys.verify(self.key))
        self.scope = self.policy.create_scope(
            "account", account_id=self.account.account_id, reason="native AUTH12"
        )
        self.policy.set_budget(
            self.account.account_id, "cu", limit_units=10, reason="native AUTH12"
        )
        self.policy.set_budget(
            self.account.account_id,
            "concurrency",
            limit_units=2,
            reason="native AUTH12",
        )

    def context(self, e):
        with self.access.transaction(readonly=True) as tx:
            a = tx.accounts.get(e.account_id)
            u = tx.identities.get(e.subject_id)
        return RequestContext(
            subject_id=e.subject_id,
            account_id=e.account_id,
            tenant_id=str(a.tenant_id),
            auth_method=e.auth_method,
            credential_id=e.credential_id,
            auth_session_id=e.auth_session_id,
            subject_version=u.subject_version,
            entitlement_version=a.entitlement_version,
            scopes=e.scopes,
            request_id="native12",
        )

    def req(
        self,
        key=None,
        *,
        cu=0,
        entry="api:GET:/v1/public/rules/templates",
        run=None,
        payload=None,
        slots=1,
        deadline=None,
    ):
        return Admission(
            entry_id=entry,
            idempotency_key=key or str(uuid4()),
            resource_kind="run" if run else "stateless",
            resource_id=run or "test-input",
            analysis_run_id=run,
            payload=payload or {"n": 80},
            cost=Cost(micro_cu=cu, version="test-only/1"),
            deadline=deadline or datetime.now(UTC) + timedelta(minutes=10),
            slots=slots,
        )

    def rows(self, table):
        with self.access.transaction(readonly=True) as tx:
            return tx.connection.execute("SELECT * FROM " + table).fetchall()

    def error(self, fn, status, code=None):
        with self.assertRaises(HTTPException) as e:
            fn()
        self.assertEqual(e.exception.status_code, status, e.exception.detail)
        if code:
            self.assertEqual(e.exception.detail["code"], code)

    def race(self, fn):
        barrier = Barrier(2)

        def call(i):
            barrier.wait()
            try:
                return fn(i)
            except HTTPException as e:
                return e.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(call, range(2)))

    def budget(self, metric):
        return next(
            b
            for b in self.rows("auth_resource_budgets")
            if b["scope_id"] == self.account.account_id and b["metric"] == metric
        )

    def test_last_cu_race_one_job_all_atomic(self):
        result = self.race(lambda i: self.ledger.reserve(self.api, self.req(cu=10)))
        self.assertEqual(sum(not isinstance(r, int) for r in result), 1, result)
        self.assertEqual(self.budget("cu")["reserved"], 10)
        self.assertEqual(len(self.rows("auth_job_outbox")), 1)

    def test_last_api_race_account_not_key(self):
        caps = PLAN_DEFINITIONS[PlanName.PROFESSIONAL].model_copy(
            update={"max_api_calls_per_month": 1}
        )
        with patch.dict(PLAN_DEFINITIONS, {PlanName.PROFESSIONAL: caps}):
            result = self.race(
                lambda i: self.ledger.reserve(self.api, self.req(slots=0))
            )
        self.assertEqual(sum(not isinstance(r, int) for r in result), 1, result)
        self.assertEqual(self.budget("api")["spent"], 1)

    def test_last_analysis_race_and_same_run_once(self):
        caps = PLAN_DEFINITIONS[PlanName.PROFESSIONAL].model_copy(
            update={"max_analyses_total": 1}
        )
        with patch.dict(PLAN_DEFINITIONS, {PlanName.PROFESSIONAL: caps}):
            result = self.race(
                lambda i: self.ledger.reserve(
                    self.ctx,
                    self.req(
                        entry="api:POST:/v1/internal/upload",
                        run="RUN-" + str(i),
                        slots=0,
                    ),
                )
            )
            self.assertEqual(sum(not isinstance(r, int) for r in result), 1, result)
            claim = self.rows("auth_analysis_claims")[0]
            self.ledger.reserve(
                self.ctx,
                self.req(
                    entry="api:POST:/v1/internal/upload", run=claim["run_id"], slots=0
                ),
            )
        self.assertEqual(self.budget("analysis")["spent"], 1)

    def test_idempotent_concurrent_and_payload_conflict(self):
        req = self.req("stable", cu=5)
        result = self.race(lambda i: self.ledger.reserve(self.api, req))
        self.assertEqual(result[0], result[1])
        self.assertEqual(len(self.rows("auth_job_outbox")), 1)
        self.error(
            lambda: self.ledger.reserve(
                self.api, req.model_copy(update={"payload": {"n": 81}})
            ),
            409,
            "idempotency_conflict",
        )

    def test_settle_partial_and_terminal_retry(self):
        r = self.ledger.reserve(self.api, self.req(cu=10))
        run = self.ledger.start(self.api, r.reservation_id, expected_version=1)
        done = self.ledger.settle(
            r.reservation_id,
            expected_version=run.version,
            actual_cu=6,
            result_ref="forecast:one",
        )
        self.assertEqual(
            self.ledger.settle(
                r.reservation_id,
                expected_version=run.version,
                actual_cu=6,
                result_ref="forecast:one",
            ),
            done,
        )
        self.assertEqual(
            (self.budget("cu")["spent"], self.budget("cu")["reserved"]), (6, 0)
        )
        self.assertEqual(self.budget("concurrency")["reserved"], 0)
        self.error(
            lambda: self.ledger.settle(
                r.reservation_id, expected_version=run.version, actual_cu=5
            ),
            409,
        )

    def test_running_release_forbidden_and_no_lease_refund(self):
        r = self.ledger.reserve(self.api, self.req(cu=4))
        r = self.ledger.start(self.api, r.reservation_id, expected_version=1)
        self.error(
            lambda: self.ledger.release(r.reservation_id, expected_version=r.version),
            409,
        )
        from apps.api.billing.coordinator import ReservationCoordinator as C

        with patch.object(
            C, "_now", return_value=datetime.now(UTC) + timedelta(hours=1)
        ):
            self.error(
                lambda: self.ledger.settle(
                    r.reservation_id, expected_version=r.version, actual_cu=1
                ),
                409,
            )
        self.assertEqual(self.budget("cu")["reserved"], 4)

    def test_pending_cancel_keeps_api_analysis_charged(self):
        r = self.ledger.reserve(
            self.api, self.req(cu=4, entry="api:POST:/v1/public/upload", run="RUN-ONE")
        )
        self.ledger.release(r.reservation_id, expected_version=1)
        self.assertEqual(self.budget("cu")["reserved"], 0)
        self.assertEqual(self.budget("api")["spent"], 1)
        self.assertEqual(self.budget("analysis")["spent"], 1)

    def test_over_estimate_cannot_spend_then_explicit_extend(self):
        r = self.ledger.reserve(self.api, self.req(cu=3))
        r = self.ledger.start(self.api, r.reservation_id, expected_version=1)
        self.error(
            lambda: self.ledger.settle(
                r.reservation_id, expected_version=r.version, actual_cu=5
            ),
            402,
        )
        r = self.ledger.extend(
            self.api, r.reservation_id, expected_version=r.version, additional_cu=2
        )
        self.ledger.settle(r.reservation_id, expected_version=r.version, actual_cu=5)
        self.assertEqual(self.budget("cu")["spent"], 5)

    def test_audit_fault_rolls_back_reserve_every_table(self):
        with self.access.transaction() as tx:
            tx.connection.execute(
                "CREATE FUNCTION fail12() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.payload->>'action'='auth_reservation_changed' THEN RAISE EXCEPTION 'intent fault' USING ERRCODE='23514'; END IF; RETURN NEW; END $$"
            )
            tx.connection.execute(
                "CREATE TRIGGER fail12 BEFORE INSERT ON auth_audit_outbox FOR EACH ROW EXECUTE FUNCTION fail12()"
            )
        self.error(lambda: self.ledger.reserve(self.api, self.req(cu=7)), 503)
        for table in (
            "auth_reservations",
            "auth_job_outbox",
            "auth_analysis_claims",
            "auth_usage_postings",
        ):
            self.assertEqual(self.rows(table), [])
        self.assertEqual(self.budget("cu")["reserved"], 0)

    def test_missing_schema_never_migrates_in_request(self):
        with self.access.transaction() as tx:
            tx.connection.execute(
                "DELETE FROM auth_schema_versions WHERE version='0025_auth12_reservations'"
            )
        self.error(lambda: self.ledger.reserve(self.api, self.req()), 503)

    def test_restore_cannot_claim_new_analysis(self):
        self.error(
            lambda: self.ledger.reserve(
                self.ctx,
                self.req(
                    entry="api:POST:/v1/progress/runs/{run_id}/restore", run="RUN-OLD"
                ),
            ),
            409,
        )

    def test_current_revoked_credential_not_allowed_to_replay(self):
        req = self.req()
        self.ledger.reserve(
            self.ctx,
            req.model_copy(update={"entry_id": "api:GET:/v1/internal/rules/templates"}),
        )
        self.auth.logout(self.token)
        self.error(
            lambda: self.ledger.reserve(
                self.ctx,
                req.model_copy(
                    update={"entry_id": "api:GET:/v1/internal/rules/templates"}
                ),
            ),
            401,
        )

    def test_common_sponsor_across_accounts_and_grant_atomic(self):
        sponsor = self.policy.create_scope("sponsor", reason="test hierarchy")
        campaign = self.policy.create_scope(
            "campaign",
            parent_id=sponsor["scope_id"],
            ends_at=datetime.now(UTC) + timedelta(hours=1),
            reason="test hierarchy",
        )
        with self.access.transaction() as tx:
            other = tx.accounts.create(self.member.subject_id, plan="starter")
        accounts = [self.other, other]
        contexts = []
        for i, a in enumerate(accounts):
            account = self.policy.create_scope(
                "account",
                account_id=a.account_id,
                parent_id=campaign["scope_id"],
                reason="test hierarchy",
            )
            grant = self.policy.create_scope(
                "grant",
                account_id=a.account_id,
                parent_id=account["scope_id"],
                ends_at=datetime.now(UTC) + timedelta(hours=1),
                reason="test hierarchy",
            )
            for scope in (account, grant):
                self.policy.set_budget(
                    scope["scope_id"], "cu", limit_units=10, reason="test hierarchy"
                )
                self.policy.set_budget(
                    scope["scope_id"],
                    "concurrency",
                    limit_units=2,
                    reason="test hierarchy",
                )
            client = self.client(account=a, member=bool(i))
            contexts.append(
                self.context(
                    self.auth.verify(client.cookies.get("__Host-cisstat_auth"))
                )
            )
        for scope in (sponsor, campaign):
            self.policy.set_budget(
                scope["scope_id"], "cu", limit_units=10, reason="test hierarchy"
            )
            self.policy.set_budget(
                scope["scope_id"], "concurrency", limit_units=2, reason="test hierarchy"
            )
        result = self.race(
            lambda i: self.ledger.reserve(
                contexts[i],
                self.req(cu=10, slots=1, entry="api:GET:/v1/internal/rules/templates"),
            )
        )
        self.assertEqual(sum(not isinstance(r, int) for r in result), 1, result)
        chain = [
            b
            for b in self.rows("auth_resource_budgets")
            if b["metric"] == "cu" and b["scope_id"] != self.account.account_id
        ]
        self.assertEqual(sum(b["reserved"] for b in chain), 40)
        self.assertEqual(len(self.rows("auth_job_outbox")), 1)

    def test_job_outbox_fault_rolls_back_all_budget_changes(self):
        with self.access.transaction() as tx:
            tx.connection.execute(
                "CREATE FUNCTION fail_job12() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'outbox fault' USING ERRCODE='23514'; END $$"
            )
            tx.connection.execute(
                "CREATE TRIGGER fail_job12 BEFORE INSERT ON auth_job_outbox FOR EACH ROW EXECUTE FUNCTION fail_job12()"
            )
        self.error(
            lambda: self.ledger.reserve(
                self.api,
                self.req(cu=5, entry="api:POST:/v1/public/upload", run="RUN-FAIL"),
            ),
            503,
        )
        for table in (
            "auth_reservations",
            "auth_analysis_claims",
            "auth_usage_postings",
            "auth_job_outbox",
        ):
            self.assertEqual(self.rows(table), [])
        self.assertEqual(self.budget("cu")["reserved"], 0)

    def test_sql_projection_and_immutable_ledger(self):
        r = self.ledger.reserve(self.api, self.req(cu=2))
        from apps.api.authentication.errors import RepositoryConflict

        for stmt in (
            "UPDATE auth_resource_budgets SET spent=spent+1,version=version+1",
            "DELETE FROM auth_usage_postings",
            "DELETE FROM auth_job_outbox",
            "UPDATE auth_reservations SET quote_version='other',version=version+1",
        ):
            with (
                self.subTest(stmt=stmt),
                self.assertRaises(RepositoryConflict),
                self.access.transaction() as tx,
            ):
                tx.connection.execute(stmt)
        self.assertEqual(self.ledger.get(self.api, r.reservation_id), r)

    def test_rotation_does_not_reset_quota_or_idempotency(self):
        from apps.api.authentication.api_key_contract import RotateKeyBody

        caps = PLAN_DEFINITIONS[PlanName.PROFESSIONAL].model_copy(
            update={"max_api_calls_per_month": 1}
        )
        req = self.req("rotation", slots=0)
        with patch.dict(PLAN_DEFINITIONS, {PlanName.PROFESSIONAL: caps}):
            receipt = self.ledger.reserve(self.api, req)
            rotated = self.keys.rotate(
                self.token,
                uuid4() if not self.api.credential_id else self.api.credential_id,
                RotateKeyBody(expected_version=1, scopes=["api.read"]),
                origin=previous.ORIGIN,
            )
            ctx = self.context(self.keys.verify(rotated.secret))
            self.assertEqual(self.ledger.reserve(ctx, req), receipt)
            self.error(lambda: self.ledger.reserve(ctx, self.req(slots=0)), 402)
        self.assertEqual(self.budget("api")["spent"], 1)

    def test_downgrade_reduces_cap_without_resetting_spent(self):
        req = self.req(slots=0)
        self.ledger.reserve(self.api, req)
        with self.access.transaction() as tx:
            a = tx.accounts.get(self.account.account_id)
            tx.accounts.update(
                a.account_id, expected_version=a.entitlement_version, plan="starter"
            )
        caps = PLAN_DEFINITIONS[PlanName.STARTER].model_copy(
            update={"max_api_calls_per_month": 1}
        )
        with patch.dict(PLAN_DEFINITIONS, {PlanName.STARTER: caps}):
            self.error(lambda: self.ledger.reserve(self.api, self.req(slots=0)), 402)
        self.assertEqual(self.budget("api")["spent"], 1)

    def test_pause_and_expiry_block_admission_but_never_refund(self):
        r = self.ledger.reserve(self.api, self.req(cu=4))
        self.policy.set_status(
            self.account.account_id,
            expected_version=1,
            status="paused",
            reason="test pause",
        )
        self.error(
            lambda: self.ledger.start(self.api, r.reservation_id, expected_version=1),
            403,
        )
        self.error(lambda: self.ledger.reserve(self.api, self.req()), 403)
        self.assertEqual(self.budget("cu")["reserved"], 4)

    def test_foreign_account_receipt_and_claim_are_not_authority(self):
        r = self.ledger.reserve(self.api, self.req())
        client = self.client(account=self.other)
        ctx = self.context(self.auth.verify(client.cookies.get("__Host-cisstat_auth")))
        self.error(lambda: self.ledger.get(ctx, r.reservation_id), 404)
        self.error(
            lambda: self.ledger.reserve(
                replace(ctx, tenant_id=self.ctx.tenant_id),
                self.req(entry="api:GET:/v1/internal/rules/templates"),
            ),
            403,
        )

    def test_same_run_concurrency_claim_charged_once(self):
        result = self.race(
            lambda i: self.ledger.reserve(
                self.ctx,
                self.req(entry="api:POST:/v1/internal/upload", run="RUN-SAME", slots=0),
            )
        )
        self.assertTrue(all(not isinstance(r, int) for r in result), result)
        self.assertEqual(self.budget("analysis")["spent"], 1)

    def test_scope_binding_invalid_parent_and_no_null_infinity(self):
        from apps.api.authentication.errors import RepositoryConflict

        with self.assertRaises(RepositoryConflict):
            self.policy.create_scope(
                "grant",
                account_id=self.other.account_id,
                ends_at=datetime.now(UTC) + timedelta(hours=1),
                reason="invalid parent",
            )
        with self.assertRaises(ValueError):
            self.policy.set_budget(
                self.account.account_id, "cu", limit_units=None, reason="invalid limit"
            )
        with self.assertRaises(RepositoryConflict), self.access.transaction() as tx:
            tx.connection.execute(
                "UPDATE auth_budget_scopes SET parent_id=%s,version=version+1 WHERE scope_id=%s",
                (uuid4(), self.account.account_id),
            )

    def test_migration_retry_checksum_trigger_drift(self):
        with self.access.transaction() as tx:
            self.assertFalse(apply_migration(tx.connection))
        with self.access.transaction() as tx:
            tx.connection.execute(
                "ALTER TABLE auth_usage_postings DISABLE TRIGGER auth12_postings_immutable"
            )
        self.error(lambda: self.ledger.reserve(self.api, self.req()), 503)

    def test_fresh_process_ledger_persists(self):
        import subprocess
        import sys

        self.ledger.reserve(self.api, self.req(cu=4))
        script = "import os; from apps.api.billing.coordinator import ReservationCoordinator; from apps.api.authentication.storage import PostgresAccessStore; s=PostgresAccessStore(os.environ['CISSTAT_AUTH_DATABASE_URL'],schema=os.environ['AUTH12_SCHEMA']); assert ReservationCoordinator(s).readiness()['ok'];\nwith s.transaction(readonly=True) as t: assert t.connection.execute('SELECT sum(reserved) AS n FROM auth_resource_budgets').fetchone()['n']==5"
        result = subprocess.run(
            [sys.executable, "-c", script],
            env={
                **os.environ,
                "CISSTAT_AUTH_DATABASE_URL": self.dsn,
                "AUTH12_SCHEMA": self.schema,
            },
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_last_concurrency_slot_race(self):
        self.policy.set_budget(
            self.account.account_id,
            "concurrency",
            limit_units=1,
            expected_version=1,
            reason="last slot",
        )
        result = self.race(lambda i: self.ledger.reserve(self.api, self.req()))
        self.assertEqual(sum(not isinstance(r, int) for r in result), 1, result)
        self.assertIn(429, result)

    def test_failed_extension_cannot_change_held_or_postings(self):
        r = self.ledger.reserve(self.api, self.req(cu=3))
        r = self.ledger.start(self.api, r.reservation_id, expected_version=1)
        before = self.rows("auth_usage_postings")
        self.error(
            lambda: self.ledger.extend(
                self.api, r.reservation_id, expected_version=r.version, additional_cu=8
            ),
            402,
        )
        self.assertEqual(self.rows("auth_usage_postings"), before)
        self.assertEqual(self.ledger.get(self.api, r.reservation_id), r)

    def test_overflow_never_wraps_or_partially_commits(self):
        self.policy.set_budget(
            self.account.account_id,
            "cu",
            limit_units=2**63 - 1,
            expected_version=1,
            reason="overflow oracle",
        )
        r = self.ledger.reserve(self.api, self.req(cu=2**63 - 1))
        r = self.ledger.start(self.api, r.reservation_id, expected_version=1)
        self.error(
            lambda: self.ledger.extend(
                self.api, r.reservation_id, expected_version=r.version, additional_cu=1
            ),
            409,
            "budget_overflow",
        )
        self.assertEqual(self.budget("cu")["reserved"], 2**63 - 1)

    def test_unknown_entry_and_custom_model_current_caps_deny(self):
        self.error(
            lambda: self.ledger.reserve(
                self.api, self.req(entry="api:POST:/v1/public/not-reviewed")
            ),
            403,
        )
        from apps.api.access_registry import ModelWorkload

        with self.access.transaction() as tx:
            a = tx.accounts.get(self.account.account_id)
            tx.accounts.update(
                a.account_id, expected_version=a.entitlement_version, plan="starter"
            )
        req = self.req(entry="api:POST:/v1/models/backtest").model_copy(
            update={
                "workload": ModelWorkload(
                    model_ids=("ets",),
                    rows=80,
                    folds=2,
                    horizon=12,
                    seasonal_period=12,
                    custom_parameters=False,
                )
            }
        )
        self.error(lambda: self.ledger.reserve(self.api, req), 402)
        self.assertEqual(self.rows("auth_reservations"), [])

    def test_payload_and_idempotency_plaintext_not_saved(self):
        marker = "unique-sensitive-native12-value"
        self.ledger.reserve(
            self.api, self.req(marker, payload={"sql_password": marker})
        )
        text = str(
            self.rows("auth_reservations")
            + self.rows("auth_job_outbox")
            + self.rows("auth_audit_outbox")
        )
        self.assertNotIn(marker, text)

    def test_utc_month_rollover_keeps_old_postings_and_retry(self):
        from apps.api.billing.coordinator import ReservationCoordinator as C

        long_key = self.keys.issue(
            self.token,
            IssueKeyBody(label="rollover", scopes=["api.read"], expires_in_days=90),
            origin=previous.ORIGIN,
        )
        ctx = self.context(self.keys.verify(long_key.secret))
        req = self.req("month-stable", slots=0)
        first = self.ledger.reserve(ctx, req)
        next_month = (datetime.now(UTC).replace(day=1) + timedelta(days=32)).replace(
            day=1
        )
        with patch.object(C, "_now", return_value=next_month):
            self.assertEqual(self.ledger.reserve(ctx, req), first)
            self.ledger.reserve(
                ctx, self.req(slots=0, deadline=next_month + timedelta(minutes=10))
            )
        buckets = [
            b for b in self.rows("auth_resource_budgets") if b["metric"] == "api"
        ]
        self.assertEqual(len(buckets), 2)
        self.assertEqual(sum(b["spent"] for b in buckets), 2)

    def test_membership_revoke_deny_new_and_start(self):
        from apps.api.accounts.lifecycle import AccountLifecycle

        client = self.client(member=True)
        ctx = self.context(self.auth.verify(client.cookies.get("__Host-cisstat_auth")))
        req = self.req(cu=2, entry="api:GET:/v1/internal/rules/templates")
        r = self.ledger.reserve(ctx, req)
        with self.access.transaction() as tx:
            a = tx.accounts.get(self.account.account_id)
        AccountLifecycle(self.access).membership(
            a.account_id,
            self.member.subject_id,
            expected_version=a.entitlement_version,
            status="revoked",
            reason="revoke oracle",
        )
        self.error(
            lambda: self.ledger.start(ctx, r.reservation_id, expected_version=1), 403
        )
        self.error(lambda: self.ledger.reserve(ctx, req), 403)
        self.assertEqual(self.budget("cu")["reserved"], 2)

    def test_expired_account_cannot_reserve(self):
        from apps.api.accounts.lifecycle import AccountChange, AccountLifecycle

        with self.access.transaction() as tx:
            a = tx.accounts.get(self.account.account_id)
        AccountLifecycle(self.access).change(
            a.account_id,
            expected_version=a.entitlement_version,
            change=AccountChange(
                plan_expires_at=datetime.now(UTC) - timedelta(seconds=1)
            ),
            reason="expiry oracle",
        )
        self.error(
            lambda: self.ledger.reserve(self.api, self.req()), 403, "account_expired"
        )
        self.assertEqual(self.rows("auth_reservations"), [])

    def test_paused_running_reservation_cannot_extend(self):
        r = self.ledger.reserve(self.api, self.req(cu=2))
        r = self.ledger.start(self.api, r.reservation_id, expected_version=1)
        self.policy.set_status(
            self.account.account_id,
            expected_version=1,
            status="paused",
            reason="pause extension",
        )
        self.error(
            lambda: self.ledger.extend(
                self.api, r.reservation_id, expected_version=r.version, additional_cu=1
            ),
            403,
        )
        self.assertEqual(self.budget("cu")["reserved"], 2)

    def test_migration_cli_apply_retry_and_check_clean_database(self):
        import subprocess
        import sys
        from pathlib import Path

        from psycopg.conninfo import make_conninfo

        db = "auth12_cli_" + uuid4().hex
        dsn = os.environ["CISSTAT_AUTH_TEST_DSN"]
        with self.pg.connect(dsn, autocommit=True) as c:
            c.execute(
                self.sql.SQL("CREATE DATABASE {}").format(self.sql.Identifier(db))
            )
        try:
            results = []
            for option in ("--apply", "--apply", "--check"):
                r = subprocess.run(
                    [sys.executable, "scripts/auth12/migrate.py", option],
                    cwd=Path(__file__).resolve().parents[2],
                    env={
                        **os.environ,
                        "CISSTAT_AUTH_DATABASE_URL": make_conninfo(dsn, dbname=db),
                    },
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                results.append(r.stdout)
            self.assertIn('"applied": true', results[0])
            self.assertIn('"applied": false', results[1])
        finally:
            with self.pg.connect(dsn, autocommit=True) as c:
                c.execute(
                    self.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        self.sql.Identifier(db)
                    )
                )

    def test_settle_audit_failure_keeps_reserve_and_running_state(self):
        r = self.ledger.reserve(self.api, self.req(cu=4))
        r = self.ledger.start(self.api, r.reservation_id, expected_version=1)
        before = self.rows("auth_usage_postings")
        with self.access.transaction() as tx:
            tx.connection.execute(
                "CREATE FUNCTION settle_fault12() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.payload->>'action'='auth_reservation_changed' THEN RAISE EXCEPTION 'intent fault' USING ERRCODE='23514'; END IF; RETURN NEW; END $$"
            )
            tx.connection.execute(
                "CREATE TRIGGER settle_fault12 BEFORE INSERT ON auth_audit_outbox FOR EACH ROW EXECUTE FUNCTION settle_fault12()"
            )
        self.error(
            lambda: self.ledger.settle(
                r.reservation_id, expected_version=r.version, actual_cu=3
            ),
            503,
        )
        self.assertEqual(self.ledger.get(self.api, r.reservation_id), r)
        self.assertEqual(self.rows("auth_usage_postings"), before)
        self.assertEqual(
            (self.budget("cu")["reserved"], self.budget("cu")["spent"]), (4, 0)
        )

    def test_budget_policy_audit_failure_keeps_limit_and_version(self):
        before = self.budget("cu")
        with self.access.transaction() as tx:
            tx.connection.execute(
                "CREATE FUNCTION policy_fault12() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.payload->>'action'='auth_budget_changed' THEN RAISE EXCEPTION 'intent fault' USING ERRCODE='23514'; END IF; RETURN NEW; END $$"
            )
            tx.connection.execute(
                "CREATE TRIGGER policy_fault12 BEFORE INSERT ON auth_audit_outbox FOR EACH ROW EXECUTE FUNCTION policy_fault12()"
            )
        from apps.api.authentication.errors import RepositoryConflict

        with self.assertRaises(RepositoryConflict):
            self.policy.set_budget(
                self.account.account_id,
                "cu",
                limit_units=50,
                expected_version=before["version"],
                reason="policy rollback oracle",
            )
        self.assertEqual(self.budget("cu"), before)
