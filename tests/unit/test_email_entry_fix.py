"""Email envelope interoperability and secret-free authority diagnostics."""

import unittest
from email.utils import parsedate_to_datetime
from unittest.mock import patch

from apps.api.authentication.context import AuthHTTPException
from apps.api.authentication.providers.email_delivery import SmtpEmailDelivery
from apps.api.authentication.sessions import boundary


class EmailEntryFixTests(unittest.TestCase):
    def test_complete_unique_headers_on_both_tls_transports(self):
        ids = set()
        for mode, factory in (("starttls", "smtplib.SMTP"), ("ssl", "smtplib.SMTP_SSL")):
            with self.subTest(mode=mode), patch(factory) as smtp:
                delivery = SmtpEmailDelivery(
                    host="smtp.example.test", sender="CISStat <admin@example.test>", mode=mode
                )
                for _ in range(2):
                    delivery.send("reader@example.net", "Подтверждение входа", "Тестовое письмо")
                    message = smtp.return_value.send_message.call_args.args[0]
                    self.assertIsNotNone(message["Date"])
                    self.assertIsNotNone(parsedate_to_datetime(str(message["Date"])).tzinfo)
                    message_id = str(message["Message-ID"])
                    self.assertRegex(message_id, r"^<[^<>\s@]+@example\.test>$")
                    self.assertNotIn(message_id, ids)
                    ids.add(message_id)
                    self.assertEqual(str(message["To"]), "reader@example.net")
                    self.assertIn("Тестовое письмо", message.get_content())

    def test_authority_failure_logs_category_without_exception_or_credentials(self):
        @boundary
        def consume():
            raise RuntimeError("SECRET token=e1_private smtp-password db-dsn")

        with self.assertLogs("apps.api.authentication.sessions", level="WARNING") as logs:
            with self.assertRaises(AuthHTTPException) as caught:
                consume()
        self.assertEqual(caught.exception.status_code, 503)
        output = "\n".join(logs.output)
        self.assertIn("consume", output)
        self.assertIn("RuntimeError", output)
        for secret in ("SECRET", "e1_private", "smtp-password", "db-dsn"):
            self.assertNotIn(secret, output)

    def test_expected_denial_is_not_reclassified_or_logged_as_outage(self):
        from apps.api.authentication.context import auth_error

        @boundary
        def consume():
            auth_error(401, "invalid_credential")

        with self.assertNoLogs("apps.api.authentication.sessions", level="WARNING"):
            with self.assertRaises(AuthHTTPException) as caught:
                consume()
        self.assertEqual(caught.exception.status_code, 401)
