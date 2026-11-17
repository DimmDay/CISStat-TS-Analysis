"""Admin-only email projection: no credentials or customer-facing effects."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import patch


class AdminNoticeContractTests(unittest.TestCase):
    def test_notice_contains_actual_limits_and_moscow_time_without_login_proof(self):
        from apps.api.authentication.demo_admin_notifications import letter, SUBJECT
        now = datetime(2026, 11, 17, 12, 30, tzinfo=timezone.utc)
        body = letter({"user_email": "new@example.test", "issued_at": now,
                       "expires_at": now + timedelta(days=14), "micro_cu": 100000000,
                       "analyses": 10, "concurrency": 1, "max_rows": 50000})
        self.assertEqual(SUBJECT, "Новый пользователь подтвердил email и получил демо-доступ")
        for value in ("new@example.test", "17.11.2026 15:30", "МСК", "100 CU", "10", "50000", "01.12.2026"):
            self.assertIn(value, body)
        for value in ("email_challenge", "e1_", "код подтверждения", "https://", "/login"):
            self.assertNotIn(value, body.lower())

    def test_disabled_publisher_does_not_touch_authority_or_smtp(self):
        from apps.api.authentication.demo_admin_notifications import publish_pending
        with patch.dict(os.environ, {"CISSTAT_DEMO_ADMIN_NOTIFICATIONS_ENABLED": "0"}), patch(
            "apps.api.authentication.storage.PostgresAccessStore.from_env"
        ) as store:
            self.assertEqual(publish_pending(), {"enabled": False, "sent": 0})
            store.assert_not_called()

    def test_invalid_recipient_is_rejected_without_header_injection(self):
        from apps.api.authentication.demo_admin_notifications import recipient
        for value in ("a@example.test,b@example.test", "a@example.test\r\nBcc:b@example.test", ""):
            with self.subTest(value=value), patch.dict(os.environ, {"CISSTAT_DEMO_ADMIN_EMAIL": value}):
                with self.assertRaises(ValueError):
                    recipient()

    def test_smtp_preserves_stable_notification_message_id(self):
        from apps.api.authentication.providers.email_delivery import SmtpEmailDelivery
        mid = f"<demo-admin.{uuid4()}@example.test>"
        with patch("smtplib.SMTP_SSL") as smtp:
            SmtpEmailDelivery(host="smtp.example.test", sender="admin@example.test", mode="ssl").send(
                "admin@example.test", "Test notice", "No proof", message_id=mid)
            self.assertEqual(str(smtp.return_value.send_message.call_args.args[0]["Message-ID"]), mid)

    def test_compose_enables_admin_delivery_only_in_api(self):
        import yaml
        from pathlib import Path
        data = yaml.safe_load((Path(__file__).resolve().parents[2] / "deployment/cisstat-stack/docker-compose.yml").read_text(encoding="utf-8"))
        for name in ("CISSTAT_DEMO_ADMIN_NOTIFICATIONS_ENABLED", "CISSTAT_DEMO_ADMIN_EMAIL"):
            self.assertIn(name, data["services"]["api"]["environment"])
            self.assertNotIn(name, str(data["services"]["web"]))

    def test_notification_failure_does_not_block_audit_or_log_private_error(self):
        from apps.api.authentication.ops_sweeper import cycle
        with (
            patch("apps.api.storage_diagnostics.get_storage_mode", return_value="required"),
            patch("apps.api.authentication.ops_service.AuthOpsService") as service,
            patch.dict(os.environ, {"CISSTAT_AUTH_OPS_LEDGER_RETENTION_DAYS": ""}),
            patch("apps.api.authentication.demo_admin_notifications.publish_pending", side_effect=RuntimeError("secret@example.test/password")),
        ):
            service.return_value.drain_audit.return_value = 7
            with self.assertLogs("apps.api.authentication.ops_sweeper", level="WARNING") as logs:
                result = cycle()
            self.assertEqual(result["demo_admin"], {"error": "notification_unavailable"})
            self.assertEqual(result["delivered"], 7)
            service.return_value.drain_audit.assert_called_once_with(limit=100)
            self.assertNotIn("secret", " ".join(logs.output))
