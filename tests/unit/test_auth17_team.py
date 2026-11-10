import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from apps.api.accounts.team_contract import (
    Invite,
    SeatRequest,
    invitation_digest,
    normalize_email,
)


class TeamContracts(unittest.TestCase):
    def test_invite_requires_exactly_one_target_and_bounded_expiry(self):
        common = {"expected_version": 2, "reason": "test", "idempotency_key": "k"}
        for extra in (
            {},
            {
                "target_subject_id": "00000000-0000-0000-0000-000000000001",
                "email": "a@example.org",
            },
            {"email": "bad"},
            {"email": 1234},
            {"email": "a@example.org", "ttl_hours": 169},
        ):
            with self.subTest(extra=extra), self.assertRaises(ValidationError):
                Invite(**common, **extra)
        self.assertEqual(Invite(**common, email="A@Example.org").email, "a@example.org")

    def test_finite_versions_seats_and_nonempty_reason(self):
        for field, value in (
            ("seats", True),
            ("seats", 0),
            ("seats", 1001),
            ("expected_version", 0),
            ("reason", " "),
        ):
            with (
                self.subTest(field=field, value=value),
                self.assertRaises(ValidationError),
            ):
                SeatRequest(
                    **(
                        {
                            "expected_version": 2,
                            "reason": "test",
                            "idempotency_key": "k",
                            "seats": 2,
                        }
                        | {field: value}
                    )
                )

    def test_invitation_domain_hash_and_no_secret_repr(self):
        self.assertEqual(len(invitation_digest("i17_" + "x" * 43)), 64)
        for value in (None, "", "i17_x"):
            with self.assertRaises(HTTPException):
                invitation_digest(value)
        self.assertEqual(normalize_email(" User@Example.ORG "), "user@example.org")

    def test_invitation_is_redacted_and_secret_body_repr_is_safe(self):
        from apps.api.accounts.team_contract import Accept
        from apps.api.telemetry import redact_text

        token = "i17_" + "x" * 43
        body = Accept(invitation_token=token, idempotency_key="native")
        self.assertNotIn(token, repr(body))
        self.assertNotIn(token, redact_text("invitation " + token))
