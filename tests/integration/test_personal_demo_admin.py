"""Real PostgreSQL notice queue; controlled SMTP only, no real recipients."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from tests.integration import test_personal_demo as personal_fixture


@unittest.skipUnless(os.environ.get("CISSTAT_AUTH_TEST_DSN"), "disposable PostgreSQL required")
class AdminNoticeSQLTests(unittest.TestCase):
    def setUp(self):
        self.f = personal_fixture.PersonalDemoSQLTests("test_migration_and_atomic_new_owner_ready_for_compute")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.store = self.f.store
        from apps.api.authentication.demo_admin_migrations import apply_migration
        with self.store.transaction() as tx:
            apply_migration(tx.connection)
        self.env = patch.dict(os.environ, {"CISSTAT_DEMO_ADMIN_NOTIFICATIONS_ENABLED": "1", "CISSTAT_DEMO_ADMIN_EMAIL": "admin@example.test"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.sent = []
        class Delivery:
            sender = "CISStat <admin@example.test>"
            def send(inner, to, subject, body, **kwargs):
                # This independent connection can lock the claimed queue row:
                # SMTP is outside both enrollment and claim transactions.
                with self.store.transaction() as tx:
                    tx.connection.execute("SELECT * FROM auth_demo_admin_notifications FOR UPDATE NOWAIT").fetchall()
                    self.assertEqual(tx.connection.execute("SELECT count(*) AS n FROM auth_personal_trials").fetchone()["n"], 1)
                self.sent.append((to, subject, body, kwargs))
        self.delivery = Delivery()

    def rows(self):
        return self.f.rows("auth_demo_admin_notifications")

    def publish(self, **kwargs):
        from apps.api.authentication.demo_admin_notifications import publish_pending
        return publish_pending(store=self.store, delivery=self.delivery, **kwargs)

    def test_only_committed_first_grant_queues_safe_notice(self):
        token = self.f.token("new@example.test")
        self.assertFalse(self.rows())
        issued = self.f.consume(token)
        self.f.f.email.verify(issued.token)
        self.assertEqual(len(self.rows()), 1)
        self.f.signup("new@example.test")
        self.assertEqual(len(self.rows()), 1)
        result = self.publish()
        self.assertEqual(result["sent"], 1)
        self.assertEqual(self.publish()["sent"], 0)
        self.assertEqual(len(self.sent), 1)
        to, subject, body, options = self.sent[0]
        self.assertEqual(to, "admin@example.test")
        self.assertIn("new@example.test", body)
        self.assertNotIn(token, body)
        code = self.f.f.delivery.letters[0]["body"].splitlines()[0].rsplit(" ", 1)[-1]
        self.assertNotIn(code, body)
        self.assertNotIn("/login", body)
        self.assertIn(str(self.rows()[0]["notification_id"]), options["message_id"])
        self.assertEqual(self.rows()[0]["status"], "sent")

    def test_mandatory_audit_fault_rolls_back_notice_and_grant(self):
        from apps.api.authentication import personal_demo as P
        token = self.f.token("rollback@example.test")
        with patch.object(P, "audit", side_effect=RuntimeError("private error")):
            self.f.f.error(lambda: self.f.consume(token), 503)
        self.assertFalse(self.rows())
        self.assertFalse(self.f.rows("auth_personal_trials"))
        self.assertEqual(self.publish()["sent"], 0)
        self.f.consume(token)
        self.assertEqual(len(self.rows()), 1)

    def test_smtp_outage_does_not_affect_login_and_is_retried(self):
        from apps.api.authentication.providers.email_delivery import DeliveryUnavailable
        issued = self.f.signup()
        self.f.f.email.verify(issued.token)
        with patch.object(self.delivery, "send", side_effect=DeliveryUnavailable("secret SMTP response")):
            self.assertEqual(self.publish()["sent"], 0)
        self.assertEqual(self.rows()[0]["status"], "pending")
        self.assertEqual(self.rows()[0]["last_error_code"], "smtp_unavailable")
        self.assertEqual(self.publish()["sent"], 0)
        with self.store.transaction() as tx:
            tx.connection.execute("UPDATE auth_demo_admin_notifications SET next_attempt_at=clock_timestamp()")
        self.assertEqual(self.publish()["sent"], 1)
        self.assertEqual(self.rows()[0]["attempts"], 2)

    def test_two_publishers_do_not_send_same_claim(self):
        self.f.signup()
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(lambda _: self.publish(), range(2)))
        self.assertEqual(sum(x["sent"] for x in result), 1)
        self.assertEqual(len(self.sent), 1)

    def test_expired_claim_recovers_and_stale_ack_cannot_overwrite(self):
        from apps.api.authentication.demo_admin_notifications import claim, complete
        self.f.signup()
        old = claim(self.store, "admin@example.test")
        self.assertEqual(self.publish()["sent"], 0)
        with self.store.transaction() as tx:
            tx.connection.execute("UPDATE auth_demo_admin_notifications SET lease_until=clock_timestamp()-interval '1 second'")
        self.assertEqual(self.publish()["sent"], 1)
        self.assertFalse(complete(self.store, old, sent=False))
        self.assertEqual(self.rows()[0]["status"], "sent")

    def test_disabled_enrollment_does_not_backfill_prior_trials(self):
        with patch.dict(os.environ, {"CISSTAT_DEMO_ADMIN_NOTIFICATIONS_ENABLED": "0"}):
            self.f.signup()
        self.assertFalse(self.rows())
        self.f.signup()
        self.assertFalse(self.rows())

    def test_environment_factory_is_used_without_injected_store(self):
        from apps.api.authentication.demo_admin_notifications import publish_pending
        from apps.api.authentication.storage import PostgresAccessStore
        self.f.signup()
        with patch.object(PostgresAccessStore, "from_env", return_value=self.store):
            self.assertEqual(publish_pending(delivery=self.delivery)["sent"], 1)

    def test_migration_is_idempotent_and_payload_is_immutable(self):
        from apps.api.authentication.demo_admin_migrations import apply_migration, check_schema
        with self.store.transaction() as tx:
            self.assertFalse(apply_migration(tx.connection))
            check_schema(tx.connection)
        self.f.signup()
        from apps.api.authentication.errors import RepositoryConflict
        with self.assertRaises(RepositoryConflict):
            with self.store.transaction() as tx:
                tx.connection.execute("UPDATE auth_demo_admin_notifications SET user_email='other@example.test'")
        self.assertEqual(self.rows()[0]["user_email"], "mono@example.test")

    def test_existing_periodic_ops_cycle_delivers_notice(self):
        from apps.api.authentication.ops_sweeper import cycle
        from apps.api.authentication.storage import PostgresAccessStore
        self.f.signup()
        with (
            patch("apps.api.storage_diagnostics.get_storage_mode", return_value="required"),
            patch("apps.api.authentication.ops_service.AuthOpsService") as service,
            patch.object(PostgresAccessStore, "from_env", return_value=self.store),
            patch("apps.api.authentication.providers.email_delivery.SmtpEmailDelivery.from_env", return_value=self.delivery),
            patch.dict(os.environ, {"CISSTAT_AUTH_OPS_LEDGER_RETENTION_DAYS": ""}),
        ):
            service.return_value.drain_audit.return_value = 0
            self.assertEqual(cycle()["demo_admin"]["sent"], 1)
        self.assertEqual(len(self.sent), 1)

    def test_operator_status_contains_counts_without_user_or_proof(self):
        import json
        from apps.api.authentication.demo_admin_notifications import status
        self.f.signup("private-reader@example.test")
        value = status(store=self.store)
        self.assertEqual(value["counts"], {"pending": 1, "sending": 0, "sent": 0})
        self.assertEqual(self.rows()[0]["attempts"], 0)
        self.assertNotIn("private-reader", json.dumps(value))
        self.assertEqual(self.publish()["sent"], 1)
        self.assertEqual(status(store=self.store)["counts"]["sent"], 1)
