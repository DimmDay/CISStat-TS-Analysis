import unittest

from apps.api.authentication.personal_demo import PROFILE, metadata


class PersonalDemoContractTests(unittest.TestCase):
    def test_finite_integer_recommendation(self):
        self.assertEqual(PROFILE["days"], 14)
        self.assertEqual(PROFILE["micro_cu"], 100000000)
        self.assertEqual(PROFILE["analyses"], 10)
        self.assertEqual(PROFILE["concurrency"], 1)

    def test_disabled_metadata_honest_without_store(self):
        from unittest.mock import patch

        with patch.dict("os.environ", {"CISSTAT_PERSONAL_DEMO_ENABLED": "0"}):
            self.assertFalse(metadata()["available"])


class SmtpContractTests(unittest.TestCase):
    def test_smtp_requires_sender_and_valid_port_before_advertising_signup(self):
        import os
        from unittest.mock import patch

        from apps.api.authentication.email_challenges import email_configured

        env = {
            "CISSTAT_AUTH_EMAIL_KEY": "test-only-key-0123456789abcdef0123456789",
            "CISSTAT_AUTH_SMTP_HOST": "smtp.example.test",
            "CISSTAT_AUTH_SMTP_FROM": "",
            "CISSTAT_AUTH_SMTP_PORT": "587",
        }
        with patch.dict(os.environ, env):
            self.assertFalse(email_configured())
            os.environ["CISSTAT_AUTH_SMTP_FROM"] = "CISStat <demo@example.test>"
            self.assertTrue(email_configured())
            os.environ["CISSTAT_AUTH_SMTP_PORT"] = "70000"
            self.assertFalse(email_configured())

    def test_tls_transport_verifies_certificate_and_preserves_unicode(self):
        import ssl
        from unittest.mock import patch

        from apps.api.authentication.providers.email_delivery import SmtpEmailDelivery

        for mode in ("starttls", "ssl"):
            with (
                self.subTest(mode=mode),
                patch("smtplib.SMTP") as smtp,
                patch("smtplib.SMTP_SSL") as secure,
            ):
                SmtpEmailDelivery(
                    host="smtp.example.test",
                    sender="demo@example.test",
                    user="user",
                    password="test-only",
                    mode=mode,
                ).send("me@example.test", "Проверка", "Текст письма")
                factory = secure if mode == "ssl" else smtp
                client = factory.return_value
                context = (
                    factory.call_args.kwargs["context"]
                    if mode == "ssl"
                    else client.starttls.call_args.kwargs["context"]
                )
                self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                self.assertTrue(context.check_hostname)
                client.login.assert_called_once_with("user", "test-only")
                self.assertIn(
                    "Текст письма", client.send_message.call_args.args[0].get_content()
                )

    def test_compose_forwards_secrets_without_values_or_web_exposure(self):
        from pathlib import Path

        import yaml

        root = Path(__file__).resolve().parents[2]
        data = yaml.safe_load(
            (root / "deployment/cisstat-stack/docker-compose.yml").read_text(
                encoding="utf-8-sig"
            )
        )
        env = data["services"]["api"]["environment"]
        for key in (
            "CISSTAT_AUTH_EMAIL_KEY",
            "CISSTAT_AUTH_SMTP_HOST",
            "CISSTAT_AUTH_SMTP_PORT",
            "CISSTAT_AUTH_SMTP_USER",
            "CISSTAT_AUTH_SMTP_PASSWORD",
            "CISSTAT_AUTH_SMTP_FROM",
            "CISSTAT_AUTH_SMTP_TLS",
            "CISSTAT_PERSONAL_DEMO_ENABLED",
        ):
            self.assertIn("${" + key, env[key])
            self.assertNotIn(key, str(data["services"]["web"]))
