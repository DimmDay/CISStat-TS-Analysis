import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from apps.api.authentication.demo_lifecycle import LifecyclePolicy, admission_digest


class LifecycleContracts(unittest.TestCase):
    def test_code_format_and_domain_hash(self):
        code = "a16_" + "x" * 43
        self.assertEqual(len(admission_digest(code)), 64)
        self.assertNotIn(code, admission_digest(code))
        for bad in ("", None, "a16_x"):
            with self.assertRaises(HTTPException):
                admission_digest(bad)

    def test_finite_limits(self):
        for field in (
            "participant_requests",
            "campaign_requests",
            "max_upload_bytes",
            "retention_hours",
        ):
            for value in (None, -1, True, 1.5):
                with (
                    self.subTest(field=field, value=value),
                    self.assertRaises(ValidationError),
                ):
                    LifecyclePolicy(**{field: value})
