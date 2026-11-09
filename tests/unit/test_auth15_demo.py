import unittest
from datetime import datetime, timedelta, timezone
from pydantic import ValidationError
from apps.api.authentication.demo import CampaignPolicy, effective_status


class DemoContracts(unittest.TestCase):
    def policy(self, **kw):
        now = datetime.now(timezone.utc)
        return dict(
            starts_at=now,
            ends_at=now + timedelta(hours=2),
            grant_minutes=60,
            max_grants=20,
            campaign_cu=1000,
            participant_cu=100,
            campaign_concurrency=3,
            participant_concurrency=1,
            campaign_analyses=40,
            participant_analyses=2,
            max_rows=1000,
            allowed_origins=["https://datasetup.ru"],
            **kw,
        )

    def test_required_finite_policy(self):
        data = self.policy()
        for key in (
            "max_grants",
            "campaign_cu",
            "participant_cu",
            "campaign_concurrency",
            "participant_analyses",
        ):
            for value in (None, -1, True, 1.5):
                with (
                    self.subTest(key=key, value=value),
                    self.assertRaises(ValidationError),
                ):
                    CampaignPolicy(**{**data, key: value})

    def test_no_infinite_or_inverted_time(self):
        data = self.policy()
        for changes in (
            {"ends_at": data["starts_at"]},
            {"ends_at": None},
            {"allowed_origins": []},
            {"max_rows": 5001},
        ):
            with self.assertRaises(ValidationError):
                CampaignPolicy(**{**data, **changes})

    def test_half_open_and_pause(self):
        p = CampaignPolicy(**self.policy())
        self.assertEqual(effective_status("active", p, p.ends_at), "expired")
        self.assertEqual(effective_status("paused", p, p.starts_at), "paused")
        self.assertEqual(
            effective_status("active", p, p.starts_at - timedelta(seconds=1)),
            "scheduled",
        )

    def test_own_upload_default_off(self):
        self.assertFalse(CampaignPolicy(**self.policy()).allow_upload)

    def test_resume_secret_redacted(self):
        from apps.api.telemetry import redact_text as redact
        from apps.api.storage_diagnostics import safe_error

        token = "d1_" + "x" * 43
        self.assertNotIn(token, redact(token))
        self.assertNotIn(token, safe_error(token))
