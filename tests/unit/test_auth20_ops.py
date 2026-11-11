"""AUTH-20 contracts without PostgreSQL: lockdown, marks validation,
audit catalog, sweeper bounds, health shape. Real SQL flows live in
tests/integration/test_auth20_reconciliation.py."""

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from apps.api.authentication.context import auth_error
from apps.api.authentication.lockdown import LOCKDOWN_ENV, assert_open, engaged
from apps.api.authentication.ops_service import (
    LEDGER_RETENTION_DEFAULT_DAYS,
    LEDGER_RETENTION_MIN_DAYS,
    MARKS_FORMAT,
    AuthOpsService,
    parse_retention_days,
)
from apps.api.authentication.ops_sweeper import (
    DEFAULT_INTERVAL,
    INTERVAL_ENV,
    interval_seconds,
)
from apps.api.security_audit import AUDIT_ACTIONS, AUDIT_REQUIREMENTS

PASS = "correct horse battery staple 42!"
ORIGIN = "https://datasetup.ru"


def _marks(entries):
    return {
        "format": MARKS_FORMAT,
        "exported_at": "2026-11-11T10:00:00+00:00",
        "entries": entries,
    }


class LockdownSwitchTests(unittest.TestCase):
    """Safe rollback kill-switch: fail-closed on unknown values."""

    def test_off_values(self):
        for value in (None, "", "0"):
            self.assertFalse(engaged(value))

    def test_unknown_value_fails_closed(self):
        for value in ("1", "true", "yes", "off", " 0", "0 ", "O"):
            self.assertTrue(engaged(value))

    def test_assert_open_raises_safe_code(self):
        with self.assertRaises(HTTPException) as raised:
            assert_open("1")
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.detail["code"], "auth_lockdown")

    def test_assert_open_passes_when_off(self):
        assert_open("0")
        assert_open(None)

    def test_env_reading(self):
        with patch.dict(os.environ, {LOCKDOWN_ENV: "1"}):
            self.assertTrue(engaged())
        with patch.dict(os.environ, {LOCKDOWN_ENV: "0"}):
            self.assertFalse(engaged())
        with patch.dict(os.environ, {LOCKDOWN_ENV: ""}):
            self.assertFalse(engaged())


class RetentionAndSweeperBoundsTests(unittest.TestCase):
    def test_retention_defaults_and_minimum(self):
        self.assertEqual(parse_retention_days(None), LEDGER_RETENTION_DEFAULT_DAYS)
        self.assertEqual(parse_retention_days("90"), 90)
        self.assertEqual(parse_retention_days("3"), LEDGER_RETENTION_MIN_DAYS)
        self.assertEqual(parse_retention_days("garbage"), LEDGER_RETENTION_DEFAULT_DAYS)
        self.assertGreaterEqual(LEDGER_RETENTION_MIN_DAYS, 7)

    def test_sweeper_interval_bounds(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(INTERVAL_ENV, None)
            self.assertEqual(interval_seconds(), DEFAULT_INTERVAL)
        with patch.dict(os.environ, {INTERVAL_ENV: "0"}):
            self.assertEqual(interval_seconds(), 0)
        with patch.dict(os.environ, {INTERVAL_ENV: "10"}):
            self.assertEqual(interval_seconds(), 10)
        with patch.dict(os.environ, {INTERVAL_ENV: "2"}):
            self.assertGreaterEqual(interval_seconds(), 5)
        with patch.dict(os.environ, {INTERVAL_ENV: "99999"}):
            self.assertLessEqual(interval_seconds(), 3600)
        with patch.dict(os.environ, {INTERVAL_ENV: "nonsense"}):
            self.assertEqual(interval_seconds(), DEFAULT_INTERVAL)


class AuditCatalogTests(unittest.TestCase):
    """AUTH-20 extends the mandatory catalog by exactly one ops action."""

    def test_auth_ops_changed_is_mandatory(self):
        self.assertIn("auth_ops_changed", AUDIT_ACTIONS)
        self.assertEqual(AUDIT_REQUIREMENTS.get("auth_ops_changed"), "mandatory")

    def test_catalog_size_42(self):
        self.assertEqual(len(AUDIT_ACTIONS), 42)
        mandatory = {k for k, v in AUDIT_REQUIREMENTS.items() if v == "mandatory"}
        self.assertIn("auth_ops_changed", mandatory)


class MarksValidationTests(unittest.TestCase):
    def _entry(self, **changes):
        entry = {
            "entry_id": 1,
            "table": "auth_api_keys",
            "event": "revoked",
            "row_id": "1b671a64-40d5-491e-99b0-da01ff1f3341",
            "occurred_at": "2026-11-11T10:00:00+00:00",
            "row_image": {"key_id": "1b671a64-40d5-491e-99b0-da01ff1f3341"},
        }
        entry.update(changes)
        return entry

    def test_valid_document_passes(self):
        parsed = AuthOpsService.validate_marks(_marks([self._entry()]))
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["table"], "auth_api_keys")

    def test_unknown_format_rejected(self):
        with self.assertRaises(ValueError):
            AuthOpsService.validate_marks({"format": "other/1", "entries": []})

    def test_unreconcilable_pair_rejected(self):
        with self.assertRaises(ValueError):
            AuthOpsService.validate_marks(
                _marks([self._entry(table="auth_identities", event="revoked")])
            )

    def test_non_terminal_event_rejected(self):
        with self.assertRaises(ValueError):
            AuthOpsService.validate_marks(
                _marks([self._entry(table="auth_reservations", event="running")])
            )

    def test_bad_uuid_rejected(self):
        with self.assertRaises(ValueError):
            AuthOpsService.validate_marks(_marks([self._entry(row_id="not-a-uuid")]))

    def test_bad_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            AuthOpsService.validate_marks(_marks([self._entry(occurred_at="yesterday")]))

    def test_missing_row_image_rejected(self):
        with self.assertRaises(ValueError):
            AuthOpsService.validate_marks(_marks([self._entry(row_image=None)]))

    def test_oversize_rejected(self):
        import apps.api.authentication.ops_service as ops_module

        with patch.object(ops_module, "MARKS_MAX_ENTRIES", 3):
            with self.assertRaises(ValueError):
                ops_module.AuthOpsService.validate_marks(_marks([self._entry()] * 4))


if __name__ == "__main__":
    unittest.main()
